"""
统一 AI 客户端服务层（V2 真实现）
覆盖：OpenAI 官方 / DeepSeek / 通义千问 / 豆包 / 硅基流动 / OneAPI / 本地 Ollama（走 OpenAI 兼容协议）
以及 Anthropic Claude 独立分支
设计遵循：
  - 经验 936341：结构化 JSON 输出 + 2 次重试补全
  - 经验 1283322：第三方非 200 直接透传 error_code+状态码，不吞异常
  - 经验 1514746 / 936341：密钥仅在此模块内用 security.decrypt 解密出明文，绝不外溢到日志
"""
from __future__ import annotations

import json
import time
import re
from dataclasses import dataclass, field, asdict
from typing import Optional, Any, Dict

import httpx

from backend.core.logging_config import logger
from backend.models.ai_config import AIConfig
from backend.core.security import decrypt_api_key, mask_api_key


# ============== 错误码常量 ==============
ERR_NOT_CONFIGURED = "AI_NOT_CONFIGURED"      # 无 Key / 未配置
ERR_INVALID_JSON = "AI_INVALID_JSON"           # 模型输出不是合法 JSON 或字段不符合（2 次重试仍失败）
ERR_PROVIDER_401 = "AI_PROVIDER_401"           # Key 无效 / 未授权
ERR_PROVIDER_403 = "AI_PROVIDER_403"
ERR_PROVIDER_404 = "AI_PROVIDER_404"           # 模型已退役 / endpoint 错
ERR_PROVIDER_410 = "AI_PROVIDER_410_RETIRED"   # 模型退役（对应 minimax 经验）
ERR_PROVIDER_429 = "AI_PROVIDER_429_RATE_LIMIT"
ERR_PROVIDER_5XX = "AI_PROVIDER_5XX"
ERR_TIMEOUT = "AI_TIMEOUT"
ERR_NETWORK = "AI_NETWORK_ERROR"
ERR_UNKNOWN = "AI_UNKNOWN"


# ============== 结构化 Schema（Prompt + 服务端校验） ==============
SYSTEM_PROMPT_BASE = """你是一名专业的加密货币/美股量化交易分析师。只输出严格合法 JSON，禁止任何额外文字、Markdown、```json 包裹、前言或解释。

你必须基于提供的实时数据进行综合分析，核心原则：
1. **实时价格优先**：首先参考【实时价格】中的当前价、买一价、卖一价和24h涨跌幅，这是最新市场状态。
2. **高低价关键位**：【近期高低价】中的20根最高/最低价是关键支撑阻力位。当前价格接近高点（>80%）注意回调风险，接近低点（<20%）注意反弹机会。
3. **技术指标综合**：结合MA均线排列（多头/空头/交叉）、RSI超买超卖、MACD多空、成交量趋势，判断技术面方向。
4. **新闻情绪交叉验证**：将技术面与【新闻情绪总结】交叉验证。新闻平均情绪偏多+技术面多头=强化看多；新闻偏空+技术面多头=注意风险。高影响级别（3-4级）新闻优先于低影响级别。
5. **新闻新鲜度判断**：标注了发布时间（X分钟前/X小时前/X天前）。1小时内的新闻影响最大，超过6小时的新闻影响递减，超过24小时的视为过期因素，以技术面为主。
6. **真实方向判断**：综合以上因素给出真实可执行的方向判断，不要模棱两可。如果技术面和新闻面矛盾，说明矛盾并给出倾向性建议。

必须返回一个对象，包含且仅包含以下三个字段：
  ai_score:      number, 范围 0.0 ~ 10.0，保留 1 位小数。7~10=强烈看多，4~6=中性/震荡，0~3=强烈看空。
  ai_direction:  string, 只允许 "long" / "short" / "neutral" 三选一。
  ai_reason:     string, 100~500 字的中文理由。必须包含：(1)实时价格位置与高低价关系，(2)技术指标综合判断(MA/RSI/MACD/量能)，(3)新闻情绪与新鲜度对价格的影响，(4)综合方向结论与风险提示。不要用序号列表。
"""

