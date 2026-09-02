"""
策略配置 + 评分记录 路由
GET    /strategies              策略列表
POST   /strategies              创建策略
PUT    /strategies/{id}         更新策略
DELETE /strategies/{id}         删除策略
POST   /strategies/{id}/toggle  启停策略
GET    /strategies/{id}/scores  评分历史
GET    /strategies/scores/latest 最新评分快照
POST   /strategies/{id}/score-symbol  手动对某个品种+周期评分（不执行交易）
POST   /strategies/{id}/run     手动一键执行策略评分 + 按运行模式执行下单
GET    /strategies/default-template  默认策略模板
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime

from backend.db.session import get_db
from backend.core.auth import get_current_user, require_editor, require_trader
from backend.core.exceptions import NotFoundException, ParameterException, success, BizException
from backend.core.schemas import ApiResponse, PaginationParams, paginate
from backend.models.user import User
from backend.models.strategy import StrategyConfig, ScoreRecord
from backend.models.exchange import ExchangeAccount
from backend.strategy.engine import StrategyEngine
from backend.strategy.scoring import StrategyScoringEngine

router = APIRouter(prefix="/strategies", tags=["策略配置"])


# ---------- Schema ----------

class StrategyCreateReq(BaseModel):
    strategy_name: str = Field(..., min_length=1, max_length=128)
    strategy_type: str = Field(default="standard", pattern=r"^(standard|emv|news_ai)$")
    description: str = ""
    symbols: List[str] = Field(default_factory=lambda: ["BTC", "ETH"])
    exchange_id: Optional[int] = None
    timeframe: str = "1h,4h"
    direction_mode: int = 0
    run_mode: int = 3
    score_threshold: float = 5.0
    strong_score_threshold: float = 8.0
    weight_technical: float = 0.4
    weight_news: float = 0.3
    weight_ai: float = 0.3
    leverage_mode: int = 1
    leverage_fixed: int = 3
    leverage_low_score: int = 3
    leverage_mid_score: int = 5
    leverage_high_score: int = 8
    tp_ratio: float = 4.0
    sl_ratio: float = 2.0
    use_exchange_tpsl: bool = True
    single_position_ratio: float = 10.0
    total_position_ratio: float = 50.0
    max_position_count: int = 3
    max_single_drawdown: float = 2.0
    daily_max_loss: float = 5.0
    consecutive_loss_pause: int = 3
    cooldown_hours: int = 24
    priority: int = 0


class ScoreSymbolReq(BaseModel):
    symbol: str = Field(..., min_length=2, max_length=16)
    timeframe: str = Field(default="1h", pattern=r"^(1m|5m|15m|1h|4h|1d)$")
    execute_trade: bool = False


# ---------- 路由 ----------

@router.get("", response_model=ApiResponse[dict])
def list_strategies(
    q: PaginationParams = Depends(),
    is_active: bool | None = None,
    run_mode: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """策略列表，附带 summary 数据（今日触发次数/最近评分）"""
    query = db.query(StrategyConfig)
    if user.role != 1:
        query = query.filter(StrategyConfig.user_id == user.id)
    if is_active is not None:
        query = query.filter(StrategyConfig.is_active == is_active)
    if run_mode is not None:
        query = query.filter(StrategyConfig.run_mode == run_mode)
    res = paginate(query, q.page, q.page_size, q.order_by)
    # 附加 summary
    for item in res["items"]:
        sid = item["id"]
        today_start = datetime.combine(datetime.now().date(), datetime.min.time())
        cnt = (
            db.query(ScoreRecord)
            .filter(
                ScoreRecord.strategy_id == sid,
                ScoreRecord.candle_close_time >= today_start,
                ScoreRecord.trigger_trade == 1,
            )
            .count()
        )
        last = (
            db.query(ScoreRecord)
            .filter(ScoreRecord.strategy_id == sid)
            .order_by(ScoreRecord.candle_close_time.desc())
            .first()
        )
        item["today_trigger_count"] = cnt
        item["last_score_total"] = float(last.score_total) if last else None
        item["last_score_time"] = last.candle_close_time.isoformat() if last else None
        item["symbols"] = item["symbols"] or []
    return success(res)


@router.post("")
def create_strategy(
    req: StrategyCreateReq,
    db: Session = Depends(get_db),
    user: User = Depends(require_trader),
):
    """创建策略"""
    if not 0 <= req.score_threshold <= 10:
        raise ParameterException("评分阈值应在0-10之间")
    # 新闻AI策略不需要技术指标权重校验
    if req.strategy_type != "news_ai":
        if abs(req.weight_technical + req.weight_news + req.weight_ai - 1.0) > 0.01:
            raise ParameterException("三项权重之和必须等于1")
    if not (3 <= req.leverage_fixed <= 10):
        raise ParameterException("固定杠杆必须在3-10之间")
    if req.tp_ratio <= 0 or req.sl_ratio <= 0:
        raise ParameterException("止盈止损比例必须大于0")
    # 过滤 symbol 只保留支持的
    from backend.routers.exchange import SUPPORTED_SYMBOLS
    allowed = {s["symbol"] for s in SUPPORTED_SYMBOLS}
    symbols = [s.upper() for s in req.symbols if s.upper() in allowed]
    if not symbols:
        raise ParameterException(f"交易品种必须是支持的 {sorted(allowed)}")
    req.symbols = symbols
    # 校验 exchange_id 归属（防止跨用户数据串联）
    if req.exchange_id:
        acc = db.query(ExchangeAccount).filter(ExchangeAccount.id == req.exchange_id).first()
        if not acc or (user.role != 1 and acc.user_id != user.id):
            raise ParameterException("交易所账号不存在或无权使用")
    s = StrategyConfig(user_id=user.id, **req.model_dump())
    db.add(s)
    db.commit()
    db.refresh(s)
    return success({"id": s.id}, message="策略创建成功")


@router.get("/default-template")
def default_template(
    type: str = Query(default="standard", pattern=r"^(standard|emv|bollinger|macd)$"),
    user: User = Depends(get_current_user),
):
    """默认策略模板（standard=标准5指标 / emv=黄金EMV / bollinger=布林带 / macd=MACD金叉死叉）"""
    if type == "emv":
        return success({
            "strategy_name": "黄金EMV趋势跟踪 4H",
            "strategy_type": "emv",
            "description": "EMV(14,3) 10层过滤趋势跟踪 | MA99斜率≥0.7% + Gap≥2.5% + RSI[38,68] | 2x固定杠杆 | ATR-based止损(2.2ATR) | 盈亏比2.3:1",
            "symbols": ["XAU"],
            "timeframe": "4h",
            "direction_mode": 1,   # 只做多
            "run_mode": 3,          # 模拟盘
            "score_threshold": 6.0,
            "strong_score_threshold": 8.0,
            "weight_technical": 0.5,  # EMV策略加重技术权重
            "weight_news": 0.25,
            "weight_ai": 0.25,
            "leverage_mode": 1,    # 固定杠杆
            "leverage_fixed": 3,    # 3x（系统最低杠杆）
            "leverage_low_score": 3,
            "leverage_mid_score": 5,
            "leverage_high_score": 8,
            "tp_ratio": 5.0,       # ATR-based会覆盖
            "sl_ratio": 2.2,      # ATR-based会覆盖
            "use_exchange_tpsl": True,
            "single_position_ratio": 5.0,   # 单笔5%（低风险）
            "total_position_ratio": 20.0,
            "max_position_count": 2,
            "max_single_drawdown": 2.0,
            "daily_max_loss": 3.0,  # 更严风控
            "consecutive_loss_pause": 2,  # 连亏2单暂停
            "cooldown_hours": 72,   # 3天冷却
            "priority": 10,
        })
    if type == "bollinger":
        return success({
            "strategy_name": "布林带突破策略 4H",
            "strategy_type": "bollinger",
            "description": "布林带(20,2σ)突破反转策略 | 价格跌破下轨收回+RSI超卖→做多；突破上轨回落+RSI超买→做空 | 回中轨止盈",
            "symbols": ["BTC", "ETH", "SOL", "XAU", "WTI"],
            "timeframe": "4h",
            "direction_mode": 0,
            "run_mode": 3,
            "score_threshold": 6.0,
            "strong_score_threshold": 8.5,
            "weight_technical": 0.6,
            "weight_news": 0.25,
            "weight_ai": 0.15,
            "leverage_mode": 2,
            "leverage_fixed": 3,
            "leverage_low_score": 2,
            "leverage_mid_score": 4,
            "leverage_high_score": 6,
            "tp_ratio": 3.5,
            "sl_ratio": 1.8,
            "use_exchange_tpsl": True,
            "single_position_ratio": 8.0,
            "total_position_ratio": 40.0,
            "max_position_count": 3,
            "max_single_drawdown": 2.5,
            "daily_max_loss": 5.0,
            "consecutive_loss_pause": 3,
            "cooldown_hours": 24,
            "priority": 5,
        })
    if type == "macd":
        return success({
            "strategy_name": "MACD趋势策略 4H",
            "strategy_type": "macd",
            "description": "MACD(12,26,9)金叉死叉策略 | MACD上穿信号线金叉+RSI过滤→做多；下穿死叉→做空 | 趋势跟踪型",
            "symbols": ["BTC", "ETH", "SOL", "XAU", "WTI"],
            "timeframe": "4h",
            "direction_mode": 0,
            "run_mode": 3,
            "score_threshold": 6.0,
            "strong_score_threshold": 8.5,
            "weight_technical": 0.55,
            "weight_news": 0.25,
            "weight_ai": 0.2,
            "leverage_mode": 2,
            "leverage_fixed": 3,
            "leverage_low_score": 2,
            "leverage_mid_score": 4,
            "leverage_high_score": 6,
            "tp_ratio": 4.0,
            "sl_ratio": 2.0,
            "use_exchange_tpsl": True,
            "single_position_ratio": 10.0,
            "total_position_ratio": 50.0,
            "max_position_count": 3,
            "max_single_drawdown": 3.0,
            "daily_max_loss": 6.0,
            "consecutive_loss_pause": 3,
            "cooldown_hours": 12,
            "priority": 5,
        })
    return success({
        "strategy_name": "BTC/ETH/SOL/XAU/WTI 全币种智能跟随 1H/4H",
        "strategy_type": "standard",
        "description": "技术面40% + 新闻情绪30% + AI分析30%，综合 ≥6 分触发交易；默认3x杠杆，4%TP/2%SL",
        "symbols": ["BTC", "ETH", "SOL", "XAU", "WTI"],
        "timeframe": "1h,4h",
        "direction_mode": 0,
        "run_mode": 3,   # 模拟盘
        "score_threshold": 6.0,
        "strong_score_threshold": 8.0,
        "weight_technical": 0.4,
        "weight_news": 0.3,
        "weight_ai": 0.3,
        "leverage_mode": 2,   # 动态
        "leverage_fixed": 3,
        "leverage_low_score": 3,
        "leverage_mid_score": 5,
        "leverage_high_score": 8,
        "tp_ratio": 4.0,
        "sl_ratio": 2.0,
        "use_exchange_tpsl": True,
        "single_position_ratio": 10.0,   # 单笔10%
        "total_position_ratio": 50.0,     # 总仓50%
        "max_position_count": 3,
        "max_single_drawdown": 2.0,       # 单笔最大回撤2%
        "daily_max_loss": 5.0,
        "consecutive_loss_pause": 3,
        "cooldown_hours": 24,
        "priority": 0,
    })


@router.get("/{sid}")
def get_strategy(sid: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """获取单个策略详情"""
    s = db.query(StrategyConfig).filter(StrategyConfig.id == sid).first()
    if not s or (user.role != 1 and s.user_id != user.id):
        raise NotFoundException("策略不存在")
    d = {c.name: getattr(s, c.name) for c in s.__table__.columns}
    d["symbols"] = s.symbols or []
    return success(d)


@router.put("/{sid}")
def update_strategy(
    sid: int,
    req: StrategyCreateReq,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """更新策略"""
    s = db.query(StrategyConfig).filter(StrategyConfig.id == sid).first()
    if not s or (user.role != 1 and s.user_id != user.id):
        raise NotFoundException("策略不存在")
    # 过滤 symbol
    from backend.routers.exchange import SUPPORTED_SYMBOLS
    allowed = {s2["symbol"] for s2 in SUPPORTED_SYMBOLS}
    symbols = [x.upper() for x in req.symbols if x.upper() in allowed]
    req.symbols = symbols
    # 校验 exchange_id 归属
    if req.exchange_id:
        acc = db.query(ExchangeAccount).filter(ExchangeAccount.id == req.exchange_id).first()
        if not acc or (user.role != 1 and acc.user_id != user.id):
            raise ParameterException("交易所账号不存在或无权使用")
    for k, v in req.model_dump().items():
        setattr(s, k, v)
    db.commit()
    return success(message="策略更新成功")


@router.delete("/{sid}")
def delete_strategy(sid: int, db: Session = Depends(get_db), user: User = Depends(require_editor)):
    """删除策略（若仍有该策略触发的持仓则禁止删除）"""
    s = db.query(StrategyConfig).filter(StrategyConfig.id == sid).first()
    if not s or (user.role != 1 and s.user_id != user.id):
        raise NotFoundException("策略不存在")
    from backend.models.trade import TradePosition
    holding = db.query(TradePosition).filter(
        TradePosition.strategy_id == sid, TradePosition.status == 1,
    ).first()
    if holding:
        raise BizException("该策略仍有持仓，请先平仓后再删除")
    db.delete(s)
    db.commit()
    return success(message="删除成功")


@router.post("/{sid}/toggle")
def toggle_strategy(
    sid: int,
    active: bool = Query(..., description="true=启用 false=停用"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """启停策略"""
    s = db.query(StrategyConfig).filter(StrategyConfig.id == sid).first()
    if not s or (user.role != 1 and s.user_id != user.id):
        raise NotFoundException("策略不存在")
    s.is_active = active
    db.commit()
    return success(message=f"策略已{'启用' if active else '停用'}", data={"is_active": active})


# =========================================================
#  手动评分 & 执行
# =========================================================
@router.post("/{sid}/score-symbol")
def score_symbol(
    sid: int,
    req: ScoreSymbolReq,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """手动对某品种+周期评分：返回完整详情（理由、指标、方向、建议杠杆），是否执行下单取决于 execute_trade"""
    s = db.query(StrategyConfig).filter(StrategyConfig.id == sid).first()
    if not s or (user.role != 1 and s.user_id != user.id):
        raise NotFoundException("策略不存在")
    engine = StrategyEngine()
    try:
        if req.execute_trade:
            # 只跑单个 symbol+tf → 模拟完整 run_strategy
            run_result = engine.run_strategy(db, sid, execute_trade=True, run_by_user=user)
            # 找到对应的那个 score
            return success({
                "message": f"已评分并{'触发下单信号' if run_result['triggered'] else '未触发'}",
                "run": run_result,
            })
        result, record = engine.score_symbol(db, s, req.symbol, req.timeframe, account_id=s.exchange_id)
    except ValueError as e:
        raise BizException(str(e), code=6001)
    # 组装可读响应
    detail = {
        "symbol": result.symbol,
        "timeframe": result.timeframe,
        "candle_close_price": result.candle_close_price,
        "candle_close_time": result.candle_close_time.isoformat() if result.candle_close_time else None,
        # 分项
        "technical_score": round(result.technical_score, 2),
        "news_score": round(result.news_score, 2),
        "ai_score": round(result.ai_score, 2),
        "total_score": round(result.score_total, 2),
        "directional_score": round(result.directional_score, 2),
        # 结论
        "direction": result.direction,
        "direction_name": {0: "观望", 1: "做多", 2: "做空"}[result.direction],
        "trigger_trade": result.trigger_trade,
        "trigger_threshold": result.trigger_threshold,
        "suggested_leverage": result.suggested_leverage,
        "suggested_tp_pct": result.suggested_tp_pct,
        "suggested_sl_pct": result.suggested_sl_pct,
        "confidence": result.confidence,
        # 指标快照
        "indicators": {
            "ma7": result.technical_detail.indicators.ma7,
            "ma25": result.technical_detail.indicators.ma25,
            "ma99": result.technical_detail.indicators.ma99,
            "rsi14": result.technical_detail.indicators.rsi14,
            "macd": result.technical_detail.indicators.macd,
            "macd_dif": result.technical_detail.indicators.macd_dif,
            "macd_dea": result.technical_detail.indicators.macd_dea,
            "bb_upper": result.technical_detail.indicators.bb_upper,
            "bb_mid": result.technical_detail.indicators.bb_mid,
            "bb_lower": result.technical_detail.indicators.bb_lower,
            "bb_position": result.technical_detail.indicators.bb_position,
            "atr14": result.technical_detail.indicators.atr14,
            "atr_pct": result.technical_detail.indicators.atr_pct,
            "emv": result.technical_detail.indicators.emv,
            "emv_signal": result.technical_detail.indicators.emv_signal,
            "emv_cross_up": result.technical_detail.indicators.emv_cross_up,
        },
        "sub_scores": result.technical_detail.sub_scores,
        "reasons": result.reasons,
        "score_record_id": record.id if record else None,
        # EMV策略专属
        "is_emv": result.is_emv,
        "emv_signal": result.emv_signal,
        "emv_filter_details": result.emv_filter_details,
        "emv_reasons": result.emv_reasons,
        # === 7因子快照 ===
        "market_regime": result.market_regime,
        "factor_scores": result.factor_scores,
        "factor_confidence": result.factor_confidence,
        "factor_details": result.factor_details,
    }
    return success(detail)


@router.post("/{sid}/run")
def run_strategy_now(
    sid: int,
    execute_trade: bool = True,
    db: Session = Depends(get_db),
    user: User = Depends(require_editor),
):
    """手动一键执行策略评分 + 按运行模式执行下单；默认 simulate 模式不会下单"""
    engine = StrategyEngine()
    s = db.query(StrategyConfig).filter(StrategyConfig.id == sid).first()
    if not s or (user.role != 1 and s.user_id != user.id):
        raise NotFoundException("策略不存在")
    result = engine.run_strategy(db, sid, execute_trade=execute_trade, run_by_user=user)
    if "error" in result:
        raise BizException(result["error"], code=6002)
    return success(result)


# =========================================================
#  评分记录
# =========================================================
@router.get("/{sid}/scores")
def strategy_scores(
    sid: int,
    symbol: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    page: int = 1,
    page_size: int = 50,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """策略评分历史"""
    s = db.query(StrategyConfig).filter(StrategyConfig.id == sid).first()
    if not s or (user.role != 1 and s.user_id != user.id):
        raise NotFoundException("策略不存在")
    query = db.query(ScoreRecord).filter(ScoreRecord.strategy_id == sid)
    if symbol:
        query = query.filter(ScoreRecord.symbol == symbol.upper())
    if start:
        query = query.filter(ScoreRecord.candle_close_time >= start)
    if end:
        query = query.filter(ScoreRecord.candle_close_time <= end)
    return success(paginate(query, page, page_size, "-candle_close_time"))


@router.get("/scores/latest")
def latest_scores(
    strategy_id: int | None = None,
    limit_per_symbol: int = 5,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """最新评分快照（用于仪表盘展示：按 (symbol,timeframe) 分组取最新）"""
    query = db.query(ScoreRecord).order_by(ScoreRecord.candle_close_time.desc())
    if strategy_id:
        s = db.query(StrategyConfig).filter(StrategyConfig.id == strategy_id).first()
        if not s or (user.role != 1 and s.user_id != user.id):
            raise NotFoundException("策略不存在")
        query = query.filter(ScoreRecord.strategy_id == strategy_id)
    else:
        if user.role != 1:
            # 只看自己的策略
            my_ids = [x.id for x in
                      db.query(StrategyConfig.id).filter(StrategyConfig.user_id == user.id).all()]
            if my_ids:
                query = query.filter(ScoreRecord.strategy_id.in_(my_ids))
            else:
                return success([])
    items = query.limit(200).all()
    # 按 (strategy_id, symbol, timeframe) 去重取最新
    dedup = {}
    for r in items:
        key = (r.strategy_id, r.symbol, r.timeframe)
        if key not in dedup:
            dedup[key] = r
    latest = list(dedup.values())
    latest.sort(key=lambda r: r.candle_close_time or datetime.min, reverse=True)
    latest = latest[: max(1, limit_per_symbol) * 10]
    return success([
        {
            "id": r.id,
            "strategy_id": r.strategy_id,
            "symbol": r.symbol,
            "timeframe": r.timeframe,
            "close_price": float(r.candle_close_price or 0),
            "close_time": r.candle_close_time.isoformat() if r.candle_close_time else None,
            "score_technical": round(float(r.score_technical or 0), 3),
            "score_news": round(float(r.score_news or 0), 3),
            "score_ai": round(float(r.score_ai or 0), 3),
            "score_total": round(float(r.score_total or 0), 2),
            "direction": r.suggested_direction,
            "leverage": r.suggested_leverage,
            "trigger_trade": bool(r.trigger_trade),
            "rsi": round(float(r.rsi or 0), 2) if r.rsi is not None else None,
        }
        for r in latest
    ])


# ==================== 新闻AI策略专属接口 ====================

@router.get("/news-sentiment/{symbol}")
def news_sentiment(
    symbol: str,
    hours: int = 24,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """查询指定品种的新闻情绪评分"""
    from backend.services.news_strategy import calc_news_sentiment_score
    result = calc_news_sentiment_score(db, symbol.upper(), hours=hours)
    return success(result)


@router.post("/{sid}/run-news-ai")
def run_news_ai(
    sid: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_trader),
):
    """手动执行新闻AI策略，返回触发的信号"""
    s = db.query(StrategyConfig).filter(StrategyConfig.id == sid).first()
    if not s or (user.role != 1 and s.user_id != user.id):
        raise NotFoundException("策略不存在")
    if s.strategy_type != "news_ai":
        raise ParameterException("该策略不是新闻AI类型")

    from backend.services.news_strategy import run_news_ai_strategy
    signals = run_news_ai_strategy(db, s)
    return success({
        "strategy_id": s.id,
        "signals_count": len(signals),
        "signals": signals,
    })


@router.post("/news-ai/run-all")
def run_all_news_ai(
    db: Session = Depends(get_db),
    user: User = Depends(require_trader),
):
    """执行所有新闻AI策略（管理员可执行全部，普通用户只执行自己的）"""
    from backend.services.news_strategy import run_all_news_ai_strategies

    # 普通用户只能看到自己策略的结果
    result = run_all_news_ai_strategies(db)
    if user.role != 1:
        result["results"] = [r for r in result["results"] if r.get("user_id") == user.id]
        result["strategies_count"] = len(result["results"])
        result["total_signals"] = sum(r.get("signals_count", 0) for r in result["results"])

    return success(result)
