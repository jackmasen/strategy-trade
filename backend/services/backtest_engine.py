"""
简化回测引擎：基于历史K线模拟策略交易，计算各项指标
策略：MA金叉死叉 + RSI过滤
"""
from datetime import datetime, timedelta
from decimal import Decimal
import math
import statistics

from backend.core.logging_config import logger
from backend.models.analytics import BacktestRun
from backend.models.exchange import ExchangeAccount


def _calc_sma(closes, period):
    if len(closes) < period:
        return []
    result = []
    for i in range(period - 1, len(closes)):
        result.append(sum(closes[i - period + 1: i + 1]) / period)
    return result


def _calc_rsi(closes, period=14):
    if len(closes) < period + 1:
        return [50.0] * len(closes)
    gains = []
    losses = []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(0, diff))
        losses.append(max(0, -diff))
    rsi_list = []
    for i in range(len(closes)):
        if i < period:
            rsi_list.append(50.0)
            continue
        avg_gain = sum(gains[i - period:i]) / period
        avg_loss = sum(losses[i - period:i]) / period
        if avg_loss == 0:
            rsi_list.append(100.0)
        else:
            rs = avg_gain / avg_loss
            rsi_list.append(100 - 100 / (1 + rs))
    return rsi_list


def _calc_bollinger_bands(closes, period=20, std_dev=2.0):
    """计算布林带：中轨=SMA，上轨=中轨+std*k，下轨=中轨-std*k"""
    if len(closes) < period:
        return []
    result = []
    for i in range(period - 1, len(closes)):
        window = closes[i - period + 1: i + 1]
        middle = sum(window) / period
        variance = sum((x - middle) ** 2 for x in window) / period
        std = math.sqrt(variance)
        result.append({
            "middle": middle,
            "upper": middle + std_dev * std,
            "lower": middle - std_dev * std,
            "bandwidth": (2 * std_dev * std) / middle if middle > 0 else 0,
        })
    return result


def _calc_ema(closes, period):
    """计算指数移动平均线"""
    if len(closes) < period:
        return []
    multiplier = 2 / (period + 1)
    result = []
    # 初始值用SMA
    sma = sum(closes[:period]) / period
    result.append(sma)
    for i in range(period, len(closes)):
        ema = closes[i] * multiplier + result[-1] * (1 - multiplier)
        result.append(ema)
    # result长度 = len(closes) - period + 1，result[0] 对应 closes[period-1]
    return result


def _calc_macd(closes, fast=12, slow=26, signal=9):
    """计算MACD：MACD线=EMA(fast)-EMA(slow)，信号线=EMA(MACD, signal)，柱状=MACD-信号"""
    if len(closes) < slow + signal - 1:
        return []
    ema_fast = _calc_ema(closes, fast)
    ema_slow = _calc_ema(closes, slow)
    # EMA对齐：ema_fast[0]对应closes[fast-1], ema_slow[0]对应closes[slow-1]
    # MACD从slow-1位置开始
    macd_line = []
    start_idx = slow - 1
    for i in range(start_idx, len(closes)):
        fast_idx = i - (fast - 1)
        slow_idx = i - (slow - 1)
        if fast_idx >= 0 and slow_idx >= 0 and fast_idx < len(ema_fast) and slow_idx < len(ema_slow):
            macd_line.append(ema_fast[fast_idx] - ema_slow[slow_idx])
    # 信号线 = EMA(MACD, signal)
    if len(macd_line) < signal:
        return []
    sig_ema = []
    sig_multiplier = 2 / (signal + 1)
    # 初始用SMA
    sig_sma = sum(macd_line[:signal]) / signal
    sig_ema.append(sig_sma)
    for i in range(signal, len(macd_line)):
        sig_ema.append(macd_line[i] * sig_multiplier + sig_ema[-1] * (1 - sig_multiplier))
    # 结果对齐：从 slow+signal-2 索引开始
    result = []
    # 前signal-1个MACD没有信号线，用None填充
    macd_start = slow - 1
    for i in range(len(closes)):
        macd_idx = i - macd_start
        if macd_idx < 0 or macd_idx >= len(macd_line):
            result.append({"macd": 0, "signal": 0, "histogram": 0})
            continue
        sig_idx = macd_idx - (signal - 1)
        if sig_idx < 0 or sig_idx >= len(sig_ema):
            result.append({"macd": macd_line[macd_idx], "signal": 0, "histogram": 0})
        else:
            result.append({
                "macd": macd_line[macd_idx],
                "signal": sig_ema[sig_idx],
                "histogram": macd_line[macd_idx] - sig_ema[sig_idx],
            })
    return result


