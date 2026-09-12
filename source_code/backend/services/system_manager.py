"""
系统管理服务：健康检测、自动修复、缓存清理、备份/恢复、版本更新
"""
import os
import shutil
import json
import zipfile
import logging
import platform
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from backend.models.system_admin import SystemHealthReport, SystemBackupRecord, SystemUpdateRecord

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent.parent
BACKUP_DIR = BASE_DIR / "backups"
UPLOAD_DIR = BASE_DIR / "uploads"


def _get_db_file_path() -> Optional[Path]:
    """
    从配置动态读取数据库文件路径（仅 SQLite 返回 Path，MySQL 返回 None）。
    解析 SQLALCHEMY_DATABASE_URI，兼容 sqlite:///相对路径 / sqlite:////绝对路径。
    """
    try:
        from backend.config import get_settings
        uri = get_settings().SQLALCHEMY_DATABASE_URI
        if not uri.startswith("sqlite"):
            return None
        # sqlite:///./data/app.db → data/app.db
        # sqlite:////www/.../app.db → /www/.../app.db
        path_str = uri.replace("sqlite:///", "", 1)
        if path_str.startswith("/"):
            return Path(path_str)
        return BASE_DIR / path_str
    except Exception:
        return None

# 可清理的缓存项
CLEANABLE_ITEMS = [
    {"key": "pycache", "path": "__pycache__", "desc": "Python 字节码缓存", "recursive": True},
    {"key": "pytest_cache", "path": ".pytest_cache", "desc": "pytest 测试缓存", "recursive": True},
    {"key": "vite_cache", "path": "frontend/node_modules/.vite", "desc": "Vite 构建缓存", "recursive": True},
    {"key": "frontend_dist", "path": "frontend/dist", "desc": "前端构建产物", "recursive": True},
    {"key": "logs", "path": "logs", "desc": "日志文件 (.log)", "recursive": True, "pattern": "*.log"},
]


# ============================================================
# 1. 系统信息
# ============================================================

def get_system_info(db: Session) -> Dict:
    """获取系统基本信息"""
    db_file = _get_db_file_path()
    db_size = db_file.stat().st_size if db_file and db_file.exists() else 0

    backup_count = 0
    if BACKUP_DIR.exists():
        backup_count = len(list(BACKUP_DIR.glob("*.zip")))

    # 交易统计
    from backend.models.trade import TradePosition, TradeOrder
    pos_count = db.query(TradePosition).filter(TradePosition.status == 1).count()
    order_count = db.query(TradeOrder).count()

    # 用户统计
    from backend.models.user import User
    user_count = db.query(User).count()

    return {
        "version": _get_current_version(),
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
        "project_root": str(BASE_DIR),
        "database_size_bytes": db_size,
        "database_size_mb": round(db_size / 1024 / 1024, 2),
        "backup_count": backup_count,
        "user_count": user_count,
        "open_position_count": pos_count,
        "total_order_count": order_count,
        "disk_free_bytes": 0,
        "disk_total_bytes": 0,
    }


# ============================================================
# 2. 健康检测 + 自动修复
# ============================================================

