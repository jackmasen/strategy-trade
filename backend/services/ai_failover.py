"""
统一 AI 故障转移服务
- 先尝试 ai_configs 单例配置（AI分析页面的主配置）
- 失败后自动轮询 ai_api_keys 接口池（系统设置页面的 Key 池）
- 全系统所有 AI 功能共用此服务，实现自动切换轮询
"""
from datetime import datetime
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session

from backend.core.logging_config import logger
from backend.core.security import decrypt_api_key
from backend.models.ai_config import AIConfig
from backend.models.ai_api_key import AiApiKey
from backend.services.ai_client import AIClient, AIResult
from sqlalchemy import inspect as sa_inspect


def _ensure_ai_keys_table(db: Session):
    insp = sa_inspect(db.bind)
    if "ai_api_keys" not in insp.get_table_names():
        AiApiKey.__table__.create(bind=db.bind, checkfirst=True)
        logger.info("[AI-Failover] 自动创建 ai_api_keys 表")


def _get_available_keys(db: Session) -> list:
    _ensure_ai_keys_table(db)
    return db.query(AiApiKey).filter(
        AiApiKey.status == "active"
    ).order_by(AiApiKey.priority.asc(), AiApiKey.id.asc()).all()


def _try_primary_config(db: Session, analysis_type: str, symbol: str,
                        timeframe: str, manual_prompt: str,
                        candles_snapshot: str = "", news_snapshot: str = "",
                        _mock: bool = False) -> Optional[AIResult]:
    """尝试使用 ai_configs 主配置调用 AI"""
    try:
        from backend.routers.analytics import _ensure_ai_config_table_and_row
        cfg = _ensure_ai_config_table_and_row(db)
        key_plain = decrypt_api_key(cfg.api_key_encrypted or "")
        if not key_plain:
            return None

        client = AIClient(cfg)
        result = client.analyze(
            analysis_type=analysis_type,
            symbol=symbol,
            timeframe=timeframe,
            manual_prompt=manual_prompt,
            candles_snapshot=candles_snapshot,
            news_snapshot=news_snapshot,
            _mock=_mock,
        )
        if result.success:
            cfg.last_verified_at = datetime.now()
            cfg.last_error = ""
            db.commit()
            return result
        else:
            cfg.last_error = (result.error_msg or "")[:500]
            db.commit()
            logger.warning(f"[AI-Failover] 主配置调用失败: {result.error_msg}")
            return None
    except Exception as e:
        db.rollback()
        logger.warning(f"[AI-Failover] 主配置异常: {e}")
        return None


def _try_key_pool(db: Session, analysis_type: str, symbol: str,
                  timeframe: str, manual_prompt: str,
                  candles_snapshot: str = "", news_snapshot: str = "",
                  _mock: bool = False) -> Dict[str, Any]:
    """轮询尝试 ai_api_keys 接口池中的所有 Key"""
    keys = _get_available_keys(db)
    if not keys:
        return {"success": False, "error": "接口池为空，请在系统设置中添加AI接口",
                "used_key_id": None, "used_key_name": "", "result": None}

    last_error = ""
    for k in keys:
        try:
            cfg = AIConfig()
            cfg.provider = AIConfig.name_to_provider(k.provider)
            cfg.model_name = k.model_name
            cfg.api_endpoint = k.api_endpoint or ""
            cfg.api_key_encrypted = k.api_key_encrypted
            cfg.temperature = k.temperature
            cfg.max_tokens = k.max_tokens
            cfg.request_timeout_sec = k.request_timeout_sec
            cfg.max_retries = k.max_retries

            client = AIClient(cfg)
            result = client.analyze(
                analysis_type=analysis_type,
                symbol=symbol,
                timeframe=timeframe,
                manual_prompt=manual_prompt,
                candles_snapshot=candles_snapshot,
                news_snapshot=news_snapshot,
                _mock=_mock,
            )
            if result.success:
                k.fail_count = 0
                k.last_error = ""
                k.last_checked = datetime.now()
                db.commit()
                logger.info(f"[AI-Failover] 接口池 Key '{k.name}' (id={k.id}) 调用成功")
                return {
                    "success": True,
                    "result": result,
                    "used_key_id": k.id,
                    "used_key_name": k.name,
                    "error": "",
                }
            last_error = result.error_msg or "未知错误"
        except Exception as e:
            last_error = str(e)[:200]
            db.rollback()

        k.fail_count = (k.fail_count or 0) + 1
        k.last_error = last_error
        k.last_checked = datetime.now()
        if k.fail_count >= 3:
            k.status = "failed"
        db.commit()
        logger.warning(f"[AI-Failover] 接口池 Key '{k.name}' (id={k.id}) 失败({k.fail_count}次): {last_error}")

    return {"success": False, "error": f"所有接口池Key均失败，最后错误: {last_error}",
            "used_key_id": None, "used_key_name": "", "result": None}