def _run_bollinger_strategy(
    closes, highs, lows, volumes, timestamps, klines_data,
    capital, slippage, fee_rate, params, symbol, timeframe,
):
    """布林带策略：价格突破下轨+RSI超卖→做多；突破上轨+RSI超买→做空；回到中轨平仓"""
    bb_period = int(params.get("bb_period", 20) or 20)
    bb_std = float(params.get("bb_std", 2.0) or 2.0)
    rsi_period = int(params.get("rsi_period", 14) or 14)
    bt_leverage = int(params.get("leverage_fixed", 3) or 3)
    bt_risk_pct = float(params.get("single_position_ratio", 10) or 10) / 100
    bt_tp_pct = float(params.get("tp_ratio", 4.0) or 4.0) / 100
    bt_sl_pct = float(params.get("sl_ratio", 2.0) or 2.0) / 100

    bollinger = _calc_bollinger_bands(closes, bb_period, bb_std)
    rsi = _calc_rsi(closes, rsi_period)
    position = None
    trades = []
    bb_offset = bb_period - 1  # bollinger[i-bb_offset] 对应 closes[i]

    for i in range(bb_period, len(closes)):
        bb_idx = i - bb_offset
        if bb_idx < 0 or bb_idx >= len(bollinger):
            continue
        bb = bollinger[bb_idx]
        curr_rsi = rsi[i] if i < len(rsi) else 50
        close = closes[i]
        low = lows[i] if i < len(lows) else close
        high = highs[i] if i < len(highs) else close

        if not position:
            # 做多：价格跌破下轨后收回（下影线触及下轨+收盘在下方）且RSI<30
            if low <= bb["lower"] and close > bb["lower"] and curr_rsi < 35:
                entry_price = close * (1 + slippage)
                leverage = bt_leverage
                margin = capital * bt_risk_pct
                quantity = margin * leverage / entry_price
                fee = margin * leverage * fee_rate
                position = {
                    "side": 1, "entry_price": entry_price, "entry_idx": i,
                    "quantity": quantity, "leverage": leverage, "margin": margin,
                    "fee": fee, "entry_time": timestamps[i],
                    "tp_price": entry_price * (1 + bt_tp_pct),
                    "sl_price": entry_price * (1 - bt_sl_pct),
                }
                capital -= (margin + fee)
            # 做空：价格突破上轨后回落且RSI>70
            elif high >= bb["upper"] and close < bb["upper"] and curr_rsi > 65:
                entry_price = close * (1 - slippage)
                leverage = bt_leverage
                margin = capital * bt_risk_pct
                quantity = margin * leverage / entry_price
                fee = margin * leverage * fee_rate
                position = {
                    "side": 2, "entry_price": entry_price, "entry_idx": i,
                    "quantity": quantity, "leverage": leverage, "margin": margin,
                    "fee": fee, "entry_time": timestamps[i],
                    "tp_price": entry_price * (1 - bt_tp_pct),
                    "sl_price": entry_price * (1 + bt_sl_pct),
                }
                capital -= (margin + fee)

        if position:
            should_close = False
            close_price = close
            if position["side"] == 1:
                # 多单平仓：触及中轨或TP或SL或RSI超买
                if close >= bb["middle"]:
                    should_close = True
                    close_price = bb["middle"]
                elif close >= position["tp_price"]:
                    should_close = True
                    close_price = position["tp_price"]
                elif close <= position["sl_price"]:
                    should_close = True
                    close_price = position["sl_price"]
                elif curr_rsi > 75:
                    should_close = True
            else:
                # 空单平仓：触及中轨或TP或SL或RSI超卖
                if close <= bb["middle"]:
                    should_close = True
                    close_price = bb["middle"]
                elif close <= position["tp_price"]:
                    should_close = True
                    close_price = position["tp_price"]
                elif close >= position["sl_price"]:
                    should_close = True
                    close_price = position["sl_price"]
                elif curr_rsi < 25:
                    should_close = True

            if should_close:
                exit_price = close_price * (1 - slippage if position["side"] == 1 else 1 + slippage)
                fee = position["quantity"] * exit_price * fee_rate
                if position["side"] == 1:
                    pnl = (exit_price - position["entry_price"]) * position["quantity"] - fee - position["fee"]
                else:
                    pnl = (position["entry_price"] - exit_price) * position["quantity"] - fee - position["fee"]
                capital += position["margin"] + pnl
                pnl_pct = pnl / position["margin"] * 100 if position["margin"] > 0 else 0
                trades.append({
                    "symbol": symbol,
                    "side": "多" if position["side"] == 1 else "空",
                    "entry_price": round(position["entry_price"], 4),
                    "exit_price": round(exit_price, 4),
                    "pnl": round(pnl, 2),
                    "pnl_pct": round(pnl_pct, 2),
                    "entry_time": position["entry_time"],
                    "exit_time": timestamps[i],
                    "holding_bars": i - position["entry_idx"],
                })
                position = None

    # 平掉剩余仓位
    if position:
        i = len(closes) - 1
        exit_price = closes[i]
        if position["side"] == 1:
            pnl = (exit_price - position["entry_price"]) * position["quantity"]
        else:
            pnl = (position["entry_price"] - exit_price) * position["quantity"]
        capital += position["margin"] + pnl
        trades.append({
            "symbol": symbol,
            "side": "多" if position["side"] == 1 else "空",
            "entry_price": round(position["entry_price"], 4),
            "exit_price": round(exit_price, 4),
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl / position["margin"] * 100, 2),
            "entry_time": position["entry_time"],
            "exit_time": timestamps[i],
            "holding_bars": i - position["entry_idx"],
        })
    return trades, capital


