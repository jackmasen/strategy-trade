"""
媒体爬虫 2/3：宏观金融 + 大宗商品媒体（路透/彭博/CNBC + OilPrice.com）
统一通过 RSS feed 抓取，Bloomberg RSS 被墙时自动跳过（不报错阻塞）。
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from typing import List

from backend.core.logging_config import logger
from backend.models.analytics import NewsArticle
from ..base import NewsCrawlerBase, RawNews
from .coindesk import _parse_rss_feed, _parse_date


class ReutersCrawler(NewsCrawlerBase):
    """路透社：business + markets + commodities（影响原油、黄金、宏观）"""
    SOURCE_CODE = NewsArticle.SOURCE_REUTERS
    SOURCE_DISPLAY = "Reuters"

    RSS_URLS = [
        "https://feeds.reuters.com/reuters/businessNews",
        "https://feeds.reuters.com/reuters/companyNews",
        "https://feeds.reuters.com/reuters/wealth",
        "https://www.reutersagency.com/feed/?taxonomy=best-sectors&post_type=best",
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
                # 分类：关键词粗分 → 关联 XAU/WTI/BTC
                title_l = title.lower()
                if any(k in title_l for k in ("oil", "crude", "opec", "brent", "wti", "gasoline")):
                    cat = "energy"
                elif any(k in title_l for k in ("gold", "silver", "metals", "xau", "precious")):
                    cat = "metals"
                elif any(k in title_l for k in ("fed", "powell", "rate", "inflation", "cpi", "interest", "treasur", "yield")):
                    cat = "macro"
                elif any(k in title_l for k in ("crypto", "bitcoin", "ethereum", "solana")):
                    cat = "crypto"
                else:
                    cat = "markets"
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
                    category=cat,
                    tags=[cat],
                ))
        out.sort(key=lambda x: x.published_at or datetime.utcnow(), reverse=True)
        logger.info(f"[News/{self.SOURCE_DISPLAY}] 抓取 {len(out)} 条")
        return out


class BloombergCrawler(NewsCrawlerBase):
    """彭博社：宏观 / 美联储 / 能源政策"""
    SOURCE_CODE = NewsArticle.SOURCE_BLOOMBERG
    SOURCE_DISPLAY = "Bloomberg"

    # Bloomberg 很多 RSS 限地区，这里列几个公共的，抓不到就跳过
    RSS_URLS = [
        "https://feeds.bloomberg.com/markets/news.rss",
        "https://feeds.bloomberg.com/economics/news.rss",
        "https://feeds.bloomberg.com/technology/news.rss",
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
                title_l = title.lower()
                if any(k in title_l for k in ("fed", "powell", "rate", "inflation", "cpi", "interest", "recession", "fomc")):
                    cat = "macro"
                elif any(k in title_l for k in ("oil", "crude", "opec", "brent", "wti")):
                    cat = "energy"
                elif any(k in title_l for k in ("gold", "silver", "metals", "treasur", "yields")):
                    cat = "metals"
                elif any(k in title_l for k in ("crypto", "bitcoin", "ethereum")):
                    cat = "crypto"
                else:
                    cat = "markets"
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
                    category=cat,
                    tags=[cat, "bloomberg"],
                ))
        out.sort(key=lambda x: x.published_at or datetime.utcnow(), reverse=True)
        logger.info(f"[News/{self.SOURCE_DISPLAY}] 抓取 {len(out)} 条")
        return out


class CNBCCrawler(NewsCrawlerBase):
    """CNBC：美股 + 能源 + 美联储；是原油/黄金日内短线的重要噪声源"""
    SOURCE_CODE = NewsArticle.SOURCE_CNBC
    SOURCE_DISPLAY = "CNBC"

    RSS_URLS = [
        "https://www.cnbc.com/id/100003114/device/rss/rss.html",  # Top News
        "https://www.cnbc.com/id/10000664/device/rss/rss.html",   # Economy（Fed/CPI）
        "https://www.cnbc.com/id/10001139/device/rss/rss.html",   # Finance
        "https://www.cnbc.com/id/19836768/device/rss/rss.html",   # Energy
        "https://www.cnbc.com/id/10000108/device/rss/rss.html",   # World Markets
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
                title_l = title.lower()
                if any(k in title_l for k in ("oil", "crude", "opec", "brent", "wti", "natural gas", "shale")):
                    cat = "energy"
                elif any(k in title_l for k in ("gold", "silver", "metals", "xau")):
                    cat = "metals"
                elif any(k in title_l for k in ("fed", "powell", "rate", "inflation", "cpi", "interest", "yields", "treasur", "fomc", "nonfarm")):
                    cat = "macro"
                elif any(k in title_l for k in ("crypto", "bitcoin", "ethereum", "solana")):
                    cat = "crypto"
                else:
                    cat = "markets"
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
                    category=cat,
                    tags=[cat, "us-markets"],
                ))
        out.sort(key=lambda x: x.published_at or datetime.utcnow(), reverse=True)
        logger.info(f"[News/{self.SOURCE_DISPLAY}] 抓取 {len(out)} 条")
        return out


class OilPriceCrawler(NewsCrawlerBase):
    """OilPrice.com：WTI 原油、天然气、OPEC 官方新闻（WTI 品种的核心来源）"""
    SOURCE_CODE = NewsArticle.SOURCE_OILPRICE
    SOURCE_DISPLAY = "OilPrice.com"

    RSS_URLS = [
        "https://oilprice.com/rss/main",        # 综合能源
        "https://oilprice.com/rss/crude-oil",   # 原油（WTI/Brent）
        "https://oilprice.com/rss/natural-gas", # 天然气
        "https://oilprice.com/rss/opec",        # OPEC 官方新闻
    ]

    def crawl(self, lookback_hours: int = 72) -> List[RawNews]:
        cutoff = datetime.utcnow() - timedelta(hours=lookback_hours)
        seen = set()
        out: List[RawNews] = []
        for rss_url in self.RSS_URLS:
            xml = self._http_get(rss_url)
            if not xml:
                continue
            for item in _parse_rss_feed(xml, limit=30):
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
                    category="energy",
                    tags=["energy", "oil", "wti", "commodities"],
                ))
        out.sort(key=lambda x: x.published_at or datetime.utcnow(), reverse=True)
        logger.info(f"[News/{self.SOURCE_DISPLAY}] 抓取 {len(out)} 条")
        return out
