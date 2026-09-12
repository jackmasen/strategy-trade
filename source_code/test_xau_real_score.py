# -*- coding: utf-8 -*-
"""
接入真实XAU/USDT 4H数据 → 同进程直接调用EMV策略评分引擎

流程：
  1. 从币安公共API拉取300根XAUUSDT 4H K线
  2. 注入MarketManager内存
  3. 同进程调用StrategyEngine.score_symbol() 触发EMV 10层过滤
  4. 输出完整评分结果
"""
import sys, os, time
from datetime import datetime

import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

BINANCE_KLINES = "https://fapi.binance.com/fapi/v1/klines"


def fetch_xau_klines(limit: int = 300):
    """从币安公共API拉取XAUUSDT 4H K线"""
    print(f"[1] 从币安拉取 XAUUSDT 4H K线 (limit={limit})...")
    url = f"{BINANCE_KLINES}?symbol=XAUUSDT&interval=4h&limit={limit}"
    r = requests.get(url, timeout=15)
    if r.status_code != 200:
        raise Exception(f"币安K线API返回 {r.status_code}: {r.text[:200]}")

    raw = r.json()
    candles = []
    for k in raw:
        candles.append({
            "t": int(k[0]), "o": float(k[1]), "h": float(k[2]),
            "l": float(k[3]), "c": float(k[4]), "v": float(k[5]),
            "ct": int(k[6]),
        })
    print(f"  获取成功: {len(candles)}根K线")
    print(f"  时间范围: {datetime.fromtimestamp(candles[0]['t']/1000)} → {datetime.fromtimestamp(candles[-1]['t']/1000)}")
    print(f"  末根收盘: ${candles[-1]['c']:.2f}")
    price_min = min(c["l"] for c in candles)
    price_max = max(c["h"] for c in candles)
    print(f"  价格区间: ${price_min:.2f} - ${price_max:.2f}")
    return candles


def inject_klines(candles):
    """注入K线到MarketManager内存"""
    print(f"\n[2] 注入K线到MarketManager内存...")
    from backend.exchanges.market import MarketManager, _KlineBucket
    from backend.exchanges._types import Candle

    mm = MarketManager.get_instance()
    now_ms = int(time.time() * 1000)
    key = ("XAU", "4h")

    history = []
    open_bucket = None
    for c in candles:
        candle = Candle(
            symbol="XAU", timeframe="4h",
            open_time_ms=c["t"], open=c["o"], high=c["h"],
            low=c["l"], close=c["c"], volume=c["v"],
            close_time_ms=c["ct"],
        )
        if c["ct"] < now_ms:
            history.append(candle)
        else:
            open_bucket = _KlineBucket(candle=candle)

    with mm._kline_lock:
        mm._kline_history[key] = history
        if open_bucket:
            mm._kline_open_bucket[key] = open_bucket

    print(f"  注入完成: 历史{len(history)}根 + 未闭合{1 if open_bucket else 0}根")

    # 验证读取
    klines = mm.get_klines("XAU", "4h", limit=300)
    print(f"  MarketManager验证: 读取到{len(klines)}根K线")
    return klines


