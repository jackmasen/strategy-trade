"""
AI多API故障转移路由
- CRUD /settings/ai-keys
- 健康检测 /settings/ai-keys/health-check
- 测试单个 /settings/ai-keys/{id}/test
"""
from datetime import datetime
from typing import Optional, List
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

from backend.db.session import get_db
from backend.core.auth import require_admin, get_current_user
from backend.core.exceptions import NotFoundException, ParameterException, success
from backend.core.logging_config import logger
from backend.core.security import encrypt_api_key, decrypt_api_key, mask_api_key
from backend.models.user import User
from backend.models.ai_api_key import AiApiKey
from backend.models.ai_config import AIConfig
from backend.services.ai_client import AIClient
import threading
import time

router = APIRouter(prefix="/settings/ai-keys", tags=["AI多API故障转移"])


# ============= Pydantic =============

class AiKeyCreate(BaseModel):
    model_config = {"protected_namespaces": ()}
    name: str = Field(..., min_length=1, max_length=64, description="名称")
    provider: str = Field("custom", description="供应商")
    model_name: str = Field("gpt-4o", description="模型名")
    api_endpoint: str = Field("", description="API地址")
    api_key_plain: str = Field("", description="API Key明文")
    priority: int = Field(10, ge=1, le=100, description="优先级")
    temperature: int = Field(3, ge=0, le=10)
    max_tokens: int = Field(800, ge=128, le=8192)
    request_timeout_sec: int = Field(15, ge=5, le=60)
    max_retries: int = Field(2, ge=0, le=5)


class AiKeyUpdate(BaseModel):
    model_config = {"protected_namespaces": ()}
    name: str = ""
    provider: str = ""
    model_name: str = ""
    api_endpoint: str = ""
    api_key_plain: str = ""
    priority: int | None = None
    status: str = ""
    temperature: int | None = None
    max_tokens: int | None = None
    request_timeout_sec: int | None = None
    max_retries: int | None = None


# ============= 辅助 =============

def _ensure_table(db: Session):
    from sqlalchemy import inspect as sa_inspect
    from backend.db.session import engine_sync
    insp = sa_inspect(engine_sync)
    if "ai_api_keys" not in insp.get_table_names():
        AiApiKey.__table__.create(bind=engine_sync, checkfirst=True)
        logger.info("[AI-Keys] 自动创建 ai_api_keys 表")


def _key_to_dict(k: AiApiKey) -> dict:
    return {
        "id": k.id,
        "name": k.name,
        "provider": k.provider,
        "model_name": k.model_name,
        "api_endpoint": k.api_endpoint or "",
        "api_key_masked": mask_api_key(decrypt_api_key(k.api_key_encrypted or "")) if k.api_key_encrypted else "",
        "has_key": bool(k.api_key_encrypted),
        "priority": k.priority,
        "status": k.status,
        "fail_count": k.fail_count,
        "last_checked": k.last_checked.isoformat() if k.last_checked else "",
        "last_error": k.last_error or "",
        "temperature": k.temperature,
        "max_tokens": k.max_tokens,
        "request_timeout_sec": k.request_timeout_sec,
        "max_retries": k.max_retries,
    }


def _get_available_keys(db: Session) -> list:
    """获取按优先级排序的可用API Key列表"""
    _ensure_table(db)
    return db.query(AiApiKey).filter(
        AiApiKey.status == "active"
    ).order_by(AiApiKey.priority.asc(), AiApiKey.id.asc()).all()


def _try_ai_key(k: AiApiKey, prompt: str = "请回复'连接成功'") -> tuple:
    """测试单个API Key连通性：直接发 HTTP 请求，不经过 analyze() 的 JSON 解析"""
    try:
        from backend.core.security import decrypt_api_key
        import httpx

        api_key = decrypt_api_key(k.api_key_encrypted) if k.api_key_encrypted else ""
        if not api_key:
            return (False, 0, "API Key 未配置")

        endpoint = (k.api_endpoint or "").rstrip("/")
        if not endpoint:
            return (False, 0, "API Endpoint 未配置")

        url = f"{endpoint}/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": k.model_name or "gpt-4o-mini",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 16,
            "temperature": 0,
        }

        timeout = min(k.request_timeout_sec or 15, 15)
        start = time.time()
        resp = httpx.post(url, json=payload, headers=headers, timeout=timeout)
        latency = int((time.time() - start) * 1000)

        if resp.status_code == 200:
            return (True, latency, "")
        else:
            body = resp.text[:200]
            return (False, latency, f"HTTP {resp.status_code}: {body}")
    except Exception as e:
        return (False, 0, str(e)[:200])


# ============= 路由 =============

