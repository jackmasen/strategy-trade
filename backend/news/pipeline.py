"""
统一新闻管道（主入口：NewsPipeline.run_once）

流程（单次调用执行）：
  1) 多源并发抓取（ThreadPoolExecutor，8 个源并行）
  2) source + source_id 联合去重（数据库内已存在的跳过）
  3) analyzer.analyze() → 情绪 / 品种关联 / 影响级别
  4) 批量写 NewsArticle（analyzed_at 填当前时间）

被 2 个地方调用：
  A. scheduled.py 的 celery task / APScheduler cron 每 15min
  B. 前端"立即采集新闻"按钮（POST /api/analytics/news/fetch 路由，后续加）
"""
from __future__ import annotations

import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Sequence, Type

from sqlalchemy.orm import Session

from backend.core.logging_config import logger
from backend.db.session import SessionLocal
from backend.models.analytics import NewsArticle
from .base import NewsCrawlerBase, RawNews
from .crawlers import ALL_CRAWLERS
from . import analyzer


@dataclass
class PipelineRunResult:
    total_fetched: int = 0
    total_inserted: int = 0
    total_skipped_dup: int = 0
    per_source: Dict[str, dict] = None
    errors: List[str] = None

    def __post_init__(self):
        if self.per_source is None: self.per_source = {}
        if self.errors is None: self.errors = []


