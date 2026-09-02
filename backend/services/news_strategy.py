"""
新闻AI驱动交易策略服务
根据新闻AI情绪评分自动触发交易信号
"""
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from decimal import Decimal

from sqlalchemy.orm import Session

from backend.models.strategy import StrategyConfig, ScoreRecord
from backend.models.trade import TradePosition
from backend.models.analytics import NewsArticle
from backend.models.user import User
from backend.models.exchange import ExchangeAccount

logger = logging.getLogger(__name__)

# 策略类型常量
STRATEGY_TYPE_NEWS_AI = "news_ai"  # 新闻AI驱动策略


# ============================================================
# 新闻情绪评分计算
# 统一委托 NewsSentimentScorer（与综合评分引擎 scoring.py 一致），
# 消除原先两套独立评分路径导致的分值不一致问题。
# ============================================================

def calc_news_sentiment_score(db: Session, symbol: str, hours: int = 24) -> Dict:
    """
    计算指定品种的新闻情绪评分
    内部统一使用 NewsSentimentScorer（与综合评分引擎一致），
    再将 NewsScoreResult(0-10) 转换为兼容的 0-100 dict 格式。
    返回: {score, direction, positive_count, negative_count, neutral_count, articles}
    """
    from backend.strategy.scoring import NewsSentimentScorer

    # 1) 使用与综合评分引擎一致的 NewsSentimentScorer 评分
    scorer = NewsSentimentScorer(lookback_hours=hours)
    news_result = scorer.score(db, symbol)

    # 2) 转换为 0-100 范围（NewsScoreResult.score_raw 是 0-10）
    score_100 = news_result.score_raw * 10.0

    # 确定方向（与 run_news_ai_strategy 的阈值逻辑一致）
    if score_100 > 55:
        direction = "long"
    elif score_100 < 45:
        direction = "short"
    else:
        direction = "neutral"

    # 3) 查询相关新闻用于摘要展示（与 NewsSentimentScorer 相同的 related_symbols 匹配）
    since = datetime.now() - timedelta(hours=hours)
    rows = db.query(NewsArticle).filter(
        NewsArticle.published_at >= since,
    ).order_by(NewsArticle.published_at.desc()).limit(50).all()

    matched = []
    for r in rows:
        syms = r.related_symbols or []
        if isinstance(syms, list) and symbol in syms:
            matched.append(r)

    article_summaries = []
    for art in matched[:10]:
        raw_score = float(art.sentiment_score or 0)
        # -1.0 ~ 1.0  →  0 ~ 100
        sentiment_val = 50 + raw_score * 50
        if art.sentiment == 1:
            art_dir = "bullish"
        elif art.sentiment == -1:
            art_dir = "bearish"
        else:
            art_dir = "neutral"
        article_summaries.append({
            "id": art.id,
            "title": art.title,
            "source": art.source_name or "",
            "sentiment": round(sentiment_val, 1),
            "direction": art_dir,
            "publish_time": art.published_at.isoformat() if art.published_at else "",
        })

    return {
        "score": round(score_100, 2),
        "direction": direction,
        "positive_count": news_result.positive_count,
        "negative_count": news_result.negative_count,
        "neutral_count": news_result.neutral_count,
        "articles_count": news_result.total_news_count,
        "analyzed_count": news_result.total_news_count,
        "articles": article_summaries,
    }


# ============================================================
# 新闻AI策略执行
# ============================================================

def run_news_ai_strategy(db: Session, strategy: StrategyConfig) -> List[Dict]:
    """
    执行新闻AI策略：检查各品种新闻情绪，触发交易信号
    返回触发的交易信号列表
    """
    if strategy.strategy_type != STRATEGY_TYPE_NEWS_AI:
        return []
    if not strategy.is_active:
        return []

    signals = []
    symbols = strategy.symbols or []

    for symbol in symbols:
        # 计算新闻情绪
        sentiment = calc_news_sentiment_score(db, symbol, hours=24)

        # 检查是否已有同方向持仓
        existing = db.query(TradePosition).filter(
            TradePosition.user_id == strategy.user_id,
            TradePosition.symbol == symbol,
            TradePosition.status == 1,
        ).first()

        # 评分转 0-10 范围（与综合评分一致）
        score_10 = sentiment["score"] / 10  # 0-10
        abs_score = abs(sentiment["score"] - 50) / 5  # 偏离中性的强度 0-10

        should_open = False
        direction = sentiment["direction"]

        # 方向过滤
        if strategy.direction_mode == 1 and direction != "long":
            continue
        if strategy.direction_mode == 2 and direction != "short":
            continue

        # 触发条件：情绪分绝对值超过阈值
        threshold = strategy.score_threshold or 5.0
        if abs_score >= threshold and direction in ("long", "short") and not existing:
            should_open = True

        if should_open:
            # 计算建议杠杆
            if strategy.leverage_mode == 2:  # 动态
                if abs_score >= strategy.strong_score_threshold:
                    leverage = strategy.leverage_high_score
                elif abs_score >= threshold + 1:
                    leverage = strategy.leverage_mid_score
                else:
                    leverage = strategy.leverage_low_score
            else:
                leverage = strategy.leverage_fixed

            signal = {
                "strategy_id": strategy.id,
                "strategy_name": strategy.strategy_name,
                "symbol": symbol,
                "direction": direction,
                "sentiment_score": sentiment["score"],
                "signal_strength": round(abs_score, 2),
                "suggested_leverage": leverage,
                "articles_count": sentiment["articles_count"],
                "positive_count": sentiment["positive_count"],
                "negative_count": sentiment["negative_count"],
                "reason": f"新闻情绪{'看多' if direction=='long' else '看空'}，强度 {round(abs_score, 1)}/10，共 {sentiment['articles_count']} 条相关新闻",
                "timestamp": datetime.now().isoformat(),
            }
            signals.append(signal)

            # 记录评分
            score_rec = ScoreRecord(
                strategy_id=strategy.id,
                symbol=symbol,
                timeframe="news",
                candle_close_time=datetime.now(),
                score_news=round(abs_score * 0.3, 2),  # 新闻分项
                score_total=round(abs_score, 2),
                suggested_direction=direction,
                suggested_leverage=leverage,
                news_count_positive=sentiment["positive_count"],
                news_count_negative=sentiment["negative_count"],
                ai_reason=signal["reason"],
            )
            db.add(score_rec)
            db.commit()

            logger.info(f"[NewsStrategy] 触发信号: {strategy.strategy_name} {symbol} {direction} "
                       f"(强度={abs_score:.1f}, 新闻数={sentiment['articles_count']})")

    return signals


def run_all_news_ai_strategies(db: Session) -> Dict:
    """执行所有新闻AI策略"""
    strategies = db.query(StrategyConfig).filter(
        StrategyConfig.strategy_type == STRATEGY_TYPE_NEWS_AI,
        StrategyConfig.is_active == True,
    ).all()

    total_signals = 0
    strategy_results = []

    for s in strategies:
        try:
            signals = run_news_ai_strategy(db, s)
            total_signals += len(signals)
            strategy_results.append({
                "strategy_id": s.id,
                "strategy_name": s.strategy_name,
                "user_id": s.user_id,
                "signals_count": len(signals),
                "signals": signals,
            })
        except Exception as e:
            logger.error(f"[NewsStrategy] 策略执行失败 {s.id}: {e}")
            strategy_results.append({
                "strategy_id": s.id,
                "strategy_name": s.strategy_name,
                "error": str(e),
            })

    return {
        "strategies_count": len(strategies),
        "total_signals": total_signals,
        "results": strategy_results,
    }
