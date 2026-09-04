"""
AI配置 + 新闻 + 风控事件 + 回测 + 报表 路由骨架
精简为一个文件，可后续拆分为独立模块
"""
from fastapi import APIRouter, Depends, Query, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy import inspect as sa_inspect
from pydantic import BaseModel, Field
from typing import List, Optional, Dict
from datetime import datetime, date, timedelta
import threading
import time

from backend.db.session import get_db
from backend.db.base import Base
from backend.core.auth import get_current_user, require_editor, require_admin, require_trader
from backend.core.exceptions import NotFoundException, ParameterException, BizException, success
from backend.core.schemas import ApiResponse, PaginationParams, paginate
from backend.config import get_settings
from backend.core.logging_config import logger
from backend.core.security import encrypt_api_key, decrypt_api_key, mask_api_key
from backend.models.user import User
from backend.models.analytics import (
    NewsArticle, AIAnalysisRecord, RiskEventLog,
    BacktestRun, DailyFinancialReport, WeeklyFinancialReport, MonthlyFinancialReport,
)
from backend.models.ai_config import AIConfig
from backend.models.strategy import StrategyConfig
from backend.services.ai_client import AIClient, AIResult, ERR_NOT_CONFIGURED, ERR_INVALID_JSON

settings = get_settings()

router = APIRouter(prefix="", tags=["分析/回测/报表"])

# ==================== AI接口配置与调用（V2 真实现 + DB 加密持久化 + 热生效） ====================
ai_router = APIRouter(prefix="/ai", tags=["AI分析"])


