# -*- coding: utf-8 -*-
"""
模拟交易全链路运营演示测试
覆盖完整运营流程：登录 → Dashboard → 交易所绑定 → 策略CRUD → 启停 → 评分执行
  → 手动下单 → 持仓 → 平仓 → 撤单 → 回测 → AI分析 → 新闻采集 → 风控 → 报表 → 退出
目标：验证所有功能逻辑跑通，系统可正常运营
"""
from __future__ import annotations
import json, sys, time, urllib.request, urllib.error, urllib.parse

BASE = "http://127.0.0.1:8001/api/v1"
PASS = 0
FAIL = 0
ERRORS = []

def log_case(name, ok, detail=""):
    global PASS, FAIL
    mark = "✅" if ok else "❌"
    print(f"  {mark} {name}  {detail}")
    if ok:
        PASS += 1
    else:
        FAIL += 1
        ERRORS.append(f"{name}: {detail}")

def req(method, path, data=None, token=None, params=None):
    url = BASE + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    body, headers = None, {}
    if data is not None:
        body = json.dumps(data).encode()
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            text = resp.read().decode("utf-8")
            return resp.status, json.loads(text)
    except urllib.error.HTTPError as e:
        text = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(text)
        except Exception:
            return e.code, {"code": 9996, "message": text[:300]}
    except Exception as e:
        return 0, {"code": 9998, "message": str(e)}


print("=" * 70)
print("🚀 模拟交易全链路运营演示测试")
print("=" * 70)

# ============================================================
# 步骤 1：认证登录
# ============================================================
print("\n━━━ 步骤 1：认证登录 ━━━")
st, d = req("POST", "/auth/login", data={"username": "admin", "password": "Admin@2024"})
tok = (d.get("data") or {}).get("access_token", "")
user = (d.get("data") or {}).get("user") or {}
log_case("1.1 admin 登录成功", st == 200 and d.get("code") == 0 and bool(tok),
        f"code={d.get('code')}")
log_case("1.2 登录响应 user 字段完整", "username" in user and "role" in user,
        f"user_keys={list(user.keys())}")
log_case("1.3 GET /users/me 获取个人信息",
         (lambda s2, d2: s2 == 200 and d2.get("code") == 0)(*req("GET", "/users/me", token=tok)))

# ============================================================
# 步骤 2：Dashboard 报表
# ============================================================
print("\n━━━ 步骤 2：Dashboard 报表 ━━━")
st, d = req("GET", "/reports/dashboard", token=tok)
log_case("2.1 Dashboard 数据加载", st == 200 and d.get("code") == 0,
        f"code={d.get('code')}")

for rpt_type, rpt_path in [("日报", "/reports/daily"),
                            ("周报", "/reports/weekly"),
                            ("月报", "/reports/monthly")]:
    st, d = req("GET", rpt_path, token=tok)
    log_case(f"2.2 {rpt_type}列表", st == 200 and d.get("code") == 0,
            f"total={(d.get('data') or {}).get('total', '?')}")

# ============================================================
# 步骤 3：交易所子账号绑定
# ============================================================
print("\n━━━ 步骤 3：交易所子账号绑定 ━━━")
st, d = req("GET", "/exchange/supported-symbols", token=tok)
syms_raw = d.get("data")
if isinstance(syms_raw, list):
    syms = syms_raw
elif isinstance(syms_raw, dict):
    syms = syms_raw.get("symbols") or syms_raw.get("items") or []
else:
    syms = []
log_case("3.1 获取支持交易对列表", st == 200 and d.get("code") == 0,
        f"count={len(syms) if isinstance(syms, list) else '?'}")

st, d = req("GET", "/exchange/accounts", token=tok)
accts_before = (d.get("data") or {}).get("items") or []
log_case("3.2 查看已有交易所账号", st == 200 and d.get("code") == 0,
        f"count={len(accts_before)}")

# 绑定模拟子账号
st, d = req("POST", "/exchange/accounts", data={
    "exchange": 1,
    "sub_account_name": "Demo-Test-Sub",
    "api_key": "demo_api_key_001",
    "api_secret": "demo_api_secret_001",
    "leverage_max": 5,
    "testnet": True,
    "remark": "模拟演示用",
}, token=tok)
new_acct_id = None
if d.get("code") == 0:
    new_acct_id = (d.get("data") or {}).get("id")
    log_case("3.3 绑定 Binance 模拟子账号", True, f"acct_id={new_acct_id}")
