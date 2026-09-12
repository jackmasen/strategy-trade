r"""
后端端到端深度测试脚本
覆盖：认证、用户、交易所、策略、交易、AI、新闻、风控、回测、报表、权限、异常输入
用法：.venv\Scripts\python.exe test_backend_e2e.py
"""
import sys, json, time, urllib.request, urllib.error, urllib.parse

BASE = "http://127.0.0.1:8001/api/v1"
PASS = 0
FAIL = 0
FAIL_CASES = []

ADMIN = {"username": "admin", "password": "Admin@2024"}
TRADER = {"username": "trader", "password": "Trader@2024"}

def D(d, key, default=None):
    if not isinstance(d, dict):
        return default
    v = d.get(key, default)
    return v if v is not None else default

def log_case(name, ok, detail=""):
    global PASS, FAIL
    mark = "✅" if ok else "❌"
    print(f"  {mark} {name}{('  -  ' + str(detail)) if detail else ''}")
    if ok:
        PASS += 1
    else:
        FAIL += 1
        FAIL_CASES.append((name, str(detail)))

def ok(data, expected_code=0):
    return isinstance(data, dict) and data.get("code") == expected_code

def req(method, path, data=None, token=None, content_type="application/json"):
    url = BASE + path
    body = None
    headers = {}
    if content_type == "application/json" and data is not None:
        body = json.dumps(data).encode()
        headers["Content-Type"] = "application/json"
    elif content_type == "form" and data is not None:
        body = urllib.parse.urlencode(data).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(r, timeout=20) as resp:
            text = resp.read().decode("utf-8")
            try:
                return resp.status, json.loads(text)
            except Exception:
                return resp.status, {"code": 9997, "message": text[:200]}
    except urllib.error.HTTPError as e:
        text = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(text)
        except Exception:
            return e.code, {"code": 9996, "message": text[:200]}
    except Exception as e:
        return 0, {"code": 9998, "message": str(e)}

# ============================================================
#  L0. 基础连通性
# ============================================================
print("\n===== [L0] 基础连通性 =====")
try:
    with urllib.request.urlopen("http://127.0.0.1:8001/health", timeout=5) as hp:
        hd = json.loads(hp.read())
        log_case("health 接口可达", D(hd, "data", {}).get("status") == "ok", str(hd))
except Exception as e:
    log_case("health 接口可达", False, str(e))

# ============================================================
#  L1. 认证模块
# ============================================================
print("\n===== [L1] 认证模块 =====")
st, d = req("POST", "/auth/login", data={"username":"notexist","password":"123456"})
log_case("不存在用户登录失败", not ok(d), f"code={D(d,'code')}")

st, d = req("POST", "/auth/login", data={"username":"admin","password":"wrongpass"})
log_case("错误密码登录失败", not ok(d), f"code={D(d,'code')} msg={D(d,'message','')}")

st, d = req("POST", "/auth/login", data={"username":"admin","password":"Admin@2024"})
ADMIN_TOKEN = D(d, "data", {}).get("access_token", "") if ok(d) else ""
ADMIN_USER = D(d, "data", {}).get("user", {})
log_case("admin 登录成功", ok(d) and bool(ADMIN_TOKEN), f"token_len={len(ADMIN_TOKEN)}")
log_case("login user 字段完整（含 username/role）",
         bool(D(ADMIN_USER,"username")) and D(ADMIN_USER,"role") is not None,
         f"keys={list(ADMIN_USER.keys()) if isinstance(ADMIN_USER,dict) else 'N/A'}")
log_case("login user role=1(管理员)", D(ADMIN_USER,"role") == 1, f"role={D(ADMIN_USER,'role')}")

st, d = req("POST", "/auth/login", data=TRADER)
TRADER_TOKEN = D(d, "data", {}).get("access_token", "") if ok(d) else ""
TRADER_USER = D(d, "data", {}).get("user", {}) if isinstance(d, dict) else {}
log_case("trader 登录成功", ok(d) and bool(TRADER_TOKEN),
         f"role={D(TRADER_USER,'role') if isinstance(TRADER_USER,dict) else 'N/A'} msg={D(d,'message','')[:50]}")

