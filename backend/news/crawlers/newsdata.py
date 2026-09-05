"""
媒体爬虫 5/5：NewsData.io 聚合新闻 API

免费档：200 篇/天 + 每秒 1 次请求 + 支持全文搜索
文档：https://newsdata.io/documentation

特点：
  - 聚合全球 3000+ 新闻源，覆盖面比 RSS 广
  - 支持关键词搜索 + 分类过滤 + 语言/国家过滤
  - 免费档每页最多 10 条（可通过 removeduplicate=1 去重）

策略：
  免费 200 篇/天，crawl() 每次请求 2 页（20 条），关键词覆盖 BTC/ETH/SOL/gold/oil/crypto。
  无 Key 时返回空列表 + 日志提示。
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from backend.core.logging_config import logger
from backend.config import get_settings
from backend.models.analytics import NewsArticle
from ..base import NewsCrawlerBase, RawNews


class NewsDataCrawler(NewsCrawlerBase):
    """NewsData.io 聚合新闻（免费 200 篇/天）"""

    SOURCE_CODE = NewsArticle.SOURCE_NEWSDATA
    SOURCE_DISPLAY = "NewsData.io"

    API_URL = "https://newsdata.io/api/1/news"

    # 关键词组合（AV 用的 OR 语法）：覆盖 5 个交易品种
    QUERY = "(bitcoin OR ethereum OR solana OR BTC OR ETH OR SOL OR crypto OR cryptocurrency OR gold OR \"crude oil\" OR WTI OR OPEC OR tesla OR nvidia OR apple OR microsoft OR tencent OR \"SK hynix\" OR sandisk OR \"semiconductor\")"
    # 免费档 category 支持：business, technology, world, science, politics
    CATEGORY = "business,technology,world"
    LANGUAGE = "en"

    def crawl(self, lookback_hours: int = 48) -> List[RawNews]:
        out: List[RawNews] = []
        s = get_settings()
        api_key = getattr(s, "NEWSDATA_API_KEY", "") or ""
        if not api_key:
            logger.info(
                f"[News/{self.SOURCE_DISPLAY}] 未配置 NEWSDATA_API_KEY，跳过"
                "（免费申请：https://newsdata.io/register）"
            )
            return out

        cutoff = datetime.utcnow() - timedelta(hours=lookback_hours)
        seen_url = set()

        # 免费 200 篇/天，每次请求 2 页（每页 10 条），节省配额
        total_pages = 2
        next_page_id = None

        for page_idx in range(total_pages):
            params = {
                "apikey": api_key,
                "q": self.QUERY,
                "category": self.CATEGORY,
                "language": self.LANGUAGE,
                "removeduplicate": 1,  # 去重
                "size": 10,
            }
            if next_page_id:
                params["page"] = next_page_id

            data = self._http_get(self.API_URL, params=params, as_json=True)
            if not data:
                logger.warning(f"[News/{self.SOURCE_DISPLAY}] 第 {page_idx + 1} 页请求失败")
                break

            # 限流检查
            results = data.get("results") or []
            if not results:
                # 可能是配额用尽或限流
                status_info = data.get("status") or ""
                msg = data.get("results") or data.get("message") or ""
                if status_info == "error":
                    code = (data.get("code") or "")[:100]
                    logger.warning(
                        f"[News/{self.SOURCE_DISPLAY}] API 错误: code={code} message={str(msg)[:200]}"
                    )
                break

            for item in results:
                try:
                    title = (item.get("title") or "").strip()
                    link = (item.get("link") or "").strip()
                    if not title or not link:
                        continue
                    if link in seen_url:
                        continue
                    seen_url.add(link)

                    sid = "ND-" + hashlib.md5(link.encode("utf-8")).hexdigest()

                    # 时间解析：NewsData 用 "2024-06-15 10:30:00 +00:00" 或 ISO
                    dt = self._parse_nd_time(item.get("pubDate") or "")

                    # description 是摘要，content 可能是全文（免费档可能截断）
                    description = (item.get("description") or "").strip()
                    content = (item.get("content") or "").strip()
                    if content and len(content) > len(description):
                        summary = description
                    else:
                        summary = description
                        content = description

                    # 作者
                    creators = item.get("creator") or []
                    author = ""
                    if isinstance(creators, list) and creators:
                        author = str(creators[0])[:128]

                    # 图片
                    image = item.get("image_url") or ""
                    # 来源名
                    source_name = (item.get("source_id") or self.SOURCE_DISPLAY)[:128]

                    # 分类映射
                    keywords_list = item.get("keywords") or []
                    category = self._infer_category(keywords_list, item.get("category") or [])

                    # 关联品种（复用 analyzer 的关键词映射逻辑）
                    tags = ["newsdata"]
                    if isinstance(keywords_list, list):
                        tags.extend(str(k).lower()[:40] for k in keywords_list[:10])

                    out.append(RawNews(
                        source_id=sid,
                        source_name=self.SOURCE_DISPLAY,
                        title=title[:300],
                        summary=self._truncate(summary, 800),
                        content=self._truncate(content, 4000),
                        url=link,
                        image_url=image,
                        author=author,
                        published_at=dt or datetime.utcnow(),
                        category=category,
                        tags=tags,
                    ))
                except Exception as e:
                    logger.debug(f"[News/{self.SOURCE_DISPLAY}] 解析单条失败: {e}")
                    continue

            # 获取下一页 token
            next_page_id = data.get("nextPage")
            if not next_page_id:
                break
            # 免费档 1 次/秒限速
            import time as _t
            _t.sleep(1.1)

        # 时间过滤
        if cutoff:
            out = [r for r in out if not r.published_at or r.published_at >= cutoff]

        out.sort(key=lambda x: x.published_at or datetime.utcnow(), reverse=True)
        logger.info(
            f"[News/{self.SOURCE_DISPLAY}] 抓取 {len(out)} 条"
            f"（免费配额 200/天，每次消耗 {total_pages} 次请求）"
        )
        return out

    @staticmethod
    def _parse_nd_time(s: str) -> Optional[datetime]:
        """解析 NewsData.io 时间格式"""
        if not s:
            return None
        s = s.strip()
        # 常见格式 1：ISO 8601 with offset
        for fmt in (
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%S.%f%z",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M:%S %z",
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
    def _infer_category(keywords: list, categories: list) -> str:
        """从 keywords 和 categories 推断新闻分类"""
        all_text = " ".join(
            [str(k) for k in (keywords or [])] + [str(c) for c in (categories or [])]
        ).lower()

        if any(k in all_text for k in ("bitcoin", "crypto", "blockchain", "ethereum", "solana", "nft")):
            return "crypto"
        if any(k in all_text for k in ("oil", "crude", "energy", "opec", "gasoline", "petroleum")):
            return "energy"
        if any(k in all_text for k in ("gold", "metal", "precious", "xau", "silver")):
            return "metals"
        if any(k in all_text for k in ("fed", "rate", "inflation", "cpi", "economy", "monetary")):
            return "macro"
        if any(k in all_text for k in ("regulation", "sec", "lawsuit", "approval")):
            return "regulation"
        return "general"