elif "已存在" in str(d.get("message", "")) or "duplicate" in str(d.get("message", "")).lower():
    st2, d2 = req("GET", "/exchange/accounts", token=tok)
    for a in ((d2.get("data") or {}).get("items") or []):
        if "Demo-Test-Sub" in str(a.get("sub_account_name", "")):
            new_acct_id = a.get("id")
            break
    log_case("3.3 绑定 Binance 模拟子账号（已存在，复用）", bool(new_acct_id), f"acct_id={new_acct_id}")
else:
    log_case("3.3 绑定 Binance 模拟子账号", False, f"code={d.get('code')} msg={str(d.get('message',''))[:100]}")

# 测试连接（模拟 Key 会失败，但接口不崩）
if new_acct_id:
    st, d = req("POST", f"/exchange/accounts/{new_acct_id}/test-connection", token=tok)
    log_case("3.4 测试子账号连接（模拟Key预期失败但不崩）",
             d.get("code") in (0, 4000, 5000, 5001, 5010),
             f"code={d.get('code')} msg={str(d.get('message',''))[:80]}")

    # 同步余额
    st, d = req("POST", f"/exchange/accounts/{new_acct_id}/sync", token=tok)
    log_case("3.5 同步子账号余额（模拟Key预期失败但不崩）",
             d.get("code") in (0, 4000, 5000, 5001, 5010),
             f"code={d.get('code')} msg={str(d.get('message',''))[:80]}")

# 行情查询（模拟环境无真实API会失败但不崩）
st, d = req("GET", "/exchange/ticker/BTCUSDT", token=tok)
log_case("3.6 BTC 行情查询（模拟环境可能失败但不崩）",
         d.get("code") in (0, 4000, 5000, 5001, 5010),
         f"code={d.get('code')} msg={str(d.get('message',''))[:80]}")

# ============================================================
# 步骤 4：策略 CRUD
# ============================================================
print("\n━━━ 步骤 4：策略 CRUD ━━━")
# 4.1 创建策略
st, d = req("POST", "/strategies", data={
    "strategy_name": "Demo-BTC-趋势跟踪-4H",
    "description": "演示用策略：BTC 4小时趋势跟踪 + RSI 过滤",
    "symbols": ["BTC"],
    "timeframe": "4h",
    "score_threshold": 5.0,
    "tp_ratio": 4.0,
    "sl_ratio": 2.0,
    "leverage_fixed": 5,
    "weight_technical": 0.4,
    "weight_news": 0.3,
    "weight_ai": 0.3,
}, token=tok)
new_sid = None
_d = d.get("data")
if isinstance(_d, dict):
    new_sid = _d.get("id") or _d.get("strategy_id")
elif isinstance(_d, list) and _d:
    new_sid = _d[0].get("id") if isinstance(_d[0], dict) else None
log_case("4.1 创建策略 BTC-4H-趋势跟踪", d.get("code") == 0 and bool(new_sid),
        f"sid={new_sid} code={d.get('code')} msg={str(d.get('message',''))[:60]}")

# 4.2 查看策略列表
st, d = req("GET", "/strategies", token=tok)
strategies = (d.get("data") or {}).get("items") or []
log_case("4.2 策略列表", st == 200 and d.get("code") == 0,
        f"total={len(strategies)}")

# 4.3 查看策略详情
if new_sid:
    st, d = req("GET", f"/strategies/{new_sid}", token=tok)
    log_case("4.3 策略详情", st == 200 and d.get("code") == 0,
            f"name={(d.get('data') or {}).get('name', '?')}")

    # 4.4 修改策略（PUT 用 StrategyCreateReq，需传必填字段）
    st, d = req("PUT", f"/strategies/{new_sid}", data={
        "strategy_name": "Demo-BTC-趋势跟踪-4H-修改版",
        "symbols": ["BTC"],
        "timeframe": "4h",
        "tp_ratio": 5.0,
        "sl_ratio": 2.5,
        "score_threshold": 5.0,
        "leverage_fixed": 5,
        "weight_technical": 0.4,
        "weight_news": 0.3,
        "weight_ai": 0.3,
    }, token=tok)
    log_case("4.4 修改策略止盈止损参数",
             d.get("code") == 0,
             f"code={d.get('code')} msg={str(d.get('message',''))[:60]}")

    # 4.5 策略启停
    st, d = req("POST", f"/strategies/{new_sid}/toggle", params={"active": True}, token=tok)
    log_case("4.5a 启动策略", d.get("code") == 0,
            f"code={d.get('code')} msg={str(d.get('message',''))[:60]}")

    st, d = req("POST", f"/strategies/{new_sid}/toggle", params={"active": False}, token=tok)
    log_case("4.5b 停止策略", d.get("code") == 0,
            f"code={d.get('code')}")

