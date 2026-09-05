"""
系统管理路由：健康检测、缓存清理、备份管理、版本更新
"""
import os
from pathlib import Path
from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

from backend.db.session import get_db
from backend.core.auth import require_admin
from backend.core.exceptions import success, BizException
from backend.models.user import User
from backend.services.system_manager import (
    get_system_info,
    run_health_check,
    get_cleanable_items,
    clean_cache,
    create_backup,
    list_backups,
    restore_backup,
    delete_backup,
    apply_update_from_upload,
    list_updates,
    rollback_update,
    check_github_latest,
    apply_github_update,
)

router = APIRouter(prefix="/system", tags=["系统管理"])

BASE_DIR = Path(__file__).resolve().parent.parent.parent
UPLOAD_DIR = BASE_DIR / "uploads" / "updates"


# ==================== 系统信息 ====================

@router.get("/info")
def system_info(
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """获取系统基本信息"""
    info = get_system_info(db)
    return success(info)


# ==================== 健康检测 ====================

@router.post("/health-check")
def health_check(
    auto_fix: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """执行系统健康检测"""
    result = run_health_check(db, auto_fix=auto_fix)
    return success(result)


# ==================== 缓存清理 ====================

@router.get("/cache/items")
def cache_items(
    user: User = Depends(require_admin),
):
    """获取可清理的缓存项"""
    items = get_cleanable_items()
    return success(items)


class CleanCacheReq(BaseModel):
    keys: list[str] | None = Field(None, description="要清理的 key 列表，为空则清理全部")


@router.post("/cache/clean")
def cache_clean(
    req: CleanCacheReq,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """清理缓存"""
    result = clean_cache(db, selected_keys=req.keys)
    return success(result)


# ==================== 备份管理 ====================

class CreateBackupReq(BaseModel):
    include_db: bool = True
    include_config: bool = True
    description: str = ""


@router.post("/backups")
def create_new_backup(
    req: CreateBackupReq,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """创建系统备份"""
    result = create_backup(
        db,
        backup_type="manual",
        include_db=req.include_db,
        include_config=req.include_config,
        description=req.description,
    )
    return success(result, message="备份创建成功")


@router.get("/backups")
def get_backups(
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """备份列表"""
    result = list_backups(db, page=page, page_size=page_size)
    return success(result)


@router.post("/backups/{bid}/restore")
def restore(
    bid: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """恢复备份（回滚）"""
    try:
        result = restore_backup(db, backup_id=bid)
        return success(result, message="恢复成功")
    except ValueError as e:
        raise BizException(str(e), code=4004)
    except RuntimeError as e:
        raise BizException(str(e), code=5003)


@router.delete("/backups/{bid}")
def delete_backup_route(
    bid: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """删除备份"""
    try:
        delete_backup(db, backup_id=bid)
        return success({"id": bid}, message="删除成功")
    except ValueError as e:
        raise BizException(str(e), code=4004)


# ==================== 版本更新 ====================

@router.post("/updates/upload")
async def upload_update(
    file: UploadFile = File(...),
    version: str = Form(""),
    changelog: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """上传更新包并应用"""
    if not file.filename or not file.filename.endswith('.zip'):
        raise BizException("仅支持 .zip 更新包", code=4000)

    # 安全文件名：仅保留字母/数字/下划线/连字符/点，防止路径穿越
    import re
    safe_name = re.sub(r'[^a-zA-Z0-9_\-.]', '_', file.filename)
    # 防止双重扩展和隐藏文件
    if safe_name.startswith('.'):
        safe_name = '_' + safe_name
    # 限制文件名长度
    safe_name = safe_name[:128]

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    file_path = (UPLOAD_DIR / safe_name).resolve()
    # 确保解析后的路径仍在 UPLOAD_DIR 内
    if not str(file_path).startswith(str(UPLOAD_DIR.resolve())):
        raise BizException("非法文件名", code=4000)

    # 先检查 Content-Length（避免大文件读完才报错）
    content_length = 0
    # 流式读取，避免一次性加载大文件到内存
    content = bytearray()
    chunk_size = 1024 * 1024  # 1MB chunks
    max_size = 200 * 1024 * 1024  # 200MB 限制
    while True:
        chunk = await file.read(chunk_size)
        if not chunk:
            break
        content.extend(chunk)
        if len(content) > max_size:
            raise BizException("更新包过大，最大 200MB", code=4000)

    with open(file_path, "wb") as f:
        f.write(content)

    try:
        result = apply_update_from_upload(
            db,
            file_path=str(file_path),
            version=version,
            changelog=changelog,
        )
        return success(result, message="更新完成")
    except (ValueError, RuntimeError) as e:
        # 清理上传文件
        if file_path.exists():
            file_path.unlink(missing_ok=True)
        raise BizException(str(e), code=5002)


@router.get("/updates")
def get_updates(
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """更新记录"""
    result = list_updates(db, page=page, page_size=page_size)
    return success(result)


@router.post("/updates/{uid}/rollback")
def rollback(
    uid: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """回滚更新"""
    try:
        result = rollback_update(db, update_id=uid)
        return success(result, message="回滚成功")
    except ValueError as e:
        raise BizException(str(e), code=4004)
    except RuntimeError as e:
        raise BizException(str(e), code=5003)


@router.get("/updates/check-latest")
def check_latest(
    user: User = Depends(require_admin),
):
    """检查 GitHub 最新版本"""
    try:
        result = check_github_latest()
        return success(result)
    except ValueError as e:
        raise BizException(str(e), code=4004)
    except Exception as e:
        raise BizException(f"检查更新失败: {e}", code=5002)


@router.post("/updates/github")
def github_update(
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """从 GitHub 下载并应用最新版本更新"""
    try:
        # 1) 先检查最新版本
        info = check_github_latest()
        zip_url = info.get("zip_url")
        tag_name = info.get("tag_name", "")
        changelog = info.get("body", "")

        if not zip_url:
            raise ValueError("未找到可下载的更新包")

        # 2) 下载并应用
        result = apply_github_update(
            db, zip_url=zip_url, tag_name=tag_name, changelog=changelog
        )
        return success(result, message=f"GitHub 更新完成: {tag_name}")
    except ValueError as e:
        raise BizException(str(e), code=4004)
    except RuntimeError as e:
        raise BizException(str(e), code=5002)
    except Exception as e:
        raise BizException(f"GitHub 更新失败: {e}", code=5002)