def run_emv_score(klines):
    """同进程调用评分引擎"""
    print(f"\n[3] 查找EMV策略配置...")
    from backend.db.session import SessionLocal
    from backend.models.strategy import StrategyConfig

    db = SessionLocal()
    strategies = db.query(StrategyConfig).filter(
        StrategyConfig.strategy_type == "emv"
    ).all()
    if not strategies:
        print("  未找到EMV策略，创建默认配置...")
        from backend.db.seed_data import ensure_seed_data
        ensure_seed_data(db)
        strategies = db.query(StrategyConfig).filter(
            StrategyConfig.strategy_type == "emv"
        ).all()

    if not strategies:
        # 手动创建一个临时EMV策略配置
        s = StrategyConfig(
            user_id=1, strategy_name="黄金EMV_临时测试",
            strategy_type="emv",
            description="EMV临时测试",
            symbols='["XAU"]', timeframe="4h",
            direction_mode=1, run_mode=3,
            score_threshold=5.0, strong_score_threshold=7.5,
            weight_technical=0.5, weight_news=0.25, weight_ai=0.25,
            leverage_mode=1, leverage_fixed=3,
            leverage_low_score=3, leverage_mid_score=3, leverage_high_score=5,
            tp_ratio=5.0, sl_ratio=2.2,
            use_exchange_tpsl=True,
            single_position_ratio=5.0, total_position_ratio=20.0,
            max_position_count=2, max_single_drawdown=2.0,
            daily_max_loss=3.0, consecutive_loss_pause=2,
            cooldown_hours=72, is_active=True, priority=10,
        )
        db.add(s)
        db.commit()
        db.refresh(s)
        strategies = [s]

    s = strategies[0]
    print(f"  策略: ID={s.id}, name={s.strategy_name}, type={s.strategy_type}")

    print(f"\n[4] 调用评分引擎...")
    from backend.strategy.engine import StrategyEngine

    engine = StrategyEngine()
    try:
        result, record = engine.score_symbol(db, s, "XAU", "4h", account_id=None)
    except Exception as e:
        print(f"  评分异常: {e}")
        import traceback; traceback.print_exc()
        db.close()
        return

    print(f"\n{'='*60}")
    print(f"  黄金EMV策略评分结果（真实XAU/USDT 4H数据）")
    print(f"{'='*60}")
    print(f"  品种: {result.symbol}  周期: {result.timeframe}")
    print(f"  收盘价: ${result.candle_close_price:.2f}")
    if result.candle_close_time:
        print(f"  收盘时间: {result.candle_close_time}")
    print(f"\n  --- 评分明细 ---")
    print(f"  技术分: {result.technical_score:.2f}")
    print(f"  新闻分: {result.news_score:.2f}")
    print(f"  AI分:   {result.ai_score:.2f}")
    print(f"  总分:   {result.score_total:.2f}")
    print(f"  方向:   {result.direction} ({'观望' if result.direction==0 else '做多' if result.direction==1 else '做空'})")
    print(f"  触发阈值: {result.trigger_threshold}")
    print(f"  触发交易: {'是' if result.trigger_trade else '否'}")
    print(f"  建议杠杆: {result.suggested_leverage}x")
    print(f"  止盈: {result.suggested_tp_pct}%  止损: {result.suggested_sl_pct}%")

    print(f"\n  --- 技术指标快照 ---")
    d = result.technical_detail.indicators
    print(f"  EMV:        {d.emv:.6f}")
    print(f"  EMV信号线:  {d.emv_signal:.6f}")
    print(f"  EMV上穿:    {d.emv_cross_up}")
    print(f"  MA7:   {d.ma7:.2f}  MA25: {d.ma25:.2f}  MA99: {d.ma99:.2f}")
    print(f"  RSI14: {d.rsi14:.2f}")
    print(f"  ATR14: {d.atr14:.2f}  ATR%: {d.atr_pct:.4f}")
    print(f"  MACD:  DIF={d.macd_dif:.4f} DEA={d.macd_dea:.4f} Hist={d.macd:.4f}")
    print(f"  布林带: U={d.bb_upper:.2f} M={d.bb_mid:.2f} L={d.bb_lower:.2f}")

    print(f"\n  --- 子评分明细 ---")
    for k, v in result.technical_detail.sub_scores.items():
        print(f"  {k}: {v}")

    print(f"\n  --- 评分理由 ---")
    for r in result.reasons:
        print(f"  • {r[:200]}")

    if record:
        print(f"\n  评分记录ID: {record.id}")

    print(f"\n{'='*60}")
    print(f"  结论: {'EMV信号触发 → 可执行做多' if result.trigger_trade else 'EMV信号未触发 → 观望'}")
    print(f"{'='*60}")

    db.close()


def main():
    print("=" * 60)
    print("接入真实XAU/USDT 4H数据 → EMV策略评分")
    print("=" * 60)

    # 1. 拉取真实K线
    candles = fetch_xau_klines(300)

    # 2. 注入MarketManager
    klines = inject_klines(candles)

    # 3. 同进程评分
    run_emv_score(klines)


if __name__ == "__main__":
    main()
