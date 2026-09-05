"""
交易订单 / 持仓 路由
GET    /trades/orders            订单列表
POST   /trades/orders/manual     手动下单
POST   /trades/orders/{oid}/cancel 撤单
GET    /trades/positions         当前持仓
POST   /trades/positions/{pid}/close 手动平仓
GET    /trades/history           已平仓历史
GET    /trades/overview          交易总览（Dashboard用）
"""
import logging
from datetime import datetime, date
from decimal import Decimal
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func, case
from pydantic import BaseModel, Field

from backend.db.session import get_db
from backend.core.auth import get_current_user, require_editor, require_trader
from backend.core.exceptions import (
    NotFoundException, ParameterException, RiskControlException, success, BizException,
)
from backend.core.security import decrypt_api_key
from backend.core.schemas import ApiResponse, PaginationParams, paginate
from backend.models.user import User
from backend.models.trade import TradeOrder, TradePosition
from backend.models.exchange import ExchangeAccount
from backend.exchanges.base import ExchangeClientBase
from backend.exchanges.market import MarketManager
from backend.exchanges._types import SIDE_LONG, SIDE_SHORT, ORDER_TYPE_MARKET

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/trades", tags=["交易订单/持仓"])


SYMBOL_LEVERAGE_LIMITS = {
    # 加密货币
    "BTC": 10, "ETH": 10, "SOL": 10,
    "SAND": 10, "HBAR": 10,
    # 贵金属/能源
    "XAU": 5, "XAG": 5, "WTI": 5,
    # 美股-科技（代币化股票杠杆通常较低）
    "TSLA": 5, "NVDA": 5, "AAPL": 5, "MSFT": 5,
    # 美股-中概
    "TCEHY": 5,
}


# =========================================================
# 辅助
# =========================================================
class ManualOrderReq(BaseModel):
    exchange_account_id: int
    symbol: str = Field(..., min_length=2, max_length=16)
    side: int = Field(..., ge=1, le=2, description="1-做多 2-做空")
    quantity_usdt: float = Field(..., gt=0, description="下单名义金额USDT")
    leverage: int = Field(default=3, ge=1, le=20)
    margin_mode: int = Field(default=1, description="1-全仓 2-逐仓")
    tp_price: float | None = None
    sl_price: float | None = None
    tp_ratio_pct: float = 4.0
    sl_ratio_pct: float = 2.0
    order_type: int = 1  # 1市价 2限价


def _get_account_checked(db: Session, user: User, aid: int) -> ExchangeAccount:
    acc = db.query(ExchangeAccount).filter(
        ExchangeAccount.id == aid,
        (ExchangeAccount.user_id == user.id) | (user.role == 1),
    ).first()
    if not acc:
        raise NotFoundException("交易所子账号不存在")
    if acc.status != 1:
        raise ParameterException("子账号未启用")
    # 审计日志：管理员操作他人账号时记录
    if user.role == 1 and acc.user_id != user.id:
        logger.warning(
            f"[AUDIT] 管理员 {user.username}(id={user.id}) 访问了用户 "
            f"id={acc.user_id} 的交易所子账号 id={acc.id} ({acc.sub_account_name})"
        )
    return acc


def _build_client(acc: ExchangeAccount) -> ExchangeClientBase:
    client = ExchangeClientBase.create(
        exchange=acc.exchange,
        api_key=decrypt_api_key(acc.api_key) or "",
        api_secret=decrypt_api_key(acc.api_secret) or "",
        passphrase=decrypt_api_key(acc.api_passphrase) or "",
        testnet=bool(acc.testnet),
        exchange_account_id=acc.id,
    )
    client.connect()
    MarketManager.get_instance().register_client(client)
    return client


