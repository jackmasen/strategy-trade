"""
交易引擎运行状态服务
提供策略执行、新闻采集、AI分析、订单状态等综合运行数据
"""
from datetime import datetime, timedelta
from fastapi import Request
from sqlalchemy.orm import Session
from sqlalchemy import func, desc

from backend.models.strategy import StrategyConfig, ScoreRecord
from backend.models.trade import TradeOrder, TradePosition
from backend.models.analytics import NewsArticle, AIAnalysisRecord


def get_engine_overview(db: Session) -> dict:
    """获取交易引擎综合运行状态"""
    now = datetime.now()

    # 1. 策略统计
    total_strategies = db.query(StrategyConfig).count()
    active_strategies = db.query(StrategyConfig).filter(
        StrategyConfig.is_active == True
    ).count()
    auto_strategies = db.query(StrategyConfig).filter(
        StrategyConfig.is_active == True,
        StrategyConfig.run_mode == 1,
    ).count()
    semi_auto_strategies = db.query(StrategyConfig).filter(
        StrategyConfig.is_active == True,
        StrategyConfig.run_mode == 2,
    ).count()
    simulate_strategies = db.query(StrategyConfig).filter(
        StrategyConfig.is_active == True,
        StrategyConfig.run_mode == 3,
    ).count()

    # 2. 今日评分记录数（策略执行强度）
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_score_count = db.query(ScoreRecord).filter(
        ScoreRecord.candle_close_time >= today_start
    ).count()

    # 最近1小时评分记录（判断引擎是否在正常运行）
    one_hour_ago = now - timedelta(hours=1)
    recent_score_count = db.query(ScoreRecord).filter(
        ScoreRecord.candle_close_time >= one_hour_ago
    ).count()

    # 最近一次评分时间
    latest_score = db.query(ScoreRecord).order_by(
        desc(ScoreRecord.candle_close_time)
    ).first()
    last_score_time = latest_score.candle_close_time.isoformat() if latest_score else None

    # 3. 持仓统计
    open_positions = db.query(TradePosition).filter(
        TradePosition.status == 1
    ).all()
    total_unrealized_pnl = sum(
        float(p.unrealized_pnl or 0) for p in open_positions
    )
    total_margin_used = sum(
        float(p.margin_used or 0) for p in open_positions
    )

    # 4. 今日订单统计
    today_orders = db.query(TradeOrder).filter(
        TradeOrder.created_at >= today_start
    ).all()
    today_order_count = len(today_orders)
    today_open_count = sum(1 for o in today_orders if o.order_type == 1)
    today_close_count = sum(1 for o in today_orders if o.order_type == 2)
    today_filled_count = sum(1 for o in today_orders if o.status in (2, 6, 7, 8))
    today_pending_count = sum(1 for o in today_orders if o.status in (0, 1, 3))
    today_realized_pnl = sum(
        float(o.realized_pnl or 0) for o in today_orders if o.order_type == 2
    )

    # 5. 新闻采集统计
    today_news_count = db.query(NewsArticle).filter(
        NewsArticle.published_at >= today_start
    ).count()
    latest_news = db.query(NewsArticle).order_by(
        desc(NewsArticle.published_at)
    ).first()
    last_news_time = latest_news.published_at.isoformat() if latest_news else None

    # 近24小时重要新闻数
    one_day_ago = now - timedelta(days=1)
    important_news_24h = db.query(NewsArticle).filter(
        NewsArticle.published_at >= one_day_ago,
        NewsArticle.impact_level >= 3,
    ).count()

    # 6. AI分析统计
    today_ai_count = db.query(AIAnalysisRecord).filter(
        AIAnalysisRecord.created_at >= today_start
    ).count()
    latest_ai = db.query(AIAnalysisRecord).order_by(
        desc(AIAnalysisRecord.created_at)
    ).first()
    last_ai_time = latest_ai.created_at.isoformat() if latest_ai else None

    # 7. 各品种评分分布（最近一次各品种的评分状态）
    symbol_scores = _get_latest_symbol_scores(db)

    # 8. 最近交易记录
    recent_orders = db.query(TradeOrder).order_by(
        desc(TradeOrder.created_at)
    ).limit(10).all()

    # 9. 活跃品种列表（从策略配置中提取）
    all_symbols = set()
    for s in db.query(StrategyConfig).filter(
        StrategyConfig.is_active == True
    ).all():
        if s.symbols:
            all_symbols.update(s.symbols)

    return {
        "generated_at": now.isoformat(),
        "strategies": {
            "total": total_strategies,
            "active": active_strategies,
            "auto": auto_strategies,
            "semi_auto": semi_auto_strategies,
            "simulate": simulate_strategies,
        },
        "score_engine": {
            "today_records": today_score_count,
            "last_hour_records": recent_score_count,
            "last_score_time": last_score_time,
            "is_running": recent_score_count > 0,
        },
        "positions": {
            "open_count": len(open_positions),
            "total_unrealized_pnl": round(total_unrealized_pnl, 2),
            "total_margin_used": round(total_margin_used, 2),
            "details": [
                {
                    "symbol": p.symbol,
                    "side": p.side,
                    "leverage": p.leverage,
                    "entry_price": float(p.entry_price or 0),
                    "mark_price": float(p.mark_price or 0),
                    "unrealized_pnl": float(p.unrealized_pnl or 0),
                    "pnl_ratio": float(p.pnl_ratio or 0),
                    "quantity_usdt": float(p.quantity_usdt or 0),
                }
                for p in open_positions
            ],
        },
        "orders": {
            "today_total": today_order_count,
            "today_open": today_open_count,
            "today_close": today_close_count,
            "today_filled": today_filled_count,
            "today_pending": today_pending_count,
            "today_realized_pnl": round(today_realized_pnl, 2),
        },
        "news": {
            "today_count": today_news_count,
            "last_24h_important": important_news_24h,
            "last_news_time": last_news_time,
        },
        "ai_analysis": {
            "today_count": today_ai_count,
            "last_analysis_time": last_ai_time,
        },
        "symbol_scores": symbol_scores,
        "active_symbols": sorted(list(all_symbols)),
        "recent_orders": [
            {
                "id": o.id,
                "symbol": o.symbol,
                "side": o.side,
                "order_type": o.order_type,
                "status": o.status,
                "trigger_reason": o.trigger_reason,
                "quantity_usdt": float(o.quantity_usdt or 0),
                "realized_pnl": float(o.realized_pnl or 0),
                "created_at": o.created_at.isoformat() if o.created_at else None,
            }
            for o in recent_orders
        ],
    }