def _run_macd_strategy(
    closes, highs, lows, volumes, timestamps, klines_data,
    capital, slippage, fee_rate, params, symbol, timeframe,
):
    """MACD策略：MACD上穿信号线金叉+RSI<70→做多；下穿死叉+RSI>30→做空"""
    macd_fast = int(params.get("macd_fast", 12) or 12)
    macd_slow = int(params.get("macd_slow", 26) or 26)
    macd_signal = int(params.get("macd_signal", 9) or 9)
    rsi_period = int(params.get("rsi_period", 14) or 14)
    bt_leverage = int(params.get("leverage_fixed", 3) or 3)
    bt_risk_pct = float(params.get("single_position_ratio", 10) or 10) / 100
    bt_tp_pct = float(params.get("tp_ratio", 4.0) or 4.0) / 100
    bt_sl_pct = float(params.get("sl_ratio", 2.0) or 2.0) / 100

    macd_data = _calc_macd(closes, macd_fast, macd_slow, macd_signal)
    rsi = _calc_rsi(closes, rsi_period)
    position = None
    trades = []
    start_idx = macd_slow + macd_signal - 2  # MACD+信号线都有效的起始索引

    for i in range(start_idx, len(closes)):
        if i >= len(macd_data):
            break
        curr = macd_data[i]
        prev = macd_data[i - 1] if i > 0 else {"macd": 0, "signal": 0, "histogram": 0}
        curr_rsi = rsi[i] if i < len(rsi) else 50
        close = closes[i]

        if not position:
            # 金叉做多：MACD上穿信号线，柱状由负转正
            if prev["histogram"] <= 0 and curr["histogram"] > 0 and curr_rsi < 70:
                entry_price = close * (1 + slippage)
                leverage = bt_leverage
                margin = capital * bt_risk_pct
                quantity = margin * leverage / entry_price
                fee = margin * leverage * fee_rate
                position = {
                    "side": 1, "entry_price": entry_price, "entry_idx": i,
                    "quantity": quantity, "leverage": leverage, "margin": margin,
                    "fee": fee, "entry_time": timestamps[i],
                    "tp_price": entry_price * (1 + bt_tp_pct),
                    "sl_price": entry_price * (1 - bt_sl_pct),
                }
                capital -= (margin + fee)
            # 死叉做空：MACD下穿信号线，柱状由正转负
            elif prev["histogram"] >= 0 and curr["histogram"] < 0 and curr_rsi > 30:
                entry_price = close * (1 - slippage)
                leverage = bt_leverage
                margin = capital * bt_risk_pct
                quantity = margin * leverage / entry_price
                fee = margin * leverage * fee_rate
                position = {
                    "side": 2, "entry_price": entry_price, "entry_idx": i,
                    "quantity": quantity, "leverage": leverage, "margin": margin,
                    "fee": fee, "entry_time": timestamps[i],
                    "tp_price": entry_price * (1 - bt_tp_pct),
                    "sl_price": entry_price * (1 + bt_sl_pct),
                }
                capital -= (margin + fee)

        if position:
            should_close = False
            close_price = close
            if position["side"] == 1:
                # 多单平仓：死叉或TP或SL或RSI超买
                if prev["histogram"] >= 0 and curr["histogram"] < 0:
                    should_close = True
                elif close >= position["tp_price"]:
                    should_close = True
                    close_price = position["tp_price"]
                elif close <= position["sl_price"]:
                    should_close = True
                    close_price = position["sl_price"]
                elif curr_rsi > 75:
                    should_close = True
            else:
                # 空单平仓：金叉或TP或SL或RSI超卖
                if prev["histogram"] <= 0 and curr["histogram"] > 0:
                    should_close = True
                elif close <= position["tp_price"]:
                    should_close = True
                    close_price = position["tp_price"]
                elif close >= position["sl_price"]:
                    should_close = True
                    close_price = position["sl_price"]
                elif curr_rsi < 25:
                    should_close = True

            if should_close:
                exit_price = close_price * (1 - slippage if position["side"] == 1 else 1 + slippage)
                fee = position["quantity"] * exit_price * fee_rate
                if position["side"] == 1:
                    pnl = (exit_price - position["entry_price"]) * position["quantity"] - fee - position["fee"]
                else:
                    pnl = (position["entry_price"] - exit_price) * position["quantity"] - fee - position["fee"]
                capital += position["margin"] + pnl
                pnl_pct = pnl / position["margin"] * 100 if position["margin"] > 0 else 0
                trades.append({
                    "symbol": symbol,
                    "side": "多" if position["side"] == 1 else "空",
                    "entry_price": round(position["entry_price"], 4),
                    "exit_price": round(exit_price, 4),
                    "pnl": round(pnl, 2),
                    "pnl_pct": round(pnl_pct, 2),
                    "entry_time": position["entry_time"],
                    "exit_time": timestamps[i],
                    "holding_bars": i - position["entry_idx"],
                })
                position = None

    # 平掉剩余仓位
    if position:
        i = len(closes) - 1
        exit_price = closes[i]
        if position["side"] == 1:
            pnl = (exit_price - position["entry_price"]) * position["quantity"]
        else:
            pnl = (position["entry_price"] - exit_price) * position["quantity"]
        capital += position["margin"] + pnl
        trades.append({
            "symbol": symbol,
            "side": "多" if position["side"] == 1 else "空",
            "entry_price": round(position["entry_price"], 4),
            "exit_price": round(exit_price, 4),
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl / position["margin"] * 100, 2),
            "entry_time": position["entry_time"],
            "exit_time": timestamps[i],
            "holding_bars": i - position["entry_idx"],
        })
    return trades, capital


