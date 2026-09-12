"""
回测相关异步任务 — Celery 队列: backtest
用于异步执行策略回测，避免长时间阻塞API
"""
from __future__ import annotations

from datetime import datetime

from celery import current_app as celery

from backend.core.logging_config import logger
from backend.db.session import session_maker


@celery.task(name="backend.tasks.backtest.run_backtest", bind=True)
def run_backtest(self, strategy_id: int, symbol: str, timeframe: str = "4h",
                 start_date: str = None, end_date: str = None,
                 initial_capital: float = 10000.0, leverage: int = 3):
    """异步执行策略回测"""
    try:
        from backend.services.backtest_engine import BacktestEngine

        logger.info(f"[Backtest-Task] 开始回测: strategy={strategy_id} symbol={symbol} tf={timeframe}")

        engine = BacktestEngine()
        with session_maker() as db:
            result = engine.run(
                db=db,
                strategy_id=strategy_id,
                symbol=symbol,
                timeframe=timeframe,
                start_date=start_date,
                end_date=end_date,
                initial_capital=initial_capital,
                leverage=leverage,
            )

        logger.info(
            f"[Backtest-Task] 回测完成: {symbol} "
            f"trades={result.get('total_trades', 0)} "
            f"win_rate={result.get('win_rate', 0):.2f} "
            f"total_return={result.get('total_return', 0):.2f}%"
        )
        return {
            "status": "ok",
            "strategy_id": strategy_id,
            "symbol": symbol,
            "timeframe": timeframe,
            "total_trades": result.get("total_trades", 0),
            "win_rate": result.get("win_rate", 0),
            "total_return": result.get("total_return", 0),
            "max_drawdown": result.get("max_drawdown", 0),
            "sharpe_ratio": result.get("sharpe_ratio", 0),
        }
    except Exception as e:
        logger.exception(f"[Backtest-Task] 回测失败: {e}")
        return {"status": "error", "msg": str(e)}