@router.get("")
def list_ai_keys(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取所有AI API Key列表"""
    _ensure_table(db)
    keys = db.query(AiApiKey).order_by(AiApiKey.priority.asc(), AiApiKey.id.asc()).all()
    return success({"items": [_key_to_dict(k) for k in keys], "count": len(keys)})


@router.post("")
def create_ai_key(
    req: AiKeyCreate,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """添加AI API Key"""
    _ensure_table(db)
    if not req.api_key_plain:
        raise ParameterException("请输入API Key")

    k = AiApiKey(
        name=req.name,
        provider=req.provider,
        model_name=req.model_name,
        api_endpoint=req.api_endpoint,
        api_key_encrypted=encrypt_api_key(req.api_key_plain),
        priority=req.priority,
        status="active",
        temperature=req.temperature,
        max_tokens=req.max_tokens,
        request_timeout_sec=req.request_timeout_sec,
        max_retries=req.max_retries,
    )
    db.add(k)
    db.commit()
    db.refresh(k)
    logger.info(f"[AI-Keys] 管理员 {user.username} 添加了API Key: {k.name} (id={k.id})")
    return success({"id": k.id}, message="API Key添加成功")


@router.put("/{kid}")
def update_ai_key(
    kid: int,
    req: AiKeyUpdate,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """更新AI API Key"""
    _ensure_table(db)
    k = db.query(AiApiKey).filter(AiApiKey.id == kid).first()
    if not k:
        raise NotFoundException("API Key不存在")

    if req.name:
        k.name = req.name
    if req.provider:
        k.provider = req.provider
    if req.model_name:
        k.model_name = req.model_name
    if req.api_endpoint is not None:
        k.api_endpoint = req.api_endpoint
    if req.api_key_plain and not req.api_key_plain.startswith("****"):
        k.api_key_encrypted = encrypt_api_key(req.api_key_plain)
    if req.priority is not None:
        k.priority = req.priority
    if req.status in ("active", "disabled"):
        k.status = req.status
        if req.status == "active":
            k.fail_count = 0
            k.last_error = ""
    if req.temperature is not None:
        k.temperature = req.temperature
    if req.max_tokens is not None:
        k.max_tokens = req.max_tokens
    if req.request_timeout_sec is not None:
        k.request_timeout_sec = req.request_timeout_sec
    if req.max_retries is not None:
        k.max_retries = req.max_retries

    db.commit()
    return success(message="更新成功")


@router.delete("/{kid}")
def delete_ai_key(
    kid: int,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """删除AI API Key"""
    _ensure_table(db)
    k = db.query(AiApiKey).filter(AiApiKey.id == kid).first()
    if not k:
        raise NotFoundException("API Key不存在")
    db.delete(k)
    db.commit()
    logger.info(f"[AI-Keys] 管理员 {user.username} 删除了API Key: {k.name} (id={kid})")
    return success(message="删除成功")


@router.post("/{kid}/test")
def test_single_key(
    kid: int,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """测试单个API Key连通性"""
    _ensure_table(db)
    k = db.query(AiApiKey).filter(AiApiKey.id == kid).first()
    if not k:
        raise NotFoundException("API Key不存在")

    ok, latency, err = _try_ai_key(k)
    k.last_checked = datetime.now()
    if ok:
        k.status = "active"
        k.fail_count = 0
        k.last_error = ""
    else:
        k.fail_count = (k.fail_count or 0) + 1
        k.last_error = err
        if k.fail_count >= 3:
            k.status = "failed"
    db.commit()

    if ok:
        return success({"success": True, "latency_ms": latency}, message=f"连接成功！延迟 {latency}ms")
    else:
        return success({"success": False, "latency_ms": latency, "error": err}, message=f"连接失败: {err}")


@router.post("/health-check")
def health_check_all(
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """批量健康检测所有API Key"""
    _ensure_table(db)
    keys = db.query(AiApiKey).filter(AiApiKey.status != "disabled").all()
    results = []
    for k in keys:
        ok, latency, err = _try_ai_key(k)
        k.last_checked = datetime.now()
        if ok:
            k.status = "active"
            k.fail_count = 0
            k.last_error = ""
        else:
            k.fail_count = (k.fail_count or 0) + 1
            k.last_error = err
            if k.fail_count >= 3:
                k.status = "failed"
        results.append({
            "id": k.id,
            "name": k.name,
            "success": ok,
            "latency_ms": latency,
            "error": err,
            "status": k.status,
        })
    db.commit()
    active_count = sum(1 for r in results if r["success"])
    return success({
        "total": len(results),
        "active": active_count,
        "failed": len(results) - active_count,
        "results": results,
    }, message=f"检测完成: {active_count}/{len(results)} 可用")


# ============= 故障转移调用函数（供其他模块调用） =============

def call_ai_with_failover(db: Session, analysis_type: str, symbol: str, timeframe: str,
                          manual_prompt: str, candles_snapshot: str = "",
                          news_snapshot: str = "") -> dict:
    """
    按优先级尝试所有API Key，第一个成功就返回，失败的自动切换
    返回 {"success": bool, "result": ..., "used_key_id": int, "error": str}
    """
    keys = _get_available_keys(db)
    if not keys:
        return {"success": False, "error": "没有可用的AI API Key，请在系统设置中配置", "used_key_id": None}

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
            )
            if result.success:
                # 成功，重置失败计数
                k.fail_count = 0
                k.last_error = ""
                k.last_checked = datetime.now()
                db.commit()
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

        # 失败，记录
        k.fail_count = (k.fail_count or 0) + 1
        k.last_error = last_error
        k.last_checked = datetime.now()
        if k.fail_count >= 3:
            k.status = "failed"
        db.commit()
        logger.warning(f"[AI-Failover] Key '{k.name}' (id={k.id}) 失败({k.fail_count}次): {last_error}")

    return {"success": False, "error": f"所有API Key均失败，最后错误: {last_error}", "used_key_id": None}