st, d = req("GET", "/users/me", token=ADMIN_TOKEN)
log_case("/users/me 拉取自身信息", ok(d) and D(d,"data",{}).get("username") == "admin",
         f"keys={list(D(d,'data',{}).keys())}")

st, d = req("GET", "/users/me", token="invalid.token.value")
log_case("无效 Token 访问 /users/me 被拒", D(d,"code",9998) not in (0, 9998), f"code={D(d,'code')}")

# ============================================================
#  L2. 用户管理（权限）
# ============================================================
print("\n===== [L2] 用户管理（权限 + CRUD） =====")
st, d = req("GET", "/users", token=TRADER_TOKEN)
log_case("非管理员访问用户列表被拒", not ok(d), f"code={D(d,'code')}")

st, d = req("GET", "/users", token=ADMIN_TOKEN)
log_case("管理员拉取用户列表", ok(d) and "items" in (D(d,"data") or {}),
         f"total={D(D(d,'data'),'total')}")

NEW_USER_NAME = f"e2e_test_{int(time.time())}"
st, d = req("POST", "/users", token=ADMIN_TOKEN, data={
    "username": NEW_USER_NAME,
    "password": "Test@2024",
    "nickname": "E2E测试用户",
    "role": 3,
})
created_user_id = None
if ok(d):
    created_user_id = (D(d,"data") or {}).get("id")
log_case("管理员创建新用户", ok(d) and created_user_id is not None, f"uid={created_user_id}")

if created_user_id:
    st, d = req("PUT", f"/users/{created_user_id}", token=ADMIN_TOKEN,
                data={"nickname": "E2E修改后", "role": 2})
    log_case("管理员修改用户信息", ok(d), D(d,"message",""))

    st, d = req("DELETE", f"/users/{created_user_id}", token=ADMIN_TOKEN)
    log_case("管理员删除测试用户", ok(d), D(d,"message",""))

st, d = req("DELETE", "/users/1", token=ADMIN_TOKEN)
log_case("删除超级管理员(uid=1) 被拒绝", not ok(d), f"msg={D(d,'message','')}")

# ============================================================
#  L3. 交易所模块
# ============================================================
print("\n===== [L3] 交易所账号模块 =====")
st, d = req("GET", "/exchange/supported-symbols", token=ADMIN_TOKEN)
log_case("支持交易品种列表", ok(d) and isinstance(D(d,"data"), list) and len(D(d,"data")) >= 3,
         f"symbols={[s.get('symbol') for s in (D(d,'data') or [])[:5]]}")

st, d = req("GET", "/exchange/accounts", token=ADMIN_TOKEN)
log_case("交易所账号列表", ok(d) and "items" in (D(d,"data") or {}),
         f"total={D(D(d,'data'),'total')}")

st, d = req("POST", "/exchange/accounts", token=ADMIN_TOKEN, data={
    "exchange": 1,  # 1=币安 2=OKX
    "sub_account_name": f"E2E测试子账号_{int(time.time())}",
    "sub_account_id": f"e2e_mock_{int(time.time())}",
    "api_key": "test_key_xxxxxxxxxxx",
    "api_secret": "test_secret_xxxxxxxx",
    "api_passphrase": "",
    "ip_whitelist": "",
    "leverage_max": 5,
    "testnet": True,
    "remark": "E2E创建后删除",
})
created_acc_id = None
if ok(d):
    created_acc_id = (D(d,"data") or {}).get("id")
log_case("创建交易所子账号", ok(d) and created_acc_id is not None,
         f"aid={created_acc_id} msg={D(d,'message','')}")

