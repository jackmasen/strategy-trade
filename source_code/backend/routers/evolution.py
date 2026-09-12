"""
策略自我进化 API 路由
提供假信号分析、因子重要性、进化方案等接口
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import Optional

from backend.core.auth import get_current_user, require_admin
from backend.db.session import get_db
from backend.core.exceptions import success, ParameterException
from backend.models.user import User
from backend.services.strategy_evolution import get_evolution_service
from backend.models.analytics import EvolutionProposal

router = APIRouter(prefix="/evolution", tags=["策略进化"])


@router.get("/dashboard")
def evolution_dashboard(
    symbol: str = Query(default="ALL", description="品种，ALL表示全部"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """进化仪表盘 - 汇总胜率、假信号模式、因子重要性、优化方案"""
    svc = get_evolution_service()
    data = svc.get_dashboard_data(db, symbol=symbol)
    return success(data)


@router.get("/false-signal-patterns")
def false_signal_patterns(
    symbol: str = Query(default="ALL", description="品种"),
    severity: str = Query(default=None, description="严重程度筛选"),
    limit: int = Query(default=20, description="数量限制"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """假信号模式列表"""
    svc = get_evolution_service()
    try:
        from backend.models.analytics import FalseSignalPattern
        from datetime import datetime, timedelta
        latest = db.query(FalseSignalPattern).order_by(FalseSignalPattern.last_updated.desc()).first()
        if not latest or latest.last_updated < datetime.utcnow() - timedelta(hours=24):
            svc.analyze_false_signal_patterns(db, symbol=symbol)

        query = db.query(FalseSignalPattern)
        if severity:
            query = query.filter(FalseSignalPattern.severity == severity)
        patterns = query.order_by(
            FalseSignalPattern.severity.desc(),
            FalseSignalPattern.win_rate.asc(),
        ).limit(limit).all()

        return success([svc._pattern_to_dict(p) for p in patterns])
    except Exception:
        return success([])


@router.get("/factor-importance")
def factor_importance(
    symbol: str = Query(default="ALL", description="品种"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """因子重要性排名"""
    svc = get_evolution_service()
    try:
        stats = svc.analyze_factor_importance(db, symbol=symbol)
        return success([svc._factor_stat_to_dict(s) for s in stats])
    except Exception:
        return success([])


@router.get("/proposals")
def evolution_proposals(
    status: str = Query(default="pending", description="状态: pending/accepted/rejected/applied"),
    limit: int = Query(default=20, description="数量限制"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """进化方案列表"""
    svc = get_evolution_service()
    query = db.query(EvolutionProposal)
    if status and status != "all":
        query = query.filter(EvolutionProposal.status == status)
    proposals = query.order_by(EvolutionProposal.confidence.desc()).limit(limit).all()
    return success([svc._proposal_to_dict(p) for p in proposals])


@router.post("/proposals/{proposal_id}/accept")
def accept_proposal(
    proposal_id: int,
    apply: bool = Query(default=False, description="是否直接应用到策略"),
    strategy_id: int = Query(default=None, description="目标策略ID"),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """接受进化方案（apply=True时真正修改策略参数）"""
    proposal = db.query(EvolutionProposal).filter(EvolutionProposal.id == proposal_id).first()
    if not proposal:
        from backend.core.exceptions import ParameterException
        raise ParameterException("方案不存在")

    if apply:
        svc = get_evolution_service()
        success, msg = svc.apply_proposal_to_strategy(db, proposal, strategy_id=strategy_id)
        if not success:
            raise ParameterException(f"应用失败: {msg}")
        return success({"id": proposal.id, "status": proposal.status, "applied": True, "message": msg})
    else:
        proposal.status = "accepted"
        db.commit()
        return success({"id": proposal.id, "status": proposal.status, "applied": False})


@router.post("/proposals/{proposal_id}/reject")
def reject_proposal(
    proposal_id: int,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """拒绝进化方案"""
    proposal = db.query(EvolutionProposal).filter(EvolutionProposal.id == proposal_id).first()
    if not proposal:
        from backend.core.exceptions import ParameterException
        raise ParameterException("方案不存在")

    proposal.status = "rejected"
    db.commit()
    return success({"id": proposal.id, "status": "rejected"})


@router.post("/run")
def run_evolution(
    symbol: str = Query(default="ALL", description="分析品种"),
    strategy_id: int = Query(default=None, description="目标策略ID"),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """运行一次完整的进化分析"""
    svc = get_evolution_service()
    run = svc.run_full_evolution(db, symbol=symbol, strategy_id=strategy_id)
    return success({
        "run_id": run.id,
        "status": run.status,
        "patterns_found": run.patterns_found,
        "proposals_generated": run.proposals_generated,
    })


@router.get("/runs")
def evolution_runs(
    limit: int = Query(default=20, description="数量限制"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """进化运行历史"""
    from backend.models.analytics import EvolutionRun
    runs = db.query(EvolutionRun).order_by(EvolutionRun.started_at.desc()).limit(limit).all()
    return success([{
        "id": r.id,
        "run_type": r.run_type,
        "status": r.status,
        "signals_analyzed": r.signals_analyzed,
        "patterns_found": r.patterns_found,
        "proposals_generated": r.proposals_generated,
        "started_at": r.started_at.isoformat() if r.started_at else None,
        "completed_at": r.completed_at.isoformat() if r.completed_at else None,
        "error_message": r.error_message,
    } for r in runs])


@router.post("/proposals/{proposal_id}/rollback")
def rollback_proposal(
    proposal_id: int,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """回滚已应用的进化方案"""
    proposal = db.query(EvolutionProposal).filter(EvolutionProposal.id == proposal_id).first()
    if not proposal:
        raise ParameterException("方案不存在")
    svc = get_evolution_service()
    ok, msg = svc.rollback_proposal(db, proposal)
    return success({"id": proposal.id, "rolled_back": ok, "message": msg})


@router.get("/proposals/{proposal_id}/verify")
def verify_proposal(
    proposal_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """验证已应用方案的效果（对比应用前后胜率）"""
    svc = get_evolution_service()
    result = svc.verify_evolution_result(db, proposal_id)
    return success(result)


@router.post("/auto-evolve")
def auto_evolve(
    auto_apply_threshold: float = Query(default=75.0, description="自动应用置信度阈值(0-100)"),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """手动触发一次自动进化（分析+高置信度方案自动应用）"""
    svc = get_evolution_service()
    result = svc.auto_evolve(db, auto_apply_threshold=auto_apply_threshold)
    return success(result)