def call_ai_unified(db: Session, analysis_type: str, symbol: str = "",
                    timeframe: str = "4h", manual_prompt: str = "",
                    candles_snapshot: str = "", news_snapshot: str = "",
                    _mock: bool = False) -> Dict[str, Any]:
    """
    统一 AI 调用入口（全系统共用）：
    1. 先尝试 ai_configs 主配置
    2. 失败后自动轮询 ai_api_keys 接口池
    3. 返回 {"success": bool, "result": AIResult, "source": "primary"|"pool", "used_key_id": int|None, ...}
    """
    # 1. 先尝试主配置
    primary_result = _try_primary_config(
        db, analysis_type, symbol, timeframe, manual_prompt,
        candles_snapshot, news_snapshot, _mock
    )
    if primary_result is not None:
        return {
            "success": True,
            "result": primary_result,
            "source": "primary",
            "used_key_id": None,
            "used_key_name": "",
            "error": "",
        }

    # 2. 主配置失败，尝试接口池
    logger.info("[AI-Failover] 主配置不可用，切换到接口池轮询...")
    pool_result = _try_key_pool(
        db, analysis_type, symbol, timeframe, manual_prompt,
        candles_snapshot, news_snapshot, _mock
    )
    if pool_result["success"]:
        return {
            "success": True,
            "result": pool_result["result"],
            "source": "pool",
            "used_key_id": pool_result["used_key_id"],
            "used_key_name": pool_result["used_key_name"],
            "error": "",
        }

    # 3. AI API 全部不可用 → 规则引擎降级分析（基于技术指标）
    logger.info("[AI-Failover] AI API不可用，启用规则引擎降级分析...")
    fallback_result = _rule_based_fallback(
        analysis_type, symbol, timeframe, candles_snapshot, news_snapshot
    )
    if fallback_result:
        return {
            "success": True,
            "result": fallback_result,
            "source": "rule_fallback",
            "used_key_id": None,
            "used_key_name": "",
            "error": "",
        }

    # 4. 规则引擎也无法生成（无数据）
    return {
        "success": False,
        "result": None,
        "source": "failed",
        "used_key_id": None,
        "used_key_name": "",
        "error": pool_result["error"],
    }


