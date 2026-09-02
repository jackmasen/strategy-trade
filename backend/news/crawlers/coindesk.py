"""
媒体爬虫 1/3：加密货币媒体（CoinDesk / CoinTelegraph）
优先 RSS（合法且稳定），RSS 失败时退化到 sitemap/公开 API。
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from typing import List, Optional

from backend.core.logging_config import logger
from backend.models.analytics import NewsArticle
from ..base import NewsCrawlerBase, RawNews


# ========== 共享：RSS 解析（避免引入 feedparser 依赖，手动兼容 Atom/RSS 2.0）==========
def _parse_rss_feed(xml_text: str, limit: int = 50) -> List[dict]:
    """
    极轻量 RSS/Atom 解析器，只取：title/link/description/pubDate/content
    返回 dict 列表，不去重。
    """
    items: List[dict] = []
    if not xml_text:
        return items
    # 1) RSS 2.0 <item>
    for m in re.finditer(r"<item>([\s\S]*?)</item>", xml_text, flags=re.I):
        block = m.group(1)
        item = {
            "title": _extract_xml(block, "title"),
            "link": _extract_xml(block, "link"),
            "description": _extract_xml(block, "description"),
            "content": _extract_xml(block, "content:encoded") or _extract_xml(block, "content"),
            "pubDate": _extract_xml(block, "pubDate") or _extract_xml(block, "dc:date") or _extract_xml(block, "updated"),
            "image": _extract_xml_attr(block, "media:content", "url") or
                     _extract_xml_attr(block, "media:thumbnail", "url") or
                     _extract_xml_attr(block, "enclosure", "url"),
            "author": _extract_xml(block, "dc:creator") or _extract_xml(block, "author"),
        }
        items.append(item)
        if len(items) >= limit:
            return items
    if items:
        return items
    # 2) Atom <entry>
    for m in re.finditer(r"<entry>([\s\S]*?)</entry>", xml_text, flags=re.I):
        block = m.group(1)
        link = _extract_xml_attr(block, "link", "href") or _extract_xml(block, "link")
        item = {
            "title": _extract_xml(block, "title"),
            "link": link,
            "description": _extract_xml(block, "summary") or _extract_xml(block, "description"),
            "content": _extract_xml(block, "content"),
            "pubDate": _extract_xml(block, "updated") or _extract_xml(block, "published"),
            "image": _extract_xml_attr(block, "media:content", "url") or
                     _extract_xml_attr(block, "media:thumbnail", "url"),
            "author": _extract_xml(block, "author/name") or _extract_xml(block, "author"),
        }
        items.append(item)
        if len(items) >= limit:
            return items
    return items


def _strip_html(s: str) -> str:
    if not s:
        return ""
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"\s+", " ", s)
    import html as _h
    return _h.unescape(s).strip()


def _extract_xml(block: str, tag: str) -> str:
    # 匹配 <tag>xxx</tag> 或 <tag ...>xxx</tag>，非贪婪
    pat = rf"<{re.escape(tag)}\b[^>]*>([\s\S]*?)</{re.escape(tag)}>"
    m = re.search(pat, block, flags=re.I)
    if not m:
        return ""
    return _strip_html(m.group(1)).strip()


def _extract_xml_attr(block: str, tag: str, attr: str) -> str:
    pat = rf"<{re.escape(tag)}\b[^>]*{re.escape(attr)}\s*=\s*[\"']([^\"']+)[\"']"
    m = re.search(pat, block, flags=re.I)
    return m.group(1) if m else ""


def _parse_date(s: str) -> Optional[datetime]:
    if not s:
        return None
    s = s.strip()
    # RFC2822（RSS 常用）
    try:
        return parsedate_to_datetime(s).astimezone(timezone.utc).replace(tzinfo=None)
    except Exception:
        pass
    # ISO8601 / Atom
    for fmt in (
        "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%d %H:%M:%S",
    ):
        try:
            dt = datetime.strptime(s, fmt)
            if dt.tzinfo is not None:
                dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
            return dt
        except Exception:
            continue
    return None


# ================= CoinDesk =================
class CoinDeskCrawler(NewsCrawlerBase):
    SOURCE_CODE = NewsArticle.SOURCE_COINDESK
    SOURCE_DISPLAY = "CoinDesk"

    RSS_URLS = [
        "https://www.coindesk.com/arc/outboundfeeds/rss/",          # 综合（加密权威）
        "https://www.coindesk.com/arc/outboundfeeds/markets-rss/",   # 行情（影响币价）
    ]

    def crawl(self, lookback_hours: int = 48) -> List[RawNews]:
        cutoff = datetime.utcnow() - timedelta(hours=lookback_hours)
        seen = set()
        out: List[RawNews] = []
        for rss_url in self.RSS_URLS:
            xml = self._http_get(rss_url)
            if not xml:
                continue
            for item in _parse_rss_feed(xml, limit=40):
                title = item["title"]
                link = item["link"]
                if not title or not link:
                    continue
                # source_id 用 URL md5（CoinDesk RSS 不提供 guid）
                sid = hashlib.md5(link.encode("utf-8")).hexdigest()
                if sid in seen:
                    continue
                seen.add(sid)
                dt = _parse_date(item["pubDate"]) or datetime.utcnow()
                if dt < cutoff:
                    continue
                out.append(RawNews(
                    source_id=sid,
                    source_name=self.SOURCE_DISPLAY,
                    title=title[:300],
                    summary=self._truncate(item["description"], 800),
                    content=self._truncate(item["content"], 4000),
                    url=link,
                    image_url=item["image"],
                    author=self._truncate(item["author"], 80),
                    published_at=dt,
                    category="crypto",
                    tags=["crypto", "bitcoin", "markets"],
                ))
        out.sort(key=lambda x: x.published_at or datetime.utcnow(), reverse=True)
        logger.info(f"[News/{self.SOURCE_DISPLAY}] 抓取 {len(out)} 条")
        return out


# ================= CoinTelegraph =================
class CoinTelegraphCrawler(NewsCrawlerBase):
    SOURCE_CODE = NewsArticle.SOURCE_COINTELEGRAPH
    SOURCE_DISPLAY = "CoinTelegraph"

    RSS_URLS = [
        "https://cointelegraph.com/rss",
        "https://cointelegraph.com/feed",
        "https://cointelegraph.com/rss/tag/bitcoin",
        "https://cointelegraph.com/rss/tag/ethereum",
    ]

    def crawl(self, lookback_hours: int = 48) -> List[RawNews]:
        cutoff = datetime.utcnow() - timedelta(hours=lookback_hours)
        seen = set()
        out: List[RawNews] = []
        for rss_url in self.RSS_URLS:
            xml = self._http_get(rss_url)
            if not xml:
                continue
            for item in _parse_rss_feed(xml, limit=40):
                title = item["title"]
                link = item["link"]
                if not title or not link:
                    continue
                sid = hashlib.md5(link.encode("utf-8")).hexdigest()
                if sid in seen:
                    continue
                seen.add(sid)
                dt = _parse_date(item["pubDate"]) or datetime.utcnow()
                if dt < cutoff:
                    continue
                out.append(RawNews(
                    source_id=sid,
                    source_name=self.SOURCE_DISPLAY,
                    title=title[:300],
                    summary=self._truncate(item["description"], 800),
                    content=self._truncate(item["content"], 4000),
                    url=link,
                    image_url=item["image"],
                    author=self._truncate(item["author"], 80),
                    published_at=dt,
                    category="crypto",
                    tags=["crypto", "news"],
                ))
        out.sort(key=lambda x: x.published_at or datetime.utcnow(), reverse=True)
        logger.info(f"[News/{self.SOURCE_DISPLAY}] 抓取 {len(out)} 条")
        return out