def _get_latest_symbol_scores(db: Session) -> list:
    """获取各品种最新评分（按策略分组）"""
    # 查询最近24小时内各品种的最新评分记录
    one_day_ago = datetime.now() - timedelta(days=1)
    records = db.query(ScoreRecord).filter(
        ScoreRecord.candle_close_time >= one_day_ago
    ).order_by(
        ScoreRecord.symbol,
        ScoreRecord.timeframe,
        desc(ScoreRecord.candle_close_time)
    ).all()

    # 按品种+周期去重，取最新一条
    seen = {}
    for r in records:
        key = f"{r.symbol}_{r.timeframe}"
        if key not in seen:
            seen[key] = r

    result = []
    for key, r in seen.items():
        result.append({
            "symbol": r.symbol,
            "timeframe": r.timeframe,
            "score_total": r.score_total,
            "score_technical": r.score_technical,
            "score_news": r.score_news,
            "score_ai": r.score_ai,
            "direction": r.suggested_direction,
            "close_price": float(r.candle_close_price or 0),
            "candle_time": r.candle_close_time.isoformat(),
            "trigger_trade": r.trigger_trade,
        })

    return sorted(result, key=lambda x: x["symbol"])


def get_scheduler_status(request: Request) -> dict:
    """获取定时任务运行状态"""
    scheduler = getattr(request.app.state, "scheduler", None)

    if scheduler is None:
        return {
            "enabled": False,
            "mode": "none",
            "tasks": [],
        }

    try:
        jobs = scheduler.get_jobs()
        job_info = []
        for job in jobs:
            next_run = job.next_run_time.isoformat() if job.next_run_time else None
            # 从job id映射到中文名称
            task_map = {
                "news_crawl": {"name": "新闻采集", "icon": "📰", "interval": "30分钟"},
                "news_ai_analysis": {"name": "AI深度分析", "icon": "🧠", "interval": "2小时"},
                "data_cleanup": {"name": "数据清理", "icon": "🧹", "interval": "每天03:00"},
                "news_ai_strategy": {"name": "新闻AI策略", "icon": "📊", "interval": "1小时"},
                "risk_monitor": {"name": "平仓风控巡检", "icon": "🛡️", "interval": "30秒"},
                "strategy_auto_run": {"name": "策略自动执行", "icon": "⚡", "interval": "1分钟"},
                "proxy_refresh": {"name": "代理池刷新", "icon": "🔄", "interval": "5分钟"},
                "proxy_health_check": {"name": "代理健康检测", "icon": "🔍", "interval": "10分钟"},
            }
            info = task_map.get(job.id, {"name": job.id, "icon": "⚙️", "interval": "未知"})
            job_info.append({
                "id": job.id,
                "name": info["name"],
                "icon": info["icon"],
                "interval": info["interval"],
                "status": "running",
                "next_run_time": next_run,
            })

        return {
            "enabled": True,
            "mode": "apscheduler",
            "running": scheduler.running,
            "task_count": len(job_info),
            "tasks": job_info,
        }
    except Exception as e:
        return {
            "enabled": True,
            "mode": "apscheduler",
            "running": False,
            "error": str(e),
            "tasks": [],
        }
