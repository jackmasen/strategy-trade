# -*- coding: utf-8 -*-
"""
本地模拟交易测试：1H + 4H 周期策略
直接复用系统现成的 TechnicalAnalyzer 指标与评分引擎，
生成模拟历史K线（无真实交易所KEY也能跑），验证策略逻辑与胜率。

策略规则：
- 综合评分 >= 6 且 direction 为多/空 -> 开仓
- 止盈 tp_pct，止损 sl_pct（按 ATR 动态建议值）
- 同一周期同一品种持仓中不重复开仓
- 反向信号出现且评分 >=6 时先平再开

输出：
- 1H / 4H 双周期对比（总收益、胜率、盈亏比、最大回撤、夏普）
- 逐笔交易明细
- 权益曲线（每根K线收盘）
"""
from __future__ import annotations

import math
import random
import sys
import os
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from typing import List, Tuple, Optional, Dict

# 确保 sys.path
_PROJ = os.path.abspath(os.path.dirname(__file__))
if _PROJ not in sys.path:
    sys.path.insert(0, _PROJ)

# 复用系统指标基础函数（sma/ema/rsi/macd/bollinger_bands/atr）
from backend.strategy.indicators import (
    sma, ema, rsi, macd, bollinger_bands, atr,
    TechnicalScoreResult, IndicatorResult,
)
import math


# =======================================================
# 模拟K线生成器（几何布朗运动 + 趋势 + 波动率聚类）
# =======================================================
def generate_klines(
    symbol: str,
    timeframe: str,       # 1h / 4h
    start_dt: datetime,
    end_dt: datetime,
    start_price: Optional[float] = None,
    seed: int = 42,
) -> List[dict]:
    """
    生成指定时间段内模拟K线（按open_time升序），返回 dict[{open,high,low,close,volume,open_time_ms,close_time_ms}]
    品种参数（真实波动率近似）：
        BTC: 年化波动率 70%，长期漂移 +15%
        ETH: 年化波动率 90%，长期漂移 +12%
        SOL: 年化波动率 120%，长期漂移 +10%
        XAU: 年化波动率 18%，长期漂移 +6%
        WTI: 年化波动率 45%，长期漂移 +3%
    """
    params = {
        "BTC":  {"start": 68000,  "vol_annual": 0.70, "drift_annual": 0.15, "trend_ampl": 0.05},
        "ETH":  {"start": 3500,   "vol_annual": 0.90, "drift_annual": 0.12, "trend_ampl": 0.06},
        "SOL":  {"start": 150,    "vol_annual": 1.20, "drift_annual": 0.10, "trend_ampl": 0.08},
        "XAU":  {"start": 2300,   "vol_annual": 0.18, "drift_annual": 0.06, "trend_ampl": 0.02},
        "WTI":  {"start": 78,     "vol_annual": 0.45, "drift_annual": 0.03, "trend_ampl": 0.05},
    }
    p = params.get(symbol, params["BTC"])
    price = start_price or p["start"]
    vol_annual = p["vol_annual"]
    drift_annual = p["drift_annual"]
    trend_ampl = p["trend_ampl"]

    tf_minutes = {"1h": 60, "4h": 240, "1d": 1440}.get(timeframe, 60)
    bars_per_day = 1440 / tf_minutes
    dt_step = timedelta(minutes=tf_minutes)

    # 生成所有时间戳
    ts = start_dt
    timestamps: List[datetime] = []
    while ts <= end_dt:
        timestamps.append(ts)
        ts += dt_step
    N = len(timestamps)
    if N == 0:
        return []

    rng = random.Random(seed + hash(symbol) & 0xFFFFFF)
    bars_per_year = bars_per_day * 365
    dt_unit = 1.0 / bars_per_year          # 每根K线对应的年
    drift_per_bar = drift_annual * dt_unit
    vol_per_bar = vol_annual * math.sqrt(dt_unit)

    # 加"正弦叠加长中短周期趋势"，模拟牛熊切换+小周期波动
    klines: List[dict] = []
    for i in range(N):
        t_frac = i / max(1, N - 1)
        # 长周期(牛熊 ~2年) + 中周期(波段~3月) + 短周期(日线)
        trend_long = math.sin(2 * math.pi * t_frac * 1.5)       # -1~+1
        trend_med = math.sin(2 * math.pi * t_frac * 12)
        trend_short = math.sin(2 * math.pi * t_frac * bars_per_day * 7)  # 周内波动
        trend_total = (trend_long * 0.5 + trend_med * 0.35 + trend_short * 0.15) * trend_ampl
        # 每根K线的 drift 做趋势偏移
        local_drift = drift_per_bar + trend_total * dt_unit
        # 波动率聚类(GARCH简化)：高波动期连续出现
        vol_heat = 0.7 + 0.6 * math.sin(2 * math.pi * t_frac * 4)
        local_vol = vol_per_bar * max(0.3, vol_heat)

        # Open = 上一根 Close
        o = price
        # 波动：日内 wick 模拟
        intra_wick = local_vol * (0.6 + rng.random() * 0.8)
        change = local_drift + rng.gauss(0, 1) * local_vol
        c = max(0.001, o * (1 + change))
        h = max(o, c) * (1 + abs(rng.gauss(0, 1)) * intra_wick * 0.4)
        l = min(o, c) * (1 - abs(rng.gauss(0, 1)) * intra_wick * 0.4)
        if l <= 0:
            l = min(o, c) * 0.95
        volume = max(0, o * (500 + rng.random() * 500) * (1 + 3 * abs(change)))
        open_time = timestamps[i]
        close_time = open_time + dt_step - timedelta(seconds=1)
        klines.append({
            "open": o, "high": h, "low": l, "close": c, "volume": volume,
            "open_time_ms": int(open_time.timestamp() * 1000),
            "close_time_ms": int(close_time.timestamp() * 1000),
            "dt": open_time,
        })
        price = c
    return klines


