"""
AI 相关异步任务 — Celery 队列: ai
用于异步AI分析、新闻AI深度分析、新闻情绪策略信号
"""
from __future__ import annotations

from datetime import datetime, timedelta

from celery import current_app as celery

from backend.core.logging_config import logger
from backend.db.session import session_maker


@celery.task(name="backend.tasks.ai.run_ai_analysis", bind=True)
def run_ai_analysis(self, analysis_type: str = "score", symbol: str = "BTC",
                    timeframe: str = "4h", manual_prompt: str = ""):
    """异步AI分析（不阻塞API响应）"""
    try:
        from backend.services.ai_failover import call_ai_unified
        from backend.exchanges.market import MarketManager
        from backend.models.analytics import NewsArticle

        symbol = symbol.upper()
        candles_snapshot = ""
        news_snapshot = ""

        # 获取K线快照
        mm = MarketManager.get_instance()
        klines = mm.get_klines(symbol, timeframe, limit=30)
        if klines and len(klines) > 0:
            lines = []
            for k in klines[-20:]:
                ts = k.open_time.timestamp() if hasattr(k, 'open_time') and k.open_time else 0
                ts_str = datetime.fromtimestamp(ts).strftime('%m-%d %H:%M') if ts else 'N/A'
                lines.append(f"  O={k.open:.4f} H={k.high:.4f} L={k.low:.4f} C={k.close:.4f} V={k.volume:.2f}  [{ts_str}]")
            candles_snapshot = "\n".join(lines)

        # 获取新闻快照
        cutoff = datetime.utcnow() - timedelta(hours=24)
        with session_maker() as db:
            articles = (
                db.query(NewsArticle)
                .filter(NewsArticle.published_at >= cutoff)
                .filter(NewsArticle.related_symbols.like(f'%"{symbol}"%'))
                .order_by(NewsArticle.published_at.desc())
                .limit(10)
                .all()
            )
            if articles:
                news_lines = []
                for a in articles[:10]:
                    sentiment_label = {0: "中性", 1: "偏多", -1: "偏空", 2: "偏空"}.get(a.sentiment, "未知")
                    news_lines.append(f"  [{sentiment_label}] {a.title[:80]}")
                news_snapshot = "\n".join(news_lines)

            # 调用AI
            result = call_ai_unified(
                db, analysis_type=analysis_type, symbol=symbol,
                timeframe=timeframe, manual_prompt=manual_prompt,
                candles_snapshot=candles_snapshot, news_snapshot=news_snapshot,
            )

        logger.info(f"[AI-Task] AI分析完成: {symbol} type={analysis_type} success={result.get('success')}")
        return {
            "status": "ok" if result.get("success") else "error",
            "symbol": symbol,
            "ai_source": result.get("source", ""),
            "ai_score": result.get("result", {}).ai_score if result.get("result") else None,
            "ai_direction": result.get("result", {}).ai_direction if result.get("result") else None,
        }
    except Exception as e:
        logger.exception(f"[AI-Task] AI分析失败: {e}")
        return {"status": "error", "msg": str(e)}


@celery.task(name="backend.tasks.ai.batch_news_ai_analysis", bind=True)
def batch_news_ai_analysis(self, hours: int = 6, limit: int = 20):
    """批量AI深度分析新闻（每2小时调度一次）"""
    try:
        from backend.services.news_ai_analyzer import batch_analyze_with_ai

        with session_maker() as db:
            result = batch_analyze_with_ai(db, hours=hours, limit=limit)

        logger.info(f"[AI-Task] 新闻AI分析完成: total={result.get('total', 0)} analyzed={result.get('analyzed', 0)}")
        return {"status": "ok", **result}
    except Exception as e:
        logger.exception(f"[AI-Task] 新闻AI批量分析失败: {e}")
        return {"status": "error", "msg": str(e)}


@celery.task(name="backend.tasks.ai.news_strategy_signal", bind=True)
def news_strategy_signal(self):
    """新闻情绪驱动的交易信号生成（每小时调度一次）"""
    try:
        from backend.services.news_strategy import NewsStrategyService

        with session_maker() as db:
            service = NewsStrategyService()
            result = service.generate_signals(db)

        logger.info(f"[AI-Task] 新闻策略信号生成完成: {result}")
        return {"status": "ok", "result": result}
    except Exception as e:
        logger.exception(f"[AI-Task] 新闻策略信号失败: {e}")
        return {"status": "error", "msg": str(e)}