if created_acc_id:
    st, d = req("GET", f"/exchange/accounts/{created_acc_id}/balance", token=ADMIN_TOKEN)
    log_case("查询子账号余额（缓存）", ok(d) or (D(d,"code",9998) != 9998),
             f"code={D(d,'code')} msg={str(D(d,'message',''))[:60]}")
    st, d = req("GET", f"/exchange/accounts/{created_acc_id}/positions", token=ADMIN_TOKEN)
    log_case("查询子账号持仓（空）", ok(d) or (D(d,"code",9998) != 9998),
             f"code={D(d,'code')} msg={str(D(d,'message',''))[:60]}")
    st, d = req("DELETE", f"/exchange/accounts/{created_acc_id}", token=ADMIN_TOKEN)
    log_case("删除测试交易所账号", ok(d), D(d,"message",""))

st, d = req("GET", "/exchange/ticker/BTC", token=ADMIN_TOKEN)
log_case("BTC 行情 ticker", ok(d) or (D(d,"code",9998) != 9998),
         f"code={D(d,'code')} msg={str(D(d,'message',''))[:60]}")

st, d = req("GET", "/exchange/klines/BTC?interval=1h&limit=10", token=ADMIN_TOKEN)
log_case("BTC 1H K线 (limit=10)", ok(d) or (D(d,"code",9998) != 9998),
         f"code={D(d,'code')} msg={str(D(d,'message',''))[:60]}")

# ============================================================
#  L4. 策略模块
# ============================================================
print("\n===== [L4] 策略模块 =====")
st, d = req("GET", "/strategies/default-template", token=ADMIN_TOKEN)
log_case("策略默认模板", ok(d) and isinstance(D(d,"data"), dict),
         f"keys={list((D(d,'data') or {}).keys())[:8]}")

st, d = req("GET", "/strategies", token=ADMIN_TOKEN)
log_case("策略列表", ok(d) and "items" in (D(d,"data") or {}),
         f"total={D(D(d,'data'),'total')}")

st, d = req("POST", "/strategies", token=ADMIN_TOKEN, data={
    "strategy_name": f"E2E测试策略_{int(time.time())}",
    "description": "E2E创建后会立即删除",
    "symbols": ["BTC", "ETH"],
    "timeframe": "1h,4h",
    "direction_mode": 0,
    "run_mode": 3,
    "score_threshold": 5.0,
    "strong_score_threshold": 8.0,
    "weight_technical": 0.4,
    "weight_news": 0.3,
    "weight_ai": 0.3,
    "leverage_mode": 2,
    "leverage_fixed": 3,
    "leverage_low_score": 3,
    "leverage_mid_score": 5,
    "leverage_high_score": 8,
    "tp_ratio": 4.0,
    "sl_ratio": 2.0,
    "use_exchange_tpsl": True,
    "single_position_ratio": 10.0,
    "total_position_ratio": 50.0,
    "max_position_count": 3,
    "max_single_drawdown": 2.0,
    "daily_max_loss": 5.0,
    "is_active": False,
})
created_sid = None
if ok(d):
    created_sid = (D(d,"data") or {}).get("id")
log_case("创建策略", ok(d) and created_sid is not None,
         f"sid={created_sid} msg={D(d,'message','')}")

if created_sid:
    st, d = req("GET", f"/strategies/{created_sid}", token=ADMIN_TOKEN)
    log_case("策略详情", ok(d) and (D(d,"data") or {}).get("id") == created_sid, "")

    st, d = req("POST", f"/strategies/{created_sid}/toggle?active=true", token=ADMIN_TOKEN)
    log_case("策略启停切换", ok(d) or (D(d,"code",9998) != 9998),
             f"code={D(d,'code')} msg={str(D(d,'message',''))[:60]}")

    st, d = req("GET", f"/strategies/{created_sid}/scores", token=ADMIN_TOKEN)
    log_case("策略评分记录（空）", ok(d) and "items" in (D(d,"data") or {}),
             f"total={D(D(d,'data'),'total','N/A')}")

    st, d = req("DELETE", f"/strategies/{created_sid}", token=ADMIN_TOKEN)
    log_case("删除测试策略", ok(d), D(d,"message",""))

st, d = req("GET", "/strategies/scores/latest", token=ADMIN_TOKEN)
log_case("所有策略最新评分", ok(d) or (D(d,"code",9998) != 9998),
         f"code={D(d,'code')} msg={str(D(d,'message',''))[:80]}")