def _calc_tp_sl(side: int, entry: float, tp_ratio_pct: float, sl_ratio_pct: float,
                 tp_price: float | None, sl_price: float | None) -> tuple[float, float]:
    # 1多 2空；多单 TP > entry，SL < entry；空单反之
    mult = 0.01
    tp = tp_price
    sl = sl_price
    if not tp:
        if side == SIDE_LONG:
            tp = entry * (1 + tp_ratio_pct * mult)
        else:
            tp = entry * (1 - tp_ratio_pct * mult)
    if not sl:
        if side == SIDE_LONG:
            sl = entry * (1 - sl_ratio_pct * mult)
        else:
            sl = entry * (1 + sl_ratio_pct * mult)
    return round(tp, 8), round(sl, 8)


# ------------------- 订单 -------------------

@router.get("/orders", response_model=ApiResponse[dict])
def list_orders(
    q: PaginationParams = Depends(),
    account_id: int | None = None,
    symbol: str | None = None,
    side: int | None = None,
    status: int | None = None,
    order_type: int | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """订单列表"""
    query = db.query(TradeOrder)
    if user.role != 1:
        query = query.filter(TradeOrder.user_id == user.id)
    if account_id:
        query = query.filter(TradeOrder.exchange_account_id == account_id)
    if symbol:
        query = query.filter(TradeOrder.symbol == symbol.upper())
    if side is not None:
        query = query.filter(TradeOrder.side == side)
    if status is not None:
        query = query.filter(TradeOrder.status == status)
    if order_type is not None:
        query = query.filter(TradeOrder.order_type == order_type)
    if start:
        query = query.filter(TradeOrder.created_at >= start)
    if end:
        query = query.filter(TradeOrder.created_at <= end)
    res = paginate(query, q.page, q.page_size, q.order_by)
    return success(res)


@router.get("/ticker/{symbol}")
def get_ticker(symbol: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """获取指定品种的最新行情（bid/ask/last），用于手动下单实时定价"""
    symbol = symbol.upper()
    acc = db.query(ExchangeAccount).filter(ExchangeAccount.status == 1).order_by(ExchangeAccount.id).first()
    if not acc:
        raise NotFoundException("没有可用的交易所账号")
    client = _build_client(acc)
    ticker = client.fetch_ticker(symbol)
    return success({
        "symbol": symbol,
        "last_price": ticker.last_price,
        "bid_price": ticker.bid_price,
        "ask_price": ticker.ask_price,
        "change_pct": ticker.change_pct if hasattr(ticker, 'change_pct') else 0,
    })


@router.post("/orders/manual")
def manual_order(
    req: ManualOrderReq,
    db: Session = Depends(get_db),
    user: User = Depends(require_editor),
):
    """
    手动下单 → 调用交易所接口
    步骤： 1) 校验风控；2) 获取最新价；3) 下单（市价开仓 + TP/SL）；4) 落库订单与持仓
    """
    acc = _get_account_checked(db, user, req.exchange_account_id)
    symbol = req.symbol.upper()
    leverage_limit = min(SYMBOL_LEVERAGE_LIMITS.get(symbol, 5), acc.leverage_max)
    if req.leverage > leverage_limit:
        raise ParameterException(f"{symbol} 最大允许杠杆 {leverage_limit} 倍")
    leverage = req.leverage
    client = _build_client(acc)

    # 风控：不能反向持仓（同一 symbol 有 opposite 仓位则拒绝）
    opposite_side = SIDE_SHORT if req.side == SIDE_LONG else SIDE_LONG
    conflict = db.query(TradePosition).filter(
        TradePosition.exchange_account_id == acc.id,
        TradePosition.symbol == symbol,
        TradePosition.status == 1,
        TradePosition.side == opposite_side,
    ).first()
    if conflict:
        raise RiskControlException(f"{symbol} 已有反向持仓，请先平仓再下单")

    # 1) 获取最新价
    ticker = client.fetch_ticker(symbol)
    entry_price = ticker.last_price
    bid_price = ticker.bid_price
    ask_price = ticker.ask_price
    # 做多以卖价(ask)成交，做空以买价(bid)成交
    execution_price = ask_price if req.side == SIDE_LONG else (bid_price or ask_price)
    if entry_price <= 0:
        raise BizException("无法获取最新行情，请稍后重试")
    tp, sl = _calc_tp_sl(req.side, execution_price or entry_price,
                           req.tp_ratio_pct, req.sl_ratio_pct,
                           req.tp_price, req.sl_price)

    # 2) 计算下单数量（名义金额 / 最新价）
    qty = req.quantity_usdt / entry_price

    # 余额校验（风控：单笔保证金不超过可用5%
    bal = client.fetch_balance()
    margin_need = qty * entry_price / leverage
    if margin_need > float(bal.available) * 0.05:
        raise RiskControlException(
            f"单笔保证金不得超过可用余额5%：需要 {margin_need:.2f} USDT，最大允许 {float(bal.available)*0.05:.2f} USDT"
        )

    # 3) 设置杠杆和保证金模式（交易所侧）
    lev_ok = client.set_leverage(symbol, leverage)
    if not lev_ok:
        logger.warning(f"[Trade] 杠杆设置失败(symbol={symbol} lev={leverage}), 继续下单但可能使用默认杠杆")
    try:
        client._set_margin_mode(symbol, "cross" if req.margin_mode == 1 else "isolated")
    except Exception as e:
        logger.warning(f"[Trade] 保证金模式设置失败(symbol={symbol} mode={'cross' if req.margin_mode == 1 else 'isolated'}): {e}")

    # 4) 下单 + TP/SL
    order = TradeOrder(
        exchange_account_id=acc.id,
        strategy_id=None,
        user_id=user.id,
        exchange=acc.exchange,
        client_order_id="",
        symbol=symbol,
        side=req.side,
        order_type=1,  # 开仓
        leverage=leverage,
        quantity_contracts=Decimal(str(qty)),
        quantity_usdt=Decimal(str(req.quantity_usdt)),
        avg_fill_price=Decimal(str(entry_price)),
        order_price=Decimal(str(entry_price)),
        tp_price=Decimal(str(tp)),
        sl_price=Decimal(str(sl)),
        margin_used=Decimal(str(margin_need)),
        trigger_reason=1,  # 手动
        status=0,
        error_msg="手动下单",
    )
    db.add(order)
    db.commit()
    db.refresh(order)

    # 5) 调用交易所
    try:
        created = client.place_order(
            symbol=symbol,
            side=req.side,
            order_type=ORDER_TYPE_MARKET,
            quantity=qty,
            price=0,
            take_profit_price=tp,
            stop_loss_price=sl,
            leverage=leverage,
            margin_mode="cross" if req.margin_mode == 1 else "isolated",
            client_order_id=f"manual_{order.id}_{datetime.now().strftime('%H%M%S')}",
        )
        order.client_order_id = created.client_order_id or ""
        order.exchange_order_id = created.exchange_order_id or ""
        order.status = 2  # 已成交
        order.avg_fill_price = Decimal(str(created.avg_fill_price or entry_price))
        order.quantity_contracts = Decimal(str(created.filled_quantity or qty))
        order.filled_at = datetime.now()
        order.submitted_at = datetime.now()
    except Exception as e:
        order.status = 5  # 失败
        order.error_msg = str(e)[:500]
        db.commit()
        raise BizException(f"下单失败: {e}", code=5020)

    # 5.1) 提交订单更新（确保持仓同步失败时不丢失订单数据）
    db.commit()

    # 6) 同步持仓并创建/更新 TradePosition
    created_pos = None
    try:
        positions = client.fetch_positions()
        matched = next(
            (p for p in positions if p.symbol == symbol and p.side == req.side), None
        )
        existing = db.query(TradePosition).filter(
            TradePosition.exchange_account_id == acc.id,
            TradePosition.symbol == symbol,
            TradePosition.side == req.side,
            TradePosition.status == 1,
        ).first()
        if matched:
            if not existing:
                created_pos = TradePosition(
                    user_id=user.id,
                    exchange_account_id=acc.id,
                    strategy_id=None,
                    exchange=acc.exchange,
                    symbol=symbol,
                    side=req.side,
                    leverage=leverage,
                    entry_price=Decimal(str(matched.entry_price or entry_price)),
                    mark_price=Decimal(str(matched.mark_price or entry_price)),
                    quantity_contracts=Decimal(str(matched.quantity or qty)),
                    quantity_usdt=Decimal(str(req.quantity_usdt)),
                    margin_used=Decimal(str(matched.margin or margin_need)),
                    tp_price=Decimal(str(matched.take_profit_price or tp)),
                    sl_price=Decimal(str(matched.stop_loss_price or sl)),
                    unrealized_pnl=Decimal(str(matched.unrealized_pnl or 0)),
                    realized_pnl=Decimal(0),
                    pnl_ratio=float(matched.unrealized_pnl_pct or 0),
                    max_drawdown_ratio=0.0,
                    fee_total=Decimal(0),
                    status=1,
                    close_reason=None,
                    entry_score=None,
                    entry_time=datetime.fromtimestamp(matched.open_timestamp_ms / 1000) if matched.open_timestamp_ms > 0 else datetime.now(),
                    close_time=None,
                    close_price=None,
                    holding_minutes=0,
                )
                db.add(created_pos)
            else:
                # 更新已有同方向持仓
                existing.entry_price = Decimal(str(matched.entry_price or existing.entry_price))
                existing.mark_price = Decimal(str(matched.mark_price or existing.mark_price))
                existing.quantity_contracts = Decimal(str(matched.quantity or existing.quantity_contracts))
                existing.margin_used = Decimal(str(matched.margin or existing.margin_used))
                # 保守设置 TP/SL：取两者更保守值
                if req.side == SIDE_LONG:
                    existing.tp_price = Decimal(str(min(float(existing.tp_price or 1e18), tp)))
                    existing.sl_price = Decimal(str(max(float(existing.sl_price or 0), sl)))
                else:
                    existing.tp_price = Decimal(str(max(float(existing.tp_price or 0), tp)))
                    existing.sl_price = Decimal(str(min(float(existing.sl_price or 1e18), sl)))
                existing.unrealized_pnl = Decimal(str(matched.unrealized_pnl or existing.unrealized_pnl))
                existing.pnl_ratio = float(matched.unrealized_pnl_pct or existing.pnl_ratio)
                if float(existing.unrealized_pnl) < 0:
                    existing.max_drawdown_ratio = max(
                        float(existing.max_drawdown_ratio or 0),
                        abs(float(existing.pnl_ratio)),
                    )
        db.commit()
        if created_pos:
            db.refresh(created_pos)
            order.position_id = created_pos.id
            db.commit()
    except Exception as e_sync:
        logger.error(f"持仓同步失败(order_id={order.id}): {e_sync} — 订单已成交但持仓未录入，需人工核查")
        db.rollback()
        # Return success but with warning
        return success({
            "order_id": order.id,
            "exchange_order_id": order.exchange_order_id,
            "position_id": order.position_id,
            "status": order.status,
            "symbol": symbol,
            "side": req.side,
            "entry_price": entry_price,
            "execution_price": execution_price,
            "bid_price": bid_price,
            "ask_price": ask_price,
            "tp": tp, "sl": sl,
            "qty": qty,
            "margin": round(margin_need, 4),
            "warning": "订单已成交，但持仓同步失败，请检查持仓列表",
        }, message="下单成功，持仓同步异常")

    return success({
        "order_id": order.id,
        "exchange_order_id": order.exchange_order_id,
        "position_id": order.position_id,
        "status": order.status,
        "symbol": symbol,
        "side": req.side,
        "entry_price": entry_price,
        "execution_price": execution_price,
        "bid_price": bid_price,
        "ask_price": ask_price,
        "tp": tp, "sl": sl,
        "qty": qty,
        "margin": round(margin_need, 4),
        "message": "下单成功",
    })


@router.post("/orders/{oid}/cancel")
def cancel_order(oid: int, db: Session = Depends(get_db), user: User = Depends(require_editor)):
    """撤单：仅对挂单（非挂单的订单直接本地标取消"""
    order = db.query(TradeOrder).filter(TradeOrder.id == oid).first()
    if not order:
        raise NotFoundException("订单不存在")
    if user.role != 1:
        acc = _get_account_checked(db, user, order.exchange_account_id)
        # 权限复用
    if order.status in (2, 5, 6):
        return success(message=f"订单状态 {order.status} 不允许撤单")
    # 有 exchange_order_id 就尝试交易所撤单
    if order.exchange_order_id:
        try:
            acc = db.query(ExchangeAccount).filter(ExchangeAccount.id == order.exchange_account_id).first()
            client = _build_client(acc)
            client.cancel_order(order.symbol, order.exchange_order_id)
        except Exception:
            pass
    order.status = 4
    db.commit()
    return success(message="撤单成功")


# ------------------- 持仓 -------------------

@router.get("/positions", response_model=ApiResponse[dict])
def list_positions(
    account_id: int | None = None,
    symbol: str | None = None,
    status: int | None = 1,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """持仓列表（status=0 返回全部，默认仅持仓中）"""
    query = db.query(TradePosition)
    if status is not None and status > 0:
        query = query.filter(TradePosition.status == status)
    if user.role != 1:
        query = query.filter(TradePosition.user_id == user.id)
    if account_id:
        query = query.filter(TradePosition.exchange_account_id == account_id)
    if symbol:
        query = query.filter(TradePosition.symbol == symbol.upper())
    items = query.order_by(TradePosition.entry_time.desc()).limit(200).all()
    return success({
        "total": len(items),
        "items": [
            {
                "id": p.id,
                "symbol": p.symbol,
                "side": p.side,
                "side_name": "多" if p.side == 1 else "空",
                "entry_price": float(p.entry_price),
                "mark_price": float(p.mark_price),
                "quantity": float(p.quantity_contracts),
                "quantity_usdt": float(p.quantity_usdt or 0),
                "leverage": p.leverage,
                "margin": float(p.margin_used),
                "unrealized_pnl": float(p.unrealized_pnl),
                "unrealized_pnl_pct": float(p.pnl_ratio),
                "tp": float(p.tp_price or 0),
                "sl": float(p.sl_price or 0),
                "max_drawdown_ratio": float(p.max_drawdown_ratio or 0),
                "open_time": p.entry_time.isoformat() if p.entry_time else None,
                "realized_pnl": float(p.realized_pnl or 0),
                "fee_total": float(p.fee_total or 0),
                "entry_score": float(p.entry_score or 0),
                "holding_minutes": p.holding_minutes or 0,
                "strategy_id": p.strategy_id,
                "exchange": p.exchange,
                "status": p.status,
                "status_name": "持仓中" if p.status == 1 else "已平仓",
                "close_price": float(p.close_price or 0),
                "liquidation_price": 0,
                "raw_position_id": "",
            } for p in items
        ]
    })


@router.post("/positions/{pid}/close")
def close_position(
    pid: int,
    close_price: float | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_trader),
):
    """手动平仓：调用交易所平仓接口并更新持仓状态
    - 优先调用真实交易所API
    - 演示模式/API不可用时 fallback 到模拟平仓（用当前标记价计算）
    """
    import random

    pos = db.query(TradePosition).filter(TradePosition.id == pid).first()
    if not pos or pos.status != 1:
        raise NotFoundException("持仓不存在或已平仓")
    # 权限
    if user.role != 1:
        _get_account_checked(db, user, pos.exchange_account_id)
    acc = db.query(ExchangeAccount).filter(ExchangeAccount.id == pos.exchange_account_id).first()

    is_mock_mode = False
    close_side = SIDE_SHORT if pos.side == SIDE_LONG else SIDE_LONG

    # 1) 尝试调用真实交易所
    try:
        client = _build_client(acc)
        # 先撤销 TP/SL 挂单防止冲突
        try:
            client.cancel_all_open_orders(pos.symbol)
        except Exception as e:
            logger.warning(f"[Trade] 平仓前撤销挂单失败(position_id={pos.id} symbol={pos.symbol}): {e}")

        # 市价平仓（反方向）
        closed = client.place_order(
            symbol=pos.symbol,
            side=close_side,
            order_type=ORDER_TYPE_MARKET,
            quantity=float(pos.quantity_contracts),
            leverage=pos.leverage,
            client_order_id=f"close_{pid}_{datetime.now().strftime('%H%M%S')}",
        )
        cp = float(closed.avg_fill_price or close_price or pos.mark_price)
        pos.close_price = Decimal(str(cp))
    except Exception as e:
        # 演示模式 fallback：用标记价模拟平仓（确保演示环境可正常操作）
        if acc.testnet or "NameResolutionError" in str(e) or "ConnectionError" in str(e):
            is_mock_mode = True
            logger.warning(f"[Trade] 演示模式平仓: position={pos.id}, reason={e}")
            # 使用当前标记价，没有则在开仓价附近随机波动模拟
            entry = float(pos.entry_price or 0)
            mark = float(pos.mark_price or 0)
            cp = close_price or mark
            if cp <= 0:
                direction = random.choice([-1, 1])
                cp = entry * (1 + direction * random.uniform(0.001, 0.008))
            pos.close_price = Decimal(str(cp))
        else:
            raise BizException(f"平仓失败: {e}", code=5021)

    # 2) 标记平仓原因 & 计算盈亏
    if pos.side == 1:  # 多仓
        pnl = (float(pos.close_price) - float(pos.entry_price)) * float(pos.quantity_contracts)
    else:  # 空仓
        pnl = (float(pos.entry_price) - float(pos.close_price)) * float(pos.quantity_contracts)
    pos.realized_pnl = Decimal(str(pnl))
    margin_used = float(pos.margin_used) or 0
    if margin_used <= 0:
        # 保证金为0时，用名义金额的5%作为参考（避免除零）
        margin_used = abs(float(pos.quantity_usdt) or 100) * 0.05
    pos.pnl_ratio = round(pnl / margin_used * 100, 4) if margin_used > 0 else 0.0
    pos.status = 2
    pos.close_reason = 1  # 手动
    pos.close_time = datetime.now()
    # 持仓时长
    if pos.entry_time:
        pos.holding_minutes = int((pos.close_time - pos.entry_time).total_seconds() // 60)
    pos.max_drawdown_ratio = max(float(pos.max_drawdown_ratio or 0), abs(float(pos.pnl_ratio)) if pnl < 0 else 0)

    try:
        db.commit()
    except Exception as e:
        logger.critical(
            f"平仓DB提交失败(position_id={pos.id}) — 交易所已平仓但数据库未更新!"
            f"需人工核查防止重复平仓: {e}"
        )
        db.rollback()
        # Re-raise so the API returns an error, prompting manual intervention
        raise
    return success({
        "pid": pos.id,
        "close_price": float(pos.close_price),
        "realized_pnl": float(pos.realized_pnl),
        "pnl_ratio_pct": round(float(pos.pnl_ratio), 4),
        "message": "平仓完成" + ("（演示模式）" if is_mock_mode else ""),
        "mock_mode": is_mock_mode,
    })


@router.put("/positions/{pid}/tpsl")
def update_tpsl(
    pid: int,
    tp_price: float | None = None,
    sl_price: float | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_trader),
):
    """调整持仓止盈止损价"""
    pos = db.query(TradePosition).filter(TradePosition.id == pid).first()
    if not pos or pos.status != 1:
        raise NotFoundException("持仓不存在或已平仓")
    if user.role != 1:
        _get_account_checked(db, user, pos.exchange_account_id)

    old_tp = float(pos.tp_price or 0)
    old_sl = float(pos.sl_price or 0)

    if tp_price is not None:
        pos.tp_price = Decimal(str(tp_price))
    if sl_price is not None:
        pos.sl_price = Decimal(str(sl_price))

    db.commit()
    return success({
        "pid": pid,
        "old_tp": old_tp,
        "new_tp": float(pos.tp_price or 0),
        "old_sl": old_sl,
        "new_sl": float(pos.sl_price or 0),
        "message": "TP/SL已更新",
    })


@router.get("/history")
def trade_history(
    q: PaginationParams = Depends(),
    symbol: str | None = None,
    side: int | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """已平仓交易历史（用于盈亏统计）"""
    query = db.query(TradePosition).filter(TradePosition.status != 1)
    if user.role != 1:
        query = query.filter(TradePosition.user_id == user.id)
    if symbol:
        query = query.filter(TradePosition.symbol == symbol.upper())
    if side is not None:
        query = query.filter(TradePosition.side == side)
    if start:
        query = query.filter(TradePosition.close_time >= start)
    if end:
        query = query.filter(TradePosition.close_time <= end)
    res = paginate(query, q.page, q.page_size, "-close_time")
    return success(res)


@router.get("/overview")
def trade_overview(
    account_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """交易总览统计（首页Dashboard）"""
    pos_q = db.query(TradePosition).filter(TradePosition.status == 1)
    hist_q = db.query(TradePosition).filter(TradePosition.status == 2)
    if user.role != 1:
        pos_q = pos_q.filter(TradePosition.user_id == user.id)
        hist_q = hist_q.filter(TradePosition.user_id == user.id)
    if account_id:
        pos_q = pos_q.filter(TradePosition.exchange_account_id == account_id)
        hist_q = hist_q.filter(TradePosition.exchange_account_id == account_id)

    # 今日统计
    today = date.today()
    today_start = datetime.combine(today, datetime.min.time())
    today_orders_q = db.query(TradeOrder)
    today_closed_q = hist_q.filter(TradePosition.close_time >= today_start)
    if user.role != 1:
        today_orders_q = today_orders_q.filter(TradeOrder.user_id == user.id)
    if account_id:
        today_orders_q = today_orders_q.filter(TradeOrder.exchange_account_id == account_id)

    open_positions = pos_q.count()
    today_count = today_orders_q.count()
    today_closed_count = today_closed_q.count()

    # 历史聚合（使用 case 替代 IF，兼容 SQLite + MySQL）
    total_closed = hist_q.count()
    agg = hist_q.with_entities(
        func.coalesce(func.sum(TradePosition.realized_pnl), 0),
        func.coalesce(func.sum(case((TradePosition.realized_pnl > 0, 1), else_=0)), 0),
        func.coalesce(func.sum(case((TradePosition.realized_pnl < 0, 1), else_=0)), 0),
        func.coalesce(func.avg(TradePosition.pnl_ratio), 0),
    ).first() or (0, 0, 0, 0)
    total_pnl, win, loss, avg_pct = agg
    win = win or 0
    loss = loss or 0
    win_rate = round((win / (win + loss) * 100), 2) if (win + loss) > 0 else 0

    # 今日已实现盈亏
    today_pnl = today_closed_q.with_entities(
        func.coalesce(func.sum(TradePosition.realized_pnl), 0)
    ).scalar() or 0

    # 未实现浮动盈亏
    floating = pos_q.with_entities(
        func.coalesce(func.sum(TradePosition.unrealized_pnl), 0)
    ).scalar() or 0

    return success({
        "open_positions": open_positions,
        "today_order_count": today_count,
        "today_closed_count": today_closed_count,
        "total_closed_count": total_closed,
        "total_pnl": float(total_pnl),
        "today_pnl": float(today_pnl),
        "today_realized_win": float(today_pnl),
        "floating_unrealized_pnl": float(floating),
        "win_count": win,
        "loss_count": loss,
        "win_rate": win_rate,
        "avg_pnl_pct": round(float(avg_pct), 2),
    })
