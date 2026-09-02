# -*- coding: utf-8 -*-
"""
XAU（黄金）EMV 策略 V3 · 修复确认BUG + 合理分层过滤
===================================================
V2 关键BUG：
  cross_up(交叉) 定义为 emv[i-1] <= sig[i-1] AND emv[i] > sig[i]
  但 confirm_bars=2 要求 j=i-1,i 两根都 emv[j] >= sig[j]
  → emv[i-1] 同时要 <= 和 >=，矛盾！→ 0笔交易

V3 修复：
  - 交叉发生在 k = i - (confirm_bars - 1) 那根
  - 交叉发生后，从 k 到当前 i（含）共 confirm_bars 根保持 EMV >= Signal
  → 交叉定义与确认不再矛盾
"""
from __future__ import annotations

import json
import math
import os
import random
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Sequence, Tuple

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from backend.strategy.indicators import sma, rsi, atr  # noqa: E402

SEED = 42
random.seed(SEED)


def _nan_to_zero(xs: Sequence[float]) -> List[float]:
    return [0.0 if (v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))))
            else float(v) for v in xs]


def emv(highs, lows, volumes, period=14, signal_period=9, vol_divisor=10_000_000.0):
    n = len(highs)
    if n == 0:
        return [], []
    raw = []
    for i in range(n):
        if i == 0:
            raw.append(0.0); continue
        mid_i = (highs[i] + lows[i]) * 0.5
        mid_j = (highs[i-1] + lows[i-1]) * 0.5
        dist = mid_i - mid_j
        hl = max(highs[i] - lows[i], 1e-9)
        vol_s = volumes[i] / max(vol_divisor, 1e-9)
        box = vol_s / hl
        v = dist / max(box, 1e-9)
        if math.isnan(v) or math.isinf(v):
            v = 0.0
        raw.append(v)
    emv_s = _nan_to_zero(sma(raw, period))
    sig_s = _nan_to_zero(sma(emv_s, signal_period))
    return emv_s, sig_s


ASSET_PROFILES = {
    "XAU": {"name": "XAU/USD", "start_price": 1520.0, "annualized_return": 0.10,
            "annualized_vol": 0.14, "trend_period": 210.0, "trend_amp": 0.08},
}


def generate_klines(symbol, start, end, timeframe_minutes=240):
    p = ASSET_PROFILES[symbol]
    step = timedelta(minutes=timeframe_minutes)
    bars_per_year = (365 * 24 * 60) / timeframe_minutes
    mu = p["annualized_return"] / bars_per_year
    sigma = p["annualized_vol"] / math.sqrt(bars_per_year)
    total = int((end - start) / step)
    out, px, dt, tper, amp = [], p["start_price"], start, p["trend_period"], p["trend_amp"]
    for i in range(total):
        o = px
        drift = mu + (amp / bars_per_year) * math.cos(2 * math.pi * i / (tper * bars_per_year / 365))
        c = o * math.exp(drift + sigma * random.gauss(0.0, 1.0))
        w = max(sigma, 0.002) * 1.2
        h = max(o, c) * (1.0 + random.uniform(0.0, w))
        l = min(o, c) * (1.0 - random.uniform(0.0, w))
        vol = random.uniform(0.8, 3.5) * max(abs(c - o) / max(o, 1e-9) / max(sigma, 1e-9), 0.3)
        vol = vol * 500_000 + 300_000
        out.append({"symbol": symbol, "dt": dt, "open": round(o, 2),
                    "high": round(h, 2), "low": round(l, 2),
                    "close": round(c, 2), "volume": round(vol, 0)})
        px = c; dt += step
    return out


@dataclass
class Position:
    symbol: str; side: int; entry_px: float; entry_dt: datetime
    tp_px: float; sl_px: float; lev: int; qty_usdt: float; bars_held: int = 0


@dataclass
class Trade:
    symbol: str; side: int; entry_dt: datetime; exit_dt: datetime
    entry_px: float; exit_px: float; pnl_usdt: float; pnl_pct: float
    exit_reason: str; lev: int; bars_held: int