def _rule_based_fallback(analysis_type: str, symbol: str, timeframe: str,
                          candles_snapshot: str, news_snapshot: str) -> Optional[AIResult]:
    """无AI API时，基于K线快照进行规则分析，生成基础评分和方向判断"""
    import json as _json
    import re

    try:
        candles = []
        if candles_snapshot:
            text = candles_snapshot.strip()
            if text.startswith("```"):
                text = re.sub(r"^```[a-z]*\n?", "", text)
                text = re.sub(r"\n?```$", "", text).strip()
            try:
                data = _json.loads(text)
                if isinstance(data, list):
                    candles = data
                elif isinstance(data, dict) and "candles" in data:
                    candles = data["candles"]
            except _json.JSONDecodeError:
                lines = [l.strip() for l in text.split("\n") if l.strip()]
                for line in lines:
                    parts = re.split(r"[,\s]+", line)
                    if len(parts) >= 5:
                        try:
                            candles.append({
                                "open": float(parts[1]), "high": float(parts[2]),
                                "low": float(parts[3]), "close": float(parts[4]),
                                "volume": float(parts[5]) if len(parts) > 5 else 0,
                            })
                        except (ValueError, IndexError):
                            continue

        if not candles or len(closes := [c.get("close", c.get("c", 0)) for c in candles]) < 5:
            return None

        closes = [float(c) for c in closes if c and float(c) > 0]
        if len(closes) < 5:
            return None

        highs = [float(c.get("high", c.get("h", 0))) for c in candles]
        lows = [float(c.get("low", c.get("l", 0))) for c in candles]
        volumes = [float(c.get("volume", c.get("v", 0))) for c in candles]

        current_price = closes[-1]
        recent_high = max(highs[-20:]) if len(highs) >= 20 else max(highs)
        recent_low = min(lows[-20:]) if len(lows) >= 20 else min(lows)

        # RSI (14)
        gains, losses = [], []
        for i in range(1, min(15, len(closes))):
            diff = closes[i] - closes[i-1]
            gains.append(max(0, diff))
            losses.append(max(0, -diff))
        avg_gain = sum(gains) / len(gains) if gains else 0
        avg_loss = sum(losses) / len(losses) if losses else 0.001
        rsi = 100 - (100 / (1 + avg_gain / avg_loss)) if avg_loss > 0 else 100

        # MA
        ma5 = sum(closes[-5:]) / len(closes[-5:]) if len(closes) >= 5 else current_price
        ma20 = sum(closes[-20:]) / len(closes[-20:]) if len(closes) >= 20 else sum(closes) / len(closes)

        # 方向判断
        bullish_signals = 0
        bearish_signals = 0
        if rsi < 30:
            bullish_signals += 2
        elif rsi > 70:
            bearish_signals += 2
        if current_price > ma5:
            bullish_signals += 1
        else:
            bearish_signals += 1
        if ma5 > ma20:
            bullish_signals += 1
        else:
            bearish_signals += 1
        if current_price > recent_low * 1.02:
            bullish_signals += 1
        if current_price < recent_high * 0.98:
            bearish_signals += 1

        if bullish_signals > bearish_signals:
            direction = "bullish"
            score = min(8.0, 5.0 + (bullish_signals - bearish_signals) * 0.8)
        elif bearish_signals > bullish_signals:
            direction = "bearish"
            score = min(8.0, 5.0 + (bearish_signals - bullish_signals) * 0.8)
        else:
            direction = "neutral"
            score = 5.0

        confidence = min(0.85, 0.4 + abs(bullish_signals - bearish_signals) * 0.1)

        summary = (
            f"[规则引擎降级分析] {symbol} {timeframe}\n"
            f"当前价格: ${current_price:.2f}\n"
            f"RSI(14): {rsi:.1f} | MA5: ${ma5:.2f} | MA20: ${ma20:.2f}\n"
            f"近20根高/低: ${recent_high:.2f} / ${recent_low:.2f}\n"
            f"方向: {direction} (评分: {score:.1f}, 置信度: {confidence*100:.0f}%)\n"
            f"注: AI API未配置，此分析基于技术指标规则引擎生成"
        )

        return AIResult(
            success=True,
            ai_score=round(score, 1),
            ai_direction=direction,
            confidence=round(confidence, 2),
            summary=summary,
            error_code="",
            error_msg="",
        )
    except Exception as e:
        logger.warning(f"[AI-Failover] 规则引擎降级分析失败: {e}")
        return None


def check_ai_status(db: Session) -> Dict[str, Any]:
    """
    检查 AI 连接状态（供前端绿灯/红灯状态显示）
    返回 {"status": "ok"|"error", "source": "primary"|"pool"|"none", "detail": str}
    """
    # 检查主配置
    try:
        from backend.routers.analytics import _ensure_ai_config_table_and_row
        cfg = _ensure_ai_config_table_and_row(db)
        key_plain = decrypt_api_key(cfg.api_key_encrypted or "")
        if key_plain and not cfg.last_error:
            return {"status": "ok", "source": "primary",
                    "detail": f"{cfg.provider_name} / {cfg.model_name}",
                    "last_verified": cfg.last_verified_at.isoformat(timespec="seconds") if cfg.last_verified_at else None}
        if cfg.last_error:
            # 主配置有错误，检查接口池
            pass
    except Exception as e:
        logger.debug(f"[AI-Status] 检查主配置异常: {e}")

    # 检查接口池
    keys = _get_available_keys(db)
    active_count = len(keys)
    if active_count > 0:
        latest_key = keys[0]
        return {"status": "ok", "source": "pool",
                "detail": f"接口池 {active_count} 个可用 ({latest_key.name})",
                "last_verified": latest_key.last_checked.isoformat(timespec="seconds") if latest_key.last_checked else None}

    return {"status": "error", "source": "none",
            "detail": "无可用AI配置", "last_verified": None}
