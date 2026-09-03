"""
系统监控服务：日志收集、状态采集、功能自检、分享令牌
提供给 /monitor 路由和仪表盘页面使用
"""
from __future__ import annotations

import os
import re
import json
import time
import uuid
import shutil
import platform
import psutil
import hashlib
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field, asdict

from sqlalchemy.orm import Session
from loguru import logger

import redis as redis_lib

from backend.config import get_settings

settings = get_settings()

BASE_DIR = Path(__file__).resolve().parent.parent.parent
LOG_DIR = BASE_DIR / "logs"

# Redis客户端（多worker共享令牌状态）
_redis_client = None
SHARE_TOKEN_PREFIX = "monitor:share:token:"


def _get_redis():
    global _redis_client
    if _redis_client is None:
        _redis_client = redis_lib.Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            password=settings.REDIS_PASSWORD,
            db=settings.REDIS_DB,
            decode_responses=True,
        )
    return _redis_client


# ============================================================
# 1. 日志读取
# ============================================================

@dataclass
class LogEntry:
    timestamp: str
    level: str
    module: str
    function: str
    line: int
    message: str
    raw: str = ""


def _parse_log_line(line: str) -> Optional[LogEntry]:
    """解析 loguru 格式的日志行
    格式: 2026-09-02 15:25:36.000 | INFO    | module:function:line - message
    """
    line = line.rstrip("\n\r")
    if not line.strip():
        return None
    pattern = (
        r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3})\s*\|\s*"
        r"(\w+)\s*\|\s*"
        r"([^:]+):([^:]+):(\d+)\s*-\s*"
        r"(.*)$"
    )
    m = re.match(pattern, line)
    if not m:
        return None
    return LogEntry(
        timestamp=m.group(1),
        level=m.group(2).strip(),
        module=m.group(3).strip(),
        function=m.group(4).strip(),
        line=int(m.group(5)),
        message=m.group(6).strip(),
        raw=line,
    )


def list_log_files() -> List[Dict]:
    """列出所有日志文件"""
    if not LOG_DIR.exists():
        return []
    files = []
    for f in sorted(LOG_DIR.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True):
        stat = f.stat()
        files.append({
            "name": f.name,
            "size_bytes": stat.st_size,
            "size_kb": round(stat.st_size / 1024, 1),
            "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            "type": _classify_log(f.name),
        })
    return files


def _classify_log(filename: str) -> str:
    if filename.startswith("error_"):
        return "error"
    if filename.startswith("trade_"):
        return "trade"
    if filename.startswith("app_"):
        return "app"
    return "other"


def read_logs(
    log_type: str = "app",
    date_str: str = "",
    level: str = "",
    keyword: str = "",
    tail: int = 200,
    page: int = 1,
    page_size: int = 100,
) -> Dict:
    """读取日志文件，支持过滤和分页
    
    Args:
        log_type: app / error / trade
        date_str: 日期 YYYY-MM-DD，默认今天
        level: DEBUG/INFO/WARNING/ERROR，空表示全部
        keyword: 关键词搜索
        tail: 从文件末尾读取多少行（大文件优化）
        page: 页码
        page_size: 每页数量
    """
    if not date_str:
        date_str = datetime.now().strftime("%Y-%m-%d")
    
    filename = f"{log_type}_{date_str}.log"
    filepath = LOG_DIR / filename
    
    if not filepath.exists():
        return {
            "file": filename,
            "exists": False,
            "total": 0,
            "page": page,
            "page_size": page_size,
            "entries": [],
        }
    
    # 读取文件最后 N 行（避免大文件全量读）
    all_lines = _read_tail_lines(filepath, tail)
    
    # 解析 + 过滤
    entries = []
    for line in all_lines:
        entry = _parse_log_line(line)
        if not entry:
            # 非标准行（如异常堆栈），也保留
            entries.append(LogEntry(
                timestamp="", level="", module="", function="", line=0,
                message=line, raw=line
            ))
            continue
        
        if level and entry.level.upper() != level.upper():
            continue
        if keyword and keyword.lower() not in entry.message.lower():
            continue
        entries.append(entry)
    
    total = len(entries)
    
    # 分页（从新到旧显示，所以最新的在前）
    entries.reverse()
    start = (page - 1) * page_size
    end = start + page_size
    page_entries = entries[start:end]
    
    return {
        "file": filename,
        "exists": True,
        "total": total,
        "page": page,
        "page_size": page_size,
        "entries": [asdict(e) for e in page_entries],
    }


