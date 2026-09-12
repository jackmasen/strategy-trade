"""
统一新闻管道（主入口：NewsPipeline.run_once）

流程（单次调用执行）：
  1) Miniflux RSS 优先抓取（可靠源，不会被封锁）
  2) 其他源并发抓取（ThreadPoolExecutor，自动跳过连续失败的爬虫）
  3) source + source_id 联合去重（数据库内已存在的跳过）
  4) analyzer.analyze() → 情绪 / 品种关联 / 影响级别
  5) 批量写 NewsArticle（analyzed_at 填当前时间）

被 2 个地方调用：
  A. scheduled.py 的 celery task / APScheduler cron 每 15min
  B. 前端"立即采集新闻"按钮（POST /api/analytics/news/fetch 路由）
"""
from __future__ import annotations

import traceback
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Sequence, Type

from sqlalchemy.orm import Session

from backend.core.logging_config import logger
from backend.db.session import SessionLocal
from backend.models.analytics import NewsArticle
from .base import NewsCrawlerBase, RawNews
from .crawlers import ALL_CRAWLERS, MinifluxCrawler
from . import analyzer


@dataclass
class PipelineRunResult:
    total_fetched: int = 0
    total_inserted: int = 0
    total_skipped_dup: int = 0
    per_source: Dict[str, dict] = None
    errors: List[str] = None
    blocked_crawlers: List[str] = None
    active_crawlers: int = 0

    def __post_init__(self):
        if self.per_source is None: self.per_source = {}
        if self.errors is None: self.errors = []
        if self.blocked_crawlers is None: self.blocked_crawlers = []


class CrawlerHealthTracker:
    """爬虫健康状态跟踪器：记录连续失败次数，自动跳过被封锁的爬虫"""
    MAX_CONSECUTIVE_FAILURES = 3  # 连续失败3次后自动跳过

    def __init__(self):
        self._fail_counts: Dict[str, int] = {}
        self._success_counts: Dict[str, int] = {}
        self._last_success: Dict[str, float] = {}
        self._blocked: Dict[str, bool] = {}

    def record_success(self, source: str, count: int = 0):
        self._fail_counts[source] = 0
        self._success_counts[source] = self._success_counts.get(source, 0) + 1
        self._last_success[source] = time.time()
        if self._blocked.get(source):
            logger.info(f"[News/Health] 爬虫 {source} 已恢复正常")
        self._blocked[source] = False

    def record_failure(self, source: str, error: str = ""):
        self._fail_counts[source] = self._fail_counts.get(source, 0) + 1
        if self._fail_counts[source] >= self.MAX_CONSECUTIVE_FAILURES:
            if not self._blocked.get(source):
                logger.warning(f"[News/Health] 爬虫 {source} 连续失败 {self._fail_counts[source]} 次，已自动跳过 (最后错误: {error[:100]})")
            self._blocked[source] = True

    def is_blocked(self, source: str) -> bool:
        return self._blocked.get(source, False)

    def get_blocked_list(self) -> List[str]:
        return [s for s, b in self._blocked.items() if b]

    def get_health_report(self) -> Dict[str, dict]:
        return {
            s: {
                "consecutive_failures": self._fail_counts.get(s, 0),
                "total_successes": self._success_counts.get(s, 0),
                "blocked": self._blocked.get(s, False),
            }
            for s in set(list(self._fail_counts.keys()) + list(self._success_counts.keys()))
        }


_health_tracker = CrawlerHealthTracker()