DIRECTION_SET = {"long", "short", "neutral"}


@dataclass
class AIResult:
    """标准化 AI 结果（给路由层和评分引擎用）"""
    # 成功标志
    success: bool
    error_code: Optional[str] = None           # None 表示成功，失败时为上面常量之一
    error_msg: Optional[str] = None            # 可读错误（含第三方错误），给前端 ElMessage
    third_party_status: Optional[int] = None   # 第三方 HTTP 状态码（透传给运营排查）

    # 结构化输出（success=True 时必不为空）
    ai_score: Optional[float] = None
    ai_direction: Optional[str] = None
    ai_reason: Optional[str] = None

    # 指标
    latency_ms: int = 0
    tokens_prompt: int = 0
    tokens_completion: int = 0
    tokens_total: int = 0
    cost_usd: float = 0.0

    # 调试用（给 analyze endpoint 返回时可选附带）
    raw_response: str = ""
    model_name: str = ""
    provider: str = ""

    def as_public_dict(self) -> Dict[str, Any]:
        """路由返回给前端用（去掉 raw_response 敏感字段，保留 reason 等业务字段）"""
        d = asdict(self)
        d.pop("raw_response", None)
        return d


# ============== 主类 ==============
class AIClient:
    """无状态客户端（每次请求 new 一个或复用实例均可），所有明文 Key 只在 _do_request 作用域内"""

    def __init__(self, cfg: AIConfig):
        self.cfg = cfg

    # ======= 对外主入口 =======
    def analyze(
        self,
        *,
        analysis_type: str = "score",
        symbol: Optional[str] = None,
        timeframe: str = "4h",
        manual_prompt: str = "",
        candles_snapshot: Optional[str] = "",
        news_snapshot: Optional[str] = "",
        _mock: bool = False,
    ) -> AIResult:
        """
        执行 AI 分析，返回标准化 AIResult。
        - _mock=True：不发真实 HTTP，直接返回合法 JSON（测试脚本用，避免浪费真钱额度）
        """
        t0 = time.perf_counter()
        if _mock:
            return self._mock_result(symbol=symbol, manual_prompt=manual_prompt, latency_ms=int((time.perf_counter() - t0) * 1000) + 120)

        # 1. 前置校验：有没有配置（必须有 api_key 明文或 custom/local 允许无 Key 的本地服务）
        api_key = decrypt_api_key(self.cfg.api_key_encrypted or "")
        provider_name = self.cfg.provider_name
        if provider_name in ("openai", "anthropic") and not api_key:
            return self._fail(ERR_NOT_CONFIGURED, "尚未配置 AI API Key，请管理员在【AI 配置】中保存有效的 Key", latency_ms=int((time.perf_counter() - t0) * 1000))
        if provider_name in ("custom", "local") and (not self.cfg.api_endpoint):
            return self._fail(ERR_NOT_CONFIGURED, "尚未配置 AI API Endpoint，请在【AI 配置】中填写兼容 OpenAI 协议的接口地址", latency_ms=int((time.perf_counter() - t0) * 1000))

        # 2. 组装 Prompt（严格、最小、结构化）
        user_prompt = self._build_user_prompt(
            analysis_type=analysis_type, symbol=symbol, timeframe=timeframe,
            manual_prompt=manual_prompt, candles_snapshot=candles_snapshot, news_snapshot=news_snapshot,
        )

        # 3. 发请求（最多 1 首次 + max_retries 次重试，最后 1 次强制 STRICT_JSON 再试）
        max_retries = max(0, int(self.cfg.max_retries or 0))
        total_attempts = 1 + max_retries
        last_result: Optional[AIResult] = None

        for attempt in range(1, total_attempts + 1):
            # 最后一次尝试强制 JSON 提示（修复模型非 JSON 输出问题：经验 936341）
            force_json_strict = (attempt == total_attempts)
            attempt_result = self._call_once(
                user_prompt=user_prompt,
                api_key=api_key,
                force_json_strict=force_json_strict,
                attempt=attempt,
                total_attempts=total_attempts,
            )
            if attempt_result.success:
                attempt_result.latency_ms = int((time.perf_counter() - t0) * 1000)
                return attempt_result
            # 若失败原因是非 JSON（其他是网络/权限，重试也没用，直接退）
            if attempt_result.error_code != ERR_INVALID_JSON:
                attempt_result.latency_ms = int((time.perf_counter() - t0) * 1000)
                return attempt_result
            last_result = attempt_result

        # 所有重试仍失败（一定是 ERR_INVALID_JSON）
        if last_result is None:
            last_result = self._fail(ERR_INVALID_JSON, "AI 输出格式异常", latency_ms=int((time.perf_counter() - t0) * 1000))
        last_result.latency_ms = int((time.perf_counter() - t0) * 1000)
        return last_result

    # ======= 内部：单次请求 =======
    def _call_once(
        self,
        *,
        user_prompt: str,
        api_key: str,
        force_json_strict: bool,
        attempt: int,
        total_attempts: int,
    ) -> AIResult:
        provider_name = self.cfg.provider_name
        timeout = max(5, min(15, int(self.cfg.request_timeout_sec or 15)))

        system_prompt = SYSTEM_PROMPT_BASE
        if force_json_strict:
            system_prompt += (
                "\nCRITICAL PREVIOUS WARNING: 你上一次回复不是合法 JSON。本次必须严格返回对象且字段合法，"
                "禁止写任何 JSON 之外的字符、禁止 Markdown、禁止代码块。"
            )
        temperature = max(0, min(10, int(self.cfg.temperature or 3))) / 10.0

        try:
            if provider_name == "anthropic":
                status, raw_text, usage, model = self._call_anthropic(
                    api_key=api_key, system_prompt=system_prompt, user_prompt=user_prompt,
                    max_tokens=int(self.cfg.max_tokens or 800),
                    temperature=temperature, timeout=timeout,
                )
            else:
                # openai / custom / local → 全走 OpenAI Chat Completions
                status, raw_text, usage, model = self._call_openai_compatible(
                    api_key=api_key, system_prompt=system_prompt, user_prompt=user_prompt,
                    max_tokens=int(self.cfg.max_tokens or 800),
                    temperature=temperature, timeout=timeout,
                    provider_name=provider_name,
                )
        except httpx.TimeoutException as e:
            return self._fail(ERR_TIMEOUT, f"请求超时（{timeout}s）：{e}")
        except httpx.HTTPError as e:
            return self._fail(ERR_NETWORK, f"网络异常：{type(e).__name__}：{e}")
        except Exception as e:
            logger.warning(f"[AI] 未知异常 attempt={attempt}/{total_attempts}: {type(e).__name__}: {e}")
            return self._fail(ERR_UNKNOWN, f"{type(e).__name__}: {e}")

        # HTTP 非 2xx → 映射 error_code
        if status is not None and (status < 200 or status >= 300):
            third_msg = (raw_text or "")[:400]
            if status == 401:
                return self._fail(ERR_PROVIDER_401, f"AI Key 无效或无权限（HTTP {status}）：{third_msg}", third_party_status=status)
            if status == 403:
                return self._fail(ERR_PROVIDER_403, f"AI 访问被拒绝（HTTP {status}）：{third_msg}", third_party_status=status)
            if status == 404:
                return self._fail(ERR_PROVIDER_404, f"模型/Endpoint 地址错误（HTTP {status}）：{third_msg}", third_party_status=status)
            if status == 410:
                return self._fail(ERR_PROVIDER_410, f"模型已退役（HTTP 410），请切换其他模型：{third_msg}", third_party_status=status)
            if status == 429:
                return self._fail(ERR_PROVIDER_429, f"触发 AI 供应商限流（HTTP 429），请稍后重试：{third_msg}", third_party_status=status)
            if status >= 500:
                return self._fail(ERR_PROVIDER_5XX, f"AI 供应商服务异常（HTTP {status}）：{third_msg}", third_party_status=status)
            return self._fail(ERR_UNKNOWN, f"AI 供应商返回非 2xx（HTTP {status}）：{third_msg}", third_party_status=status)

        # 解析 JSON（严格校验 schema）
        return self._parse_structured_output(raw_text, usage, model)

    # ======= 协议实现 =======
    def _call_openai_compatible(
        self, *, api_key, system_prompt, user_prompt,
        max_tokens, temperature, timeout, provider_name,
    ):
        """OpenAI / Custom / Local 全部走同一个协议（覆盖 90% 主流模型）"""
        endpoint = (self.cfg.api_endpoint or "").strip().rstrip("/")
        if provider_name == "openai" and not endpoint:
            endpoint = "https://api.openai.com/v1"
        # 兼容：endpoint 可能是根 URL（没 /v1），也可能带了 /v1/chat/completions
        if not endpoint:
            raise RuntimeError("缺少 AI API Endpoint")
        if endpoint.endswith("/chat/completions"):
            url = endpoint
        elif endpoint.endswith("/v1"):
            url = endpoint + "/chat/completions"
        else:
            # 用户可能填了根域名，自动补 /v1/chat/completions（DeepSeek / SiliconFlow / OneAPI 都是这格式）
            url = endpoint.rstrip("/") + "/v1/chat/completions"

        headers = {
            "Authorization": f"Bearer {api_key}" if api_key else "",
            "Content-Type": "application/json",
        }
        if not api_key:
            headers.pop("Authorization", None)  # 本地 Ollama 可能完全不需要 Key
        body = {
            "model": self.cfg.model_name or "gpt-4o",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
            # 有些兼容服务不支持 response_format，只在 openai/custom 可能时加 JSON mode，但我们靠 prompt 约束更稳
        }
        logger.info(f"[AI] 调用 OpenAI兼容 endpoint={url[:80]} model={body['model']} key_masked={mask_api_key(api_key)}")

        with httpx.Client(timeout=timeout) as client:
            resp = client.post(url, headers=headers, json=body)
            status = resp.status_code
            text = resp.text
            usage, model_out = {}, body["model"]
            try:
                data = resp.json()
                if isinstance(data, dict):
                    usage = data.get("usage") or {}
                    model_out = data.get("model") or model_out
                    choices = data.get("choices") or []
                    if choices:
                        msg = choices[0].get("message") or {}
                        text = msg.get("content") or text
            except Exception:
                pass
            return status, text, usage, model_out

    def _call_anthropic(
        self, *, api_key, system_prompt, user_prompt,
        max_tokens, temperature, timeout,
    ):
        """Anthropic Messages API（独立签名头）"""
        endpoint = (self.cfg.api_endpoint or "https://api.anthropic.com").strip().rstrip("/")
        url = endpoint + "/v1/messages"
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        body = {
            "model": self.cfg.model_name or "claude-3-5-sonnet-20241022",
            "system": system_prompt,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [{"role": "user", "content": user_prompt}],
        }
        logger.info(f"[AI] 调用 Anthropic model={body['model']} key_masked={mask_api_key(api_key)}")

        with httpx.Client(timeout=timeout) as client:
            resp = client.post(url, headers=headers, json=body)
            status = resp.status_code
            text = resp.text
            usage, model_out = {}, body["model"]
            try:
                data = resp.json()
                if isinstance(data, dict):
                    usage = data.get("usage") or {}
                    model_out = data.get("model") or model_out
                    blocks = data.get("content") or []
                    if isinstance(blocks, list) and blocks:
                        first_block = blocks[0]
                        if isinstance(first_block, dict):
                            text = first_block.get("text") or text
            except Exception:
                pass
            return status, text, usage, model_out

    # ======= 输出校验 =======
    def _parse_structured_output(self, raw_text: str, usage: dict, model: str) -> AIResult:
        """从 raw_text 中提取 JSON 并做类型/范围校验"""
        # 先清理：去掉 ```json 包裹 / 前后空白
        cleaned = (raw_text or "").strip()
        json_str = self._extract_first_json(cleaned)
        if not json_str:
            return self._fail(ERR_INVALID_JSON, "AI 输出中未找到合法 JSON", raw_response=raw_text, model_name=model)
        try:
            obj = json.loads(json_str)
        except json.JSONDecodeError as e:
            return self._fail(ERR_INVALID_JSON, f"AI 输出 JSON 解析失败：{e}", raw_response=raw_text, model_name=model)
        if not isinstance(obj, dict):
            return self._fail(ERR_INVALID_JSON, "AI 输出 JSON 顶层不是对象", raw_response=raw_text, model_name=model)

        score = obj.get("ai_score")
        direction = obj.get("ai_direction")
        reason = obj.get("ai_reason")

        # 类型与取值校验
        try:
            score_f = float(score)
            if score_f < 0 or score_f > 10:
                raise ValueError("ai_score out of [0,10]")
        except Exception:
            return self._fail(
                ERR_INVALID_JSON,
                f"字段 ai_score 非法（必须是 0~10 数字），实际值：{score!r}",
                raw_response=raw_text, model_name=model,
            )
        direction_s = str(direction or "").strip().lower()
        if direction_s not in DIRECTION_SET:
            return self._fail(
                ERR_INVALID_JSON,
                f"字段 ai_direction 非法（必须 long/short/neutral），实际值：{direction!r}",
                raw_response=raw_text, model_name=model,
            )
        reason_s = str(reason or "").strip()
        if len(reason_s) < 10:
            return self._fail(
                ERR_INVALID_JSON,
                f"字段 ai_reason 太短（至少 10 字），实际 {len(reason_s)} 字",
                raw_response=raw_text, model_name=model,
            )

        # Token 统计：统一兼容 OpenAI 与 Anthropic
        prompt_tk = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
        completion_tk = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)

        r = AIResult(
            success=True,
            ai_score=round(score_f, 1),
            ai_direction=direction_s,
            ai_reason=reason_s,
            tokens_prompt=prompt_tk,
            tokens_completion=completion_tk,
            tokens_total=prompt_tk + completion_tk,
            raw_response=raw_text,
            model_name=str(model or self.cfg.model_name or ""),
            provider=self.cfg.provider_name,
        )
        # 粗估 cost（仅 GPT-4o / Claude 3.5 / deepseek 常见模型，运营可后续精细化）
        r.cost_usd = self._estimate_cost(r.model_name, prompt_tk, completion_tk)
        return r

    # ======= 工具方法 =======
    @staticmethod
    def _extract_first_json(text: str) -> Optional[str]:
        """
        从模型输出中截取第一个完整 JSON 对象：
        策略：优先第一个 { 到最后匹配的 }，如果失败则找 ```json ... ``` 包裹
        """
        if not text:
            return None
        # 1. 尝试 ```json\n...\n``` 包裹（兼容模型不自觉的行为）
        m = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", text)
        if m:
            return m.group(1)
        # 2. 尝试裸 JSON：第一个 { 到配对 }
        start = text.find("{")
        if start < 0:
            return None
        depth = 0
        in_str = False
        esc = False
        for i in range(start, len(text)):
            ch = text[i]
            if esc:
                esc = False
                continue
            if ch == "\\":
                esc = True
                continue
            if ch == '"':
                in_str = not in_str
                continue
            if in_str:
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]
        return None

    @staticmethod
    def _estimate_cost(model_name: str, in_tk: int, out_tk: int) -> float:
        """粗略美元成本估算（运营参考，非账单级）；单位：美元 / 1M tokens"""
        mn = (model_name or "").lower()
        prices = {
            # GPT-4o
            "gpt-4o":            (2.50, 10.00),
            "gpt-4o-mini":       (0.15, 0.60),
            "gpt-4-turbo":       (10.00, 30.00),
            # Claude 3.5 Sonnet
            "claude-3-5-sonnet": (3.00, 15.00),
            "claude-3-sonnet":   (3.00, 15.00),
            # DeepSeek V3（官方价）
            "deepseek-chat":     (0.14, 0.28),
            "deepseek-reasoner": (0.55, 2.19),
            # 通义千问（DashScope 兼容档）
            "qwen-plus":         (0.80, 2.00),
            "qwen-turbo":        (0.30, 0.60),
            # 豆包 / 硅基流动 / OneAPI 默认档（按 0.5 / 1.5 粗略）
            "doubao-pro":        (0.50, 1.50),
            "qwen2.5":           (0.30, 0.60),
            "llama-3.1":         (0.20, 0.40),
        }
        matched_price: Optional[tuple] = None
        for key, pr in prices.items():
            if key in mn:
                matched_price = pr
                break
        if matched_price is None:
            # 默认档（custom / local 不计费）
            return 0.0
        in_price, out_price = matched_price
        return round((in_tk * in_price + out_tk * out_price) / 1_000_000, 6)

    @staticmethod
    def _build_user_prompt(
        *,
        analysis_type: str,
        symbol: Optional[str],
        timeframe: str,
        manual_prompt: str,
        candles_snapshot: str,
        news_snapshot: str,
    ) -> str:
        parts = []
        parts.append(f"## 分析任务类型：{analysis_type or '综合评分'}")
        if symbol:
            parts.append(f"## 交易品种：{symbol.upper()} / USDT")
        if timeframe:
            parts.append(f"## 分析周期：{timeframe}")
        if candles_snapshot:
            parts.append(f"## 实时行情与技术指标快照：\n{candles_snapshot[:4000]}")
        if news_snapshot:
            parts.append(f"## 最近相关新闻与情绪分析：\n{news_snapshot[:4000]}")
        if manual_prompt:
            parts.append(f"## 用户额外关注 / 指令：\n{manual_prompt[:2000]}")
        parts.append("请综合以上实时数据、技术指标和新闻情绪，按 SYSTEM 要求输出严格 JSON。")
        return "\n\n".join(parts)

    # ======= 工具：失败 / Mock =======
    def _fail(
        self, error_code: str, error_msg: str, *,
        third_party_status: Optional[int] = None,
        raw_response: str = "",
        model_name: str = "",
        latency_ms: int = 0,
    ) -> AIResult:
        return AIResult(
            success=False,
            error_code=error_code,
            error_msg=error_msg,
            third_party_status=third_party_status,
            latency_ms=latency_ms,
            raw_response=raw_response,
            model_name=str(model_name or self.cfg.model_name or ""),
            provider=self.cfg.provider_name,
        )

    def _mock_result(self, *, symbol, manual_prompt, latency_ms) -> AIResult:
        # 测试脚本用：保证成功 + 合法 JSON 字段
        return AIResult(
            success=True,
            ai_score=7.2,
            ai_direction="long",
            ai_reason=manual_prompt or f"【Mock 测试模式】{symbol or 'BTC'} 结构偏多：MA 均线多头排列、MACD 金叉、成交量温和放大、情绪偏积极，建议轻仓试多，关键止损设于前低下方。",
            latency_ms=latency_ms,
            tokens_prompt=120, tokens_completion=160, tokens_total=280,
            cost_usd=0.0,
            model_name=self.cfg.model_name or "mock-model",
            provider="mock",
        )
