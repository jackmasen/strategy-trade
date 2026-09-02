# -*- coding: utf-8 -*-
r"""
黄金EMV策略信号生成器（V7最优参数集成版）
================================================
将回测脚本 test_xau_emv_strategy_v7.py 的10层过滤逻辑
封装为实时信号生成模块，供 StrategyScoringEngine 调用。

策略类型：趋势跟踪 + 量价配合
适用品种：XAU（黄金）、BTC、ETH 等趋势性强的资产
适用周期：4H（主趋势判断）
核心逻辑：
  ① EMV上穿Signal + 2根K线确认
  ② MA99近10根上升（大趋势多头）
  ③ Close > MA25 > MA99 多头排列
  ④ |EMV| ≥ 0.7σ 强度阈值
  ⑤ RSI ∈ [38, 68] 中段趋势
  ⑥ ATR/ATR120 ≤ 1.5x 波动率不过热
  ⑦ Close ≥ 过去20根65分位 强势突破
  ⑧ MA99近30根涨幅 ≥ 0.7% 斜率加速
  ⑨ Close > MA99 × 1.025 远离均线纠缠区
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from .indicators import sma, rsi, atr, emv, _nan_to_zero


@dataclass
class EMVSignalResult:
    """EMV策略信号结果"""
    signal: int = 0  # 0=无信号 1=做多 2=做空（当前只实现做多）
    score: float = 5.0  # 0-10，信号强度评分
    direction: float = 0.0  # -1..+1
    confidence: float = 0.0  # 0-1
    reasons: List[str] = field(default_factory=list)
    # 各层过滤结果（供调试/前端展示）
    filter_details: Dict[str, bool] = field(default_factory=dict)
    # 关键指标快照
    emv_value: float = 0.0
    emv_signal_line: float = 0.0
    emv_cross_up: bool = False
    ma25: float = 0.0
    ma99: float = 0.0
    rsi14: float = 0.0
    atr14: float = 0.0
    atr_vol_ratio: float = 0.0
    breakout_pctl: float = 0.0
    ma99_slope_pct: float = 0.0
    price_above_ma99_pct: float = 0.0
    # ⑩ 滚动历史胜率观察期
    recent_win_rate: Optional[float] = None
    recent_trade_count: int = 0


class EMVSignalGenerator:
    """
    EMV策略信号生成器

    用法：
        gen = EMVSignalGenerator()
        result = gen.generate(klines, symbol="XAU", timeframe="4h")
        if result.signal == 1:
            # 做多信号
    """

    # V7最优参数（Gap2.5%/MA0.7%组）
    DEFAULT_PARAMS = {
        "emv_period": 14,
        "signal_period": 3,
        "vol_divisor": 10_000_000.0,
        "confirm_bars": 2,
        "emv_lookback": 30,
        "emv_strength_std_mul": 0.7,
        "ma99_lookback": 10,
        "alignment_tol": 0.003,
        "rsi_low": 38.0,
        "rsi_high": 68.0,
        "atr_vol_max_ratio": 1.5,
        "atr_long_lookback": 120,
        "breakout_lookback": 20,
        "breakout_pctl": 65,
        "ma99_slope_lookback": 30,
        "ma99_slope_min_pct": 0.7,
        "price_above_ma99_min_pct": 2.5,
        # ⑩ 滚动历史胜率观察期：样本达 win_rate_min_trades 笔后才生效，
        #    避免冷启动阶段样本不足误判（交接文档 V8 建议）
        "win_rate_lookback": 24,
        "win_rate_min": 15.0,
        "win_rate_min_trades": 8,
    }

    def __init__(self, params: Optional[Dict] = None):
        p = {**self.DEFAULT_PARAMS}
        if params:
            p.update(params)
        self.p = p

    def generate(
        self,
        klines: Sequence,
        symbol: str = "XAU",
        timeframe: str = "4h",
        recent_win_rate: Optional[float] = None,
        recent_trade_count: int = 0,
    ) -> EMVSignalResult:
        """
        对最新K线生成EMV信号
        klines: 按时间正序的K线列表（dict或对象），至少200根
        recent_win_rate: 该品种滚动近 win_rate_lookback 笔的胜率(0-100)，由调用方查DB传入；
            样本不足 win_rate_min_trades 笔时观察期不生效（默认通过），避免冷启动误杀
        recent_trade_count: 已有历史平仓笔数，用于判断观察期是否生效
        """
        result = EMVSignalResult()
        need = max(
            self.p["emv_period"] + self.p["signal_period"] + 30,
            99 + self.p["ma99_lookback"],
            99 + self.p["ma99_slope_lookback"] + 5,
            self.p["atr_long_lookback"] + 30,
            self.p["breakout_lookback"] + 5,
            200,
        )
        n = len(klines)
        if n < need:
            result.reasons.append(f"K线不足({n} < {need})，无法生成EMV信号")
            return result

        # 提取数据
        highs = [_get(k, "high") for k in klines]
        lows = [_get(k, "low") for k in klines]
        closes = [_get(k, "close") for k in klines]
        vols = [_get(k, "volume") for k in klines]

        # 计算指标
        emv_arr, emv_sig = emv(
            highs, lows, vols,
            self.p["emv_period"], self.p["signal_period"], self.p["vol_divisor"],
        )
        ma25 = _nan_to_zero(sma(closes, 25))
        ma99 = _nan_to_zero(sma(closes, 99))
        atr14 = _nan_to_zero(atr(highs, lows, closes, 14))
        atr_long = _nan_to_zero(sma(atr14, self.p["atr_long_lookback"]))
        rsi14 = _nan_to_zero(rsi(closes, 14))

        i = n - 1  # 最新K线索引
        fd = result.filter_details

        # 快照关键指标
        result.emv_value = emv_arr[i]
        result.emv_signal_line = emv_sig[i]
        result.ma25 = ma25[i]
        result.ma99 = ma99[i]
        result.rsi14 = rsi14[i]
        result.atr14 = atr14[i]
        if atr_long[i] > 0:
            result.atr_vol_ratio = atr14[i] / atr_long[i]
        if ma99[i] > 0 and closes[i] > 0:
            result.price_above_ma99_pct = (closes[i] / ma99[i] - 1) * 100
        if i >= self.p["ma99_slope_lookback"] and ma99[i - self.p["ma99_slope_lookback"]] > 0:
            result.ma99_slope_pct = (ma99[i] / ma99[i - self.p["ma99_slope_lookback"]] - 1) * 100
        result.recent_win_rate = recent_win_rate
        result.recent_trade_count = recent_trade_count

        # ① EMV交叉 + confirm_bars根确认
        conf = self.p["confirm_bars"]
        k_idx = i - (conf - 1)
        cross_ok = (
            k_idx >= 1
            and emv_arr[k_idx - 1] <= emv_sig[k_idx - 1]
            and emv_arr[k_idx] > emv_sig[k_idx]
            and emv_arr[k_idx] > 0
        )
        confirm_ok = cross_ok and all(
            emv_arr[j] >= emv_sig[j] for j in range(k_idx, i + 1)
        )
        fd["1_emv_cross"] = bool(cross_ok)
        fd["1_emv_confirm"] = bool(confirm_ok)
        result.emv_cross_up = bool(cross_ok)

        if not confirm_ok:
            result.reasons.append("EMV未上穿Signal或确认不足")
            result.score = 5.0
            return result

        # ② MA99上升
        ma99_up = ma99[i] > 0 and ma99[i - self.p["ma99_lookback"]] > 0 and ma99[i] > ma99[i - self.p["ma99_lookback"]]
        fd["2_ma99_up"] = ma99_up
        if not ma99_up:
            result.reasons.append("MA99未上升，大趋势非多头")
            result.score = 4.5
            return result

        # ③ 多头排列
        align_ok = (
            ma25[i] > 0 and ma99[i] > 0 and closes[i] > ma25[i]
            and ma25[i] > ma99[i] * (1 - self.p["alignment_tol"])
        )
        fd["3_bull_alignment"] = align_ok
        if not align_ok:
            result.reasons.append("均线非多头排列")
            result.score = 4.8
            return result

        # ④ EMV强度
        if i >= self.p["emv_lookback"]:
            window = emv_arr[i - self.p["emv_lookback"] + 1: i + 1]
            m = sum(window) / len(window)
            var = sum((x - m) ** 2 for x in window) / len(window)
            std = var ** 0.5
            thresh = max(std * self.p["emv_strength_std_mul"], 1e-9)
            strength_ok = abs(emv_arr[i]) >= thresh
        else:
            strength_ok = True
        fd["4_emv_strength"] = strength_ok
        if not strength_ok:
            result.reasons.append("EMV强度不足")
            result.score = 4.8
            return result

        # ⑤ RSI中段
        rsi_ok = self.p["rsi_low"] <= rsi14[i] <= self.p["rsi_high"]
        fd["5_rsi_range"] = rsi_ok
        if not rsi_ok:
            result.reasons.append(f"RSI={rsi14[i]:.1f}不在[{self.p['rsi_low']},{self.p['rsi_high']}]")
            result.score = 4.5
            return result

        # ⑥ ATR波动率
        vol_ok = atr_long[i] > 0 and atr14[i] / atr_long[i] <= self.p["atr_vol_max_ratio"]
        fd["6_atr_vol"] = vol_ok
        if not vol_ok:
            result.reasons.append("ATR波动率过热")
            result.score = 4.5
            return result

        # ⑦ 突破分位
        if i >= self.p["breakout_lookback"]:
            window = sorted(closes[j] for j in range(i - self.p["breakout_lookback"], i))
            idx_p = max(0, min(int(len(window) * self.p["breakout_pctl"] / 100), len(window) - 1))
            p_thresh = window[idx_p]
            breakout_ok = closes[i] >= p_thresh
        else:
            breakout_ok = True
        fd["7_breakout"] = breakout_ok
        if not breakout_ok:
            result.reasons.append("未突破65分位")
            result.score = 4.8
            return result

        # ⑧ MA99斜率加速
        if i >= self.p["ma99_slope_lookback"] and ma99[i - self.p["ma99_slope_lookback"]] > 0:
            slope = ma99[i] / ma99[i - self.p["ma99_slope_lookback"]] - 1
            slope_ok = slope >= self.p["ma99_slope_min_pct"] / 100
        else:
            slope_ok = False
        fd["8_ma99_slope"] = slope_ok
        if not slope_ok:
            result.reasons.append(f"MA99斜率={result.ma99_slope_pct:.2f}%<{self.p['ma99_slope_min_pct']}%")
            result.score = 4.8
            return result

        # ⑨ Close远离MA99
        if ma99[i] > 0:
            gap = closes[i] / ma99[i] - 1
            gap_ok = gap >= self.p["price_above_ma99_min_pct"] / 100
        else:
            gap_ok = False
        fd["9_price_above_ma99"] = gap_ok
        if not gap_ok:
            result.reasons.append(f"价格距MA99仅{result.price_above_ma99_pct:.2f}%<{self.p['price_above_ma99_min_pct']}%")
            result.score = 4.8
            return result

        # ⑩ 滚动历史胜率观察期：样本达 win_rate_min_trades 笔后才生效，
        #    胜率 < win_rate_min% 则拦截（连续黑天鹅保护）；样本不足时默认通过
        if recent_trade_count >= self.p["win_rate_min_trades"]:
            winrate_ok = (
                recent_win_rate is not None
                and recent_win_rate >= self.p["win_rate_min"]
            )
            fd["10_win_rate_observe"] = winrate_ok
            if not winrate_ok:
                result.reasons.append(
                    f"滚动{recent_trade_count}笔胜率"
                    f"{recent_win_rate:.1f}%<{self.p['win_rate_min']}%观察期拦截"
                )
                result.score = 4.5
                return result
        else:
            # 样本不足，观察期不生效
            fd["10_win_rate_observe"] = True

        # ====== 全部10层通过 → 做多信号 ======
        result.signal = 1
        result.direction = 0.8
        result.confidence = 0.75
        result.score = 7.5  # 高于默认5.0触发阈值

        # 根据过滤层通过数量动态提升评分
        passed = sum(1 for v in fd.values() if v)
        if passed >= 10:
            result.score = 8.0
            result.confidence = 0.85
        result.reasons.append(
            f"EMV策略信号：10层过滤全部通过 → 做多 | "
            f"EMV={emv_arr[i]:.4f}>Sig={emv_sig[i]:.4f} | "
            f"MA99斜率={result.ma99_slope_pct:.2f}% | "
            f"Gap={result.price_above_ma99_pct:.2f}% | "
            f"RSI={rsi14[i]:.1f}"
        )
        return result


def _get(k, field: str) -> float:
    """从 dict 或对象中提取字段"""
    if isinstance(k, dict):
        v = k.get(field, k.get(field[0], 0))
        try:
            return float(v) if v is not None else 0.0
        except (TypeError, ValueError):
            return 0.0
    try:
        return float(getattr(k, field, 0))
    except (TypeError, ValueError):
        return 0.0