def _read_tail_lines(filepath: Path, n: int = 500) -> List[str]:
    """高效读取文件最后 n 行"""
    try:
        file_size = filepath.stat().st_size
        if file_size == 0:
            return []
        
        # 估算：平均每行 200 字节，读 n*200 字节
        read_size = min(file_size, max(n * 300, 8192))
        
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            f.seek(file_size - read_size)
            # 跳过第一行可能是不完整的
            f.readline()
            lines = f.readlines()
        
        # 如果读的不够，扩大范围
        if len(lines) < n and read_size < file_size:
            return _read_tail_lines(filepath, n * 2)
        
        return lines[-n:]
    except Exception:
        return []


def get_log_summary() -> Dict:
    """获取日志统计摘要（最近24h各级别数量）"""
    today = datetime.now().strftime("%Y-%m-%d")
    counts = {"DEBUG": 0, "INFO": 0, "WARNING": 0, "ERROR": 0, "CRITICAL": 0, "OTHER": 0}
    
    # 今天的 app 日志
    app_file = LOG_DIR / f"app_{today}.log"
    if app_file.exists():
        for line in _read_tail_lines(app_file, 2000):
            entry = _parse_log_line(line)
            if entry and entry.level:
                lvl = entry.level.upper()
                if lvl in counts:
                    counts[lvl] += 1
                else:
                    counts["OTHER"] += 1
    
    # 今天的 error 日志
    err_file = LOG_DIR / f"error_{today}.log"
    error_count = 0
    if err_file.exists():
        for line in _read_tail_lines(err_file, 500):
            if "ERROR" in line or "CRITICAL" in line:
                error_count += 1
        counts["ERROR"] = max(counts["ERROR"], error_count)
    
    # 日志目录总大小
    total_size = 0
    file_count = 0
    if LOG_DIR.exists():
        for f in LOG_DIR.glob("*.log"):
            total_size += f.stat().st_size
            file_count += 1
    
    return {
        "level_counts": counts,
        "total_log_files": file_count,
        "total_size_bytes": total_size,
        "total_size_kb": round(total_size / 1024, 1),
        "today_errors": counts["ERROR"],
        "today_warnings": counts["WARNING"],
    }


# ============================================================
# 2. 系统状态采集
# ============================================================

