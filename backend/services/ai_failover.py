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

    # 3. 全部失败
    return {
        "success": False,
        "result": None,
        "source": "failed",
        "used_key_id": None,
        "used_key_name": "",
        "error": pool_result["error"],
    }


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