class NewsPipeline:
    """
    采集 + 分析 + 入库。无状态：每次 run_once 都是独立事务。
    Miniflux 优先策略：先执行 Miniflux（可靠源），再并行其他爬虫。
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
            # 1) Miniflux 优先抓取 + 其他源并发
            raw_by_source: Dict[str, List[RawNews]] = self._concurrent_fetch(res)

            # 2) 已存在 source+source_id 的去重
            all_raw: List[RawNews] = []
            for src, items in raw_by_source.items():
                for r in items:
                    all_raw.append(r)
            res.total_fetched = len(all_raw)
            if not all_raw:
                logger.warning("[News/Pipeline] 所有源均未获取到新闻，建议检查 Miniflux 配置和爬虫健康状态")
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

        # 分离 Miniflux（优先）和其他爬虫
        miniflux_classes = []
        other_classes = []
        for cls in self.crawlers_classes:
            if cls == MinifluxCrawler:
                miniflux_classes.append(cls)
            else:
                other_classes.append(cls)

        # Step 1: 先执行 Miniflux（不跳过，不受健康状态影响）
        for cls in miniflux_classes:
            try:
                crawler = cls()
                src = crawler.SOURCE_DISPLAY
                items = crawler.crawl(self.lookback_hours) or []
                out[src] = list(items)
                res.per_source[src] = {"fetched": len(items), "status": "ok"}
                _health_tracker.record_success(src, len(items))
                logger.info(f"[News/Pipeline] Miniflux 获取 {len(items)} 条（优先源）")
            except Exception as e:
                err = f"Miniflux 抓取异常: {e}"
                logger.warning(f"[News/Pipeline] {err}")
                res.errors.append(err)
                res.per_source[src] = {"fetched": 0, "status": "error", "error": str(e)[:200]}
                _health_tracker.record_failure(src, str(e))

        # Step 2: 并发执行其他爬虫（跳过被封锁的）
        active_crawlers = []
        skipped_crawlers = []
        for cls in other_classes:
            try:
                display = cls.SOURCE_DISPLAY
            except AttributeError:
                display = cls.__name__
            if _health_tracker.is_blocked(display):
                skipped_crawlers.append(display)
                res.per_source[display] = {"fetched": 0, "status": "blocked"}
                continue
            active_crawlers.append(cls)

        res.blocked_crawlers = _health_tracker.get_blocked_list()
        res.active_crawlers = len(active_crawlers) + len(miniflux_classes)

        if skipped_crawlers:
            logger.info(f"[News/Pipeline] 跳过 {len(skipped_crawlers)} 个被封锁的爬虫: {skipped_crawlers}")

        with ThreadPoolExecutor(max_workers=self.max_workers) as ex:
            future_map = {}
            for cls in active_crawlers:
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
                    res.per_source[src] = {"fetched": len(items), "status": "ok"}
                    _health_tracker.record_success(src, len(items))
                except Exception as e:
                    err = f"抓取源 {src} 异常: {e}"
                    logger.warning(f"[News/Pipeline] {err}")
                    res.errors.append(err)
                    res.per_source[src] = {"fetched": 0, "status": "error", "error": str(e)[:200]}
                    _health_tracker.record_failure(src, str(e))
        return out

    def _match_source_code(self, source_name: str, display_to_code: Dict[str, int]) -> int:
        """根据 source_name 匹配 source_code，支持前缀匹配（如 'Miniflux RSS/CoinDesk' → 70）"""
        if source_name in display_to_code:
            return display_to_code[source_name]
        for display_name, code in display_to_code.items():
            if source_name.startswith(display_name):
                return code
        return 99

    def _dedupe_against_db(self, db: Session, items: List[RawNews], res: PipelineRunResult) -> List[RawNews]:
        """NewsArticle 存在 (source, source_id) 的直接跳过"""
        display_to_code: Dict[str, int] = {}
        for cls in self.crawlers_classes:
            display_to_code[cls.SOURCE_DISPLAY] = int(cls.SOURCE_CODE)

        # 生成 (source_code, source_id) 列表
        lookup_keys: List[tuple[int, str]] = []
        for r in items:
            code = self._match_source_code(r.source_name, display_to_code)
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
            code = self._match_source_code(r.source_name, display_to_code)
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
            code = self._match_source_code(raw.source_name, display_to_code)
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
                    code = self._match_source_code(raw.source_name, display_to_code)
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