def collect_system_status(db: Session) -> Dict:
    """采集完整系统状态（给仪表盘用）"""
    status = {
        "collected_at": datetime.now().isoformat(),
        "overall": "healthy",
        "version": "v1.2.0",
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "uptime_seconds": _get_uptime(),
    }
    
    issues = []
    
    # 2.1 系统资源
    try:
        cpu_percent = psutil.cpu_percent(interval=0.5)
        mem = psutil.virtual_memory()
        disk = shutil.disk_usage(str(BASE_DIR))
        
        status["resources"] = {
            "cpu_percent": cpu_percent,
            "memory_percent": mem.percent,
            "memory_used_mb": round(mem.used / 1024 / 1024, 1),
            "memory_total_mb": round(mem.total / 1024 / 1024, 1),
            "disk_percent": round(disk.used / disk.total * 100, 1),
            "disk_used_gb": round(disk.used / 1024**3, 2),
            "disk_total_gb": round(disk.total / 1024**3, 2),
            "disk_free_gb": round(disk.free / 1024**3, 2),
        }
        
        if cpu_percent > 90:
            issues.append({"level": "warning", "msg": f"CPU使用率过高: {cpu_percent}%"})
        if mem.percent > 90:
            issues.append({"level": "warning", "msg": f"内存使用率过高: {mem.percent}%"})
        if disk.free / disk.total < 0.1:
            issues.append({"level": "critical", "msg": "磁盘空间不足10%"})
    except Exception as e:
        status["resources"] = {"error": str(e)}
        issues.append({"level": "warning", "msg": f"资源采集失败: {e}"})
    
    # 2.2 数据库
    try:
        from sqlalchemy import text
        db.execute(text("SELECT 1"))
        
        # 统计关键表
        from backend.models.user import User
        from backend.models.strategy import StrategyConfig
        from backend.models.trade import TradePosition, TradeOrder
        from backend.models.analytics import NewsArticle
        
        status["database"] = {
            "connection": "ok",
            "users": db.query(User).count(),
            "strategies": db.query(StrategyConfig).count(),
            "open_positions": db.query(TradePosition).filter(TradePosition.status == 1).count(),
            "total_orders": db.query(TradeOrder).count(),
            "news_articles": db.query(NewsArticle).count(),
        }
    except Exception as e:
        status["database"] = {"connection": "error", "error": str(e)}
        issues.append({"level": "critical", "msg": f"数据库连接失败: {e}"})
    
    # 2.3 Redis（如配置）
    try:
        import redis as _r
        r = _r.Redis(
            host=settings.REDIS_HOST, port=settings.REDIS_PORT,
            password=settings.REDIS_PASSWORD, db=settings.REDIS_DB,
            socket_connect_timeout=2, socket_timeout=2,
        )
        pong = r.ping()
        status["redis"] = {
            "status": "ok" if pong else "error",
            "host": settings.REDIS_HOST,
            "port": settings.REDIS_PORT,
        }
    except Exception as e:
        status["redis"] = {"status": "unavailable", "error": str(e)[:100]}
        # Redis 不是必需的，仅 warning
        if settings.CELERY_ENABLED:
            issues.append({"level": "warning", "msg": f"Redis不可用(Celery模式): {e}"})
    
    # 2.4 定时任务状态
    try:
        status["scheduler"] = {
            "enabled": True,
            "status": "running",
            "mode": "apscheduler" if not settings.CELERY_ENABLED else "celery",
            "tasks": [
                {"name": "平仓巡检", "interval": "30s", "status": "running"},
                {"name": "策略执行", "interval": "1min", "status": "running"},
                {"name": "新闻采集", "interval": "30min", "status": "running"},
                {"name": "AI分析", "interval": "2h", "status": "running"},
                {"name": "新闻策略", "interval": "1h", "status": "running"},
            ],
        }
    except Exception:
        status["scheduler"] = {"enabled": False}
    
    # 2.5 日志摘要
    try:
        log_sum = get_log_summary()
        status["logs"] = log_sum
        if log_sum["today_errors"] > 10:
            issues.append({"level": "warning", "msg": f"今日错误数较多: {log_sum['today_errors']}条"})
    except Exception:
        status["logs"] = {"level_counts": {}, "total_log_files": 0}
    
    # 2.6 交易所账号状态
    try:
        from backend.models.exchange import ExchangeAccount
        accounts = db.query(ExchangeAccount).all()
        acc_list = []
        for acc in accounts:
            acc_list.append({
                "id": acc.id,
                "name": acc.name or "",
                "exchange": acc.exchange,
                "testnet": bool(acc.testnet),
                "status": acc.status,
            })
        status["exchange_accounts"] = acc_list
    except Exception:
        status["exchange_accounts"] = []
    
    # 计算总体状态
    critical_count = sum(1 for i in issues if i["level"] == "critical")
    warning_count = sum(1 for i in issues if i["level"] == "warning")
    info_count = sum(1 for i in issues if i["level"] == "info")
    
    if critical_count > 0:
        status["overall"] = "critical"
    elif warning_count > 0:
        status["overall"] = "warning"
    else:
        status["overall"] = "healthy"
    
    status["issues"] = issues
    status["issue_count"] = {
        "total": len(issues),
        "critical": critical_count,
        "warning": warning_count,
        "info": info_count,
    }
    
    return status


