"""
交易审计日志服务
记录下单/平仓/风控完整上下文，用于审计追踪和事后分析
"""
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from backend.core.logging_config import logger
from backend.models.analytics import TradeAuditLog


def log_trade_event(
    db: Session,
    *,
    action_type: int,
    action_desc: str = "",
    user_id: Optional[int] = None,
    exchange_account_id: Optional[int] = None,
    strategy_id: Optional[int] = None,
    order_id: Optional[int] = None,
    position_id: Optional[int] = None,
    symbol: Optional[str] = None,
    side: Optional[int] = None,
    price: Optional[float] = None,
    quantity: Optional[float] = None,
    market_snapshot: Optional[dict] = None,
    position_snapshot: Optional[dict] = None,
    strategy_snapshot: Optional[dict] = None,
    factor_scores: Optional[dict] = None,
    extra: Optional[dict] = None,
) -> Optional[TradeAuditLog]:
    """
    记录一条交易审计日志

    Args:
        action_type: TradeAuditLog.ACTION_*
        action_desc: 动作描述
        user_id: 用户ID
        exchange_account_id: 交易所子账号ID
        strategy_id: 策略ID
        order_id: 关联订单ID
        position_id: 关联持仓ID
        symbol: 品种
        side: 方向 1-多 2-空
        price: 价格
        quantity: 数量
        market_snapshot: 市场数据快照
        position_snapshot: 持仓状态快照
        strategy_snapshot: 策略参数快照
        factor_scores: 7因子评分快照
        extra: 扩展字段
    """
    try:
        log = TradeAuditLog(
            user_id=user_id,
            exchange_account_id=exchange_account_id,
            strategy_id=strategy_id,
            order_id=order_id,
            position_id=position_id,
            action_type=action_type,
            action_desc=action_desc,
            symbol=symbol,
            side=side,
            price=Decimal(str(price)) if price is not None else Decimal(0),
            quantity=Decimal(str(quantity)) if quantity is not None else Decimal(0),
            market_snapshot=market_snapshot or {},
            position_snapshot=position_snapshot or {},
            strategy_snapshot=strategy_snapshot or {},
            factor_scores=factor_scores or {},
            extra=extra or {},
        )
        db.add(log)
        db.commit()
        return log
    except Exception as e:
        logger.warning(f"[TradeAudit] 审计日志写入失败: {e}")
        db.rollback()
        return None


def snapshot_position(pos) -> dict:
    """从TradePosition对象生成快照"""
    return {
        "id": pos.id,
        "symbol": pos.symbol,
        "side": pos.side,
        "leverage": pos.leverage,
        "entry_price": float(pos.entry_price or 0),
        "mark_price": float(pos.mark_price or 0),
        "quantity_contracts": float(pos.quantity_contracts or 0),
        "margin_used": float(pos.margin_used or 0),
        "tp_price": float(pos.tp_price or 0) if pos.tp_price else None,
        "sl_price": float(pos.sl_price or 0) if pos.sl_price else None,
        "unrealized_pnl": float(pos.unrealized_pnl or 0),
        "pnl_ratio": float(pos.pnl_ratio or 0),
        "trailing_enabled": int(pos.trailing_enabled or 0),
        "trailing_mode": int(pos.trailing_mode or 0),
        "trailing_high_price": float(pos.trailing_high_price or 0) if pos.trailing_high_price else None,
    }


def snapshot_strategy(strategy) -> dict:
    """从StrategyConfig对象生成快照"""
    if not strategy:
        return {}
    return {
        "id": strategy.id,
        "name": getattr(strategy, "name", ""),
        "score_threshold": float(strategy.score_threshold or 5.0),
        "weight_technical": float(strategy.weight_technical or 0),
        "weight_news": float(strategy.weight_news or 0),
        "weight_ai": float(strategy.weight_ai or 0),
        "tp_ratio": float(strategy.tp_ratio or 5.0),
        "sl_ratio": float(strategy.sl_ratio or 2.0),
        "leverage_fixed": int(strategy.leverage_fixed or 3),
    }


def snapshot_market(mark_price: float, symbol: str, extra: dict = None) -> dict:
    """生成市场数据快照"""
    snap = {
        "symbol": symbol,
        "mark_price": mark_price,
        "timestamp": datetime.utcnow().isoformat(),
    }
    if extra:
        snap.update(extra)
    return snap
