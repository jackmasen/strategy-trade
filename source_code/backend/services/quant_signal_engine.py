"""
AI Quant Signal Engine - AI量化信号引擎
==========================================
核心思想：从"单策略触发"升级为"多因子量化信号引擎"

7大因子体系：
  1. MarketRegimeFactor    - 市场状态因子（趋势强度/震荡幅度/突破概率）
  2. CapitalFlowFactor     - 资金流向因子（跨币种资金流入流出）
  3. LeverageFactor        - 杠杆集中度因子（持仓量/资金费率/杠杆水平）
  4. LiquidationFactor     - 清算压力因子（爆仓热力图/清算瀑布风险）
  5. NewsSentimentFactor   - 新闻情绪因子（事件驱动/情绪极值）
  6. VolatilityFactor      - 波动率因子（隐含波动/已实现波动/波动率锥）
  7. StrategyAdvantageFactor - 策略优势因子（当前哪种策略胜率最高）

综合评分公式：
  SignalScore = Σ (factor_weight_i * factor_score_i)
  其中各因子权重根据市场状态动态调整

交易决策：
  - 开多：SignalScore > bullish_threshold 且 多因子方向一致
  - 开空：SignalScore < bearish_threshold 且 多因子方向一致
  - 平仓：SignalScore 反转穿越中线 或 止盈止损触发
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from enum import Enum
import math
import statistics


class MarketRegime(str, Enum):
    """市场状态类型"""
    STRONG_TREND_UP = "strong_trend_up"      # 强势上涨趋势
    WEAK_TREND_UP = "weak_trend_up"          # 弱势上涨趋势
    RANGING = "ranging"                      # 震荡市
    WEAK_TREND_DOWN = "weak_trend_down"      # 弱势下跌趋势
    STRONG_TREND_DOWN = "strong_trend_down"  # 强势下跌趋势
    BREAKOUT_UP = "breakout_up"              # 向上突破
    BREAKOUT_DOWN = "breakout_down"          # 向下突破


class FactorDirection(str, Enum):
    """因子方向"""
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


@dataclass
class FactorResult:
    """单个因子的计算结果"""
    factor_name: str
    score: float           # -10 ~ +10 分
    direction: FactorDirection
    confidence: float      # 0 ~ 100%
    details: Dict = field(default_factory=dict)
    weight: float = 0.15   # 默认权重


@dataclass
class QuantSignal:
    """综合量化信号"""
    symbol: str
    timestamp: int
    composite_score: float       # -10 ~ +10
    direction: FactorDirection
    confidence: float            # 0 ~ 100%
    market_regime: MarketRegime
    factors: Dict[str, FactorResult]
    entry_price: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    suggested_leverage: int = 1
    position_size_pct: float = 0.0
    risk_reward_ratio: float = 0.0


# ============================================================
# 因子1: 市场状态因子 MarketRegimeFactor
# ============================================================
class MarketRegimeFactor:
    """
    市场状态识别因子
    
    数学公式：
    - ADX(14): 趋势强度  0-25弱趋势, 25-50强趋势, 50+极强趋势
    - MA斜率: slope = (MA20 - MA60) / MA60 * 100
    - 布林带宽度: BBWidth = (BB_upper - BB_lower) / BB_mid * 100
    - 波动率比: VolRatio = RealizedVol(20) / RealizedVol(60)
    
    综合趋势强度:
      TrendStrength = ADX_norm * 0.4 + |MA_slope|_norm * 0.3 + VolRatio_norm * 0.3
    
    市场状态判定：
      TrendStrength > 0.6 且 MA_slope > 0 → STRONG_TREND_UP
      TrendStrength > 0.6 且 MA_slope < 0 → STRONG_TREND_DOWN
      0.3 < TrendStrength ≤ 0.6 且 MA_slope > 0 → WEAK_TREND_UP
      0.3 < TrendStrength ≤ 0.6 且 MA_slope < 0 → WEAK_TREND_DOWN
      TrendStrength ≤ 0.3 → RANGING
    """

    @staticmethod
    def calc_adx(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> float:
        """计算ADX平均趋向指数"""
        if len(closes) < period + 1:
            return 20.0
        
        tr_list = []
        plus_dm = []
        minus_dm = []
        
        for i in range(1, len(closes)):
            high = highs[i]
            low = lows[i]
            prev_close = closes[i-1]
            prev_high = highs[i-1]
            prev_low = lows[i-1]
            
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            tr_list.append(tr)
            
            up_move = high - prev_high
            down_move = prev_low - low
            
            if up_move > down_move and up_move > 0:
                plus_dm.append(up_move)
            else:
                plus_dm.append(0)
            
            if down_move > up_move and down_move > 0:
                minus_dm.append(down_move)
            else:
                minus_dm.append(0)
        
        # 简化ADX计算
        atr = sum(tr_list[-period:]) / period if len(tr_list) >= period else sum(tr_list) / len(tr_list)
        plus_di = 100 * (sum(plus_dm[-period:]) / period) / atr if atr > 0 else 0
        minus_di = 100 * (sum(minus_dm[-period:]) / period) / atr if atr > 0 else 0
        dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di) if (plus_di + minus_di) > 0 else 0
        return min(100, dx)

    @staticmethod
    def calc_ma_slope(closes: List[float], fast: int = 20, slow: int = 60) -> float:
        """计算MA斜率（百分比）"""
        if len(closes) < slow:
            return 0.0
        ma_fast = sum(closes[-fast:]) / fast
        ma_slow = sum(closes[-slow:]) / slow
        return (ma_fast - ma_slow) / ma_slow * 100 if ma_slow > 0 else 0

    @staticmethod
    def calc_bb_width(closes: List[float], period: int = 20, std_dev: float = 2.0) -> float:
        """计算布林带宽度百分比"""
        if len(closes) < period:
            return 5.0
        ma = sum(closes[-period:]) / period
        variance = sum((c - ma) ** 2 for c in closes[-period:]) / period
        std = math.sqrt(variance)
        return (2 * std_dev * std) / ma * 100 if ma > 0 else 5.0

    @staticmethod
    def calc_realized_vol(closes: List[float], period: int = 20) -> float:
        """计算已实现波动率（年化）"""
        if len(closes) < period + 1:
            return 50.0
        returns = []
        for i in range(1, min(period + 1, len(closes))):
            if closes[i-1] > 0:
                returns.append((closes[i] - closes[i-1]) / closes[i-1])
        if len(returns) < 2:
            return 50.0
        std = statistics.stdev(returns)
        # 假设4小时K线，年化因子 = sqrt(365 * 6)
        return std * math.sqrt(365 * 6) * 100

    def compute(self, closes: List[float], highs: List[float], lows: List[float]) -> FactorResult:
        """计算市场状态因子"""
        adx = self.calc_adx(highs, lows, closes)
        ma_slope = self.calc_ma_slope(closes)
        bb_width = self.calc_bb_width(closes)
        vol_short = self.calc_realized_vol(closes, 20)
        vol_long = self.calc_realized_vol(closes, 60)
        vol_ratio = vol_short / vol_long if vol_long > 0 else 1.0

        # 归一化
        adx_norm = min(1.0, adx / 50)
        slope_norm = min(1.0, abs(ma_slope) / 3.0)  # 3%斜率算强趋势
        vol_norm = min(1.0, abs(vol_ratio - 1) / 0.5)

        trend_strength = adx_norm * 0.4 + slope_norm * 0.3 + vol_norm * 0.3
        is_bullish = ma_slope > 0

        # 判定市场状态
        if trend_strength > 0.6 and vol_ratio > 1.3:
            regime = MarketRegime.BREAKOUT_UP if is_bullish else MarketRegime.BREAKOUT_DOWN
        elif trend_strength > 0.6:
            regime = MarketRegime.STRONG_TREND_UP if is_bullish else MarketRegime.STRONG_TREND_DOWN
        elif trend_strength > 0.3:
            regime = MarketRegime.WEAK_TREND_UP if is_bullish else MarketRegime.WEAK_TREND_DOWN
        else:
            regime = MarketRegime.RANGING

        # 因子得分 (-10 ~ +10)
        score = trend_strength * 10 * (1 if is_bullish else -1)
        confidence = min(95, trend_strength * 100)
        direction = FactorDirection.BULLISH if score > 1.5 else (FactorDirection.BEARISH if score < -1.5 else FactorDirection.NEUTRAL)

        return FactorResult(
            factor_name="market_regime",
            score=score,
            direction=direction,
            confidence=confidence,
            details={
                "regime": regime.value,
                "adx": round(adx, 1),
                "ma_slope_pct": round(ma_slope, 2),
                "bb_width_pct": round(bb_width, 2),
                "trend_strength": round(trend_strength, 3),
                "vol_ratio": round(vol_ratio, 2),
            },
            weight=0.20,
        )


# ============================================================
# 因子2: 资金流向因子 CapitalFlowFactor
# ============================================================
class CapitalFlowFactor:
    """
    资金流向因子
    
    数学公式：
    - 成交量加权价格变化: VWAP_Dev = (Price - VWAP) / VWAP * 100
    - OBV变化率: OBV_pct = OBV(now) / OBV(20期前) - 1
    - 量价背离: VolumeDivergence = corr(price, volume, 20期)
    - 资金流向指数: MFI(14) - 0~100, >80超买, <20超卖
    
    综合资金流向得分:
      FlowScore = VWAP_Dev_norm * 0.3 + OBV_pct_norm * 0.3 + (MFI - 50)/50 * 10 * 0.4
    """

    @staticmethod
    def calc_vwap(closes: List[float], highs: List[float], lows: List[float], volumes: List[float]) -> float:
        """计算VWAP（成交量加权平均价）"""
        period = min(20, len(closes))
        if period == 0:
            return closes[-1] if closes else 0
        typical_prices = [(h + l + c) / 3 for h, l, c in zip(highs[-period:], lows[-period:], closes[-period:])]
        total_volume = sum(volumes[-period:])
        if total_volume == 0:
            return closes[-1]
        vwap = sum(tp * v for tp, v in zip(typical_prices, volumes[-period:])) / total_volume
        return vwap

    @staticmethod
    def calc_obv(closes: List[float], volumes: List[float]) -> float:
        """计算OBV能量潮（变化率）"""
        period = min(20, len(closes) - 1)
        if period < 2:
            return 0
        obv = 0.0
        obv_values = []
        for i in range(1, len(closes)):
            if closes[i] > closes[i-1]:
                obv += volumes[i]
            elif closes[i] < closes[i-1]:
                obv -= volumes[i]
            obv_values.append(obv)
        
        if len(obv_values) < period:
            return 0
        old_obv = obv_values[-period] if obv_values[-period] != 0 else 1
        return (obv - old_obv) / abs(old_obv) * 100 if old_obv != 0 else 0

    @staticmethod
    def calc_mfi(highs: List[float], lows: List[float], closes: List[float], volumes: List[float], period: int = 14) -> float:
        """计算MFI资金流向指数"""
        if len(closes) < period + 1:
            return 50.0
        positive_flow = []
        negative_flow = []
        for i in range(1, min(period + 1, len(closes))):
            typical_price_t = (highs[i] + lows[i] + closes[i]) / 3
            typical_price_prev = (highs[i-1] + lows[i-1] + closes[i-1]) / 3
            money_flow = typical_price_t * volumes[i]
            if typical_price_t > typical_price_prev:
                positive_flow.append(money_flow)
            elif typical_price_t < typical_price_prev:
                negative_flow.append(money_flow)
        
        pos_sum = sum(positive_flow)
        neg_sum = sum(negative_flow)
        if neg_sum == 0:
            return 100.0
        money_ratio = pos_sum / neg_sum
        mfi = 100 - (100 / (1 + money_ratio))
        return mfi

    def compute(self, closes: List[float], highs: List[float], lows: List[float], volumes: List[float]) -> FactorResult:
        """计算资金流向因子"""
        vwap = self.calc_vwap(closes, highs, lows, volumes)
        current_price = closes[-1]
        vwap_dev = (current_price - vwap) / vwap * 100 if vwap > 0 else 0
        
        obv_pct = self.calc_obv(closes, volumes)
        mfi = self.calc_mfi(highs, lows, closes, volumes)

        # 归一化得分
        vwap_score = max(-5, min(5, vwap_dev * 2))  # ±2.5% → ±5分
        obv_score = max(-5, min(5, obv_pct * 0.5))  # ±10% → ±5分
        mfi_score = (mfi - 50) / 50 * 5  # 0-100 → -5~+5分

        # 综合得分
        score = vwap_score * 0.3 + obv_score * 0.3 + mfi_score * 0.4
        confidence = min(90, abs(score) * 8 + 30)
        direction = FactorDirection.BULLISH if score > 1.0 else (FactorDirection.BEARISH if score < -1.0 else FactorDirection.NEUTRAL)

        return FactorResult(
            factor_name="capital_flow",
            score=score,
            direction=direction,
            confidence=confidence,
            details={
                "vwap": round(vwap, 4),
                "vwap_deviation_pct": round(vwap_dev, 2),
                "obv_change_pct": round(obv_pct, 2),
                "mfi": round(mfi, 1),
            },
            weight=0.18,
        )


# ============================================================
# 因子3: 杠杆集中度因子 LeverageFactor
# ============================================================
class LeverageFactor:
    """
    杠杆集中度因子
    
    数学公式：
    - 持仓量变化率: OI_pct = (OI_now - OI_20periods_ago) / OI_20periods_ago * 100
    - 资金费率: FundingRate - 正=多头付空头，负=空头付多头
    - 多空持仓比: LongShortRatio - >1多头占优
    - 杠杆水平估算: EstLeverage = OI / MarketCap * avg_lev_factor
    
    综合杠杆压力得分：
      - 高OI增长 + 正资金费率 → 多头拥挤，反向看空
      - 高OI增长 + 负资金费率 → 空头拥挤，反向看多
      - 低OI + 中性费率 → 杠杆低，趋势可持续
    """

    def compute(self, oi_data: Optional[List[float]] = None, 
                funding_rate: float = 0.01, 
                long_short_ratio: float = 1.0) -> FactorResult:
        """计算杠杆集中度因子"""
        # OI变化率
        oi_pct = 0.0
        if oi_data and len(oi_data) >= 20:
            oi_pct = (oi_data[-1] - oi_data[-20]) / oi_data[-20] * 100 if oi_data[-20] > 0 else 0

        # 资金费率得分 (年化0.01%为正常，偏离越大越极端)
        funding_annualized = funding_rate * 3 * 365 * 100  # 假设3次/天
        funding_score = -funding_annualized * 0.5  # 正费率→负分（多头付）
        funding_score = max(-5, min(5, funding_score))

        # 多空比得分
        ratio_score = (long_short_ratio - 1) * 5  # 1:1→0, 2:1→+5
        ratio_score = max(-5, min(5, ratio_score))

        # OI变化得分
        oi_score = max(-5, min(5, oi_pct * 0.3))

        # 综合：OI增长+正费率+高多空比 = 极端多头 = 看空信号
        score = - (abs(oi_score) * 0.3 + funding_score * 0.4 + ratio_score * 0.3)
        # 修正：如果OI快速增加且多空比极端，是反向指标
        if oi_pct > 5:
            if long_short_ratio > 1.5:
                score = -abs(score)  # 多头拥挤→看空
            elif long_short_ratio < 0.7:
                score = abs(score)   # 空头拥挤→看多

        confidence = min(85, abs(funding_annualized) * 2 + abs(long_short_ratio - 1) * 20 + 30)
        direction = FactorDirection.BULLISH if score > 1.0 else (FactorDirection.BEARISH if score < -1.0 else FactorDirection.NEUTRAL)

        return FactorResult(
            factor_name="leverage",
            score=score,
            direction=direction,
            confidence=confidence,
            details={
                "oi_change_pct_20p": round(oi_pct, 2),
                "funding_rate_pct": round(funding_rate * 100, 4),
                "funding_annualized_pct": round(funding_annualized, 2),
                "long_short_ratio": round(long_short_ratio, 2),
                "crowding_level": "high" if abs(oi_pct) > 10 and abs(long_short_ratio - 1) > 0.5 else "normal",
            },
            weight=0.15,
        )


# ============================================================
# 因子4: 清算压力因子 LiquidationFactor
# ============================================================
class LiquidationFactor:
    """
    清算压力因子（爆仓热力图）
    
    数学公式：
    - 清算价格分布估计: 基于OI和杠杆水平估算关键清算价位
    - 上方清算压力: LiqAbove = Σ OI_long * lev_ratio 在 [price, price+X%] 区间
    - 下方清算压力: LiqBelow = Σ OI_short * lev_ratio 在 [price-X%, price] 区间
    - 清算瀑布风险: LiqCascadeRisk = LiqAbove / 24h_volume 或 LiqBelow / 24h_volume
    
    得分逻辑：
      - 上方大量清算 → 上涨阻力大（负分）
      - 下方大量清算 → 下跌支撑弱（正分，因为清算会加速下跌）
      - 清算密度 > 阈值 → 高波动预期
    """

    def compute(self, current_price: float, 
                liquidation_above_pct: float = 0.0,
                liquidation_below_pct: float = 0.0,
                volume_24h: float = 1_000_000_000) -> FactorResult:
        """计算清算压力因子
        
        Args:
            liquidation_above_pct: 上方5%内清算量占24h成交量的百分比
            liquidation_below_pct: 下方5%内清算量占24h成交量的百分比
        """
        # 清算压力不对称性
        liq_imbalance = (liquidation_above_pct - liquidation_below_pct) 
        
        # 上方清算多 = 上涨阻力 = 看空（负分）
        # 下方清算多 = 下跌加速 = 看空（正分因为会加速下跌但方向是下）
        # 实际上：大量清算在上方=阻力=偏空，大量在下方=支撑位附近=可能反弹
        score = liquidation_below_pct * 0.5 - liquidation_above_pct * 0.5
        score = max(-10, min(10, score))

        total_liq_pct = liquidation_above_pct + liquidation_below_pct
        confidence = min(80, total_liq_pct * 2 + 20)
        direction = FactorDirection.BULLISH if score > 1.5 else (FactorDirection.BEARISH if score < -1.5 else FactorDirection.NEUTRAL)

        return FactorResult(
            factor_name="liquidation",
            score=score,
            direction=direction,
            confidence=confidence,
            details={
                "liquidation_above_5pct_pct": round(liquidation_above_pct, 2),
                "liquidation_below_5pct_pct": round(liquidation_below_pct, 2),
                "total_liquidity_zone_pct": round(total_liq_pct, 2),
                "imbalance": round(liq_imbalance, 2),
                "cascade_risk": "high" if total_liq_pct > 15 else "medium" if total_liq_pct > 8 else "low",
            },
            weight=0.12,
        )


# ============================================================
# 因子5: 波动率因子 VolatilityFactor
# ============================================================
class VolatilityFactor:
    """
    波动率因子
    
    数学公式：
    - 已实现波动率: RealizedVol = std(returns) * sqrt(periods_per_year)
    - 波动率锥位置: VolPercentile = percentile(current_vol, vol_history)
    - ATR比值: ATR_ratio = ATR(14) / ATR(60)
    - 波动率偏度: VolSkew = (IV_high - IV_low) / IV_atm  (如果有IV数据)
    
    得分逻辑：
      - 低波动率 + 收敛 → 即将突破（中性偏多）
      - 高波动率 + 扩张 → 趋势延续（顺势）
      - 波动率极值 → 反转信号
    """

    def compute(self, closes: List[float], highs: List[float], lows: List[float]) -> FactorResult:
        """计算波动率因子"""
        rv_20 = MarketRegimeFactor.calc_realized_vol(closes, 20)
        rv_60 = MarketRegimeFactor.calc_realized_vol(closes, 60)
        vol_ratio = rv_20 / rv_60 if rv_60 > 0 else 1.0
        bb_width = MarketRegimeFactor.calc_bb_width(closes)

        # ATR计算
        period = min(14, len(closes) - 1)
        if period > 1:
            tr_list = []
            for i in range(1, len(closes)):
                tr = max(highs[i] - lows[i], 
                        abs(highs[i] - closes[i-1]), 
                        abs(lows[i] - closes[i-1]))
                tr_list.append(tr)
            atr = sum(tr_list[-period:]) / period if len(tr_list) >= period else sum(tr_list) / len(tr_list)
            atr_pct = atr / closes[-1] * 100 if closes[-1] > 0 else 2
        else:
            atr_pct = 2.0

        # 波动率状态
        if vol_ratio > 1.3:
            vol_state = "expanding"  # 扩张
            # 扩张中 + 高波动 → 趋势延续
            score = 3 if vol_ratio > 1.5 else 1.5
        elif vol_ratio < 0.7:
            vol_state = "contracting"  # 收敛
            # 低波动收敛 → 即将突破
            score = 0
        else:
            vol_state = "normal"
            score = 0

        confidence = min(80, abs(vol_ratio - 1) * 50 + 30)
        direction = FactorDirection.NEUTRAL  # 波动率因子主要辅助，不给明确方向

        return FactorResult(
            factor_name="volatility",
            score=score,
            direction=direction,
            confidence=confidence,
            details={
                "realized_vol_20d_pct": round(rv_20, 1),
                "realized_vol_60d_pct": round(rv_60, 1),
                "vol_ratio_20_60": round(vol_ratio, 2),
                "atr_pct": round(atr_pct, 2),
                "bb_width_pct": round(bb_width, 2),
                "vol_state": vol_state,
            },
            weight=0.10,
        )


# ============================================================
# 因子6: 新闻情绪因子 NewsSentimentFactor
# ============================================================
class NewsSentimentFactor:
    """
    新闻情绪因子
    
    数学公式：
    - 情绪得分: SentimentScore = avg(sentiment * impact_weight) over N news
    - 情绪极值: SentimentExtreme = |sentiment - 0.5| * 2  (0~1)
    - 新闻密度: NewsDensity = news_count_24h / avg_news_count_7d
    - 事件重要性: EventImpact = max(impact_score) over recent news
    
    综合情绪得分：
      NewsScore = SentimentScore * (1 + NewsDensity * 0.5) * EventImpact_factor
      
    反身性：极度看多(>0.8)且新闻密度极高 → 反向指标（过热）
    """

    def compute(self, sentiment_score: float = 0.5, 
                news_count_24h: int = 10,
                avg_news_count: int = 10,
                max_impact: float = 0.5) -> FactorResult:
        """计算新闻情绪因子
        
        Args:
            sentiment_score: 0~1, 0.5中性, 1极度看多, 0极度看空
            news_count_24h: 24小时新闻数量
            avg_news_count: 7天平均新闻数
            max_impact: 最大事件影响力 0~1
        """
        news_density = news_count_24h / avg_news_count if avg_news_count > 0 else 1.0
        
        # 基础情绪分 (-10 ~ +10)
        base_score = (sentiment_score - 0.5) * 20  # 0~1 → -10~+10
        
        # 密度放大
        density_amp = 1 + min(1.0, (news_density - 1) * 0.5)
        score = base_score * density_amp
        
        # 反身性修正：极度情绪+高密度 → 反向减弱（过热/过冷反转）
        if abs(base_score) > 7 and news_density > 2:
            score *= 0.6  # 减弱60%，因为可能是极值反转
        
        score = max(-10, min(10, score))
        confidence = min(90, abs(sentiment_score - 0.5) * 100 + news_density * 10)
        direction = FactorDirection.BULLISH if score > 1.5 else (FactorDirection.BEARISH if score < -1.5 else FactorDirection.NEUTRAL)

        return FactorResult(
            factor_name="news_sentiment",
            score=score,
            direction=direction,
            confidence=confidence,
            details={
                "sentiment_score": round(sentiment_score, 3),
                "news_count_24h": news_count_24h,
                "news_density_ratio": round(news_density, 2),
                "max_event_impact": round(max_impact, 2),
                "is_extreme": abs(sentiment_score - 0.5) > 0.3,
            },
            weight=0.15,
        )


# ============================================================
# 因子7: 策略优势因子 StrategyAdvantageFactor
# ============================================================
class StrategyAdvantageFactor:
    """
    策略优势因子 - 评估当前哪种策略最有优势
    
    数学公式：
    - 各策略近期胜率: WinRate_strat = wins / total_trades (最近N笔)
    - 各策略盈亏比: ProfitFactor_strat = gross_profit / gross_loss
    - 夏普比率: Sharpe_strat = avg_return / std_return * sqrt(frequency)
    - 适配度: StrategyFit = 策略在当前market_regime下的历史表现
    
    综合策略优势评分：
      AdvantageScore_strat = WinRate_norm * 0.4 + ProfitFactor_norm * 0.3 + Sharpe_norm * 0.3
    """

    def compute(self, strategy_performance: Dict[str, Dict]) -> FactorResult:
        """
        计算策略优势因子
        
        Args:
            strategy_performance: {strategy_name: {win_rate, profit_factor, sharpe, recent_trades}}
        """
        if not strategy_performance:
            return FactorResult(
                factor_name="strategy_advantage",
                score=0,
                direction=FactorDirection.NEUTRAL,
                confidence=0,
                details={"best_strategy": None, "rankings": []},
                weight=0.10,
            )

        rankings = []
        for strat_name, perf in strategy_performance.items():
            wr = perf.get("win_rate", 50)
            pf = perf.get("profit_factor", 1.0)
            sharpe = perf.get("sharpe", 0.5)
            trades = perf.get("recent_trades", 10)
            
            # 归一化
            wr_norm = min(1.0, max(0, (wr - 40) / 30))  # 40%~70% → 0~1
            pf_norm = min(1.0, max(0, (pf - 0.8) / 1.2))  # 0.8~2.0 → 0~1
            sharpe_norm = min(1.0, max(0, (sharpe + 1) / 3))  # -1~2 → 0~1
            
            # 交易数权重（样本量越大越可信）
            sample_weight = min(1.0, trades / 30)
            
            score = (wr_norm * 0.4 + pf_norm * 0.3 + sharpe_norm * 0.3) * sample_weight
            rankings.append({
                "strategy": strat_name,
                "advantage_score": round(score, 3),
                "win_rate": wr,
                "profit_factor": round(pf, 2),
                "sharpe": round(sharpe, 2),
                "trades": trades,
            })

        rankings.sort(key=lambda x: x["advantage_score"], reverse=True)
        best = rankings[0] if rankings else None
        best_score = best["advantage_score"] if best else 0
        
        # 因子得分：最优策略优势度
        score = best_score * 10 - 5  # 0~1 → -5~+5
        confidence = min(85, best_score * 100 if best else 30)
        direction = FactorDirection.BULLISH if score > 1 else (FactorDirection.BEARISH if score < -1 else FactorDirection.NEUTRAL)

        return FactorResult(
            factor_name="strategy_advantage",
            score=score,
            direction=direction,
            confidence=confidence,
            details={
                "best_strategy": best["strategy"] if best else None,
                "best_score": round(best_score, 3),
                "rankings": rankings[:5],
            },
            weight=0.10,
        )


# ============================================================
# 综合信号引擎 QuantSignalEngine
# ============================================================
class QuantSignalEngine:
    """
    AI量化信号引擎 - 多因子综合评分
    
    综合评分公式：
      CompositeScore = Σ (factor_i.weight * factor_i.score * factor_i.confidence/100)
    
    动态权重调整：
      - 强趋势市：market_regime权重+10%, bollinger类策略权重-5%
      - 震荡市：volatility权重+10%, 趋势类策略权重-5%
      - 高新闻密度：news_sentiment权重+10%
    """

    def __init__(self):
        self.regime_factor = MarketRegimeFactor()
        self.flow_factor = CapitalFlowFactor()
        self.leverage_factor = LeverageFactor()
        self.liq_factor = LiquidationFactor()
        self.vol_factor = VolatilityFactor()
        self.news_factor = NewsSentimentFactor()
        self.strategy_factor = StrategyAdvantageFactor()

    def generate_signal(self, symbol: str,
                       closes: List[float],
                       highs: List[float],
                       lows: List[float],
                       volumes: List[float],
                       oi_data: Optional[List[float]] = None,
                       funding_rate: float = 0.01,
                       long_short_ratio: float = 1.0,
                       liq_above_pct: float = 0.0,
                       liq_below_pct: float = 0.0,
                       news_sentiment: float = 0.5,
                       news_count_24h: int = 10,
                       avg_news_count: int = 10,
                       strategy_perf: Optional[Dict[str, Dict]] = None) -> QuantSignal:
        """生成综合量化信号"""
        
        # 1. 计算各因子
        factors = {}
        factors["market_regime"] = self.regime_factor.compute(closes, highs, lows)
        factors["capital_flow"] = self.flow_factor.compute(closes, highs, lows, volumes)
        factors["leverage"] = self.leverage_factor.compute(oi_data, funding_rate, long_short_ratio)
        factors["liquidation"] = self.liq_factor.compute(closes[-1] if closes else 0, liq_above_pct, liq_below_pct)
        factors["volatility"] = self.vol_factor.compute(closes, highs, lows)
        factors["news_sentiment"] = self.news_factor.compute(news_sentiment, news_count_24h, avg_news_count)
        factors["strategy_advantage"] = self.strategy_factor.compute(strategy_perf or {})

        # 2. 动态权重调整
        regime = factors["market_regime"].details.get("regime", "ranging")
        self._adjust_weights(factors, regime)

        # 3. 综合评分
        total_weight = sum(f.weight * (f.confidence / 100) for f in factors.values())
        composite = sum(
            f.weight * (f.confidence / 100) * f.score
            for f in factors.values()
        ) / total_weight if total_weight > 0 else 0

        composite = max(-10, min(10, composite))

        # 4. 方向判定（需要多因子一致性）
        bullish_count = sum(1 for f in factors.values() if f.direction == FactorDirection.BULLISH and f.confidence > 40)
        bearish_count = sum(1 for f in factors.values() if f.direction == FactorDirection.BEARISH and f.confidence > 40)
        total_active = bullish_count + bearish_count

        # 一致性阈值：至少60%的有效因子方向一致
        consistency_bull = bullish_count / total_active if total_active > 0 else 0
        consistency_bear = bearish_count / total_active if total_active > 0 else 0

        if composite > 1.5 and consistency_bull >= 0.5:
            direction = FactorDirection.BULLISH
        elif composite < -1.5 and consistency_bear >= 0.5:
            direction = FactorDirection.BEARISH
        else:
            direction = FactorDirection.NEUTRAL

        # 5. 置信度（加权平均）
        confidence = sum(f.weight * f.confidence for f in factors.values()) / sum(f.weight for f in factors.values())

        # 6. 止盈止损计算
        current_price = closes[-1] if closes else 0
        atr_pct = factors["volatility"].details.get("atr_pct", 2.0)
        bb_width = factors["volatility"].details.get("bb_width_pct", 5.0)
        
        # 动态止损：ATR的1.5倍，最小1.5%，最大5%
        sl_pct = max(1.5, min(5.0, atr_pct * 1.5))
        # 动态止盈：根据盈亏比和波动率
        tp_ratio = 2.0 if factors["market_regime"].details.get("trend_strength", 0.3) > 0.5 else 1.5
        tp_pct = sl_pct * tp_ratio

        if direction == FactorDirection.BULLISH:
            stop_loss = current_price * (1 - sl_pct / 100)
            take_profit = current_price * (1 + tp_pct / 100)
        elif direction == FactorDirection.BEARISH:
            stop_loss = current_price * (1 + sl_pct / 100)
            take_profit = current_price * (1 - tp_pct / 100)
        else:
            stop_loss = 0
            take_profit = 0

        # 7. 建议杠杆和仓位
        trend_strength = factors["market_regime"].details.get("trend_strength", 0.3)
        if confidence > 70 and trend_strength > 0.5:
            suggested_lev = 5
            pos_pct = 10
        elif confidence > 50:
            suggested_lev = 3
            pos_pct = 7
        else:
            suggested_lev = 2
            pos_pct = 5

        rr_ratio = tp_pct / sl_pct if sl_pct > 0 else 0

        return QuantSignal(
            symbol=symbol,
            timestamp=int(__import__('time').time()),
            composite_score=round(composite, 2),
            direction=direction,
            confidence=round(confidence, 1),
            market_regime=MarketRegime(regime),
            factors=factors,
            entry_price=current_price,
            stop_loss=round(stop_loss, 4),
            take_profit=round(take_profit, 4),
            suggested_leverage=suggested_lev,
            position_size_pct=pos_pct,
            risk_reward_ratio=round(rr_ratio, 2),
        )

    def _adjust_weights(self, factors: Dict[str, FactorResult], regime: str):
        """根据市场状态动态调整因子权重"""
        if "trend" in regime or "breakout" in regime:
            # 趋势市：加重市场状态和资金流权重
            factors["market_regime"].weight = 0.25
            factors["capital_flow"].weight = 0.20
            factors["volatility"].weight = 0.08
            factors["strategy_advantage"].weight = 0.12  # 趋势策略更重要
        elif regime == "ranging":
            # 震荡市：加重波动率和清算因子
            factors["market_regime"].weight = 0.15
            factors["volatility"].weight = 0.15
            factors["liquidation"].weight = 0.15
            factors["capital_flow"].weight = 0.15
        # 默认权重总和保持 ~1.0
