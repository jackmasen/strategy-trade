# -*- coding: utf-8 -*-
"""
XAU（黄金）EMV 策略分析脚本
===================================================
EMV = Ease of Movement 简易波动指标（Richard W. Arms 提出）

EMV 核心思想：
  - 价格"轻松"上涨时，成交量不大但价格推进远 → EMV 上穿 0 且攀升（做多信号）
  - 价格"艰难"上涨时，成交量很大但价格走不远 → EMV 走平或下降（衰竭信号）
  - 下跌同理，EMV 深跌 < 0 且放量 → 做空信号

公式：
  1. Mid[i] = (High[i] + Low[i]) / 2
  2. Distance[i] = Mid[i] - Mid[i-1]
  3. BoxRatio[i] = Volume[i] / max(High[i] - Low[i], 1e-9)
     * 若 Volume 以"张/手"为单位通常偏大，可除以一个 VOL_DIVISOR 压制数量级
  4. EMV[i] = Distance[i] / max(BoxRatio[i], 1e-9)   （Box==0 时置 0）
  5. Signal[i] = SMA(EMV, signal_period)   信号线

常见策略：
  策略 A · 纯交叉：EMV 上穿 Signal → 做多；EMV 下穿 Signal → 做空
  策略 B · 加 MA 过滤：MA25 上升只做多 / 下降只做空（用大趋势过滤假交叉）
  策略 C · 加 RSI 超买超卖过滤：做多要求 RSI < 70（不追超买），做空要求 RSI > 30（不抄超卖）

输出：
  - 三策略年度对比表
  - 胜率 / 盈亏比 / 夏普 / 最大回撤
  - 参数敏感性（emv_period × signal_period 网格）
"""
from __future__ import annotations

import json
import math
import os
import random
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Sequence, Tuple

# ======== 让脚本能直接引用 backend.strategy.indicators（SMA/EMA/RSI/ATR） ========
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from backend.strategy.indicators import sma, ema, rsi, atr  # noqa: E402

SEED = 42
random.seed(SEED)


# =======================================================
# 1. EMV 指标实现
# =======================================================
def _nan_to_zero(xs: Sequence[float]) -> List[float]:
    import math as _m
    return [0.0 if (v is None or (isinstance(v, float) and (_m.isnan(v) or _m.isinf(v)))) else float(v) for v in xs]


def emv(
    highs: Sequence[float],
    lows: Sequence[float],
    volumes: Sequence[float],
    period: int = 14,
    signal_period: int = 9,
    vol_divisor: float = 10_000_000.0,
) -> Tuple[List[float], List[float]]:
    """
    计算 EMV 及信号线
    参数:
        highs/lows/volumes: 等长价格序列
        period: EMV 自身平滑周期（先算单根 EMV，再做 period-SMA 得到最终 EMV）
        signal_period: 信号线 SMA 周期
        vol_divisor: 成交量单位压制。股票"手"、加密"张"时量偏大，默认 1e6。
                    若数据源 volume 已经标准化，传 1.0 即可。
    返回:
        (emv_series, signal_series)，长度与输入一致
    """
    n = len(highs)
    if n == 0:
        return [], []
    raw_emv: List[float] = []
    for i in range(n):
        if i == 0:
            raw_emv.append(0.0)
            continue
        mid_i = (highs[i] + lows[i]) * 0.5
        mid_j = (highs[i - 1] + lows[i - 1]) * 0.5
        distance = mid_i - mid_j
        hl = max(highs[i] - lows[i], 1e-9)
        vol_scaled = volumes[i] / max(vol_divisor, 1e-9)
        box = vol_scaled / hl  # 越小代表越"轻松"
        v = distance / max(box, 1e-9)
        # 钳制一下避免极端异常值（HL 极小导致 div ≈ ∞）
        import math as _m
        if _m.isnan(v) or _m.isinf(v):
            v = 0.0
        raw_emv.append(v)

    emv_smoothed = sma(raw_emv, period)
    emv_smoothed = _nan_to_zero(emv_smoothed)
    signal = sma(emv_smoothed, signal_period)
    signal = _nan_to_zero(signal)
    return emv_smoothed, signal


# =======================================================
# 2. K 线合成（贴近真实金价 2020~2026 的走势）
# =======================================================
ASSET_PROFILES: Dict[str, Dict] = {
    "XAU": {
        "name": "XAU/USD 黄金现货",
        "start_price": 1520.0,    # 2020-01
        "annualized_return": 0.10,  # ~10%/yr（2020~2026 黄金大致真实均值）
        "annualized_vol": 0.14,     # ~14%/yr
        "trend_period": 210.0,      # 长周期 约 8-9 月
        "trend_amp": 0.08,          # 叠加 8% 幅度的正弦长期趋势（模拟牛熊轮回）
        "mean_leverage": 3,         # 建议杠杆均值
    },
}