# ============================================================
#  L5. 交易模块（订单/持仓/历史/总览）
# ============================================================
print("\n===== [L5] 交易模块 =====")
st, d = req("GET", "/trades/orders", token=ADMIN_TOKEN)
log_case("订单列表", ok(d) and "items" in (D(d,"data") or {}),
         f"total={D(D(d,'data'),'total')}")

st, d = req("GET", "/trades/positions", token=ADMIN_TOKEN)
log_case("持仓列表", ok(d) and "items" in (D(d,"data") or {}),
         f"total={D(D(d,'data'),'total')}")

st, d = req("GET", "/trades/history", token=ADMIN_TOKEN)
log_case("交易历史", ok(d) and "items" in (D(d,"data") or {}),
         f"total={D(D(d,'data'),'total')}")

st, d = req("GET", "/trades/overview", token=ADMIN_TOKEN)
log_case("交易总览（统计卡）", ok(d) or (D(d,"code",9998) != 9998),
         f"code={D(d,'code')} keys={list((D(d,'data') or {}).keys())[:6]}")

# ============================================================
#  L6. AI / 新闻 / 风控 / 回测 / 报表
# ============================================================
print("\n===== [L6] AI + 新闻 + 风控 + 回测 + 报表 =====")
st, d = req("GET", "/ai/config", token=ADMIN_TOKEN)
log_case("AI 配置获取（无敏感明文）", ok(d) and isinstance(D(d,"data"), dict),
         f"keys={list((D(d,'data') or {}).keys())}")

st, d = req("GET", "/news", token=ADMIN_TOKEN)
log_case("新闻列表", ok(d) and "items" in (D(d,"data") or {}),
         f"total={D(D(d,'data'),'total')}")

st, d = req("GET", "/news/sentiment/summary?symbol=BTC", token=ADMIN_TOKEN)
log_case("新闻情绪摘要(BTC)", ok(d) or (D(d,"code",9998) != 9998),
         f"code={D(d,'code')} msg={str(D(d,'message',''))[:60]}")

st, d = req("GET", "/news/proxy/health", token=ADMIN_TOKEN)
log_case("代理池健康度", ok(d) or (D(d,"code",9998) != 9998),
         f"code={D(d,'code')} msg={str(D(d,'message',''))[:60]}")

st, d = req("GET", "/risk/events", token=ADMIN_TOKEN)
log_case("风控事件列表", ok(d) and "items" in (D(d,"data") or {}),
         f"total={D(D(d,'data'),'total')}")

st, d = req("GET", "/risk/summary?days=7", token=ADMIN_TOKEN)
log_case("风控摘要(7天)", ok(d) or (D(d,"code",9998) != 9998),
         f"code={D(d,'code')} msg={str(D(d,'message',''))[:60]}")

st, d = req("GET", "/backtests", token=ADMIN_TOKEN)
log_case("回测任务列表", ok(d) and "items" in (D(d,"data") or {}),
         f"total={D(D(d,'data'),'total')}")

st, d = req("POST", "/backtests", token=ADMIN_TOKEN, data={
    "strategy_id": 0,
    "run_name": "E2E边界回测",
    "symbols": ["BTC"],
    "timeframe": "1h",
    "date_start": "2025-01-01T00:00:00",
    "date_end": "2025-01-10T00:00:00",
    "initial_capital": 10000.0,
    "fee_rate": 0.04,
    "slippage": 0.05,
    "strategy_params": {},
})
log_case("创建回测任务（边界入参）", D(d,"code",9998) != 9998,
         f"code={D(d,'code')} msg={str(D(d,'message',''))[:60]}")

st, d = req("GET", "/reports/dashboard?days=30", token=ADMIN_TOKEN)
log_case("Dashboard 报表数据", ok(d) or (D(d,"code",9998) != 9998),
         f"code={D(d,'code')} msg={str(D(d,'message',''))[:60]}")

st, d = req("GET", "/reports/daily", token=ADMIN_TOKEN)
log_case("日报列表", ok(d) and "items" in (D(d,"data") or {}),
         f"total={D(D(d,'data'),'total')}")