# ========== 工具：单例初始化（幂等，兼容老数据库无表/无行） ==========
def _ensure_ai_config_table_and_row(db: Session) -> AIConfig:
    """
    任何读取/写入 AIConfig 前都调用一次：
    1) 若 ai_configs 表不存在 → 自动建（只用这个表，不动其他模型）
    2) 若 id=1 行不存在 → 从 settings.AI_* 初始化一行（api_key 加密落库）
    返回单例（永远有值，不会是 None）
    """
    from backend.db.session import engine_sync
    insp = sa_inspect(engine_sync)
    if "ai_configs" not in insp.get_table_names():
        # 只建这一张表（避免影响其他表）
        AIConfig.__table__.create(bind=engine_sync, checkfirst=True)
        logger.info("[AI] 自动创建 ai_configs 表成功")
    row = db.query(AIConfig).filter(AIConfig.id == AIConfig.SINGLETON_ID).first()
    if row is None:
        # 从 .env 的 settings 初始化首次默认值（迁移无 DB 记录的老系统）
        row = AIConfig(
            id=AIConfig.SINGLETON_ID,
            provider=AIConfig.name_to_provider(settings.AI_PROVIDER),
            model_name=settings.AI_MODEL_NAME or "gpt-4o",
            api_endpoint=settings.AI_API_ENDPOINT or "",
            api_key_encrypted=encrypt_api_key(settings.AI_API_KEY or ""),
            temperature=3,
            max_tokens=800,
            request_timeout_sec=30,
            max_retries=2,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        logger.info(f"[AI] 初始化 ai_configs 单例成功 provider={row.provider_name} model={row.model_name}")
    return row


def _cfg_to_public_dict(cfg: AIConfig) -> dict:
    """将 AIConfig ORM 转前端需要的字段（**绝不明文 Key**）"""
    key_plain = decrypt_api_key(cfg.api_key_encrypted or "")
    return {
        "provider": cfg.provider_name,
        "model_name": cfg.model_name or "",
        "api_endpoint": cfg.api_endpoint or "",
        "api_key_masked": mask_api_key(key_plain),
        "has_key": bool(key_plain),
        "temperature": int(cfg.temperature or 3),
        "max_tokens": int(cfg.max_tokens or 800),
        "request_timeout_sec": int(cfg.request_timeout_sec or 30),
        "max_retries": int(cfg.max_retries or 2),
        "last_verified_at": cfg.last_verified_at.isoformat(timespec="seconds") if cfg.last_verified_at else None,
        "last_error": cfg.last_error or "",
    }


# ========== Pydantic 契约（兼容前端 AI.vue 现有 4 字段 + 扩展字段可选） ==========
class AIConfigUpdate(BaseModel):
    provider: str = Field(default="custom", description="openai/anthropic/custom/local")
    model_name: str = "gpt-4o"
    api_endpoint: str = ""
    api_key: str = ""
    temperature: Optional[float] = Field(default=None, ge=0, le=10)
    max_tokens: Optional[int] = Field(default=None, ge=32, le=65536)
    request_timeout_sec: Optional[int] = Field(default=None, ge=3, le=300)
    max_retries: Optional[int] = Field(default=None, ge=0, le=10)


class AIAnalyzeReq(BaseModel):
    analysis_type: str = "score"
    symbol: Optional[str] = None
    timeframe: str = "4h"
    manual_prompt: str = ""
    # 测试/运营用：True 时走 mock 模式不发真请求（避免消耗真钱额度）
    # 注意：不以下划线开头，保证 Pydantic v1/v2 都能从 JSON body 正常解析
    mock: bool = False


@ai_router.get("/config")
def ai_config(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """获取当前 AI 全局配置（绝不返回 Key 明文；返回 mask + has_key）"""
    cfg = _ensure_ai_config_table_and_row(db)
    return success(_cfg_to_public_dict(cfg))


@ai_router.put("/config")
def update_ai_config(
    req: AIConfigUpdate,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    管理员修改 AI 全局配置 → 加密后写入 DB → 热生效（下次调用 analyze 即读最新，无需重启服务）
    安全：仅 ROLE_ADMIN（role=1）可改；运营/访客一律 403。
    """
    if not req.model_name or not req.model_name.strip():
        raise ParameterException("模型名不能为空")
    req_provider_name = (req.provider or "custom").strip().lower()
    if req_provider_name not in ("openai", "anthropic", "custom", "local"):
        raise ParameterException(f"不支持的 AI 供应商：{req.provider}")

    cfg = _ensure_ai_config_table_and_row(db)
    # 更新标量字段
    cfg.provider = AIConfig.name_to_provider(req_provider_name)
    cfg.model_name = req.model_name.strip()
    cfg.api_endpoint = (req.api_endpoint or "").strip()

    # Key 处理：
    #   空串：沿用 DB 现有 Key（前端"只改模型不改 Key"场景）
    #   __CLEAR__：主动清空 Key（运营停用 AI / 清除旧 Key 场景，测试脚本回滚也用）
    #   其他非空：加密后覆盖更新
    if req.api_key is not None:
        raw = req.api_key.strip() if isinstance(req.api_key, str) else ""
        if raw == "__CLEAR__":
            cfg.api_key_encrypted = ""
            logger.info(f"[AI] 管理员 {user.username}(uid={user.id}) 主动清除了 AI API Key")
        elif raw:
            cfg.api_key_encrypted = encrypt_api_key(raw)

    # 扩展字段：None 表示沿用 DB 原值（避免前端不传时把温度重置成 0）
    if req.temperature is not None:
        cfg.temperature = int(req.temperature)
    if req.max_tokens is not None:
        cfg.max_tokens = int(req.max_tokens)
    if req.request_timeout_sec is not None:
        cfg.request_timeout_sec = int(req.request_timeout_sec)
    if req.max_retries is not None:
        cfg.max_retries = int(req.max_retries)

    # 审计
    cfg.updated_by = user.id
    cfg.updated_username = user.username or ""
    cfg.last_error = ""

    db.commit()
    db.refresh(cfg)

    logger.info(
        f"[AI] 管理员 {user.username}(uid={user.id}) 更新 AI 配置："
        f"provider={cfg.provider_name} model={cfg.model_name} "
        f"endpoint_len={len(cfg.api_endpoint)} has_key={bool(decrypt_api_key(cfg.api_key_encrypted))}"
    )
    return success(_cfg_to_public_dict(cfg), message="AI 配置已保存并热生效（立即生效，无需重启）")


@ai_router.post("/analyze")
def ai_analyze(
    req: AIAnalyzeReq,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    手动触发 AI 分析：
      - 先拉取实时行情（bid/ask/last价格）、K线数据、新闻数据
      - 检查新闻完整度，不足时提示用户先采集新闻
      - 将实时数据传入 AI，确保分析基于当前市场情况
      - 先尝试 ai_configs 主配置
      - 失败自动切换到系统设置 AI 接口池轮询
      - 记录完整 AIAnalysisRecord（tokens/cost/latency/raw_response）
      - 返回 source 字段标识使用的配置来源（primary/pool）
      - 返回中附带当前实时价格信息
    """
    from backend.services.ai_failover import call_ai_unified
    from backend.exchanges.market import MarketManager

    symbol = (req.symbol or "BTC").upper()
    timeframe = req.timeframe or "4h"

    # ========== 1. 拉取实时行情 ==========
    current_price = None
    bid_price = None
    ask_price = None
    change_pct = None
    try:
        mm = MarketManager.get_instance()
        ticker = mm.get_ticker(symbol)
        if ticker:
            current_price = ticker.last_price
            bid_price = ticker.bid_price
            ask_price = ticker.ask_price
            change_pct = ticker.change_pct_24h
    except Exception as e:
        logger.warning(f"[AI-Analyze] 行情获取失败 {symbol}: {e}")

    # 行情取不到，尝试从交易所直接拉
    if not current_price:
        try:
            from backend.routers.trade import _build_client
            from backend.models.exchange import ExchangeAccount
            acc = db.query(ExchangeAccount).filter(ExchangeAccount.status == 1).order_by(ExchangeAccount.id).first()
            if acc:
                client = _build_client(acc)
                ticker2 = client.fetch_ticker(symbol)
                if ticker2 and ticker2.last_price > 0:
                    current_price = ticker2.last_price
                    bid_price = ticker2.bid_price
                    ask_price = ticker2.ask_price
                    change_pct = ticker2.change_pct_24h if hasattr(ticker2, 'change_pct_24h') else getattr(ticker2, 'change_pct', 0)
        except Exception as e:
            logger.warning(f"[AI-Analyze] 交易所行情获取失败 {symbol}: {e}")

    # ========== 2. 拉取K线数据 ==========
    candles_snapshot = ""
    try:
        mm2 = MarketManager.get_instance()
        klines = mm2.get_klines(symbol, timeframe, limit=30)
        if klines and len(klines) > 0:
            lines = []
            for k in klines[-20:]:  # 最近20根K线
                ts = k.open_time.timestamp() if hasattr(k, 'open_time') and k.open_time else 0
                ts_str = datetime.fromtimestamp(ts).strftime('%m-%d %H:%M') if ts else 'N/A'
                lines.append(
                    f"  O={k.open:.4f} H={k.high:.4f} L={k.low:.4f} C={k.close:.4f} V={k.volume:.2f}  [{ts_str}]"
                )
            candles_snapshot = "\n".join(lines)
            logger.info(f"[AI-Analyze] {symbol} 获取K线 {len(klines)} 根，使用最近20根")
    except Exception as e:
        logger.warning(f"[AI-Analyze] K线获取失败 {symbol}: {e}")

    # ========== 3. 拉取新闻数据 ==========
    news_snapshot = ""
    news_count_24h = 0
    try:
        from datetime import timedelta as _td
        cutoff = datetime.utcnow() - _td(hours=24)
        articles = (
            db.query(NewsArticle)
            .filter(NewsArticle.published_at >= cutoff)
            .filter(NewsArticle.related_symbols.like(f'%\"{symbol}\"%'))
            .order_by(NewsArticle.published_at.desc())
            .limit(15)
            .all()
        )
        news_count_24h = len(articles)
        if articles:
            news_lines = []
            for a in articles[:10]:
                sentiment_label = {0: "中性", 1: "偏多", 2: "偏空"}.get(a.sentiment, "未知")
                news_lines.append(
                    f"  [{sentiment_label}] {a.title[:80]}  ({a.published_at.strftime('%m-%d %H:%M')})"
                )
            news_snapshot = "\n".join(news_lines)
            logger.info(f"[AI-Analyze] {symbol} 获取新闻 {news_count_24h} 条（24h内相关）")
        else:
            # 检查全量新闻（不限symbol）
            all_24h = (
                db.query(NewsArticle)
                .filter(NewsArticle.published_at >= cutoff)
                .count()
            )
            if all_24h < 5:
                logger.warning(f"[AI-Analyze] {symbol} 24小时内无相关新闻，全量新闻仅 {all_24h} 条，建议先采集新闻")
    except Exception as e:
        logger.warning(f"[AI-Analyze] 新闻获取失败 {symbol}: {e}")

    # ========== 4. 新闻完整度检查 ==========
    news_warning = ""
    if news_count_24h < 3:
        news_warning = "[新闻不足] 当前24小时内相关新闻不足3条，AI分析准确性可能受影响，建议先执行新闻采集。"
        logger.warning(f"[AI-Analyze] {symbol} 新闻不足，news_count_24h={news_count_24h}")

    # ========== 5. 调用AI（传入真实数据） ==========
    unified = call_ai_unified(
        db,
        analysis_type=req.analysis_type,
        symbol=symbol,
        timeframe=timeframe,
        manual_prompt=req.manual_prompt or "",
        candles_snapshot=candles_snapshot,
        news_snapshot=news_snapshot,
        _mock=bool(req.mock),
    )

    result: AIResult = unified["result"] or AIResult(
        success=False,
        error_code="AI_ALL_FAILED",
        error_msg=unified["error"] or "AI 分析失败：主配置和接口池均不可用",
    )

    cfg = _ensure_ai_config_table_and_row(db)
    # 落 AIAnalysisRecord 审计
    provider_int = {
        "openai": AIAnalysisRecord.PROVIDER_OPENAI,
        "anthropic": AIAnalysisRecord.PROVIDER_ANTHROPIC,
        "custom": AIAnalysisRecord.PROVIDER_CUSTOM,
        "local": AIAnalysisRecord.PROVIDER_LOCAL,
    }.get(result.provider or cfg.provider_name, cfg.provider)

    # prompt 脱敏（绝不落日志/DB 的明文 Key）
    prompt_safe = (req.manual_prompt or "")[:2000]
    if req.symbol:
        prompt_safe = f"[symbol={req.symbol.upper()}][tf={req.timeframe}] {prompt_safe}".strip()[:2000]

    record = AIAnalysisRecord(
        user_id=user.id,
        provider=provider_int,
        model_name=result.model_name or cfg.model_name or "",
        analysis_type=req.analysis_type,
        symbol=req.symbol,
        timeframe=req.timeframe,
        prompt_snapshot=prompt_safe,
        # AI 内容
        ai_response_raw=(result.raw_response or "")[:20000],
        ai_score=result.ai_score,
        ai_direction=result.ai_direction,
        ai_reason=(result.ai_reason or "")[:3000],
        # 用量
        tokens_prompt=result.tokens_prompt,
        tokens_completion=result.tokens_completion,
        cost_usd=result.cost_usd,
        latency_ms=result.latency_ms,
        # 成功/失败
        success=result.success,
        error_msg=(result.error_msg or "")[:1000],
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    # 构造返回体：字段对齐前端 AI.vue expected
    payload = {
        "record_id": record.id,
        "ai_score": result.ai_score,
        "ai_direction": result.ai_direction,
        "ai_reason": result.ai_reason,
        "mock": False,
        "latency_ms": result.latency_ms,
        "tokens_prompt": result.tokens_prompt,
        "tokens_completion": result.tokens_completion,
        "tokens_total": result.tokens_total,
        "cost_usd": result.cost_usd,
        "provider": result.provider or cfg.provider_name,
        "model_name": result.model_name or cfg.model_name,
        "success": result.success,
        "error_code": result.error_code,
        "error_msg": result.error_msg,
        "third_party_status": result.third_party_status,
        "ai_source": unified["source"],
        "used_key_name": unified.get("used_key_name", ""),
        # 实时价格数据（供前端展示核对）
        "current_price": current_price,
        "bid_price": bid_price,
        "ask_price": ask_price,
        "change_pct_24h": round(change_pct, 2) if change_pct else None,
        "candles_count": len(candles_snapshot.split("\n")) if candles_snapshot else 0,
        "news_count_24h": news_count_24h,
        "news_warning": news_warning,
    }
    if not result.success:
        msg = result.error_msg or "AI 分析失败"
        if news_warning:
            msg += " | " + news_warning
        return success(payload, message=msg)
    msg = "AI 分析完成"
    if unified["source"] == "pool":
        msg = f"AI 分析完成（已自动切换到接口池: {unified.get('used_key_name', '')}）"
    if news_warning:
        msg += " | " + news_warning
    return success(payload, message=msg)


@ai_router.get("/status")
def ai_status(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """检查 AI 连接状态（主配置 + 接口池），供前端绿灯/红灯显示"""
    from backend.services.ai_failover import check_ai_status
    return success(check_ai_status(db))


@ai_router.get("/records")
def ai_records(
    q: PaginationParams = Depends(),
    symbol: Optional[str] = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    # 确保表存在（新库首次访问无 ai_analysis_records 时也 OK）
    from backend.db.session import engine_sync
    insp2 = sa_inspect(engine_sync)
    if "ai_analysis_records" not in insp2.get_table_names():
        AIAnalysisRecord.__table__.create(bind=engine_sync, checkfirst=True)

    query = db.query(AIAnalysisRecord)
    if user.role != 1:
        query = query.filter(AIAnalysisRecord.user_id == user.id)
    if symbol:
        query = query.filter(AIAnalysisRecord.symbol == symbol)
    return success(paginate(query, q.page, q.page_size, q.order_by))


# ==================== 新闻 ====================
news_router = APIRouter(prefix="/news", tags=["新闻情绪"])


@news_router.get("/status")
def news_status(
    request: Request,
    user: User = Depends(get_current_user),
):
    """新闻系统调度器状态"""
    scheduler = getattr(request.app.state, "scheduler", None)
    running = scheduler is not None and scheduler.running
    jobs = []
    if running:
        for job in scheduler.get_jobs():
            jobs.append({
                "id": job.id,
                "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
            })
    return success({"running": running, "jobs": jobs})


@news_router.get("", response_model=ApiResponse[dict])
def list_news(
    q: PaginationParams = Depends(),
    keyword: str = "",
    category: str = "",
    sentiment: int | None = None,
    impact: int | None = None,
    related_symbol: str = "",
    db: Session = Depends(get_db),
):
    """新闻列表（含情绪分析）"""
    query = db.query(NewsArticle)
    if keyword:
        like = f"%{keyword}%"
        query = query.filter(NewsArticle.title.like(like))
    if category:
        query = query.filter(NewsArticle.category == category)
    if sentiment is not None:
        query = query.filter(NewsArticle.sentiment == sentiment)
    if impact is not None:
        query = query.filter(NewsArticle.impact_level == impact)
    if related_symbol:
        query = query.filter(NewsArticle.related_symbols.like(f'%"{related_symbol}"%'))
    return success(paginate(query, q.page, q.page_size, "-published_at"))


@news_router.post("/collect")
def collect_news(source: str = "all", lookback_hours: int = 48,
                 db: Session = Depends(get_db), user: User = Depends(require_editor)):
    """手动触发新闻采集（8 个国际源 + FRED/EIA 官方数据 + VADER 情绪）。
    - source=all 跑所有源；其他值目前与 all 等价
    - 响应里带 per_source 的抓取/新增数，方便看哪些源没抓到
    """
    try:
        from backend.news.pipeline import NewsPipeline
        from backend.news.crawlers import ALL_CRAWLERS
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"NewsPipeline 导入失败：{e}")

    from datetime import datetime
    t0 = datetime.now()
    try:
        pipeline = NewsPipeline(lookback_hours=max(1, int(lookback_hours)), max_workers=4)
        res = pipeline.run_once(db=db)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"新闻采集失败：{e}")
    elapsed = (datetime.now() - t0).total_seconds()
    return success({
        "fetched": res.total_fetched,
        "inserted": res.total_inserted,
        "skipped_dup": res.total_skipped_dup,
        "per_source": res.per_source,
        "errors": res.errors[-20:],
        "elapsed_seconds": round(elapsed, 2),
        "sources_count": len(ALL_CRAWLERS),
    }, message=f"采集完成，新增 {res.total_inserted} 条")


# ------------------ 代理健康检查 ------------------
@news_router.get("/proxy/health")
def proxy_health(user: User = Depends(get_current_user)):
    """查看当前代理池健康度（前端配置页/运维面板可直接调用）"""
    from backend.core.proxy_manager import ProxyManager
    return success(ProxyManager.get_instance().health_report())


@news_router.get("/sentiment/summary")
def sentiment_summary(
    symbol: str = "BTC",
    hours: int = 24,
    db: Session = Depends(get_db),
):
    """过去N小时情绪汇总（DB 方言无关实现：先按时间过滤，再在 Python 层按 symbol 过滤，
    彻底规避 MySQL JSON_CONTAINS / SQLite LIKE 的方言差异，保证 fallback 环境稳定）"""
    cutoff = datetime.now() - timedelta(hours=hours)
    rows = db.query(NewsArticle).filter(NewsArticle.published_at >= cutoff).all()
    if symbol:
        # related_symbols 在模型层为 List[str]，在 ORM 读取后已是原生 list，直接 in 判断即可
        rows = [r for r in rows if isinstance(r.related_symbols, list) and symbol in r.related_symbols]
    total = len(rows)
    pos = sum(1 for r in rows if r.sentiment == 1)
    neg = sum(1 for r in rows if r.sentiment == -1)
    neu = total - pos - neg
    from sqlalchemy import func as sa_func
    avg_score = 0.0
    if total:
        scores = [float(r.sentiment_score or 0) for r in rows if r.sentiment_score is not None]
        if scores:
            avg_score = sum(scores) / len(scores)
    return success({
        "symbol": symbol,
        "hours": hours,
        "total": total,
        "positive": pos,
        "negative": neg,
        "neutral": neu,
        "avg_sentiment_score": round(float(avg_score), 3),
        "news_pnl_score": round(max(0, min(3, (1 + float(avg_score)) * 1.5)), 2),
    })


@news_router.post("/ai-analyze")
def ai_analyze_news(
    hours: int = 6,
    limit: int = 20,
    db: Session = Depends(get_db),
    user: User = Depends(require_editor),
):
    """对近期重要新闻进行AI深度分析（多API轮询）"""
    try:
        from backend.services.news_ai_analyzer import batch_analyze_with_ai
        result = batch_analyze_with_ai(db, hours=hours, limit=limit)
        return success(result, message=f"AI分析完成：{result['analyzed']}/{result['total']} 条已分析")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI分析失败：{e}")


@news_router.get("/sources")
def news_sources(user: User = Depends(get_current_user)):
    """获取所有新闻源列表"""
    from backend.news.crawlers import ALL_CRAWLERS
    sources = []
    for cls in ALL_CRAWLERS:
        sources.append({
            "code": int(cls.SOURCE_CODE),
            "name": cls.SOURCE_DISPLAY,
        })
    return success({"sources": sources, "total": len(sources)})


@news_router.get("/keywords/stats")
def keyword_stats(user: User = Depends(get_current_user)):
    """获取关键词库统计信息"""
    from backend.services.news_keywords import get_keyword_stats
    return success(get_keyword_stats())


@news_router.post("/auto-collect")
def auto_collect_news(
    db: Session = Depends(get_db),
    user: User = Depends(require_editor),
):
    """一键执行：采集新闻 + 关键词预筛选 + AI深度分析（全自动流程）"""
    from datetime import datetime
    t0 = datetime.now()

    # Step 1: 采集新闻
    try:
        from backend.news.pipeline import NewsPipeline
        pipeline = NewsPipeline(lookback_hours=48, max_workers=6)
        crawl_result = pipeline.run_once(db=db)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"新闻采集失败：{e}")

    # Step 2: AI深度分析（关键词预筛选）
    ai_result = {"analyzed": 0, "failed": 0, "skipped_not_important": 0}
    try:
        from backend.services.news_ai_analyzer import batch_analyze_with_ai
        ai_result = batch_analyze_with_ai(db, hours=6, limit=20)
    except Exception as e:
        logger.warning(f"[News] AI分析失败（不影响采集结果）: {e}")

    elapsed = (datetime.now() - t0).total_seconds()
    return success({
        "crawl": {
            "fetched": crawl_result.total_fetched,
            "inserted": crawl_result.total_inserted,
            "skipped_dup": crawl_result.total_skipped_dup,
            "per_source": crawl_result.per_source,
            "errors": crawl_result.errors[-5:],
        },
        "ai_analysis": ai_result,
        "elapsed_seconds": round(elapsed, 2),
    }, message=f"采集{crawl_result.total_inserted}条，AI分析{ai_result.get('analyzed', 0)}条，耗时{elapsed:.1f}s")


# ==================== 新闻AI多API配置（轮询/故障转移） ====================

class NewsAIConfigCreate(BaseModel):
    name: str = Field(..., max_length=64, description="配置名称，如'主API''备用API1'")
    provider: str = "custom"
    api_endpoint: str = ""
    api_key: str = ""
    model_name: str = "gpt-4o-mini"
    enabled: bool = True
    priority: int = 1


class NewsAIConfigUpdate(BaseModel):
    name: Optional[str] = None
    provider: Optional[str] = None
    api_endpoint: Optional[str] = None
    api_key: Optional[str] = None
    model_name: Optional[str] = None
    enabled: Optional[bool] = None
    priority: Optional[int] = None


class NewsAIConfigTest(BaseModel):
    provider: str = "custom"
    api_endpoint: str = ""
    api_key: str = ""
    model_name: str = "gpt-4o-mini"


def _load_news_ai_configs(db: Session, strip_encrypted: bool = True) -> List[Dict]:
    """从 SystemConfig 加载新闻AI配置列表（解密api_key）"""
    from backend.models.system_config import SystemConfig
    row = db.query(SystemConfig).filter(SystemConfig.config_key == "news_ai_configs").first()
    if not row or not row.config_value:
        return []
    try:
        import json
        items = json.loads(row.config_value)
        for item in items:
            if item.get("api_key_encrypted"):
                decrypted = decrypt_api_key(item["api_key_encrypted"])
                item["api_key_masked"] = mask_api_key(decrypted)
                item["has_key"] = True
                # strip_encrypted=False 时保留明文 key，供内部使用（测试/故障转移）
                if not strip_encrypted:
                    item["api_key"] = decrypted
            else:
                item["api_key_masked"] = ""
                item["has_key"] = False
                if not strip_encrypted:
                    item["api_key"] = ""
            if strip_encrypted:
                item.pop("api_key_encrypted", None)
                item.pop("api_key", None)
        return items
    except Exception as e:
        logger.warning(f"[NewsAI] 配置解析失败: {e}")
        return []


def _save_news_ai_configs(db: Session, items: List[Dict]):
    """保存新闻AI配置列表（加密api_key）"""
    from backend.models.system_config import SystemConfig
    import json
    row = db.query(SystemConfig).filter(SystemConfig.config_key == "news_ai_configs").first()
    if not row:
        row = SystemConfig(
            config_key="news_ai_configs",
            config_type="json",
            category="ai",
            description="新闻AI多API配置（轮询/故障转移）",
        )
        db.add(row)
    safe_items = []
    for item in items:
        safe = {k: v for k, v in item.items() if k not in ("api_key_masked", "has_key")}
        if safe.get("api_key"):
            safe["api_key_encrypted"] = encrypt_api_key(safe["api_key"])
        safe.pop("api_key", None)
        if "id" not in safe:
            import uuid
            safe["id"] = uuid.uuid4().hex[:12]
        safe_items.append(safe)
    row.config_value = json.dumps(safe_items, ensure_ascii=False)
    db.commit()


@news_router.get("/ai-configs")
def list_news_ai_configs(
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """获取新闻AI多API配置列表（不含明文Key）"""
    configs = _load_news_ai_configs(db)
    return success({"configs": configs, "total": len(configs)})


@news_router.post("/ai-configs")
def create_news_ai_config(
    req: NewsAIConfigCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """新增新闻AI API配置"""
    import uuid
    configs = _load_news_ai_configs(db, strip_encrypted=False)
    new_item = {
        "id": uuid.uuid4().hex[:12],
        "name": req.name.strip(),
        "provider": req.provider,
        "api_endpoint": req.api_endpoint.strip(),
        "api_key": req.api_key,
        "model_name": req.model_name.strip(),
        "enabled": req.enabled,
        "priority": req.priority,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    configs.append(new_item)
    _save_news_ai_configs(db, configs)
    return success({"id": new_item["id"]}, message="新闻AI配置已添加")


@news_router.put("/ai-configs/{cid}")
def update_news_ai_config(
    cid: str,
    req: NewsAIConfigUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """更新新闻AI API配置"""
    configs = _load_news_ai_configs(db, strip_encrypted=False)
    found = False
    for item in configs:
        if item["id"] == cid:
            if req.name is not None:
                item["name"] = req.name.strip()
            if req.provider is not None:
                item["provider"] = req.provider
            if req.api_endpoint is not None:
                item["api_endpoint"] = req.api_endpoint.strip()
            if req.api_key is not None and req.api_key:
                item["api_key"] = req.api_key
            if req.model_name is not None:
                item["model_name"] = req.model_name.strip()
            if req.enabled is not None:
                item["enabled"] = req.enabled
            if req.priority is not None:
                item["priority"] = req.priority
            found = True
            break
    if not found:
        raise NotFoundException("配置不存在")
    _save_news_ai_configs(db, configs)
    return success(message="新闻AI配置已更新")


@news_router.delete("/ai-configs/{cid}")
def delete_news_ai_config(
    cid: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """删除新闻AI API配置"""
    configs = _load_news_ai_configs(db, strip_encrypted=False)
    new_configs = [c for c in configs if c["id"] != cid]
    if len(new_configs) == len(configs):
        raise NotFoundException("配置不存在")
    _save_news_ai_configs(db, new_configs)
    return success(message="新闻AI配置已删除")


@news_router.post("/ai-configs/test")
async def test_news_ai_config(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """测试新闻AI API连接（直接解析请求体，避免Pydantic校验422）"""
    import requests as _requests
    import time
    import uuid
    try:
        body = await request.json()
        api_key = body.get("api_key", "").strip()
        api_endpoint = (body.get("api_endpoint") or "").strip()
        model_name = (body.get("model_name") or "").strip()
        config_id = body.get("config_id", "")

        # 编辑模式且未提供新Key时，从数据库读取现有Key
        if config_id and (not api_key or api_key == "__USE_EXISTING__"):
            configs = _load_news_ai_configs(db, strip_encrypted=False)
            for item in configs:
                if item.get("id") == config_id and item.get("api_key"):
                    api_key = item["api_key"]
                    break

        if not api_key:
            raise BizException("请先输入或选择API Key", code=4001, http_status=400)
        if not model_name:
            raise BizException("请输入模型名称", code=4001, http_status=400)

        endpoint = api_endpoint.rstrip("/") if api_endpoint else "https://api.openai.com/v1"
        if not endpoint.endswith("/chat/completions"):
            endpoint = f"{endpoint}/chat/completions"
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
        payload = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "Say OK in one word."},
            ],
            "max_tokens": 10,
            "temperature": 0,
        }
        t0 = time.time()
        resp = _requests.post(endpoint, json=payload, headers=headers, timeout=15)
        latency = int((time.time() - t0) * 1000)
        if resp.status_code != 200:
            raise Exception(f"HTTP {resp.status_code}: {resp.text[:200]}")
        data = resp.json()
        result = {"latency_ms": latency, "model": data.get("model", "")}
        # 更新该配置的健康状态
        if config_id:
            configs = _load_news_ai_configs(db, strip_encrypted=False)
            for item in configs:
                if item.get("id") == config_id:
                    item["health_status"] = "ok"
                    item["last_test_at"] = datetime.now().isoformat(timespec="seconds")
                    item["last_test_latency_ms"] = latency
                    break
            _save_news_ai_configs(db, configs)
        return success(result, message="连接成功")
    except (ParameterException, BizException):
        raise
    except Exception as e:
        # 更新健康状态为error
        if config_id:
            try:
                configs = _load_news_ai_configs(db, strip_encrypted=False)
                for item in configs:
                    if item.get("id") == config_id:
                        item["health_status"] = "error"
                        item["last_test_at"] = datetime.now().isoformat(timespec="seconds")
                        break
                _save_news_ai_configs(db, configs)
            except Exception:
                pass
        raise BizException(f"连接测试失败: {e}", code=5020, http_status=502)


# ==================== 风控事件 ====================
risk_router = APIRouter(prefix="/risk", tags=["风控事件"])


@risk_router.get("/events")
def risk_events(
    q: PaginationParams = Depends(),
    event_type: int | None = None,
    severity: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """风控事件日志"""
    query = db.query(RiskEventLog)
    if user.role != 1:
        query = query.filter(RiskEventLog.user_id == user.id)
    if event_type is not None:
        query = query.filter(RiskEventLog.event_type == event_type)
    if severity is not None:
        query = query.filter(RiskEventLog.severity == severity)
    return success(paginate(query, q.page, q.page_size, q.order_by))


@risk_router.get("/summary")
def risk_summary(
    days: int = 7,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """近期风控摘要"""
    cutoff = datetime.now() - timedelta(days=days)
    q = db.query(RiskEventLog).filter(RiskEventLog.created_at >= cutoff)
    if user.role != 1:
        q = q.filter(RiskEventLog.user_id == user.id)
    total = q.count()
    from sqlalchemy import func as sa_func
    by_severity = dict(q.with_entities(
        RiskEventLog.severity, sa_func.count(RiskEventLog.id)
    ).group_by(RiskEventLog.severity).all())
    by_type = dict(q.with_entities(
        RiskEventLog.event_type, sa_func.count(RiskEventLog.id)
    ).group_by(RiskEventLog.event_type).all())
    return success({
        "days": days,
        "total_events": total,
        "by_severity": by_severity,
        "by_type": by_type,
    })


# ==================== 历史回测 ====================
backtest_router = APIRouter(prefix="/backtests", tags=["历史回测"])


class BacktestCreateReq(BaseModel):
    strategy_id: Optional[int] = None
    run_name: str = Field(default="", max_length=255)
    symbols: List[str] = Field(default_factory=lambda: ["BTC", "ETH"])
    timeframe: str = "4h"
    date_start: datetime
    date_end: datetime
    initial_capital: float = 10000.0
    fee_rate: float = 0.04
    slippage: float = 0.05
    strategy_params: dict = Field(default_factory=dict)


@backtest_router.get("", response_model=ApiResponse[dict])
def list_backtests(
    q: PaginationParams = Depends(),
    status: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """回测任务列表"""
    query = db.query(BacktestRun)
    if user.role != 1:
        query = query.filter(BacktestRun.user_id == user.id)
    if status is not None:
        query = query.filter(BacktestRun.status == status)
    return success(paginate(query, q.page, q.page_size, q.order_by))


@backtest_router.post("")
def create_backtest(
    req: BacktestCreateReq,
    db: Session = Depends(get_db),
    user: User = Depends(require_trader),
):
    """创建回测任务（后台异步执行）"""
    if req.date_start >= req.date_end:
        raise ParameterException("开始日期必须早于结束日期")
    if req.initial_capital <= 0:
        raise ParameterException("初始资金必须大于0")

    # 从策略配置自动填充参数
    strategy_params = req.strategy_params or {}
    if req.strategy_id:
        try:
            from backend.models.strategy import StrategyConfig
            sc = db.query(StrategyConfig).filter(StrategyConfig.id == req.strategy_id).first()
            if sc:
                strategy_params.setdefault("strategy_type", getattr(sc, "strategy_type", None) or "ma_rsi")
                strategy_params.setdefault("tp_ratio", float(getattr(sc, "tp_ratio", 3.0) or 3.0))
                strategy_params.setdefault("sl_ratio", float(getattr(sc, "sl_ratio", 1.5) or 1.5))
                strategy_params.setdefault("leverage_fixed", int(getattr(sc, "leverage_fixed", 3) or 3))
                strategy_params.setdefault("single_position_ratio", float(getattr(sc, "single_position_ratio", 10) or 10))
                strategy_params.setdefault("score_threshold", float(getattr(sc, "score_threshold", 5.0) or 5.0))
                if not strategy_params.get("strategy_type"):
                    strategy_params["strategy_type"] = "ma_rsi"
        except Exception as e:
            logger.warning(f"[Backtest] 加载策略参数失败: {e}")
    else:
        strategy_params.setdefault("strategy_type", "ma_rsi")

    run = BacktestRun(
        user_id=user.id,
        strategy_id=req.strategy_id,
        run_name=req.run_name or f"回测-{datetime.now():%m%d-%H%M}",
        symbols=req.symbols,
        timeframe=req.timeframe,
        date_start=req.date_start,
        date_end=req.date_end,
        initial_capital=req.initial_capital,
        fee_rate=req.fee_rate,
        slippage=req.slippage,
        param_snapshot=strategy_params,
        status=0,
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    # 后台线程执行回测
    import threading
    from backend.db.session import SessionLocal
    from backend.services.backtest_engine import run_backtest

    def _bg_backtest():
        bg_db = SessionLocal()
        try:
            bg_run = bg_db.query(BacktestRun).filter(BacktestRun.id == run.id).first()
            if bg_run:
                run_backtest(bg_db, bg_run)
        except Exception as e:
            logger.error(f"[Backtest] 后台执行失败: {e}")
            try:
                bg_run = bg_db.query(BacktestRun).filter(BacktestRun.id == run.id).first()
                if bg_run:
                    bg_run.status = BacktestRun.STATUS_FAILED
                    bg_run.error_msg = str(e)[:500]
                    bg_run.finished_at = datetime.now()
                    bg_db.commit()
            except:
                pass
        finally:
            bg_db.close()

    t = threading.Thread(target=_bg_backtest, daemon=True)
    t.start()

    return success({"id": run.id}, message="回测任务已创建，正在执行中")


@backtest_router.get("/{bid}")
def get_backtest(bid: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """回测详情与报告"""
    run = db.query(BacktestRun).filter(BacktestRun.id == bid).first()
    if not run or (user.role != 1 and run.user_id != user.id):
        raise NotFoundException("回测任务不存在")
    data = {c.name: getattr(run, c.name) for c in run.__table__.columns}
    return success(data)


@backtest_router.delete("/{bid}")
def delete_backtest(bid: int, db: Session = Depends(get_db), user: User = Depends(require_trader)):
    run = db.query(BacktestRun).filter(BacktestRun.id == bid).first()
    if not run or (user.role != 1 and run.user_id != user.id):
        raise NotFoundException("回测任务不存在")
    if run.status == 1:
        raise ParameterException("运行中的回测无法删除，请先终止")
    db.delete(run)
    db.commit()
    return success(message="删除成功")


# ==================== 财务报表 ====================
report_router = APIRouter(prefix="/reports", tags=["财务报表"])


@report_router.get("/daily")
def daily_reports(
    start_date: str = "",
    end_date: str = "",
    account_id: int | None = None,
    page: int = 1,
    page_size: int = 30,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """日报表列表"""
    query = db.query(DailyFinancialReport)
    if user.role != 1:
        query = query.filter(DailyFinancialReport.user_id == user.id)
    if account_id:
        query = query.filter(DailyFinancialReport.exchange_account_id == account_id)
    if start_date:
        query = query.filter(DailyFinancialReport.report_date >= start_date)
    if end_date:
        query = query.filter(DailyFinancialReport.report_date <= end_date)
    return success(paginate(query, page, page_size, "-report_date"))


@report_router.get("/weekly")
def weekly_reports(
    year: int | None = None,
    account_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """周报表"""
    query = db.query(WeeklyFinancialReport)
    if user.role != 1:
        query = query.filter(WeeklyFinancialReport.user_id == user.id)
    if account_id:
        query = query.filter(WeeklyFinancialReport.exchange_account_id == account_id)
    if year:
        query = query.filter(WeeklyFinancialReport.week_key.like(f"{year}-%"))
    items = query.order_by(WeeklyFinancialReport.week_key.desc()).limit(52).all()
    return success({"items": items, "total": len(items)})


@report_router.get("/monthly")
def monthly_reports(
    account_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """月报表"""
    query = db.query(MonthlyFinancialReport)
    if user.role != 1:
        query = query.filter(MonthlyFinancialReport.user_id == user.id)
    if account_id:
        query = query.filter(MonthlyFinancialReport.exchange_account_id == account_id)
    items = query.order_by(MonthlyFinancialReport.month_key.desc()).limit(24).all()
    return success({"items": items, "total": len(items)})


@report_router.get("/dashboard")
def dashboard_report(
    days: int = 30,
    account_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """首页Dashboard 汇总数据
    - 普通用户：只看自己的数据
    - 超级管理员：汇总所有用户数据（按日期聚合，避免多用户行叠加）
    """
    from sqlalchemy import func as sa_func
    end = date.today()
    start = end - timedelta(days=days - 1)
    
    # 基础过滤
    q = db.query(DailyFinancialReport).filter(
        DailyFinancialReport.report_date.between(start.isoformat(), end.isoformat()),
        DailyFinancialReport.exchange_account_id.is_(None),  # 全账号汇总行
    )
    if user.role != 1:
        q = q.filter(DailyFinancialReport.user_id == user.id)
    if account_id:
        q = q.filter(DailyFinancialReport.exchange_account_id == account_id)
    
    # 管理员场景：按日期聚合所有用户数据，避免每天多条数据点
    if user.role == 1:
        agg_rows = q.with_entities(
            DailyFinancialReport.report_date,
            sa_func.sum(DailyFinancialReport.end_balance).label("end_balance"),
            sa_func.sum(DailyFinancialReport.total_pnl).label("total_pnl"),
            sa_func.sum(DailyFinancialReport.trade_count).label("trade_count"),
            sa_func.avg(DailyFinancialReport.win_rate).label("win_rate"),
        ).group_by(
            DailyFinancialReport.report_date
        ).order_by(
            DailyFinancialReport.report_date
        ).all()
        
        dates = [r.report_date for r in agg_rows]
        balance_curve = [float(r.end_balance or 0) for r in agg_rows]
        pnl_curve = [float(r.total_pnl or 0) for r in agg_rows]
        trade_count_list = [int(r.trade_count or 0) for r in agg_rows]
        win_rate_list = [float(r.win_rate or 0) for r in agg_rows]
        
        total_pnl = sum(float(r.total_pnl or 0) for r in agg_rows)
        total_trades = sum(int(r.trade_count or 0) for r in agg_rows)
        today_row = agg_rows[-1] if agg_rows else None
        today_pnl = float(today_row.total_pnl or 0) if today_row else 0
        today_count = int(today_row.trade_count or 0) if today_row else 0
    else:
        # 普通用户：直接取自己的数据行
        rows = q.order_by(DailyFinancialReport.report_date).all()
        dates = [r.report_date for r in rows]
        pnl_curve = [float(r.total_pnl) for r in rows]
        balance_curve = [float(r.end_balance) for r in rows]
        trade_count_list = [r.trade_count for r in rows]
        win_rate_list = [r.win_rate for r in rows]
        
        total_pnl = sum(float(r.total_pnl) for r in rows)
        total_trades = sum(r.trade_count for r in rows)
        today_row = rows[-1] if rows else None
        today_pnl = float(today_row.total_pnl) if today_row else 0
        today_count = today_row.trade_count if today_row else 0

    # 历史全部汇总
    hist_all = db.query(MonthlyFinancialReport)
    if user.role != 1:
        hist_all = hist_all.filter(MonthlyFinancialReport.user_id == user.id)
    agg = hist_all.with_entities(
        sa_func.coalesce(sa_func.sum(MonthlyFinancialReport.total_pnl), 0),
        sa_func.coalesce(sa_func.sum(MonthlyFinancialReport.total_trade_count), 0),
        sa_func.coalesce(sa_func.avg(MonthlyFinancialReport.win_rate), 0),
    ).first() or (0, 0, 0)
    hist_pnl, hist_count, avg_winrate = agg

    return success({
        "days": days,
        "dates": dates,
        "pnl_curve": pnl_curve,
        "balance_curve": balance_curve,
        "trade_count_curve": trade_count_list,
        "win_rate_curve": win_rate_list,
        "period_total_pnl": round(total_pnl, 2),
        "period_trade_count": total_trades,
        "today_pnl": round(today_pnl, 2),
        "today_trade_count": today_count,
        "historical_total_pnl": round(float(hist_pnl), 2),
        "historical_trade_count": int(hist_count),
        "average_win_rate": round(float(avg_winrate), 2),
    })


# ======================== AI 综合预测 ========================

PREDICTION_SYMBOLS = ["BTC", "ETH", "SOL", "XAU", "WTI", "SAND", "HBAR"]

_OKX_INST_MAP = {
    "WTI": ["CL-USDT-SWAP", "CLUSDT", "WTI-USDT-SWAP"],
    "XAU": ["XAU-USDT-SWAP", "XAUUSDT"],
    "XAG": ["XAG-USDT-SWAP", "XAGUSDT"],
}

_commodity_price_cache: Dict[str, dict] = {}


def _fetch_commodity_price(symbol: str) -> Optional[float]:
    """从OKX公共API获取商品价格（WTI/XAU等），带5秒缓存"""
    import requests as _requests
    inst_ids = _OKX_INST_MAP.get(symbol)
    if not inst_ids:
        return None
    cache = _commodity_price_cache.get(symbol, {})
    if cache and time.time() - cache.get("ts", 0) < 5:
        return cache.get("price")
    for inst_id in inst_ids:
        try:
            r = _requests.get(
                "https://www.okx.com/api/v5/market/ticker",
                params={"instId": inst_id},
                timeout=5,
            )
            data = r.json().get("data", [{}])[0]
            price = float(data.get("last", 0))
            if price > 0:
                _commodity_price_cache[symbol] = {"price": price, "ts": time.time()}
                logger.info(f"[Prediction] OKX获取{symbol}价格成功: {price} (instId={inst_id})")
                return price
        except Exception as e:
            logger.debug(f"[Prediction] OKX {inst_id} 获取{symbol}价格失败: {e}")
    return None

# Polymarket 缓存（避免每次请求都发HTTP）
_poly_cache: Dict = {"data": {}, "timestamp": 0.0}
POLY_CACHE_TTL = 300  # 5分钟缓存


def _fetch_all_polymarket_odds() -> Dict[str, float]:
    """批量获取所有币种的Polymarket预测概率（带缓存，一次HTTP请求）"""
    import httpx
    import time
    global _poly_cache

    now_ts = time.time()
    if now_ts - _poly_cache["timestamp"] < POLY_CACHE_TTL and _poly_cache["data"]:
        return _poly_cache["data"]

    result: Dict[str, float] = {}
    try:
        url = "https://clob.polymarket.com/markets"
        params = {"next_cursor": "MA=="}
        r = httpx.get(url, params=params, timeout=3)  # 3秒超时，不卡主流程
        if r.status_code != 200:
            return result
        data = r.json()

        markets = data.get("data", [])[:100]
        for sym in PREDICTION_SYMBOLS:
            sym_upper = sym.upper()
            for m in markets:
                question = (m.get("question") or "").upper()
                if sym_upper in question and ("UP" in question or "DOWN" in question or "ABOVE" in question or "BELOW" in question):
                    outcomes = m.get("outcomes") or []
                    if len(outcomes) >= 2:
                        prices = m.get("outcome_prices") or m.get("prices") or ""
                        if isinstance(prices, str):
                            import json
                            try:
                                prices = json.loads(prices)
                            except Exception:
                                continue
                        if isinstance(prices, list) and len(prices) >= 2:
                            result[sym] = float(prices[0])
                            break

        _poly_cache["data"] = result
        _poly_cache["timestamp"] = now_ts
    except Exception:
        pass

    return result


def _fetch_polymarket_odds(symbol: str) -> float | None:
    """从缓存获取单个币种的Polymarket概率（兼容旧接口）"""
    all_odds = _fetch_all_polymarket_odds()
    return all_odds.get(symbol.upper())


def _score_to_signal(score: float, threshold: float = 5.0) -> float:
    """评分(0-10) → 信号(-1 ~ +1)"""
    if score >= threshold + 2:
        return min(1.0, (score - threshold) / 3.0)
    elif score <= threshold - 2:
        return max(-1.0, (score - threshold) / 3.0)
    else:
        return (score - threshold) / 4.0


# =========================================================
#  CryptoPanic WebSocket 实时新闻配置
# =========================================================

class CryptoPanicConfigReq(BaseModel):
    token: str = Field(..., description="CryptoPanic API Token")
    auto_close: bool = Field(default=True, description="突发新闻自动止损")
    auto_trade: bool = Field(default=True, description="突发新闻自动交易")


@router.get("/cryptopanic/config")
def get_cryptopanic_config(
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """获取 CryptoPanic WebSocket 配置 + 连接状态"""
    from backend.models.system_config import SystemConfig
    from backend.services.cryptopanic_ws import CryptoPanicWSClient

    row = db.query(SystemConfig).filter(
        SystemConfig.config_key == "cryptopanic_config"
    ).first()

    token_masked = ""
    auto_close = True
    auto_trade = True
    if row and row.config_value:
        import json
        try:
            cfg = json.loads(row.config_value)
            if cfg.get("token_encrypted"):
                token_masked = mask_api_key(decrypt_api_key(cfg["token_encrypted"]))
            auto_close = cfg.get("auto_close", True)
            auto_trade = cfg.get("auto_trade", True)
        except Exception:
            pass

    client = CryptoPanicWSClient.get_instance()
    status = client.status

    return success({
        "token_masked": token_masked,
        "token_configured": bool(token_masked),
        "auto_close": auto_close,
        "auto_trade": auto_trade,
        "ws_status": status,
        "news_source_mode": "websocket" if status["status"] == "connected" else "rss_fallback",
    })


@router.put("/cryptopanic/config")
async def save_cryptopanic_config(
    req: CryptoPanicConfigReq,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """保存 CryptoPanic 配置并自动重启 WebSocket"""
    from backend.models.system_config import SystemConfig
    from backend.services.cryptopanic_ws import CryptoPanicWSClient
    import json

    row = db.query(SystemConfig).filter(
        SystemConfig.config_key == "cryptopanic_config"
    ).first()
    if not row:
        row = SystemConfig(
            config_key="cryptopanic_config",
            config_type="json",
            category="news",
            description="CryptoPanic WebSocket 实时新闻配置",
        )
        db.add(row)

    cfg = {"auto_close": req.auto_close, "auto_trade": req.auto_trade}
    if req.token and req.token != "__USE_EXISTING__":
        cfg["token_encrypted"] = encrypt_api_key(req.token)
    else:
        if row.config_value:
            try:
                old = json.loads(row.config_value)
                cfg["token_encrypted"] = old.get("token_encrypted", "")
            except Exception:
                pass

    row.config_value = json.dumps(cfg, ensure_ascii=False)
    db.commit()

    # 配置更新后重启 WebSocket
    client = CryptoPanicWSClient.get_instance()
    await client.stop()

    token_plain = ""
    if cfg.get("token_encrypted"):
        token_plain = decrypt_api_key(cfg["token_encrypted"])
    if token_plain:
        client.configure(token_plain, auto_close=req.auto_close)
        result = await client.start()
        return success({"message": result["message"], "ws_status": client.status})
    else:
        return success({"message": "配置已保存（未设置Token，使用RSS轮询模式）", "ws_status": client.status})


@router.post("/cryptopanic/test")
async def test_cryptopanic_connection(
    req: CryptoPanicConfigReq,
    user: User = Depends(require_admin),
):
    """测试 CryptoPanic WebSocket 连通性"""
    from backend.services.cryptopanic_ws import CryptoPanicWSClient

    if not req.token or req.token == "__USE_EXISTING__":
        raise ParameterException("请输入 CryptoPanic Token")

    client = CryptoPanicWSClient.get_instance()
    result = await client.test_connection(req.token)
    if result["success"]:
        return success(result)
    else:
        raise ParameterException(result["message"])


@router.post("/cryptopanic/start")
async def start_cryptopanic_ws(
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """手动启动新闻服务（有Token用WebSocket，无Token用RSS轮询）"""
    from backend.models.system_config import SystemConfig
    from backend.services.cryptopanic_ws import CryptoPanicWSClient
    import json

    row = db.query(SystemConfig).filter(
        SystemConfig.config_key == "cryptopanic_config"
    ).first()

    client = CryptoPanicWSClient.get_instance()

    if row and row.config_value:
        cfg = json.loads(row.config_value)
        token_plain = decrypt_api_key(cfg.get("token_encrypted", "")) if cfg.get("token_encrypted") else ""
        if token_plain:
            client.configure(token_plain, auto_close=cfg.get("auto_close", True), auto_trade=cfg.get("auto_trade", True))
        else:
            client.configure("", auto_close=cfg.get("auto_close", True), auto_trade=cfg.get("auto_trade", True))
    else:
        client.configure("", auto_close=True, auto_trade=True)

    result = await client.start()
    return success({"message": result["message"], "ws_status": client.status})


@router.post("/cryptopanic/stop")
async def stop_cryptopanic_ws(
    user: User = Depends(require_admin),
):
    """手动停止 WebSocket 连接"""
    from backend.services.cryptopanic_ws import CryptoPanicWSClient
    client = CryptoPanicWSClient.get_instance()
    result = await client.stop()
    return success({"message": result["message"], "ws_status": client.status})


def _run_with_timeout(fn, timeout_sec=8.0, *args, **kwargs):
    """在子线程中运行函数，超时则返回 None"""
    result = [None]
    exception = [None]

    def _target():
        try:
            result[0] = fn(*args, **kwargs)
        except Exception as e:
            exception[0] = e

    t = threading.Thread(target=_target, daemon=True)
    t.start()
    t.join(timeout=timeout_sec)
    if t.is_alive():
        raise TimeoutError(f"function timed out after {timeout_sec}s")
    if exception[0]:
        raise exception[0]
    return result[0]


def _compute_predictions(syms, db, poly_odds):
    """核心预测逻辑（可在超时线程中运行）"""
    from backend.models.strategy import StrategyConfig
    from backend.strategy.engine import StrategyEngine

    results = []
    cutoff = datetime.utcnow() - timedelta(hours=24)
    all_articles = db.query(NewsArticle).filter(
        NewsArticle.published_at >= cutoff,
    ).order_by(NewsArticle.published_at.desc()).limit(200).all()

    all_ai: Dict[str, AIAnalysisRecord] = {}
    ai_records = db.query(AIAnalysisRecord).filter(
        AIAnalysisRecord.symbol.in_(syms),
    ).order_by(AIAnalysisRecord.created_at.desc()).all()
    for rec in ai_records:
        if rec.symbol not in all_ai:
            all_ai[rec.symbol] = rec

    strat = db.query(StrategyConfig).filter(StrategyConfig.is_active == True).first()
    eng = StrategyEngine()

    for sym in syms:
        tech_score = None
        tech_dir = 0
        try:
            if strat:
                r, _ = eng.score_symbol(db, strat, sym, "1h", account_id=strat.exchange_id)
                tech_score = round(r.score_total, 2)
                tech_dir = 1 if r.direction == 1 else (-1 if r.direction == 2 else 0)
        except Exception as e:
            logger.warning(f"[Prediction] 技术评分失败 {sym}: {e}")

        news_score = None
        news_dir = 0
        try:
            related = [a for a in all_articles if isinstance(a.related_symbols, list) and sym in a.related_symbols]
            if related:
                positives = sum(1 for a in related if a.sentiment == 1)
                negatives = sum(1 for a in related if a.sentiment == -1)
                neutrals = len(related) - positives - negatives
                total = len(related)
                news_score = round((positives * 8 + neutrals * 5 + negatives * 2) / total, 2)
                news_dir = 1 if positives > negatives else (-1 if negatives > positives else 0)
            elif all_articles:
                news_score = 5.0
        except Exception as e:
            logger.warning(f"[Prediction] 新闻情绪计算失败 {sym}: {e}")

        ai_score = None
        ai_dir = 0
        try:
            ai_rec = all_ai.get(sym)
            if ai_rec:
                ai_score = round(float(ai_rec.ai_score or 5.0), 2)
                ai_dir = 1 if ai_rec.ai_direction == "long" else (-1 if ai_rec.ai_direction == "short" else 0)
        except Exception as e:
            logger.warning(f"[Prediction] AI分析获取失败 {sym}: {e}")

        poly_prob = poly_odds.get(sym)

        signals = []
        weights = []
        if tech_score is not None:
            s = _score_to_signal(tech_score)
            signals.append(s * 0.4)
            weights.append(0.4)
        if news_score is not None:
            s = _score_to_signal(news_score)
            signals.append(s * 0.3)
            weights.append(0.3)
        if ai_score is not None:
            s = _score_to_signal(ai_score)
            signals.append(s * 0.2)
            weights.append(0.2)
        if poly_prob is not None:
            s = (poly_prob - 0.5) * 2
            signals.append(s * 0.1)
            weights.append(0.1)

        if signals:
            total_weight = sum(weights)
            composite = sum(signals) / total_weight if total_weight > 0 else 0
        else:
            composite = 0

        raw_confidence = round(min(95.0, max(15.0, abs(composite) * 100 + 20)), 1)
        if raw_confidence < 15:
            raw_confidence = 15.0

        MIN_CONFIDENCE_FOR_DIRECTION = 35.0
        if raw_confidence < MIN_CONFIDENCE_FOR_DIRECTION:
            direction = "neutral"
            direction_cn = "震荡"
        elif composite > 0.15:
            direction = "bullish"
            direction_cn = "看涨"
        elif composite < -0.15:
            direction = "bearish"
            direction_cn = "看跌"
        else:
            direction = "neutral"
            direction_cn = "震荡"

        predicted_pct = round(composite * 5.0, 2)
        confidence = raw_confidence

        current_price = None
        try:
            from backend.exchanges.market import MarketManager
            mm = MarketManager.get_instance()
            ticker = mm.get_ticker(sym)
            if ticker and ticker.last_price:
                current_price = ticker.last_price
            else:
                klines = mm.get_klines(sym, "1h", limit=2)
                if klines and len(klines) > 0:
                    current_price = klines[-1].close
        except Exception:
            pass

        if not current_price:
            current_price = _fetch_commodity_price(sym)

        target_price = None
        if current_price and predicted_pct:
            target_price = round(current_price * (1 + predicted_pct / 100), 4)

        results.append({
            "symbol": sym,
            "direction": direction,
            "direction_cn": direction_cn,
            "predicted_change_pct": predicted_pct,
            "confidence": confidence,
            "current_price": current_price,
            "target_price": target_price,
            "scores": {
                "technical": tech_score,
                "news": news_score,
                "ai": ai_score,
                "polymarket_prob": round(poly_prob * 100, 1) if poly_prob is not None else None,
            },
            "signals": {
                "technical": tech_dir,
                "news": news_dir,
                "ai": ai_dir,
                "polymarket": 1 if poly_prob and poly_prob > 0.5 else (-1 if poly_prob else 0),
            },
            "composite_signal": round(composite, 3),
        })

    return results


@router.get("/analytics/prediction")
def get_prediction(
    symbols: str = Query("", description="逗号分隔的币种列表，默认BTC,ETH,SOL"),
    db: Session = Depends(get_db),
    user: User = Depends(require_trader),
):
    """综合预测：技术面(40%) + 新闻情绪(30%) + AI分析(20%) + Polymarket(10%)"""
    syms = [s.strip().upper() for s in symbols.split(",") if s.strip()] or PREDICTION_SYMBOLS

    poly_odds = {}
    try:
        poly_odds = _run_with_timeout(_fetch_all_polymarket_odds, timeout_sec=5.0)
    except TimeoutError:
        logger.warning("[Prediction] Polymarket获取超时，跳过")
    except Exception as e:
        logger.warning(f"[Prediction] Polymarket获取失败: {e}")

    try:
        results = _run_with_timeout(_compute_predictions, timeout_sec=15.0, syms=syms, db=db, poly_odds=poly_odds)
    except TimeoutError:
        logger.warning("[Prediction] 预测计算超时，返回基础数据")
        results = []
    except Exception as e:
        logger.warning(f"[Prediction] 预测计算异常: {e}")
        results = []

    return success({"predictions": results, "generated_at": datetime.utcnow().isoformat()})


# ==================== 爬虫健康检测 ====================

@router.get("/news/crawler-health")
def get_crawler_health(db: Session = Depends(get_db), user: User = Depends(require_trader)):
    """检测所有新闻爬虫的健康状态：每个源最近采集量和最后采集时间"""
    from backend.news.crawlers import ALL_CRAWLERS
    from sqlalchemy import func

    source_map = {}
    for cls in ALL_CRAWLERS:
        source_map[cls.SOURCE_CODE] = {
            "source_code": cls.SOURCE_CODE,
            "source_name": cls.SOURCE_DISPLAY,
            "crawler_class": cls.__name__,
        }

    now = datetime.utcnow()
    thresholds = {
        "24h": now - timedelta(hours=24),
        "7d": now - timedelta(days=7),
    }

    rows_24h = (
        db.query(NewsArticle.source, func.count(NewsArticle.id).label("cnt"), func.max(NewsArticle.created_at).label("last"))
        .filter(NewsArticle.created_at >= thresholds["24h"])
        .group_by(NewsArticle.source)
        .all()
    )
    rows_7d = (
        db.query(NewsArticle.source, func.count(NewsArticle.id).label("cnt"))
        .filter(NewsArticle.created_at >= thresholds["7d"])
        .group_by(NewsArticle.source)
        .all()
    )

    stats_24h = {r.source: {"count": r.cnt, "last_at": r.last} for r in rows_24h}
    stats_7d = {r.source: r.cnt for r in rows_7d}

    result = []
    for code, info in source_map.items():
        s24 = stats_24h.get(code, {})
        cnt_24h = s24.get("count", 0)
        cnt_7d = stats_7d.get(code, 0)
        last_at = s24.get("last_at")

        if cnt_24h > 0:
            status = "healthy"
            status_cn = "正常"
        elif cnt_7d > 0:
            status = "warning"
            status_cn = "异常"
        else:
            status = "critical"
            status_cn = "被屏蔽"

        result.append({
            **info,
            "count_24h": cnt_24h,
            "count_7d": cnt_7d,
            "last_article_at": last_at.isoformat() if last_at else None,
            "status": status,
            "status_cn": status_cn,
        })

    result.sort(key=lambda x: x["source_code"])

    healthy = sum(1 for r in result if r["status"] == "healthy")
    warning = sum(1 for r in result if r["status"] == "warning")
    critical = sum(1 for r in result if r["status"] == "critical")
    total_24h = sum(r["count_24h"] for r in result)

    return success({
        "crawlers": result,
        "summary": {
            "total": len(result),
            "healthy": healthy,
            "warning": warning,
            "critical": critical,
            "total_articles_24h": total_24h,
        },
    })