def run_health_check(db: Session, auto_fix: bool = False) -> Dict:
    """执行系统健康检测"""
    checks = []
    fixed = []
    overall = "healthy"

    def set_status(s):
        nonlocal overall
        order = {"healthy": 0, "warning": 1, "critical": 2}
        if order.get(s, 0) > order.get(overall, 0):
            overall = s

    # 1) 数据库连接
    try:
        from sqlalchemy import text
        db.execute(text("SELECT 1"))
        checks.append({"key": "db_connection", "name": "数据库连接", "status": "healthy", "detail": "连接正常"})
    except Exception as e:
        checks.append({"key": "db_connection", "name": "数据库连接", "status": "critical", "detail": str(e)})
        set_status("critical")

    # 2) 磁盘空间
    try:
        usage = shutil.disk_usage(str(BASE_DIR))
        free_gb = usage.free / (1024 ** 3)
        pct = usage.free / usage.total * 100
        status = "healthy" if pct > 15 else ("warning" if pct > 5 else "critical")
        checks.append({
            "key": "disk_space", "name": "磁盘空间",
            "status": status,
            "detail": f"剩余 {free_gb:.1f} GB ({pct:.1f}%)"
        })
        set_status(status)
    except Exception as e:
        checks.append({"key": "disk_space", "name": "磁盘空间", "status": "warning", "detail": str(e)})
        set_status("warning")

    # 3) 必要目录检测 + 自动修复
    required_dirs = [
        ("backups", "备份目录"),
        ("logs", "日志目录"),
        ("data", "数据目录"),
        ("uploads", "上传目录"),
    ]
    for dir_name, display in required_dirs:
        d = BASE_DIR / dir_name
        if d.exists():
            checks.append({"key": f"dir_{dir_name}", "name": display, "status": "healthy", "detail": f"{dir_name}/ 存在"})
        else:
            if auto_fix:
                try:
                    d.mkdir(parents=True, exist_ok=True)
                    checks.append({
                        "key": f"dir_{dir_name}", "name": display,
                        "status": "healthy", "detail": f"已自动创建 {dir_name}/"
                    })
                    fixed.append({"key": f"dir_{dir_name}", "action": "create_dir", "name": display})
                except Exception as e:
                    checks.append({"key": f"dir_{dir_name}", "name": display, "status": "critical", "detail": str(e)})
                    set_status("critical")
            else:
                checks.append({
                    "key": f"dir_{dir_name}", "name": display,
                    "status": "warning", "detail": f"{dir_name}/ 不存在"
                })
                set_status("warning")

    # 4) 日志文件大小
    log_dir = BASE_DIR / "logs"
    if log_dir.exists():
        log_files = list(log_dir.glob("*.log"))
        total_size = sum(f.stat().st_size for f in log_files if f.is_file())
        size_mb = total_size / 1024 / 1024
        status = "healthy" if size_mb < 100 else ("warning" if size_mb < 500 else "critical")
        checks.append({
            "key": "log_size", "name": "日志文件",
            "status": status,
            "detail": f"{len(log_files)} 个文件，共 {size_mb:.1f} MB"
        })
        set_status(status)

    # 5) 数据库大小
    db_file = _get_db_file_path()
    if db_file and db_file.exists():
        size_mb = db_file.stat().st_size / 1024 / 1024
        status = "healthy" if size_mb < 500 else ("warning" if size_mb < 2000 else "critical")
        checks.append({
            "key": "db_size", "name": "数据库大小",
            "status": status,
            "detail": f"SQLite 数据库 {size_mb:.1f} MB"
        })
        set_status(status)

    # 6) 备份目录
    if BACKUP_DIR.exists():
        backups = list(BACKUP_DIR.glob("*.zip"))
        total_size = sum(f.stat().st_size for f in backups)
        checks.append({
            "key": "backups", "name": "备份文件",
            "status": "healthy",
            "detail": f"{len(backups)} 个备份，共 {total_size/1024/1024:.1f} MB"
        })

    # 保存报告
    report = SystemHealthReport(
        overall_status=overall,
        check_details=json.dumps(checks, ensure_ascii=False),
        fixed_items=json.dumps(fixed, ensure_ascii=False),
    )
    db.add(report)
    db.commit()

    return {
        "overall_status": overall,
        "checks": checks,
        "fixed": fixed,
        "report_id": report.id,
        "checked_at": report.created_at.isoformat(),
    }


# ============================================================
# 3. 缓存/垃圾清理
# ============================================================

def get_cleanable_items() -> Dict:
    """获取可清理项列表"""
    items = []
    total_size = 0
    for item in CLEANABLE_ITEMS:
        path = BASE_DIR / item["path"]
        size = 0
        exists = path.exists()
        if exists and item.get("recursive"):
            size = _calc_dir_size(path, item.get("pattern"))
        elif exists and path.is_file():
            size = path.stat().st_size
        total_size += size
        items.append({
            "key": item["key"],
            "path": item["path"],
            "description": item["desc"],
            "size_bytes": size,
            "size_mb": round(size / 1024 / 1024, 2),
            "exists": exists,
        })
    return {
        "items": items,
        "total_size_bytes": total_size,
        "total_size_mb": round(total_size / 1024 / 1024, 2),
    }