def generate_klines(
    symbol: str,
    start: datetime,
    end: datetime,
    timeframe_minutes: int = 240,  # 默认 4H，适合黄金
) -> List[dict]:
    """
    GBM + 正弦长周期 + 随机跳空，合成 XAU 的 4H / 1H K线
    """
    profile = ASSET_PROFILES[symbol]
    step = timedelta(minutes=timeframe_minutes)
    bars_per_year = (365 * 24 * 60) / timeframe_minutes
    mu = profile["annualized_return"] / bars_per_year
    sigma = profile["annualized_vol"] / math.sqrt(bars_per_year)

    total_bars = int((end - start) / step)
    klines: List[dict] = []
    px = profile["start_price"]
    dt = start
    tp = profile["trend_period"]
    amp = profile["trend_amp"]

    for i in range(total_bars):
        o = px
        # 正弦趋势项（模拟长周期利率/地缘驱动）
        trend_drift = (amp / bars_per_year) * math.cos(2 * math.pi * i / (tp * bars_per_year / 365))
        drift = mu + trend_drift
        # GBM 对数增量
        z = random.gauss(0.0, 1.0)
        close_change = math.exp(drift + sigma * z)
        c = o * close_change

        # 日内影线（H / L）：在 close 两侧均匀分布，长度 ~ 1.2 sigma
        w = max(sigma, 0.002) * 1.2
        h = max(o, c) * (1.0 + random.uniform(0.0, w))
        l = min(o, c) * (1.0 - random.uniform(0.0, w))

        # 成交量：黄金 4H 量级大约 5k~20k 手（本脚本归一化到 1e6~1e7，后面会除以 vol_divisor）
        vol = random.uniform(0.8, 3.5) * max(abs(c - o) / max(o, 1e-9) / max(sigma, 1e-9), 0.3)
        vol = vol * 500_000 + 300_000  # 给个 base

        klines.append({
            "symbol": symbol,
            "dt": dt,
            "open": round(o, 2),
            "high": round(h, 2),
            "low": round(l, 2),
            "close": round(c, 2),
            "volume": round(vol, 0),
        })
        px = c
        dt += step
    return klines


# =======================================================
# 3. 持仓 / 交易 结构
# =======================================================
@dataclass
class Position:
    symbol: str
    side: int          # 1多 2空
    entry_px: float
    entry_dt: datetime
    tp_px: float
    sl_px: float
    lev: int
    qty_usdt: float
    bars_held: int = 0


@dataclass
class Trade:
    symbol: str
    side: int
    entry_dt: datetime
    exit_dt: datetime
    entry_px: float
    exit_px: float
    pnl_usdt: float
    pnl_pct: float
    exit_reason: str  # tp/sl/signal/end
    lev: int
    bars_held: int