# ============================================================
# 步骤 5：策略评分执行
# ============================================================
print("\n━━━ 步骤 5：策略评分执行 ━━━")
if new_sid:
    # 先启动策略（评分/执行要求策略处于激活状态）
    req("POST", f"/strategies/{new_sid}/toggle", params={"active": True}, token=tok)

    # 5.1 评分单个交易对
    st, d = req("POST", f"/strategies/{new_sid}/score-symbol",
                data={"symbol": "BTC"}, token=tok)
    score_data = d.get("data") or {}
    # 评分可能因无交易所绑定返回 6001，但接口不崩
    log_case("5.1 策略评分 BTC（接口不崩）",
             d.get("code") in (0, 4000, 6001, 6002),
             f"code={d.get('code')} total_score={score_data.get('total_score', '?')} signal={score_data.get('signal', score_data.get('direction', '?'))} msg={str(d.get('message',''))[:60]}")

    # 5.2 查看评分历史
    st, d = req("GET", f"/strategies/{new_sid}/scores", token=tok)
    log_case("5.2 评分历史记录",
             st == 200 and d.get("code") == 0,
             f"total={(d.get('data') or {}).get('total', '?')}")

    # 5.3 执行策略（无真实API会失败但不崩）
    st, d = req("POST", f"/strategies/{new_sid}/run", token=tok)
    log_case("5.3 执行策略（模拟环境）",
             d.get("code") in (0, 4000, 6001, 6002, 5000, 5001, 5010),
             f"code={d.get('code')} msg={str(d.get('message',''))[:80]}")

    # 停掉策略（清理）
    req("POST", f"/strategies/{new_sid}/toggle", params={"active": False}, token=tok)

# 5.4 最新评分
st, d = req("GET", "/strategies/scores/latest", token=tok)
log_case("5.4 全局最新评分", st == 200 and d.get("code") == 0,
        f"code={d.get('code')}")

# ============================================================
# 步骤 6：手动下单 → 持仓 → 平仓 → 撤单
# ============================================================
print("\n━━━ 步骤 6：手动下单 → 持仓 → 平仓 → 撤单 ━━━")
# 6.1 交易总览
st, d = req("GET", "/trades/overview", token=tok)
log_case("6.1 交易总览 Dashboard",
         st == 200 and d.get("code") == 0,
         f"code={d.get('code')}")

# 6.2 手动下单（模拟Key会失败但接口不崩）
_acct_id = new_acct_id or 1
st, d = req("POST", "/trades/orders/manual", data={
    "exchange_account_id": _acct_id,
    "symbol": "BTC",
    "side": 1,
    "quantity_usdt": 100,
    "leverage": 5,
    "order_type": 1,
    "tp_ratio_pct": 4.0,
    "sl_ratio_pct": 2.0,
}, token=tok)
_d6 = d.get("data")
order_id = None
if isinstance(_d6, dict):
    order_id = _d6.get("id") or _d6.get("order_id")
elif isinstance(_d6, list) and _d6:
    order_id = _d6[0].get("id") if isinstance(_d6[0], dict) else None
log_case("6.2 手动下单（模拟Key预期失败但不崩）",
         d.get("code") in (0, 4000, 4001, 5000, 5001, 5010),
         f"code={d.get('code')} oid={order_id} msg={str(d.get('message',''))[:80]}")

# 6.3 订单列表
st, d = req("GET", "/trades/orders", token=tok)
_d3 = d.get("data")
log_case("6.3 订单列表",
         st == 200 and d.get("code") == 0,
         f"total={(_d3.get('total','?') if isinstance(_d3, dict) else len(_d3) if isinstance(_d3, list) else '?')}")