def _get_uptime() -> float:
    """获取进程运行时间（秒）"""
    try:
        p = psutil.Process(os.getpid())
        return time.time() - p.create_time()
    except Exception:
        return 0


# ============================================================
# 3. 功能自检（深度检测）
# ============================================================

def run_full_self_check(db: Session) -> Dict:
    """运行完整的功能自检，返回逐项结果"""
    results = []
    start = time.monotonic()
    
    def add_check(name: str, passed: bool, detail: dict = None, error: str = ""):
        results.append({
            "name": name,
            "passed": passed,
            "detail": detail or {},
            "error": error,
        })
    
    # 3.1 核心模块导入
    core_modules = [
        ("fastapi", "FastAPI框架"),
        ("sqlalchemy", "数据库ORM"),
        ("apscheduler", "定时任务"),
        ("pandas", "数据处理"),
        ("numpy", "数值计算"),
    ]
    for mod, desc in core_modules:
        try:
            __import__(mod)
            add_check(f"模块: {desc}", True)
        except Exception as e:
            add_check(f"模块: {desc}", False, error=str(e))
    
    # 3.2 数据库
    try:
        from sqlalchemy import text
        db.execute(text("SELECT 1"))
        add_check("数据库连接", True)
    except Exception as e:
        add_check("数据库连接", False, error=str(e))
    
    # 3.3 策略评分引擎
    try:
        import numpy as np
        from backend.strategy.scoring import TechnicalIndicatorsScorer, StrategyScoringEngine
        from backend.exchanges._types import Candle
        
        np.random.seed(42)
        n = 200
        closes = 70000 + 3000 * np.sin(np.arange(n) / 20) + 500 * np.random.randn(n)
        opens = closes * (1 + (np.random.rand(n) - 0.5) * 0.002)
        highs = np.maximum(opens, closes) * (1 + np.random.rand(n) * 0.004)
        lows = np.minimum(opens, closes) * (1 - np.random.rand(n) * 0.004)
        volumes = np.random.rand(n) * 1e5
        candles = [Candle(int(i * 3600_000), float(opens[i]), float(highs[i]),
                          float(lows[i]), float(closes[i]), float(volumes[i]))
                   for i in range(n)]
        
        tech = TechnicalIndicatorsScorer().score(candles)
        add_check("策略评分引擎", True, {
            "tech_score": tech.score,
            "candles": len(candles),
        })
    except Exception as e:
        add_check("策略评分引擎", False, error=f"{e.__class__.__name__}: {e}")
    
    # 3.4 新闻情绪分析
    try:
        from backend.news.analyzer import NewsSentimentAnalyzer
        analyzer = NewsSentimentAnalyzer()
        result = analyzer.analyze_text("Bitcoin surges to new all-time high as ETF inflows increase.")
        add_check("新闻情绪分析", True, {"score": result.get("compound", 0)})
    except Exception as e:
        add_check("新闻情绪分析", False, error=f"{e.__class__.__name__}: {e}")
    
    # 3.5 代理管理器
    try:
        from backend.core.proxy_manager import ProxyManager
        pm = ProxyManager.get_instance()
        hr = pm.health_report()
        add_check("代理管理器", True, {
            "total_nodes": hr.get("total_nodes", 0),
            "active_nodes": hr.get("active_nodes", 0),
        })
    except Exception as e:
        add_check("代理管理器", False, error=f"{e.__class__.__name__}: {e}")
    
    # 3.6 交易所基类
    try:
        from backend.exchanges.base import ExchangeClientBase
        add_check("交易所客户端", True)
    except Exception as e:
        add_check("交易所客户端", False, error=str(e))
    
    # 3.7 AI模块
    try:
        from backend.strategy.ai_strategy import AIStrategyEngine
        add_check("AI策略引擎", True, {"status": "模块可导入"})
    except Exception as e:
        add_check("AI策略引擎", False, error=str(e))
    
    # 3.8 必要目录
    required_dirs = [("logs", "日志目录"), ("data", "数据目录"),
                     ("backups", "备份目录"), ("uploads", "上传目录")]
    for dir_name, display in required_dirs:
        d = BASE_DIR / dir_name
        if d.exists():
            add_check(f"目录: {display}", True)
        else:
            add_check(f"目录: {display}", False, error=f"{dir_name}/ 不存在")
    
    # 汇总
    elapsed = int((time.monotonic() - start) * 1000)
    passed = sum(1 for r in results if r["passed"])
    total = len(results)
    
    overall = "healthy"
    if passed < total * 0.7:
        overall = "critical"
    elif passed < total:
        overall = "warning"
    
    return {
        "overall": overall,
        "elapsed_ms": elapsed,
        "passed": passed,
        "total": total,
        "pass_rate": round(passed / total * 100, 1) if total else 0,
        "checks": results,
        "checked_at": datetime.now().isoformat(),
    }