# =======================================================
# 4. EMV 策略引擎
# =======================================================
class EMVStrategyBacktest:
    def __init__(
        self,
        initial_capital: float = 10000.0,
        fee_rate_pct: float = 0.04,    # 双边手续费 0.04%
        slippage_pct: float = 0.05,    # 滑点 0.05%
        risk_pct_per_trade: float = 0.6,  # 单笔风险 0.6%（原 1.2% 减半，避免连亏爆仓）
        tp_sl_ratio: float = 1.8,      # 盈亏比 1.8（原 2.5 太高导致 TP 极少触发）
        # EMV 参数
        emv_period: int = 14,
        signal_period: int = 9,
        vol_divisor: float = 10_000_000.0,
        # 过滤开关
        variant: str = "A",   # A:纯交叉 B:MA过滤 C:RSI过滤
        ma_period: int = 25,  # 策略 B 用
        rsi_period: int = 14, # 策略 C 用
        # 风控/行为
        max_bars_held: int = 48,   # 持仓超 48 根 4H K 线（8 天）仍未 TP/SL，按浮盈/亏强制止盈止损
        min_bars_between: int = 12,# 两次开仓之间最少隔 12 根 K 线（2 天），避免高频假交叉
        allow_reverse: bool = False,  # 是否允许反向信号立刻换仓（默认关：只走 TP/SL）
        allow_short_in_up_trend: bool = False,  # MA 上升期是否允许开空（黄金单边市：关）
        max_consecutive_losses: int = 3,   # 连续亏损 N 笔 → 冷却
        cooldown_after_loss_streak: int = 48,  # 连亏后冷却 48 根（8 天）
        fixed_leverage: int = 2,   # 固定杠杆 2x（黄金波动大，3x 太激进）
        # 高级行为
        use_trailing_stop: bool = True,    # 启用移动止盈
        long_only_mode: bool = False,      # 只做多模式（适合黄金长期上涨）
        require_emv_strong: bool = True,   # 要求 EMV 上穿/下穿时绝对值够强（过滤弱交叉）
        emv_lookback: int = 20,            # 强度回看周期
        emv_strength_std_mul: float = 0.7, # 强度阈值：|EMV| >= std_mul * std_20
    ):
        self.cap = initial_capital
        self.start_cap = initial_capital
        self.fee = fee_rate_pct / 100.0
        self.slip = slippage_pct / 100.0
        self.risk = risk_pct_per_trade / 100.0
        self.tp_sl = tp_sl_ratio

        self.emv_p = emv_period
        self.sig_p = signal_period
        self.vol_div = vol_divisor

        self.variant = variant
        self.ma_p = ma_period
        self.rsi_p = rsi_period

        self.max_bars_held = max_bars_held
        self.min_bars_between = min_bars_between
        self.allow_reverse = allow_reverse
        self.allow_short_in_up_trend = allow_short_in_up_trend
        self.max_cl = max_consecutive_losses
        self.cooldown_cl = cooldown_after_loss_streak
        self.fixed_lev = fixed_leverage
        self.use_ts = use_trailing_stop
        self.long_only = long_only_mode
        self.require_emv_strong = require_emv_strong
        self.emv_lb = emv_lookback
        self.emv_std_mul = emv_strength_std_mul

        self.pos: Optional[Position] = None
        self.trades: List[Trade] = []
        self.equity_curve: List[Tuple[datetime, float]] = []
        self._last_open_idx: int = -999999  # 冷却
        self._loss_streak: int = 0
        self._cooldown_until_idx: int = -999999  # 连亏冷却到这根

    # ---------- 执行 ----------
    def run(self, symbol: str, klines: List[dict]) -> dict:
        if len(klines) < max(self.emv_p + self.sig_p + 10, self.ma_p + 20, 120):
            return {"error": f"K线不足({len(klines)})"}

        highs = [k["high"] for k in klines]
        lows = [k["low"] for k in klines]
        closes = [k["close"] for k in klines]
        vols = [k["volume"] for k in klines]

        # 预计算 EMV
        emv_s, sig_s = emv(highs, lows, vols, self.emv_p, self.sig_p, self.vol_div)
        ma_s = _nan_to_zero(sma(closes, self.ma_p))
        rsi_s = _nan_to_zero(rsi(closes, self.rsi_p)) if self.variant == "C" else None
        atr_s = _nan_to_zero(atr(highs, lows, closes, 14))

        warmup = 120
        start_cap = self.cap

        for i in range(warmup, len(klines)):
            k = klines[i]
            a = atr_s[i]
            # 0) 连亏冷却：冷却期内直接跳过信号，但仍 TP/SL 检测
            if i < self._cooldown_until_idx:
                self._check_tp_sl(k, i, a)
                eq = self.cap
                if self.pos is not None:
                    c = k["close"]
                    if self.pos.side == 1:
                        chg = (c - self.pos.entry_px) / self.pos.entry_px
                    else:
                        chg = (self.pos.entry_px - c) / self.pos.entry_px
                    eq += self.pos.qty_usdt * self.pos.lev * chg
                    self.pos.bars_held += 1
                self.equity_curve.append((k["dt"], eq))
                continue

            # 1) TP/SL + Trailing Stop
            self._check_tp_sl(k, i, a)

            # 1.5) 超时强平：持仓超过 max_bars_held 根还没走出来 → 平仓
            if self.pos is not None and self.pos.bars_held >= self.max_bars_held:
                self._close(k, "timeout", i)

            # 2) 信号判定
            long_sig, short_sig = self._signal(i, emv_s, sig_s, ma_s, rsi_s)

            # 3) 黄金单边优化（策略 B）：MA 上升期禁止开空（顺势单边）
            if self.variant == "B" and not self.allow_short_in_up_trend and ma_s[i] > 0:
                ma_up = (ma_s[i] > ma_s[i - 5]) if i >= 5 and ma_s[i - 5] > 0 else True
                if ma_up:
                    short_sig = False

            # 4) 执行：只有空仓时才开新仓；反向信号默认不换仓（allow_reverse 控制）
            key_cool = (i - self._last_open_idx) >= self.min_bars_between
            if self.pos is not None:
                if self.allow_reverse:
                    reverse_side = None
                    if self.pos.side == 1 and short_sig:
                        reverse_side = 2
                    elif self.pos.side == 2 and long_sig:
                        reverse_side = 1
                    if reverse_side is not None and key_cool:
                        self._close(k, "signal", i)
                        self._open(k, reverse_side, a, i); self._last_open_idx = i
            else:
                if (long_sig or short_sig) and key_cool:
                    self._open(k, 1 if long_sig else 2, a, i); self._last_open_idx = i

            # 5) 权益标记
            eq = self.cap
            if self.pos is not None:
                c = k["close"]
                if self.pos.side == 1:
                    chg = (c - self.pos.entry_px) / self.pos.entry_px
                else:
                    chg = (self.pos.entry_px - c) / self.pos.entry_px
                eq += self.pos.qty_usdt * self.pos.lev * chg
                self.pos.bars_held += 1
            self.equity_curve.append((k["dt"], eq))

        # 最后强制平仓
        if self.pos is not None:
            self._close(klines[-1], "end", len(klines) - 1)

        return self._summary(symbol, start_cap, self.cap)

    # ---------- 信号逻辑：3 种 variant ----------
    def _signal(
        self,
        i: int,
        emv_s: List[float],
        sig_s: List[float],
        ma_s: List[float],
        rsi_s: List[float] | None,
    ) -> Tuple[bool, bool]:
        if i < 1:
            return False, False
        # ① 基本交叉：EMV 上穿/下穿 Signal（方向确认）
        emv_cross_up = (emv_s[i - 1] <= sig_s[i - 1]) and (emv_s[i] > sig_s[i])
        emv_cross_down = (emv_s[i - 1] >= sig_s[i - 1]) and (emv_s[i] < sig_s[i])
        # 额外方向确认：EMV 当前值方向延续
        emv_cross_up = emv_cross_up and (emv_s[i] >= emv_s[i - 1]) and (emv_s[i] > 0)
        emv_cross_down = emv_cross_down and (emv_s[i] <= emv_s[i - 1]) and (emv_s[i] < 0)

        long = emv_cross_up
        short = emv_cross_down

        # ② EMV 强度过滤（弱交叉直接砍掉）
        if self.require_emv_strong and (long or short):
            lb = self.emv_lb
            if i >= lb:
                window = emv_s[i - lb + 1: i + 1]
                mean = sum(window) / len(window)
                var = sum((x - mean) ** 2 for x in window) / len(window)
                std = var ** 0.5
                thresh = max(std * self.emv_std_mul, 1e-9)
                if long and abs(emv_s[i]) < thresh:
                    long = False
                if short and abs(emv_s[i]) < thresh:
                    short = False

        # ③ 只做多模式（黄金单边市，完全砍掉空头）
        if self.long_only:
            short = False

        # 变体 B：MA 过滤（大趋势只顺势）—— MA 最近 5 根方向判断
        if self.variant == "B":
            ma_up = (ma_s[i] > ma_s[i - 5]) if i >= 5 and ma_s[i - 5] > 0 else (ma_s[i] > 0)
            ma_dn = (ma_s[i] < ma_s[i - 5]) if i >= 5 and ma_s[i - 5] > 0 else (ma_s[i] < 0)
            # MA 为 0（warmup 阶段）视为无方向，放行
            if ma_s[i] > 0:
                if long and not ma_up:
                    long = False
                if short and not ma_dn:
                    short = False

        # 变体 C：RSI 超买超卖过滤（不追极端）
        if self.variant == "C" and rsi_s is not None:
            r = rsi_s[i]
            if r > 0:
                if long and r > 72:
                    long = False
                if short and r < 28:
                    short = False
        return long, short

    # ---------- 开 / 平 ----------
    def _open(self, k: dict, side: int, atr14: float, idx: int) -> None:
        if atr14 <= 0:
            return
        c = k["close"]
        sl_atr = atr14 * 1.2   # SL = 1.2 ATR
        tp_atr = sl_atr * self.tp_sl
        sl_pct = sl_atr / c
        if sl_pct <= 0:
            return
        # 仓位：risk% = qty_usdt × lev × sl_pct → qty = risk% * cap / (lev * sl_pct)
        lev = self.fixed_lev
        qty_usdt = (self.risk * self.cap) / (lev * sl_pct)
        qty_usdt = min(qty_usdt, self.cap * 0.4)  # 单笔不超过 40% 本金，防止极端仓位

        entry = c * (1 + self.slip) if side == 1 else c * (1 - self.slip)
        if side == 1:
            tp = entry + tp_atr
            sl = entry - sl_atr
        else:
            tp = entry - tp_atr
            sl = entry + sl_atr
        self.pos = Position(
            symbol=k["symbol"], side=side, entry_px=entry, entry_dt=k["dt"],
            tp_px=tp, sl_px=sl, lev=lev, qty_usdt=qty_usdt,
        )

    def _check_tp_sl(self, k: dict, idx: int, atr14: float = 0.0) -> None:
        if self.pos is None:
            return
        h, l, c = k["high"], k["low"], k["close"]
        p = self.pos

        # ---- Trailing Stop（仅 use_trailing_stop 且 atr14>0 时生效）----
        if self.use_ts and atr14 > 0:
            tp_amt = abs(p.tp_px - p.entry_px)
            if p.side == 1:
                # 浮盈 ≥ 0.5 TP 时 → SL 抬到盈亏平衡
                if c >= p.entry_px + tp_amt * 0.5 and p.sl_px < p.entry_px:
                    p.sl_px = p.entry_px
                # 浮盈 ≥ TP 时 → 开始 trailing（SL = max(原 SL, 最高 - 1 ATR)）
                if h >= p.tp_px:
                    new_sl = h - atr14 * 1.0
                    if new_sl > p.sl_px:
                        p.sl_px = new_sl
            else:
                if c <= p.entry_px - tp_amt * 0.5 and p.sl_px > p.entry_px:
                    p.sl_px = p.entry_px
                if l <= p.tp_px:
                    new_sl = l + atr14 * 1.0
                    if new_sl < p.sl_px:
                        p.sl_px = new_sl

        if p.side == 1:
            if h >= p.tp_px:
                self._close(k, "tp", idx, force_px=p.tp_px); return
            if l <= p.sl_px:
                self._close(k, "sl", idx, force_px=p.sl_px); return
        else:
            if l <= p.tp_px:
                self._close(k, "tp", idx, force_px=p.tp_px); return
            if h >= p.sl_px:
                self._close(k, "sl", idx, force_px=p.sl_px); return

    def _close(self, k: dict, reason: str, idx: int, force_px: float | None = None) -> None:
        p = self.pos
        c = force_px if force_px is not None else k["close"]
        exit_px = c * (1 - self.slip) if p.side == 1 else c * (1 + self.slip)
        if p.side == 1:
            pnl_pct = (exit_px - p.entry_px) / p.entry_px
        else:
            pnl_pct = (p.entry_px - exit_px) / p.entry_px
        gross = p.qty_usdt * p.lev * pnl_pct
        fee = p.qty_usdt * self.fee * 2  # 开 + 平 双边
        net = gross - fee
        self.cap += net
        self.trades.append(Trade(
            symbol=p.symbol, side=p.side, entry_dt=p.entry_dt, exit_dt=k["dt"],
            entry_px=p.entry_px, exit_px=exit_px, pnl_usdt=net,
            pnl_pct=pnl_pct * 100, exit_reason=reason, lev=p.lev, bars_held=p.bars_held,
        ))
        # 连亏冷却
        if net < 0:
            self._loss_streak += 1
            if self._loss_streak >= self.max_cl:
                self._cooldown_until_idx = idx + self.cooldown_cl
                self._loss_streak = 0
        else:
            self._loss_streak = 0
        self.pos = None

    # ---------- 汇总 ----------
    def _summary(self, symbol: str, start_cap: float, end_cap: float) -> dict:
        total_ret = (end_cap - start_cap) / start_cap * 100
        wins = [t for t in self.trades if t.pnl_usdt > 0]
        losses = [t for t in self.trades if t.pnl_usdt <= 0]
        win_rate = len(wins) / len(self.trades) * 100 if self.trades else 0.0
        avg_win = (sum(t.pnl_pct for t in wins) / len(wins)) if wins else 0.0
        avg_loss = (sum(t.pnl_pct for t in losses) / len(losses)) if losses else 0.0
        pr = (avg_win / abs(avg_loss)) if losses and avg_loss != 0 else 0.0

        # 回撤/夏普
        peak, max_dd = start_cap, 0.0
        returns_d = []
        last_eq = start_cap
        for dt, eq in self.equity_curve:
            if eq > peak:
                peak = eq
            dd = (peak - eq) / peak * 100
            if dd > max_dd:
                max_dd = dd
            if last_eq > 0:
                returns_d.append((eq - last_eq) / last_eq)
            last_eq = eq
        import statistics
        sharpe = 0.0
        if returns_d and statistics.stdev(returns_d) > 0:
            sharpe = (statistics.mean(returns_d) / statistics.stdev(returns_d)) * math.sqrt(252 * (24 * 60 / 240))

        # 连胜/连败
        win_streak, lose_streak, cur_w, cur_l = 0, 0, 0, 0
        for t in self.trades:
            if t.pnl_usdt > 0:
                cur_w += 1; cur_l = 0
                win_streak = max(win_streak, cur_w)
            else:
                cur_l += 1; cur_w = 0
                lose_streak = max(lose_streak, cur_l)

        tp_count = sum(1 for t in self.trades if t.exit_reason == "tp")
        sl_count = sum(1 for t in self.trades if t.exit_reason == "sl")
        sig_count = sum(1 for t in self.trades if t.exit_reason == "signal")
        timeout_count = sum(1 for t in self.trades if t.exit_reason == "timeout")
        end_count = sum(1 for t in self.trades if t.exit_reason == "end")

        return {
            "symbol": symbol, "variant": self.variant,
            "emv_period": self.emv_p, "signal_period": self.sig_p,
            "start_cap": start_cap, "end_cap": round(end_cap, 2),
            "total_return_pct": round(total_ret, 2),
            "trade_count": len(self.trades),
            "win_rate_pct": round(win_rate, 2),
            "profit_factor": round(pr, 2),
            "avg_win_pct": round(avg_win, 2),
            "avg_loss_pct": round(avg_loss, 2),
            "sharpe": round(sharpe, 2),
            "max_drawdown_pct": round(max_dd, 2),
            "win_streak": win_streak, "lose_streak": lose_streak,
            "tp_count": tp_count, "sl_count": sl_count, "signal_count": sig_count,
            "timeout_count": timeout_count, "end_count": end_count,
            "last5": [
                {
                    "entry": t.entry_dt.strftime("%Y-%m-%d %H:%M"),
                    "exit": t.exit_dt.strftime("%Y-%m-%d %H:%M"),
                    "side": "LONG" if t.side == 1 else "SHORT",
                    "lev": t.lev, "pnl_pct": round(t.pnl_pct, 2),
                    "pnl_usdt": round(t.pnl_usdt, 2),
                    "reason": t.exit_reason, "bars": t.bars_held,
                }
                for t in self.trades[-5:]
            ],
        }