class EMVStrategyBacktestV3:
    def __init__(
        self,
        initial_capital=10000.0, fee_rate_pct=0.04, slippage_pct=0.05,
        risk_pct_per_trade=0.5, tp_sl_ratio=1.5, sl_atr_mult=1.0,
        emv_period=14, signal_period=9, vol_divisor=10_000_000.0,
        # 入场过滤
        require_ma99_up=True,        # MA99 上升（10 根前对比，更宽松）
        require_bull_alignment=True, # MA25 > MA99 * 0.997（允许 0.3% 容差）
        emv_confirm_bars=2,          # 交叉后 N-1 根保持确认（=1 即交叉即入场）
        emv_lookback=30,
        emv_strength_std_mul=0.9,    # V3: 从 1.2 放宽到 0.9
        alignment_tol=0.003,         # 排列容差 0.3%
        ma99_lookback=10,            # MA99 趋势回看 10 根（比 V2 的5更宽）
        # 频率 / 冷却
        min_bars_between=20,         # V3: 5→3.3 天
        max_bars_held=60,
        max_consecutive_losses=2,
        cooldown_after_loss_streak=60,  # V3: 10 天
        fixed_leverage=2,
        use_trailing_stop=True,
    ):
        self.cap = self.start_cap = initial_capital
        self.fee = fee_rate_pct / 100.0
        self.slip = slippage_pct / 100.0
        self.risk = risk_pct_per_trade / 100.0
        self.tp_sl = tp_sl_ratio
        self.sl_atr = sl_atr_mult
        self.emv_p, self.sig_p, self.vol_div = emv_period, signal_period, vol_divisor
        self.req_ma99 = require_ma99_up
        self.req_align = require_bull_alignment
        self.emv_conf = emv_confirm_bars
        self.emv_lb = emv_lookback
        self.emv_std_mul = emv_strength_std_mul
        self.align_tol = alignment_tol
        self.ma99_lb = ma99_lookback
        self.min_bars = min_bars_between
        self.max_bars = max_bars_held
        self.max_cl = max_consecutive_losses
        self.cooldown_cl = cooldown_after_loss_streak
        self.fixed_lev = fixed_leverage
        self.use_ts = use_trailing_stop
        self.pos: Optional[Position] = None
        self.trades: List[Trade] = []
        self.equity_curve: List[Tuple[datetime, float]] = []
        self._last_open_idx = -999999
        self._loss_streak = 0
        self._cooldown_until_idx = -999999
        self.stats = {
            "total_cross_attempt": 0,
            "blocked_no_cross": 0,
            "blocked_ma99": 0,
            "blocked_alignment": 0,
            "blocked_confirm": 0,
            "blocked_strength": 0,
            "blocked_cooldown": 0,
            "actually_opened": 0,
        }

    def run(self, symbol, klines):
        need = max(self.emv_p + self.sig_p + 30, 99 + self.ma99_lb, 150)
        if len(klines) < need:
            return {"error": f"K线不足({len(klines)})"}
        highs = [k["high"] for k in klines]
        lows = [k["low"] for k in klines]
        closes = [k["close"] for k in klines]
        vols = [k["volume"] for k in klines]
        emv_s, sig_s = emv(highs, lows, vols, self.emv_p, self.sig_p, self.vol_div)
        ma25 = _nan_to_zero(sma(closes, 25))
        ma99 = _nan_to_zero(sma(closes, 99))
        atr_s = _nan_to_zero(atr(highs, lows, closes, 14))
        warmup = 150
        sc = self.cap
        for i in range(warmup, len(klines)):
            k = klines[i]
            a = atr_s[i]
            if i < self._cooldown_until_idx:
                self._check_tp_sl(k, i, a)
                self.equity_curve.append((k["dt"], self._equity(k)))
                continue
            self._check_tp_sl(k, i, a)
            if self.pos is not None and self.pos.bars_held >= self.max_bars:
                self._close(k, "timeout", i)
            long_sig = self._signal_long(i, emv_s, sig_s, ma25, ma99, closes)
            cool = (i - self._last_open_idx) >= self.min_bars
            if self.pos is None and long_sig and cool:
                self._open(k, 1, a, i); self._last_open_idx = i
                self.stats["actually_opened"] += 1
            elif self.pos is None and long_sig and not cool:
                self.stats["blocked_cooldown"] += 1
            self.equity_curve.append((k["dt"], self._equity(k)))
        if self.pos is not None:
            self._close(klines[-1], "end", len(klines)-1)
        return self._summary(symbol, sc, self.cap)

    def _signal_long(self, i, emv_s, sig_s, ma25, ma99, closes):
        # ⭐ V3 修复：确认根数与交叉定义无矛盾
        # 交叉发生在 k = i - (confirm_bars - 1) 这根
        # 然后从 k 到 i，共 confirm_bars 根保持 EMV >= Signal
        self.stats["total_cross_attempt"] += 1
        conf = self.emv_conf
        k = i - (conf - 1)
        if k < 2:
            self.stats["blocked_no_cross"] += 1
            return False
        # ① 在 k 根发生经典上穿（k-1 在下，k 在上，且 EMV_k > 0）
        cross_at_k = (emv_s[k-1] <= sig_s[k-1]) and (emv_s[k] > sig_s[k]) and (emv_s[k] > 0)
        if not cross_at_k:
            self.stats["blocked_no_cross"] += 1
            return False
        # ② 从 k 到 i，confirm_bars 根都保持 EMV >= Signal
        for j in range(k, i + 1):
            if emv_s[j] < sig_s[j]:
                self.stats["blocked_confirm"] += 1
                return False
        # ③ MA99 方向：MA99[i] > MA99[i-ma99_lb]（回看 N 根）
        if self.req_ma99 and ma99[i] > 0:
            ref = i - self.ma99_lb
            if ref < 0 or ma99[ref] <= 0 or ma99[i] <= ma99[ref]:
                self.stats["blocked_ma99"] += 1
                return False
        # ④ 多头排列容差：MA25 > MA99*(1 - tol)  AND  Close > MA25
        if self.req_align:
            if ma25[i] <= 0 or ma99[i] <= 0 or closes[i] <= ma25[i]:
                self.stats["blocked_alignment"] += 1
                return False
            if ma25[i] <= ma99[i] * (1.0 - self.align_tol):
                self.stats["blocked_alignment"] += 1
                return False
        # ⑤ 强度阈值
        if i >= self.emv_lb:
            w = emv_s[i - self.emv_lb + 1: i + 1]
            m = sum(w) / len(w)
            var = sum((x - m) ** 2 for x in w) / len(w)
            std = var ** 0.5
            thresh = max(std * self.emv_std_mul, 1e-9)
            if abs(emv_s[i]) < thresh:
                self.stats["blocked_strength"] += 1
                return False
        return True

    def _equity(self, k):
        eq = self.cap
        if self.pos is not None:
            c = k["close"]
            chg = (c - self.pos.entry_px) / self.pos.entry_px if self.pos.side == 1 \
                else (self.pos.entry_px - c) / self.pos.entry_px
            eq += self.pos.qty_usdt * self.pos.lev * chg
            self.pos.bars_held += 1
        return eq

    def _open(self, k, side, atr14, idx):
        if atr14 <= 0: return
        c = k["close"]
        sl_atr = atr14 * self.sl_atr
        tp_atr = sl_atr * self.tp_sl
        sl_pct = sl_atr / c
        if sl_pct <= 0: return
        lev = self.fixed_lev
        qty = (self.risk * self.cap) / (lev * sl_pct)
        qty = min(qty, self.cap * 0.4)
        entry = c * (1 + self.slip) if side == 1 else c * (1 - self.slip)
        if side == 1:
            tp, sl = entry + tp_atr, entry - sl_atr
        else:
            tp, sl = entry - tp_atr, entry + sl_atr
        self.pos = Position(symbol=k["symbol"], side=side, entry_px=entry,
                            entry_dt=k["dt"], tp_px=tp, sl_px=sl, lev=lev, qty_usdt=qty)

    def _check_tp_sl(self, k, idx, atr14=0.0):
        if self.pos is None: return
        h, l, c, p = k["high"], k["low"], k["close"], self.pos
        if self.use_ts and atr14 > 0:
            tp_amt = abs(p.tp_px - p.entry_px)
            if p.side == 1:
                if c >= p.entry_px + tp_amt * 0.4 and p.sl_px < p.entry_px:
                    p.sl_px = p.entry_px
                if h >= p.tp_px:
                    new_sl = h - atr14 * 0.8
                    if new_sl > p.sl_px: p.sl_px = new_sl
            else:
                if c <= p.entry_px - tp_amt * 0.4 and p.sl_px > p.entry_px:
                    p.sl_px = p.entry_px
                if l <= p.tp_px:
                    new_sl = l + atr14 * 0.8
                    if new_sl < p.sl_px: p.sl_px = new_sl
        if p.side == 1:
            if h >= p.tp_px: self._close(k, "tp", idx, force_px=p.tp_px); return
            if l <= p.sl_px: self._close(k, "sl", idx, force_px=p.sl_px); return
        else:
            if l <= p.tp_px: self._close(k, "tp", idx, force_px=p.tp_px); return
            if h >= p.sl_px: self._close(k, "sl", idx, force_px=p.sl_px); return

    def _close(self, k, reason, idx, force_px=None):
        p = self.pos
        c = force_px if force_px is not None else k["close"]
        exit_px = c * (1 - self.slip) if p.side == 1 else c * (1 + self.slip)
        pnl_pct = (exit_px - p.entry_px) / p.entry_px if p.side == 1 \
            else (p.entry_px - exit_px) / p.entry_px
        gross = p.qty_usdt * p.lev * pnl_pct
        fee = p.qty_usdt * self.fee * 2
        net = gross - fee
        self.cap += net
        self.trades.append(Trade(symbol=p.symbol, side=p.side, entry_dt=p.entry_dt,
                                 exit_dt=k["dt"], entry_px=p.entry_px, exit_px=exit_px,
                                 pnl_usdt=net, pnl_pct=pnl_pct*100, exit_reason=reason,
                                 lev=p.lev, bars_held=p.bars_held))
        if net < 0:
            self._loss_streak += 1
            if self._loss_streak >= self.max_cl:
                self._cooldown_until_idx = idx + self.cooldown_cl
                self._loss_streak = 0
        else:
            self._loss_streak = 0
        self.pos = None

    def _summary(self, symbol, sc, ec):
        tr = (ec - sc) / sc * 100
        W = [t for t in self.trades if t.pnl_usdt > 0]
        L = [t for t in self.trades if t.pnl_usdt <= 0]
        wr = len(W) / len(self.trades) * 100 if self.trades else 0.0
        aw = (sum(t.pnl_pct for t in W) / len(W)) if W else 0.0
        al = (sum(t.pnl_pct for t in L) / len(L)) if L else 0.0
        pf = (aw / abs(al)) if L and al else 0.0
        expct = (wr / 100 * (pf + 1) - 1) * 100
        peak, mdd = sc, 0.0
        rets, le = [], sc
        for dt, eq in self.equity_curve:
            if eq > peak: peak = eq
            dd = (peak - eq) / peak * 100
            if dd > mdd: mdd = dd
            if le > 0: rets.append((eq - le) / le)
            le = eq
        import statistics
        sp = 0.0
        if rets and statistics.stdev(rets) > 0:
            sp = (statistics.mean(rets) / statistics.stdev(rets)) * math.sqrt(252 * 6)
        ws = ls = cw = cl_ = 0
        for t in self.trades:
            if t.pnl_usdt > 0: cw += 1; cl_ = 0; ws = max(ws, cw)
            else: cl_ += 1; cw = 0; ls = max(ls, cl_)
        tpc = sum(1 for t in self.trades if t.exit_reason == "tp")
        slc = sum(1 for t in self.trades if t.exit_reason == "sl")
        toc = sum(1 for t in self.trades if t.exit_reason == "timeout")
        enc = sum(1 for t in self.trades if t.exit_reason == "end")
        return {
            "symbol": symbol, "start_cap": sc, "end_cap": round(ec, 2),
            "total_return_pct": round(tr, 2), "trade_count": len(self.trades),
            "win_rate_pct": round(wr, 2), "profit_factor": round(pf, 2),
            "expectancy_pct_per_trade": round(expct, 3),
            "avg_win_pct": round(aw, 2), "avg_loss_pct": round(al, 2),
            "sharpe": round(sp, 2), "max_drawdown_pct": round(mdd, 2),
            "win_streak": ws, "lose_streak": ls,
            "tp_count": tpc, "sl_count": slc, "timeout_count": toc, "end_count": enc,
            "filters": dict(self.stats),
            "last5": [
                {"entry": t.entry_dt.strftime("%Y-%m-%d %H:%M"),
                 "exit": t.exit_dt.strftime("%Y-%m-%d %H:%M"),
                 "side": "LONG" if t.side == 1 else "SHORT",
                 "lev": t.lev, "pnl_pct": round(t.pnl_pct, 2),
                 "pnl_usdt": round(t.pnl_usdt, 2), "reason": t.exit_reason,
                 "bars": t.bars_held} for t in self.trades[-5:]
            ],
        }


