"""
系统监控路由：仪表盘、日志、自检、分享令牌
提供 /api/v1/monitor 下的所有接口
以及公开分享接口 /api/v1/monitor/share/{token}
"""
from fastapi import APIRouter, Depends, Query, HTTPException, Request
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

from backend.db.session import get_db
from backend.core.auth import require_admin, get_current_user
from fastapi.responses import FileResponse, HTMLResponse
from backend.core.exceptions import success, BizException
from backend.models.user import User
from backend.services.monitor_service import (
    collect_system_status,
    run_full_self_check,
    list_log_files,
    read_logs,
    get_log_summary,
    create_share_token,
    validate_share_token,
    list_share_tokens,
    revoke_share_token,
    generate_diagnostic_report,
)
from backend.services.ai_share_engine import (
    create_task,
    get_task,
    list_tasks,
    stream_task_events,
)

router = APIRouter(prefix="/monitor", tags=["系统监控"])


# ============================================================
# 1. 系统状态仪表盘
# ============================================================

@router.get("/status")
def monitor_status(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """获取系统实时状态（仪表盘用）"""
    status = collect_system_status(db)
    return success(status)


@router.get("/self-check")
def self_check(
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """运行完整功能自检"""
    result = run_full_self_check(db)
    return success(result)


# ============================================================
# 2. 日志管理
# ============================================================

@router.get("/logs/files")
def log_files(
    user: User = Depends(require_admin),
):
    """获取日志文件列表"""
    files = list_log_files()
    return success({"files": files})


@router.get("/logs")
def get_logs(
    log_type: str = Query(default="app", description="app/error/trade"),
    date: str = Query(default="", description="日期 YYYY-MM-DD，默认今天"),
    level: str = Query(default="", description="日志级别过滤"),
    keyword: str = Query(default="", description="关键词搜索"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=10, le=500),
    tail: int = Query(default=500, ge=50, le=5000),
    user: User = Depends(require_admin),
):
    """读取日志内容"""
    result = read_logs(
        log_type=log_type,
        date_str=date,
        level=level,
        keyword=keyword,
        page=page,
        page_size=page_size,
        tail=tail,
    )
    return success(result)


@router.get("/logs/summary")
def log_summary(
    user: User = Depends(get_current_user),
):
    """获取日志统计摘要"""
    summary = get_log_summary()
    return success(summary)


# ============================================================
# 3. 分享令牌（公开链接）
# ============================================================

class CreateShareReq(BaseModel):
    ttl_hours: float = Field(default=0.5, description="有效期（小时）", ge=0.083, le=720)


@router.post("/share")
def create_share(
    req: CreateShareReq,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """创建分享令牌（生成公开监控链接）"""
    result = create_share_token(db, user.id, ttl_hours=req.ttl_hours)
    return success(result, message="分享链接已创建")


@router.get("/share/list")
def share_list(
    user: User = Depends(require_admin),
):
    """列出所有有效分享令牌"""
    tokens = list_share_tokens()
    return success({"tokens": tokens})


@router.delete("/share/{token}")
def share_revoke(
    token: str,
    user: User = Depends(require_admin),
):
    """撤销分享令牌"""
    ok = revoke_share_token(token)
    if not ok:
        raise BizException("令牌不存在或已过期", code=4004)
    return success({"token": token}, message="已撤销")


# ============================================================
# 4. 公开分享接口（无需登录）
# ============================================================
# 注意：这些接口是公开的，通过 token 鉴权，不需要登录
# 只暴露有限的状态信息，不暴露敏感数据

@router.get("/share/{token}/status")
def share_status(
    token: str,
    db: Session = Depends(get_db),
):
    """公开分享 - 获取系统状态（脱敏）"""
    info = validate_share_token(token)
    if not info:
        raise BizException("分享链接无效或已过期", code=4004)
    
    status = collect_system_status(db)
    
    # 脱敏：移除敏感信息
    safe_status = {
        "overall": status.get("overall"),
        "version": status.get("version"),
        "collected_at": status.get("collected_at"),
        "uptime_seconds": status.get("uptime_seconds"),
        "resources": status.get("resources", {}),
        "issues": status.get("issues", []),
        "issue_count": status.get("issue_count", {}),
        "logs": status.get("logs", {}),
        "scheduler": status.get("scheduler", {}),
        # 不暴露数据库详情、用户数等敏感信息
        "database": {
            "connection": status.get("database", {}).get("connection", "unknown"),
        },
        "redis": {
            "status": status.get("redis", {}).get("status", "unknown"),
        },
    }
    
    return success(safe_status)


@router.get("/share/{token}/self-check")
def share_self_check(
    token: str,
    db: Session = Depends(get_db),
):
    """公开分享 - 运行自检"""
    info = validate_share_token(token)
    if not info:
        raise BizException("分享链接无效或已过期", code=4004)
    
    result = run_full_self_check(db)
    return success(result)


@router.get("/share/{token}/logs")
def share_logs(
    token: str,
    log_type: str = Query(default="app"),
    date: str = Query(default=""),
    level: str = Query(default=""),
    keyword: str = Query(default=""),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=10, le=200),
):
    """公开分享 - 读取日志（仅error和warning级别，脱敏）"""
    info = validate_share_token(token)
    if not info:
        raise BizException("分享链接无效或已过期", code=4004)
    
    # 公开分享只允许看 app 和 error 日志
    if log_type not in ("app", "error"):
        log_type = "app"
    
    result = read_logs(
        log_type=log_type,
        date_str=date,
        level=level,
        keyword=keyword,
        page=page,
        page_size=page_size,
        tail=300,
    )
    
    # 脱敏：移除可能包含敏感信息的字段（如API key等）
    for entry in result.get("entries", []):
        msg = entry.get("message", "")
        # 简单的敏感信息过滤
        import re
        msg = re.sub(r'(api[_-]?key|secret|password|token)\s*[=:]\s*\S+', 
                     r'\1=***', msg, flags=re.IGNORECASE)
        entry["message"] = msg
        entry["raw"] = ""  # 不暴露原始行
    
    return success(result)


@router.get("/share/{token}/diagnostic")
def share_diagnostic(
    token: str,
    db: Session = Depends(get_db),
):
    """公开分享 - 完整诊断报告（给开发者分析用）"""
    info = validate_share_token(token)
    if not info:
        raise BizException("分享链接无效或已过期", code=4004)
    
    report = generate_diagnostic_report(db)
    
    # 脱敏处理
    if "system_status" in report:
        ss = report["system_status"]
        ss.pop("exchange_accounts", None)
        if "database" in ss:
            ss["database"].pop("users", None)
            ss["database"].pop("strategies", None)
    
    return success(report)


# ============================================================
# 4.5 AI 控制中心（分享链接可用）
# ============================================================
# 所有任务均为模拟/只读性质，不影响真实交易

class BacktestTaskReq(BaseModel):
    symbol: str = Field(default="BTC/USDT", description="交易对")
    timeframe: str = Field(default="1h", description="时间级别")
    strategy: str = Field(default="emv", description="策略类型")
    days: int = Field(default=90, description="回测天数", ge=7, le=365)
    initial_capital: float = Field(default=10000, description="初始资金", gt=0)


class StrategyScanReq(BaseModel):
    symbols: list = Field(default=["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT"], description="扫描币种列表")
    timeframes: list = Field(default=["15m", "1h", "4h", "1d"], description="时间级别列表")
    strategy: str = Field(default="emv", description="策略类型")
    top_n: int = Field(default=5, description="返回前N个最佳机会", ge=1, le=20)


class AIAnalysisReq(BaseModel):
    symbol: str = Field(default="BTC/USDT", description="分析币种")
    analysis_type: str = Field(default="comprehensive", description="分析类型")


class FullTestReq(BaseModel):
    symbols: list = Field(default=["BTC/USDT", "ETH/USDT", "SOL/USDT"], description="测试币种")
    timeframes: list = Field(default=["1h", "4h"], description="时间级别")
    strategy: str = Field(default="emv", description="策略类型")


# ============================================================
# 后台 AI 控制中心接口（登录鉴权）
# ============================================================

def _user_ai_token(user_id: int) -> str:
    """后台用户 AI 任务内部 token"""
    return f"admin_user_{user_id}"


@router.post("/ai/tasks/backtest")
def admin_ai_backtest(
    req: BacktestTaskReq,
    user: User = Depends(require_admin),
):
    """后台 - 创建模拟回测任务"""
    token = _user_ai_token(user.id)
    params = {
        "symbol": req.symbol,
        "timeframe": req.timeframe,
        "strategy": req.strategy,
        "days": req.days,
        "initial_capital": req.initial_capital,
    }
    task = create_task(token, "backtest", params)
    return success(task)


@router.post("/ai/tasks/strategy-scan")
def admin_ai_strategy_scan(
    req: StrategyScanReq,
    user: User = Depends(require_admin),
):
    """后台 - 创建多币种策略扫描任务"""
    token = _user_ai_token(user.id)
    params = {
        "symbols": req.symbols,
        "timeframes": req.timeframes,
        "strategy": req.strategy,
        "top_n": req.top_n,
    }
    task = create_task(token, "strategy_scan", params)
    return success(task)


@router.post("/ai/tasks/ai-analysis")
def admin_ai_analysis(
    req: AIAnalysisReq,
    user: User = Depends(require_admin),
):
    """后台 - 创建AI市场分析任务"""
    token = _user_ai_token(user.id)
    params = {
        "symbol": req.symbol,
        "analysis_type": req.analysis_type,
    }
    task = create_task(token, "ai_analysis", params)
    return success(task)


@router.post("/ai/tasks/full-test")
def admin_ai_full_test(
    req: FullTestReq,
    user: User = Depends(require_admin),
):
    """后台 - 创建全面系统测试任务"""
    token = _user_ai_token(user.id)
    params = {
        "test_symbol": req.symbols[0] if req.symbols else "BTC/USDT",
        "test_timeframe": req.timeframes[0] if req.timeframes else "1h",
        "strategy": req.strategy,
    }
    task = create_task(token, "full_test", params)
    return success(task)


@router.get("/ai/tasks/{task_id}")
def admin_ai_task_status(
    task_id: str,
    user: User = Depends(require_admin),
):
    """后台 - 获取任务状态和结果"""
    token = _user_ai_token(user.id)
    task = get_task(token, task_id)
    if not task:
        raise BizException("任务不存在", code=4004)
    return success(task)


@router.get("/ai/tasks/{task_id}/stream")
async def admin_ai_task_stream(
    task_id: str,
    user: User = Depends(require_admin),
):
    """后台 - SSE实时推送任务进度"""
    from fastapi.responses import StreamingResponse
    import json
    
    token = _user_ai_token(user.id)
    
    def event_generator():
        for event in stream_task_events(token, task_id):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/ai/tasks")
def admin_ai_task_list(
    limit: int = Query(default=20, ge=1, le=50),
    user: User = Depends(require_admin),
):
    """后台 - 获取任务列表"""
    token = _user_ai_token(user.id)
    tasks = list_tasks(token, limit)
    return success({"tasks": tasks})


@router.post("/share/{token}/ai/tasks/backtest")
def share_ai_backtest(
    token: str,
    req: BacktestTaskReq,
):
    """分享链接 - 创建模拟回测任务"""
    info = validate_share_token(token)
    if not info:
        raise BizException("分享链接无效或已过期", code=4004)

    task = create_task(token, "backtest", {
        "symbol": req.symbol,
        "timeframe": req.timeframe,
        "strategy": req.strategy,
        "days": req.days,
        "initial_capital": req.initial_capital,
    })
    return success(task, message="回测任务已启动")


@router.post("/share/{token}/ai/tasks/strategy-scan")
def share_ai_strategy_scan(
    token: str,
    req: StrategyScanReq,
):
    """分享链接 - 创建多币种策略扫描任务"""
    info = validate_share_token(token)
    if not info:
        raise BizException("分享链接无效或已过期", code=4004)

    task = create_task(token, "strategy_scan", {
        "symbols": req.symbols,
        "timeframes": req.timeframes,
        "strategy": req.strategy,
        "top_n": req.top_n,
    })
    return success(task, message="策略扫描任务已启动")


@router.post("/share/{token}/ai/tasks/ai-analysis")
def share_ai_analysis(
    token: str,
    req: AIAnalysisReq,
):
    """分享链接 - 创建AI市场分析任务"""
    info = validate_share_token(token)
    if not info:
        raise BizException("分享链接无效或已过期", code=4004)

    task = create_task(token, "ai_analysis", {
        "symbol": req.symbol,
        "analysis_type": req.analysis_type,
    })
    return success(task, message="AI分析任务已启动")


@router.post("/share/{token}/ai/tasks/full-test")
def share_ai_full_test(
    token: str,
    req: FullTestReq,
):
    """分享链接 - 创建全面系统测试任务"""
    info = validate_share_token(token)
    if not info:
        raise BizException("分享链接无效或已过期", code=4004)

    task = create_task(token, "full_test", {
        "symbols": req.symbols,
        "timeframes": req.timeframes,
        "strategy": req.strategy,
    })
    return success(task, message="全面测试任务已启动")


@router.get("/share/{token}/ai/tasks/{task_id}")
def share_ai_task_status(
    token: str,
    task_id: str,
):
    """分享链接 - 获取任务状态和结果"""
    info = validate_share_token(token)
    if not info:
        raise BizException("分享链接无效或已过期", code=4004)

    task = get_task(token, task_id)
    if not task:
        raise BizException("任务不存在", code=4004)
    return success(task)


@router.get("/share/{token}/ai/tasks/{task_id}/stream")
async def share_ai_task_stream(
    token: str,
    task_id: str,
):
    """分享链接 - SSE实时推送任务进度
    
    使用 Server-Sent Events 实时推送任务进度、完成、失败等事件
    """
    info = validate_share_token(token)
    if not info:
        raise BizException("分享链接无效或已过期", code=4004)
    
    from fastapi.responses import StreamingResponse
    import json
    
    def event_generator():
        for event in stream_task_events(token, task_id):
            # SSE 格式: data: <json>\n\n
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/share/{token}/ai/tasks")
def share_ai_task_list(
    token: str,
    limit: int = Query(default=20, ge=1, le=50),
):
    """分享链接 - 获取任务列表"""
    info = validate_share_token(token)
    if not info:
        raise BizException("分享链接无效或已过期", code=4004)

    tasks = list_tasks(token, limit=limit)
    return success({"tasks": tasks, "total": len(tasks)})


# ============================================================
# 5. 诊断报告（管理员用，完整数据）
# ============================================================

@router.get("/diagnostic")
def diagnostic_report(
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """生成完整诊断报告"""
    report = generate_diagnostic_report(db)
    return success(report)

from backend.services.engine_monitor_service import (
    get_engine_overview,
    get_scheduler_status,
)

from pathlib import Path

_STATIC_DIR = Path(__file__).resolve().parent.parent.parent / "static"


@router.get("/dashboard", include_in_schema=False)
async def public_dashboard(request: Request):
    """公开监控仪表盘页面（独立页面，通过 token 参数访问）
    
    访问方式: /api/v1/monitor/dashboard?token=xxx
    完全独立，不依赖后台系统，专门用于分享给开发者分析问题
    """
    dashboard_file = _STATIC_DIR / "monitor-dashboard.html"
    if not dashboard_file.exists():
        return HTMLResponse("<h1>监控页面未找到</h1><p>请联系管理员</p>", status_code=404)
    return FileResponse(str(dashboard_file), media_type="text/html")


# ============================================================
# 6. 交易引擎运行总览（管理员用）
# ============================================================

@router.get("/engine/overview")
def engine_overview(
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """交易引擎综合运行状态"""
    data = get_engine_overview(db)
    return success(data)


@router.get("/engine/scheduler")
def engine_scheduler(
    request: Request,
    user: User = Depends(require_admin),
):
    """定时任务运行状态"""
    data = get_scheduler_status(request)
    return success(data)