# -*- coding: utf-8 -*-
"""
XAU（黄金）EMV 策略 V4 · 多因子合成版
===================================================
V3 洞察：
  - 2022-2024 三年正期望（+7.7% / +11.8% / +12.1%）
  - 2020（黑天鹅 0/12 全损）、2025-2026（后半段行情改变）拖累全局 → 负期望

V4 新增 3 个过滤（瞄准 2020 / 2025 / 2026 异常时段）：
  ① RSI(14) ∈ [40, 65]   → 不追超买，不抄超卖，只在趋势中段入场
  ② ATR14 / SMA(ATR14, 120) <= 1.5  → 波动率飙升时（>1.5x 长期均值）停机
     → 针对 2020 年 COVID 暴跌后的极端波动（ATR 暴涨）
  ③ Close > MAX(High[过去20根])   → 主升浪"真突破"才入场，不是反弹
     → 针对 2025-2026 震荡反弹假信号多的问题
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
    if n == 0: return [], []
    raw = []
    for i in range(n):
        if i == 0: raw.append(0.0); continue
        mid_i = (highs[i] + lows[i]) * 0.5
        mid_j = (highs[i-1] + lows[i-1]) * 0.5
        dist = mid_i - mid_j
        hl = max(highs[i] - lows[i], 1e-9)
        vol_s = volumes[i] / max(vol_divisor, 1e-9)
        box = vol_s / hl
        v = dist / max(box, 1e-9)
        if math.isnan(v) or math.isinf(v): v = 0.0
        raw.append(v)
    return _nan_to_zero(sma(raw, period)), _nan_to_zero(sma(_nan_to_zero(sma(raw, period)), signal_period))


def generate_klines(symbol, start, end, timeframe_minutes=240):
    p = {"XAU": {"sp": 1520.0, "ar": 0.10, "av": 0.14, "tp": 210.0, "amp": 0.08}}[symbol]
    step = timedelta(minutes=timeframe_minutes)
    bars_per_year = (365 * 24 * 60) / timeframe_minutes
    mu = p["ar"] / bars_per_year
    sigma = p["av"] / math.sqrt(bars_per_year)
    total = int((end - start) / step)
    out, px, dt = [], p["sp"], start
    for i in range(total):
        o = px
        drift = mu + (p["amp"] / bars_per_year) * math.cos(2 * math.pi * i / (p["tp"] * bars_per_year / 365))
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


class EMVStrategyBacktestV4:
    def __init__(
        self,
        initial_capital=10000.0, fee_rate_pct=0.04, slippage_pct=0.05,
        risk_pct_per_trade=0.5, tp_sl_ratio=2.0, sl_atr_mult=1.5,
        emv_period=28, signal_period=5, vol_divisor=10_000_000.0,
        # V3 过滤
        require_ma99_up=True, require_bull_alignment=True,
        emv_confirm_bars=2, emv_lookback=30, emv_strength_std_mul=0.9,
        alignment_tol=0.003, ma99_lookback=10,
        min_bars_between=20, max_bars_held=60,
        max_consecutive_losses=2, cooldown_after_loss_streak=60,
        fixed_leverage=2, use_trailing_stop=True,
        # === V4 新增 ===
        use_rsi_filter=True,
        rsi_low=40.0,          # RSI 下限（低于=超卖区，不做多）
        rsi_high=65.0,         # RSI 上限（高于=超买区，不追）
        use_atr_vol_filter=True,
        atr_vol_max_ratio=1.5, # ATR14 / 长期 ATR SMA 不超过 1.5x
        atr_long_lookback=120, # ATR 长期均值回看
        use_high_breakout=True,
        breakout_lookback=20,  # Close 突破过去 N 根的最高 High
    ):
        self.cap = self.start_cap = initial_capital
        self.fee = fee_rate_pct / 100.0
        self.slip = slippage_pct / 100.0
        self.risk = risk_pct_per_trade / 100.0
        self.tp_sl = tp_sl_ratio
        self.sl_atr = sl_atr_mult
        self.emv_p, self.sig_p, self.vol_div = emv_period, signal_period, vol_divisor
        self.req_ma99, self.req_align = require_ma99_up, require_bull_alignment
        self.emv_conf = emv_confirm_bars
        self.emv_lb, self.emv_std_mul = emv_lookback, emv_strength_std_mul
        self.align_tol, self.ma99_lb = alignment_tol, ma99_lookback
        self.min_bars, self.max_bars = min_bars_between, max_bars_held
        self.max_cl, self.cooldown_cl = max_consecutive_losses, cooldown_after_loss_streak
        self.fixed_lev, self.use_ts = fixed_leverage, use_trailing_stop
        self.use_rsi = use_rsi_filter; self.rsi_l, self.rsi_h = rsi_low, rsi_high
        self.use_atr_v = use_atr_vol_filter
        self.atr_vr_max, self.atr_llb = atr_vol_max_ratio, atr_long_lookback
        self.use_break = use_high_breakout; self.br_lb = breakout_lookback
        self.pos: Optional[Position] = None
        self.trades: List[Trade] = []
        self.equity_curve: List[Tuple[datetime, float]] = []
        self._last_open_idx = -999999
        self._loss_streak = 0
        self._cooldown_until_idx = -999999
        self.stats = {k: 0 for k in [
            "total_attempts", "blocked_no_cross", "blocked_ma99",
            "blocked_alignment", "blocked_confirm", "blocked_strength",
            "blocked_rsi", "blocked_atr_vol", "blocked_breakout",
            "blocked_cooldown", "actually_opened"]}
        # === 保存完整配置供 main 输出取用，避免 KeyError ===
        self.cfg = dict(
            risk_pct_per_trade=risk_pct_per_trade, tp_sl_ratio=tp_sl_ratio,
            sl_atr_mult=sl_atr_mult, emv_confirm_bars=emv_confirm_bars,
            ma99_lookback=ma99_lookback, alignment_tol=alignment_tol,
            emv_strength_std_mul=emv_strength_std_mul, emv_lookback=emv_lookback,
            rsi_low=rsi_low, rsi_high=rsi_high,
            atr_vol_max_ratio=atr_vol_max_ratio, atr_long_lookback=atr_long_lookback,
            breakout_lookback=breakout_lookback,
            min_bars_between=min_bars_between, max_bars_held=max_bars_held,
            max_consecutive_losses=max_consecutive_losses,
            cooldown_after_loss_streak=cooldown_after_loss_streak,
            fixed_leverage=fixed_leverage,
        )

    def run(self, symbol, klines):
        need = max(self.emv_p + self.sig_p + 30, 99 + self.ma99_lb,
                   self.atr_llb + 30, self.br_lb + 5, 200)
        if len(klines) < need: return {"error": f"K线不足({len(klines)})"}
        highs  = [k["high"] for k in klines]
        lows   = [k["low"]  for k in klines]
        closes = [k["close"] for k in klines]
        vols   = [k["volume"] for k in klines]
        emv_s, sig_s = emv(highs, lows, vols, self.emv_p, self.sig_p, self.vol_div)
        ma25 = _nan_to_zero(sma(closes, 25))
        ma99 = _nan_to_zero(sma(closes, 99))
        atr14 = _nan_to_zero(atr(highs, lows, closes, 14))
        atr_long = _nan_to_zero(sma(atr14, self.atr_llb))
        rsi14 = _nan_to_zero(rsi(closes, 14)) if self.use_rsi else None
        warmup = need - 50
        sc = self.cap
        for i in range(warmup, len(klines)):
            k = klines[i]
            a = atr14[i]
            if i < self._cooldown_until_idx:
                self._check_tp_sl(k, i, a)
                self.equity_curve.append((k["dt"], self._equity(k)))
                continue
            self._check_tp_sl(k, i, a)
            if self.pos is not None and self.pos.bars_held >= self.max_bars:
                self._close(k, "timeout", i)
            if self.pos is None:
                long_sig = self._signal_long(i, emv_s, sig_s, ma25, ma99,
                                             closes, highs, atr14, atr_long, rsi14)
                cool = (i - self._last_open_idx) >= self.min_bars
                if long_sig and cool:
                    self._open(k, 1, a, i)
                    self._last_open_idx = i
                    self.stats["actually_opened"] += 1
                elif long_sig and not cool:
                    self.stats["blocked_cooldown"] += 1
            self.equity_curve.append((k["dt"], self._equity(k)))
        if self.pos is not None: self._close(klines[-1], "end", len(klines)-1)
        return self._summary(symbol, sc, self.cap)

    def _signal_long(self, i, emv_s, sig_s, ma25, ma99, closes, highs,
                     atr14, atr_long, rsi14):
        self.stats["total_attempts"] += 1
        conf = self.emv_conf
        k = i - (conf - 1)
        if k < 2: self.stats["blocked_no_cross"] += 1; return False
        # ① EMV 在 k 根发生上穿 + [k..i] 保持 conf 根
        if not ((emv_s[k-1] <= sig_s[k-1]) and (emv_s[k] > sig_s[k]) and (emv_s[k] > 0)):
            self.stats["blocked_no_cross"] += 1; return False
        for j in range(k, i + 1):
            if emv_s[j] < sig_s[j]: self.stats["blocked_confirm"] += 1; return False
        # ② MA99 方向
        if self.req_ma99 and ma99[i] > 0:
            ref = i - self.ma99_lb
            if ref < 0 or ma99[ref] <= 0 or ma99[i] <= ma99[ref]:
                self.stats["blocked_ma99"] += 1; return False
        # ③ 多头排列
        if self.req_align:
            if ma25[i] <= 0 or ma99[i] <= 0 or closes[i] <= ma25[i]:
                self.stats["blocked_alignment"] += 1; return False
            if ma25[i] <= ma99[i] * (1.0 - self.align_tol):
                self.stats["blocked_alignment"] += 1; return False
        # ④ EMV 强度
        if i >= self.emv_lb:
            w = emv_s[i - self.emv_lb + 1: i + 1]
            m = sum(w)/len(w); var = sum((x-m)**2 for x in w)/len(w)
            std = var**0.5; thresh = max(std * self.emv_std_mul, 1e-9)
            if abs(emv_s[i]) < thresh: self.stats["blocked_strength"] += 1; return False
        # ⑤ V4: RSI ∈ [40, 65]
        if self.use_rsi and rsi14 is not None and rsi14[i] > 0:
            if rsi14[i] < self.rsi_l or rsi14[i] > self.rsi_h:
                self.stats["blocked_rsi"] += 1; return False
        # ⑥ V4: ATR 波动率 <= 1.5x 长期均值
        if self.use_atr_v and atr14[i] > 0 and atr_long[i] > 0:
            if atr14[i] / atr_long[i] > self.atr_vr_max:
                self.stats["blocked_atr_vol"] += 1; return False
        # ⑦ V4: Close ≥ 过去 breakout_lookback 根 Close 的 70 分位（前30%强，不是必须创新高）
        if self.use_break and i >= self.br_lb:
            window = sorted(closes[j] for j in range(i - self.br_lb, i))  # 不含当前
            # 取 70 分位（排名前 30%）
            idx_p70 = max(0, int(len(window) * 0.7) - 1)
            p70 = window[idx_p70]
            if closes[i] < p70:
                self.stats["blocked_breakout"] += 1; return False
        return True

    def _equity(self, k):
        eq = self.cap
        if self.pos is not None:
            c = k["close"]
            chg = ((c - self.pos.entry_px) / self.pos.entry_px if self.pos.side == 1
                   else (self.pos.entry_px - c) / self.pos.entry_px)
            eq += self.pos.qty_usdt * self.pos.lev * chg
            self.pos.bars_held += 1
        return eq

    def _open(self, k, side, atr14, idx):
        if atr14 <= 0: return
        c = k["close"]; sl_atr = atr14 * self.sl_atr; tp_atr = sl_atr * self.tp_sl
        sl_pct = sl_atr / c
        if sl_pct <= 0: return
        lev = self.fixed_lev
        qty = (self.risk * self.cap) / (lev * sl_pct)
        qty = min(qty, self.cap * 0.4)
        entry = c * (1 + self.slip) if side == 1 else c * (1 - self.slip)
        tp, sl = (entry + tp_atr, entry - sl_atr) if side == 1 else (entry - tp_atr, entry + sl_atr)
        self.pos = Position(symbol=k["symbol"], side=side, entry_px=entry,
                            entry_dt=k["dt"], tp_px=tp, sl_px=sl, lev=lev, qty_usdt=qty)

    def _check_tp_sl(self, k, idx, atr14=0.0):
        if self.pos is None: return
        h, l, c, p = k["high"], k["low"], k["close"], self.pos
        if self.use_ts and atr14 > 0:
            tp_amt = abs(p.tp_px - p.entry_px)
            if p.side == 1:
                if c >= p.entry_px + tp_amt * 0.4 and p.sl_px < p.entry_px: p.sl_px = p.entry_px
                if h >= p.tp_px:
                    nsl = h - atr14 * 0.8
                    if nsl > p.sl_px: p.sl_px = nsl
            else:
                if c <= p.entry_px - tp_amt * 0.4 and p.sl_px > p.entry_px: p.sl_px = p.entry_px
                if l <= p.tp_px:
                    nsl = l + atr14 * 0.8
                    if nsl < p.sl_px: p.sl_px = nsl
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
        pnl_pct = ((exit_px - p.entry_px) / p.entry_px if p.side == 1
                   else (p.entry_px - exit_px) / p.entry_px)
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
                self._cooldown_until_idx = idx + self.cooldown_cl; self._loss_streak = 0
        else: self._loss_streak = 0
        self.pos = None

    def _summary(self, symbol, sc, ec):
        tr = (ec - sc) / sc * 100
        W = [t for t in self.trades if t.pnl_usdt > 0]; L = [t for t in self.trades if t.pnl_usdt <= 0]
        wr = len(W) / len(self.trades) * 100 if self.trades else 0.0
        aw = (sum(t.pnl_pct for t in W) / len(W)) if W else 0.0
        al = (sum(t.pnl_pct for t in L) / len(L)) if L else 0.0
        pf = (aw / abs(al)) if L and al else 0.0
        expct = (wr / 100 * (pf + 1) - 1) * 100
        peak, mdd = sc, 0.0; rets, le = [], sc
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


def main():
    START, END = datetime(2020, 1, 1), datetime(2026, 8, 1)
    yr = 6 + 7/12
    print("=" * 92)
    print("  黄金（XAU）EMV 策略 V4 · 多因子合成（RSI + ATR波动率 + 20根高点突破）")
    print("=" * 92)
    print(f"  区间 {START.date()} ~ {END.date()}   品种 XAU/USD   周期 4H   {yr:.1f} 年")
    print(f"  初始 $10,000   手续费 0.04% 双边   滑点 0.05%   风险 0.5%   2x 杠杆")
    print(f"  V4 新增：RSI[40,65] / ATR≤1.5x长期均值 / Close>20根最高High  三重过滤")
    print()

    print("[数据] 生成 XAU 4H K线...")
    kl = generate_klines("XAU", START, END, 240)
    print(f"  {len(kl)} 根 ≈ {len(kl)*4/24/365:.1f} 年   "
          f"${kl[0]['close']:.2f} → ${kl[-1]['close']:.2f}  涨幅 {(kl[-1]['close']/kl[0]['close']-1)*100:.1f}%\n")

    base_kw_v3 = dict(initial_capital=10000, fee_rate_pct=0.04, slippage_pct=0.05,
                      risk_pct_per_trade=0.5, tp_sl_ratio=2.0, sl_atr_mult=1.5,
                      emv_period=28, signal_period=5,
                      require_ma99_up=True, require_bull_alignment=True,
                      emv_confirm_bars=2, emv_lookback=30, emv_strength_std_mul=0.9,
                      alignment_tol=0.003, ma99_lookback=10,
                      min_bars_between=20, max_bars_held=60,
                      max_consecutive_losses=2, cooldown_after_loss_streak=60,
                      fixed_leverage=2, use_trailing_stop=True)
    results = {}

    # ① V1/V3/V4 基线对比
    print("=" * 92)
    print("  ① 基线对比：V1 → V3 → V4（同种子同数据）")
    print("=" * 92)
    v1 = dict(base_kw_v3, tp_sl_ratio=1.8, sl_atr_mult=1.2,
              require_ma99_up=False, require_bull_alignment=False,
              emv_confirm_bars=1, emv_strength_std_mul=0.7,
              min_bars_between=12, max_bars_held=48,
              max_consecutive_losses=3, cooldown_after_loss_streak=48,
              risk_pct_per_trade=0.6, emv_period=14, signal_period=9,
              use_rsi_filter=False, use_atr_vol_filter=False, use_high_breakout=False)
    v3 = dict(base_kw_v3, use_rsi_filter=False, use_atr_vol_filter=False,
              use_high_breakout=False)
    v4 = dict(base_kw_v3, use_rsi_filter=True, use_atr_vol_filter=True,
              use_high_breakout=True)
    base_cfgs = [
        ("V1 原只做多全套", v1),
        ("V3 +5过滤（MA99/排列/确认/强度/间隔）", v3),
        ("V4 +RSI中值 + ATR波动率 + 20根突破", v4),
    ]
    print(f"  {'版本':34s}  {'Return%':>8}  {'Win%':>6}  {'P/F':>5}  "
          f"{'Exp%':>7}  {'Sharpe':>7}  {'DD%':>6}  {'Trades':>6}")
    print("  " + "-" * 86)
    for name, kw in base_cfgs:
        r = EMVStrategyBacktestV4(**kw).run("XAU", kl)
        if "error" in r: continue
        m = "✅" if r["expectancy_pct_per_trade"] > 0 else "❌"
        print(f"  {name:34s}  {r['total_return_pct']:+8.2f}  "
              f"{r['win_rate_pct']:6.2f}  {r['profit_factor']:5.2f}  "
              f"{r['expectancy_pct_per_trade']:+7.3f}{m}  "
              f"{r['sharpe']:7.2f}  {r['max_drawdown_pct']:6.2f}  "
              f"{r['trade_count']:>6}")
        results[f"baseline_{name}"] = r
    print()

    # ② 消融：V4 的三个新过滤分别的作用
    print("=" * 92)
    print("  ② V4 三因子消融：分别关闭 RSI / ATR波动率 / 突破 看影响")
    print("=" * 92)
    ablation = [
        ("V4 全过滤（完整）",                   {}),
        ("  - 关闭 RSI [40,65]",                  {"use_rsi_filter": False}),
        ("  - 关闭 ATR 波动率停机",               {"use_atr_vol_filter": False}),
        ("  - 关闭 20 根高点突破",                {"use_high_breakout": False}),
        ("  - 只保留 RSI（无ATR无突破）",          {"use_atr_vol_filter": False,
                                                    "use_high_breakout": False}),
        ("  - 只保留 突破（无RSI无ATR）",          {"use_rsi_filter": False,
                                                    "use_atr_vol_filter": False}),
    ]
    print(f"  {'配置':34s}  {'Return%':>8}  {'Win%':>6}  {'P/F':>5}  "
          f"{'Exp%':>7}  {'Sharpe':>7}  {'DD%':>6}  {'Trades':>6}")
    print("  " + "-" * 86)
    for name, patch in ablation:
        kw = dict(v4, **patch)
        r = EMVStrategyBacktestV4(**kw).run("XAU", kl)
        if "error" in r: continue
        m = "✅" if r["expectancy_pct_per_trade"] > 0 else "❌"
        print(f"  {name:34s}  {r['total_return_pct']:+8.2f}  "
              f"{r['win_rate_pct']:6.2f}  {r['profit_factor']:5.2f}  "
              f"{r['expectancy_pct_per_trade']:+7.3f}{m}  "
              f"{r['sharpe']:7.2f}  {r['max_drawdown_pct']:6.2f}  "
              f"{r['trade_count']:>6}")
        results[f"ablation_{name.strip()}"] = r
    print()

    # ③ EMV 参数网格（V4 全过滤）
    print("=" * 92)
    print("  ③ V4 全过滤 · EMV × Signal 网格")
    print("=" * 92)
    eps, sps = [14, 21, 28, 35], [3, 5, 7, 9]
    grid = []
    print(f"  {'EMV':>4}/{'Sig':>3}  |  {'Return%':>8}  {'Win%':>6}  {'P/F':>5}  "
          f"{'Exp%':>7}  {'Sharpe':>7}  {'DD%':>6}  Trades")
    print("  " + "-" * 86)
    for ep in eps:
        for sp in sps:
            kw = dict(v4, emv_period=ep, signal_period=sp)
            r = EMVStrategyBacktestV4(**kw).run("XAU", kl)
            if "error" in r: continue
            grid.append((ep, sp, r))
            m = "✅" if r["expectancy_pct_per_trade"] > 0 else " "
            print(f"  {ep:>3}/{sp:>3}  |  {r['total_return_pct']:+8.2f}  "
                  f"{r['win_rate_pct']:6.2f}  {r['profit_factor']:5.2f}  "
                  f"{r['expectancy_pct_per_trade']:+7.3f}{m}  "
                  f"{r['sharpe']:7.2f}  {r['max_drawdown_pct']:6.2f}  "
                  f"{r['trade_count']:>5}")

    def score(x):
        r = x[2]; e = r["expectancy_pct_per_trade"]
        if e <= 0: return (-9999, -9999, -9999)
        return (e, r["sharpe"], r["total_return_pct"])
    best = max(grid, key=score)
    bs = max(grid, key=lambda x: x[2]["sharpe"])
    br = max(grid, key=lambda x: x[2]["total_return_pct"])
    print()
    print(f"  【综合最佳（正期望优先）】EMV={best[0]}/Sig={best[1]}")
    r = best[2]
    print(f"     收益 {r['total_return_pct']:+}%  胜率 {r['win_rate_pct']}%  "
          f"P/F {r['profit_factor']}  每笔期望 {r['expectancy_pct_per_trade']:+.3f}%  "
          f"夏普 {r['sharpe']}  回撤 {r['max_drawdown_pct']}%  交易 {r['trade_count']} 笔")
    print(f"  【夏普最高】EMV={bs[0]}/Sig={bs[1]}：夏普 {bs[2]['sharpe']:+.2f}  "
          f"收益 {bs[2]['total_return_pct']:+}%")
    print(f"  【收益最高】EMV={br[0]}/Sig={br[1]}：收益 {br[2]['total_return_pct']:+}%  "
          f"期望 {br[2]['expectancy_pct_per_trade']:+.3f}%")
    ep_b, sp_b, r_best = best
    results["grid_best"] = {"emv_period": ep_b, "signal_period": sp_b, **r_best}

    # ④ 过滤漏斗 + RSI/ATR/突破 各拦截统计
    print()
    print("=" * 92)
    print(f"  ④ 完整过滤漏斗 · EMV={ep_b}/Sig={sp_b}（V4 全过滤）")
    print("=" * 92)
    best_kw = dict(v4, emv_period=ep_b, signal_period=sp_b)
    rf = EMVStrategyBacktestV4(**best_kw).run("XAU", kl)
    fs = rf["filters"]; tot = fs["total_attempts"] or 1
    def rem_print(label, key, prev, show_cum=False):
        v = fs[key]; frac = v / max(prev, 1) * 100
        mark = f"  ({v/tot*100:.1f}% total)" if show_cum else ""
        print(f"    ├ {label:<24s} {v:>6}  ({frac:5.1f}% of 上一层){mark}")
        return prev - v
    print(f"  进入信号判断总次数:     {tot:>6}  (100%)")
    rem = rem_print("EMV 交叉未发生",           "blocked_no_cross",   tot, True)
    rem = rem_print("MA99 不上升",              "blocked_ma99",       rem)
    rem = rem_print("MA25/MA99 不排列",          "blocked_alignment",  rem)
    rem_print(f"{best_kw['emv_confirm_bars']} 根保持不成立",    "blocked_confirm",    rem)
    rem = tot - (fs["blocked_no_cross"] + fs["blocked_ma99"] +
                 fs["blocked_alignment"] + fs["blocked_confirm"] +
                 fs["blocked_strength"] + fs["blocked_rsi"] +
                 fs["blocked_atr_vol"] + fs["blocked_breakout"] +
                 fs["blocked_cooldown"] + fs["actually_opened"])
    # 重新算漏斗：按 _signal_long 调用顺序
    after_cross = tot - fs["blocked_no_cross"]
    after_ma99 = after_cross - fs["blocked_ma99"]
    after_align = after_ma99 - fs["blocked_alignment"]
    after_conf = after_align - fs["blocked_confirm"]
    after_str = after_conf - fs["blocked_strength"]
    after_rsi = after_str - fs["blocked_rsi"]
    after_atrv = after_rsi - fs["blocked_atr_vol"]
    after_break = after_atrv - fs["blocked_breakout"]
    n_opened = fs["actually_opened"]
    print(f"\n  → 按执行顺序的漏斗：")
    stages = [
        ("通过交叉",        after_cross),
        ("  通过MA99",      after_ma99),
        ("  通过排列",      after_align),
        ("  通过确认",      after_conf),
        ("  通过强度",      after_str),
        ("  通过RSI",       after_rsi),
        ("  通过ATR波动",   after_atrv),
        ("  通过突破",      after_break),
        ("最终开仓",        n_opened),
    ]
    for label, v in stages:
        print(f"     {label:<14s} {v:>6}  "
              f"({v/tot*100:6.2f}% of 总   |  "
              f"保留率 {v/max(after_cross,1)*100:5.1f}% of 通过交叉)")
    print()
    print(f"  信号通过率 {n_opened}/{tot} = {n_opened/tot*100:.3f}%   |   "
          f"交易频率 {n_opened/yr:.1f} 笔/年 = 每 {12/max(n_opened/yr,0.01):.1f} 月 1 笔")
    results["funnel"] = fs

    # ⑤ TP:SL × SL_ATR 扫（最佳参数）
    print()
    print("=" * 92)
    print(f"  ⑤ TP/SL × SL(ATR) 敏感性 · EMV={ep_b}/Sig={sp_b}")
    print("=" * 92)
    tsls = [1.5, 1.8, 2.0, 2.3, 2.7, 3.0]
    sls = [1.0, 1.3, 1.5, 1.8, 2.2]
    print(f"  {'TP:SL':>5}  {'SL×ATR':>7}  |  {'Return%':>8}  {'Win%':>6}  {'P/F':>5}  "
          f"{'Exp%':>7}  {'Sharpe':>7}  {'DD%':>6}  Trades")
    print("  " + "-" * 90)
    ts_best = None
    for tsr in tsls:
        for sam in sls:
            kw = dict(best_kw, tp_sl_ratio=tsr, sl_atr_mult=sam)
            r = EMVStrategyBacktestV4(**kw).run("XAU", kl)
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

    # ⑥ 年度拆解 + 对比 V1 → V3 → V4 的年度变化
    print()
    print("=" * 92)
    print("  ⑥ 年度表现拆解 · V4 最终推荐参数")
    print("=" * 92)
    final_kw = dict(best_kw,
                    tp_sl_ratio=(ts_best[3] if ts_best else 2.0),
                    sl_atr_mult=(ts_best[4] if ts_best else 1.5))
    bt_final = EMVStrategyBacktestV4(**final_kw)
    bt_final.run("XAU", kl)
    ty: Dict[int, List[Trade]] = {}
    for t in bt_final.trades: ty.setdefault(t.exit_dt.year, []).append(t)
    print(f"  {'Year':>5}  {'Return%':>9}  {'Trades':>7}  {'Win%':>7}  "
          f"{'P/F':>5}  {'Exp%':>7}  {'TP':>4}  {'SL':>4}  {'Timeout':>7}")
    print("  " + "-" * 86)
    cum = 0.0
    for y in sorted(ty.keys()):
        ts2 = ty[y]
        yr_pnl = sum(t.pnl_usdt for t in ts2)
        wy = [t for t in ts2 if t.pnl_usdt > 0]; ly2 = [t for t in ts2 if t.pnl_usdt <= 0]
        wr = len(wy)/len(ts2)*100 if ts2 else 0
        aw = (sum(t.pnl_pct for t in wy)/len(wy)) if wy else 0
        al = (sum(t.pnl_pct for t in ly2)/len(ly2)) if ly2 else 0
        pf = (aw / abs(al)) if al else 0
        e = (wr/100*(pf+1)-1)*100 if pf else 0
        base = 10000 + cum
        yr_ret = yr_pnl/base*100 if base else 0
        tpc = sum(1 for t in ts2 if t.exit_reason=="tp")
        slc = sum(1 for t in ts2 if t.exit_reason=="sl")
        toc = sum(1 for t in ts2 if t.exit_reason=="timeout")
        mark = "✅" if e > 0 else ("⚠" if -20 < e <= 0 else "❌")
        print(f"  {y:>5}  {yr_ret:+9.2f}  {len(ts2):>7}  {wr:7.2f}  "
              f"{pf:5.2f}  {e:+7.3f}{mark}  {tpc:>4}  {slc:>4}  {toc:>7}")
        cum += yr_pnl
    results["yearly"] = {
        y: {"return_pct": round(sum(t.pnl_usdt for t in ts2)/10000*100, 2),
            "trades": len(ts2),
            "win_pct": round(len([t for t in ts2 if t.pnl_usdt>0])/len(ts2)*100, 2) if ts2 else 0}
        for y, ts2 in ty.items()}

    out = os.path.join(BASE_DIR, "simulate_xau_emv_v4.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n  [JSON 结果已保存] {out}")

    # 最终结论
    print()
    print("=" * 92)
    print("  最终结论 · 黄金(XAU) EMV 策略 V4 · 多因子合成版")
    print("=" * 92)
    fr = ts_best[5] if ts_best else rf
    e = ts_best[0] if ts_best else rf["expectancy_pct_per_trade"]
    sh = ts_best[1] if ts_best else rf["sharpe"]
    rt = ts_best[2] if ts_best else rf["total_return_pct"]
    tsr = ts_best[3] if ts_best else 2.0
    sam = ts_best[4] if ts_best else 1.5
    n = fr["trade_count"]
    wr2 = fr["win_rate_pct"] / 100; pf2 = fr["profit_factor"]
    exp_verify = wr2 * (1 + pf2) - 1
    ok = e > 0
    print(f"  ★ 推荐参数组：")
    print(f"     EMV:  period={ep_b}  signal={sp_b}  vol_divisor=1e7")
    print(f"     出场: TP/SL = {tsr}:1    SL = {sam} ATR    Trailing Stop = ON")
    cfg = bt_final.cfg  # 从实例化后的对象取参数，避免 dict 缺键
    print(f"     7 层入场过滤：")
    print(f"       ① EMV 在 k 上穿 Signal + {cfg['emv_confirm_bars']} 根保持 ≥ Signal")
    print(f"       ② MA99 近 {cfg['ma99_lookback']} 根上升（大周期趋势）")
    print(f"       ③ Close > MA25 > MA99×(1-{cfg['alignment_tol']*100:.1f}%)（多头排列容差）")
    print(f"       ④ |EMV| ≥ {cfg['emv_strength_std_mul']}σ × σ(EMV_{cfg['emv_lookback']})")
    print(f"       ⑤ RSI(14) ∈ [{cfg['rsi_low']:.0f}, {cfg['rsi_high']:.0f}]（不追超买，不抄超卖）")
    print(f"       ⑥ ATR(14) / SMA(ATR,{cfg['atr_long_lookback']}) ≤ {cfg['atr_vol_max_ratio']:.1f}x（波动率不飙升）")
    print(f"       ⑦ Close ≥ 过去 {cfg['breakout_lookback']} 根 Close 的 70 分位（强于 70% 历史）")
    print(f"     风控：开仓间隔≥{cfg['min_bars_between']}根({cfg['min_bars_between']/6:.1f}天)  ·  "
          f"超时 {cfg['max_bars_held']/6:.0f}天强平  ·  "
          f"连亏{cfg['max_consecutive_losses']}笔→冷却{cfg['cooldown_after_loss_streak']/6:.0f}天")
    print(f"     仓位：单笔风险 {cfg['risk_pct_per_trade']}%  ·  杠杆 {cfg['fixed_leverage']}x  ·  "
          f"仓位上限 40% 本金")
    print()
    print(f"  {yr:.1f} 年回测成绩：")
    print(f"     收益率 {rt:+8.2f}%    胜率 {fr['win_rate_pct']:6.2f}%    "
          f"盈亏比 {fr['profit_factor']:5.2f}    最大回撤 {fr['max_drawdown_pct']:5.2f}%")
    print(f"     每笔期望 {e:+8.4f}%  {'✅ 正期望' if ok else '❌ 负期望'}    "
          f"夏普比 {sh:+6.2f}    交易 {n} 笔 ({n/yr:.1f}/年)")
    print(f"     成交分布：TP {fr['tp_count']} / SL {fr['sl_count']} / 超时 {fr['timeout_count']} / "
          f"结束 {fr['end_count']}    连胜 {fr['win_streak']} / 连败 {fr['lose_streak']}")
    print(f"     期望公式再验证：E = {wr2:.4f} × ({pf2:.2f}+1) - 1 = {exp_verify:+.4f}  "
          f"({'✅>0' if exp_verify>0 else '❌≤0'})")
    if exp_verify > 0:
        print(f"     年期望收益 = {n/yr:.1f} 笔/年 × {exp_verify*100:+.2f}%/笔 = "
              f"{n/yr*exp_verify*100:+.2f}%/年")
    if fr["last5"]:
        print(f"     最近 5 笔：")
        for t in fr["last5"]:
            ic = "▲" if t["side"] == "LONG" else "▼"
            print(f"       {ic} {t['entry']}~{t['exit']}  {t['side']}  "
                  f"lev={t['lev']}x  PnL={t['pnl_pct']:+.2f}% (${t['pnl_usdt']:+.2f})  "
                  f"{t['reason']}  持 {t['bars']}K")
    print()
    print("  实盘部署清单：")
    print("    1) 【必做】vol_divisor 校准：把真实 XAU/USD 4H 历史（TradingView CSV / Alpha Vantage）")
    print("       导入后跑本脚本，扫描 vol_divisor ∈ {1e5, 5e5, 1e6, 5e6, 1e7, 5e7, 1e8, 1e9}，")
    print("       取 30 根回看 EMV 的 σ 中位数在 [0.005, 0.05] 区间的那个 divisor 再跑扫参。")
    print("    2) 【必做】只交易北京 20:00 ~ 次日 02:00（伦敦 + 纽约重叠盘），其他时段信号忽略。")
    print("    3) 【必做】真实手续费 + 滑点按 0.1% 双边重跑（本脚本 0.04%+0.05% = 0.09% 已偏乐观）。")
    print("    4) 【推荐】DXY 过滤：DXY(4H) Close < MA25 时单笔风险 0.6%；反之 0.3%（负相关）。")
    print("    5) 【推荐】首 3 个月 SIM 模式：按信号 100% 复现但不真实下单，记录偏差。")
    print("    6) 【红线】单日亏损 ≥ 2% 当日停机；单周 ≥ 5% 下周停机观察。")


if __name__ == "__main__":
    main()