def run_bt(kw, klines, symbol="XAU"):
    return EMVStrategyBacktestV3(**kw).run(symbol, klines)


def main():
    START = datetime(2020, 1, 1)
    END = datetime(2026, 8, 1)
    print("=" * 88)
    print("  黄金（XAU）EMV 策略 V3 · 确认BUG修复 + 分层过滤 深度回测")
    print("=" * 88)
    years = 6 + 7/12
    print(f"  区间: {START.date()} ~ {END.date()}   品种: XAU/USD   周期: 4H   约 {years:.1f} 年")
    print(f"  初始资金 $10,000  ·  手续费 0.04% 双边  ·  滑点 0.05%  ·  单笔风险 0.5%  ·  2x 杠杆")
    print(f"  V3 核心修复：交叉发生在 k，然后 [k..i] 共 N 根保持确认（解决V2矛盾）")
    print(f"  V3 过滤：MA99(10根上升) / MA25>MA99(容差0.3%) / 2根确认 / 0.9σ强度 / 间隔3.3天")
    print()

    print("[1/6 数据生成] XAU 4H K线...")
    kl = generate_klines("XAU", START, END, 240)
    yr = len(kl) * 4 / 24 / 365
    print(f"  K线 {len(kl)} 根 ≈ {yr:.1f} 年   ${kl[0]['close']:.2f} → ${kl[-1]['close']:.2f}  "
          f"涨幅 {(kl[-1]['close']/kl[0]['close']-1)*100:.1f}%\n")

    results = {}

    # ① V1 vs V2a vs V3 基线对比
    print("=" * 88)
    print("  ① 基线对比：V1（原只做多全套）/ V2a（仅调TP:SL）/ V3 修复版 同种子")
    print("=" * 88)
    v1_kw = dict(initial_capital=10000, fee_rate_pct=0.04, slippage_pct=0.05,
                 risk_pct_per_trade=0.6, tp_sl_ratio=1.8, sl_atr_mult=1.2,
                 emv_period=14, signal_period=9,
                 require_ma99_up=False, require_bull_alignment=False,
                 emv_confirm_bars=1, emv_strength_std_mul=0.7,
                 min_bars_between=12, max_bars_held=48,
                 max_consecutive_losses=3, cooldown_after_loss_streak=48,
                 fixed_leverage=2, use_trailing_stop=True)
    v2a_kw = dict(v1_kw, require_ma99_up=True, require_bull_alignment=True,
                  emv_confirm_bars=1, emv_strength_std_mul=0.7,
                  tp_sl_ratio=1.5, sl_atr_mult=1.0, risk_pct_per_trade=0.5)
    v3_kw = dict(v1_kw, tp_sl_ratio=1.5, sl_atr_mult=1.0, risk_pct_per_trade=0.5,
                 require_ma99_up=True, require_bull_alignment=True,
                 emv_confirm_bars=2, emv_strength_std_mul=0.9, alignment_tol=0.003,
                 ma99_lookback=10, min_bars_between=20, max_bars_held=60,
                 max_consecutive_losses=2, cooldown_after_loss_streak=60)
    base_cfgs = [
        ("V1 · 只做多全套(原)",   v1_kw),
        ("V2a · 收紧TP:SL + 两MA", v2a_kw),
        ("V3 · 确认BUG修复 + 5过滤", v3_kw),
    ]
    print(f"  {'名称':30s}  {'Return%':>8}  {'Win%':>6}  {'P/F':>5}  "
          f"{'Exp%':>7}  {'Sharpe':>7}  {'DD%':>6}  {'Trades':>6}")
    print("  " + "-" * 82)
    for name, kw in base_cfgs:
        r = run_bt(kw, kl)
        if "error" in r: continue
        mark = "✅" if r["expectancy_pct_per_trade"] > 0 else "❌"
        print(f"  {name:30s}  {r['total_return_pct']:+8.2f}  "
              f"{r['win_rate_pct']:6.2f}  {r['profit_factor']:5.2f}  "
              f"{r['expectancy_pct_per_trade']:+7.3f}{mark}  "
              f"{r['sharpe']:7.2f}  {r['max_drawdown_pct']:6.2f}  "
              f"{r['trade_count']:>6}")
        results[f"baseline_{name}"] = r
    print()

    # ② 单因子消融（哪个过滤最关键）
    print("=" * 88)
    print("  ② 因子消融：逐一关闭各过滤，看每个因子的贡献")
    print("=" * 88)
    base = dict(v3_kw, emv_period=14, signal_period=9)
    ablation = [
        ("V3 全过滤",                                    {}),
        ("  - 关闭 MA99 上升",                            {"require_ma99_up": False}),
        ("  - 关闭 MA 多头排列",                           {"require_bull_alignment": False}),
        ("  - 减少确认到 1 根（无保持）",                    {"emv_confirm_bars": 1}),
        ("  - 降低强度到 0.5σ",                            {"emv_strength_std_mul": 0.5}),
        ("  - 强度完全关闭（σ=0）",                         {"emv_strength_std_mul": 0.0}),
        ("  - 缩小间隔到 5 天",                             {"min_bars_between": 30}),
        ("  - 只保留 50% 基础（无排列无MA99）",              {"require_ma99_up": False,
                                                                 "require_bull_alignment": False}),
    ]
    print(f"  {'配置':32s}  {'Return%':>8}  {'Win%':>6}  {'P/F':>5}  "
          f"{'Exp%':>7}  {'Sharpe':>7}  {'DD%':>6}  {'Trades':>6}")
    print("  " + "-" * 82)
    for name, patch in ablation:
        kw = dict(base, **patch)
        r = run_bt(kw, kl)
        if "error" in r: continue
        mark = "✅" if r["expectancy_pct_per_trade"] > 0 else "❌"
        print(f"  {name:32s}  {r['total_return_pct']:+8.2f}  "
              f"{r['win_rate_pct']:6.2f}  {r['profit_factor']:5.2f}  "
              f"{r['expectancy_pct_per_trade']:+7.3f}{mark}  "
              f"{r['sharpe']:7.2f}  {r['max_drawdown_pct']:6.2f}  "
              f"{r['trade_count']:>6}")
        results[f"ablation_{name.strip()}"] = r
    print()

    # ③ EMV × Signal 参数网格
    print("=" * 88)
    print("  ③ V3 全过滤 · EMV 周期 × Signal 周期 网格")
    print("=" * 88)
    eps = [7, 14, 21, 28]
    sps = [3, 5, 7, 9]
    grid = []
    print(f"  {'EMV':>4}/{'Sig':>3}  |  {'Return%':>8}  {'Win%':>6}  {'P/F':>5}  "
          f"{'Exp%':>7}  {'Sharpe':>7}  {'DD%':>6}  Trades")
    print("  " + "-" * 82)
    for ep in eps:
        for sp in sps:
            kw = dict(v3_kw, emv_period=ep, signal_period=sp)
            r = run_bt(kw, kl)
            if "error" in r: continue
            grid.append((ep, sp, r))
            mark = "✅" if r["expectancy_pct_per_trade"] > 0 else " "
            print(f"  {ep:>3}/{sp:>3}  |  {r['total_return_pct']:+8.2f}  "
                  f"{r['win_rate_pct']:6.2f}  {r['profit_factor']:5.2f}  "
                  f"{r['expectancy_pct_per_trade']:+7.3f}{mark}  "
                  f"{r['sharpe']:7.2f}  {r['max_drawdown_pct']:6.2f}  "
                  f"{r['trade_count']:>5}")

    def score(x):
        r = x[2]
        e = r["expectancy_pct_per_trade"]
        if e <= 0: return (-999, -999, r["total_return_pct"])
        return (e, r["sharpe"], r["total_return_pct"])
    best = max(grid, key=score)
    bs = max(grid, key=lambda x: x[2]["sharpe"])
    br = max(grid, key=lambda x: x[2]["total_return_pct"])
    print()
    print(f"  【综合最佳（正期望+夏普）】EMV={best[0]}/Sig={best[1]}  "
          f"收益 {best[2]['total_return_pct']:+}%  胜率 {best[2]['win_rate_pct']}%  "
          f"P/F {best[2]['profit_factor']}  每笔期望 {best[2]['expectancy_pct_per_trade']:+.3f}%  "
          f"夏普 {best[2]['sharpe']}  回撤 {best[2]['max_drawdown_pct']}%  "
          f"交易 {best[2]['trade_count']} 笔")
    print(f"  【夏普最高】EMV={bs[0]}/Sig={bs[1]}：夏普 {bs[2]['sharpe']}  "
          f"收益 {bs[2]['total_return_pct']:+}%  期望 {bs[2]['expectancy_pct_per_trade']:+.3f}%")
    print(f"  【收益最高】EMV={br[0]}/Sig={br[1]}：收益 {br[2]['total_return_pct']:+}%  "
          f"胜率 {br[2]['win_rate_pct']}%  期望 {br[2]['expectancy_pct_per_trade']:+.3f}%")
    best_ep, best_sp, _ = best
    results["grid_best"] = {"emv_period": best_ep, "signal_period": best_sp, **best[2]}

    # ④ 过滤漏斗（最佳参数）
    print()
    print("=" * 88)
    print(f"  ④ 过滤漏斗 · EMV={best_ep}/Sig={best_sp}")
    print("=" * 88)
    best_kw = dict(v3_kw, emv_period=best_ep, signal_period=best_sp)
    rf = run_bt(best_kw, kl)
    fs = rf["filters"]
    tot = fs["total_cross_attempt"] or 1
    passed = fs["actually_opened"]
    print(f"  进入信号判断 i 次数:        {tot:>6}  (100.0%)")
    print(f"    ├ 未在 k={best_kw['emv_confirm_bars']-1} 根前交叉:     {fs['blocked_no_cross']:>6}  "
          f"({fs['blocked_no_cross']/tot*100:5.1f}%)")
    rem = tot - fs["blocked_no_cross"]
    print(f"    ├ 被 MA99 趋势拦截:       {fs['blocked_ma99']:>6}  "
          f"({fs['blocked_ma99']/max(rem,1)*100:5.1f}% of 上一层)")
    rem -= fs["blocked_ma99"]
    print(f"    ├ 被多头排列拦截:         {fs['blocked_alignment']:>6}  "
          f"({fs['blocked_alignment']/max(rem,1)*100:5.1f}% of 上一层)")
    rem -= fs["blocked_alignment"]
    print(f"    ├ 被 {best_kw['emv_confirm_bars']} 根保持确认拦截:   {fs['blocked_confirm']:>6}  "
          f"({fs['blocked_confirm']/max(rem,1)*100:5.1f}% of 上一层)")
    rem -= fs["blocked_confirm"]
    print(f"    ├ 被 {best_kw['emv_strength_std_mul']}σ 强度拦截:     {fs['blocked_strength']:>6}  "
          f"({fs['blocked_strength']/max(rem,1)*100:5.1f}% of 上一层)")
    rem -= fs["blocked_strength"]
    print(f"    ├ 被开仓间隔拦截:         {fs['blocked_cooldown']:>6}  "
          f"({fs['blocked_cooldown']/max(rem,1)*100:5.1f}% of 上一层)")
    print(f"    → 最终实际开仓:           {passed:>6}  "
          f"({passed/tot*100:.2f}% of 全部 i)")
    print()
    print(f"  信号通过率: {passed}/{tot} = {passed/tot*100:.2f}%  |  "
          f"交易频率: {passed/yr:.1f} 笔/年 = 每 {12/max(passed/yr,0.01):.1f} 月 1 笔")
    results["funnel"] = fs

    # ⑤ TP:SL × SL_ATR 敏感性（最佳参数）
    print()
    print("=" * 88)
    print(f"  ⑤ TP/SL × SL(ATR) 敏感性 · EMV={best_ep}/Sig={best_sp}")
    print("=" * 88)
    tsls = [1.2, 1.4, 1.5, 1.7, 2.0]
    sls = [0.8, 1.0, 1.2, 1.5]
    print(f"  {'TP:SL':>5}  {'SL×ATR':>7}  |  {'Return%':>8}  {'Win%':>6}  {'P/F':>5}  "
          f"{'Exp%':>7}  {'Sharpe':>7}  {'DD%':>6}  Trades")
    print("  " + "-" * 86)
    ts_best = None
    for tsr in tsls:
        for sam in sls:
            kw = dict(best_kw, tp_sl_ratio=tsr, sl_atr_mult=sam)
            r = run_bt(kw, kl)
            if "error" in r: continue
            e = r["expectancy_pct_per_trade"]
            mark = "✅" if e > 0 else " "
            print(f"  {tsr:>5.2f}  {sam:>7.1f}  |  {r['total_return_pct']:+8.2f}  "
                  f"{r['win_rate_pct']:6.2f}  {r['profit_factor']:5.2f}  "
                  f"{e:+7.3f}{mark}  {r['sharpe']:7.2f}  "
                  f"{r['max_drawdown_pct']:6.2f}  {r['trade_count']:>5}")
            if ts_best is None or (e, r["sharpe"], r["total_return_pct"]) > (
                    ts_best[0], ts_best[1], ts_best[2]):
                ts_best = (e, r["sharpe"], r["total_return_pct"], tsr, sam, r)
    if ts_best:
        e, sh, rt, tsr, sam, fr = ts_best
        print()
        print(f"  【TP/SL 最优】TP:SL = {tsr} : 1，SL = {sam} ATR")
        print(f"     收益 {rt:+}%  胜率 {fr['win_rate_pct']}%  "
              f"每笔期望 {e:+.3f}%  夏普 {sh}  回撤 {fr['max_drawdown_pct']}%  "
              f"交易 {fr['trade_count']} 笔")
        results["tpsl_best"] = {"tp_sl_ratio": tsr, "sl_atr_mult": sam, **fr}

    # ⑥ 年度拆解（最终推荐组 = TP:SL 最优）
    print()
    print("=" * 88)
    print("  ⑥ 年度表现拆解 · 最终推荐参数组")
    print("=" * 88)
    if ts_best:
        e, sh, rt, tsr, sam, fr = ts_best
        final_kw = dict(best_kw, tp_sl_ratio=tsr, sl_atr_mult=sam)
    else:
        final_kw = best_kw
    bt_final = EMVStrategyBacktestV3(**final_kw)
    bt_final.run("XAU", kl)
    ty: Dict[int, List[Trade]] = {}
    for t in bt_final.trades:
        ty.setdefault(t.exit_dt.year, []).append(t)
    print(f"  {'Year':>5}  {'Return%':>9}  {'Trades':>7}  {'Win%':>7}  "
          f"{'P/F':>5}  {'Exp%':>7}  {'TP':>4}  {'SL':>4}  {'Timeout':>7}")
    print("  " + "-" * 82)
    cum = 0.0
    for y in sorted(ty.keys()):
        ts2 = ty[y]
        yr_pnl = sum(t.pnl_usdt for t in ts2)
        wy = [t for t in ts2 if t.pnl_usdt > 0]
        ly2 = [t for t in ts2 if t.pnl_usdt <= 0]
        wr = len(wy)/len(ts2)*100 if ts2 else 0
        aw = (sum(t.pnl_pct for t in wy)/len(wy)) if wy else 0
        al = (sum(t.pnl_pct for t in ly2)/len(ly2)) if ly2 else 0
        pf = (aw / abs(al)) if al else 0
        e = (wr/100*(pf+1)-1)*100 if pf else 0
        base = 10000 + cum
        yr_ret = yr_pnl / base * 100 if base else 0
        tpc = sum(1 for t in ts2 if t.exit_reason == "tp")
        slc = sum(1 for t in ts2 if t.exit_reason == "sl")
        toc = sum(1 for t in ts2 if t.exit_reason == "timeout")
        print(f"  {y:>5}  {yr_ret:+9.2f}  {len(ts2):>7}  {wr:7.2f}  "
              f"{pf:5.2f}  {e:+7.3f}  {tpc:>4}  {slc:>4}  {toc:>7}")
        cum += yr_pnl
    results["yearly"] = {
        y: {"return_pct": round(sum(t.pnl_usdt for t in ts2)/10000*100, 2),
            "trades": len(ts2),
            "win_pct": round(len([t for t in ts2 if t.pnl_usdt>0])/len(ts2)*100, 2) if ts2 else 0}
        for y, ts2 in ty.items()
    }

    out = os.path.join(BASE_DIR, "simulate_xau_emv_v3.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n  [JSON结果保存] {out}")

    # 最终结论
    print()
    print("=" * 88)
    print("  最终结论 · 黄金(XAU) EMV 策略 V3")
    print("=" * 88)
    fr = ts_best[5] if ts_best else rf
    e = ts_best[0] if ts_best else rf["expectancy_pct_per_trade"]
    sh = ts_best[1] if ts_best else rf["sharpe"]
    rt = ts_best[2] if ts_best else rf["total_return_pct"]
    n = fr["trade_count"]
    tp_sl_r = ts_best[3] if ts_best else 1.5
    sl_atr_r = ts_best[4] if ts_best else 1.0
    print(f"  ★ 推荐参数组：")
    print(f"     · EMV 指标: period={best_ep}，signal={best_sp}，vol_divisor=1e7")
    print(f"     · 出场: TP/SL = {tp_sl_r}:1，SL = {sl_atr_r} ATR")
    print(f"     · 过滤: MA99↑(10根)  +  MA25 > MA99(容差0.3%)  +  Close>MA25")
    print(f"              + 交叉后 {final_kw.get('emv_confirm_bars',2)} 根保持  +  "
          f"|EMV| ≥ {final_kw.get('emv_strength_std_mul',0.9)}σ(30根)")
    print(f"     · 风控: 间隔 ≥ {final_kw.get('min_bars_between',20)}根({final_kw.get('min_bars_between',20)/6:.1f}天)  "
          f"·  超时 {final_kw.get('max_bars_held',60)/6:.0f}天强平  ·  连亏{final_kw.get('max_consecutive_losses',2)}笔冷却"
          f"{final_kw.get('cooldown_after_loss_streak',60)/6:.0f}天")
    print(f"     · 单笔风险 {final_kw.get('risk_pct_per_trade',0.5)}%  ·  杠杆 {final_kw.get('fixed_leverage',2)}x  ·  "
          f"Trailing Stop {'ON' if final_kw.get('use_trailing_stop',True) else 'OFF'}")
    print()
    ok = e > 0
    print(f"  {yr:.1f} 年回测成绩：")
    print(f"     收益率 {rt:+}%    胜率 {fr['win_rate_pct']}%    盈亏比 {fr['profit_factor']}    "
          f"每笔期望 {e:+.3f}%  {'✅ 正期望 · 可实盘模拟' if ok else '❌ 负期望 · 需继续优化'}")
    print(f"     夏普比 {sh:+.2f}    最大回撤 {fr['max_drawdown_pct']}%    "
          f"交易 {n} 笔 ({n/yr:.1f}/年 或 每 {12/max(n/yr,0.01):.1f}月1笔)")
    print(f"     TP {fr['tp_count']} / SL {fr['sl_count']} / 超时 {fr['timeout_count']} / 结束 {fr['end_count']}    "
          f"最大连胜 {fr['win_streak']} / 连败 {fr['lose_streak']}")
    if fr["last5"]:
        print(f"     最近 5 笔：")
        for t in fr["last5"]:
            ic = "▲" if t["side"] == "LONG" else "▼"
            print(f"       {ic} {t['entry']}~{t['exit']}  {t['side']}  "
                  f"lev={t['lev']}x  PnL={t['pnl_pct']:+.2f}% (${t['pnl_usdt']:+.2f})  "
                  f"{t['reason']}  持 {t['bars']}K")
    print()
    print("  数学期望公式验证：")
    wr2 = fr["win_rate_pct"] / 100
    pf2 = fr["profit_factor"]
    exp_verify = wr2 * (1 + pf2) - 1
    print(f"     E = 胜率 × (盈亏比 + 1) - 1 = {wr2:.4f} × ({pf2:.2f} + 1) - 1 = {exp_verify:+.4f}")
    if exp_verify > 0:
        annual_e = n / yr * exp_verify * 100
        print(f"     → 每笔期望 {exp_verify*100:+.3f}%  ✅ 为正")
        print(f"     → 年期望收益 ≈ {n/yr:.1f} × {exp_verify*100:+.3f}% = {annual_e:+.2f}%")
    else:
        print(f"     → 每笔期望 {exp_verify*100:+.3f}%  ❌ 为负（长期必亏）")
    print()
    print("  真实市场接入（强依赖！EMV 是量价指标，Volume 口径必须对）：")
    print("    1) vol_divisor 校准：用真实 XAU/USD 4H 数据（建议 Alpha Vantage / Polygon / "
          "TradingView 导出）")
    print("       扫描 1e5 ~ 1e9，让 |EMV| ≈ 0.01 ~ 0.2 区间，再重新跑扫参")
    print("    2) 交易时段：只处理北京时间 20:00-次日 02:00（伦敦+纽约重叠，流动性最佳）")
    print("    3) 基本面叠加：DXY(美元指数) 4H 收低于 MA25 → XAU 多头置信度 ↑，可 0.4→0.6% 风险")
    print("    4) 数据替代：无 Volume 数据源时，用 (High-Low) × Close 作为 Volume proxy 应急")
    print()
    print("  主要风险：")
    print("    · 黄金震荡市（例如 2021 横盘半年）→ MA 排列过滤仍会入场，需配合 VIX>20 时关仓 1 个月")
    print("    · 黑天鹅（俄乌/美联储意外）→ Trailing Stop 提前保本/止盈保护；单日亏 ≥2% 当日停机")
    print("    · 滑点放大（非农/CPI）→ 这些时段跳过信号，不要用市价单追入")


if __name__ == "__main__":
    main()