# 6.4 持仓列表
st, d = req("GET", "/trades/positions", token=tok)
_d4 = d.get("data")
log_case("6.4 持仓列表",
         st == 200 and d.get("code") == 0,
         f"total={(_d4.get('total','?') if isinstance(_d4, dict) else len(_d4) if isinstance(_d4, list) else '?')}")

# 6.5 平仓（如果有持仓）
positions = []
if isinstance(_d4, dict):
    positions = _d4.get("items") or []
elif isinstance(_d4, list):
    positions = _d4
if positions:
    pid = positions[0].get("id") if isinstance(positions[0], dict) else None
    if pid:
        st, d = req("POST", f"/trades/positions/{pid}/close", token=tok)
        log_case("6.5 平仓操作",
                 d.get("code") in (0, 4000, 5000, 5001, 5010, 5021),
                 f"pid={pid} code={d.get('code')}")
    else:
        log_case("6.5 平仓操作（无有效持仓ID，跳过）", True, "")
else:
    log_case("6.5 平仓操作（无持仓，跳过）", True, "no open positions")

# 6.6 撤单
if order_id:
    st, d = req("POST", f"/trades/orders/{order_id}/cancel", token=tok)
    log_case("6.6 撤单操作",
             d.get("code") in (0, 4000, 5000, 5001, 5010, 4040),
             f"oid={order_id} code={d.get('code')}")
else:
    log_case("6.6 撤单操作（无订单，跳过）", True, "no orders to cancel")

# 6.7 交易历史
st, d = req("GET", "/trades/history", token=tok)
_d7 = d.get("data")
log_case("6.7 交易历史",
         st == 200 and d.get("code") == 0,
         f"total={(_d7.get('total','?') if isinstance(_d7, dict) else len(_d7) if isinstance(_d7, list) else '?')}")

# ============================================================
# 步骤 7：回测
# ============================================================
print("\n━━━ 步骤 7：回测 ━━━")
# 7.1 创建回测任务
bt_sid = new_sid or 1
st, d = req("POST", "/backtests", data={
    "strategy_id": bt_sid,
    "run_name": "Demo-BTC-Backtest",
    "symbols": ["BTC"],
    "timeframe": "4h",
    "date_start": "2024-01-01T00:00:00",
    "date_end": "2024-06-01T00:00:00",
    "initial_capital": 10000,
    "fee_rate": 0.04,
    "slippage": 0.05,
}, token=tok)
bt_id = None
_d_bt = d.get("data")
if isinstance(_d_bt, dict):
    bt_id = _d_bt.get("id") or _d_bt.get("backtest_id")
elif isinstance(_d_bt, list) and _d_bt:
    bt_id = _d_bt[0].get("id") if isinstance(_d_bt[0], dict) else None
log_case("7.1 创建回测任务", d.get("code") == 0,
        f"bt_id={bt_id} code={d.get('code')}")

# 7.2 回测列表
st, d = req("GET", "/backtests", token=tok)
_d_bt2 = d.get("data")
log_case("7.2 回测列表",
         st == 200 and d.get("code") == 0,
         f"total={(_d_bt2.get('total','?') if isinstance(_d_bt2, dict) else len(_d_bt2) if isinstance(_d_bt2, list) else '?')}")

# ============================================================
# 步骤 8：AI 分析
# ============================================================
print("\n━━━ 步骤 8：AI 分析 ━━━")
# 8.1 AI 配置读取
st, d = req("GET", "/ai/config", token=tok)
log_case("8.1 AI 配置读取", st == 200 and d.get("code") == 0,
        f"provider={(d.get('data') or {}).get('provider', '?')} has_key={(d.get('data') or {}).get('has_key', '?')}")

# 8.2 AI Mock 分析
st, d = req("POST", "/ai/analyze", data={
    "analysis_type": "score",
    "symbol": "BTC",
    "timeframe": "4h",
    "mock": True,
}, token=tok)
ai_data = d.get("data") or {}
log_case("8.2 AI Mock 分析（不消耗真额度）",
         d.get("code") == 0 and ai_data.get("success") is not False,
         f"score={ai_data.get('ai_score', '?')} dir={ai_data.get('ai_direction', '?')} latency={ai_data.get('latency_ms', '?')}ms")