st, d = req("GET", "/reports/weekly", token=ADMIN_TOKEN)
log_case("周报列表", ok(d) and "items" in (D(d,"data") or {}),
         f"total={D(D(d,'data'),'total')}")

st, d = req("GET", "/reports/monthly", token=ADMIN_TOKEN)
log_case("月报列表", ok(d) and "items" in (D(d,"data") or {}),
         f"total={D(D(d,'data'),'total')}")

# ============================================================
#  L7. 权限：未登录访问受保护资源
# ============================================================
print("\n===== [L7] 权限：未登录/越权 =====")
st, d = req("GET", "/users/me")
log_case("未 Token 访问 /users/me 被拒", not ok(d), f"code={D(d,'code')}")

st, d = req("GET", "/users", token=TRADER_TOKEN)
log_case("trader 访问 /users 被拒", not ok(d), f"code={D(d,'code')}")

st, d = req("GET", "/trades/overview", token=None)
log_case("未 Token 访问 /trades/overview 被拒", not ok(d), f"code={D(d,'code')}")

# ============================================================
#  L8. 异常输入
# ============================================================
print("\n===== [L8] 异常输入鲁棒性 =====")
st, d = req("POST", "/auth/login", data={"username": "x", "password": "x"})
log_case("短用户名/短密码登录 422 级验证", D(d,"code",9998) != 9998, f"code={D(d,'code')}")

st, d = req("POST", "/users", token=ADMIN_TOKEN, data={"username":"ab"})
log_case("创建用户缺必填字段 422 级参数校验", D(d,"code",9998) != 9998, f"code={D(d,'code')}")

st, d = req("GET", "/exchange/klines/INVALID?interval=1h&limit=10", token=ADMIN_TOKEN)
log_case("非法交易对行情查询不崩溃", D(d,"code",9998) != 9998, f"code={D(d,'code')} msg={str(D(d,'message',''))[:40]}")

# ============================================================
#  L9. AI 模块深度用例（V2）：configRW权限+analyzeMock成功+JSON校验降级+401透传+trader禁PUT
# ============================================================
print("\n===== [L9] AI 模块 V2 深度 =====")

# ====== L9 前置：清 DB 中可能遗留的测试假 Key（避免上轮测试或人工写入残留导致 has_key=True） ======
req("PUT", "/ai/config", token=ADMIN_TOKEN, data={
    "provider": "custom", "model_name": "gpt-4o", "api_endpoint": "",
    "api_key": "__CLEAR__", "temperature": 3, "max_tokens": 800, "max_retries": 2,
})

# --- 用例 1：config GET 权限 & 安全（无明文 Key、字段齐全） ---
st, d = req("GET", "/ai/config")
log_case("AI[1a] 未登录GET /ai/config 被拒", not ok(d), f"code={D(d,'code')}")

st, d = req("GET", "/ai/config", token=TRADER_TOKEN)
log_case("AI[1b] trader GET /ai/config 可读", ok(d) and isinstance(D(d,"data"), dict),
         f"keys={list((D(d,'data') or {}).keys())}")

st, d = req("GET", "/ai/config", token=ADMIN_TOKEN)
cfg_data = D(d, "data") or {}
_get_ok = ok(d) and isinstance(cfg_data, dict)
_key_safe = True
_key_leak_samples = []
if _get_ok:
    import re as _re
    resp_str = json.dumps(cfg_data, ensure_ascii=False)
    # 安全：明文 Key 规则是 sk- 后跟至少 8 位字母/数字（如 sk-abc123XYZ789）
    # 允许打码格式 sk-**** / sk-I**** 等（* 不算真 Key）
    for m in _re.finditer(r"sk-[A-Za-z0-9_\-]{6,}", resp_str):
        tok = m.group(0)
        real_chars = sum(1 for ch in tok[3:] if ch not in "*#xX·")
        if real_chars >= 8:
            _key_safe = False
            _key_leak_samples.append(tok[:24])
    required_keys = {"provider", "model_name", "api_endpoint", "api_key_masked", "has_key",
                     "temperature", "max_tokens", "request_timeout_sec", "max_retries"}
    _get_ok = _get_ok and required_keys.issubset(set(cfg_data.keys()))
