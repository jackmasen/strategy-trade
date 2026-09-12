"""
中文财经媒体爬虫 + Decrypt + DailyFX
- 财联社电报（API/网页）
- 币世界（API）
- 华尔街见闻（RSS）
- Decrypt（RSS）
- DailyFX（RSS）
- 金十数据（API）
- 币安公告（API）
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta
from typing import List

from backend.core.logging_config import logger
from backend.models.analytics import NewsArticle
from ..base import NewsCrawlerBase, RawNews
from .coindesk import _parse_rss_feed, _parse_date


# ================= 财联社电报 =================
class CLSCrawler(NewsCrawlerBase):
    """财联社电报：A股/加密/宏观 快讯"""
    SOURCE_CODE = NewsArticle.SOURCE_CLS
    SOURCE_DISPLAY = "财联社"

    API_URL = "https://www.cls.cn/nodeapi/updateTelegraphList"

    def crawl(self, lookback_hours: int = 48) -> List[RawNews]:
        cutoff = datetime.utcnow() - timedelta(hours=lookback_hours)
        out: List[RawNews] = []
        try:
            params = {"app": "CailianpressWeb", "category": "", "lastTime": "", "os": "web", "sv": "7.7.5"}
            data = self._http_get(self.API_URL, params=params, as_json=True)
            if not data or not isinstance(data, dict):
                return out
            items = data.get("data", {}).get("roll_data", [])
            if not items:
                items = data.get("data", [])
            for item in items[:60]:
                title = item.get("title", "") or item.get("content", "")[:80]
                if not title:
                    continue
                content = item.get("content", "")
                pub_ts = item.get("ctime", 0)
                if pub_ts:
                    dt = datetime.fromtimestamp(int(pub_ts))
                else:
                    dt = datetime.utcnow()
                if dt < cutoff:
                    continue
                sid = hashlib.md5(f"cls_{item.get('id', title)}".encode()).hexdigest()
                title_l = title.lower()
                if any(k in title_l for k in ("btc", "比特币", "eth", "以太", "加密")):
                    cat = "crypto"
                elif any(k in title_l for k in ("原油", "opec", "wti", "布伦特")):
                    cat = "energy"
                elif any(k in title_l for k in ("黄金", "白银", "贵金属")):
                    cat = "metals"
                elif any(k in title_l for k in ("非农", "cpi", "利率", "加息", "降息", "美联储", "就业")):
                    cat = "macro"
                else:
                    cat = "markets"
                out.append(RawNews(
                    source_id=sid, source_name=self.SOURCE_DISPLAY,
                    title=title[:300], summary=self._truncate(content, 800),
                    content=self._truncate(content, 4000),
                    url=f"https://www.cls.cn/detail/{item.get('id', '')}",
                    published_at=dt, category=cat,
                    tags=[cat, "cls", "中文"], language="zh",
                ))
        except Exception as e:
            logger.warning(f"[News/财联社] 抓取异常: {e}")
        logger.info(f"[News/{self.SOURCE_DISPLAY}] 抓取 {len(out)} 条")
        return out


# ================= 币世界 =================
class BishijieCrawler(NewsCrawlerBase):
    """币世界：加密货币快讯"""
    SOURCE_CODE = NewsArticle.SOURCE_BISHIJIE
    SOURCE_DISPLAY = "币世界"

    API_URL = "https://www.bishijie.com/shandian/pro/newsflash_list"

    def crawl(self, lookback_hours: int = 48) -> List[RawNews]:
        cutoff = datetime.utcnow() - timedelta(hours=lookback_hours)
        out: List[RawNews] = []
        try:
            params = {"size": 50, "app": "pc"}
            data = self._http_get(self.API_URL, params=params, as_json=True)
            if not data or not isinstance(data, dict):
                return out
            items = data.get("data", {}).get("list", [])
            if not items:
                items = data.get("data", [])
            for item in items[:50]:
                content = item.get("content", "") or item.get("title", "")
                title = item.get("title", "") or content[:80]
                if not title:
                    continue
                pub_ts = item.get("issue_time", 0) or item.get("created_at", 0)
                if pub_ts:
                    dt = datetime.fromtimestamp(int(pub_ts))
                else:
                    dt = datetime.utcnow()
                if dt < cutoff:
                    continue
                sid = hashlib.md5(f"bsj_{item.get('id', title)}".encode()).hexdigest()
                out.append(RawNews(
                    source_id=sid, source_name=self.SOURCE_DISPLAY,
                    title=title[:300], summary=self._truncate(content, 800),
                    content=self._truncate(content, 4000),
                    url=f"https://www.bishijie.com/news/{item.get('id', '')}",
                    published_at=dt, category="crypto",
                    tags=["crypto", "bishijie", "中文"], language="zh",
                ))
        except Exception as e:
            logger.warning(f"[News/币世界] 抓取异常: {e}")
        logger.info(f"[News/{self.SOURCE_DISPLAY}] 抓取 {len(out)} 条")
        return out


# ================= 华尔街见闻 =================
class WallStreetCNCrawler(NewsCrawlerBase):
    """华尔街见闻：宏观/美联储/非农"""
    SOURCE_CODE = NewsArticle.SOURCE_WALLSTREETCN
    SOURCE_DISPLAY = "华尔街见闻"

    RSS_URLS = [
        "https://wallstreetcn.com/rss",
        "https://wallstreetcn.com/feed/global",
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
                if any(k in title_l for k in ("非农", "cpi", "利率", "加息", "降息", "美联储", "fed", "powell")):
                    cat = "macro"
                elif any(k in title_l for k in ("原油", "oil", "opec", "黄金", "gold")):
                    cat = "energy" if "油" in title_l else "metals"
                elif any(k in title_l for k in ("比特币", "btc", "eth", "加密")):
                    cat = "crypto"
                else:
                    cat = "markets"
                out.append(RawNews(
                    source_id=sid, source_name=self.SOURCE_DISPLAY,
                    title=title[:300], summary=self._truncate(item["description"], 800),
                    content=self._truncate(item["content"], 4000),
                    url=link, image_url=item["image"],
                    published_at=dt, category=cat,
                    tags=[cat, "wallstreetcn", "中文"], language="zh",
                ))
        out.sort(key=lambda x: x.published_at or datetime.utcnow(), reverse=True)
        logger.info(f"[News/{self.SOURCE_DISPLAY}] 抓取 {len(out)} 条")
        return out


# ================= Decrypt =================
class DecryptCrawler(NewsCrawlerBase):
    """Decrypt：加密货币英文媒体"""
    SOURCE_CODE = NewsArticle.SOURCE_DECRYPT
    SOURCE_DISPLAY = "Decrypt"

    RSS_URLS = [
        "https://decrypt.co/feed",
        "https://decrypt.co/news/feed",
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
                    source_id=sid, source_name=self.SOURCE_DISPLAY,
                    title=title[:300], summary=self._truncate(item["description"], 800),
                    content=self._truncate(item["content"], 4000),
                    url=link, image_url=item["image"],
                    author=self._truncate(item["author"], 80),
                    published_at=dt, category="crypto",
                    tags=["crypto", "decrypt"],
                ))
        out.sort(key=lambda x: x.published_at or datetime.utcnow(), reverse=True)
        logger.info(f"[News/{self.SOURCE_DISPLAY}] 抓取 {len(out)} 条")
        return out


# ================= DailyFX =================
class DailyFXCrawler(NewsCrawlerBase):
    """DailyFX：宏观经济/非农数据/美联储"""
    SOURCE_CODE = NewsArticle.SOURCE_DAILYFX
    SOURCE_DISPLAY = "DailyFX"

    RSS_URLS = [
        "https://www.dailyfx.com/feeds/market-news",
        "https://www.dailyfx.com/feeds/all",
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
                if any(k in title_l for k in ("nonfarm", "nfp", "cpi", "fed", "fomc", "rate", "interest")):
                    cat = "macro"
                elif any(k in title_l for k in ("oil", "crude", "gold", "xau")):
                    cat = "energy" if "oil" in title_l else "metals"
                elif any(k in title_l for k in ("bitcoin", "crypto", "btc")):
                    cat = "crypto"
                else:
                    cat = "markets"
                out.append(RawNews(
                    source_id=sid, source_name=self.SOURCE_DISPLAY,
                    title=title[:300], summary=self._truncate(item["description"], 800),
                    content=self._truncate(item["content"], 4000),
                    url=link, image_url=item["image"],
                    author=self._truncate(item["author"], 80),
                    published_at=dt, category=cat,
                    tags=[cat, "dailyfx", "macro"],
                ))
        out.sort(key=lambda x: x.published_at or datetime.utcnow(), reverse=True)
        logger.info(f"[News/{self.SOURCE_DISPLAY}] 抓取 {len(out)} 条")
        return out


# ================= 金十数据 =================
class Jin10Crawler(NewsCrawlerBase):
    """金十数据：宏观经济/美联储/CPI/非农 中文快讯"""
    SOURCE_CODE = NewsArticle.SOURCE_JIN10
    SOURCE_DISPLAY = "金十数据"

    API_URL = "https://flash-api.jin10.com/get_flash_list"
    MAX_ITEMS = 80

    def crawl(self, lookback_hours: int = 48) -> List[RawNews]:
        cutoff = datetime.utcnow() - timedelta(hours=lookback_hours)
        out: List[RawNews] = []
        try:
            params = {
                "max_time": "",
                "channel": "-8200",
                "t": str(int(datetime.utcnow().timestamp() * 1000)),
            }
            data = self._http_get(self.API_URL, params=params, as_json=True)
            if not data or not isinstance(data, dict):
                return out
            items = data.get("data", [])
            if not items:
                items = data.get("items", [])
            for item in items[:self.MAX_ITEMS]:
                title = item.get("title", "") or ""
                content = item.get("content", "") or ""
                if not title and content:
                    title = content[:80]
                if not title:
                    continue
                pub_ts = item.get("time", 0)
                if pub_ts:
                    if pub_ts > 1e12:
                        dt = datetime.fromtimestamp(int(pub_ts) / 1000)
                    else:
                        dt = datetime.fromtimestamp(int(pub_ts))
                else:
                    dt = datetime.utcnow()
                if dt < cutoff:
                    continue
                sid = hashlib.md5(f"jin10_{item.get('id', title)}".encode()).hexdigest()
                title_l = title.lower()
                if any(k in title_l for k in ("非农", "cpi", "利率", "加息", "降息", "美联储", "fed", "就业", "pmi", "gdp")):
                    cat = "macro"
                elif any(k in title_l for k in ("原油", "opec", "wti", "布伦特")):
                    cat = "energy"
                elif any(k in title_l for k in ("黄金", "白银", "贵金属", "gold")):
                    cat = "metals"
                elif any(k in title_l for k in ("btc", "比特币", "eth", "以太", "加密", "区块链")):
                    cat = "crypto"
                else:
                    cat = "markets"
                out.append(RawNews(
                    source_id=sid, source_name=self.SOURCE_DISPLAY,
                    title=title[:300], summary=self._truncate(content, 800),
                    content=self._truncate(content, 4000),
                    url=f"https://www.jin10.com/flash/{item.get('id', '')}",
                    published_at=dt, category=cat,
                    tags=[cat, "jin10", "中文"], language="zh",
                ))
        except Exception as e:
            logger.warning(f"[News/金十数据] 抓取异常: {e}")
        logger.info(f"[News/{self.SOURCE_DISPLAY}] 抓取 {len(out)} 条")
        return out


# ================= 币安公告 =================
class BinanceAnnouncementCrawler(NewsCrawlerBase):
    """币安官方公告：上新/下架/维护/风控等"""
    SOURCE_CODE = NewsArticle.SOURCE_BINANCE_ANN
    SOURCE_DISPLAY = "币安公告"

    API_URL = "https://www.binance.com/bapi/composite/v1/public/cms/article/list/query"
    MAX_ITEMS = 50

    def crawl(self, lookback_hours: int = 48) -> List[RawNews]:
        cutoff = datetime.utcnow() - timedelta(hours=lookback_hours)
        out: List[RawNews] = []
        try:
            import httpx
            payload = {
                "pageNo": 1,
                "pageSize": self.MAX_ITEMS,
                "catalogId": "48",
            }
            with httpx.Client(timeout=15) as client:
                resp = client.post(self.API_URL, json=payload)
                if resp.status_code != 200:
                    logger.warning(f"[News/币安公告] HTTP {resp.status_code}")
                    return out
                data = resp.json()
            items = data.get("data", {}).get("articles", [])
            if not items:
                items = data.get("data", [])
            for item in items[:self.MAX_ITEMS]:
                title = item.get("title", "") or ""
                if not title:
                    continue
                content = item.get("content", "") or item.get("summary", "") or ""
                pub_ts = item.get("publishDate", "") or item.get("ctime", "")
                if isinstance(pub_ts, (int, float)):
                    if pub_ts > 1e12:
                        dt = datetime.fromtimestamp(int(pub_ts) / 1000)
                    else:
                        dt = datetime.fromtimestamp(int(pub_ts))
                elif isinstance(pub_ts, str) and pub_ts:
                    try:
                        dt = datetime.fromisoformat(pub_ts.replace("Z", "+00:00"))
                        dt = dt.replace(tzinfo=None)
                    except Exception:
                        dt = datetime.utcnow()
                else:
                    dt = datetime.utcnow()
                if dt < cutoff:
                    continue
                article_id = item.get("id", "") or item.get("code", "")
                sid = hashlib.md5(f"binance_ann_{article_id}".encode()).hexdigest()
                title_l = title.lower()
                if any(k in title_l for k in ("list", "listing", "delist", "new trading")):
                    detail_tag = "listing"
                elif any(k in title_l for k in ("suspension", "maintenance", "upgrade")):
                    detail_tag = "maintenance"
                elif any(k in title_l for k in ("burn", "airdrop", "distribution")):
                    detail_tag = "corporate"
                else:
                    detail_tag = "announcement"
                out.append(RawNews(
                    source_id=sid, source_name=self.SOURCE_DISPLAY,
                    title=title[:300], summary=self._truncate(content, 800),
                    content=self._truncate(content, 4000),
                    url=f"https://www.binance.com/en/support/announcement/{article_id}",
                    published_at=dt, category="crypto",
                    tags=["crypto", "binance", detail_tag],
                ))
        except Exception as e:
            logger.warning(f"[News/币安公告] 抓取异常: {e}")
        logger.info(f"[News/{self.SOURCE_DISPLAY}] 抓取 {len(out)} 条")
        return out
