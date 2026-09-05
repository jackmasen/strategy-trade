"""
Celery 应用 - 异步任务 & 定时调度
- Worker: 处理下单、回测、AI分析、新闻采集等耗时任务
- Beat:   周期性触发评分计算、止盈止损巡检、日报生成等
使用:
    celery -A backend.core.celery_app worker --loglevel=info -P prefork -c 4
    celery -A backend.core.celery_app beat  --loglevel=info
"""
from __future__ import annotations

import os
from celery import Celery
from celery.schedules import crontab
from kombu import Exchange, Queue

from backend.config import get_settings

settings = get_settings()

# -------- 实例 --------
app = Celery(
    "strategy-trade",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
)

# -------- 通用配置 --------
app.conf.update(
    timezone="Asia/Shanghai",
    enable_utc=False,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,
    task_time_limit=30 * 60,          # 单任务最长30分钟（回测）
    task_soft_time_limit=28 * 60,
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=200,   # 防止内存泄漏
    worker_concurrency=4,
    result_expires=86400,             # 结果保留1天
    # 队列
    task_queues=(
        Queue("default",   Exchange("default"),   routing_key="default"),
        Queue("trade",     Exchange("trade"),     routing_key="trade.#"),
        Queue("ai",        Exchange("ai"),        routing_key="ai.#"),
        Queue("backtest",  Exchange("backtest"),  routing_key="backtest.#"),
        Queue("scheduled", Exchange("scheduled"), routing_key="scheduled.#"),
    ),
    task_routes={
        "backend.tasks.trade.*":       {"queue": "trade"},
        "backend.tasks.ai.*":          {"queue": "ai"},
        "backend.tasks.backtest.*":    {"queue": "backtest"},
        "backend.tasks.scheduled.*":   {"queue": "scheduled"},
    },
    # 定时任务（Beat）
    beat_schedule={
        # --- 行情 + 评分（每 1 分钟） ---
        "update-score-every-min": {
            "task": "backend.tasks.scheduled.update_all_scores",
            "schedule": 60.0,
            "options": {"queue": "scheduled"},
        },
        # --- 止盈止损巡检（每 30 秒） ---
        "risk-monitor": {
            "task": "backend.tasks.scheduled.risk_monitor",
            "schedule": 30.0,
            "options": {"queue": "scheduled"},
        },
        # --- 新闻采集（每 5 分钟） ---
        "news-crawl": {
            "task": "backend.tasks.scheduled.crawl_news",
            "schedule": 300.0,
            "options": {"queue": "scheduled"},
        },
        # --- 日报（每日 00:05） ---
        "daily-report": {
            "task": "backend.tasks.scheduled.generate_daily_report",
            "schedule": crontab(hour=0, minute=5),
            "options": {"queue": "scheduled"},
        },
    },
)

# -------- 自动发现任务（需要先有 backend/tasks 包） --------
# 结构示例：
#   backend/tasks/__init__.py
#   backend/tasks/trade.py      -> place_order, close_position
#   backend/tasks/ai.py         -> ai_analysis, sentiment_analysis
#   backend/tasks/backtest.py   -> run_backtest
#   backend/tasks/scheduled.py  -> update_all_scores, risk_monitor, crawl_news, generate_daily_report
app.autodiscover_tasks(["backend.tasks"], force=True)


# -------- 基础示例任务（用于连通性测试） --------
@app.task(bind=True, name="core.ping", ignore_result=False)
def ping(self, x: int = 0):
    """测试任务：收到什么回什么"""
    return {"pong": x, "worker": os.getpid()}


@app.task(bind=True, name="core.error_test", ignore_result=False)
def error_test(self):
    """测试异常重试"""
    raise RuntimeError("故意出错 - 测试重试")