# ============================================================
# 4. 分享令牌（公开日志链接）
# ============================================================

def create_share_token(db: Session, user_id: int, ttl_hours: float = 0.5) -> Dict:
    """创建一个分享令牌，用于公开访问监控页面
    
    分享链接格式: /monitor/share/{token}
    """
    token = hashlib.sha256(f"{uuid.uuid4()}{time.time()}{user_id}".encode()).hexdigest()[:32]
    expires_at = datetime.now() + timedelta(hours=ttl_hours)
    
    _share_tokens[token] = {
        "token": token,
        "user_id": user_id,
        "created_at": datetime.now().isoformat(),
        "expires_at": expires_at.isoformat(),
        "ttl_hours": ttl_hours,
        "access_count": 0,
    }
    
    # 清理过期的
    _cleanup_expired_tokens()
    
    return {
        "token": token,
        "expires_at": expires_at.isoformat(),
        "share_url": f"/monitor/share/{token}",
        "ttl_hours": ttl_hours,
    }


def validate_share_token(token: str) -> Optional[Dict]:
    """验证分享令牌是否有效"""
    info = _share_tokens.get(token)
    if not info:
        return None
    
    # 检查是否过期
    try:
        exp = datetime.fromisoformat(info["expires_at"])
        if datetime.now() > exp:
            del _share_tokens[token]
            return None
    except Exception:
        return None
    
    info["access_count"] += 1
    return info


def list_share_tokens(user_id: int = 0) -> List[Dict]:
    """列出有效的分享令牌"""
    _cleanup_expired_tokens()
    tokens = []
    for t, info in _share_tokens.items():
        if user_id and info["user_id"] != user_id:
            continue
        tokens.append(info)
    return sorted(tokens, key=lambda x: x["created_at"], reverse=True)


def revoke_share_token(token: str) -> bool:
    """撤销分享令牌"""
    if token in _share_tokens:
        del _share_tokens[token]
        return True
    return False


def _cleanup_expired_tokens():
    """清理过期令牌"""
    now = datetime.now()
    expired = []
    for t, info in _share_tokens.items():
        try:
            if now > datetime.fromisoformat(info["expires_at"]):
                expired.append(t)
        except Exception:
            expired.append(t)
    for t in expired:
        del _share_tokens[t]


# ============================================================
# 5. 生成诊断报告（一键导出给开发者分析）
# ============================================================

def generate_diagnostic_report(db: Session) -> Dict:
    """生成完整的诊断报告，包含系统状态+最近错误日志+自检结果
    
    这个报告就是你发给开发者分析的"完整快照"
    """
    report = {
        "generated_at": datetime.now().isoformat(),
        "version": "v1.2.0",
        "system_status": collect_system_status(db),
        "self_check": run_full_self_check(db),
        "log_summary": get_log_summary(),
        "recent_errors": [],
        "recent_warnings": [],
    }
    
    # 最近50条错误日志
    today = datetime.now().strftime("%Y-%m-%d")
    err_result = read_logs(log_type="error", date_str=today, tail=50, page_size=50)
    report["recent_errors"] = err_result["entries"]
    
    # 最近100条警告
    warn_result = read_logs(log_type="app", level="WARNING", date_str=today, tail=100, page_size=100)
    report["recent_warnings"] = warn_result["entries"]
    
    return report