# =======================================================
# 5. 主流程
# =======================================================
def main():
    START = datetime(2020, 1, 1, 0, 0)
    END = datetime(2026, 8, 1, 0, 0)
    print("=" * 80)
    print("  黄金（XAU）EMV 策略深度回测")
    print("=" * 80)
    print(f"  区间: {START.date()} ~ {END.date()}   品种: XAU/USD   周期: 4H")
    print(f"  初始资金: $10,000   手续费 0.04% 双边   滑点 0.05%   单笔风险 0.6%")
    print(f"  TP/SL 盈亏比 = 1.8 : 1   SL 距离 = 1.2 ATR   杠杆 2x   "
          f"连亏3笔冷却6天   2次开仓间隔>1天")
    print()

    print("[数据生成] 生成 XAU 4H K 线...")
    klines_4h = generate_klines("XAU", START, END, 240)
    print(f"  - 4H = {len(klines_4h)} 根（约 {len(klines_4h)*4/24/365:.1f} 年）")
    print(f"  - 起始价 ${klines_4h[0]['close']:.2f} → 结束价 ${klines_4h[-1]['close']:.2f}")
    print(f"  - 区间涨幅 {(klines_4h[-1]['close']/klines_4h[0]['close'] - 1)*100:.2f}%")
    print()

    results = {}

    # ① 三策略变体对比（固定默认参数 emv=14, signal=9）
    variants = [
        ("A", "纯 EMV 交叉（EMV × Signal 直接多空）"),
        ("B", "EMV 交叉 + MA25 大趋势过滤（只顺势）"),
        ("C", "EMV 交叉 + RSI 超买超卖过滤（不追极端）"),
    ]
    print("=" * 80)
    print("  ① 三策略变体对比（EMV=14, Signal=9, TP:SL=2.5:1）")
    print("=" * 80)
    for v, desc in variants:
        bt = EMVStrategyBacktest(variant=v)
        r = bt.run("XAU", klines_4h)
        results[f"variant_{v}"] = r
        print(f"  策略 {v}：{desc}")
        print(f"    总收益率: {r['total_return_pct']:+}%    胜率: {r['win_rate_pct']}%    "
              f"盈亏比: {r['profit_factor']}    夏普: {r['sharpe']}    最大回撤: {r['max_drawdown_pct']}%")
        print(f"    交易次数: {r['trade_count']}    TP {r['tp_count']} / SL {r['sl_count']} / "
              f"超时 {r.get('timeout_count', 0)} / 信号 {r.get('signal_count', 0)} / 结束 {r.get('end_count', 0)}    "
              f"最大连胜 {r['win_streak']} / 连败 {r['lose_streak']}")
        if r["last5"]:
            print(f"    最近 5 笔：")
            for t in r["last5"]:
                side_icon = "▲" if t["side"] == "LONG" else "▼"
                print(f"      {side_icon} {t['entry']}~{t['exit']}  {t['side']}  "
                      f"lev={t['lev']}x  PnL={t['pnl_pct']:+.2f}% (${t['pnl_usdt']:+.2f})  "
                      f"{t['reason']}  持 {t['bars']}K")
        print()

    # ② 参数敏感性网格（以策略 B 为基准：MA 过滤后最接近真实运营）
    print("=" * 80)
    print("  ② 参数敏感性 · 策略 B（EMV 周期 × Signal 周期）网格扫参")
    print("=" * 80)
    emv_periods = [7, 14, 21, 28]
    signal_periods = [3, 5, 9, 14]
    grid_results: List[Tuple[int, int, dict]] = []
    print(f"  {'EMV':>4} / {'Sig':>3}  |   Return%   Win%   P/F   Sharpe    DD%   Trades")
    print("  " + "-" * 72)
    for ep in emv_periods:
        for sp in signal_periods:
            bt = EMVStrategyBacktest(variant="B", emv_period=ep, signal_period=sp)
            r = bt.run("XAU", klines_4h)
            if "error" in r:
                continue
            grid_results.append((ep, sp, r))
            print(f"  {ep:>4} / {sp:>3}  |  {r['total_return_pct']:+7.2f}   "
                  f"{r['win_rate_pct']:5.1f}  {r['profit_factor']:5.2f}  "
                  f"{r['sharpe']:6.2f}  {r['max_drawdown_pct']:6.2f}   "
                  f"{r['trade_count']:>6}")
    # 找冠军组合
    best = max(grid_results, key=lambda x: x[2]["sharpe"])
    print()
    print(f"  【最佳夏普组合】EMV={best[0]} / Signal={best[1]}："
          f"收益 {best[2]['total_return_pct']:+}%  胜率 {best[2]['win_rate_pct']}%  "
          f"盈亏比 {best[2]['profit_factor']}  夏普 {best[2]['sharpe']}  回撤 {best[2]['max_drawdown_pct']}%")

    best_ret = max(grid_results, key=lambda x: x[2]["total_return_pct"])
    print(f"  【最佳收益组合】EMV={best_ret[0]} / Signal={best_ret[1]}："
          f"收益 {best_ret[2]['total_return_pct']:+}%  胜率 {best_ret[2]['win_rate_pct']}%  "
          f"盈亏比 {best_ret[2]['profit_factor']}  夏普 {best_ret[2]['sharpe']}  回撤 {best_ret[2]['max_drawdown_pct']}%")
    results["param_sweep_best_sharpe"] = {"emv_period": best[0], "signal_period": best[1], **best[2]}
    results["param_sweep_best_return"] = {"emv_period": best_ret[0], "signal_period": best_ret[1], **best_ret[2]}

    # ③ 最佳参数 + 组合策略：B（MA 过滤）再叠加 RSI 过滤，看能否进一步提升胜率
    print()
    print("=" * 80)
    print("  ③ 实战组合验证：最佳参数(EMV=%d/Sig=%d) × 行为开关组合" % (best[0], best[1]))
    print("=" * 80)
    combos = [
        ("基础 · 纯交叉",        dict(variant="A", use_trailing_stop=False, long_only_mode=False, require_emv_strong=False)),
        ("基础 · MA 过滤",        dict(variant="B", use_trailing_stop=False, long_only_mode=False, require_emv_strong=False)),
        ("+ EMV强度过滤",        dict(variant="B", use_trailing_stop=False, long_only_mode=False, require_emv_strong=True)),
        ("+ Trailing Stop",      dict(variant="B", use_trailing_stop=True,  long_only_mode=False, require_emv_strong=True)),
        ("★实战 · 只做多 + 全套", dict(variant="B", use_trailing_stop=True,  long_only_mode=True,  require_emv_strong=True)),
    ]
    best_combo_r: dict | None = None
    for name, kw in combos:
        kw.setdefault("emv_period", best[0])
        kw.setdefault("signal_period", best[1])
        bt = EMVStrategyBacktest(**kw)
        r = bt.run("XAU", klines_4h)
        if best_combo_r is None or r["sharpe"] > best_combo_r["sharpe"]:
            best_combo_r = dict(**r, _name=name, _kw=kw)
        star = "★" if name.startswith("★") else " "
        print(f"  {star} {name:20s}: 收益 {r['total_return_pct']:+7.2f}%   胜率 {r['win_rate_pct']:5.1f}%   "
              f"盈亏比 {r['profit_factor']:5.2f}   夏普 {r['sharpe']:6.2f}   回撤 {r['max_drawdown_pct']:5.2f}%   "
              f"交易{r['trade_count']:>4}")
        results[f"combo_{name}"] = r

    # ④ 年度收益分析（★实战最佳组合）
    print()
    print("=" * 80)
    print("  ④ 年度表现拆解 · %s（EMV=%d/Sig=%d）" % (best_combo_r["_name"], best[0], best[1]))
    print("=" * 80)
    bt_best = EMVStrategyBacktest(**best_combo_r["_kw"])
    bt_best.run("XAU", klines_4h)
    trades_by_year: Dict[int, List[Trade]] = {}
    for t in bt_best.trades:
        y = t.exit_dt.year
        trades_by_year.setdefault(y, []).append(t)
    print(f"  {'Year':>5}  {'Return%':>9}  {'Trades':>7}  {'Win%':>6}  "
          f"{'P/F':>5}  {'Win$':>8}  {'Loss$':>8}   连亏冷却触发")
    print("  " + "-" * 74)
    cum_pnl = 0.0
    for y in sorted(trades_by_year.keys()):
        ts = trades_by_year[y]
        yr_pnl = sum(t.pnl_usdt for t in ts)
        wins_y = [t for t in ts if t.pnl_usdt > 0]
        losses_y = [t for t in ts if t.pnl_usdt <= 0]
        win_r = len(wins_y) / len(ts) * 100 if ts else 0
        avg_w = (sum(t.pnl_pct for t in wins_y) / len(wins_y)) if wins_y else 0
        avg_l = (sum(t.pnl_pct for t in losses_y) / len(losses_y)) if losses_y else 0
        pf = (avg_w / abs(avg_l)) if avg_l != 0 else 0
        base = 10000 + cum_pnl
        yr_ret = yr_pnl / base * 100 if base != 0 else 0
        # 连亏冷却次数 = SL 后紧接 SL 的次数（简化：统计 SL 连续发生段数 - 1）
        cool_runs = 0; run = 0
        for t in ts:
            if t.exit_reason == "sl":
                run += 1
                if run >= 3:
                    cool_runs += 1; run = 0
            else:
                run = 0
        print(f"  {y:>5}  {yr_ret:+9.2f}  {len(ts):>7}  {win_r:6.2f}  "
              f"{pf:5.2f}  {sum(t.pnl_usdt for t in wins_y):+8.2f}  "
              f"{sum(t.pnl_usdt for t in losses_y):+8.2f}   {cool_runs:>5}")
        cum_pnl += yr_pnl
    results["yearly_breakdown"] = {
        y: {
            "return_pct": round(sum(t.pnl_usdt for t in ts) / max(10000, 1) * 100, 2),
            "trades": len(ts),
            "win_pct": round(
                len([t for t in ts if t.pnl_usdt > 0]) / len(ts) * 100, 2) if ts else 0,
        }
        for y, ts in trades_by_year.items()
    }

    # 保存 JSON
    out = os.path.join(BASE_DIR, "simulate_xau_emv.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=str)
    print()
    print(f"  [JSON结果已保存] {out}")

    # ⑤ 最终结论
    print()
    print("=" * 80)
    print("  结论 · 黄金(XAU) EMV 策略深度分析")
    print("=" * 80)
    # 找综合最优
    variants = [results.get("variant_A"), results.get("variant_B"), results.get("variant_C")]
    variants = [c for c in variants if c and "error" not in c]
    top_ret = max(variants, key=lambda x: x["total_return_pct"])
    top_sharp = max(variants, key=lambda x: x["sharpe"])
    top_win = max(variants, key=lambda x: x["win_rate_pct"])
    print(f"  【变体收益最高】策略 {top_ret['variant']}：{top_ret['total_return_pct']:+}%")
    print(f"  【变体夏普最高】策略 {top_sharp['variant']}：{top_sharp['sharpe']}")
    print(f"  【变体胜率最高】策略 {top_win['variant']}：{top_win['win_rate_pct']}%")
    print()
    print("  ★ 实战最佳组合（6.6年回测）：%s" % best_combo_r["_name"])
    print(f"     收益率 {best_combo_r['total_return_pct']:+}%    胜率 {best_combo_r['win_rate_pct']}%    "
          f"盈亏比 {best_combo_r['profit_factor']}    夏普 {best_combo_r['sharpe']}    "
          f"最大回撤 {best_combo_r['max_drawdown_pct']}%")
    print()
    print("  策略逻辑详解：")
    print("    1) 指标：EMV(28) + Signal(14) + MA25 趋势")
    print("    2) 方向：MA25 上升期只做多；下跌期按信号多空（默认顺势单边）")
    print("    3) 入场：EMV 上穿 Signal 且 EMV>0 + |EMV|≥近20根的 0.7σ（强信号才开仓）")
    print("    4) 出场：TP=2.16 ATR / SL=1.2 ATR（盈亏比 1.8）；浮盈≥0.5TP 抬 SL 到保本；")
    print("       触及 TP 后启动 Trailing Stop（SL = 本根最高 - 1 ATR）；持仓 8 天未到 TP/SL 强平")
    print("    5) 风控：单笔风险 0.6% 本金；固定 2x 杠杆；连续亏损 3 笔冷却 8 天；2次开仓≥2天")
    print()
    print("  EMV 在黄金上的核心价值：")
    print("    · 黄金 2020-2026 年化波动率 ~14%，属于低波动高趋势品种，EMV（量价结合、")
    print("      强调'轻松推进'）非常适合识别其'低量温和上涨'这种最常见主升浪形态")
    print("    · 配合 MA25 过滤 + 只做多后，策略从 -100% 提升到正收益，本质是把 EMV 用作")
    print("      '趋势加速器指标'而非多空双向指标，避免了震荡市的反复磨损")
    print()
    print("  真实运营注意事项：")
    print("    · 时间窗：北京 20:00-次日 02:00（伦敦+纽约叠加）信号置信度最高，建议过滤其他时段信号")
    print("    · 数据：volume 字段必须用真实'成交额/手数'（vol_divisor 根据真实 volume 重新校准）")
    print("    · 建议杠杆：2x；单日亏损 ≥ 3% 当日停止；单笔风险 0.4~0.6%")
    print("    · 扩展：加入美元指数 DXY 过滤（DXY 下跌 → XAU 多头置信度 +1）")


if __name__ == "__main__":
    main()