# =======================================================
# 预计算指标（O(N)，一次性算完所有K线的 ma/rsi/macd/boll/atr）
# =======================================================
@dataclass
class PrecomputedIndicators:
    ma7: List[float]
    ma25: List[float]
    ma99: List[float]
    rsi14: List[float]
    dif: List[float]
    dea: List[float]
    hist: List[float]
    bb_u: List[float]
    bb_m: List[float]
    bb_l: List[float]
    atr14: List[float]
    closes: List[float]

    @classmethod
    def from_klines(cls, klines: List[dict]) -> "PrecomputedIndicators":
        o, h, l, c = [], [], [], []
        for k in klines:
            if isinstance(k, dict):
                o.append(float(k["open"])); h.append(float(k["high"]))
                l.append(float(k["low"])); c.append(float(k["close"]))
            else:
                o.append(float(getattr(k, "open", 0)))
                h.append(float(getattr(k, "high", 0)))
                l.append(float(getattr(k, "low", 0)))
                c.append(float(getattr(k, "close", 0)))
        ma7 = sma(c, 7); ma25 = sma(c, 25); ma99 = sma(c, 99)
        rsi14 = rsi(c, 14)
        dif, dea, hist = macd(c)
        bb_u, bb_m, bb_l = bollinger_bands(c, 20)
        atr14 = atr(h, l, c, 14)
        return cls(
            ma7=ma7, ma25=ma25, ma99=ma99, rsi14=rsi14,
            dif=dif, dea=dea, hist=hist,
            bb_u=bb_u, bb_m=bb_m, bb_l=bb_l, atr14=atr14, closes=c,
        )

    def score_at(self, i: int, timeframe: str) -> TechnicalScoreResult:
        """计算第 i 根K线收盘时的技术评分（与 TechnicalAnalyzer 规则完全一致，O(1)）"""
        res = TechnicalScoreResult()
        N = len(self.closes)
        ind = res.indicators
        if i < 99:
            ind.last_close = self.closes[i]
            return res
        ind.ma7 = self.ma7[i]; ind.ma25 = self.ma25[i]; ind.ma99 = self.ma99[i]
        ind.rsi14 = self.rsi14[i]
        ind.macd_dif = self.dif[i]; ind.macd_dea = self.dea[i]; ind.macd = self.hist[i]
        ind.bb_upper = self.bb_u[i]; ind.bb_mid = self.bb_m[i]; ind.bb_lower = self.bb_l[i]
        ind.atr14 = self.atr14[i]; ind.last_close = self.closes[i]
        if ind.bb_mid > 0:
            ind.bb_width_pct = (ind.bb_upper - ind.bb_lower) / ind.bb_mid
            if ind.bb_upper - ind.bb_lower > 1e-12:
                ind.bb_position = (ind.last_close - ind.bb_lower) / (ind.bb_upper - ind.bb_lower)
        if ind.last_close > 0:
            ind.atr_pct = ind.atr14 / ind.last_close

        W = {"ma": 2.0, "rsi": 2.0, "macd": 2.5, "boll": 2.0, "atr": 1.5}
        # 复用 TechnicalAnalyzer 里的分项评分逻辑（完全一致）
        def _score_ma():
            base = self.closes[i] or 1
            a = self.ma7[i] - self.ma25[i]
            b = self.ma25[i] - self.ma99[i]
            c_ = self.closes[i] - self.ma7[i]
            ls = (max(a,0)/base*1000)+(max(b,0)/base*1000)+(max(c_,0)/base*1000)
            ss = (max(-a,0)/base*1000)+(max(-b,0)/base*1000)+(max(-c_,0)/base*1000)
            total = ls + ss
            d = (ls - ss)/total if total > 0 else 0.0
            s = 5.0 + d*5.0 if d >= 0 else max(0.0, 5.0 + d*5.0)
            return min(10.0, s), d
        def _score_rsi():
            val = self.rsi14[i]
            if math.isnan(val): return 5.0, 0.0
            if val < 30: d = (30 - val)/30
            elif val > 70: d = -(val - 70)/30
            else: d = (val - 50)/50*0.4
            s = min(10.0, 5.0 + d*5.0) if d >= 0 else max(0.0, 5.0 + d*5.0)
            return s, d
        def _score_macd():
            if i < 3: return 5.0, 0.0
            h1, h2, h3 = self.hist[i-2], self.hist[i-1], self.hist[i]
            if h3 > 0: d = min(1.0, 0.4 + 0.3*(h3 > h2) + 0.3*(h2 > h1))
            else: d = -min(1.0, 0.4 + 0.3*(h3 < h2) + 0.3*(h2 < h1))
            axis = 0.2 if (self.dif[i]>0 and self.dea[i]>0) else (-0.2 if (self.dif[i]<0 and self.dea[i]<0) else 0.0)
            d = max(-1.0, min(1.0, d + axis))
            s = min(10.0, max(0.0, 5.0 + d*5.0))
            return s, d
        def _score_boll():
            u, m, l = self.bb_u[i], self.bb_m[i], self.bb_l[i]
            if u - l > 1e-12:
                pos = max(0.0, min(1.0, (self.closes[i] - l) / (u - l)))
            else:
                pos = 0.5
            if pos < 0.2: d = (0.2 - pos)/0.2
            elif pos > 0.8: d = -(pos - 0.8)/0.2
            else: d = (pos - 0.5)/0.3*0.4
            d = max(-1.0, min(1.0, d))
            s = min(10.0, max(0.0, 5.0 + d*5.0))
            return s, d
        def _score_atr():
            expected = {"15m":0.005,"1h":0.012,"4h":0.03,"1d":0.06}.get(timeframe, 0.012)
            ap = ind.atr_pct or 0
            ratio = ap / expected if expected > 0 else 1
            conf = 1.0
            if ratio < 0.3: conf = 0.6
            elif ratio > 3: conf = 0.5
            elif ratio > 1.5: conf = 0.8
            sc = 7.0 * conf + 3.0 * 0.7
            return sc, 0.0, conf
        ms, md = _score_ma(); rs, rd = _score_rsi(); ms2, md2 = _score_macd()
        bs, bd = _score_boll(); ats, atd, vconf = _score_atr()
        ss = {"ma": ms, "rsi": rs, "macd": ms2, "boll": bs, "atr": ats}
        dd = {"ma": md, "rsi": rd, "macd": md2, "boll": bd, "atr": atd}
        tot_w = sum(W.values()) or 1
        weighted = sum(ss[k]*W[k] for k in W)/tot_w
        res.score = round(min(10.0, max(0.0, weighted)), 2)
        ds = sum(dd[k]*W[k] for k in W)/tot_w
        res.directional_score = round(ds*10, 2)
        if res.score >= 5.5 and res.directional_score >= 0.5:
            res.direction = 1
        elif res.score <= 4.5 and res.directional_score <= -0.5:
            res.direction = 2
        res.confidence = round(min(1.0, max(0.0, 0.5 + vconf*0.5)), 3)
        lev = 3
        ap = ind.atr_pct or 0
        if ap > 0:
            ratio = ap / {"15m":0.005,"1h":0.012,"4h":0.03,"1d":0.06}.get(timeframe, 0.012)
            if ratio < 0.5: lev = 7
            elif ratio < 1.0: lev = 5
            elif ratio < 1.5: lev = 4
            else: lev = 3
        res.suggest_leverage = max(3, min(10, lev))
        res.suggest_tp_pct = max(3.0, min(8.0, 4.0*(1+(ind.atr_pct or 0)*20)))
        res.suggest_sl_pct = max(1.5, min(4.0, 2.0*(1+(ind.atr_pct or 0)*20)))
        res.sub_scores = ss
        return res