def clean_cache(db: Session, selected_keys: Optional[List[str]] = None) -> Dict:
    """清理缓存"""
    info = get_cleanable_items()
    freed = 0
    cleared = []

    for item in info["items"]:
        if not item["exists"]:
            continue
        if selected_keys and item["key"] not in selected_keys:
            continue
        path = BASE_DIR / item["path"]
        size = item["size_bytes"]
        try:
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            elif path.is_file():
                path.unlink(missing_ok=True)
            freed += size
            cleared.append({"key": item["key"], "path": item["path"], "freed_bytes": size})
            logger.info(f"[System] 清理: {item['path']} ({size/1024/1024:.2f} MB)")
        except Exception as e:
            logger.error(f"[System] 清理失败 {item['path']}: {e}")

    # 保存健康报告
    report = SystemHealthReport(
        overall_status="healthy",
        check_details=json.dumps([{"name": "缓存清理", "status": "healthy", "detail": f"清理 {len(cleared)} 项"}], ensure_ascii=False),
        fixed_items=json.dumps(cleared, ensure_ascii=False),
        freed_space_bytes=freed,
    )
    db.add(report)
    db.commit()

    return {
        "freed_bytes": freed,
        "freed_mb": round(freed / 1024 / 1024, 2),
        "cleared_count": len(cleared),
        "cleared_items": cleared,
    }


# ============================================================
# 4. 系统备份
# ============================================================

def create_backup(db: Session, backup_type: str = "manual", include_db: bool = True,
                  include_config: bool = True, description: str = "") -> Dict:
    """创建系统备份（zip 压缩）"""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_name = f"backup_{backup_type}_{timestamp}.zip"
    file_path = BACKUP_DIR / file_name

    record = SystemBackupRecord(
        backup_type=backup_type,
        file_name=file_name,
        includes_db=1 if include_db else 0,
        includes_config=1 if include_config else 0,
        description=description,
        status=1,
    )
    db.add(record)
    db.flush()  # Get ID without committing

    start = datetime.now()
    try:
        with zipfile.ZipFile(file_path, "w", zipfile.ZIP_DEFLATED) as zf:
            # 数据库
            if include_db:
                db_file = _get_db_file_path()
                if db_file and db_file.exists():
                    zf.write(db_file, "data/app.db")
                elif not db_file:
                    logger.warning("MySQL数据库无法通过文件复制备份，请使用mysqldump手动备份")

            # 配置文件
            if include_config:
                env_file = BASE_DIR / ".env"
                if env_file.exists():
                    zf.write(env_file, ".env")

            # 上传文件
            if UPLOAD_DIR.exists():
                for f in UPLOAD_DIR.rglob("*"):
                    if f.is_file():
                        arcname = f"uploads/{f.relative_to(UPLOAD_DIR)}"
                        zf.write(f, arcname)

        file_size = file_path.stat().st_size
        record.file_size = file_size
        record.status = 2
        record.finished_at = datetime.now()
        db.commit()

        duration = (record.finished_at - start).total_seconds()
        logger.info(f"[System] 备份完成: {file_name} ({file_size/1024/1024:.2f} MB, {duration:.1f}s)")

        return {
            "id": record.id,
            "file_name": file_name,
            "size_bytes": file_size,
            "size_mb": round(file_size / 1024 / 1024, 2),
            "duration_sec": round(duration, 1),
        }
    except Exception as e:
        db.rollback()
        record = db.query(SystemBackupRecord).filter(SystemBackupRecord.id == record.id).first()
        if record:
            record.status = 3
            record.error_msg = str(e)[:500]
            record.finished_at = datetime.now()
            db.commit()
        logger.error(f"[System] 备份失败: {e}")
        raise RuntimeError(f"备份失败: {e}")