def run_backtest(db, run: BacktestRun):
    """执行回测（同步阻塞，适合在后台线程调用）"""
    from backend.routers.exchange import _get_client_by_account

    run.status = BacktestRun.STATUS_RUNNING
    run.started_at = datetime.now()
    run.progress = 5
    db.commit()

    try:
        symbols = run.symbols or ["BTC"]
        timeframe = run.timeframe or "4h"
        initial_capital = float(run.initial_capital or 10000)
        fee_rate = float(run.fee_rate or 0.04) / 100
        slippage = float(run.slippage or 0.05) / 100

        all_trades = []
        equity_curve = []

        for sym_idx, symbol in enumerate(symbols):
            run.progress = 10 + int(80 * sym_idx / len(symbols))
            db.commit()

            try:
                user = db.query(ExchangeAccount).filter(
                    ExchangeAccount.user_id == run.user_id
                ).first()

                klines_data = _fetch_klines_for_backtest(db, run.user_id, symbol, timeframe,
                                                         run.date_start, run.date_end)

                if not klines_data or len(klines_data) < 30:
                    logger.warning(f"[Backtest] {symbol} K线数据不足({len(klines_data) if klines_data else 0}条)，跳过")
                    continue

                closes = [k["close"] for k in klines_data]
                highs = [k["high"] for k in klines_data]
                lows = [k["low"] for k in klines_data]
                volumes = [k["volume"] for k in klines_data]
                timestamps = [k["time"] for k in klines_data]

                # 策略分发：根据 param_snapshot.strategy_type 或关联策略选择回测策略
                _params = run.param_snapshot or {}
                _strat_type = _params.get("strategy_type")
                if not _strat_type and run.strategy_id:
                    try:
                        from backend.models.strategy import StrategyConfig as _SC
                        _sc = db.query(_SC).filter(_SC.id == run.strategy_id).first()
                        if _sc:
                            _strat_type = getattr(_sc, "strategy_type", None)
                    except Exception:
                        pass

                if _strat_type == "emv":
                    capital = initial_capital
                    sym_trades, capital = _run_emv_strategy(
                        closes, highs, lows, volumes, timestamps, klines_data,
                        capital, slippage, fee_rate, _params, symbol, timeframe,
                    )
                    all_trades.extend(sym_trades)
                    step_count = max(1, len(closes) // 30)
                    for _i in range(0, len(closes), step_count):
                        equity_curve.append({
                            "date": timestamps[_i][:10] if isinstance(timestamps[_i], str) else str(timestamps[_i])[:10],
                            "equity": round(capital, 2),
                        })
                    continue  # 跳过下方 MA/RSI 逻辑

                if _strat_type == "bollinger":
                    capital = initial_capital
                    sym_trades, capital = _run_bollinger_strategy(
                        closes, highs, lows, volumes, timestamps, klines_data,
                        capital, slippage, fee_rate, _params, symbol, timeframe,
                    )
                    all_trades.extend(sym_trades)
                    # 权益曲线从交易记录重建
                    _eq_cap = initial_capital
                    for _t in sym_trades:
                        _eq_cap += _t["pnl"]
                        equity_curve.append({
                            "date": _t["exit_time"][:10] if isinstance(_t["exit_time"], str) else str(_t["exit_time"])[:10],
                            "equity": round(_eq_cap, 2),
                        })
                    continue

                if _strat_type == "macd":
                    capital = initial_capital
                    sym_trades, capital = _run_macd_strategy(
                        closes, highs, lows, volumes, timestamps, klines_data,
                        capital, slippage, fee_rate, _params, symbol, timeframe,
                    )
                    all_trades.extend(sym_trades)
                    _eq_cap = initial_capital
                    for _t in sym_trades:
                        _eq_cap += _t["pnl"]
                        equity_curve.append({
                            "date": _t["exit_time"][:10] if isinstance(_t["exit_time"], str) else str(_t["exit_time"])[:10],
                            "equity": round(_eq_cap, 2),
                        })
                    continue

                sma_short = _calc_sma(closes, 7)
                sma_long = _calc_sma(closes, 25)
                rsi = _calc_rsi(closes, 14)

                position = None  # {side, entry_price, entry_idx, quantity, leverage}
                sym_trades = []
                capital = initial_capital

                # 从策略参数获取交易参数
                bt_leverage = int(_params.get("leverage_fixed", 3) or 3)
                bt_risk_pct = float(_params.get("single_position_ratio", 10) or 10) / 100
                bt_tp_pct = float(_params.get("tp_ratio", 5.0) or 5.0) / 100
                bt_sl_pct = float(_params.get("sl_ratio", 1.5) or 1.5) / 100

                for i in range(25, len(closes)):
                    # SMA 索引对齐: _calc_sma 返回紧凑列表, result[k] = SMA at closes[k + period - 1]
                    # 7-period: SMA at closes[i] = sma_short[i - 6], previous = sma_short[i - 7]
                    # 25-period: SMA at closes[i] = sma_long[i - 24], previous = sma_long[i - 25]
                    curr_s = sma_short[i - 6]
                    prev_s = sma_short[i - 7]
                    curr_l = sma_long[i - 24]
                    prev_l = sma_long[i - 25]
                    curr_rsi = rsi[i] if i < len(rsi) else 50

                    # 金叉做多
                    if prev_s <= prev_l and curr_s > curr_l and curr_rsi < 70 and not position:
                        entry_price = closes[i] * (1 + slippage)
                        leverage = bt_leverage
                        margin = capital * bt_risk_pct
                        quantity = margin * leverage / entry_price
                        fee = margin * leverage * fee_rate
                        position = {
                            "side": 1, "entry_price": entry_price, "entry_idx": i,
                            "quantity": quantity, "leverage": leverage, "margin": margin,
                            "fee": fee, "entry_time": timestamps[i],
                            "tp_price": entry_price * (1 + bt_tp_pct),
                            "sl_price": entry_price * (1 - bt_sl_pct),
                        }
                        capital -= (margin + fee)

                    # 死叉做空
                    elif prev_s >= prev_l and curr_s < curr_l and curr_rsi > 30 and not position:
                        entry_price = closes[i] * (1 - slippage)
                        leverage = bt_leverage
                        margin = capital * bt_risk_pct
                        quantity = margin * leverage / entry_price
                        fee = margin * leverage * fee_rate
                        position = {
                            "side": 2, "entry_price": entry_price, "entry_idx": i,
                            "quantity": quantity, "leverage": leverage, "margin": margin,
                            "fee": fee, "entry_time": timestamps[i],
                            "tp_price": entry_price * (1 - bt_tp_pct),
                            "sl_price": entry_price * (1 + bt_sl_pct),
                        }
                        capital -= (margin + fee)

                    # 平仓条件
                    if position:
                        should_close = False
                        close_price = closes[i]

                        if position["side"] == 1:
                            # 多单：死叉或RSI超买或TP/SL
                            if (curr_s < curr_l) or curr_rsi > 75:
                                should_close = True
                            elif closes[i] >= position["tp_price"]:
                                should_close = True
                                close_price = position["tp_price"]
                            elif closes[i] <= position["sl_price"]:
                                should_close = True
                                close_price = position["sl_price"]
                        else:
                            # 空单：金叉或RSI超卖或TP/SL
                            if (curr_s > curr_l) or curr_rsi < 25:
                                should_close = True
                            elif closes[i] <= position["tp_price"]:
                                should_close = True
                                close_price = position["tp_price"]
                            elif closes[i] >= position["sl_price"]:
                                should_close = True
                                close_price = position["sl_price"]

                        if should_close:
                            exit_price = close_price * (1 - slippage if position["side"] == 1 else 1 + slippage)
                            fee = position["quantity"] * exit_price * fee_rate
                            if position["side"] == 1:
                                pnl = (exit_price - position["entry_price"]) * position["quantity"] - fee - position["fee"]
                            else:
                                pnl = (position["entry_price"] - exit_price) * position["quantity"] - fee - position["fee"]

                            capital += position["margin"] + pnl
                            pnl_pct = pnl / position["margin"] * 100 if position["margin"] > 0 else 0

                            sym_trades.append({
                                "symbol": symbol,
                                "side": "多" if position["side"] == 1 else "空",
                                "entry_price": round(position["entry_price"], 4),
                                "exit_price": round(exit_price, 4),
                                "pnl": round(pnl, 2),
                                "pnl_pct": round(pnl_pct, 2),
                                "entry_time": position["entry_time"],
                                "exit_time": timestamps[i],
                                "holding_bars": i - position["entry_idx"],
                            })
                            position = None

                if position:
                    i = len(closes) - 1
                    exit_price = closes[i]
                    if position["side"] == 1:
                        pnl = (exit_price - position["entry_price"]) * position["quantity"]
                    else:
                        pnl = (position["entry_price"] - exit_price) * position["quantity"]
                    capital += position["margin"] + pnl
                    sym_trades.append({
                        "symbol": symbol,
                        "side": "多" if position["side"] == 1 else "空",
                        "entry_price": round(position["entry_price"], 4),
                        "exit_price": round(exit_price, 4),
                        "pnl": round(pnl, 2),
                        "pnl_pct": round(pnl / position["margin"] * 100, 2),
                        "entry_time": position["entry_time"],
                        "exit_time": timestamps[i],
                        "holding_bars": i - position["entry_idx"],
                    })

                all_trades.extend(sym_trades)

                # 权益曲线：从交易记录重建，正确反映每个时点的权益
                _eq_cap = initial_capital
                _ts_idx = 0
                for _t in sym_trades:
                    _eq_cap += _t["pnl"]
                    equity_curve.append({
                        "date": _t["exit_time"][:10] if isinstance(_t["exit_time"], str) else str(_t["exit_time"])[:10],
                        "equity": round(_eq_cap, 2),
                    })

            except Exception as e:
                logger.warning(f"[Backtest] {symbol} 回测异常: {e}")

        _calc_and_save_results(db, run, all_trades, equity_curve, initial_capital, symbols)

    except Exception as e:
        run.status = BacktestRun.STATUS_FAILED
        run.error_msg = str(e)[:500]
        run.finished_at = datetime.now()
        db.commit()
        logger.error(f"[Backtest] 回测失败: {e}")


def _fetch_klines_for_backtest(db, user_id, symbol, timeframe, date_start, date_end):
    """拉取历史K线数据"""
    try:
        from backend.routers.exchange import _get_client_by_account
        from sqlalchemy.orm import Session
        from backend.db.session import SessionLocal
        from backend.models.user import User

        user = db.query(User).filter(User.id == user_id).first() if user_id else None
        client = _get_client_by_account(db, user, account_id=0, allow_public=True)
        if not client:
            return _generate_mock_klines(symbol, timeframe, date_start, date_end)

        if hasattr(client, 'fetch_klines'):
            PAGE_SIZE = 500
            MAX_PAGES = 40
            all_candles = []
            seen_ts = set()
            end_time = None
            for _ in range(MAX_PAGES):
                candles = client.fetch_klines(symbol=symbol, timeframe=timeframe, limit=PAGE_SIZE, end_time=end_time)
                if not candles:
                    break
                deduped = [c for c in candles if c.open_time_ms not in seen_ts]
                if not deduped:
                    break
                for c in deduped:
                    seen_ts.add(c.open_time_ms)
                all_candles = deduped + all_candles
                end_time = deduped[0].open_time_ms - 1
                if date_start:
                    oldest_dt = datetime.fromtimestamp(deduped[0].open_time_ms / 1000)
                    if oldest_dt <= date_start:
                        break
            klines = all_candles
        else:
            klines = client.get_klines(symbol=symbol, timeframe=timeframe, limit=5000)

        if not klines:
            return _generate_mock_klines(symbol, timeframe, date_start, date_end)

        result = []
        for k in klines:
            if hasattr(k, 'open_time_ms'):
                ts = k.open_time_ms
                dt = datetime.fromtimestamp(ts / 1000 if ts > 1e12 else ts)
                time_str = dt.strftime("%Y-%m-%d %H:%M")
            elif hasattr(k, 'timestamp'):
                ts = k.timestamp
                if isinstance(ts, (int, float)):
                    dt = datetime.fromtimestamp(ts / 1000 if ts > 1e12 else ts)
                    time_str = dt.strftime("%Y-%m-%d %H:%M")
                else:
                    time_str = str(ts)
            elif isinstance(k, dict):
                ts = k.get("open_time_ms") or k.get("time") or k.get("timestamp") or k.get("open_time")
                if isinstance(ts, (int, float)):
                    dt = datetime.fromtimestamp(ts / 1000 if ts > 1e12 else ts)
                    time_str = dt.strftime("%Y-%m-%d %H:%M")
                else:
                    time_str = str(ts) if ts else ""
            else:
                time_str = ""

            if hasattr(k, 'open'):
                result.append({
                    "time": time_str, "open": float(k.open), "high": float(k.high),
                    "low": float(k.low), "close": float(k.close), "volume": float(getattr(k, 'volume', 0)),
                })
            elif isinstance(k, dict):
                result.append({
                    "time": time_str, "open": float(k.get("open", 0)), "high": float(k.get("high", 0)),
                    "low": float(k.get("low", 0)), "close": float(k.get("close", 0)),
                    "volume": float(k.get("volume", 0)),
                })

        if date_start and date_end:
            result = [k for k in result if _in_date_range(k["time"], date_start, date_end)]

        return result

    except Exception as e:
        logger.warning(f"[Backtest] 拉取K线失败({symbol}): {e}")
        return _generate_mock_klines(symbol, timeframe, date_start, date_end)


def _in_date_range(time_str, date_start, date_end):
    try:
        d = time_str[:10]
        ds = date_start.strftime("%Y-%m-%d") if hasattr(date_start, 'strftime') else str(date_start)[:10]
        de = date_end.strftime("%Y-%m-%d") if hasattr(date_end, 'strftime') else str(date_end)[:10]
        return ds <= d <= de
    except:
        return True


def _generate_mock_klines(symbol, timeframe, date_start, date_end):
    """生成模拟K线数据（无交易所连接时用）"""
    import random
    random.seed(42)

    if hasattr(date_start, 'strftime'):
        start = date_start
        end = date_end
    else:
        start = datetime.fromisoformat(str(date_start))
        end = datetime.fromisoformat(str(date_end))

    if timeframe == "1h":
        delta = timedelta(hours=1)
    elif timeframe == "4h":
        delta = timedelta(hours=4)
    elif timeframe == "1d":
        delta = timedelta(days=1)
    else:
        delta = timedelta(hours=4)

    base_prices = {"BTC": 65000, "ETH": 3200, "SOL": 150, "XRP": 0.5, "BNB": 500,
                   "ADA": 0.4, "DOGE": 0.12, "XAU": 2300, "WTI": 78, "AVAX": 30, "LINK": 15,
                   }
    base = base_prices.get(symbol, 100)

    result = []
    curr = start
    price = base
    while curr < end:
        volatility = base * 0.02
        change = random.gauss(0, volatility)
        high = price + abs(change) + random.uniform(0, volatility)
        low = price - abs(change) - random.uniform(0, volatility)
        open_p = price
        close_p = price + change
        result.append({
            "time": curr.strftime("%Y-%m-%d %H:%M"),
            "open": round(open_p, 4), "high": round(high, 4),
            "low": round(low, 4), "close": round(close_p, 4),
            "volume": round(random.uniform(100, 10000), 2),
        })
        price = close_p
        curr += delta
    return result


def _calc_and_save_results(db, run, trades, equity_curve, initial_capital, symbols):
    """计算回测指标并保存"""
    run.progress = 95
    db.commit()

    if not trades:
        run.total_return_pct = 0
        run.annual_return_pct = 0
        run.max_drawdown_pct = 0
        run.sharpe_ratio = 0
        run.sortino_ratio = 0
        run.calmar_ratio = 0
        run.win_rate = 0
        run.profit_factor = 0
        run.total_trades = 0
        run.win_trades = 0
        run.loss_trades = 0
        run.avg_win_pct = 0
        run.avg_loss_pct = 0
        run.max_consecutive_wins = 0
        run.max_consecutive_losses = 0
        run.equity_curve = equity_curve[:100]
        run.trades_detail = []
        run.per_symbol_stats = {}
    else:
        total_pnl = sum(t["pnl"] for t in trades)
        total_return_pct = total_pnl / initial_capital * 100

        win_trades = [t for t in trades if t["pnl"] > 0]
        loss_trades = [t for t in trades if t["pnl"] <= 0]

        total_win = sum(t["pnl"] for t in win_trades)
        total_loss = abs(sum(t["pnl"] for t in loss_trades))
        profit_factor = total_win / total_loss if total_loss > 0 else 999.0

        win_rate = len(win_trades) / len(trades) * 100 if trades else 0

        avg_win = statistics.mean([t["pnl_pct"] for t in win_trades]) if win_trades else 0
        avg_loss = statistics.mean([t["pnl_pct"] for t in loss_trades]) if loss_trades else 0

        # 最大连胜/连败
        max_wins = max_loss_streak = 0
        curr_wins = curr_losses = 0
        for t in trades:
            if t["pnl"] > 0:
                curr_wins += 1
                curr_losses = 0
                max_wins = max(max_wins, curr_wins)
            else:
                curr_losses += 1
                curr_wins = 0
                max_loss_streak = max(max_loss_streak, curr_losses)

        # 最大回撤
        eq_values = [e["equity"] for e in equity_curve] if equity_curve else [initial_capital]
        peak = eq_values[0]
        max_dd = 0
        for v in eq_values:
            if v > peak:
                peak = v
            dd = (peak - v) / peak * 100 if peak > 0 else 0
            max_dd = max(max_dd, dd)

        # 夏普比率（简化：用日收益率）
        if len(eq_values) > 2:
            returns = [(eq_values[i] - eq_values[i - 1]) / eq_values[i - 1]
                       for i in range(1, len(eq_values)) if eq_values[i - 1] > 0]
            if returns:
                avg_ret = statistics.mean(returns)
                std_ret = statistics.stdev(returns) if len(returns) > 1 else 0.01
                sharpe = avg_ret / std_ret * math.sqrt(252) if std_ret > 0 else 0
            else:
                sharpe = 0
        else:
            sharpe = 0

        # 年化收益
        days = (run.date_end - run.date_start).days if run.date_end and run.date_start else 30
        annual_return = total_return_pct / days * 365 if days > 0 else 0

        # 索提诺
        downside_returns = [r for r in returns if r < 0] if len(eq_values) > 2 else []
        downside_std = statistics.stdev(downside_returns) if len(downside_returns) > 1 else 0.01
        sortino = (statistics.mean(returns) if returns else 0) / downside_std * math.sqrt(252) if downside_std > 0 else 0

        # 卡玛
        calmar = annual_return / max_dd if max_dd > 0 else 0

        # 分品种统计
        per_symbol = {}
        for t in trades:
            sym = t["symbol"]
            if sym not in per_symbol:
                per_symbol[sym] = {"trades": 0, "wins": 0, "pnl": 0}
            per_symbol[sym]["trades"] += 1
            if t["pnl"] > 0:
                per_symbol[sym]["wins"] += 1
            per_symbol[sym]["pnl"] += t["pnl"]

        run.total_return_pct = round(total_return_pct, 2)
        run.annual_return_pct = round(annual_return, 2)
        run.max_drawdown_pct = round(max_dd, 2)
        run.sharpe_ratio = round(sharpe, 2)
        run.sortino_ratio = round(sortino, 2)
        run.calmar_ratio = round(calmar, 2)
        run.win_rate = round(win_rate, 1)
        run.profit_factor = round(profit_factor, 2)
        run.total_trades = len(trades)
        run.win_trades = len(win_trades)
        run.loss_trades = len(loss_trades)
        run.avg_win_pct = round(avg_win, 2)
        run.avg_loss_pct = round(avg_loss, 2)
        run.max_consecutive_wins = max_wins
        run.max_consecutive_losses = max_loss_streak
        run.equity_curve = equity_curve[:200]
        run.trades_detail = trades[:200]
        run.per_symbol_stats = per_symbol

    run.status = BacktestRun.STATUS_SUCCESS
    run.progress = 100
    run.finished_at = datetime.now()
    db.commit()
    logger.info(f"[Backtest] 回测完成: {run.run_name}, 交易{run.total_trades}笔, 收益{run.total_return_pct}%")


def _run_emv_strategy(closes, highs, lows, volumes, timestamps, klines_data,
                      capital, slippage, fee_rate, params, symbol, timeframe):
    """EMV V7 策略回测：逐根K线切片调用 EMVSignalGenerator，signal==1 做多，TP/SL 平仓。
    复用与实盘一致的信号生成器，保证回测结果可外推到实盘。"""
    from backend.strategy.emv_strategy import EMVSignalGenerator

    gen = EMVSignalGenerator()
    tp_pct = float(params.get("tp_ratio", 3.0)) / 100
    sl_pct = float(params.get("sl_ratio", 1.5)) / 100
    leverage = int(params.get("leverage_fixed", 2))
    risk_pct = float(params.get("single_position_ratio", 10)) / 100

    sym_trades = []
    position = None
    min_bars = 200  # EMV 至少需要 200 根

    for i in range(min_bars, len(closes)):
        # 开仓：截至 i 的 K 线切片生成 EMV 信号
        if not position:
            try:
                emv_res = gen.generate(klines_data[: i + 1], symbol=symbol, timeframe=timeframe)
            except Exception:
                emv_res = None
            if emv_res and emv_res.signal == 1:
                entry_price = closes[i] * (1 + slippage)
                margin = capital * risk_pct
                if margin <= 0:
                    break
                quantity = margin * leverage / entry_price
                fee = margin * leverage * fee_rate
                position = {
                    "side": 1, "entry_price": entry_price, "entry_idx": i,
                    "quantity": quantity, "leverage": leverage, "margin": margin,
                    "fee": fee, "entry_time": timestamps[i],
                    "tp_price": entry_price * (1 + tp_pct),
                    "sl_price": entry_price * (1 - sl_pct),
                }
                capital -= (margin + fee)

        # 平仓：TP/SL（做多）
        if position:
            should_close = False
            close_price = closes[i]
            if closes[i] >= position["tp_price"]:
                should_close = True
                close_price = position["tp_price"]
            elif closes[i] <= position["sl_price"]:
                should_close = True
                close_price = position["sl_price"]

            if should_close:
                exit_price = close_price * (1 - slippage)
                fee = position["quantity"] * exit_price * fee_rate
                pnl = (exit_price - position["entry_price"]) * position["quantity"] - fee - position["fee"]
                capital += position["margin"] + pnl
                pnl_pct = pnl / position["margin"] * 100 if position["margin"] > 0 else 0
                sym_trades.append({
                    "symbol": symbol,
                    "side": "多",
                    "entry_price": round(position["entry_price"], 4),
                    "exit_price": round(exit_price, 4),
                    "pnl": round(pnl, 2),
                    "pnl_pct": round(pnl_pct, 2),
                    "entry_time": position["entry_time"],
                    "exit_time": timestamps[i],
                    "holding_bars": i - position["entry_idx"],
                })
                position = None

    # 末尾未平仓按收盘价平仓
    if position:
        i = len(closes) - 1
        exit_price = closes[i]
        fee = position["quantity"] * exit_price * fee_rate
        pnl = (exit_price - position["entry_price"]) * position["quantity"] - fee - position["fee"]
        capital += position["margin"] + pnl
        sym_trades.append({
            "symbol": symbol,
            "side": "多",
            "entry_price": round(position["entry_price"], 4),
            "exit_price": round(exit_price, 4),
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl / position["margin"] * 100, 2),
            "entry_time": position["entry_time"],
            "exit_time": timestamps[i],
            "holding_bars": i - position["entry_idx"],
        })

    return sym_trades, capital