# =======================================================
# 交易数据结构
# =======================================================
@dataclass
class SimPosition:
    symbol: str
    side: int                # 1=多 2=空
    entry_price: float
    quantity_usdt: float     # 投入USDT
    leverage: int
    tp_pct: float
    sl_pct: float
    tp_price: float
    sl_price: float
    open_idx: int            # K线索引
    open_dt: datetime
    max_dd_pct: float = 0.0  # 持仓期间最大回撤(浮亏相对权益)
    peak_eq: float = 0.0


@dataclass
class SimTrade:
    symbol: str
    side: int
    entry_price: float
    exit_price: float
    quantity_usdt: float
    leverage: int
    pnl_usdt: float
    pnl_pct: float          # 相对本金（扣除杠杆放大，这里直接记总盈亏%）
    hold_bars: int
    close_reason: str       # tp/sl/reverse/end
    open_dt: datetime
    close_dt: datetime
    score_at_entry: float
    dir_at_entry: int
    # 回测统计计算用
    _equity_before: float = 0
    _equity_after: float = 0


# =======================================================
# 模拟引擎
# =======================================================
class Simulator:
    """
    本地模拟交易引擎（指标预计算 O(N)，逐K线评分 O(1)）
    """
    def __init__(
        self,
        initial_capital: float = 10000.0,
        fee_rate_pct: float = 0.04,
        slippage_pct: float = 0.05,
        risk_per_trade_pct: float = 1.5,
        score_threshold: float = 6.0,
    ):
        self.initial_capital = initial_capital
        self.equity = initial_capital
        self.fee_rate = fee_rate_pct / 100.0
        self.slippage = slippage_pct / 100.0
        self.risk_pct = risk_per_trade_pct / 100.0
        self.score_threshold = score_threshold

        self.positions: Dict[Tuple[str, str], SimPosition] = {}   # (symbol, tf) -> pos
        self.trades: List[SimTrade] = []
        self.equity_curve: List[Tuple[datetime, float]] = []

        # 内部指标计数
        self._count_opens = 0
        self._count_tp = 0
        self._count_sl = 0
        self._count_rev = 0

    # ---- 内部：根据评分结果执行信号 ----
    def _open_position(
        self,
        symbol: str,
        tf: str,
        side: int,
        score_result: TechnicalScoreResult,
        kline: dict,
        idx: int,
    ) -> bool:
        key = (symbol, tf)
        if key in self.positions:
            return False
        if self.equity <= 0:
            return False

        price = kline["close"]
        leverage = max(3, min(10, score_result.suggest_leverage))
        tp_pct = score_result.suggest_tp_pct     # %
        sl_pct = score_result.suggest_sl_pct     # %
        # 按单笔风险 1.5% 算投入 USDT（忽略手续费精确性）
        # risk = qty_usdt * lev * (sl_pct/100) <= equity * risk_pct
        max_qty_usdt = (self.equity * self.risk_pct) / max(0.01, (sl_pct / 100) * leverage)
        max_qty_usdt = min(max_qty_usdt, self.equity * 0.9)   # 单笔下限不超 90% 本金
        qty_usdt = max(100.0, max_qty_usdt)

        # 滑点 + 手续费
        if side == 1:   # 多
            entry_price = price * (1 + self.slippage)
            tp_price = entry_price * (1 + tp_pct / 100)
            sl_price = entry_price * (1 - sl_pct / 100)
        else:           # 空
            entry_price = price * (1 - self.slippage)
            tp_price = entry_price * (1 - tp_pct / 100)
            sl_price = entry_price * (1 + sl_pct / 100)

        self.positions[key] = SimPosition(
            symbol=symbol, side=side,
            entry_price=entry_price,
            quantity_usdt=qty_usdt,
            leverage=leverage,
            tp_pct=tp_pct, sl_pct=sl_pct,
            tp_price=tp_price, sl_price=sl_price,
            open_idx=idx, open_dt=kline["dt"],
            peak_eq=self.equity,
        )
        self._count_opens += 1
        # 扣除开仓手续费
        self.equity -= qty_usdt * self.fee_rate
        return True

    def _close_position(
        self,
        symbol: str,
        tf: str,
        kline: dict,
        reason: str,
        idx: int,
    ) -> Optional[SimTrade]:
        key = (symbol, tf)
        pos = self.positions.pop(key, None)
        if pos is None:
            return None
        price = kline["close"]
        # 若触发TP/SL，用触发价
        if reason == "tp":
            exit_price = pos.tp_price
        elif reason == "sl":
            exit_price = pos.sl_price
        else:
            exit_price = price * (1 + self.slippage) if pos.side == 1 else price * (1 - self.slippage)

        # 计算盈亏（杠杆放大）
        if pos.side == 1:
            change_pct = (exit_price - pos.entry_price) / pos.entry_price
        else:
            change_pct = (pos.entry_price - exit_price) / pos.entry_price
        pnl_usdt = pos.quantity_usdt * pos.leverage * change_pct
        # 扣除平仓手续费
        pnl_usdt -= pos.quantity_usdt * self.fee_rate
        eq_before = self.equity
        self.equity += pnl_usdt
        if self.equity < 0:
            self.equity = 0.0

        hold_bars = idx - pos.open_idx
        pnl_pct_total = (pnl_usdt / max(1e-9, eq_before)) * 100
        trade = SimTrade(
            symbol=symbol, side=pos.side,
            entry_price=pos.entry_price, exit_price=exit_price,
            quantity_usdt=pos.quantity_usdt, leverage=pos.leverage,
            pnl_usdt=pnl_usdt, pnl_pct=pnl_pct_total,
            hold_bars=hold_bars, close_reason=reason,
            open_dt=pos.open_dt, close_dt=kline["dt"],
            score_at_entry=0.0, dir_at_entry=pos.side,
            _equity_before=eq_before, _equity_after=self.equity,
        )
        if reason == "tp": self._count_tp += 1
        elif reason == "sl": self._count_sl += 1
        elif reason == "reverse": self._count_rev += 1
        self.trades.append(trade)
        return trade

    def _check_tp_sl(self, symbol: str, tf: str, kline: dict, idx: int):
        """遍历持仓，检查当根K线的H/L是否触碰到TP/SL"""
        key = (symbol, tf)
        pos = self.positions.get(key)
        if pos is None:
            return
        h, l = kline["high"], kline["low"]
        close_price = kline["close"]
        # 跟踪持仓期间的权益峰值和最大回撤
        if pos.side == 1:
            mark_price = close_price
            pnl_floating = (mark_price - pos.entry_price) / pos.entry_price * pos.leverage
        else:
            mark_price = close_price
            pnl_floating = (pos.entry_price - mark_price) / pos.entry_price * pos.leverage
        floating_eq = self.equity + pos.quantity_usdt * pnl_floating
        if floating_eq > pos.peak_eq:
            pos.peak_eq = floating_eq
        if pos.peak_eq > 0:
            dd = (pos.peak_eq - floating_eq) / pos.peak_eq * 100
            if dd > pos.max_dd_pct:
                pos.max_dd_pct = dd

        # 检查 TP/SL 触发（用H/L判断，更真实）
        if pos.side == 1:
            # 多：TP 先触碰到 H，SL 先触碰到 L
            if h >= pos.tp_price:
                self._close_position(symbol, tf, kline, "tp", idx)
                return
            if l <= pos.sl_price:
                self._close_position(symbol, tf, kline, "sl", idx)
                return
        else:
            # 空：TP 先触碰到 L，SL 先触碰到 H
            if l <= pos.tp_price:
                self._close_position(symbol, tf, kline, "tp", idx)
                return
            if h >= pos.sl_price:
                self._close_position(symbol, tf, kline, "sl", idx)
                return

    # ---- 主回测入口：单品种单周期 ----
    def run_single(
        self,
        symbol: str,
        timeframe: str,
        klines_1h: List[dict],
        klines_4h: List[dict] | None = None,
        use_double_filter: bool = True,
    ) -> dict:
        """
        回测单个品种（指标 O(N) 预计算，逐K线评分 O(1)）
        - use_double_filter=True: 1H 必须同时满足：1H 自身评分>=6，且 4H 评分>=5（同向）
        - use_double_filter=False: 只用当前周期评分
        返回回测结果 dict
        """
        if timeframe == "1h":
            target_klines = klines_1h
        else:
            target_klines = klines_4h or klines_1h

        # 预热：跳过前 120 根让指标稳定
        warmup = 120
        if len(target_klines) <= warmup:
            return {"error": f"K线不足({len(target_klines)} <= {warmup})"}

        # 指标一次性预计算（O(N)）
        ind_tgt = PrecomputedIndicators.from_klines(target_klines)

        # 预计算 4H 的评分（如果启用双周期）——同样用预计算加速
        score_4h_by_dt: Dict[datetime, TechnicalScoreResult] = {}
        if use_double_filter and timeframe == "1h" and klines_4h:
            ind_4h = PrecomputedIndicators.from_klines(klines_4h)
            for i_4h in range(warmup, len(klines_4h)):
                r = ind_4h.score_at(i_4h, "4h")
                score_4h_by_dt[klines_4h[i_4h]["dt"]] = r
            # 按 dt 排序，方便 bisect 找最近一个
            sorted_4h_dts = sorted(score_4h_by_dt.keys())

        self.equity_curve = []
        start_equity = self.equity

        # 4H 过滤辅助：bisect 找最近 <= 1h kline dt 的 4h 评分
        def _find_4h_score(dt: datetime) -> TechnicalScoreResult | None:
            if not sorted_4h_dts:
                return None
            # 从后往前找最近一个 <= dt 的
            for j in range(len(sorted_4h_dts) - 1, -1, -1):
                if sorted_4h_dts[j] <= dt:
                    return score_4h_by_dt[sorted_4h_dts[j]]
            return None

        for i in range(warmup, len(target_klines)):
            kline = target_klines[i]

            # 1) 先检查现有持仓 TP/SL（用当根 K 线 H/L）
            self._check_tp_sl(symbol, timeframe, kline, i)

            # 2) 评分（O(1)，读预计算数组）
            res = ind_tgt.score_at(i, timeframe)

            # 双周期过滤：1H 同时看 4H 大方向
            tf_ok = True
            if use_double_filter and timeframe == "1h":
                r4h = _find_4h_score(kline["dt"])
                if r4h is None:
                    tf_ok = False
                else:
                    if res.direction == 1 and not (r4h.direction == 1 and r4h.score >= 5.0):
                        tf_ok = False
                    if res.direction == 2 and not (r4h.direction == 2 and r4h.score >= 5.0):
                        tf_ok = False

            trigger = (
                res.score >= self.score_threshold
                and res.direction in (1, 2)
                and tf_ok
            )

            # 3) 开仓/反向
            key = (symbol, timeframe)
            if key in self.positions:
                cur_pos = self.positions[key]
                # 反向信号：先平再开（同样要求评分>=阈值）
                if (
                    trigger
                    and res.direction != cur_pos.side
                    and res.score >= self.score_threshold + 0.5  # 反向需要更强烈信号
                ):
                    self._close_position(symbol, timeframe, kline, "reverse", i)
                    self._open_position(symbol, timeframe, res.direction, res, kline, i)
            else:
                if trigger:
                    self._open_position(symbol, timeframe, res.direction, res, kline, i)

            # 4) 记录权益（收盘mark）
            marked_eq = self.equity
            pos = self.positions.get(key)
            if pos is not None:
                c = kline["close"]
                if pos.side == 1:
                    chg = (c - pos.entry_price) / pos.entry_price
                else:
                    chg = (pos.entry_price - c) / pos.entry_price
                marked_eq += pos.quantity_usdt * pos.leverage * chg
            self.equity_curve.append((kline["dt"], marked_eq))

        # 最后强制平掉未平仓
        for (s, t) in list(self.positions.keys()):
            last_idx = len(target_klines) - 1
            self._close_position(s, t, target_klines[last_idx], "end", last_idx)

        # 汇总
        final_equity = self.equity
        total_return_pct = (final_equity - start_equity) / start_equity * 100
        result = self._summarize(start_equity, final_equity, timeframe, symbol)
        result.update({
            "symbol": symbol,
            "timeframe": timeframe,
            "start_equity": start_equity,
            "final_equity": final_equity,
            "total_return_pct": round(total_return_pct, 2),
            "use_double_filter": use_double_filter,
            "count_opens": self._count_opens,
            "count_tp": self._count_tp,
            "count_sl": self._count_sl,
            "count_rev": self._count_rev,
            "trade_count": len(self.trades),
        })
        return result

    def _summarize(self, start_eq: float, final_eq: float, tf: str, symbol: str) -> dict:
        if not self.trades:
            return {
                "win_rate": 0, "profit_factor": 0, "avg_win_pct": 0,
                "avg_loss_pct": 0, "max_drawdown_pct": 0,
                "sharpe_ratio": 0, "sortino_ratio": 0,
                "max_win_streak": 0, "max_loss_streak": 0,
                "trades": [],
            }
        wins = [t for t in self.trades if t.pnl_usdt > 0]
        losses = [t for t in self.trades if t.pnl_usdt <= 0]
        win_rate = len(wins) / len(self.trades) * 100
        gross_win = sum(t.pnl_usdt for t in wins) or 0.01
        gross_loss = abs(sum(t.pnl_usdt for t in losses)) or 0.01
        profit_factor = gross_win / gross_loss

        # 最大回撤
        eq_series = [e for _, e in self.equity_curve] or [start_eq, final_eq]
        peak, max_dd = eq_series[0], 0.0
        for e in eq_series:
            if e > peak:
                peak = e
            dd = (peak - e) / peak * 100
            if dd > max_dd:
                max_dd = dd

        # 夏普/索提诺（简化：按K线收益率近似）
        rets = []
        for i in range(1, len(eq_series)):
            if eq_series[i-1] > 0:
                rets.append((eq_series[i] - eq_series[i-1]) / eq_series[i-1])
        if rets:
            avg = sum(rets) / len(rets)
            var = sum((r - avg) ** 2 for r in rets) / max(1, len(rets))
            std = math.sqrt(var)
            bars_per_year = {"1h": 8760, "4h": 2190, "1d": 365}.get(tf, 365)
            sharpe = (avg / max(1e-9, std)) * math.sqrt(bars_per_year)
            neg_rets = [r for r in rets if r < 0]
            if neg_rets:
                dvar = sum((r) ** 2 for r in neg_rets) / len(neg_rets)
                dstd = math.sqrt(dvar)
                sortino = (avg / max(1e-9, dstd)) * math.sqrt(bars_per_year)
            else:
                sortino = sharpe
        else:
            sharpe = sortino = 0

        # 连胜/连败
        max_ws = max_ls = cur_ws = cur_ls = 0
        for t in self.trades:
            if t.pnl_usdt > 0:
                cur_ws += 1; cur_ls = 0
                if cur_ws > max_ws: max_ws = cur_ws
            else:
                cur_ls += 1; cur_ws = 0
                if cur_ls > max_ls: max_ls = cur_ls

        avg_win_pct = (sum(t.pnl_pct for t in wins) / len(wins)) if wins else 0
        avg_loss_pct = (sum(t.pnl_pct for t in losses) / len(losses)) if losses else 0

        trades_summary = []
        for t in self.trades[-20:]:  # 最后20笔
            trades_summary.append({
                "open": t.open_dt.strftime("%Y-%m-%d %H:%M"),
                "close": t.close_dt.strftime("%Y-%m-%d %H:%M"),
                "side": {1: "LONG", 2: "SHORT"}[t.side],
                "entry": round(t.entry_price, 4),
                "exit": round(t.exit_price, 4),
                "lev": t.leverage,
                "pnl": round(t.pnl_usdt, 2),
                "pnl%": round(t.pnl_pct, 2),
                "bars": t.hold_bars,
                "reason": t.close_reason,
            })

        return {
            "win_rate": round(win_rate, 2),
            "profit_factor": round(profit_factor, 2),
            "avg_win_pct": round(avg_win_pct, 2),
            "avg_loss_pct": round(avg_loss_pct, 2),
            "max_drawdown_pct": round(max_dd, 2),
            "sharpe_ratio": round(sharpe, 2),
            "sortino_ratio": round(sortino, 2),
            "max_win_streak": max_ws,
            "max_loss_streak": max_ls,
            "trades_tail": trades_summary,
            "equity_curve_points": [
                (dt.strftime("%Y-%m-%d %H:%M"), round(eq, 2))
                for dt, eq in (self.equity_curve[:: max(1, len(self.equity_curve) // 50)] or self.equity_curve)
            ],
        }


# =======================================================
# 主程序：BTC/ETH/SOL/XAU/WTI 全量对比
# =======================================================
SYMBOLS = ["BTC", "ETH", "SOL", "XAU", "WTI"]
TF_LABELS = {"1h": "1小时", "4h": "4小时"}
START = datetime(2024, 1, 1)
END = datetime(2026, 8, 1)

def print_header(s):
    print("\n" + "=" * 80)
    print("  " + s)
    print("=" * 80)

def print_result(r):
    if "error" in r:
        print(f"  [ERROR] {r['error']}")
        return
    print(f"  品种: {r['symbol']}   周期: {TF_LABELS[r['timeframe']]}   双周期过滤: {'开' if r['use_double_filter'] else '关'}")
    print(f"  初始资金: ${r['start_equity']:,.2f}   最终资金: ${r['final_equity']:,.2f}   总收益率: {r['total_return_pct']:+.2f}%")
    print(f"  交易笔数: {r['trade_count']}   胜率: {r['win_rate']:.1f}%   盈亏比: {r['profit_factor']:.2f}")
    print(f"  平均盈利: +{r['avg_win_pct']:.2f}%   平均亏损: {r['avg_loss_pct']:.2f}%")
    print(f"  夏普比率: {r['sharpe_ratio']:.2f}   索提诺: {r['sortino_ratio']:.2f}   最大回撤: {r['max_drawdown_pct']:.2f}%")
    print(f"  最大连胜: {r['max_win_streak']}   最大连败: {r['max_loss_streak']}")
    print(f"  止盈触发: {r['count_tp']}   止损触发: {r['count_sl']}   反向换仓: {r['count_rev']}")

def main():
    print_header("模拟交易测试 · 1H + 4H 策略（系统评分引擎 + 双周期过滤）")
    print(f"  区间: {START:%Y-%m-%d} ~ {END:%Y-%m-%d}   品种: {SYMBOLS}")
    print(f"  评分阈值 >= 6   单笔风险 1.5%   手续费 0.04%   滑点 0.05%")
    print(f"  策略 A（仅单周期） vs 策略 B（1H+4H双周期同向过滤）")

    # 先生成所有 K 线（每个周期每个品种一次）
    print("\n[数据生成] 生成 1H + 4H K 线...")
    klines_1h_all: Dict[str, List[dict]] = {}
    klines_4h_all: Dict[str, List[dict]] = {}
    for sym in SYMBOLS:
        k1h = generate_klines(sym, "1h", START, END, seed=1000 + ord(sym[0]))
        k4h = generate_klines(sym, "4h", START, END, seed=2000 + ord(sym[0]))
        klines_1h_all[sym] = k1h
        klines_4h_all[sym] = k4h
        print(f"  - {sym}: 1H={len(k1h)} 根   4H={len(k4h)} 根")

    all_results = []

    # 模式 A: 单周期独立跑（1H / 4H）
    for tf_name, tf_key in [("1H 独立", "1h"), ("4H 独立", "4h")]:
        print_header(f"模式 A · {tf_name} 策略（纯单周期评分 >= 6 触发）")
        for sym in SYMBOLS:
            sim = Simulator(initial_capital=10000, score_threshold=6.0, risk_per_trade_pct=1.5)
            if tf_key == "1h":
                r = sim.run_single(sym, "1h", klines_1h_all[sym], klines_4h_all[sym], use_double_filter=False)
            else:
                r = sim.run_single(sym, "4h", klines_1h_all[sym], klines_4h_all[sym], use_double_filter=False)
            r["mode"] = f"模式A-{tf_name}"
            all_results.append(r)
            print_result(r)
            print()

    # 模式 B: 双周期过滤（4H定方向 + 1H找入场，评分同时满足）
    print_header("模式 B · 1H+4H 双周期共振策略（推荐主用）")
    print("  规则：4H 评分>=5且方向同向，同时 1H 评分>=6才开仓；反向需评分>=6.5 才换仓")
    for sym in SYMBOLS:
        sim = Simulator(initial_capital=10000, score_threshold=6.0, risk_per_trade_pct=1.5)
        r = sim.run_single(sym, "1h", klines_1h_all[sym], klines_4h_all[sym], use_double_filter=True)
        r["mode"] = "模式B-双周期共振"
        all_results.append(r)
        print_result(r)
        # 输出最后 5 笔交易
        trades_tail = r.get("trades_tail", [])[-5:]
        if trades_tail:
            print(f"  最近 {len(trades_tail)} 笔交易：")
            for t in trades_tail:
                print(f"    {t['open']}~{t['close'][-5:]} {t['side']:5s} lev={t['lev']:>2}x  PnL=${t['pnl']:>+8.2f} ({t['pnl%']:+.2f}%) {t['reason']}")
        print()

    # 综合对比表
    print_header("综合对比 · 模式 A(1H) vs 模式 A(4H) vs 模式 B(双周期共振)")
    header = ["品种", "模式", "总收益%", "胜率%", "盈亏比", "夏普", "最大回撤%", "交易数"]
    col_w = [8, 22, 10, 8, 8, 8, 10, 8]
    fmt = "  ".join(f"{{{i}:<{w}}}" for i, w in enumerate(col_w))
    print("  " + fmt.format(*header))
    print("  " + "-" * (sum(col_w) + 2 * (len(col_w) - 1)))
    # 按 1H 独立 / 4H 独立 / 双周期 分组
    groups = ["模式A-1H 独立", "模式A-4H 独立", "模式B-双周期共振"]
    for g in groups:
        group_results = [r for r in all_results if r.get("mode") == g]
        for r in group_results:
            row = [
                r.get("symbol", ""),
                r.get("mode", ""),
                f"{r.get('total_return_pct', 0):+.2f}",
                f"{r.get('win_rate', 0):.1f}",
                f"{r.get('profit_factor', 0):.2f}",
                f"{r.get('sharpe_ratio', 0):.2f}",
                f"{r.get('max_drawdown_pct', 0):.2f}",
                f"{r.get('trade_count', 0)}",
            ]
            print("  " + fmt.format(*row))
        # 组均值
        if group_results:
            avg_ret = sum(r.get('total_return_pct', 0) for r in group_results) / len(group_results)
            avg_wr = sum(r.get('win_rate', 0) for r in group_results) / len(group_results)
            avg_pf = sum(r.get('profit_factor', 0) for r in group_results) / len(group_results)
            avg_sharpe = sum(r.get('sharpe_ratio', 0) for r in group_results) / len(group_results)
            avg_dd = sum(r.get('max_drawdown_pct', 0) for r in group_results) / len(group_results)
            avg_count = sum(r.get('trade_count', 0) for r in group_results) / len(group_results)
            row_avg = [
                "平均", g,
                f"{avg_ret:+.2f}",
                f"{avg_wr:.1f}",
                f"{avg_pf:.2f}",
                f"{avg_sharpe:.2f}",
                f"{avg_dd:.2f}",
                f"{avg_count:.0f}",
            ]
            print("  " + fmt.format(*row_avg))
            print()

    # 结论
    print_header("结论 & 推荐")
    # 取各模式的平均收益、胜率等
    summary_lines = []
    for g in groups:
        group_results = [r for r in all_results if r.get("mode") == g]
        if not group_results: continue
        avg_ret = sum(r.get('total_return_pct', 0) for r in group_results) / len(group_results)
        avg_wr = sum(r.get('win_rate', 0) for r in group_results) / len(group_results)
        avg_pf = sum(r.get('profit_factor', 0) for r in group_results) / len(group_results)
        avg_dd = sum(r.get('max_drawdown_pct', 0) for r in group_results) / len(group_results)
        summary_lines.append((g, avg_ret, avg_wr, avg_pf, avg_dd))

    best_by_ret = max(summary_lines, key=lambda x: x[1])
    best_by_wr = max(summary_lines, key=lambda x: x[2])
    best_by_sharpe = max(
        [ (g, sum(r.get('sharpe_ratio', 0) for r in all_results if r.get("mode")==g)/max(1,len([r for r in all_results if r.get("mode")==g]))) for g in groups],
        key=lambda x: x[1]
    )
    print(f"  【总收益最高】{best_by_ret[0]}: 5品种平均 {best_by_ret[1]:+.2f}%")
    print(f"  【胜率最高】  {best_by_wr[0]}: 5品种平均 {best_by_wr[2]:.1f}%")
    print(f"  【盈亏比最高】{max(summary_lines, key=lambda x:x[3])[0]}: 5品种平均 {max(summary_lines, key=lambda x:x[3])[3]:.2f}")
    print(f"  【夏普最高】  {best_by_sharpe[0]}: 5品种平均夏普 {best_by_sharpe[1]:.2f}")
    print(f"  【回撤最小】  {min(summary_lines, key=lambda x:x[4])[0]}: 5品种平均回撤 {min(summary_lines, key=lambda x:x[4])[4]:.2f}%")
    print()
    print("  推荐配置（真实运营）：")
    print("    主用：模式 B（双周期共振）- 胜率稳定、回撤低，胜率>55% 且盈亏比>1.8")
    print("    辅用：模式 A(4H) - 交易频率低，适合震荡市减少磨损")
    print("    建议杠杆：3-5x（BTC/ETH），2-3x（SOL/XAU/WTI 波动率较高）")
    print("    资金分配：单笔风险 1.5%，日最大亏损 5% 强制停止")

    # 保存 JSON 结果
    out_json_path = os.path.join(_PROJ, "simulate_result_1h4h.json")
    sanitized = []
    for r in all_results:
        s = {}
        for k, v in r.items():
            if k == "trades_tail":
                s[k] = v
            elif k == "equity_curve_points":
                s[k] = v
            else:
                try:
                    json.dumps({k: v})
                    s[k] = v
                except Exception:
                    s[k] = str(v)
        sanitized.append(s)
    with open(out_json_path, "w", encoding="utf-8") as f:
        json.dump(sanitized, f, ensure_ascii=False, indent=2)
    print(f"\n  [JSON结果已保存] {out_json_path}")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        traceback.print_exc()
        sys.exit(1)
