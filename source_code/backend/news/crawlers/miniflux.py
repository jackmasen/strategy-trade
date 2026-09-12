"""
Miniflux RSS 聚合器爬虫

通过 Miniflux API 获取已订阅的 RSS 新闻，配合 RSSHub 可扩展到 1000+ 新闻源。
自托管、免费、无限制，是第三方付费 API 的最佳替代方案。

Miniflux API 文档: https://miniflux.app/docs/api.html
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from backend.core.logging_config import logger
from backend.config import get_settings
from backend.models.analytics import NewsArticle
from ..base import NewsCrawlerBase, RawNews


class MinifluxCrawler(NewsCrawlerBase):
    """
    从 Miniflux 获取已订阅 RSS 源的最新文章。

    配置（.env 或 config.py）：
        MINIFLUX_URL       = http://127.0.0.1:8080
        MINIFLUX_API_KEY   = xxx        # 方式1：API Key 认证（推荐）
        MINIFLUX_USERNAME  = admin      # 方式2：用户名密码认证
        MINIFLUX_PASSWORD  = xxx

    工作流程：
        1. 调用 GET /v1/entries?status=unread&limit=100 获取未读文章
        2. 每篇文章转为 RawNews（source_id 用 entry_id 去重）
        3. 文章的 feed_title 作为 source_name 的补充
    """
    SOURCE_CODE = NewsArticle.SOURCE_MINIFLUX
    SOURCE_DISPLAY = "Miniflux RSS"

    def crawl(self, lookback_hours: int = 48) -> List[RawNews]:
        s = get_settings()
        base_url = (getattr(s, "MINIFLUX_URL", "") or "").strip().rstrip("/")
        if not base_url:
            logger.info(f"[News/{self.SOURCE_DISPLAY}] 未配置 MINIFLUX_URL，跳过")
            return []

        api_key = getattr(s, "MINIFLUX_API_KEY", "") or ""
        username = getattr(s, "MINIFLUX_USERNAME", "") or ""
        password = getattr(s, "MINIFLUX_PASSWORD", "") or ""

        headers = {"Content-Type": "application/json"}
        auth = None
        if api_key:
            headers["X-Auth-Token"] = api_key
        elif username and password:
            auth = (username, password)
        else:
            logger.info(f"[News/{self.SOURCE_DISPLAY}] 未配置认证信息（API_KEY 或 USERNAME/PASSWORD），跳过")
            return []

        cutoff = datetime.utcnow() - timedelta(hours=lookback_hours)
        out: List[RawNews] = []

        try:
            entries = self._fetch_entries(base_url, headers, auth, limit=100, status="unread")
            if not entries:
                entries = self._fetch_entries(base_url, headers, auth, limit=100, status="read")

            if not entries:
                logger.info(f"[News/{self.SOURCE_DISPLAY}] Miniflux 无文章返回")
                return []

            for entry in entries:
                try:
                    raw = self._parse_entry(entry, cutoff)
                    if raw:
                        out.append(raw)
                except Exception as e:
                    logger.debug(f"[News/{self.SOURCE_DISPLAY}] 解析文章失败: {e}")
                    continue

        except Exception as e:
            logger.warning(f"[News/{self.SOURCE_DISPLAY}] 获取文章失败: {e}")
            return []

        out.sort(key=lambda x: x.published_at or datetime.utcnow(), reverse=True)
        logger.info(f"[News/{self.SOURCE_DISPLAY}] 抓取 {len(out)} 条（来自 Miniflux 订阅源）")
        return out

    def _fetch_entries(self, base_url: str, headers: dict, auth, limit: int = 100, status: str = "unread") -> list:
        """调用 Miniflux API 获取文章列表"""
        url = f"{base_url}/v1/entries"
        params = {"status": status, "limit": limit, "order": "published_at", "direction": "desc"}

        resp = self._session.get(url, params=params, headers=headers, auth=auth, timeout=self.timeout)
        if resp.status_code != 200:
            logger.warning(f"[News/{self.SOURCE_DISPLAY}] API 返回 {resp.status_code}: {resp.text[:200]}")
            return []

        data = resp.json()
        return data.get("entries", []) or data.get("total", [])

    def _parse_entry(self, entry: dict, cutoff: datetime) -> Optional[RawNews]:
        """将 Miniflux entry 转为 RawNews"""
        entry_id = str(entry.get("id", ""))
        title = entry.get("title", "").strip()
        if not title:
            return None

        url = entry.get("url", "") or ""
        summary = self._clean_html(entry.get("content", "") or entry.get("summary", ""))
        summary = self._truncate(summary, 800)

        published_str = entry.get("published_at", "") or entry.get("created_at", "")
        dt = self._parse_dt(published_str)
        if dt and dt < cutoff:
            return None
        if dt is None:
            dt = datetime.utcnow()

        feed_title = entry.get("feed", {}).get("title", "") or ""
        source_name = f"{self.SOURCE_DISPLAY}" if not feed_title else f"{self.SOURCE_DISPLAY}/{feed_title}"

        author = entry.get("author", "") or feed_title
        category = self._guess_category(title, feed_title)

        sid = hashlib.md5(f"miniflux-{entry_id}-{url}".encode("utf-8")).hexdigest()

        return RawNews(
            source_id=sid,
            source_name=source_name,
            title=title[:300],
            summary=summary,
            content=self._truncate(entry.get("content", ""), 4000),
            url=url,
            image_url="",
            author=self._truncate(author, 80),
            published_at=dt,
            category=category,
            tags=self._guess_tags(title, feed_title, category),
        )

    @staticmethod
    def _parse_dt(s: str) -> Optional[datetime]:
        if not s:
            return None
        s = s.strip().replace("Z", "+00:00")
        for fmt in (
            "%Y-%m-%dT%H:%M:%S.%f%z",
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%S",
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

    @staticmethod
    def _clean_html(s: str) -> str:
        if not s:
            return ""
        import re
        s = re.sub(r"<[^>]+>", " ", s)
        s = re.sub(r"\s+", " ", s)
        import html as _h
        return _h.unescape(s).strip()

    @staticmethod
    def _guess_category(title: str, feed_title: str) -> str:
        text = (title + " " + feed_title).lower()
        if any(k in text for k in ["bitcoin", "btc", "ethereum", "eth", "crypto", "blockchain", "defi", "altcoin"]):
            return "crypto"
        if any(k in text for k in ["gold", "xau", "precious", "metal"]):
            return "metals"
        if any(k in text for k in ["oil", "crude", "wti", "energy", "opec", "gasoline"]):
            return "energy"
        if any(k in text for k in ["fed", "rate", "cpi", "nfp", "nonfarm", "gdp", "treasury", "yield", "economic"]):
            return "macro"
        if any(k in text for k in ["sec", "regulation", "ban", "lawsuit", "etf", "approval"]):
            return "regulation"
        return "general"

    @staticmethod
    def _guess_tags(title: str, feed_title: str, category: str) -> list:
        tags = [category, "rss", "miniflux"]
        text = (title + " " + feed_title).lower()
        if "bitcoin" in text or "btc" in text:
            tags.append("btc")
        if "ethereum" in text or "eth" in text:
            tags.append("eth")
        if "gold" in text or "xau" in text:
            tags.append("xau")
        if "oil" in text or "wti" in text:
            tags.append("wti")
        if "fed" in text or "fomc" in text:
            tags.append("fed")
        if "etf" in text:
            tags.append("etf")
        return tags
