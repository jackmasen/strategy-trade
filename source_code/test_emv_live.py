# -*- coding: utf-8 -*-
"""EMV策略后端实跑验证"""
import requests, json, sys

BASE = "http://127.0.0.1:8001"

def main():
    # 1. 登录
    r = requests.post(f"{BASE}/api/v1/auth/login", json={"username": "admin", "password": "Admin@2024"})
    assert r.status_code == 200, f"登录失败: {r.status_code}"
    token = r.json()["data"]["access_token"]
    print(f"[OK] 登录成功, token={token[:20]}...")
    H = {"Authorization": f"Bearer {token}"}

    # 2. 获取EMV默认模板
    r2 = requests.get(f"{BASE}/api/v1/strategies/default-template?type=emv", headers=H)
    assert r2.status_code == 200, f"获取模板失败: {r2.status_code}"
    d = r2.json()["data"]
    print(f"\n[OK] EMV默认模板:")
    print(f"  名称: {d['strategy_name']}")
    print(f"  类型: {d['strategy_type']}")
    print(f"  标的: {d['symbols']}")
    print(f"  周期: {d['timeframe']}")
    print(f"  方向: {d['direction_mode']} (只做多)")
    print(f"  杠杆: {d['leverage_fixed']}x (固定)")
    print(f"  TP/SL: {d['tp_ratio']}/{d['sl_ratio']}")
    print(f"  单笔仓位: {d['single_position_ratio']}%")
    print(f"  连亏暂停: {d['consecutive_loss_pause']}笔 → 冷却{d['cooldown_hours']}h")

    # 3. 创建EMV策略
    payload = dict(d)
    payload.pop("strategy_name", None)
    payload["strategy_name"] = "黄金EMV趋势跟踪V7"
    r3 = requests.post(f"{BASE}/api/v1/strategies", headers=H, json=payload)
    assert r3.status_code in (200, 201), f"创建策略失败: {r3.status_code} {r3.text[:200]}"
    sdata = r3.json()["data"]
    sid = sdata["id"] if isinstance(sdata, dict) else sdata
    print(f"\n[OK] EMV策略创建成功:")
    print(f"  ID: {sid}")
    print(f"  Raw response: {json.dumps(r3.json(), ensure_ascii=False)[:300]}")

    # 4. 获取策略列表验证
    r4 = requests.get(f"{BASE}/api/v1/strategies", headers=H)
    assert r4.status_code == 200
    strategies = r4.json()["data"]
    if isinstance(strategies, list):
        print(f"\n[OK] 策略列表: 共{len(strategies)}个策略")
        for s in strategies[:5]:
            if isinstance(s, dict):
                print(f"  - ID={s.get('id')} name={s.get('strategy_name','?')} type={s.get('strategy_type','?')}")
            else:
                print(f"  - {s}")
    else:
        print(f"\n策略列表响应: {json.dumps(r4.json(), ensure_ascii=False)[:300]}")

    # 5. 触发评分
    print(f"\n--- 触发EMV策略评分 ---")
    r5 = requests.post(f"{BASE}/api/v1/strategies/{sid}/score-symbol",
                       headers=H, json={"symbol": "XAU", "timeframe": "4h", "execute_trade": False})
    print(f"评分响应: {r5.status_code}")
    if r5.status_code == 200:
        sr = r5.json()["data"]
        print(f"  品种: {sr.get('symbol')}  周期: {sr.get('timeframe')}")
        print(f"  收盘价: {sr.get('candle_close_price')}")
        print(f"  技术分: {sr.get('technical_score')}  新闻分: {sr.get('news_score')}  AI分: {sr.get('ai_score')}")
        print(f"  总分: {sr.get('total_score')}  方向: {sr.get('direction_name')}  触发: {sr.get('trigger_trade')}")
        print(f"  建议杠杆: {sr.get('suggested_leverage')}x  TP: {sr.get('suggested_tp_pct')}%  SL: {sr.get('suggested_sl_pct')}%")
        inds = sr.get("indicators", {})
        print(f"  EMV: {inds.get('emv', 'N/A')}  EMV信号线: {inds.get('emv_signal', 'N/A')}  上穿: {inds.get('emv_cross_up', 'N/A')}")
        print(f"  MA7={inds.get('ma7')}  MA25={inds.get('ma25')}  MA99={inds.get('ma99')}")
        print(f"  RSI={inds.get('rsi14')}  ATR={inds.get('atr14')}")
        reasons = sr.get("reasons", [])
        if reasons:
            print(f"  理由: {reasons[0][:120]}")
    else:
        print(f"  响应: {r5.text[:400]}")

    # 6. 获取评分记录
    r7 = requests.get(f"{BASE}/api/v1/strategies/{sid}/scores?limit=5", headers=H)
    print(f"\n评分历史: {r7.status_code}")
    if r7.status_code == 200:
        rdata = r7.json().get("data", {})
        items = rdata.get("items", rdata) if isinstance(rdata, dict) else rdata
        if isinstance(items, list) and items:
            for sc in items[:3]:
                print(f"  时间={sc.get('created_at','?')} 总分={sc.get('score_total','?')} 方向={sc.get('suggested_direction','?')} EMV={sc.get('emv','N/A')}")
        else:
            print(f"  数据: {json.dumps(rdata, ensure_ascii=False)[:300]}")

    print("\n" + "=" * 60)
    print("EMV策略后端实跑验证完成")
    print("=" * 60)

if __name__ == "__main__":
    main()