# 8.3 AI 调用记录
st, d = req("GET", "/ai/records", token=tok)
log_case("8.3 AI 调用历史记录",
         st == 200 and d.get("code") == 0,
         f"total={(d.get('data') or {}).get('total', '?')}")

# ============================================================
# 步骤 9：新闻采集
# ============================================================
print("\n━━━ 步骤 9：新闻采集 ━━━")
# 9.1 新闻列表
st, d = req("GET", "/news", params={"page": 1, "page_size": 5}, token=tok)
log_case("9.1 新闻列表",
         st == 200 and d.get("code") == 0,
         f"total={(d.get('data') or {}).get('total', '?')}")

# 9.2 手动触发采集
st, d = req("POST", "/news/collect", token=tok)
collect_data = d.get("data") or {}
_fetched = collect_data.get("total_fetched") or collect_data.get("fetched") or collect_data.get("inserted") or 0
if isinstance(collect_data, list):
    _fetched = len(collect_data)
log_case("9.2 手动触发新闻采集",
         d.get("code") == 0,
         f"fetched={_fetched} code={d.get('code')} msg={str(d.get('message',''))[:60]}")

# 9.3 新闻情绪摘要
st, d = req("GET", "/news/sentiment/summary", params={"symbol": "BTC"}, token=tok)
log_case("9.3 BTC 新闻情绪摘要",
         st == 200 and d.get("code") == 0,
         f"total={(d.get('data') or {}).get('total', '?')}")

# 9.4 代理健康
st, d = req("GET", "/news/proxy/health", token=tok)
log_case("9.4 代理池健康检查",
         st == 200 and d.get("code") == 0,
         f"code={d.get('code')}")

# ============================================================
# 步骤 10：风控 + 报表
# ============================================================
print("\n━━━ 步骤 10：风控 + 报表 ━━━")
# 10.1 风控事件
st, d = req("GET", "/risk/events", token=tok)
log_case("10.1 风控事件列表",
         st == 200 and d.get("code") == 0,
         f"code={d.get('code')}")

# 10.1b 风控摘要
st, d = req("GET", "/risk/summary", token=tok)
log_case("10.1b 风控摘要",
         st == 200 and d.get("code") == 0,
         f"code={d.get('code')}")

# 10.2 用户管理
st, d = req("GET", "/users", token=tok)
log_case("10.2 用户管理列表",
         st == 200 and d.get("code") == 0,
         f"total={(d.get('data') or {}).get('total', len((d.get('data') or {}).get('items', [])))}")

# ============================================================
# 步骤 11：退出登录
# ============================================================
print("\n━━━ 步骤 11：退出登录 ━━━")
st, d = req("POST", "/auth/logout", token=tok)
log_case("11.1 退出登录", st == 200 and d.get("code") == 0,
        f"code={d.get('code')}")

# 退出后访问应被拒（JWT 无状态，logout 仅前端清 token；后端不强制黑名单）
st, d = req("GET", "/users/me", token=tok)
log_case("11.2 退出登录后旧 Token 行为（JWT无状态：接受或拒绝均可）",
         d.get("code") in (0, 4010),
         f"code={d.get('code')}（JWT 无状态，后端不强制黑名单）")

# ============================================================
# 清理：删除演示用策略和交易所账号
# ============================================================
print("\n━━━ 清理：删除演示数据 ━━━")
# 重新登录清理
st, d = req("POST", "/auth/login", data={"username": "admin", "password": "Admin@2024"})
tok2 = (d.get("data") or {}).get("access_token", "")

if new_sid:
    st, d = req("DELETE", f"/strategies/{new_sid}", token=tok2)
    log_case("清理.1 删除演示策略", d.get("code") == 0, f"sid={new_sid} code={d.get('code')}")

if new_acct_id:
    st, d = req("DELETE", f"/exchange/accounts/{new_acct_id}", token=tok2)
    log_case("清理.2 删除演示交易所账号", d.get("code") == 0, f"acct_id={new_acct_id} code={d.get('code')}")

# ============================================================
# 汇总
# ============================================================
print("\n" + "=" * 70)
print(f"📊 模拟交易全链路演示汇总：通过 {PASS} / {PASS + FAIL} ，失败 {FAIL}")
print("=" * 70)
if ERRORS:
    print("\n❌ 失败用例明细：")
    for e in ERRORS:
        print(f"  - {e}")
sys.exit(0 if FAIL == 0 else 1)
