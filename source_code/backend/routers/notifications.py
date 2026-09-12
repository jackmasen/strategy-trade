"""
通知系统路由：聚合风控事件、AI分析、大资金异动等通知
"""
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import desc

from backend.db.session import get_db
from backend.core.auth import get_current_user
from backend.core.exceptions import success
from backend.models.user import User
from backend.models.analytics import RiskEventLog, AIAnalysisRecord
from backend.models.trade import TradePosition, TradeOrder
from backend.models.analytics import BacktestRun

router = APIRouter(prefix="/notifications", tags=["通知中心"])


@router.get("")
def list_notifications(
    limit: int = 20,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """获取通知列表（聚合风控事件+AI分析+交易提醒+回测完成）"""
    items = []

    # 1. 风控事件
    risk_q = db.query(RiskEventLog)
    if user.role != 1:
        risk_q = risk_q.filter(RiskEventLog.user_id == user.id)
    risk_events = risk_q.order_by(desc(RiskEventLog.created_at)).limit(limit).all()
    for r in risk_events:
        severity_map = {1: "info", 2: "warning", 3: "danger"}
        type_map = {
            1: "单笔回撤超限", 2: "日亏损超限", 3: "连续亏损",
            4: "持仓数超限", 5: "API异常", 6: "异常行情",
            7: "强制平仓", 8: "冷静期开始", 9: "冷静期结束",
        }
        items.append({
            "id": f"risk_{r.id}",
            "type": "risk",
            "title": r.title or type_map.get(r.event_type, "风控事件"),
            "detail": r.detail or "",
            "severity": severity_map.get(r.severity, "info"),
            "symbol": r.symbol or "",
            "created_at": r.created_at.isoformat() if r.created_at else "",
            "read": r.notified,
        })

    # 2. AI分析记录（按用户隔离）
    ai_q = db.query(AIAnalysisRecord).filter(AIAnalysisRecord.success == True)
    if user.role != 1:
        ai_q = ai_q.filter(AIAnalysisRecord.user_id == user.id)
    ai_q = ai_q.order_by(desc(AIAnalysisRecord.created_at)).limit(limit).all()
    for a in ai_q:
        items.append({
            "id": f"ai_{a.id}",
            "type": "ai",
            "title": f"AI分析 · {a.symbol or ''} {a.ai_direction or ''} 评分{a.ai_score or '?'}",
            "detail": (a.ai_reason or "")[:200],
            "severity": "info",
            "symbol": a.symbol or "",
            "created_at": a.created_at.isoformat() if a.created_at else "",
            "read": True,
        })

    # 3. 回测完成通知
    bt_q = db.query(BacktestRun)
    if user.role != 1:
        bt_q = bt_q.filter(BacktestRun.user_id == user.id)
    bt_q = bt_q.filter(BacktestRun.status.in_([2, 3])).order_by(desc(BacktestRun.finished_at)).limit(limit // 2).all()
    for b in bt_q:
        if b.status == 2:
            items.append({
                "id": f"bt_{b.id}",
                "type": "backtest",
                "title": f"回测完成 · {b.run_name}",
                "detail": f"收益率: {b.total_return_pct or 0}%, 胜率: {b.win_rate or 0}%, 交易{b.total_trades or 0}笔",
                "severity": "success",
                "symbol": "",
                "created_at": b.finished_at.isoformat() if b.finished_at else "",
                "read": True,
            })
        else:
            items.append({
                "id": f"bt_{b.id}",
                "type": "backtest",
                "title": f"回测失败 · {b.run_name}",
                "detail": b.error_msg or "执行失败",
                "severity": "danger",
                "symbol": "",
                "created_at": b.finished_at.isoformat() if b.finished_at else "",
                "read": True,
            })

    # 4. 最近平仓通知
    pos_q = db.query(TradePosition).filter(TradePosition.status == 2)
    if user.role != 1:
        from backend.models.exchange import ExchangeAccount
        acc_ids = [a.id for a in db.query(ExchangeAccount.id).filter(ExchangeAccount.user_id == user.id).all()]
        pos_q = pos_q.filter(TradePosition.exchange_account_id.in_(acc_ids)) if acc_ids else pos_q.filter(False)
    closed = pos_q.order_by(desc(TradePosition.close_time)).limit(limit // 2).all()
    for p in closed:
        pnl = float(p.realized_pnl or 0)
        items.append({
            "id": f"pos_{p.id}",
            "type": "trade",
            "title": f"平仓 · {p.symbol} {'多' if p.side == 1 else '空'} {'盈利' if pnl > 0 else '亏损'} {abs(pnl):.2f} USDT",
            "detail": f"开仓价: {float(p.entry_price or 0):.2f}, 平仓价: {float(p.close_price or 0):.2f}",
            "severity": "success" if pnl > 0 else "danger",
            "symbol": p.symbol or "",
            "created_at": p.close_time.isoformat() if p.close_time else "",
            "read": True,
        })

    # 按时间排序
    items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    items = items[:limit]

    unread = sum(1 for i in items if not i.get("read", True))
    return success({
        "items": items,
        "total": len(items),
        "unread": unread,
    })


@router.get("/unread-count")
def unread_count(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """获取未读通知数量"""
    cutoff = datetime.now() - timedelta(hours=48)
    risk_q = db.query(RiskEventLog).filter(RiskEventLog.notified == False, RiskEventLog.created_at >= cutoff)
    if user.role != 1:
        risk_q = risk_q.filter(RiskEventLog.user_id == user.id)
    count = risk_q.count()
    return success({"count": count})
