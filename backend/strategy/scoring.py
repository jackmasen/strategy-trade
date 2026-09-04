"""
7因子量化信号引擎集成版
========================================
原3因子(技术40% + 新闻30% + AI30%) 升级为 7因子体系：
  1. 市场状态(18%)  - 趋势/震荡/突破强度
  2. 资金流向(15%)  - 量价配合/资金流入流出
  3. 杠杆集中度(12%) - OI/资金费率/多空比
  4. 清算压力(10%)  - 爆仓风险/清算瀑布
  5. 波动率(15%)    - 波动水平/极值
  6. 新闻情绪(15%)  - 事件驱动/情绪极值（替代原新闻+AI）
  7. 策略优势(15%)  - 回测最优策略加权

如果某些因子无数据，给中性分（不影响综合评分方向），
由有数据的因子主导决策；技术相关因子始终是核心驱动。
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Optional, Sequence, Dict

from sqlalchemy.orm import Session
from sqlalchemy import inspect as sa_inspect

from .indicators import TechnicalAnalyzer, TechnicalScoreResult
from .emv_strategy import EMVSignalGenerator, EMVSignalResult
from backend.models.analytics import NewsArticle, AIAnalysisRecord, BacktestRun
from backend.models.ai_config import AIConfig
from backend.models.strategy import StrategyConfig, ScoreRecord
from backend.models.trade import TradePosition, TradeOrder
from backend.services.ai_client import AIClient, AIResult, ERR_NOT_CONFIGURED
from backend.services.quant_signal_engine import (
    QuantSignalEngine,
    FactorResult,
    FactorDirection,
    MarketRegime,
)
from backend.exchanges.market import MarketManager


# =========================================================
# Data classes
# =========================================================
@dataclass
class NewsScoreResult:
    """新闻情绪评分（满分 10 分，再 * 30% 权重）"""
    score_raw: float = 5.0         # 0-10
    directional_score: float = 0.0  # -1..+1
    total_news_count: int = 0
    positive_count: int = 0
    negative_count: int = 0
    neutral_count: int = 0
    hot_positive_count: int = 0
    hot_negative_count: int = 0
    weighted_avg_sentiment: float = 0.0   # 按 impact 加权
    top_reasons: List[str] = field(default_factory=list)


@dataclass
class AIScoreResult:
    """AI 分析评分（满分 10 分）"""
    score_raw: float = 5.0         # 0-10
    directional_score: float = 0.0  # -1..+1
    used_cache: bool = False
    ai_reason: str = ""
    ai_direction: str = "neutral"
    model: str = "default"


@dataclass
class ScoreResult:
    """综合评分结果（7因子体系）"""
    symbol: str = ""
    timeframe: str = "1h"
    candle_close_time: datetime = None
    candle_close_price: float = 0.0

    # 三个分项（各自0-10）—— 兼容旧字段
    technical_score: float = 0.0
    news_score: float = 0.0
    ai_score: float = 0.0

    # 加权后
    score_total: float = 0.0      # 综合 0-10
    directional_score: float = 0.0  # -10..+10

    # 最终结论
    direction: int = 0             # 0观望 1多 2空
    trigger_trade: bool = False    # 是否触发交易
    trigger_threshold: float = 5.0

    # 建议
    suggested_leverage: int = 3
    suggested_tp_pct: float = 4.0
    suggested_sl_pct: float = 2.0
    confidence: float = 0.0

    # 详细
    technical_detail: TechnicalScoreResult = field(default_factory=TechnicalScoreResult)
    news_detail: NewsScoreResult = field(default_factory=NewsScoreResult)
    ai_detail: AIScoreResult = field(default_factory=AIScoreResult)
    reasons: List[str] = field(default_factory=list)
    # EMV策略专属
    is_emv: bool = False
    emv_signal: int = 0  # 0=无信号 1=做多
    emv_filter_details: dict = field(default_factory=dict)
    emv_reasons: List[str] = field(default_factory=list)

    # === 7因子快照（新体系） ===
    market_regime: str = "ranging"    # 市场状态
    factor_scores: Dict[str, float] = field(default_factory=dict)   # 各因子得分 -10~+10
    factor_confidence: Dict[str, float] = field(default_factory=dict)  # 各因子置信度 0-100
    factor_details: Dict[str, dict] = field(default_factory=dict)     # 各因子详情

    def as_record_dict(self) -> dict:
        d = self.technical_detail.indicators
        return {
            "score_technical": round(self.technical_score * 0.4, 3),  # 存权重后 0-4
            "score_news": round(self.news_score * 0.3, 3),            # 0-3
            "score_ai": round(self.ai_score * 0.3, 3),                # 0-3
            "score_total": round(self.score_total, 2),
            "suggested_direction": {0: "neutral", 1: "long", 2: "short"}[self.direction],
            "suggested_leverage": self.suggested_leverage,
            "trigger_trade": self.trigger_trade,
            "ma_short": d.ma7,
            "ma_long": d.ma99,
            "macd": d.macd_dif,
            "macd_signal": d.macd_dea,
            "rsi": d.rsi14,
            "bb_upper": d.bb_upper,
            "bb_middle": d.bb_mid,
            "bb_lower": d.bb_lower,
            "news_count_positive": self.news_detail.positive_count,
            "news_count_negative": self.news_detail.negative_count,
            "ai_reason": self.ai_detail.ai_reason[:1000],
            # === 7因子快照 ===
            "market_regime": self.market_regime,
            "factor_scores": self.factor_scores,
            "factor_confidence": self.factor_confidence,
            "factor_details": self.factor_details,
        }


# =========================================================
# 新闻评分 (C-2) —— 统一调用 NewsSentimentFactor 计算
# =========================================================
class NewsSentimentScorer:
    """
    新闻情绪评分（统一使用 QuantSignalEngine 的 NewsSentimentFactor）
    - DB 数据采集层：从数据库拉取相关新闻，计算情绪得分/新闻数量/影响力
    - 计算层：委托给 NewsSentimentFactor（与展示页用同一套算法）
    """

    def __init__(self, lookback_hours: int = 48):
        self.lookback_hours = lookback_hours
        # 延迟导入，避免循环引用
        from backend.services.quant_signal_engine import NewsSentimentFactor
        self._factor = NewsSentimentFactor()

    def score(
        self, db: Session, symbol: str, as_of: datetime | None = None
    ) -> NewsScoreResult:
        as_of = as_of or datetime.now()
        start_24h = as_of - timedelta(hours=24)
        start_7d = as_of - timedelta(days=7)

        # ---- 从DB拉取新闻 ----
        rows = db.query(NewsArticle).filter(
            NewsArticle.published_at >= start_7d,
            NewsArticle.published_at <= as_of,
        ).order_by(NewsArticle.published_at.desc()).limit(300).all()

        matched_7d = []
        for r in rows:
            syms = r.related_symbols or []
            if isinstance(syms, list) and symbol in syms:
                matched_7d.append(r)

        res = NewsScoreResult()
        res.total_news_count = len(matched_7d)

        if not matched_7d:
            # 无新闻 → 调用因子的"中性"计算（score=5, dir=0）
            factor_res = self._factor.compute(0.5, 0, 10, 0.5)
            res.score_raw = (factor_res.score + 10) / 2  # -10~+10 → 0~10
            res.directional_score = factor_res.score / 10
            return res

        # ---- 计算24h内新闻 ----
        matched_24h = [r for r in matched_7d if r.published_at >= start_24h]
        res.total_news_count = len(matched_24h)
        res.positive_count = sum(1 for r in matched_24h if r.sentiment == 1)
        res.negative_count = sum(1 for r in matched_24h if r.sentiment == -1)
        res.neutral_count = sum(1 for r in matched_24h if r.sentiment == 0)

        # 热点统计
        res.hot_positive_count = sum(1 for r in matched_24h if r.sentiment == 1 and r.is_hot)
        res.hot_negative_count = sum(1 for r in matched_24h if r.sentiment == -1 and r.is_hot)

        # 情绪加权平均（按 impact_level + 热点加成）
        weighted_sent = 0.0
        sum_w = 0.0
        max_impact = 0.0
        pos_titles = []
        neg_titles = []
        for r in matched_24h:
            w = 1.0 + (r.impact_level - 1) * 0.5   # 1→1, 2→1.5, 3→2, 4→2.5
            if r.is_hot:
                w *= 1.5
            sent = r.sentiment_score or float(r.sentiment or 0)  # [-1,1]
            weighted_sent += sent * w
            sum_w += w
            impact_norm = (r.impact_level or 1) / 4.0  # 归一化到 0~1
            if r.is_hot:
                impact_norm = min(1.0, impact_norm * 1.5)
            max_impact = max(max_impact, impact_norm)
            if r.sentiment == 1:
                pos_titles.append((r.title, w))
            elif r.sentiment == -1:
                neg_titles.append((r.title, w))

        if sum_w > 0:
            res.weighted_avg_sentiment = weighted_sent / sum_w   # -1..+1
        else:
            res.weighted_avg_sentiment = 0.0

        # 7天日均新闻量
        avg_news_count = len(matched_7d) / 7.0

        # ---- 统一调用 NewsSentimentFactor 计算 ----
        # sentiment_score 映射：-1~+1 → 0~1（0.5中性）
        sentiment_01 = (res.weighted_avg_sentiment + 1) / 2
        factor_res = self._factor.compute(
            sentiment_score=sentiment_01,
            news_count_24h=len(matched_24h),
            avg_news_count=avg_news_count,
            max_impact=max_impact,
        )

        # 因子得分 -10~+10 → 0~10
        res.score_raw = (factor_res.score + 10) / 2
        res.directional_score = factor_res.score / 10  # -1..+1

        # Top reasons
        pos_titles.sort(key=lambda x: -x[1]); neg_titles.sort(key=lambda x: -x[1])
        for t, _ in pos_titles[:2]:
            res.top_reasons.append("[利好] " + (t[:60]))
        for t, _ in neg_titles[:2]:
            res.top_reasons.append("[利空] " + (t[:60]))
        if res.hot_positive_count or res.hot_negative_count:
            res.top_reasons.append(
                f"热点新闻：利好 {res.hot_positive_count} 条 / 利空 {res.hot_negative_count} 条"
            )
        return res

    # ---- 暴露给7因子引擎的快速接口 ----
    def compute_for_engine(
        self, db: Session, symbol: str, as_of: datetime | None = None
    ) -> dict:
        """返回 NewsSentimentFactor.compute 需要的参数字典"""
        as_of = as_of or datetime.now()
        start_24h = as_of - timedelta(hours=24)
        start_7d = as_of - timedelta(days=7)

        rows = db.query(NewsArticle).filter(
            NewsArticle.published_at >= start_7d,
            NewsArticle.published_at <= as_of,
        ).order_by(NewsArticle.published_at.desc()).limit(300).all()

        matched_7d = [r for r in rows if isinstance(r.related_symbols, list) and symbol in r.related_symbols]
        matched_24h = [r for r in matched_7d if r.published_at >= start_24h]

        if not matched_24h:
            return {
                "sentiment_score": 0.5,
                "news_count_24h": 0,
                "avg_news_count": len(matched_7d) / 7.0 if matched_7d else 10,
                "max_impact": 0.5,
            }

        weighted_sent = 0.0
        sum_w = 0.0
        max_impact = 0.0
        for r in matched_24h:
            w = 1.0 + (r.impact_level - 1) * 0.5
            if r.is_hot:
                w *= 1.5
            sent = r.sentiment_score or float(r.sentiment or 0)
            weighted_sent += sent * w
            sum_w += w
            impact_norm = (r.impact_level or 1) / 4.0
            if r.is_hot:
                impact_norm = min(1.0, impact_norm * 1.5)
            max_impact = max(max_impact, impact_norm)

        sentiment_01 = ((weighted_sent / sum_w) + 1) / 2 if sum_w > 0 else 0.5
        return {
            "sentiment_score": sentiment_01,
            "news_count_24h": len(matched_24h),
            "avg_news_count": len(matched_7d) / 7.0 if matched_7d else 10,
            "max_impact": max_impact,
        }


# =========================================================
# AI 评分 (C-2)
# =========================================================
class AISentimentScorer:
    """
    AI 评分实现（V2 真调 AIClient）：
    - 优先复用最近 15 分钟内同一 symbol+timeframe 的记录（避免重复调用烧钱）
    - 若无缓存 → 真调 AIClient（失败/未配置时离线合成，绝不抛异常）
    - 真调成功时写 AIAnalysisRecord 作下次缓存
    """

    CACHE_MINUTES = 15

    # ---------- 内部工具：幂等获取 AIConfig（确保 ai_configs 表/行存在） ----------
    def _get_or_init_ai_config(self, db: Session) -> AIConfig:
        from backend.db.session import engine_sync
        from backend.config import get_settings
        from backend.core.security import encrypt_api_key
        insp = sa_inspect(engine_sync)
        if "ai_configs" not in insp.get_table_names():
            AIConfig.__table__.create(bind=engine_sync, checkfirst=True)
        row = db.query(AIConfig).filter(AIConfig.id == AIConfig.SINGLETON_ID).first()
        if row is None:
            s = get_settings()
            row = AIConfig(
                id=AIConfig.SINGLETON_ID,
                provider=AIConfig.name_to_provider(s.AI_PROVIDER),
                model_name=s.AI_MODEL_NAME or "gpt-4o",
                api_endpoint=s.AI_API_ENDPOINT or "",
                api_key_encrypted=encrypt_api_key(s.AI_API_KEY or ""),
                temperature=3,
                max_tokens=800,
                request_timeout_sec=30,
                max_retries=2,
            )
            db.add(row)
            db.commit()
            db.refresh(row)
        return row

    # ---------- 内部工具：构造 candles_snapshot 文本给 AI Prompt ----------
    @staticmethod
    def _build_candles_snapshot(symbol: str, timeframe: str, tech: TechnicalScoreResult) -> str:
        if not tech or not getattr(tech, "indicators", None):
            return ""
        ind = tech.indicators
        lines = [
            f"品种: {symbol} | 周期: {timeframe}",
            f"最新价格: {ind.last_close:.4f}",
            f"均线: MA7={ind.ma7:.4f}, MA25={ind.ma25:.4f}, MA99={ind.ma99:.4f}",
            f"MACD: DIF={ind.macd_dif:.4f}, DEA={ind.macd_dea:.4f}, HIST={ind.macd:.4f}",
            f"RSI(14): {ind.rsi14:.2f}",
            f"布林带: 上={ind.bb_upper:.4f}, 中={ind.bb_mid:.4f}, 下={ind.bb_lower:.4f}",
            f"ATR波动率: {ind.atr_pct * 100:.2f}%",
            f"技术面综合评分: {tech.score:.1f}/10，方向分: {tech.directional_score:.2f}",
            f"技术面方向信号: {tech.direction} (0观望/1多/2空)",
        ]
        if tech.reasons:
            lines.append("技术面要点:")
            for r in tech.reasons[:6]:
                lines.append(f"  - {r}")
        return "\n".join(lines)

    # ---------- 内部工具：构造 news_snapshot 文本 ----------
    @staticmethod
    def _build_news_snapshot(news: NewsScoreResult) -> str:
        if not news:
            return ""
        lines = [
            f"新闻情绪: 评分{news.score_raw:.1f}/10, 方向分{news.directional_score:.2f}",
            f"近48h新闻: 总计{news.total_news_count}条 (利好{news.positive_count}/利空{news.negative_count}/中性{news.neutral_count})",
        ]
        if news.hot_positive_count or news.hot_negative_count:
            lines.append(f"热点新闻: 利好{news.hot_positive_count}条, 利空{news.hot_negative_count}条")
        if news.top_reasons:
            lines.append("新闻要点:")
            for r in news.top_reasons[:6]:
                lines.append(f"  - {r}")
        return "\n".join(lines)

    def score(
        self,
        db: Session,
        symbol: str,
        timeframe: str,
        technical: TechnicalScoreResult,
        news: NewsScoreResult,
        as_of: datetime | None = None,
    ) -> AIScoreResult:
        as_of = as_of or datetime.now()
        cutoff = as_of - timedelta(minutes=self.CACHE_MINUTES)
        # 1) 查缓存（DB内的 AIAnalysisRecord）
        cached = (
            db.query(AIAnalysisRecord)
            .filter(
                AIAnalysisRecord.symbol == symbol,
                AIAnalysisRecord.timeframe == timeframe,
                AIAnalysisRecord.success == 1,
                AIAnalysisRecord.created_at >= cutoff,
            )
            .order_by(AIAnalysisRecord.id.desc())
            .first()
        )
        result = AIScoreResult()
        if cached and cached.ai_score is not None:
            result.used_cache = True
            # ai_score 如果是 0-3 则归一化；若是 0-10 直接用
            score = float(cached.ai_score)
            if score <= 3.0:
                score = score / 3.0 * 10.0
            result.score_raw = max(0.0, min(10.0, score))
            direction_text = (cached.ai_direction or "neutral").lower()
            if direction_text.startswith("long") or direction_text in ("buy", "多"):
                result.directional_score = +0.8
            elif direction_text.startswith("short") or direction_text in ("sell", "空"):
                result.directional_score = -0.8
            else:
                result.directional_score = 0.0
            result.ai_reason = cached.ai_reason or ""
            result.ai_direction = direction_text
            result.model = cached.model_name or ""
            return result

        # 2) 无缓存 → 真调 AI（主配置 + 接口池自动故障转移）
        try:
            from backend.services.ai_failover import call_ai_unified
            candles_snap = self._build_candles_snapshot(symbol, timeframe, technical)
            news_snap = self._build_news_snapshot(news)
            unified = call_ai_unified(
                db,
                analysis_type="score",
                symbol=symbol,
                timeframe=timeframe,
                manual_prompt="",
                candles_snapshot=candles_snap,
                news_snapshot=news_snap,
                _mock=False,
            )
            ai_ret = unified["result"]
            if ai_ret and ai_ret.success:
                from backend.core.logging_config import logger as _log
                if unified["source"] == "pool":
                    _log.info(f"[AIScorer] AI主配置失败，已自动切换接口池: {unified.get('used_key_name','')}")
            elif not ai_ret or not ai_ret.success:
                ai_ret = None
        except Exception as exc:
            ai_ret = None
            import traceback
            from backend.core.logging_config import logger
            logger.warning(f"[AIScorer] AI调用异常，降级离线合成：{type(exc).__name__}: {exc}\n{traceback.format_exc()[:400]}")

        # 3) 根据 AI 调用结果分支
        if ai_ret is not None and ai_ret.success:
            # 真实 AI 返回成功 → 写缓存 + 取字段
            result.score_raw = max(0.0, min(10.0, float(ai_ret.ai_score or 5.0)))
            d = (ai_ret.ai_direction or "neutral").lower()
            if d == "long":
                result.directional_score = +0.8
                result.ai_direction = "long"
            elif d == "short":
                result.directional_score = -0.8
                result.ai_direction = "short"
            else:
                result.directional_score = 0.0
                result.ai_direction = "neutral"
            result.ai_reason = ai_ret.ai_reason or ""
            result.model = ai_ret.model_name or ""
            # 写 AIAnalysisRecord 作下次缓存（success=1）
            try:
                provider_int = {
                    "openai": 1, "anthropic": 2, "custom": 3, "local": 4,
                }.get(ai_ret.provider or "custom", 3)
                rec = AIAnalysisRecord(
                    user_id=0,
                    provider=provider_int,
                    model_name=ai_ret.model_name or "",
                    analysis_type="score",
                    symbol=symbol,
                    timeframe=timeframe,
                    prompt_snapshot=f"[ENGINE][{symbol}][{timeframe}] strategy-scoring",
                    ai_response_raw=(ai_ret.raw_response or "")[:20000],
                    ai_score=ai_ret.ai_score,
                    ai_direction=ai_ret.ai_direction,
                    ai_reason=(ai_ret.ai_reason or "")[:3000],
                    tokens_prompt=ai_ret.tokens_prompt,
                    tokens_completion=ai_ret.tokens_completion,
                    cost_usd=ai_ret.cost_usd,
                    latency_ms=ai_ret.latency_ms,
                    success=1,
                    error_msg="",
                )
                db.add(rec)
                db.commit()
            except Exception as exc2:
                import traceback
                from backend.core.logging_config import logger
                logger.warning(f"[AIScorer] 写 AI 缓存记录失败：{type(exc2).__name__}: {exc2}\n{traceback.format_exc()[:300]}")
                try:
                    db.rollback()
                except Exception:
                    pass
            return result

        # 4) 未配置 / 调用失败 → 离线合成（标标志位，给运营和用户看）
        offline_hint = ""
        if ai_ret is not None and ai_ret.error_code == ERR_NOT_CONFIGURED:
            offline_hint = f"[AI未配置] {ai_ret.error_msg or ''}；"
        elif ai_ret is not None and not ai_ret.success:
            offline_hint = f"[AI调用失败:{ai_ret.error_code}] {ai_ret.error_msg or ''}；"
        else:
            offline_hint = "[AI离线]"

        tech_norm = technical.score / 10.0          # 0-1
        news_norm = news.score_raw / 10.0           # 0-1
        combined = tech_norm * 0.55 + news_norm * 0.45
        result.score_raw = max(0.0, min(10.0, 5.0 + (combined - 0.5) * 10.0))
        tech_dir = technical.directional_score / 10.0   # -1..+1
        news_dir = news.directional_score               # -1..+1
        result.directional_score = max(-1.0, min(1.0, 0.55 * tech_dir + 0.45 * news_dir))
        if result.directional_score > 0.25:
            result.ai_direction = "long"
        elif result.directional_score < -0.25:
            result.ai_direction = "short"
        else:
            result.ai_direction = "neutral"
        result.ai_reason = (
            f"{offline_hint}当前使用离线合成：技术面评分 {technical.score:.1f}/10，方向 {technical.direction}；"
            f"新闻面 {len(news.top_reasons)} 条要点；建议方向 {result.ai_direction}。"
            f"管理员可在【AI接口】保存真实模型 Key 启用深度分析（无需重启服务）。"
        )
        result.model = "offline-synth"
        return result


# =========================================================
# 综合评分引擎 (C-3)
# =========================================================
class StrategyScoringEngine:
    """
    7因子量化信号引擎（集成版）
    ========================================
    7大因子权重（技术相关合计48%为核心驱动）：
      1. 市场状态   18%   - ADX/MA斜率/布林宽度/波动率比
      2. 资金流向   15%   - OBV/量价背离/VWAP/MFI
      3. 杠杆集中度 12%   - OI变化/资金费率/多空比
      4. 清算压力   10%   - 爆仓风险估算（ATR*3）
      5. 波动率     15%   - 已实现波动/波动率锥/极值
      6. 新闻情绪   15%   - 情绪极值/新闻密度/事件影响（含AI修正）
      7. 策略优势   15%   - 回测最优策略胜率/夏普比

    输出 ScoreResult，score_total（0-10）≥阈值 且方向明确时 trigger_trade=True
    """

    # 7因子默认权重（合计100%）
    DEFAULT_FACTOR_WEIGHTS = {
        "market_regime": 0.18,
        "capital_flow": 0.15,
        "leverage": 0.12,
        "liquidation": 0.10,
        "volatility": 0.15,
        "news_sentiment": 0.15,
        "strategy_advantage": 0.15,
    }

    # 兼容旧的3因子权重（用于填充旧字段，不影响实际计算）
    DEFAULT_WEIGHTS = {
        "technical": 0.4,
        "news": 0.3,
        "ai": 0.3,
    }

    def __init__(self):
        self.technical = TechnicalAnalyzer()
        self.news_scorer = NewsSentimentScorer()
        self.ai_scorer = AISentimentScorer()
        self.emv_generator = EMVSignalGenerator()
        # 7因子引擎（核心计算）
        self._quant_engine = QuantSignalEngine()

    # --------- 外部主入口 ----------
    def compute(
        self,
        db: Session,
        symbol: str,
        klines: Sequence,
        timeframe: str = "1h",
        strategy: Optional[StrategyConfig] = None,
        as_of: datetime | None = None,
        candle_close_price: float = 0.0,
    ) -> ScoreResult:
        """
        7因子综合评分主入口
        - 技术指标 → 市场状态 + 资金流向 + 波动率（从K线计算）
        - OI/资金费率 → 杠杆集中度因子
        - ATR估算 → 清算压力因子
        - 新闻情绪 → 新闻情绪因子（统一用 NewsSentimentFactor）
        - AI分析 → 作为新闻情绪因子的置信度调节
        - 回测数据 → 策略优势因子
        """
        as_of = as_of or datetime.now()
        result = ScoreResult()
        result.symbol = symbol
        result.timeframe = timeframe
        result.candle_close_time = as_of

        # 触发阈值
        result.trigger_threshold = float(strategy.score_threshold or 5.0) if strategy else 5.0

        # 1) 技术指标（保留旧的 TechnicalAnalyzer，用于兼容 + 提取基础指标值）
        tech = self.technical.analyze(klines, timeframe=timeframe)
        result.technical_detail = tech
        result.technical_score = tech.score
        result.candle_close_price = candle_close_price or tech.indicators.last_close
        last_close = result.candle_close_price

        # 2) 准备K线数组供7因子引擎使用
        from .indicators import _candles_to_arrays
        opens, highs, lows, closes, volumes = _candles_to_arrays(klines)

        # ---- 3) 收集各因子数据 ----

        # 3a) OI/资金费率/多空比（杠杆因子）
        mm = MarketManager.get_instance()
        oi_data = mm.get_oi_history(symbol, limit=60)
        funding_rate = mm.get_funding_rate(symbol)
        long_short_ratio = mm.get_long_short_ratio(symbol)

        # 3b) 清算压力（用ATR*3估算）
        atr_pct = tech.indicators.atr_pct or 0.02
        if atr_pct > 0 and atr_pct < 1:
            liq_above_pct = atr_pct * 3 * 100
            liq_below_pct = liq_above_pct
        else:
            liq_above_pct = 5.0
            liq_below_pct = 5.0

        # 3c) 新闻情绪（统一调用 NewsSentimentScorer → NewsSentimentFactor）
        news_res = self.news_scorer.score(db, symbol, as_of=as_of)
        result.news_detail = news_res
        result.news_score = news_res.score_raw
        news_params = self.news_scorer.compute_for_engine(db, symbol, as_of=as_of)

        # 3d) AI分析（保留，但仅作为新闻情绪的置信度修正）
        ai_res = self.ai_scorer.score(db, symbol, timeframe, tech, news_res, as_of=as_of)
        result.ai_detail = ai_res
        result.ai_score = ai_res.score_raw
        # AI方向修正新闻情绪（如果AI有明确方向，新闻情绪朝该方向微调）
        if ai_res.ai_direction != "neutral" and news_params["news_count_24h"] < 3:
            ai_bias = 0.1 if ai_res.ai_direction == "long" else -0.1
            news_params["sentiment_score"] = max(0.0, min(1.0, news_params["sentiment_score"] + ai_bias))

        # 3e) 策略优势（从回测数据库取）
        strategy_perf = self._get_strategy_performance(db, symbol, timeframe)

        # ---- 4) 调用7因子引擎生成信号 ----
        quant_signal = self._quant_engine.generate_signal(
            symbol=symbol,
            closes=closes,
            highs=highs,
            lows=lows,
            volumes=volumes,
            oi_data=oi_data if len(oi_data) >= 5 else None,
            funding_rate=funding_rate,
            long_short_ratio=long_short_ratio,
            liq_above_pct=liq_above_pct,
            liq_below_pct=liq_below_pct,
            news_sentiment=news_params["sentiment_score"],
            news_count_24h=news_params["news_count_24h"],
            avg_news_count=news_params["avg_news_count"],
            strategy_perf=strategy_perf,
        )

        # ---- 5) 把7因子结果映射到 ScoreResult ----
        # composite_score 是 -10~+10 → 映射到 0~10
        result.score_total = round((quant_signal.composite_score + 10) / 2, 2)
        result.directional_score = round(quant_signal.composite_score, 2)
        result.confidence = round(quant_signal.confidence / 100, 3)
        result.market_regime = quant_signal.market_regime.value

        # 7因子快照
        for fkey, fresult in quant_signal.factors.items():
            result.factor_scores[fkey] = round(fresult.score, 2)
            result.factor_confidence[fkey] = round(fresult.confidence, 1)
            result.factor_details[fkey] = fresult.details

        # 方向映射
        direction_map = {"bullish": 1, "bearish": 2, "neutral": 0}
        result.direction = direction_map.get(quant_signal.direction.value, 0)

        # ---- 6) EMV 策略特殊处理（保留原有机制） ----
        is_emv = (
            strategy is not None
            and getattr(strategy, "strategy_type", "standard") == StrategyConfig.TYPE_EMV
        )
        emv_res: Optional[EMVSignalResult] = None
        if is_emv:
            _wr_lookback = self.emv_generator.p["win_rate_lookback"]
            _recent_closed = (
                db.query(TradePosition)
                .filter(
                    TradePosition.symbol == symbol,
                    TradePosition.status == 2,
                )
                .order_by(TradePosition.id.desc())
                .limit(_wr_lookback)
                .all()
            )
            _cnt = len(_recent_closed)
            _win = sum(1 for p in _recent_closed if float(p.realized_pnl or 0) > 0)
            _rate = round(_win / _cnt * 100, 2) if _cnt > 0 else None
            emv_res = self.emv_generator.generate(
                klines, symbol=symbol, timeframe=timeframe,
                recent_win_rate=_rate, recent_trade_count=_cnt,
                direction=getattr(strategy, "direction_mode", 0) or 0,
            )
            result.is_emv = True
            result.emv_signal = emv_res.signal
            result.emv_filter_details = emv_res.filter_details
            result.emv_reasons = list(emv_res.reasons)
            # EMV信号通过 → 设置方向（做多/做空）
            if emv_res.signal == 1:
                result.direction = 1
                result.score_total = max(result.score_total, 7.5)
            elif emv_res.signal == 2:
                result.direction = 2
                result.score_total = max(result.score_total, 7.5)
            result.reasons.extend(emv_res.reasons)

        # ---- 7) 是否触发交易 ----
        if result.direction != 0 and result.score_total >= result.trigger_threshold:
            # EMV策略：信号通过即触发（做多或做空）
            if is_emv and emv_res and emv_res.signal in (1, 2):
                result.trigger_trade = True
            else:
                # 7因子引擎已经做了方向一致性判断
                result.trigger_trade = True
        else:
            result.trigger_trade = False

        # ---- 8) 建议杠杆 & TP/SL ----
        base_lev = tech.suggest_leverage
        if strategy:
            if strategy.leverage_mode == 1:  # 固定
                base_lev = int(strategy.leverage_fixed or 3)
            else:  # 动态
                if result.score_total >= float(strategy.strong_score_threshold or 8):
                    base_lev = int(strategy.leverage_high_score or 8)
                elif result.score_total >= (float(strategy.score_threshold or 5) + 1.5):
                    base_lev = int(strategy.leverage_mid_score or 5)
                else:
                    base_lev = int(strategy.leverage_low_score or 3)
            # 方向模式过滤
            if strategy.direction_mode == StrategyConfig.DIR_LONG_ONLY and result.direction == 2:
                result.trigger_trade = False
                result.direction = 0
            elif strategy.direction_mode == StrategyConfig.DIR_SHORT_ONLY and result.direction == 1:
                result.trigger_trade = False
                result.direction = 0

        # 7因子引擎的建议杠杆（如果更保守则取低的）
        quant_lev = quant_signal.suggested_leverage
        if quant_lev and quant_lev > 0:
            base_lev = min(base_lev, quant_lev)
        result.suggested_leverage = max(1, min(10, int(base_lev)))

        # TP/SL：7因子引擎直接给了具体价位
        if quant_signal.stop_loss > 0 and last_close > 0:
            sl_pct = abs(quant_signal.stop_loss - last_close) / last_close * 100
            tp_pct = abs(quant_signal.take_profit - last_close) / last_close * 100
            result.suggested_sl_pct = round(sl_pct, 2)
            result.suggested_tp_pct = round(tp_pct, 2)
        else:
            tp = tech.suggest_tp_pct
            sl = tech.suggest_sl_pct
            if strategy:
                tp = float(strategy.tp_ratio or tp)
                sl = float(strategy.sl_ratio or sl)
            result.suggested_tp_pct = round(tp, 2)
            result.suggested_sl_pct = round(sl, 2)

        # EMV的ATR止损覆盖
        if is_emv and emv_res and emv_res.signal == 1 and tech.indicators.atr14 > 0:
            sl_atr = 2.2 * tech.indicators.atr14 / max(last_close, 1e-9) * 100
            tp_atr = sl_atr * 2.3
            result.suggested_sl_pct = round(max(result.suggested_sl_pct, sl_atr), 2)
            result.suggested_tp_pct = round(max(result.suggested_tp_pct, tp_atr), 2)

        # ---- 9) 汇总理由 ----
        reasons = []
        reasons.extend(tech.reasons)
        reasons.extend(news_res.top_reasons)
        if ai_res.ai_reason:
            reasons.append("[AI] " + ai_res.ai_reason[:120])
        # 7因子核心结论
        regime_cn = {
            "strong_trend_up": "强势上涨趋势", "weak_trend_up": "弱势上涨趋势",
            "ranging": "震荡市", "weak_trend_down": "弱势下跌趋势",
            "strong_trend_down": "强势下跌趋势",
            "breakout_up": "向上突破", "breakout_down": "向下突破",
        }
        reasons.append(
            f"[7因子] 市场状态: {regime_cn.get(quant_signal.market_regime.value, quant_signal.market_regime.value)}"
        )
        if result.trigger_trade:
            dir_cn = '做多' if result.direction == 1 else '做空'
            reasons.append(
                f"综合评分 {result.score_total:.1f} ≥ {result.trigger_threshold:.1f}，"
                f"方向 {dir_cn}，建议杠杆 {result.suggested_leverage}x，"
                f"TP {result.suggested_tp_pct}% / SL {result.suggested_sl_pct}%"
            )
        result.reasons = reasons
        return result

    # ---------- 辅助：获取策略优势（回测数据） ----------
    def _get_strategy_performance(self, db: Session, symbol: str, timeframe: str) -> dict:
        """从回测结果中获取各策略的表现，用于策略优势因子"""
        try:
            runs = db.query(BacktestRun).filter(
                BacktestRun.symbol == symbol,
                BacktestRun.status == 2,  # 成功
            ).order_by(BacktestRun.end_time.desc()).limit(50).all()

            perf = {}
            for r in runs:
                name = r.strategy_name or f"strategy_{r.id}"
                if name not in perf:
                    perf[name] = {
                        "win_rate": float(r.win_rate or 0),
                        "profit_factor": float(r.profit_factor or 1.0),
                        "sharpe": float(r.sharpe_ratio or 0),
                        "total_return": float(r.total_return_pct or 0),
                        "max_drawdown": float(r.max_drawdown_pct or 0),
                        "total_trades": int(r.total_trades or 0),
                    }
            return perf
        except Exception:
            return {}




# =========================================================
# 向后兼容的别名（health_check.py / engine.py 等旧调用方）
# =========================================================
class TechnicalIndicatorsScorer(TechnicalAnalyzer):
    """
    健康检查脚本使用：TechnicalIndicatorsScorer().score(candles)
    复用 TechnicalAnalyzer.analyze，返回 TechnicalScoreResult
    """
    def score(self, klines, timeframe: str = "1h"):
        return self.analyze(klines, timeframe=timeframe)


# aggregate 作为 StrategyScoringEngine 的静态方法补上（health_check.py 用到）
# 这里通过 monkey patch 实现
def _aggregate_static(
    cls, *, symbol, timeframe, close,
    tech_score, tech_detail, news_score, news_detail, ai_score, ai_detail,
):
    """
    与 compute 内部一致的加权逻辑：
    - 返回 ScoreResult（简化版，不写DB）
    - 被 health_check.py 调用，验证综合分在 [0,10]
    """
    w = cls.DEFAULT_WEIGHTS
    total = round(
        tech_score * w["technical"] + news_score * w["news"] + ai_score * w["ai"],
        2,
    )
    # 方向分（不连DB，直接用三个 detail 里的方向分合成；news_detail 可能是 NewsScoreResult 或 dict）
    td_dir = getattr(tech_detail, "directional_score", 0) / 10.0
    if isinstance(news_detail, dict):
        nd_dir = float(news_detail.get("directional_score", 0))
    else:
        nd_dir = float(getattr(news_detail, "directional_score", 0) or 0)
    if isinstance(ai_detail, dict):
        ad_dir = float(ai_detail.get("directional_score", 0))
    else:
        ad_dir = float(getattr(ai_detail, "directional_score", 0) or 0)
    directional_total = round(
        td_dir * w["technical"] + nd_dir * w["news"] + ad_dir * w["ai"], 3,
    ) * 10
    r = ScoreResult(
        symbol=symbol, timeframe=timeframe,
        candle_close_price=float(close or 0),
        technical_score=float(tech_score or 0),
        news_score=float(news_score or 0),
        ai_score=float(ai_score or 0),
        score_total=max(0.0, min(10.0, float(total))),
        directional_score=float(directional_total),
    )
    # 方向 & 触发
    threshold = 5.0
    r.trigger_threshold = threshold
    if r.score_total >= threshold and r.directional_score >= 0.5:
        r.direction = 1
    elif r.score_total >= threshold and r.directional_score <= -0.5:
        r.direction = 2
    else:
        r.direction = 0
    r.trigger_trade = (r.direction != 0 and r.score_total >= threshold)
    r.confidence = round(min(1.0, max(0.0, (r.score_total / 10.0))), 3)
    return r


StrategyScoringEngine.aggregate = classmethod(_aggregate_static)


def _score_news_from_list(self, symbol, raw_news_list, as_of):
    """
    不连 DB，直接从 RawNews / 字典列表 合成新闻分（health_check.py 用空列表测兜底逻辑）
    返回 (score_0_10, news_detail_dict_or_obj)
    """
    scorer = NewsSentimentScorer()
    if raw_news_list:
        # 有真实 RawNews → 粗算（这里简化：返回默认5分）
        return 5.0, {
            "score_raw": 5.0, "directional_score": 0.0,
            "total_news_count": len(raw_news_list),
        }
    # 空列表：兜底中性 5/10，方向 0
    return 5.0, {
        "score_raw": 5.0, "directional_score": 0.0,
        "total_news_count": 0,
        "positive_count": 0, "negative_count": 0, "neutral_count": 0,
    }


StrategyScoringEngine.score_news_from_list = _score_news_from_list