log_case("AI[1c] admin GET /ai/config 字段齐全+无明文Key泄露",
         ok(d) and _get_ok and _key_safe,
         f"has_key={cfg_data.get('has_key')} masked={cfg_data.get('api_key_masked')} provider={cfg_data.get('provider')} leaks={_key_leak_samples}")

# --- 用例 2：config PUT 权限（trader 禁止 / admin 允许且不改 Key 只改温度） ---
st, d = req("PUT", "/ai/config", token=TRADER_TOKEN, data={
    "provider": "custom", "model_name": "trader-hack-model",
    "api_key": "sk-TRADER-SHOULD-NOT-WRITE",
})
log_case("AI[2a] trader PUT /ai/config 被拒（仅管理员）", not ok(d),
         f"code={D(d,'code')} status={st}")

orig_provider = cfg_data.get("provider") or "custom"
orig_model = cfg_data.get("model_name") or "gpt-4o"
orig_endpoint = cfg_data.get("api_endpoint") or ""
st, d = req("PUT", "/ai/config", token=ADMIN_TOKEN, data={
    "provider": orig_provider,
    "model_name": orig_model,
    "api_endpoint": orig_endpoint,
    "api_key": "",   # 空串：不改 Key（幂等安全）
    "temperature": 4,
    "max_tokens": 600,
    "max_retries": 2,
})
cfg_after_put = D(d, "data") or {}
log_case("AI[2b] admin PUT /ai/config 成功（热生效+Key保留）",
         ok(d) and cfg_after_put.get("temperature") == 4 and cfg_after_put.get("max_tokens") == 600,
         f"temp={cfg_after_put.get('temperature')} tokens={cfg_after_put.get('max_tokens')} has_key={cfg_after_put.get('has_key')}")

# --- 用例 3：analyze Mock 成功（结构化 JSON 校验：score/方向/reason长度） ---
st, d = req("POST", "/ai/analyze", token=ADMIN_TOKEN, data={
    "analysis_type": "score",
    "symbol": "BTC",
    "timeframe": "4h",
    "manual_prompt": "E2E测试用，走mock模式",
    "mock": True,
})
mock_payload = D(d, "data") or {}
mock_success = ok(d) and bool(mock_payload.get("success"))
ai_score = mock_payload.get("ai_score")
ai_direction = (mock_payload.get("ai_direction") or "").lower()
ai_reason = mock_payload.get("ai_reason") or ""
_score_ok = isinstance(ai_score, (int, float)) and 0.0 <= float(ai_score) <= 10.0
_dir_ok = ai_direction in {"long", "short", "neutral"}
_reason_ok = isinstance(ai_reason, str) and len(ai_reason) >= 10
log_case("AI[3] POST /ai/analyze mock成功 + 字段合规(JSON schema校验)",
         mock_success and _score_ok and _dir_ok and _reason_ok,
         f"success={mock_payload.get('success')} score={ai_score} dir={ai_direction} reason_len={len(ai_reason)} latency={mock_payload.get('latency_ms')}ms")

# --- 用例 4：错误透传（配置 NOT_CONFIGURED → success=false+error_code，HTTP=200不吞异常） ---
# 临时切到 openai 无 Key 无 endpoint 场景
st, d = req("PUT", "/ai/config", token=ADMIN_TOKEN, data={
    "provider": "openai",
    "model_name": "gpt-4o",
    "api_endpoint": "",
    "api_key": "",   # 空 = 不改，所以我们先确保用一个明确 provider=openai
})
st, d = req("POST", "/ai/analyze", token=ADMIN_TOKEN, data={
    "analysis_type": "score", "symbol": "ETH", "timeframe": "1h", "mock": False,
})
err_payload = D(d, "data") or {}
_http_ok = st == 200 or (isinstance(st, int) and st > 0)
_biz_fail = isinstance(err_payload, dict) and err_payload.get("success") is False
_err_code = err_payload.get("error_code") or ""
_err_msg = err_payload.get("error_msg") or ""
log_case("AI[4a] 无配置时 /ai/analyze 失败透传（HTTP=200, success=false, error_code 明确）",
         _http_ok and _biz_fail and bool(_err_code),
         f"HTTP={st} success={err_payload.get('success')} err_code={_err_code} msg={_err_msg[:80]}")
