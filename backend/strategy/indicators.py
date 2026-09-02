"""
C-1: 技术指标计算模块
输入：K线数据（按时间正序，升序）
输出：MA / RSI / MACD / Bollinger Bands / ATR 数值，以及10分制技术分项评分 + 方向建议

注意：本模块使用纯 NumPy 实现，避免额外依赖 ta-lib（它在Windows编译麻烦）。
如果项目后续装了 ta-lib 可直接替换本文件实现。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Tuple, Sequence

import math


# =========================================================
# Data structures
# =========================================================
@dataclass
class Candle:
    """简化版K线（与 _types.Candle 一致的字段名）"""
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    open_time_ms: int = 0
    close_time_ms: int = 0


@dataclass
class IndicatorResult:
    """指标计算结果"""
    # 移动均线
    ma7: float = 0.0
    ma25: float = 0.0
    ma99: float = 0.0
    # RSI
    rsi14: float = 0.0
    # MACD
    macd: float = 0.0        # dif - dea
    macd_dif: float = 0.0    # 12ema - 26ema
    macd_dea: float = 0.0    # 9ema(dif)
    # 布林带
    bb_upper: float = 0.0
    bb_mid: float = 0.0       # MA20
    bb_lower: float = 0.0
    bb_width_pct: float = 0.0  # (upper-lower)/mid
    bb_position: float = 0.0   # (close - lower)/(upper - lower) ∈[0,1]
    # ATR（波动率）
    atr14: float = 0.0
    atr_pct: float = 0.0      # atr / close，用来建议杠杆
    # EMV（Ease of Movement）
    emv: float = 0.0           # EMV 主线
    emv_signal: float = 0.0    # EMV 信号线
    emv_cross_up: bool = False # EMV 是否刚上穿信号线
    # 最新价
    last_close: float = 0.0


@dataclass
class TechnicalScoreResult:
    """技术面评分(10分制) + 多空方向建议 + 建议杠杆"""
    score: float = 0.0                   # 0-10，越高越偏多
    directional_score: float = 0.0       # -10 到 +10，正为多，负为空
    direction: int = 0                   # 0观望 1多 2空
    confidence: float = 0.0              # 0-1，整体置信度
    indicators: IndicatorResult = field(default_factory=IndicatorResult)
    sub_scores: dict = field(default_factory=dict)   # 每个指标的子分
    reasons: List[str] = field(default_factory=list)  # 主要理由（用于前端展示）
    suggest_leverage: int = 3            # 建议杠杆倍数(3-10)，波动率低就给高倍数
    suggest_tp_pct: float = 4.0
    suggest_sl_pct: float = 2.0


# =========================================================
# Helpers
# =========================================================
def _as_float(x) -> float:
    try:
        if x is None:
            return 0.0
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def _candles_to_arrays(klines: Sequence) -> Tuple[List[float], List[float], List[float], List[float], List[float]]:
    """兼容 backend.exchanges._types.Candle 或 Candle 或 dict 三种输入
    返回 (opens, highs, lows, closes, volumes)
    """
    opens, highs, lows, closes, vols = [], [], [], [], []
    for k in klines:
        if isinstance(k, dict):
            o, h, l, c, v = (
                _as_float(k.get("open", k.get("o"))),
                _as_float(k.get("high", k.get("h"))),
                _as_float(k.get("low", k.get("l"))),
                _as_float(k.get("close", k.get("c"))),
                _as_float(k.get("volume", k.get("vol", k.get("v", 0)))),
            )
        else:
            o, h, l, c, v = (
                _as_float(getattr(k, "open", 0)),
                _as_float(getattr(k, "high", 0)),
                _as_float(getattr(k, "low", 0)),
                _as_float(getattr(k, "close", 0)),
                _as_float(getattr(k, "volume", 0)),
            )
        opens.append(o); highs.append(h); lows.append(l); closes.append(c); vols.append(v)
    return opens, highs, lows, closes, vols


# =========================================================
# Indicator primitives
# =========================================================
def sma(values: Sequence[float], period: int) -> List[float]:
    """简单移动均线"""
    res = []
    s = 0.0
    for i, v in enumerate(values):
        s += v
        if i >= period:
            s -= values[i - period]
        res.append(s / period if i >= period - 1 else float("nan"))
    return res


def ema(values: Sequence[float], period: int) -> List[float]:
    """指数移动均线（EMA）"""
    if not values:
        return []
    k = 2 / (period + 1)
    res = [float(values[0])]
    for v in values[1:]:
        res.append(res[-1] * (1 - k) + v * k)
    # 前面一部分用 NaN（为了对齐周期长度）
    for i in range(min(period - 1, len(res))):
        res[i] = float("nan")
    return res


def rsi(closes: Sequence[float], period: int = 14) -> List[float]:
    """RSI（Wilder平滑，简化版用EMA）"""
    gains = [0.0]
    losses = [0.0]
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    avg_gain = ema(gains, period)
    avg_loss = ema(losses, period)
    out = []
    for i in range(len(closes)):
        ag, al = avg_gain[i], avg_loss[i]
        if math.isnan(ag) or math.isnan(al):
            out.append(float("nan"))
        elif al == 0:
            out.append(100.0 if ag > 0 else 50.0)
        else:
            rs = ag / al
            out.append(100.0 - 100.0 / (1.0 + rs))
    return out


def macd(closes: Sequence[float], fast: int = 12, slow: int = 26, signal: int = 9):
    """MACD → (dif, dea, histogram)"""
    ema_fast = ema(closes, fast)
    ema_slow = ema(closes, slow)
    dif = []
    for i in range(len(closes)):
        d = (
            (ema_fast[i] if not math.isnan(ema_fast[i]) else closes[i])
            - (ema_slow[i] if not math.isnan(ema_slow[i]) else closes[i])
        )
        dif.append(d)
    dea = ema(dif, signal)
    hist = [(dif[i] - dea[i]) * 2 for i in range(len(closes))]
    return dif, dea, hist


def bollinger_bands(closes: Sequence[float], period: int = 20, std_mult: float = 2.0):
    """布林带 → (upper, mid(MA20), lower)"""
    mid = sma(closes, period)
    upper = []; lower = []
    for i in range(len(closes)):
        if i < period - 1:
            upper.append(float("nan")); lower.append(float("nan"))
            continue
        vsum = 0.0
        mean = mid[i]
        for j in range(i - period + 1, i + 1):
            vsum += (closes[j] - mean) ** 2
        std = math.sqrt(vsum / period)
        upper.append(mean + std_mult * std)
        lower.append(mean - std_mult * std)
    return upper, mid, lower


def atr(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], period: int = 14):
    """平均真实波幅 ATR（Wilder 平滑用 EMA 近似）"""
    tr = []
    for i in range(len(highs)):
        h, l = highs[i], lows[i]
        if i == 0:
            tr.append(h - l)
        else:
            pc = closes[i - 1]
            tr.append(max(h - l, abs(h - pc), abs(l - pc)))
    # Wilder 平滑（EMA 近似：period=14 用 alpha=1/14）
    alpha = 1.0 / period
    if not tr:
        return []
    out = [tr[0]]
    for i in range(1, len(tr)):
        out.append(out[-1] * (1 - alpha) + tr[i] * alpha)
    for i in range(min(period - 1, len(out))):
        out[i] = float("nan")
    return out


def emv(
    highs: Sequence[float],
    lows: Sequence[float],
    volumes: Sequence[float],
    period: int = 14,
    signal_period: int = 9,
    vol_divisor: float = 10_000_000.0,
) -> Tuple[List[float], List[float]]:
    """
    Ease of Movement（简易移动指标）
    返回 (emv_main, emv_signal) 两个序列，与输入等长。

    EMV 衡量价格移动的"轻松程度"：
    - 分子 = Mid-Price 变化（方向）
    - 分母 = Volume / (High-Low)（阻力）
    当价格上行且成交量放大时 EMV 升高 → 多头轻松推进
    当价格下行且成交量放大时 EMV 降低 → 空头轻松推进

    vol_divisor 用于将 volume 缩放到合理量级，避免除零。
    """
    n = len(highs)
    if n == 0:
        return [], []

    raw: List[float] = [0.0]
    for i in range(1, n):
        mid_i = (highs[i] + lows[i]) * 0.5
        mid_j = (highs[i - 1] + lows[i - 1]) * 0.5
        dist = mid_i - mid_j
        hl = max(highs[i] - lows[i], 1e-9)
        vol_scaled = volumes[i] / max(vol_divisor, 1e-9)
        box = vol_scaled / hl
        v = dist / max(box, 1e-9)
        if math.isnan(v) or math.isinf(v):
            v = 0.0
        raw.append(v)

    # EMV 主线 = SMA(raw, period)
    main = _nan_to_zero(sma(raw, period))
    # EMV 信号线 = SMA(main, signal_period)
    sig = _nan_to_zero(sma(main, signal_period))
    return main, sig


def _nan_to_zero(xs: Sequence[float]) -> List[float]:
    """将 NaN/inf 替换为 0.0"""
    return [
        0.0 if (v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))))
        else float(v)
        for v in xs
    ]


# =========================================================
# Main technical analyzer
# =========================================================
class TechnicalAnalyzer:
    """
    技术指标分析器

    典型用法：
        res = TechnicalAnalyzer().analyze(klines, timeframe="1h")
        print(res.score, res.direction, res.suggest_leverage)
    """

    # ============== 配置 ==============
    # 权重：5大指标合计10分。方向分用 "做多倾向 - 做空倾向"
    WEIGHTS = {
        "ma": 2.0,         # 均线趋势
        "rsi": 2.0,        # 震荡超买超卖
        "macd": 2.5,       # 动能
        "boll": 2.0,       # 布林位置 & 收口
        "atr": 1.5,        # 波动率决定可信度 & 杠杆
    }

    def __init__(self, min_klines: int = 80):
        self.min_klines = min_klines

    # ============== 入口 ==============
    def analyze(self, klines: Sequence, timeframe: str = "1h") -> TechnicalScoreResult:
        opens, highs, lows, closes, vols = _candles_to_arrays(klines)
        N = len(closes)
        result = TechnicalScoreResult()
        if N < self.min_klines:
            result.reasons.append(f"K线样本不足：{N} < {self.min_klines}，参考价值有限")
            result.indicators.last_close = closes[-1] if closes else 0
            return result

        # 1) 计算基础指标
        ma7_arr = sma(closes, 7)
        ma25_arr = sma(closes, 25)
        ma99_arr = sma(closes, 99)
        rsi_arr = rsi(closes, 14)
        dif_arr, dea_arr, hist_arr = macd(closes)
        bb_u, bb_m, bb_l = bollinger_bands(closes, 20)
        atr_arr = atr(highs, lows, closes, 14)
        emv_arr, emv_sig_arr = emv(highs, lows, vols, period=14, signal_period=9)

        ind = result.indicators
        ind.ma7 = ma7_arr[-1]; ind.ma25 = ma25_arr[-1]; ind.ma99 = ma99_arr[-1]
        ind.rsi14 = rsi_arr[-1]
        ind.macd_dif = dif_arr[-1]; ind.macd_dea = dea_arr[-1]; ind.macd = hist_arr[-1]
        ind.bb_upper = bb_u[-1]; ind.bb_mid = bb_m[-1]; ind.bb_lower = bb_l[-1]
        ind.atr14 = atr_arr[-1]
        # EMV
        if emv_arr:
            ind.emv = emv_arr[-1]
            ind.emv_signal = emv_sig_arr[-1]
            # 检测上穿：前一根 EMV <= Signal，当前根 EMV > Signal 且 EMV > 0
            if len(emv_arr) >= 2:
                ind.emv_cross_up = (
                    emv_arr[-2] <= emv_sig_arr[-2]
                    and emv_arr[-1] > emv_sig_arr[-1]
                    and emv_arr[-1] > 0
                )
        ind.last_close = closes[-1]

        if ind.bb_mid > 0:
            ind.bb_width_pct = (ind.bb_upper - ind.bb_lower) / ind.bb_mid
            if ind.bb_upper - ind.bb_lower > 1e-12:
                ind.bb_position = (ind.last_close - ind.bb_lower) / (ind.bb_upper - ind.bb_lower)
        if ind.last_close > 0:
            ind.atr_pct = ind.atr14 / ind.last_close

        # 2) 分项评分（每个0-10分，并给出方向 -1..+1）
        ss = {}
        reasons = []
        ma_score, ma_dir = self._score_ma(ma7_arr, ma25_arr, ma99_arr, closes)
        ss["ma"] = ma_score
        if ma_dir > 0.2:
            reasons.append(f"均线多头 MA7>{'>MA25>' if ind.ma25>ind.ma99 else ''}MA99")
        elif ma_dir < -0.2:
            reasons.append(f"均线空头 MA7<{'MA25<' if ind.ma25<ind.ma99 else ''}MA99")

        rsi_score, rsi_dir = self._score_rsi(rsi_arr)
        ss["rsi"] = rsi_score
        if ind.rsi14 < 30:
            reasons.append(f"RSI={ind.rsi14:.1f} 超卖，倾向多头")
        elif ind.rsi14 > 70:
            reasons.append(f"RSI={ind.rsi14:.1f} 超买，倾向空头")

        macd_score, macd_dir = self._score_macd(dif_arr, dea_arr, hist_arr)
        ss["macd"] = macd_score
        if ind.macd > 0 and dif_arr[-1] > dea_arr[-1]:
            reasons.append("MACD金叉/红柱放大，多头动能")
        elif ind.macd < 0 and dif_arr[-1] < dea_arr[-1]:
            reasons.append("MACD死叉/绿柱放大，空头动能")

        boll_score, boll_dir = self._score_boll(bb_u, bb_m, bb_l, closes)
        ss["boll"] = boll_score
        if ind.bb_position < 0.1:
            reasons.append("价格贴近布林下轨，支撑反弹可能")
        elif ind.bb_position > 0.9:
            reasons.append("价格贴近布林上轨，阻力回调可能")
        if ind.bb_width_pct > 0 and ind.bb_width_pct < 0.015:
            reasons.append("布林极度收窄，关注方向突破")

        atr_score, atr_dir, vol_confidence = self._score_atr(ind.atr_pct, timeframe)
        ss["atr"] = atr_score

        result.sub_scores = ss
        result.reasons = reasons

        # 3) 综合加权：score ∈ [0,10]
        total_w = sum(self.WEIGHTS.values()) or 1
        weighted = sum(ss[k] * self.WEIGHTS[k] for k in self.WEIGHTS) / total_w
        result.score = round(min(10.0, max(0.0, weighted)), 2)

        # 4) 方向分：每个指标的 dir * weight 求和
        dir_sum = sum(
            ({"ma": ma_dir, "rsi": rsi_dir, "macd": macd_dir, "boll": boll_dir, "atr": atr_dir}[k])
            * self.WEIGHTS[k] for k in self.WEIGHTS
        ) / total_w
        result.directional_score = round(dir_sum * 10, 2)   # -10..+10

        # 5) 方向决策 & 可信度
        if result.score >= 5.5 and result.directional_score >= 0.5:
            result.direction = 1
        elif result.score <= 4.5 and result.directional_score <= -0.5:
            result.direction = 2
        else:
            result.direction = 0
        # 波动率适中（ATR合理）则可信度高
        result.confidence = round(min(1.0, max(0.0, 0.5 + vol_confidence * 0.5)), 3)

        # 6) 建议杠杆(3-10)：根据 ATR%（波动率越高杠杆越低）
        lev = self._suggest_leverage(ind.atr_pct, timeframe)
        result.suggest_leverage = lev
        # 建议TP/SL
        result.suggest_tp_pct = max(3.0, min(8.0, 4.0 * (1 + (ind.atr_pct or 0) * 20)))
        result.suggest_sl_pct = max(1.5, min(4.0, 2.0 * (1 + (ind.atr_pct or 0) * 20)))
        return result

    # ============== 分项评分实现 ==============
    def _score_ma(self, ma7, ma25, ma99, closes):
        """均线趋势评分：均线多头=高分(多)，空头=低分(空)"""
        if len(closes) < 99:
            return 5.0, 0.0
        a = ma7[-1] - ma25[-1]
        b = ma25[-1] - ma99[-1]
        c = closes[-1] - ma7[-1]
        base = closes[-1] or 1
        # 归一化，每档距离给分
        long_strength = (max(a, 0) / base * 1000) + (max(b, 0) / base * 1000) + (max(c, 0) / base * 1000)
        short_strength = (max(-a, 0) / base * 1000) + (max(-b, 0) / base * 1000) + (max(-c, 0) / base * 1000)
        # 方向 [-1, 1]
        total = long_strength + short_strength
        direction = (long_strength - short_strength) / total if total > 0 else 0.0
        # 评分：多头强 → 高分，空头强 → 低分
        if direction >= 0:
            score = min(10.0, 5.0 + direction * 5.0)
        else:
            score = max(0.0, 5.0 + direction * 5.0)
        return round(score, 2), round(direction, 3)

    def _score_rsi(self, rsi_arr):
        """RSI 超买超卖 + 趋势"""
        val = rsi_arr[-1]
        if math.isnan(val):
            return 5.0, 0.0
        # 50为中性，两端极值 +2/-2 修正
        # 方向：30以下看多（反弹），70以上看空（回调）
        direction = 0.0
        if val < 30:
            direction = (30 - val) / 30          # 0~+1
        elif val > 70:
            direction = -(val - 70) / 30         # -1~0
        else:
            direction = (val - 50) / 50 * 0.4    # 中间轻微顺势
        # 分数：RSI越靠近50越"中性差"；极值（超卖多给分，超买少给分）
        if direction >= 0:
            score = min(10.0, 5.0 + direction * 5.0)
        else:
            score = max(0.0, 5.0 + direction * 5.0)
        return round(score, 2), round(direction, 3)

    def _score_macd(self, dif, dea, hist):
        """MACD: 金叉/红柱放大看多，死叉/绿柱放大看空"""
        if len(hist) < 3:
            return 5.0, 0.0
        h1, h2, h3 = hist[-3], hist[-2], hist[-1]
        # 趋势方向：hist >0 看多；hist 加速放大看多
        direction = 0.0
        if h3 > 0:
            direction = min(1.0, 0.4 + 0.3 * (h3 > h2) + 0.3 * (h2 > h1))
        else:
            direction = -min(1.0, 0.4 + 0.3 * (h3 < h2) + 0.3 * (h2 < h1))
        # DIF/DEA 相对0轴位置
        axis_bias = 0.0
        if dif[-1] > 0 and dea[-1] > 0:
            axis_bias = 0.2
        elif dif[-1] < 0 and dea[-1] < 0:
            axis_bias = -0.2
        direction += axis_bias
        direction = max(-1.0, min(1.0, direction))
        if direction >= 0:
            score = 5.0 + direction * 5.0
        else:
            score = 5.0 + direction * 5.0
        return round(min(10.0, max(0.0, score)), 2), round(direction, 3)

    def _score_boll(self, u, m, l, closes):
        """布林带位置 & 收窄"""
        if len(closes) < 20:
            return 5.0, 0.0
        pos = 0.5
        if u[-1] - l[-1] > 1e-12:
            pos = (closes[-1] - l[-1]) / (u[-1] - l[-1])
        pos = max(0.0, min(1.0, pos))
        # 位置偏离越极端越给反方向分
        direction = 0.0
        if pos < 0.2:
            direction = (0.2 - pos) / 0.2                # 超跌反弹：+方向
        elif pos > 0.8:
            direction = -(pos - 0.8) / 0.2               # 超涨回调：-方向
        else:
            # 区间顺势
            direction = (pos - 0.5) / 0.3 * 0.4
        direction = max(-1.0, min(1.0, direction))
        if direction >= 0:
            score = 5.0 + direction * 5.0
        else:
            score = 5.0 + direction * 5.0
        return round(min(10.0, max(0.0, score)), 2), round(direction, 3)

    def _score_atr(self, atr_pct: float, timeframe: str):
        """ATR 波动率只影响可信度和杠杆，不直接决定多空方向；
        给固定 7 分基础分；波动率极端(过高或过低)略降分"""
        # 典型 ATR% 范围 0.3% ~ 4%（根据 timeframe 缩放）
        expected = {"15m": 0.005, "1h": 0.012, "4h": 0.03, "1d": 0.06}.get(timeframe, 0.012)
        atr_pct = atr_pct or 0
        ratio = atr_pct / expected if expected > 0 else 1
        confidence = 1.0
        if ratio < 0.3:
            confidence = 0.6  # 过低，没有行情
        elif ratio > 3:
            confidence = 0.5  # 极高波动，风险大
        elif ratio > 1.5:
            confidence = 0.8
        score = 7.0 * confidence + 3.0 * 0.7   # 波动率只给 7 分基础
        return round(min(10.0, max(5.0, score)), 2), 0.0, confidence

    def _suggest_leverage(self, atr_pct: float, timeframe: str) -> int:
        expected = {"15m": 0.005, "1h": 0.012, "4h": 0.03, "1d": 0.06}.get(timeframe, 0.012)
        atr_pct = atr_pct or expected
        ratio = atr_pct / max(1e-9, expected)
        # ratio 低（低波动）给高杠杆；ratio 高（剧烈波动）低杠杆
        if ratio < 0.6:
            return 10
        elif ratio < 1.0:
            return 8
        elif ratio < 1.4:
            return 6
        elif ratio < 1.8:
            return 5
        elif ratio < 2.5:
            return 4
        else:
            return 3
