"""
系统监控服务：日志收集、状态采集、功能自检、分享令牌
提供给 /monitor 路由和仪表盘页面使用
"""
from __future__ import annotations

import os
import re
import json
import time
import threading
import uuid
import shutil
import platform
import subprocess
import socket
import ssl
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

# 分享令牌内存存储
_share_tokens: Dict[str, Dict] = {}
LOG_DIR = BASE_DIR / "logs"

# Redis客户端（多worker共享令牌状态）
_redis_client = None
SHARE_TOKEN_PREFIX = "monitor:share:token:"

# 分享令牌内存存储 + 线程锁（fallback：Redis 不可用时使用）
_share_tokens: Dict[str, Dict] = {}
_share_tokens_lock = threading.Lock()


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
        "version": "v1.2.5",
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
        
        # Load Average + Swap + 网络连接数
        load_avg = os.getloadavg() if hasattr(os, 'getloadavg') else (0, 0, 0)
        swap = psutil.swap_memory()
        net_conn_count = len(psutil.net_connections(kind='inet'))

        status["resources"] = {
            "cpu_percent": cpu_percent,
            "load_avg_1": round(load_avg[0], 2),
            "load_avg_5": round(load_avg[1], 2),
            "load_avg_15": round(load_avg[2], 2),
            "memory_percent": mem.percent,
            "memory_used_mb": round(mem.used / 1024 / 1024, 1),
            "memory_total_mb": round(mem.total / 1024 / 1024, 1),
            "swap_percent": swap.percent,
            "swap_used_mb": round(swap.used / 1024 / 1024, 1),
            "disk_percent": round(disk.used / disk.total * 100, 1),
            "disk_used_gb": round(disk.used / 1024**3, 2),
            "disk_total_gb": round(disk.total / 1024**3, 2),
            "disk_free_gb": round(disk.free / 1024**3, 2),
            "network_connections": net_conn_count,
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
        
        # MySQL 连接数等指标
        mysql_info = {}
        try:
            from sqlalchemy import text as _text
            threads = db.execute(_text("SHOW STATUS LIKE 'Threads_connected'")).fetchone()
            if threads:
                mysql_info["threads_connected"] = int(threads[1])
            slow = db.execute(_text("SHOW STATUS LIKE 'Slow_queries'")).fetchone()
            if slow:
                mysql_info["slow_queries"] = int(slow[1])
        except Exception:
            pass

        status["database"] = {
            "connection": "ok",
            "users": db.query(User).count(),
            "strategies": db.query(StrategyConfig).count(),
            "open_positions": db.query(TradePosition).filter(TradePosition.status == 1).count(),
            "total_orders": db.query(TradeOrder).count(),
            "news_articles": db.query(NewsArticle).count(),
            **mysql_info,
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
    
    # 2.4 定时任务状态（真实检测）
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from main import scheduler as _sched
        jobs = _sched.get_jobs() if _sched else []
        task_list = []
        for j in jobs:
            next_run = j.next_run_time.isoformat() if j.next_run_time else None
            task_list.append({
                "id": j.id,
                "name": j.name,
                "next_run": next_run,
                "status": "running" if next_run else "paused",
            })
        status["scheduler"] = {
            "enabled": True,
            "status": "running" if len(task_list) > 0 else "no_jobs",
            "mode": "apscheduler" if not settings.CELERY_ENABLED else "celery",
            "task_count": len(task_list),
            "tasks": task_list,
        }
    except Exception as e:
        status["scheduler"] = {"enabled": False, "error": str(e)[:100]}
        issues.append({"level": "warning", "msg": f"定时任务状态获取失败: {e}"})
    
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
    
    # 2.7 基础设施服务状态（Nginx/Supervisor）
    try:
        infra = {}
        # Nginx
        try:
            r = subprocess.run(["systemctl", "is-active", "nginx"], capture_output=True, text=True, timeout=3)
            infra["nginx"] = "running" if r.returncode == 0 else "stopped"
        except Exception:
            infra["nginx"] = "unknown"
        # Supervisor（通过端口或进程）
        try:
            r = subprocess.run(["pgrep", "-f", "supervisord"], capture_output=True, text=True, timeout=3)
            infra["supervisor"] = "running" if r.returncode == 0 else "stopped"
        except Exception:
            infra["supervisor"] = "unknown"
        status["infrastructure"] = infra
        if infra.get("nginx") == "stopped":
            issues.append({"level": "critical", "msg": "Nginx 未运行"})
    except Exception:
        status["infrastructure"] = {}

    # 2.8 交易所 WebSocket 状态
    try:
        from backend.exchanges.market import MarketManager
        mkt = MarketManager.get_instance()
        ws_status = []
        if mkt and mkt._clients:
            for name, client in mkt._clients.items():
                ws_ok = getattr(client, '_ws_connected', False)
                ws_status.append({"name": name, "ws_connected": ws_ok})
        status["market_ws"] = ws_status
        if ws_status and not all(w["ws_connected"] for w in ws_status):
            disconnected = [w["name"] for w in ws_status if not w["ws_connected"]]
            issues.append({"level": "warning", "msg": f"交易所WS断开: {', '.join(disconnected)}"})
    except Exception:
        status["market_ws"] = []

    # 2.9 AI 接口可用性
    try:
        from backend.models.ai_config import AIConfig
        ai_cfg = db.query(AIConfig).first()
        ai_has_key = bool(ai_cfg and ai_cfg.api_key_encrypted)
        status["ai_service"] = {"configured": ai_has_key, "provider": ai_cfg.provider_name if ai_cfg else None}
    except Exception as e:
        status["ai_service"] = {"configured": False, "error": str(e)[:100]}

    # 2.10 API 响应时间（自测）
    try:
        import httpx
        t0 = time.time()
        httpx.get("http://127.0.0.1:8000/health", timeout=5)
        api_ms = round((time.time() - t0) * 1000, 1)
        status["api_latency_ms"] = api_ms
        if api_ms > 3000:
            issues.append({"level": "warning", "msg": f"API响应慢: {api_ms}ms"})
    except Exception:
        status["api_latency_ms"] = -1

    # 2.11 SSL 证书过期检测
    try:
        ssl_days = None
        try:
            ctx = ssl.create_default_context()
            with socket.create_connection(("127.0.0.1", 443), timeout=3) as sock:
                with ctx.wrap_socket(sock, server_hostname="localhost") as ssock:
                    cert = ssock.getpeercert()
                    if cert and "notAfter" in cert:
                        import datetime as dt
                        expire = dt.datetime.strptime(cert["notAfter"], "%b %d %H:%M:%S %Y %Z")
                        ssl_days = (expire - dt.datetime.utcnow()).days
        except Exception:
            pass
        status["ssl"] = {"days_to_expire": ssl_days}
        if ssl_days is not None and ssl_days < 30:
            issues.append({"level": "warning", "msg": f"SSL证书将在{ssl_days}天后过期"})
    except Exception:
        status["ssl"] = {"days_to_expire": None}

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
        from backend.news.analyzer import analyze
        result = analyze("Bitcoin surges to new all-time high", "ETF inflows increase significantly.")
        add_check("新闻情绪分析", True, {"score": result.sentiment_score})
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
        from backend.strategy.engine import StrategyEngine
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

def _cleanup_token_later(token: str, delay: float):
    """在TTL过期后异步清理令牌"""
    def _cleanup():
        time.sleep(delay)
        with _share_tokens_lock:
            _share_tokens.pop(token, None)
    t = threading.Thread(target=_cleanup, daemon=True)
    t.start()


def create_share_token(db: Session, user_id: int, ttl_hours: float = 0.5) -> Dict:
    """创建一个分享令牌，用于公开访问监控页面

    分享链接格式: /monitor/share/{token}
    """
    token = hashlib.sha256(f"{uuid.uuid4()}{time.time()}{user_id}".encode()).hexdigest()[:32]
    expires_at = datetime.now() + timedelta(hours=ttl_hours)

    token_data = {
        "token": token,
        "user_id": user_id,
        "created_at": datetime.now().isoformat(),
        "expires_at": expires_at.isoformat(),
        "ttl_hours": ttl_hours,
        "access_count": 0,
    }

    # 写入Redis（持久化，支持多worker共享）
    try:
        r = _get_redis()
        import json
        r.setex(
            f"{SHARE_TOKEN_PREFIX}{token}",
            int(ttl_hours * 3600),
            json.dumps(token_data),
        )
    except Exception as e:
        logger.warning(f"[Monitor] Redis写入分享令牌失败，降级到内存: {e}")

    # 同时写入内存（降级方案）
    with _share_tokens_lock:
        _share_tokens[token] = token_data

    # 清理过期的
    _cleanup_expired_tokens()

    # 调度TTL过期后的异步清理
    _cleanup_token_later(token, ttl_hours * 3600)

    return {
        "token": token,
        "expires_at": expires_at.isoformat(),
        "share_url": f"/monitor/share/{token}",
        "ttl_hours": ttl_hours,
    }


def validate_share_token(token: str) -> Optional[Dict]:
    """验证分享令牌是否有效"""
    # 优先从Redis读取
    try:
        r = _get_redis()
        import json
        raw = r.get(f"{SHARE_TOKEN_PREFIX}{token}")
        if raw:
            info = json.loads(raw)
            # 检查是否过期
            try:
                exp = datetime.fromisoformat(info["expires_at"])
                if datetime.now() > exp:
                    r.delete(f"{SHARE_TOKEN_PREFIX}{token}")
                    return None
            except Exception:
                return None
            # 原子性增加访问计数
            info["access_count"] = info.get("access_count", 0) + 1
            r.setex(
                f"{SHARE_TOKEN_PREFIX}{token}",
                int((datetime.fromisoformat(info["expires_at"]) - datetime.now()).total_seconds()),
                json.dumps(info),
            )
            # 同步更新内存
            with _share_tokens_lock:
                _share_tokens[token] = info
            return dict(info)
    except Exception:
        pass

    # 降级到内存
    with _share_tokens_lock:
        info = _share_tokens.get(token)
        if not info:
            return None

        # 检查是否过期
        try:
            exp = datetime.fromisoformat(info["expires_at"])
            if datetime.now() > exp:
                _share_tokens.pop(token, None)
                return None
        except Exception:
            return None

        info["access_count"] += 1
        return dict(info)


def list_share_tokens(user_id: int = 0) -> List[Dict]:
    """列出有效的分享令牌"""
    _cleanup_expired_tokens()
    tokens_dict = {}

    # 从Redis读取
    try:
        r = _get_redis()
        import json
        keys = r.keys(f"{SHARE_TOKEN_PREFIX}*")
        for key in keys:
            raw = r.get(key)
            if raw:
                info = json.loads(raw)
                if user_id and info.get("user_id") != user_id:
                    continue
                tokens_dict[info.get("token", "")] = info
    except Exception:
        pass

    # 从内存读取（补充Redis中可能缺失的）
    with _share_tokens_lock:
        for t, info in _share_tokens.items():
            if user_id and info["user_id"] != user_id:
                continue
            if t not in tokens_dict:
                tokens_dict[t] = dict(info)

    return sorted(tokens_dict.values(), key=lambda x: x.get("created_at", ""), reverse=True)


def revoke_share_token(token: str) -> bool:
    """撤销分享令牌"""
    deleted = False
    # 从Redis删除
    try:
        r = _get_redis()
        r.delete(f"{SHARE_TOKEN_PREFIX}{token}")
        deleted = True
    except Exception:
        pass

    # 从内存删除
    with _share_tokens_lock:
        if token in _share_tokens:
            _share_tokens.pop(token, None)
            deleted = True

    return deleted


def _cleanup_expired_tokens():
    """清理过期令牌"""
    now = datetime.now()
    with _share_tokens_lock:
        expired = []
        for t, info in list(_share_tokens.items()):
            try:
                if now > datetime.fromisoformat(info["expires_at"]):
                    expired.append(t)
            except Exception:
                expired.append(t)
        for t in expired:
            _share_tokens.pop(t, None)

    # Redis中的过期令牌由setex自动清理，无需手动处理


# ============================================================
# 5. 生成诊断报告（一键导出给开发者分析）
# ============================================================

def generate_diagnostic_report(db: Session) -> Dict:
    """生成完整的诊断报告，包含系统状态+最近错误日志+自检结果
    
    这个报告就是你发给开发者分析的"完整快照"
    """
    report = {
        "generated_at": datetime.now().isoformat(),
        "version": "v1.2.5",
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
