"""
媒体爬虫 4/5：Alpha Vantage News & Sentiment API

免费档：25 次/天，每次返回最多 50 条新闻 + AI 情绪分（-1~1）
文档：https://www.alphavantage.co/documentation/#news-sentiment

特点：
  - 返回的每条新闻自带 overall_sentiment_score（AI 情绪分），比 VADER 更准
  - 支持按 ticker 过滤：CRYPTO:BTC / CRYPTO:ETH / FOREX:USD / COMMODITY:WTI
  - 支持按 topic 过滤：monetary_policy / economy / finance / crypto / energy

策略：
  免费 25 次/天非常有限，所以把所有 ticker + topic 合并到一次请求里（不拆分），
  每次 crawl() 只消耗 1 次配额，拿到最多 50 条。
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from backend.core.logging_config import logger
from backend.config import get_settings
from backend.models.analytics import NewsArticle
from ..base import NewsCrawlerBase, RawNews


class AlphaVantageCrawler(NewsCrawlerBase):
    """Alpha Vantage News & Sentiment（免费 25 次/天）"""

    SOURCE_CODE = NewsArticle.SOURCE_ALPHAVANTAGE
    SOURCE_DISPLAY = "Alpha Vantage"

    # 一次请求合并所有关心的 ticker（节省免费配额）
    TICKERS = "CRYPTO:BTC,CRYPTO:ETH,CRYPTO:SOL,CRYPTO:SAND,CRYPTO:HBAR"
    # topic 过滤（逗号分隔，AV 会返回命中的）
    TOPICS = "monetary_policy,economy,finance,crypto,energy"

    API_URL = "https://www.alphavantage.co/query"

    def crawl(self, lookback_hours: int = 48) -> List[RawNews]:
        out: List[RawNews] = []
        s = get_settings()
        api_key = getattr(s, "ALPHAVANTAGE_API_KEY", "") or ""
        if not api_key:
            logger.info(
                f"[News/{self.SOURCE_DISPLAY}] 未配置 ALPHAVANTAGE_API_KEY，跳过"
                "（免费申请：https://www.alphavantage.co/support/#api-key）"
            )
            return out

        cutoff = datetime.utcnow() - timedelta(hours=lookback_hours)
        # time_from 格式：YYYYMMDDTHMMSS（AV 要求）
        time_from = cutoff.strftime("%Y%m%dT%H%M%S")

        data = self._http_get(
            self.API_URL,
            params={
                "function": "NEWS_SENTIMENT",
                "tickers": self.TICKERS,
                "topics": self.TOPICS,
                "time_from": time_from,
                "sort": "LATEST",
                "limit": 50,
                "apikey": api_key,
            },
            as_json=True,
        )
        if not data:
            logger.warning(f"[News/{self.SOURCE_DISPLAY}] API 请求失败（代理+直连均失败）")
            return out

        # AV 返回格式：{"feed": [{...}, ...]}
        feed = data.get("feed") or data.get("results") or []
        if not feed:
            # 可能是限流 / Information 字段
            info = data.get("Information") or data.get("Note") or ""
            if info:
                logger.warning(f"[News/{self.SOURCE_DISPLAY}] API 限流或信息：{str(info)[:200]}")
            else:
                logger.info(f"[News/{self.SOURCE_DISPLAY}] feed 为空，0 条新闻")
            return out

        for item in feed:
            try:
                title = (item.get("title") or "").strip()
                url = (item.get("url") or "").strip()
                if not title or not url:
                    continue

                # source_id 用 URL 哈希
                sid = "AV-" + hashlib.md5(url.encode("utf-8")).hexdigest()

                # 时间解析：AV 用 "2024-06-15T10:30:00.000" 格式
                time_published = item.get("time_published") or ""
                dt = self._parse_av_time(time_published)
                if dt and dt < cutoff:
                    continue

                summary = (item.get("summary") or "").strip()
                # AV 自带情绪分
                av_score = float(item.get("overall_sentiment_score") or 0)
                av_label = (item.get("overall_sentiment_label") or "neutral").lower()

                # 提取作者
                authors = item.get("authors") or []
                author = ""
                if isinstance(authors, list) and authors:
                    author = str(authors[0])[:128]
                elif isinstance(authors, str):
                    author = authors[:128]

                # 提取图片
                banner = item.get("banner_image") or ""
                source_name = (item.get("source") or self.SOURCE_DISPLAY)[:128]

                # 从 ticker_sentiment 提取关联品种
                related_symbols = self._extract_ticker_symbols(
                    item.get("ticker_sentiment") or []
                )

                # 从 topic_relevance 提取分类
                category = self._infer_category(
                    item.get("topic") or item.get("topics") or ""
                )

                # 标题中附加 AV 情绪标记（前端可展示）
                tags = ["alphavantage", av_label]
                if av_score >= 0.15:
                    tags.append("av_bullish")
                elif av_score <= -0.15:
                    tags.append("av_bearish")

                out.append(RawNews(
                    source_id=sid,
                    source_name=self.SOURCE_DISPLAY,
                    title=title[:300],
                    summary=self._truncate(summary, 800),
                    content=self._truncate(summary, 4000),
                    url=url,
                    image_url=banner,
                    author=author,
                    published_at=dt or datetime.utcnow(),
                    category=category,
                    tags=tags + related_symbols,
                ))
                # 把 AV 情绪分注入到 RawNews（pipeline 的 analyzer 会覆盖，
                # 但我们在 content 末尾加一条元数据行，analyzer 的 VADER 也能感知）
                if av_score and out[-1].content:
                    out[-1].content += (
                        f"\n\n[AlphaVantage sentiment: {av_label}, score={av_score:.3f}]"
                    )
            except Exception as e:
                logger.debug(f"[News/{self.SOURCE_DISPLAY}] 解析单条失败: {e}")
                continue

        out.sort(key=lambda x: x.published_at or datetime.utcnow(), reverse=True)
        logger.info(
            f"[News/{self.SOURCE_DISPLAY}] 抓取 {len(out)} 条"
            f"（AV sentiment score 直采，免费配额 25/天）"
        )
        return out

    @staticmethod
    def _parse_av_time(s: str) -> Optional[datetime]:
        """解析 AV 时间格式 20240615T103000 → datetime"""
        if not s:
            return None
        s = s.strip()
        # AV 格式：YYYYMMDDTHHMMSS[.fff]
        for fmt in ("%Y%m%dT%H%M%S", "%Y%m%dT%H%M%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
            try:
                dt = datetime.strptime(s.replace(".", "", 0), fmt)
                # 更靠谱的做法：先试带毫秒的
                if dt.year > 2000:
                    return dt
            except Exception:
                continue
        # 带毫秒的情况需要特殊处理
        try:
            if "T" in s and "." in s:
                base, ms = s.split(".")
                dt = datetime.strptime(base, "%Y%m%dT%H%M%S")
                return dt
        except Exception:
            pass
        return None

    @staticmethod
    def _extract_ticker_symbols(ticker_sentiment: list) -> List[str]:
        """从 AV ticker_sentiment 数组提取本系统关心的品种映射"""
        # AV 返回：[{"ticker": "CRYPTO:BTC", "relevance_score": "0.85", ...}, ...]
        av_to_sys = {
            "CRYPTO:BTC": "BTC", "CRYPTO:ETH": "ETH", "CRYPTO:SOL": "SOL",
            "CRYPTO:SAND": "SAND", "CRYPTO:HBAR": "HBAR",
            "FOREX:USD": "XAU",  # USD 美元 ↔ 黄金（反向，但关联性强）
            "COMMODITY:WTI": "WTI", "COMMODITY:BRENT": "WTI",
            "COMMODITY:NATURAL_GAS": "WTI",  # 能源板块联动
        }
        out: List[str] = []
        for ts in ticker_sentiment:
            if not isinstance(ts, dict):
                continue
            ticker = (ts.get("ticker") or "").upper()
            sys_sym = av_to_sys.get(ticker)
            if sys_sym and sys_sym not in out:
                out.append(sys_sym)
        return out

    @staticmethod
    def _infer_category(topic_str: str) -> str:
        """从 AV topic 字段推断新闻分类"""
        t = (topic_str or "").lower()
        if any(k in t for k in ("crypto", "blockchain", "bitcoin")):
            return "crypto"
        if any(k in t for k in ("energy", "oil", "crude", "gas")):
            return "energy"
        if any(k in t for k in ("monetary", "economy", "fed", "rate", "inflation")):
            return "macro"
        if any(k in t for k in ("finance", "market", "stock")):
            return "macro"
        return "general"
