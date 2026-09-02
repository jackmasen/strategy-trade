# -*- coding: utf-8 -*-
"""
接入真实XAU/USDT 4H K线数据 → 触发EMV策略评分

数据源：币安合约公共API (无需API Key)
  GET https://fapi.binance.com/fapi/v1/klines?symbol=XAUUSDT&interval=4h&limit=300

流程：
  1. 从币安拉取300根4H K线
  2. 注入MarketManager内存
  3. 调用评分API触发EMV 10层过滤
  4. 输出完整评分结果
"""
import sys, os, json, time
from datetime import datetime

import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

API_BASE = "http://127.0.0.1:8001"
BINANCE_KLINES = "https://fapi.binance.com/fapi/v1/klines"


def fetch_xau_klines(limit: int = 300) -> list:
    """从币安公共API拉取XAUUSDT 4H K线"""
    print(f"[1] 从币安拉取 XAUUSDT 4H K线 (limit={limit})...")
    url = f"{BINANCE_KLINES}?symbol=XAUUSDT&interval=4h&limit={limit}"
    r = requests.get(url, timeout=15)
    if r.status_code != 200:
        # 尝试其他交易对名称
        print(f"  XAUUSDT失败({r.status_code})，尝试 XAUUSDM...")
        url2 = f"{BINANCE_KLINES}?symbol=XAUUSDM&interval=4h&limit={limit}"
        r = requests.get(url2, timeout=15)
        if r.status_code != 200:
            raise Exception(f"币安K线API返回 {r.status_code}: {r.text[:200]}")

    raw = r.json()
    candles = []
    for k in raw:
        candles.append({
            "t": int(k[0]),       # open_time_ms
            "o": float(k[1]),     # open
            "h": float(k[2]),     # high
            "l": float(k[3]),     # low
            "c": float(k[4]),     # close
            "v": float(k[5]),     # volume
            "ct": int(k[6]),      # close_time_ms
        })
    print(f"  获取成功: {len(candles)}根K线")
    print(f"  首根: {datetime.fromtimestamp(candles[0]['t']/1000)} O={candles[0]['o']} H={candles[0]['h']} L={candles[0]['l']} C={candles[0]['c']}")
    print(f"  末根: {datetime.fromtimestamp(candles[-1]['t']/1000)} O={candles[-1]['o']} H={candles[-1]['h']} L={candles[-1]['l']} C={candles[-1]['c']}")
    price_min = min(c["l"] for c in candles)
    price_max = max(c["h"] for c in candles)
    print(f"  价格区间: {price_min:.2f} - {price_max:.2f}")
    return candles


def inject_into_market_manager(candles: list):
    """将K线注入MarketManager内存（绕过交易所绑定要求）"""
    print(f"\n[2] 注入K线到MarketManager内存...")
    from backend.exchanges.market import MarketManager, _KlineBucket, _tf_bucket_ms
    from backend.exchanges._types import Candle

    mm = MarketManager.get_instance()
    now_ms = int(time.time() * 1000)
    tf = "4h"

    key = ("XAU", tf)
    history = []
    open_bucket = None
    for c in candles:
        candle = Candle(
            symbol="XAU", timeframe=tf,
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


def login_and_score():
    """登录 → 获取EMV策略 → 触发评分"""
    print(f"\n[3] 登录系统...")
    r = requests.post(f"{API_BASE}/api/v1/auth/login",
                      json={"username": "admin", "password": "Admin@2024"})
    assert r.status_code == 200, f"登录失败: {r.status_code}"
    token = r.json()["data"]["access_token"]
    H = {"Authorization": f"Bearer {token}"}
    print(f"  登录成功")

    # 获取EMV策略ID
    print(f"\n[4] 查找EMV策略...")
    r2 = requests.get(f"{API_BASE}/api/v1/strategies", headers=H)
    strategies = r2.json()["data"]["items"]
    emv_strats = [s for s in strategies if s.get("strategy_type") == "emv"]
    if not emv_strats:
        print("  未找到EMV策略，创建新策略...")
        r_tmpl = requests.get(f"{API_BASE}/api/v1/strategies/default-template?type=emv", headers=H)
        payload = r_tmpl.json()["data"]
        payload["strategy_name"] = "黄金EMV趋势跟踪V7"
        r3 = requests.post(f"{API_BASE}/api/v1/strategies", headers=H, json=payload)
        sid = r3.json()["data"]["id"]
    else:
        sid = emv_strats[0]["id"]
        print(f"  找到EMV策略: ID={sid}, name={emv_strats[0]['strategy_name']}")

    # 触发评分
    print(f"\n[5] 触发EMV策略评分 (策略ID={sid}, XAU 4H)...")
    r5 = requests.post(
        f"{API_BASE}/api/v1/strategies/{sid}/score-symbol",
        headers=H, json={"symbol": "XAU", "timeframe": "4h", "execute_trade": False}
    )
    print(f"  评分响应: {r5.status_code}")
    if r5.status_code == 200:
        sr = r5.json()["data"]
        print(f"\n{'='*60}")
        print(f"  EMV策略评分结果")
        print(f"{'='*60}")
        print(f"  品种: {sr.get('symbol')}  周期: {sr.get('timeframe')}")
        print(f"  收盘价: ${sr.get('candle_close_price')}")
        print(f"  --- 评分明细 ---")
        print(f"  技术分: {sr.get('technical_score')}  新闻分: {sr.get('news_score')}  AI分: {sr.get('ai_score')}")
        print(f"  总分: {sr.get('total_score')}  方向: {sr.get('direction_name')}  触发交易: {sr.get('trigger_trade')}")
        print(f"  建议杠杆: {sr.get('suggested_leverage')}x")
        print(f"  止盈: {sr.get('suggested_tp_pct')}%  止损: {sr.get('suggested_sl_pct')}%")
        print(f"  --- 技术指标快照 ---")
        inds = sr.get("indicators", {})
        print(f"  EMV: {inds.get('emv')}  信号线: {inds.get('emv_signal')}  上穿: {inds.get('emv_cross_up')}")
        print(f"  MA7: {inds.get('ma7')}  MA25: {inds.get('ma25')}  MA99: {inds.get('ma99')}")
        print(f"  RSI: {inds.get('rsi14')}  ATR: {inds.get('atr14')}  ATR%: {inds.get('atr_pct')}")
        print(f"  MACD: DIF={inds.get('macd_dif')} DEA={inds.get('macd_dea')} Hist={inds.get('macd')}")
        print(f"  布林带: U={inds.get('bb_upper')} M={inds.get('bb_mid')} L={inds.get('bb_lower')}")
        print(f"  --- 评分理由 ---")
        reasons = sr.get("reasons", [])
        for r in reasons[:5]:
            print(f"  • {r[:150]}")
        print(f"  记录ID: {sr.get('score_record_id')}")
        print(f"{'='*60}")
    else:
        print(f"  失败: {r5.text[:400]}")


def main():
    print("=" * 60)
    print("接入真实XAU/USDT 4H数据 → EMV策略评分")
    print("=" * 60)

    # 1. 拉取真实K线
    candles = fetch_xau_klines(300)

    # 2. 注入MarketManager
    inject_into_market_manager(candles)

    # 3. 登录并触发评分
    login_and_score()


if __name__ == "__main__":
    main()