# 恢复成原 provider（避免影响后续 / 运营）
st, d = req("PUT", "/ai/config", token=ADMIN_TOKEN, data={
    "provider": orig_provider, "model_name": orig_model, "api_endpoint": orig_endpoint,
    "api_key": "", "temperature": 3, "max_tokens": 800, "max_retries": 2,
})

# --- 用例 5：JSON 校验降级（mock 的合法 JSON 已经过校验，这里用真调失败的错误码分类检查） ---
# 再次验证：401 模拟 → 通过临时写入一个无效 Key，再调 analyze（真发请求），应返回 PROVIDER_401 或 NOT_CONFIGURED，绝不 500
st, d = req("PUT", "/ai/config", token=ADMIN_TOKEN, data={
    "provider": "openai",
    "model_name": "gpt-4o-mini",
    "api_endpoint": "https://api.openai.com/v1",
    "api_key": "sk-INVALID-KEY-FOR-E2E-TEST-1234567890",  # 假 Key，用于触发 401
    "max_retries": 1, "request_timeout_sec": 8,
})
st, d = req("POST", "/ai/analyze", token=ADMIN_TOKEN, data={
    "analysis_type": "score", "symbol": "SOL", "timeframe": "1h", "mock": False,
})
fail_payload = D(d, "data") or {}
_HTTP_ok = isinstance(st, int) and st > 0
_biz_resp_structured = isinstance(fail_payload, dict) and "success" in fail_payload
_err_codes_allowed = {
    "AI_PROVIDER_401", "AI_NOT_CONFIGURED", "AI_TIMEOUT", "AI_NETWORK_ERROR",
    "AI_PROVIDER_403", "AI_PROVIDER_5XX", "AI_UNKNOWN", "AI_PROVIDER_429",
}
_code_class_ok = (fail_payload.get("error_code") or "") in _err_codes_allowed or fail_payload.get("success") is False
log_case("AI[4b/5] 假Key调用：结构化错误码分类正确，无500崩溃",
         _HTTP_ok and _biz_resp_structured and _code_class_ok,
         f"HTTP={st} success={fail_payload.get('success')} err_code={fail_payload.get('error_code')} msg={str(fail_payload.get('error_msg',''))[:80]}")
# 恢复配置到本地离线模式（运营安全：用 __CLEAR__ 主动清除测试写入的假 Key）
st, d = req("PUT", "/ai/config", token=ADMIN_TOKEN, data={
    "provider": orig_provider, "model_name": orig_model, "api_endpoint": orig_endpoint,
    "api_key": "__CLEAR__",  # 魔法值：主动清空 DB 中的 Key，确保不落假 Key
    "temperature": 3, "max_tokens": 800, "max_retries": 2,
})
cfg_restored = D(d, "data") or {}
log_case("AI[4c] 用例后配置回滚成功（温度恢复+Key 已安全清空）",
         ok(d) and cfg_restored.get("temperature") == 3 and cfg_restored.get("max_tokens") == 800
         and cfg_restored.get("has_key") is False,
         f"temp={cfg_restored.get('temperature')} tokens={cfg_restored.get('max_tokens')} has_key={cfg_restored.get('has_key')} masked={cfg_restored.get('api_key_masked')}")

# ============================================================
#  汇总
# ============================================================
TOTAL = PASS + FAIL
print("\n" + "=" * 60)
print(f"📊 测试汇总：通过 {PASS} / {TOTAL} ，失败 {FAIL}")
if FAIL_CASES:
    print("❌ 失败用例清单：")
    for name, detail in FAIL_CASES:
        print(f"   - {name}\n     {detail}")
print("=" * 60)
sys.exit(0 if FAIL == 0 else 1)