class NewsPipeline:
    """
    采集 + 分析 + 入库。无状态：每次 run_once 都是独立事务。
    """

    def __init__(
        self,
        crawlers: Optional[Sequence[Type[NewsCrawlerBase]]] = None,
        lookback_hours: int = 48,
        max_workers: int = 4,
    ):
        self.crawlers_classes: List[Type[NewsCrawlerBase]] = list(crawlers or ALL_CRAWLERS)
        self.lookback_hours = lookback_hours
        self.max_workers = max(max_workers, 1)

    # ============= 主入口 =============
    def run_once(self, db: Optional[Session] = None) -> PipelineRunResult:
        """对外入口：可手动传入 DB session，或者内部临时开一个"""
        res = PipelineRunResult()
        own_session = db is None
        if own_session:
            db = SessionLocal()
        try:
            # 1) 并发抓取所有源
            raw_by_source: Dict[str, List[RawNews]] = self._concurrent_fetch(res)

            # 2) 已存在 source+source_id 的去重
            all_raw: List[RawNews] = []
            for src, items in raw_by_source.items():
                for r in items:
                    all_raw.append(r)
            res.total_fetched = len(all_raw)
            if not all_raw:
                return res
            deduped = self._dedupe_against_db(db, all_raw, res)

            # 3) 情绪 / 关联 / 影响级别
            analyzed_pairs: List[tuple[RawNews, analyzer.AnalysisResult]] = []
            for r in deduped:
                try:
                    ar = analyzer.analyze(
                        title=r.title, summary=r.summary or r.content,
                        category=r.category or "general",
                        language=r.language or "en",
                        tags=r.tags,
                        source_name=r.source_name,
                        published_at=r.published_at,
                    )
                    analyzed_pairs.append((r, ar))
                except Exception as e:
                    logger.debug(f"[News/Pipeline] 分析失败 {r.title[:40]}: {e}")

            # 4) 批量写入 DB
            new_count = self._bulk_insert(db, analyzed_pairs)
            res.total_inserted = new_count
            db.commit()
            return res
        except Exception as e:
            logger.error(f"[News/Pipeline] 运行异常: {e}\n{traceback.format_exc()}")
            res.errors.append(str(e))
            db.rollback()
            return res
        finally:
            if own_session and db is not None:
                db.close()

    # ============= 内部步骤 =============
    def _concurrent_fetch(self, res: PipelineRunResult) -> Dict[str, List[RawNews]]:
        out: Dict[str, List[RawNews]] = {}
        with ThreadPoolExecutor(max_workers=self.max_workers) as ex:
            future_map = {}
            for cls in self.crawlers_classes:
                try:
                    crawler = cls()
                    future = ex.submit(crawler.crawl, self.lookback_hours)
                    future_map[future] = crawler.SOURCE_DISPLAY
                except Exception as e:
                    err = f"创建爬虫 {getattr(cls, 'SOURCE_DISPLAY', cls.__name__)} 失败: {e}"
                    logger.warning(f"[News/Pipeline] {err}")
                    res.errors.append(err)
            for fu in as_completed(future_map):
                src = future_map[fu]
                try:
                    items = fu.result() or []
                    out[src] = list(items)
                    res.per_source[src] = {
                        "fetched": len(items),
                    }
                except Exception as e:
                    err = f"抓取源 {src} 异常: {e}"
                    logger.warning(f"[News/Pipeline] {err}")
                    res.errors.append(err)
                    res.per_source.setdefault(src, {})["error"] = str(e)
        return out

    def _dedupe_against_db(self, db: Session, items: List[RawNews], res: PipelineRunResult) -> List[RawNews]:
        """NewsArticle 存在 (source, source_id) 的直接跳过"""
        # 把 crawler.SOURCE_CODE 从 display 名反查出来（通过 crawler 类对象扫一遍）
        display_to_code: Dict[str, int] = {}
        for cls in self.crawlers_classes:
            display_to_code[cls.SOURCE_DISPLAY] = int(cls.SOURCE_CODE)

        # 生成 (source_code, source_id) 列表
        lookup_keys: List[tuple[int, str]] = []
        for r in items:
            code = display_to_code.get(r.source_name, 99)
            lookup_keys.append((code, r.source_id))
        if not lookup_keys:
            return items

        # 分批查询（SQLite 也兼容）
        existing: set[tuple[int, str]] = set()
        batch = 400
        for start in range(0, len(lookup_keys), batch):
            chunk = lookup_keys[start:start + batch]
            # 用 OR：兼容所有 DB（SQLite/MySQL 都 OK）
            from sqlalchemy import or_, and_
            clauses = [and_(NewsArticle.source == c, NewsArticle.source_id == sid) for c, sid in chunk]
            rows = db.query(NewsArticle.source, NewsArticle.source_id).filter(or_(*clauses)).all()
            for c, sid in rows:
                existing.add((int(c), str(sid)))

        deduped: List[RawNews] = []
        for r in items:
            code = display_to_code.get(r.source_name, 99)
            key = (int(code), str(r.source_id))
            if key in existing:
                res.total_skipped_dup += 1
                continue
            deduped.append(r)
        return deduped

    def _bulk_insert(self, db: Session, pairs: List) -> int:
        """批量写 NewsArticle；返回插入条数"""
        # 反查 display -> source_code
        display_to_code: Dict[str, int] = {}
        for cls in self.crawlers_classes:
            display_to_code[cls.SOURCE_DISPLAY] = int(cls.SOURCE_CODE)

        count = 0
        now = datetime.now()
        for raw, ar in pairs:
            code = display_to_code.get(raw.source_name, 99)
            obj = NewsArticle(
                source=code,
                source_id=str(raw.source_id or ""),
                title=str(raw.title)[:512],
                summary=str(raw.summary or "")[:2000],
                content=str(raw.content or "")[:8000],
                url=str(raw.url or "")[:1024],
                image_url=str(raw.image_url or "")[:1024],
                author=str(raw.author or "")[:128],
                source_name=str(raw.source_name)[:128],
                category=str(raw.category or "")[:64],
                tags=list(ar.tags or raw.tags or []),
                related_symbols=list(ar.related_symbols or []),
                sentiment=int(ar.sentiment),
                sentiment_score=float(ar.sentiment_score),
                sentiment_keywords=list(ar.sentiment_keywords or []),
                impact_level=int(ar.impact_level),
                is_hot=bool(ar.is_hot),
                published_at=raw.published_at or now,
                analyzed_at=now,
            )
            db.add(obj)
            count += 1
        if count:
            try:
                db.flush()
            except Exception as e:
                db.rollback()
                logger.warning(f"[News/Pipeline] flush 失败，尝试单条写入: {e}")
                count = 0
                # 退回单条写入（SQLAlchemy flush 单条失败不会污染其余）
                for raw, ar in pairs:
                    code = display_to_code.get(raw.source_name, 99)
                    try:
                        obj = NewsArticle(
                            source=code,
                            source_id=str(raw.source_id or ""),
                            title=str(raw.title)[:512],
                            summary=str(raw.summary or "")[:2000],
                            content=str(raw.content or "")[:8000],
                            url=str(raw.url or "")[:1024],
                            image_url=str(raw.image_url or "")[:1024],
                            author=str(raw.author or "")[:128],
                            source_name=str(raw.source_name)[:128],
                            category=str(raw.category or "")[:64],
                            tags=list(ar.tags or raw.tags or []),
                            related_symbols=list(ar.related_symbols or []),
                            sentiment=int(ar.sentiment),
                            sentiment_score=float(ar.sentiment_score),
                            sentiment_keywords=list(ar.sentiment_keywords or []),
                            impact_level=int(ar.impact_level),
                            is_hot=bool(ar.is_hot),
                            published_at=raw.published_at or now,
                            analyzed_at=now,
                        )
                        db.add(obj); db.flush()
                        count += 1
                    except Exception as ee:
                        logger.debug(f"[News/Pipeline] 单条插入跳过: {raw.title[:40]} ... {ee}")
                        db.rollback()
        return count


# ------------------ 简单 CLI 入口 ------------------
if __name__ == "__main__":
    pipeline = NewsPipeline(lookback_hours=48, max_workers=4)
    r = pipeline.run_once()
    print(f"fetched={r.total_fetched}, inserted={r.total_inserted}, skipped_dup={r.total_skipped_dup}")
    print(f"per_source={r.per_source}")
    if r.errors:
        print(f"errors={r.errors}")