def list_backups(db: Session, page: int = 1, page_size: int = 20) -> Dict:
    """备份列表"""
    query = db.query(SystemBackupRecord).order_by(SystemBackupRecord.created_at.desc())
    total = query.count()
    items = query.offset((page - 1) * page_size).limit(page_size).all()
    return {
        "items": [{
            "id": r.id,
            "backup_type": r.backup_type,
            "file_name": r.file_name,
            "size_bytes": r.file_size or 0,
            "size_mb": round((r.file_size or 0) / 1024 / 1024, 2),
            "includes_db": bool(r.includes_db),
            "includes_config": bool(r.includes_config),
            "status": r.status,
            "description": r.description or "",
            "error_msg": r.error_msg or "",
            "created_at": r.created_at.isoformat() if r.created_at else "",
            "finished_at": r.finished_at.isoformat() if r.finished_at else "",
        } for r in items],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def restore_backup(db: Session, backup_id: int) -> Dict:
    """从备份恢复（回滚）"""
    record = db.query(SystemBackupRecord).filter(SystemBackupRecord.id == backup_id).first()
    if not record:
        raise ValueError("备份记录不存在")
    if record.status != 2:
        raise ValueError("备份未成功，无法恢复")

    file_path = BACKUP_DIR / record.file_name
    if not file_path.exists():
        raise ValueError("备份文件不存在")

    start = datetime.now()
    temp_dir = BASE_DIR / f".restore_{backup_id}_{int(start.timestamp())}"

    try:
        temp_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(file_path, "r") as zf:
            zf.extractall(temp_dir)

        restored = []

        # 恢复数据库
        db_src = temp_dir / "data" / "app.db"
        if db_src.exists() and record.includes_db:
            db_dst = _get_db_file_path() or (BASE_DIR / "data" / "app.db")
            db_dst.parent.mkdir(parents=True, exist_ok=True)
            if db_dst.exists():
                db_dst.rename(BASE_DIR / "data" / f"app.db.bak_{int(start.timestamp())}")
            shutil.copy2(db_src, db_dst)
            restored.append("database")

        # 恢复配置
        env_src = temp_dir / ".env"
        if env_src.exists() and record.includes_config:
            env_dst = BASE_DIR / ".env"
            if env_dst.exists():
                env_dst.rename(BASE_DIR / f".env.bak_{int(start.timestamp())}")
            shutil.copy2(env_src, env_dst)
            restored.append("config")

        # 恢复上传文件
        upload_src = temp_dir / "uploads"
        if upload_src.exists():
            upload_dst = BASE_DIR / "uploads"
            if upload_dst.exists():
                upload_dst.rename(BASE_DIR / f"uploads.bak_{int(start.timestamp())}")
            shutil.copytree(upload_src, upload_dst)
            restored.append("uploads")

        shutil.rmtree(temp_dir, ignore_errors=True)

        duration = (datetime.now() - start).total_seconds()
        logger.info(f"[System] 备份恢复完成: {record.file_name} ({duration:.1f}s)")

        return {
            "success": True,
            "restored_items": restored,
            "duration_sec": round(duration, 1),
            "message": "恢复完成，重启服务后生效",
            "needs_restart": True,
        }
    except Exception as e:
        shutil.rmtree(temp_dir, ignore_errors=True)
        logger.error(f"[System] 备份恢复失败: {e}")
        raise RuntimeError(f"恢复失败: {e}")


def delete_backup(db: Session, backup_id: int) -> bool:
    """删除备份"""
    record = db.query(SystemBackupRecord).filter(SystemBackupRecord.id == backup_id).first()
    if not record:
        raise ValueError("备份记录不存在")

    file_path = BACKUP_DIR / record.file_name
    if file_path.exists():
        try:
            file_path.unlink()
        except Exception as e:
            logger.error(f"[System] 删除备份文件失败: {e}")

    db.delete(record)
    db.commit()
    return True


# ============================================================
# 5. 系统版本更新
# ============================================================

def apply_update_from_upload(db: Session, file_path: str, version: str = "",
                             changelog: str = "") -> Dict:
    """应用上传的更新包"""
    fp = Path(file_path)
    if not fp.exists():
        raise ValueError("更新文件不存在")

    file_size = fp.stat().st_size
    record = SystemUpdateRecord(
        version=version or "custom",
        update_type="upload",
        source=fp.name,
        changelog=changelog,
        file_size=file_size,
        status=1,
    )
    db.add(record)
    db.commit()

    start = datetime.now()
    try:
        # 1) 先自动备份
        bk = create_backup(db, backup_type="pre_update",
                           description=f"更新前自动备份 → v{version or 'custom'}")
        record.backup_id = bk["id"]

        # 2) 解压（防 Zip Slip：校验每个条目解析后仍在 temp_dir 内）
        temp_dir = BASE_DIR / f".update_{record.id}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        temp_dir_resolved = temp_dir.resolve()
        with zipfile.ZipFile(fp, "r") as zf:
            for member in zf.infolist():
                # 跳过目录条目
                if member.is_dir():
                    continue
                # 解析目标路径并确保不逃逸 temp_dir
                target = (temp_dir / member.filename).resolve()
                if not str(target).startswith(str(temp_dir_resolved)):
                    logger.warning(f"[System] Zip Slip 拦截: {member.filename}")
                    continue
                # 提取单个文件
                zf.extract(member, temp_dir)

        # 2.1) GitHub zip 可能有多一层根目录（如 strategy-trade-v1.2.1/），自动提升一层
        has_direct_backend = (temp_dir / "backend").exists()
        has_direct_frontend = (temp_dir / "frontend").exists() or (temp_dir / "frontend_dist").exists()
        if not has_direct_backend and not has_direct_frontend:
            children = [d for d in temp_dir.iterdir() if d.is_dir()]
            if len(children) == 1:
                root_child = children[0]
                for item in root_child.iterdir():
                    shutil.move(str(item), str(temp_dir / item.name))
                shutil.rmtree(root_child, ignore_errors=True)

        # 3) 校验结构
        has_backend = (temp_dir / "backend").exists()
        has_frontend = (temp_dir / "frontend").exists() or (temp_dir / "frontend_dist").exists()
        if not has_backend and not has_frontend:
            raise ValueError("更新包无效：未找到 backend 或 frontend 目录")

        # 4) 应用后端更新（合并覆盖）
        if has_backend:
            _merge_dir(temp_dir / "backend", BASE_DIR / "backend")

        # 5) 应用前端更新
        if has_frontend:
            if (temp_dir / "frontend_dist").exists():
                src_dist = temp_dir / "frontend_dist"
            else:
                src_dist = temp_dir / "frontend" / "dist"
            if src_dist.exists():
                dst_dist = BASE_DIR / "frontend" / "dist"
                if dst_dist.exists():
                    shutil.rmtree(dst_dist)
                shutil.copytree(src_dist, dst_dist)

        # 6) 清理
        shutil.rmtree(temp_dir, ignore_errors=True)
        # 删除上传的更新包
        fp.unlink(missing_ok=True)

        duration = int((datetime.now() - start).total_seconds())
        record.status = 2
        record.duration_sec = duration
        record.finished_at = datetime.now()
        db.commit()

        logger.info(f"[System] 更新完成: {fp.name} ({duration}s)")

        return {
            "id": record.id,
            "version": version,
            "backup_id": bk["id"],
            "has_backend": has_backend,
            "has_frontend": has_frontend,
            "duration_sec": duration,
            "message": "更新完成，服务将自动重启",
            "needs_restart": True,
        }
    except Exception as e:
        record.status = 3
        record.error_msg = str(e)
        record.finished_at = datetime.now()
        db.commit()
        logger.error(f"[System] 更新失败: {e}")
        raise RuntimeError(f"更新失败: {e}")


def list_updates(db: Session, page: int = 1, page_size: int = 20) -> Dict:
    """更新记录列表"""
    query = db.query(SystemUpdateRecord).order_by(SystemUpdateRecord.created_at.desc())
    total = query.count()
    items = query.offset((page - 1) * page_size).limit(page_size).all()
    return {
        "items": [{
            "id": r.id,
            "version": r.version,
            "update_type": r.update_type,
            "source": r.source,
            "status": r.status,
            "backup_id": r.backup_id,
            "changelog": r.changelog or "",
            "error_msg": r.error_msg or "",
            "file_size": r.file_size or 0,
            "duration_sec": r.duration_sec or 0,
            "created_at": r.created_at.isoformat() if r.created_at else "",
            "finished_at": r.finished_at.isoformat() if r.finished_at else "",
        } for r in items],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def rollback_update(db: Session, update_id: int) -> Dict:
    """回滚到更新前的备份"""
    record = db.query(SystemUpdateRecord).filter(SystemUpdateRecord.id == update_id).first()
    if not record:
        raise ValueError("更新记录不存在")
    if not record.backup_id:
        raise ValueError("无关联备份，无法回滚")

    result = restore_backup(db, record.backup_id)
    record.status = 4  # 已回滚
    db.commit()

    return result


# ============================================================
# 6. GitHub 在线更新
# ============================================================

GITHUB_API = "https://api.github.com"


def check_github_latest() -> Dict:
    """检查 GitHub 最新 Release"""
    import httpx
    from backend.config import get_settings

    settings = get_settings()
    repo = settings.GITHUB_REPO.strip()
    if not repo:
        raise ValueError("未配置 GitHub 仓库地址（GITHUB_REPO），请在 .env 中设置，格式: owner/repo")

    headers = {"Accept": "application/vnd.github+json"}
    if settings.GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {settings.GITHUB_TOKEN}"

    # 获取最新 release
    r = httpx.get(f"{GITHUB_API}/repos/{repo}/releases/latest", headers=headers, timeout=15)
    if r.status_code == 404:
        # 没有 release，尝试获取 tags
        r2 = httpx.get(f"{GITHUB_API}/repos/{repo}/tags", headers=headers, timeout=15)
        if r2.status_code == 200 and r2.json():
            tag = r2.json()[0]
            return {
                "has_update": True,
                "tag_name": tag["name"],
                "name": tag.get("name", ""),
                "body": "（Tag 无更新说明）",
                "html_url": f"https://github.com/{repo}/releases/tag/{tag['name']}",
                "zipball_url": tag.get("zipball_url", f"https://github.com/{repo}/archive/refs/tags/{tag['name']}.zip"),
                "tarball_url": tag.get("tarball_url", ""),
                "draft": False,
                "prerelease": False,
            }
        raise ValueError("仓库没有任何 Release 或 Tag")

    if r.status_code != 200:
        raise ValueError(f"GitHub API 返回 {r.status_code}: {r.text[:200]}")

    data = r.json()
    tag_name = data.get("tag_name", "")
    current = _get_current_version()

    has_update = _compare_versions(tag_name, current) > 0

    # 找到 Source code zip asset
    zip_url = None
    for asset in data.get("assets", []):
        if asset["name"].endswith(".zip"):
            zip_url = asset["browser_download_url"]
            break
    if not zip_url:
        zip_url = data.get("zipball_url", f"https://github.com/{repo}/archive/refs/tags/{tag_name}.zip")

    return {
        "has_update": has_update,
        "tag_name": tag_name,
        "name": data.get("name", ""),
        "body": data.get("body", "")[:2000],
        "html_url": data.get("html_url", ""),
        "zip_url": zip_url,
        "current_version": current,
        "draft": data.get("draft", False),
        "prerelease": data.get("prerelease", False),
    }


def apply_github_update(db: Session, zip_url: str, tag_name: str,
                        changelog: str = "") -> Dict:
    """从 GitHub 下载更新包并应用"""
    import httpx
    from backend.config import get_settings

    settings = get_settings()
    repo = settings.GITHUB_REPO.strip()

    headers = {}
    if settings.GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {settings.GITHUB_TOKEN}"

    # 1) 下载 zip
    download_dir = BASE_DIR / ".github_update"
    download_dir.mkdir(parents=True, exist_ok=True)
    zip_path = download_dir / f"{tag_name}.zip"

    logger.info(f"[System] 开始从 GitHub 下载: {zip_url}")
    with httpx.stream("GET", zip_url, headers=headers, timeout=120, follow_redirects=True) as resp:
        if resp.status_code != 200:
            raise ValueError(f"下载失败: HTTP {resp.status_code}")
        total = 0
        with open(zip_path, "wb") as f:
            for chunk in resp.iter_bytes(chunk_size=65536):
                f.write(chunk)
                total += len(chunk)

    logger.info(f"[System] GitHub 下载完成: {zip_path.name} ({total / 1024 / 1024:.1f}MB)")

    # 2) 复用 upload 更新逻辑
    try:
        result = apply_update_from_upload(
            db, str(zip_path), version=tag_name, changelog=changelog
        )
        # 修正记录类型为 github
        record = db.query(SystemUpdateRecord).filter(
            SystemUpdateRecord.id == result["id"]
        ).first()
        if record:
            record.update_type = "github"
            record.source = f"github:{repo}:{tag_name}"
            db.commit()
        return result
    finally:
        # 清理下载目录
        shutil.rmtree(download_dir, ignore_errors=True)


def _get_current_version() -> str:
    """获取当前版本号"""
    try:
        import main as _main
        if hasattr(_main, "_INSTALL_APP_VERSION"):
            return f"v{_main._INSTALL_APP_VERSION}"
    except Exception:
        pass
    return "v1.2.7"


def _compare_versions(v1: str, v2: str) -> int:
    """比较版本号，v1 > v2 返回 1，相等返回 0，v1 < v2 返回 -1"""
    def normalize(v):
        v = v.lstrip("vV").strip()
        parts = []
        for p in v.split("."):
            try:
                parts.append(int(p))
            except ValueError:
                parts.append(0)
        return parts

    a, b = normalize(v1), normalize(v2)
    for i in range(max(len(a), len(b))):
        va = a[i] if i < len(a) else 0
        vb = b[i] if i < len(b) else 0
        if va > vb:
            return 1
        if va < vb:
            return -1
    return 0

def _calc_dir_size(path: Path, pattern: str = None) -> int:
    """计算目录大小"""
    total = 0
    try:
        if pattern:
            files = path.rglob(pattern)
        else:
            files = path.rglob("*")
        for f in files:
            try:
                if f.is_file():
                    total += f.stat().st_size
            except (OSError, PermissionError):
                pass
    except (OSError, PermissionError):
        pass
    return total


def _merge_dir(src: Path, dst: Path):
    """合并目录：src 覆盖到 dst，保留 dst 独有文件"""
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        dst_item = dst / item.name
        if item.is_dir():
            _merge_dir(item, dst_item)
        else:
            shutil.copy2(item, dst_item)
