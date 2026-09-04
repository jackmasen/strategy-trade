"""
FastAPI 应用入口
- 装配中间件（CORS/GZip）
- 注册全局异常处理器
- 注册所有 APIRouter
- 挂载前端 dist 静态资源
- 启动/关闭事件（建表、初始化超级管理员、APScheduler）
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from contextlib import asynccontextmanager

# 确保项目根目录在 sys.path 中（宝塔 uvicorn 启动时路径问题）
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR.parent))

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from backend.config import get_settings
from backend.core.exceptions import register_exception_handlers, success
from backend.core.logging_config import setup_logger, logger
from backend.db.base import Base
from backend.db.session import engine, SessionLocal
from backend.db.seed_data import ensure_seed_data
from backend.core.auth import get_current_user
from backend.models import *  # noqa: F403 （确保所有模型被导入以便建表）
from backend.models.user import User  # noqa: F401 （在 menu_info 里显式用）

settings = get_settings()
setup_logger()


# ============== 生命周期事件 ==============

@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动/关闭钩子"""
    # ---- 启动时执行 ----
    logger.info(f"🚀 启动 {settings.APP_NAME} - 环境: {settings.APP_ENV}")

    # 1. 数据库迁移（优先 Alembic，降级为 create_all）
    try:
        from alembic.config import Config as AlembicConfig
        from alembic import command as alembic_command
        _alembic_cfg_path = str(BASE_DIR / "alembic.ini")
        import os as _os
        if _os.path.exists(_alembic_cfg_path):
            _alembic_cfg = AlembicConfig(_alembic_cfg_path)
            alembic_command.upgrade(_alembic_cfg, "head")
            logger.info("✅ Alembic 迁移完成")
        else:
            Base.metadata.create_all(bind=engine)
            logger.info("✅ 数据库表初始化完成 (create_all)")
    except Exception as e:
        logger.warning(f"⚠️ Alembic 迁移失败，降级为 create_all: {e}")
        try:
            Base.metadata.create_all(bind=engine)
        except Exception as e2:
            logger.error(f"❌ 数据库建表失败: {e2}")

    # 2. 初始化种子数据（管理员/策略模板/演示新闻/Mock交易数据 —— 幂等）
    try:
        with SessionLocal() as db:
            # 开发环境写Mock交易，生产不写
            stats = ensure_seed_data(db, with_mock_trades=settings.APP_DEBUG)
            logger.info(f"✅ 种子数据初始化完成: {stats}")
            # 安全检测：若 admin/trader 仍使用默认密码，强制 must_change_password=True
            from backend.core.utils import verify_password
            from backend.db.seed_data import DEFAULT_ADMIN_PASSWORD, DEFAULT_EDITOR_PASSWORD
            _need_flag_update = False
            for _uname, _dpwd in (
                ("admin", DEFAULT_ADMIN_PASSWORD),
                ("trader", DEFAULT_EDITOR_PASSWORD),
            ):
                _u = db.query(User).filter(User.username == _uname).first()
                if _u and verify_password(_dpwd, _u.password_hash):
                    logger.error(
                        f"🚨 安全告警：账号 [{_uname}] 仍在使用默认密码！"
                        f"请立即登录后修改，否则存在被爆破风险。"
                    )
                    if not _u.must_change_password:
                        _u.must_change_password = True
                        _need_flag_update = True
            if _need_flag_update:
                db.commit()
                logger.info("[Security] 已为使用默认密码的账号标记 must_change_password=True")
    except Exception as e:
        logger.error(f"❌ 种子数据初始化失败: {e}")

    # 3. APScheduler 定时任务（新闻采集 / 策略执行引擎 / 日报生成）
    scheduler = None
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.interval import IntervalTrigger

        scheduler = BackgroundScheduler()

        # Celery 未启用时，由 APScheduler 兜底执行交易类定时任务；
        # Celery 已启用时跳过重叠任务，避免双调度器重复触发。
        _celery_on = bool(getattr(settings, "CELERY_ENABLED", False))

        # 新闻采集：每30分钟自动采集+关键词预筛选
        def _scheduled_news_crawl():
            try:
                from backend.db.session import SessionLocal
                from backend.news.pipeline import NewsPipeline
                db = SessionLocal()
                pipeline = NewsPipeline(lookback_hours=6, max_workers=4)
                res = pipeline.run_once(db=db)
                logger.info(f"[Scheduler] 新闻采集完成: 新增{res.total_inserted}条")
                db.close()
            except Exception as e:
                logger.error(f"[Scheduler] 新闻采集失败: {e}")

        if not _celery_on:
            scheduler.add_job(
                _scheduled_news_crawl,
                IntervalTrigger(minutes=30),
                id="news_crawl",
                replace_existing=True,
            )

        # AI深度分析：每2小时对重要新闻做AI分析
        def _scheduled_ai_analysis():
            try:
                from backend.db.session import SessionLocal
                from backend.services.news_ai_analyzer import batch_analyze_with_ai
                db = SessionLocal()
                result = batch_analyze_with_ai(db, hours=6, limit=15)
                logger.info(f"[Scheduler] AI分析完成: {result.get('analyzed', 0)}条")
                db.close()
            except Exception as e:
                logger.error(f"[Scheduler] AI分析失败: {e}")

        scheduler.add_job(
            _scheduled_ai_analysis,
            IntervalTrigger(hours=2),
            id="news_ai_analysis",
            replace_existing=True,
        )

        # 数据清理：每天凌晨3点清理过期新闻和AI记录，防止数据库膨胀
        from apscheduler.triggers.cron import CronTrigger

        def _scheduled_cleanup():
            try:
                from backend.db.session import SessionLocal
                from backend.models.analytics import NewsArticle, AIAnalysisRecord
                from datetime import datetime, timedelta
                db = SessionLocal()
                now = datetime.now()

                # 清理30天前的普通新闻（impact_level < 3 的非重要新闻）
                old_cutoff = now - timedelta(days=30)
                old_news = db.query(NewsArticle).filter(
                    NewsArticle.published_at < old_cutoff,
                    NewsArticle.impact_level < 3,
                    NewsArticle.is_hot == False,
                ).all()
                for n in old_news:
                    db.delete(n)
                old_news_count = len(old_news)

                # 清理90天前的所有新闻（包括重要新闻）
                very_old_cutoff = now - timedelta(days=90)
                very_old = db.query(NewsArticle).filter(
                    NewsArticle.published_at < very_old_cutoff,
                ).all()
                for n in very_old:
                    db.delete(n)
                very_old_count = len(very_old)

                # 清理180天前的AI分析记录
                ai_cutoff = now - timedelta(days=180)
                old_ai = db.query(AIAnalysisRecord).filter(
                    AIAnalysisRecord.created_at < ai_cutoff,
                ).delete(synchronize_session=False)

                # 清理30天前的评分记录（每分钟30+条，膨胀快）
                from backend.models.strategy import ScoreRecord
                score_cutoff = now - timedelta(days=30)
                old_scores = db.query(ScoreRecord).filter(
                    ScoreRecord.candle_close_time < score_cutoff,
                ).delete(synchronize_session=False)

                db.commit()
                logger.info(
                    f"[Scheduler] 数据清理完成: 删除{old_news_count}条旧新闻, "
                    f"{very_old_count}条过期新闻, {old_ai}条AI记录, {old_scores}条评分记录"
                )
                db.close()
            except Exception as e:
                logger.error(f"[Scheduler] 数据清理失败: {e}")

        scheduler.add_job(
            _scheduled_cleanup,
            CronTrigger(hour=3, minute=0),
            id="data_cleanup",
            replace_existing=True,
        )

        # 新闻AI策略：每1小时检查一次新闻情绪并触发交易信号
        def _scheduled_news_strategy():
            try:
                from backend.db.session import SessionLocal
                from backend.services.news_strategy import run_all_news_ai_strategies
                db = SessionLocal()
                result = run_all_news_ai_strategies(db)
                if result["total_signals"] > 0:
                    logger.info(f"[Scheduler] 新闻AI策略触发 {result['total_signals']} 个信号")
                db.close()
            except Exception as e:
                logger.error(f"[Scheduler] 新闻AI策略执行失败: {e}")

        scheduler.add_job(
            _scheduled_news_strategy,
            IntervalTrigger(hours=1),
            id="news_ai_strategy",
            replace_existing=True,
        )

        # 平仓风控巡检：每30秒检查所有持仓的 TP/SL/单笔回撤/日亏，命中即市价平仓。
        # 复用 tasks/scheduled.py 的 risk_monitor；Celery 未启用时由这里兜底，保证平仓闭环不依赖额外进程。
        def _scheduled_risk_monitor():
            try:
                from backend.tasks.scheduled import risk_monitor
                risk_monitor()
            except Exception as e:
                logger.error(f"[Scheduler] 平仓巡检失败: {e}")

        if not _celery_on:
            scheduler.add_job(
                _scheduled_risk_monitor,
                IntervalTrigger(seconds=30),
                id="risk_monitor",
                replace_existing=True,
            )

        # 策略自动执行：每1分钟刷新所有启用策略评分，AUTO 模式评分达标即自动下单。
        # 复用 tasks/scheduled.py 的 update_all_scores；Celery 未启用时由这里兜底。
        def _scheduled_strategy_run():
            try:
                from backend.tasks.scheduled import update_all_scores
                update_all_scores()
            except Exception as e:
                logger.error(f"[Scheduler] 策略自动执行失败: {e}")

        if not _celery_on:
            scheduler.add_job(
                _scheduled_strategy_run,
                IntervalTrigger(minutes=1),
                id="strategy_auto_run",
                replace_existing=True,
            )

        # 代理池定时刷新：从订阅URL重新拉取节点（每 refresh_minutes 分钟）
        def _scheduled_proxy_refresh():
            try:
                from backend.core.proxy_manager import ProxyManager
                pm = ProxyManager.get_instance()
                if not pm.enabled:
                    return
                pm._refresh_if_due()
            except Exception as e:
                logger.error(f"[Scheduler] 代理池刷新失败: {e}")

        scheduler.add_job(
            _scheduled_proxy_refresh,
            IntervalTrigger(minutes=5),
            id="proxy_refresh",
            replace_existing=True,
        )

        # 代理健康检测：每10分钟并发检测所有代理连通性
        def _scheduled_proxy_health_check():
            try:
                from backend.core.proxy_manager import ProxyManager
                pm = ProxyManager.get_instance()
                if not pm.enabled:
                    return
                result = pm.check_all_proxies()
                logger.info(f"[Scheduler] 代理健康检测: {result['ok']}/{result['total']} 正常")
            except Exception as e:
                logger.error(f"[Scheduler] 代理健康检测失败: {e}")

        scheduler.add_job(
            _scheduled_proxy_health_check,
            IntervalTrigger(minutes=10),
            id="proxy_health_check",
            replace_existing=True,
        )

        scheduler.start()
        app.state.scheduler = scheduler
        _mode = "Celery" if _celery_on else "APScheduler兜底"
        logger.info(
            f"✅ 定时任务已启动（{_mode}）：平仓巡检30s/策略执行1min/新闻采集30min/"
            f"AI分析2h/新闻策略1h/清理每天3点/代理刷新5min/代理检测10min"
        )
    except ImportError:
        logger.warning("⚠️  apscheduler 未安装，定时任务未启动。pip install apscheduler 可启用。")
    except Exception as e:
        logger.error(f"❌ 定时任务启动失败: {e}")

    # 4. CryptoPanic WebSocket 实时新闻（优先WS，断线自动回退RSS轮询）
    try:
        from backend.services.cryptopanic_ws import CryptoPanicWSClient
        from backend.models.system_config import SystemConfig
        import json as _json

        cp_client = CryptoPanicWSClient.get_instance()
        with SessionLocal() as _db:
            _row = _db.query(SystemConfig).filter(
                SystemConfig.config_key == "cryptopanic_config"
            ).first()
            if _row and _row.config_value:
                _cfg = _json.loads(_row.config_value)
                _token = ""
                if _cfg.get("token_encrypted"):
                    _token = decrypt_api_key(_cfg["token_encrypted"])
                if _token:
                    cp_client.configure(
                        _token,
                        auto_close=_cfg.get("auto_close", True),
                        auto_trade=_cfg.get("auto_trade", True),
                    )
                    import asyncio as _asyncio
                    _asyncio.get_event_loop().create_task(cp_client.start())
                    logger.info("✅ CryptoPanic WebSocket 已启动（实时新闻模式）")
                else:
                    import asyncio as _asyncio
                    _asyncio.get_event_loop().create_task(cp_client.start())
                    logger.info("✅ CryptoPanic 未配置Token，启动RSS轮询兜底模式")
    except Exception as e:
        logger.error(f"❌ CryptoPanic 新闻服务启动失败: {e}")

    yield  # ---- 分隔线：下面是关闭时 ----

    # ---- 关闭时执行 ----
    logger.info("🛑 服务正在关闭...")
    try:
        from backend.services.cryptopanic_ws import CryptoPanicWSClient
        await CryptoPanicWSClient.get_instance().stop()
        logger.info("✅ CryptoPanic WebSocket 已关闭")
    except Exception:
        pass
    if hasattr(app.state, "scheduler") and app.state.scheduler:
        app.state.scheduler.shutdown()
    logger.info("👋 服务已关闭")


# ============== 创建 FastAPI 应用 ==============
#
# 说明：/docs /openapi.json 固定挂在根路径（不绑 API_PREFIX，也不绑 APP_DEBUG），
# 这样运维和用户访问 http://127.0.0.1:8000/docs 永远能看到 Swagger UI；
# 同时保留 {API_PREFIX}/docs 的兼容路径，方便前端或脚本调用。
PREFIX = settings.API_PREFIX
_docs_ok = "/docs"
_redoc_ok = "/redoc"
_openapi_ok = "/openapi.json"
_docs_compat = f"{PREFIX}/docs"
_redoc_compat = f"{PREFIX}/redoc"
_openapi_compat = f"{PREFIX}/openapi.json"

app = FastAPI(
    title=settings.APP_NAME,
    description="策略交易系统 - 支持币安/OKX子账号、新闻+指标+AI综合评分、1H/4H多空策略、回测、财务报表",
    version="1.2.0",
    docs_url=_docs_ok,
    redoc_url=_redoc_ok,
    openapi_url=_openapi_ok,
    lifespan=lifespan,
)


# 兼容旧路径：把 /api/v1/docs 等 307 重定向到根路径下的同名端点（Swagger UI 本身会再自动找 openapi.json）
from fastapi.responses import RedirectResponse


@app.get(_docs_compat, include_in_schema=False)
async def _docs_compat_redirect():
    return RedirectResponse(url=_docs_ok, status_code=307)


@app.get(_redoc_compat, include_in_schema=False)
async def _redoc_compat_redirect():
    return RedirectResponse(url=_redoc_ok, status_code=307)


@app.get(_openapi_compat, include_in_schema=False)
async def _openapi_compat_redirect():
    return RedirectResponse(url=_openapi_ok, status_code=307)

# ============== 中间件 ==============

# CORS：通过 CORS_ALLOW_ORIGINS 配置；生产应改为具体域名（逗号分隔）。
# 注意：allow_credentials=True 与 allow_origins=["*"] 同时存在是安全风险，
# 因此当来源含 * 时自动关闭 credentials，仅指定域名时才开启。
_cors_raw = (getattr(settings, "CORS_ALLOW_ORIGINS", "*") or "*").strip()
_cors_origins = [o.strip() for o in _cors_raw.split(",") if o.strip()]
_cors_wildcard = "*" in _cors_origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=not _cors_wildcard,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)
app.add_middleware(GZipMiddleware, minimum_size=1024)


# ============== 强制修改密码中间件 ==============
# 当用户 must_change_password=True 时，仅允许访问登录/刷新Token/查看个人信息/修改密码接口，
# 其他已认证接口一律返回 403，迫使前端引导用户先修改密码。
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse


class MustChangePasswordMiddleware(BaseHTTPMiddleware):
    # 允许通过的路径（不需要检查 must_change_password）
    _ALLOWED_PATHS = {
        f"{PREFIX}/auth/login",
        f"{PREFIX}/auth/refresh",
        f"{PREFIX}/auth/logout",
        f"{PREFIX}/users/me",
        f"{PREFIX}/users/me/password",
    }

    async def dispatch(self, request, call_next):
        path = request.url.path
        # 非 API 路径 / docs / openapi 直接放行
        if not path.startswith(PREFIX) or path in ("/docs", "/redoc", "/openapi.json"):
            return await call_next(request)
        # 白名单路径放行
        if path in self._ALLOWED_PATHS:
            return await call_next(request)
        # 尝试解析 Token（未带 Token 的请求交给后续依赖处理，不拦截）
        auth_header = request.headers.get("Authorization", "")
        token = ""
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
        if not token:
            token = request.cookies.get("access_token", "")
        if not token:
            return await call_next(request)
        try:
            from backend.core.utils import decode_token
            from backend.db.session import SessionLocal
            from backend.models.user import User
            payload = decode_token(token)
            if payload.get("type") != "access":
                return await call_next(request)
            uid = int(payload.get("sub", 0))
            if not uid:
                return await call_next(request)
            with SessionLocal() as _db:
                _u = _db.query(User).filter(User.id == uid, User.status == 1).first()
                if _u and _u.must_change_password:
                    return JSONResponse(
                        status_code=403,
                        content={
                            "code": 403,
                            "message": "账号需要修改默认密码后才能继续操作",
                            "data": {"must_change_password": True},
                        },
                    )
        except Exception:
            pass  # 解析失败交给后续认证依赖处理
        return await call_next(request)


app.add_middleware(MustChangePasswordMiddleware)


# ============== 全局异常 ==============
register_exception_handlers(app)


# ============== 注册路由 ==============

from backend.routers.auth import router as auth_router, user_router
from backend.routers.exchange import router as exchange_router
from backend.routers.strategy import router as strategy_router
from backend.routers.trade import router as trade_router
from backend.routers.analytics import (
    router as analytics_base_router, ai_router, news_router, risk_router, backtest_router, report_router,
)
from backend.routers.settings import router as settings_router
from backend.routers.ai_keys import router as ai_keys_router
from backend.routers.notifications import router as notifications_router
from backend.routers.quant_signal import router as quant_signal_router
from backend.routers.system_admin import router as system_admin_router
from backend.routers.monitor import router as monitor_router
from backend.routers.kline_layout import router as kline_layout_router

# 认证与用户
app.include_router(auth_router, prefix=PREFIX)
app.include_router(user_router, prefix=PREFIX)
# 交易所
app.include_router(exchange_router, prefix=PREFIX)
# 策略
app.include_router(strategy_router, prefix=PREFIX)
# 交易
app.include_router(trade_router, prefix=PREFIX)
# AI / 新闻 / 风控 / 回测 / 报表 / 综合预测
app.include_router(analytics_base_router, prefix=PREFIX)
app.include_router(ai_router, prefix=PREFIX)
app.include_router(news_router, prefix=PREFIX)
app.include_router(risk_router, prefix=PREFIX)
app.include_router(backtest_router, prefix=PREFIX)
app.include_router(report_router, prefix=PREFIX)
# AI量化信号引擎
app.include_router(quant_signal_router, prefix=PREFIX)
# 策略自我进化
from backend.routers.evolution import router as evolution_router
app.include_router(evolution_router, prefix=PREFIX)
# 系统配置
app.include_router(settings_router, prefix=PREFIX)
# AI多API故障转移
app.include_router(ai_keys_router, prefix=PREFIX)
# 通知中心
app.include_router(notifications_router, prefix=PREFIX)
# 系统管理（管理员）
app.include_router(system_admin_router, prefix=PREFIX)
# 系统监控（仪表盘+日志+分享）
app.include_router(monitor_router, prefix=PREFIX)
# K线自定义布局（个人+公共）
app.include_router(kline_layout_router, prefix=PREFIX)


# ============== 健康检查 ==============

@app.get("/health", tags=["系统"])
def health_check():
    """健康检查（供宝塔/监控/Nginx存活探测）—— 安装状态不影响，保持可探测"""
    installed = _onepress_is_installed()
    extra = {"installed": installed}
    if installed:
        extra["installed_at"] = _onepress_install_info().get("installed_at")
    return success({"status": "ok", "app": settings.APP_NAME, "env": settings.APP_ENV, **extra})


# ============================================================================
# 🚀 WordPress 式一键安装向导（宝塔用户：加网站 → 传 zip → 访问域名自动跳 /install）
# - 未安装：访问 / 自动 307 跳 /install
# - 已安装：/install 直接 307 跳 /，且禁止 POST 二次安装
# - 向导完成后，输出 1 行命令 + Nginx 反代片段 + 宝塔 Python 项目管理器配置
# ============================================================================
from fastapi import Request, HTTPException, Body
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse
import json, re, secrets, shutil, string, time, hashlib, platform
from typing import Any
from pathlib import Path as _Path

_INSTALL_MARK_FILE = BASE_DIR / ".installed"  # 项目根下放一个简单的 JSON 标记
_INSTALL_ENV_EXAMPLE = BASE_DIR / ".env.example"
_INSTALL_ENV_FILE = BASE_DIR / ".env"
_INSTALL_APP_VERSION = "1.2.0"


def _onepress_is_installed() -> bool:
    return _INSTALL_MARK_FILE.exists() and _INSTALL_MARK_FILE.is_file()


def _onepress_install_info() -> dict:
    try:
        if _INSTALL_MARK_FILE.exists():
            return json.loads(_INSTALL_MARK_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _onepress_mark_installed(meta: dict) -> None:
    payload = {
        "installed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "version": _INSTALL_APP_VERSION,
        "host": platform.node(),
        **meta,
    }
    # 600 权限（尽力而为）
    try:
        if _INSTALL_MARK_FILE.exists():
            _INSTALL_MARK_FILE.chmod(0o600)
        _INSTALL_MARK_FILE.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        _INSTALL_MARK_FILE.chmod(0o600)
    except Exception:
        pass


def _onepress_rand_secret(n: int = 48) -> str:
    alphabet = string.ascii_letters + string.digits + "-_!$@%"
    return "".join(secrets.choice(alphabet) for _ in range(n))


def _onepress_env_lines_from_payload(p: dict[str, Any]) -> list[str]:
    """根据安装向导 payload 生成 .env 文本；保留用户原有 DB_SQLITE_FALLBACK（用户可能选了 SQLite）"""
    out: list[str] = []
    # ---------- 基础 ----------
    out.append("# ---------- 基础 ----------")
    out.append(f'APP_NAME={p.get("APP_NAME") or "TradingStrategySystem"}')
    out.append(f'APP_ENV={p.get("APP_ENV") or "production"}')
    out.append(f'APP_DEBUG={"true" if str(p.get("APP_DEBUG","")).lower() in ("1","true","yes") else "false"}')
    out.append(f'APP_SECRET_KEY={p.get("APP_SECRET_KEY") or _onepress_rand_secret(64)}')
    out.append('API_PREFIX=/api/v1')
    out.append('SERVER_HOST=0.0.0.0')
    out.append('SERVER_PORT=8000')
    out.append("")

    # ---------- 数据库 ----------
    out.append("# ---------- 数据库 ----------")
    use_sqlite = str(p.get("USE_SQLITE", "")).lower() in ("1", "true", "yes", "y", "on")
    if use_sqlite:
        sqlite_path = str(p.get("DB_SQLITE_FALLBACK") or "sqlite:///./trading_system.db")
        out.append(f'DB_SQLITE_FALLBACK={sqlite_path}')
        # MySQL 字段留空占位
        for k in ("DB_HOST","DB_PORT","DB_USER","DB_PASSWORD","DB_NAME","DB_CHARSET"):
            out.append(f"{k}=")
    else:
        out.append(f'DB_HOST={p.get("DB_HOST") or "127.0.0.1"}')
        out.append(f'DB_PORT={p.get("DB_PORT") or "3306"}')
        out.append(f'DB_USER={p.get("DB_USER") or "root"}')
        out.append(f'DB_PASSWORD={p.get("DB_PASSWORD") or ""}')
        out.append(f'DB_NAME={p.get("DB_NAME") or "trading_system"}')
        out.append(f'DB_CHARSET={p.get("DB_CHARSET") or "utf8mb4"}')
        out.append('DB_SQLITE_FALLBACK=')
    out.append("")

    # ---------- Redis ----------
    out.append("# ---------- Redis ----------")
    out.append(f'REDIS_HOST={p.get("REDIS_HOST") or "127.0.0.1"}')
    out.append(f'REDIS_PORT={p.get("REDIS_PORT") or "6379"}')
    out.append(f'REDIS_PASSWORD={p.get("REDIS_PASSWORD") or ""}')
    out.append(f'REDIS_DB={p.get("REDIS_DB") or "0"}')
    out.append(f'REDIS_DB_CELERY={p.get("REDIS_DB_CELERY") or "1"}')
    out.append("")

    # ---------- 币安 ----------
    out.append("# ---------- 币安 ----------")
    out.append(f'BINANCE_MAIN_API_KEY={p.get("BINANCE_MAIN_API_KEY") or ""}')
    out.append(f'BINANCE_MAIN_API_SECRET={p.get("BINANCE_MAIN_API_SECRET") or ""}')
    out.append(f'BINANCE_TESTNET={"true" if str(p.get("BINANCE_TESTNET","false")).lower() in ("1","true","yes","y") else "false"}')
    out.append(f'BINANCE_BASE_URL={p.get("BINANCE_BASE_URL") or ("https://testnet.binancefuture.com" if str(p.get("BINANCE_TESTNET")).lower()!="false" else "https://fapi.binance.com")}')
    out.append("")

    # ---------- OKX ----------
    out.append("# ---------- OKX ----------")
    out.append(f'OKX_MAIN_API_KEY={p.get("OKX_MAIN_API_KEY") or ""}')
    out.append(f'OKX_MAIN_API_SECRET={p.get("OKX_MAIN_API_SECRET") or ""}')
    out.append(f'OKX_MAIN_PASSPHRASE={p.get("OKX_MAIN_PASSPHRASE") or ""}')
    out.append(f'OKX_TESTNET={"true" if str(p.get("OKX_TESTNET","false")).lower() in ("1","true","yes","y") else "false"}')
    out.append(f'OKX_BASE_URL={p.get("OKX_BASE_URL") or "https://www.okx.com"}')
    out.append("")

    # ---------- 代理 / AI / 新闻 / 告警 ----------
    out.append("# ---------- 代理 / AI / 新闻 / 告警 ----------")
    out.append(f'PROXY_ENABLED={"true" if str(p.get("PROXY_ENABLED","true")).lower() not in ("0","false","no","n","off") else "false"}')
    out.append(f'PROXY_HTTP_LIST={p.get("PROXY_HTTP_LIST") or ""}')
    out.append(f'AI_PROVIDER={p.get("AI_PROVIDER") or "custom"}')
    out.append(f'AI_API_KEY={p.get("AI_API_KEY") or ""}')
    out.append(f'AI_API_ENDPOINT={p.get("AI_API_ENDPOINT") or ""}')
    out.append(f'AI_MODEL_NAME={p.get("AI_MODEL_NAME") or "gpt-4o"}')
    out.append(f'DINGTALK_WEBHOOK={p.get("DINGTALK_WEBHOOK") or ""}')
    out.append(f'FEISHU_WEBHOOK={p.get("FEISHU_WEBHOOK") or ""}')
    out.append("")
    return out


def _onepress_write_env(lines: list[str]) -> None:
    # 已存在 .env 就加前缀备份（不丢原有配置）
    if _INSTALL_ENV_FILE.exists():
        backup = _INSTALL_ENV_FILE.with_name(
            _INSTALL_ENV_FILE.name + ".bak." + time.strftime("%Y%m%d%H%M%S")
        )
        try:
            shutil.copy2(_INSTALL_ENV_FILE, backup)
        except Exception:
            pass
    _INSTALL_ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        _INSTALL_ENV_FILE.chmod(0o600)
    except Exception:
        pass


def _onepress_reload_settings() -> None:
    """安装向导写完 .env 后，强制重新读取配置（刷新 pydantic-settings lru_cache）"""
    from backend import config as _cfg_mod
    _get_settings = getattr(_cfg_mod, "get_settings", None)
    if callable(_get_settings):
        try:
            _get_settings.cache_clear()
        except Exception:
            pass
    # 把本文件里的 settings 引用也刷新（避免后续 DB 初始化用旧连接）
    global settings
    try:
        settings = get_settings()
    except Exception:
        pass


def _onepress_try_db_connect(timeout_seconds: int = 6) -> tuple[bool, str]:
    """安装向导预检数据库能不能连上，不抛异常，返回 (ok, message)"""
    try:
        # 重新读 settings（用户可能在向导里刚选了 SQLite）
        from backend.config import get_settings as _gs
        try: _gs.cache_clear()
        except Exception: pass
        st = _gs()
        if str(st.DB_SQLITE_FALLBACK or "").strip():
            return (True, f"SQLite fallback 模式 OK：{st.DB_SQLITE_FALLBACK}")
        import pymysql  # type: ignore
        conn = pymysql.connect(
            host=st.DB_HOST, port=int(st.DB_PORT), user=st.DB_USER,
            password=str(st.DB_PASSWORD), database=st.DB_NAME,
            charset=st.DB_CHARSET, connect_timeout=timeout_seconds,
        )
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        finally:
            conn.close()
        return (True, f"MySQL OK：{st.DB_HOST}:{st.DB_PORT}/{st.DB_NAME}")
    except Exception as e:
        return (False, f"连接失败：{type(e).__name__}: {e}")


def _onepress_try_redis_connect(timeout_seconds: int = 3) -> tuple[bool, str]:
    try:
        from backend.config import get_settings as _gs
        try: _gs.cache_clear()
        except Exception: pass
        st = _gs()
        import redis as _redis  # type: ignore
        r = _redis.Redis(
            host=st.REDIS_HOST, port=int(st.REDIS_PORT),
            password=(st.REDIS_PASSWORD or None), db=int(st.REDIS_DB),
            socket_connect_timeout=timeout_seconds, socket_timeout=timeout_seconds,
        )
        r.ping()
        return (True, f"Redis OK：{st.REDIS_HOST}:{st.REDIS_PORT}/{st.REDIS_DB}")
    except Exception as e:
        return (False, f"Redis 未启用或连接失败（不影响后端启动，后续可再配）：{type(e).__name__}: {e}")


def _onepress_precheck() -> dict:
    from backend.config import get_settings as _gs
    py_ok = sys.version_info >= (3, 10)
    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    disk_ok_gb = 5
    disk_free_gb = 0
    ram_gb = 0
    try:
        usage = shutil.disk_usage(str(BASE_DIR))
        disk_free_gb = round(usage.free / 1024 / 1024 / 1024, 2)
    except Exception:
        pass
    try:
        import psutil  # type: ignore
        ram_gb = round(psutil.virtual_memory().total / 1024 / 1024 / 1024, 2)
    except Exception:
        pass
    db_ok, db_msg = _onepress_try_db_connect()
    redis_ok, redis_msg = _onepress_try_redis_connect()
    # 核心依赖 import 检查（只报不致命，让用户知道缺什么）
    missing: list[str] = []
    for mod, pip_name in [
        ("fastapi","fastapi"),("uvicorn","uvicorn"),("sqlalchemy","sqlalchemy"),
        ("pydantic","pydantic"),("redis","redis"),("celery","celery"),
        ("jinja2","jinja2"),("pandas","pandas"),("numpy","numpy"),
        ("requests","requests"),("websockets","websockets"),("aiosqlite","aiosqlite"),
        ("jose","python-jose[cryptography]"),("passlib","passlib[bcrypt]"),
        ("pymysql","pymysql"),("pydantic_settings","pydantic-settings"),
    ]:
        try:
            __import__(mod)
        except Exception:
            missing.append(pip_name)
    requirements_txt = BASE_DIR / "requirements.txt"
    return {
        "python": {
            "version": py_ver,
            "ok": py_ok,
            "required": "3.10+",
        },
        "disk": {
            "free_gb": disk_free_gb,
            "required_gb": disk_ok_gb,
            "ok": disk_free_gb >= disk_ok_gb,
        },
        "ram_gb": ram_gb,
        "db": {"ok": db_ok, "message": db_msg},
        "redis": {"ok": redis_ok, "message": redis_msg},
        "missing_packages": missing,
        "requirements_exists": requirements_txt.exists(),
        "frontend_dist_exists": bool(FRONTEND_DIST and FRONTEND_DIST.exists() and (FRONTEND_DIST / "index.html").exists()),
        "installed": _onepress_is_installed(),
        "install_info": _onepress_install_info(),
    }


# ---------- GET /install：Web 安装向导 HTML（零 JS 依赖也能用，按钮纯 HTML form）----------
_INSTALL_HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<title>策略交易系统 · 一键安装向导</title>
<style>
  *{box-sizing:border-box}
  body{margin:0;padding:28px 22px 60px;font-family:"Microsoft YaHei","PingFang SC",Segoe UI,Arial,sans-serif;background:linear-gradient(135deg,#0b1220,#132039 55%,#0b1220);color:#e2e8f0;}
  .wrap{max-width:980px;margin:0 auto}
  h1{margin:0 0 6px;font-size:28px;background:linear-gradient(90deg,#60a5fa,#a78bfa,#f472b6);-webkit-background-clip:text;-webkit-text-fill-color:transparent;}
  .sub{color:#94a3b8;margin-bottom:22px;font-size:14px;}
  .card{background:rgba(15,23,42,.7);border:1px solid rgba(148,163,184,.18);border-radius:16px;padding:22px 24px;margin-bottom:22px;backdrop-filter:blur(6px);box-shadow:0 18px 40px rgba(0,0,0,.28)}
  h2{margin:0 0 14px;font-size:20px;letter-spacing:.5px}
  .chip{display:inline-block;padding:2px 10px;border-radius:999px;font-size:12px;font-weight:600;margin-right:6px}
  .chip.ok{background:rgba(16,185,129,.15);color:#34d399;border:1px solid rgba(52,211,153,.4)}
  .chip.err{background:rgba(239,68,68,.18);color:#fca5a5;border:1px solid rgba(252,165,165,.4)}
  .chip.warn{background:rgba(245,158,11,.15);color:#fbbf24;border:1px solid rgba(251,191,36,.4)}
  .chip.info{background:rgba(59,130,246,.15);color:#93c5fd;border:1px solid rgba(147,197,253,.4)}
  table{width:100%;border-collapse:collapse;font-size:13px;margin-top:8px}
  th,td{padding:9px 12px;border-bottom:1px solid rgba(148,163,184,.15);text-align:left;vertical-align:top}
  th{background:rgba(30,41,59,.6);color:#cbd5e1}
  .row{display:grid;grid-template-columns:1fr 1fr;gap:12px 16px;margin:10px 0}
  @media(max-width:820px){.row{grid-template-columns:1fr}}
  label{display:block;font-size:13px;margin-bottom:6px;color:#cbd5e1}
  input,select,textarea{width:100%;background:#0b1120;border:1px solid rgba(148,163,184,.25);border-radius:10px;color:#e2e8f0;padding:10px 12px;font-size:14px;outline:none}
  input:focus,select:focus,textarea:focus{border-color:#60a5fa;box-shadow:0 0 0 3px rgba(96,165,250,.18)}
  textarea{min-height:90px;resize:vertical}
  .hint{font-size:12px;color:#94a3b8;margin-top:4px}
  .actions{display:flex;gap:12px;flex-wrap:wrap;margin-top:14px}
  button{padding:12px 20px;border-radius:12px;border:none;color:#fff;font-size:15px;font-weight:700;letter-spacing:.5px;cursor:pointer}
  button.primary{background:linear-gradient(135deg,#10b981,#059669);box-shadow:0 10px 28px rgba(16,185,129,.35)}
  button.primary:hover{filter:brightness(1.08)}
  button.secondary{background:rgba(255,255,255,.14);border:1px solid rgba(255,255,255,.28);font-weight:500}
  .grid-3{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-top:6px}
  @media(max-width:720px){.grid-3{grid-template-columns:1fr}}
  .stat{background:rgba(30,41,59,.55);border:1px solid rgba(148,163,184,.15);border-radius:12px;padding:12px 14px}
  .stat .k{font-size:12px;color:#93c5fd;letter-spacing:1px}
  .stat .v{font-size:20px;font-weight:700;margin-top:4px}
  code,.mono{font-family:Consolas,"Courier New",monospace;background:#0b1120;border:1px solid rgba(148,163,184,.2);padding:2px 8px;border-radius:8px}
  details{margin-top:8px}
  details summary{cursor:pointer;padding:6px 2px;color:#93c5fd}
  footer{margin-top:28px;text-align:center;font-size:12px;color:#64748b}
  .danger{color:#fca5a5;font-weight:600}
</style>
</head>
<body>
<div class="wrap">
<h1>📈 策略交易系统 · 一键安装向导（WordPress 式体验）</h1>
<div class="sub">宝塔用户流程：添加网站 → 上传 onepress zip → 解压 → 访问域名自动跳到本页。点击『运行安装』即可，全程不进终端。</div>

<div class="card">
  <h2>① 环境预检 <span class="chip info" id="chipInstallState">未安装</span></h2>
  <div class="grid-3">
    <div class="stat"><div class="k">PYTHON 版本</div><div class="v" id="pyVer">…</div><div class="hint" id="pyHint"></div></div>
    <div class="stat"><div class="k">剩余磁盘</div><div class="v" id="disk">…</div><div class="hint" id="diskHint"></div></div>
    <div class="stat"><div class="k">内存</div><div class="v" id="ram">…</div><div class="hint">生产建议 ≥ 8GB</div></div>
  </div>
  <table id="precheckTable">
    <thead><tr><th style="width:30%">检查项</th><th>结果</th><th style="width:18%">状态</th></tr></thead>
    <tbody></tbody>
  </table>
  <div class="hint">缺 Python 包不影响安装继续。安装完成后，页面第 ③ 步会给出一条命令自动 <code>pip install -r requirements.txt</code>。</div>
</div>

<form id="installForm" onsubmit="return submitInstall(event)">
<div class="card">
  <h2>② 站点 &amp; 数据库配置（像 WordPress 一样填写下面 8~10 项即可）</h2>

  <div class="row">
    <div><label>站点标题</label><input id="APP_NAME" name="APP_NAME" value="TradingStrategySystem" /></div>
    <div><label>运行环境</label>
      <select id="APP_ENV" name="APP_ENV">
        <option value="production" selected>生产（宝塔部署推荐）</option>
        <option value="development">开发 / 调试</option>
        <option value="staging">预发布</option>
      </select>
    </div>
  </div>

  <div class="row">
    <div>
      <label>管理员账号（自定义，不强制默认 admin）</label>
      <input id="ADMIN_USERNAME" name="ADMIN_USERNAME" value="admin" placeholder="建议改成你自己的用户名" />
      <div class="hint">建议不要用 admin / root / test 这类常见名</div>
    </div>
    <div>
      <label>管理员密码（必填，至少 8 位，数字+字母）</label>
      <input type="password" id="ADMIN_PASSWORD" name="ADMIN_PASSWORD" placeholder="至少 8 位，例如 Str0ng!P@ss" value="" />
      <div class="hint">⚠️ 忘记密码只能清空用户表重建，务必保存到密码管理器</div>
    </div>
    <div>
      <label>管理员昵称</label><input id="ADMIN_NICKNAME" name="ADMIN_NICKNAME" value="超级管理员" />
    </div>
    <div>
      <label>APP_SECRET_KEY（JWT 秘钥，不填自动生成 64 位）</label>
      <input id="APP_SECRET_KEY" name="APP_SECRET_KEY" placeholder="留空自动生成；生产务必保存（换服务器要同步）" />
    </div>
  </div>

  <hr style="border:none;border-top:1px dashed rgba(148,163,184,.2);margin:18px 0" />

  <div class="row">
    <div>
      <label><input type="checkbox" id="USE_SQLITE" name="USE_SQLITE" onchange="toggleMysqlInputs(this.checked)" /> 先试用 SQLite（零依赖宝塔直接跑，以后可换 MySQL）</label>
      <div class="hint">✅ 推荐第一次安装选这个：不用建数据库，点击运行安装立刻能用；上线前再切换为 MySQL。</div>
    </div>
  </div>

  <div class="row" id="mysqlBox">
    <div><label>MySQL 主机</label><input id="DB_HOST" name="DB_HOST" value="127.0.0.1" /></div>
    <div><label>端口</label><input id="DB_PORT" name="DB_PORT" value="3306" /></div>
    <div><label>数据库用户</label><input id="DB_USER" name="DB_USER" value="trading_user" /></div>
    <div><label>数据库密码</label><input id="DB_PASSWORD" name="DB_PASSWORD" type="password" /></div>
    <div><label>数据库名</label><input id="DB_NAME" name="DB_NAME" value="trading_system" /></div>
    <div><label>字符集</label><input id="DB_CHARSET" name="DB_CHARSET" value="utf8mb4" /></div>
  </div>

  <hr style="border:none;border-top:1px dashed rgba(148,163,184,.2);margin:18px 0" />

  <div class="row">
    <div><label>Redis 主机（留空 127.0.0.1；无 Redis 也能启动，只是 Celery 不开）</label><input id="REDIS_HOST" name="REDIS_HOST" value="127.0.0.1" /></div>
    <div><label>端口 / 密码 / DB</label><div class="row" style="margin:0"><input id="REDIS_PORT" name="REDIS_PORT" value="6379" /><input id="REDIS_PASSWORD" name="REDIS_PASSWORD" type="password" placeholder="无密码留空" /><input id="REDIS_DB" name="REDIS_DB" value="0" /></div></div>
  </div>

  <details>
    <summary>📌 更多配置：币安 / OKX API / 代理池 / AI 模型（都可留空，装好再在「系统设置」改）</summary>
    <div class="row">
      <div><label>BINANCE 主账号 API Key</label><input id="BINANCE_MAIN_API_KEY" /></div>
      <div><label>BINANCE Secret</label><input id="BINANCE_MAIN_API_SECRET" type="password" /></div>
      <div><label>BINANCE_TESTNET（测试网=低风险，先跑这个）</label>
        <select id="BINANCE_TESTNET"><option value="true" selected>true（测试网）</option><option value="false">false（实盘，确认有风控再开）</option></select>
      </div>
      <div><label>OKX API Key / Secret / Passphrase</label>
        <input id="OKX_MAIN_API_KEY" placeholder="Key"/>
        <input id="OKX_MAIN_API_SECRET" type="password" placeholder="Secret"/>
        <input id="OKX_MAIN_PASSPHRASE" type="password" placeholder="Passphrase"/>
      </div>
    </div>
    <div class="row">
      <div><label>代理（抓国际新闻经常失败就填，多个逗号分隔）<span class="chip.info">http://user:pass@ip:port,…</span></label><textarea id="PROXY_HTTP_LIST" placeholder="留空=直连；例如：http://127.0.0.1:7890"></textarea></div>
      <div><label>AI 模型 / API Key / Endpoint（AI 评分用）</label>
        <select id="AI_PROVIDER">
          <option value="custom" selected>custom（走后端代理，可不填）</option>
          <option value="openai">openai</option><option value="anthropic">anthropic</option><option value="local">本地部署</option>
        </select>
        <input id="AI_API_KEY" type="password" placeholder="Key 留空也不影响基础功能"/>
        <input id="AI_API_ENDPOINT" placeholder="Endpoint 留空走默认官方" />
        <input id="AI_MODEL_NAME" value="gpt-4o" />
      </div>
    </div>
  </details>

  <div class="actions">
    <button type="button" class="secondary" onclick="location.href='/health'">🔍 先测 /health</button>
    <button type="button" class="secondary" onclick="loadPrecheck()">🔄 重新检测环境</button>
    <button type="submit" class="primary" id="btnSubmit">▶️ 运行安装（写入 .env → 建表 → 创建管理员）</button>
  </div>
</div>
</form>

<div class="card" id="step3card" style="display:none;">
  <h2>③ 安装完成 ✅ 宝塔一键启动下面两项即可上线（WordPress famous 5 秒结束）</h2>
  <div class="hint">安装向导已经帮你完成：.env 写入、数据库建表、策略模板初始化、管理员账号创建。<b>剩下只需两步启动后端进程（或在宝塔 Python 项目管理器添加项目），就能访问站点。</b></div>

  <h3 style="margin-top:18px;font-size:16px;color:#93c5fd;">方案 A（推荐，宝塔用户最快）：宝塔「Python 项目管理器」添加项目</h3>
  <table id="btTable"><thead><tr><th>项目字段</th><th>填什么</th></tr></thead><tbody></tbody></table>

  <h3 style="margin-top:20px;font-size:16px;color:#93c5fd;">方案 B（1 行命令，不想进管理器就粘贴这个）：后台启动 + 进程文件保存</h3>
  <div class="hint">宝塔站点根目录打开终端，粘贴下面命令（已包含建 venv + pip install + nohup 后台起 uvicorn，输出到 logs/uvicorn.log）</div>
  <pre class="mono" id="oneLineCmd" style="padding:14px 16px;line-height:1.6;overflow-x:auto;white-space:pre-wrap;word-break:break-all;"></pre>
  <div class="actions"><button type="button" class="primary" id="btnCopyCmd" onclick="copyText(document.getElementById('oneLineCmd').innerText)">📋 复制 1 行启动命令</button></div>

  <h3 style="margin-top:20px;font-size:16px;color:#93c5fd;">方案 C（可选但推荐，Nginx 反代片段）</h3>
  <div class="hint">宝塔站点设置 → 配置文件 → 在 <code>server {</code> 里面，<b>仅插入下面 location 片段</b>（不要替换整段 server{}，避免 SSL 证书路径丢失）</div>
  <pre class="mono" id="nginxSnippet" style="padding:14px 16px;line-height:1.6;overflow-x:auto;white-space:pre-wrap;"></pre>
  <div class="actions"><button type="button" class="secondary" onclick="copyText(document.getElementById('nginxSnippet').innerText)">📋 复制 Nginx 反代片段</button></div>

  <h3 style="margin-top:20px;font-size:16px;color:#93c5fd;">✅ 最后验收（出现这 3 个信号就全部完成）</h3>
  <ol class="hint" style="line-height:2;">
    <li>访问 <a target="_blank" href="/health">/health</a>：返回 <code>{"status":"ok","installed":true}</code></li>
    <li>访问 <a target="_blank" href="/docs">/docs</a>：能看到 Swagger UI（左侧接口列表 + Authorize 按钮）</li>
    <li>访问 <a target="_blank" href="/">/</a>：前端正常（如未构建 dist，会提示「先构建前端 /docs 可正常用」，/docs 能用就说明后端 OK）</li>
  </ol>

  <div class="actions" style="margin-top:18px;">
    <a class="mono" href="/docs" target="_blank" style="text-decoration:none;padding:12px 18px;color:#fff;background:linear-gradient(135deg,#3b82f6,#1d4ed8);border-radius:12px;font-weight:700">👉 去 Swagger 文档 /docs 试试登录</a>
  </div>
</div>

<footer>安装成功后会在项目根生成 <code>.installed</code>（600 权限），删除它可重新进入向导；/install 将自动 307 跳首页。</footer>
</div>

<script>
const INSTALL_API_PRECHECK = '/install/api/precheck';
const INSTALL_API_GO = '/install/api/go';
const $ = (id) => document.getElementById(id);
function chip(v){
  if(v===true) return '<span class="chip ok">✅ 正常</span>';
  if(v===false) return '<span class="chip err">❌ 异常</span>';
  return '<span class="chip warn">'+v+'</span>';
}
async function loadPrecheck(){
  $('chipInstallState').className = 'chip info';
  try{
    const r = await fetch(INSTALL_API_PRECHECK, {cache:'no-store'});
    const j = await r.json();
    const d = j.data || j;
    // Stat cards
    const py = d.python || {};
    $('pyVer').innerText = py.version || '-';
    $('pyHint').innerHTML = py.ok ? chip(true)+' 满足 ≥'+(py.required||'3.10') : chip(false)+' 请升级 Python';
    $('disk').innerText = (d.disk||{}).free_gb ? d.disk.free_gb+' GB' : '-';
    const dk = d.disk || {};
    $('diskHint').innerHTML = dk.ok ? chip(true)+' ≥'+dk.required_gb+'G' : chip(false)+' 不足';
    $('ram').innerText = d.ram_gb ? d.ram_gb+' GB' : '-';
    $('chipInstallState').innerText = d.installed ? '已安装（可继续用于生成配置）' : '未安装';
    $('chipInstallState').className = 'chip ' + (d.installed ? 'ok' : 'info');
    // Table
    const tb = document.querySelector('#precheckTable tbody');
    const rows = [
      ['Python 版本', (py.version||'-')+'（要求 ≥'+(py.required||'3.10')+'）', chip(py.ok===true)],
      ['磁盘剩余', (dk.free_gb||'-')+'GB，要求 ≥'+(dk.required_gb||5)+'GB', chip(dk.ok===true)],
      ['内存（尽力获取）', d.ram_gb ? d.ram_gb+'GB' : '未装 psutil，获取不到（不致命）', ''],
      ['数据库连接', (d.db||{}).message || '-', chip((d.db||{}).ok)],
      ['Redis 连接', (d.redis||{}).message || '-', chip((d.redis||{}).ok===true?'（不致命）':false) + ' 未装也能跑后端'],
      ['requirements.txt', d.requirements_exists ? '存在' : '缺失', chip(d.requirements_exists)],
      ['前端 dist 构建', (d.frontend_dist_exists ? '存在，可直接访问首页' : '未构建（/docs /health /api 仍可用，前端后续再 build）'), ''],
      ['缺失的 Py 包（安装完成后统一 pip install）', (d.missing_packages||[]).length ? d.missing_packages.join(', ') : '无缺失', (d.missing_packages||[]).length ? '<span class="chip warn">'+(d.missing_packages||[]).length+' 个待装</span>' : '<span class="chip ok">0</span>'],
    ];
    tb.innerHTML = rows.map(r => '<tr><td>'+r[0]+'</td><td>'+r[1]+'</td><td>'+r[2]+'</td></tr>').join('');
  }catch(e){
    alert('环境预检失败：'+e);
  }
}
function toggleMysqlInputs(checked){
  const box = $('mysqlBox');
  if(checked){
    box.style.opacity = '.45'; box.style.pointerEvents = 'none';
  }else{
    box.style.opacity = '1'; box.style.pointerEvents = '';
  }
}
function collectForm(){
  const fd = new FormData(document.getElementById('installForm'));
  const obj = {};
  fd.forEach((v,k)=>{ obj[k] = typeof v === 'string' ? v.trim() : v; });
  // 单 value 的 checkbox：USE_SQLITE
  obj.USE_SQLITE = document.getElementById('USE_SQLITE').checked ? 'true' : 'false';
  // 下拉
  ['APP_ENV','BINANCE_TESTNET','AI_PROVIDER'].forEach(k=>{
    const el = document.getElementById(k); if(el) obj[k]=el.value;
  });
  ['BINANCE_MAIN_API_KEY','BINANCE_MAIN_API_SECRET','BINANCE_BASE_URL','OKX_MAIN_API_KEY','OKX_MAIN_API_SECRET','OKX_MAIN_PASSPHRASE','OKX_TESTNET','OKX_BASE_URL','PROXY_ENABLED','PROXY_HTTP_LIST','AI_API_KEY','AI_API_ENDPOINT','AI_MODEL_NAME','DINGTALK_WEBHOOK','FEISHU_WEBHOOK'].forEach(k=>{
    const el = document.getElementById(k); if(el){ obj[k] = (el.value||'').trim(); }
  });
  return obj;
}
async function submitInstall(e){
  e && e.preventDefault();
  const pwd = document.getElementById('ADMIN_PASSWORD').value || '';
  if(pwd.length < 8){ alert('管理员密码至少 8 位，符合 WordPress 安全标准。'); return false; }
  const btn = $('btnSubmit');
  btn.disabled = true; btn.innerText = '⏳ 正在安装（写 .env → 建库 → 建管理员…）';
  try{
    const body = collectForm();
    const r = await fetch(INSTALL_API_GO, {
      method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body),
    });
    const j = await r.json();
    if(!r.ok){
      const msg = (j && (j.detail || j.message)) || ('HTTP '+r.status);
      throw new Error(msg);
    }
    const d = j.data || j;
    // 第 3 步显示
    $('step3card').style.display='block';
    // 宝塔 Python 项目管理器配置表
    const bt = d.bt_python_project || {};
    const btBody = document.querySelector('#btTable tbody');
    const rows = Object.entries(bt);
    btBody.innerHTML = rows.map(x => '<tr><td>'+x[0]+'</td><td><span class="mono">'+String(x[1]||'').replace(/</g,'&lt;')+'</span></td></tr>').join('');
    // 1 行命令 + Nginx 片段
    $('oneLineCmd').innerText = d.one_line_command || '';
    $('nginxSnippet').innerText = d.nginx_snippet || '';
    // 成功跳到第 3 步
    location.hash = '#step3card';
    $('step3card').scrollIntoView({behavior:'smooth'});
  }catch(err){
    alert('安装失败：'+err.message);
  }finally{
    btn.disabled = false; btn.innerText = '▶️ 运行安装（写入 .env → 建表 → 创建管理员）';
  }
  return false;
}
async function copyText(t){
  try{
    await navigator.clipboard.writeText(t);
    alert('✅ 已复制到剪贴板，到宝塔终端/配置文件粘贴即可。');
  }catch(_){
    const ta = document.createElement('textarea'); ta.value = t; document.body.appendChild(ta); ta.select();
    try{ document.execCommand('copy'); alert('✅ 已复制（浏览器剪贴板未授权，已退回 execCommand 复制）'); }
    catch(e){ alert('复制失败，请手动选中复制。'); }
    document.body.removeChild(ta);
  }
}
window.addEventListener('DOMContentLoaded', () => { loadPrecheck(); toggleMysqlInputs(document.getElementById('USE_SQLITE').checked); });
</script>
</body>
</html>
"""


def _onepress_generate_next_step(project_root: str, backend_port: int = 8000) -> dict:
    """安装完成后生成下一步配置：宝塔 Python 项目管理器字段、1 行启动命令、Nginx 片段"""
    project_root = project_root.rstrip("/").rstrip("\\")
    venv_py = f"{project_root}/.venv/bin/python"
    log_dir = f"{project_root}/logs"
    # 宝塔 Python 项目管理器（BT-Panel Python Project Manager）常见字段
    bt_python_project = {
        "项目名称": "strategy-trade",
        "项目路径": project_root,
        "Python 版本": "Python-3.10（或任意 3.10+）",
        "框架": "FastAPI/uvicorn（手动命令启动）",
        "启动方式": "自定义模块启动",
        "启动模块/文件": "main:app",
        "启动命令（推荐用下方 1 行命令，避免填错）": f"cd {project_root} && (test -d .venv || python3 -m venv .venv) && .venv/bin/pip install -r requirements.txt --index-url https://pypi.tuna.tsinghua.edu.cn/simple && mkdir -p logs && nohup .venv/bin/python -m uvicorn main:app --host 127.0.0.1 --port {backend_port} --log-file {log_dir}/uvicorn.log > {log_dir}/nohup.log 2>&1 & echo $! > logs/uvicorn.pid",
        "运行端口": str(backend_port),
        "绑定域名": "（填你在宝塔添加的站点域名，也可留空在反代里配）",
        "反向代理": "建议在站点配置文件插入下方 Nginx 片段（最稳）",
        "启动用户": "www（避免 root 提权）",
        "守护/Supervisor": "生产用：deploy/supervisor.conf（3 个进程：后端 / celery worker / celery beat）",
    }
    one_line_command = (
        f"cd {project_root} && "
        f"(test -d .venv || python3 -m venv .venv) && "
        f".venv/bin/pip install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple && "
        f".venv/bin/pip install -r requirements.txt --index-url https://pypi.tuna.tsinghua.edu.cn/simple || "
        f".venv/bin/pip install -r requirements.txt && "
        f"mkdir -p logs && "
        f"nohup .venv/bin/python -m uvicorn main:app --host 127.0.0.1 --port {backend_port} "
        f"--log-file {log_dir}/uvicorn.log > {log_dir}/nohup.log 2>&1 & "
        f"echo $! > logs/uvicorn.pid && "
        f"echo '✅ uvicorn PID='$(cat logs/uvicorn.pid)  → 访问 http://127.0.0.1:{backend_port}/health"
    )
    nginx_snippet = (
        f"# ========= 策略交易系统 onepress Nginx 反代片段 =========\n"
        f"# 宝塔：站点设置 → 配置文件 → 把这段插到 server {{ }} 内部（不要删原有 listen/ssl/server_name 段！）\n"
        f"\n"
        f"# 1) 前端 SPA 入口（已用 npm run build 构建 frontend/dist 时才需要；未构建可注释）\n"
        f"location /assets/ {{\n"
        f"    alias {project_root}/frontend/dist/assets/;\n"
        f"    access_log off; expires 7d; add_header Cache-Control \"public, immutable\";\n"
        f"}}\n"
        f"\n"
        f"# 2) 后端 /api /docs /redoc /openapi.json /health 反代到 uvicorn\n"
        f"location ~ ^/(api|docs|redoc|openapi\\.json|health)(/.*)?$ {{\n"
        f"    proxy_pass http://127.0.0.1:{backend_port};\n"
        f"    proxy_http_version 1.1;\n"
        f"    proxy_set_header Host $host;\n"
        f"    proxy_set_header X-Real-IP $remote_addr;\n"
        f"    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n"
        f"    proxy_set_header X-Forwarded-Proto $scheme;\n"
        f"    proxy_read_timeout 300s;\n"
        f"    # WebSocket 升级头（币安/OKX 行情/实时 AI 推送需要）\n"
        f"    proxy_set_header Upgrade $http_upgrade;\n"
        f"    proxy_set_header Connection \"upgrade\";\n"
        f"}}\n"
        f"\n"
        f"# 3) SPA 首页（未构建 dist 时，这段可注释或返回 /docs 引导；构建后正常返回 index.html）\n"
        f"location / {{\n"
        f"    try_files $uri $uri/ /frontend/dist/index.html;\n"
        f"    root {project_root};\n"
        f"    index index.html index.htm;\n"
        f"    # 没构建前端时改成 307 跳 /docs 先看 Swagger：\n"
        f"    # return 307 /docs;\n"
        f"}}\n"
    )
    return {
        "bt_python_project": bt_python_project,
        "one_line_command": one_line_command,
        "nginx_snippet": nginx_snippet,
    }


# ---------- 路由注册 ----------
@app.get("/install", tags=["系统"], include_in_schema=False)
async def install_wizard_page(req: Request):
    """WordPress 式 Web 安装向导（GET 返回页面）"""
    # 已安装：禁止反复打开安装页（避免泄露信息 / 误操作），307 跳首页
    if _onepress_is_installed():
        # 如果用户真要重装，给一个明确操作指引（避免 307 死循环）
        hint = (
            "<!doctype html><title>已安装</title>"
            "<h2>✅ 系统已安装。如需重新进入安装向导：</h2>"
            f"<ol><li>SSH 进入项目根：<code class='mono'>rm -f {_INSTALL_MARK_FILE}</code></li>"
            f"<li>（可选）备份配置：<code class='mono'>cp -a {_INSTALL_ENV_FILE} {_INSTALL_ENV_FILE}.bak.$(date +%s)</code></li>"
            f"<li>浏览器重新访问：<a href='/install'>/install</a></li></ol>"
            f"<hr/><p>现在可以：<a href='/'>/ 站点首页</a> · <a href='/docs'>Swagger 文档 /docs</a> · <a href='/health'>存活探测 /health</a></p>"
        )
        return HTMLResponse(content=hint, status_code=303, headers={"Location": "/docs"})
    return HTMLResponse(content=_INSTALL_HTML)


@app.get("/install/api/precheck", tags=["系统"], include_in_schema=False)
async def install_api_precheck():
    return success(_onepress_precheck())


@app.post("/install/api/go", tags=["系统"], include_in_schema=False, status_code=201)
async def install_api_go(payload: dict[str, Any] = Body(...)):
    """执行安装：校验密码 → 写 .env → 刷 settings → 建表 → 种子数据（用户自定义管理员）→ 写 .installed → 返回下一步配置"""
    if _onepress_is_installed():
        raise HTTPException(
            status_code=409,
            detail=f"已安装，禁止重复安装。如需重装，先删除标记文件：{_INSTALL_MARK_FILE}",
        )

    # 1) 校验管理员账号密码（至少 8 位，字母 + 数字）
    admin_user = (str(payload.get("ADMIN_USERNAME") or "").strip() or "admin")
    admin_pwd = str(payload.get("ADMIN_PASSWORD") or "")
    admin_nick = (str(payload.get("ADMIN_NICKNAME") or "").strip() or "超级管理员")
    if not (4 <= len(admin_user) <= 48):
        raise HTTPException(status_code=400, detail="管理员账号长度：4~48")
    if len(admin_pwd) < 8:
        raise HTTPException(status_code=400, detail="管理员密码至少 8 位（符合 WordPress 安全标准）")
    has_letter = any(ch.isalpha() for ch in admin_pwd)
    has_digit = any(ch.isdigit() for ch in admin_pwd)
    if not (has_letter and has_digit):
        raise HTTPException(status_code=400, detail="管理员密码必须同时包含字母和数字（加符号更安全）")
    # 用户名只允许数字字母下划线中划线
    if not re.fullmatch(r"[A-Za-z0-9_\-@.]+", admin_user):
        raise HTTPException(status_code=400, detail="管理员账号只允许字母 / 数字 / _ - @ .")

    # 2) 生成 .env 并写盘
    if not str(payload.get("APP_SECRET_KEY") or "").strip():
        payload["APP_SECRET_KEY"] = _onepress_rand_secret(64)
    env_lines = _onepress_env_lines_from_payload(payload)
    _onepress_write_env(env_lines)

    # 3) 刷新 settings（确保后续 DB/Redis 用新配置）
    _onepress_reload_settings()

    # 4) 建表 + 种子初始化（管理员密码 = 用户刚才输入的那套）
    stats: dict[str, Any] = {}
    try:
        # 从刚刷新的 settings 拿 DB，重新 import 保证 SQLAlchemy engine 用新 URL
        import importlib, backend.db.base, backend.db.session, backend.models  # noqa: F401
        import backend.db.seed_data as _seed_mod
        importlib.reload(backend.db.session)
        importlib.reload(backend.db.base)
        from backend.db.base import Base as _NewBase
        from backend.db.session import engine as _NewEngine, SessionLocal as _NewSL
        _NewBase.metadata.create_all(bind=_NewEngine)
        logger.info("✅ WordPress 安装向导：表结构已创建/校验")
        # 种子：不传 with_mock_trades=settings.APP_DEBUG 太麻烦，简单处理：开发环境写，生产不写
        import backend.config as _c
        try: _c.get_settings.cache_clear()
        except Exception: pass
        _st = _c.get_settings()
        with _NewSL() as db:
            stats = _seed_mod.ensure_seed_data(
                db,
                with_mock_trades=bool(_st.APP_DEBUG),
                admin_username=admin_user,
                admin_password=admin_pwd,
                admin_nickname=admin_nick,
            )
            db.commit()
        logger.info(f"✅ WordPress 安装向导：种子初始化完成 {stats}")
    except Exception as e:
        logger.exception(f"❌ WordPress 安装向导：建表/种子失败 {e}")
        raise HTTPException(
            status_code=500,
            detail=f"数据库初始化失败：{type(e).__name__}: {e}（请先在 ① 环境预检里通过 DB/Redis 检测，或勾选 SQLite）",
        )

    # 5) 写 .installed 标记 + 元信息
    _onepress_mark_installed({
        "admin_username": admin_user,
        "admin_password_hash": hashlib.sha256(admin_pwd.encode("utf-8")).hexdigest()[:16] + "...(sha256前16位，不存明文)",
        "use_sqlite": str(payload.get("USE_SQLITE") or "").lower() in ("1","true","yes"),
        "db_host": payload.get("DB_HOST",""),
        "db_name": payload.get("DB_NAME",""),
        "app_name": payload.get("APP_NAME") or "TradingStrategySystem",
    })

    # 5.5) WordPress 式收尾：把站点根 index.html（就是我们在 zip 里塞的静态安装入口）重命名到 .bak
    #      避免 Nginx 的 index 指令继续返回静态安装页，盖过后端 SPA / 状态机
    try:
        root_index = BASE_DIR / "index.html"
        if root_index.exists() and root_index.is_file():
            text_bytes = root_index.read_bytes()
            text_snippet = text_bytes[:4096].decode("utf-8", errors="ignore")
            is_our_entry = (
                "onepress-wordpress-entry" in text_snippet
                or "策略交易系统 · 一键安装向导" in text_snippet
                or "Famous 5 分钟" in text_snippet
            )
            if is_our_entry:
                ts = time.strftime("%Y%m%d-%H%M%S")
                bak = BASE_DIR / f"index.html.onepress-entry.bak.{ts}"
                try:
                    shutil.move(str(root_index), str(bak))
                except Exception:
                    shutil.copy2(str(root_index), str(bak))
                    try:
                        root_index.unlink()
                    except Exception:
                        pass
                logger.info(f"WordPress 安装向导完成：已把静态入口 index.html 备份到 {bak.name}，由后端状态机接管 / 路由")
    except Exception as e:
        logger.warning(f"重命名静态安装入口 index.html 失败（非致命）：{type(e).__name__}: {e}")

    # 6) 返回下一步（1 行命令 + 宝塔 Python 项目管理器配置 + Nginx 片段）
    next_step = _onepress_generate_next_step(
        project_root=str(BASE_DIR),
        backend_port=int(str(payload.get("SERVER_PORT") or "8000")),
    )
    return success({
        "ok": True,
        "seed_stats": stats,
        "admin_user": admin_user,
        "env_wrote": str(_INSTALL_ENV_FILE),
        "install_mark": str(_INSTALL_MARK_FILE),
        **next_step,
    })


# ---------- 安装状态机最后一层：让 "/" 未安装自动跳 /install ----------
# （为了不与前端静态托管 / SPA fallback 冲突：统一在下方 SPA fallback 函数内拦截）


@app.get(f"{PREFIX}/me/menu", tags=["系统"])
def menu_info(_user: User = Depends(get_current_user)):
    """前端左侧菜单与权限点（前端启动时拉取）"""
    base_menus = [
        {"key": "dashboard", "title": "数据大屏", "icon": "Monitor"},
        {"key": "exchange", "title": "交易所子账号", "icon": "Wallet"},
        {"key": "strategy", "title": "策略管理", "icon": "DataAnalysis"},
        {"key": "trade", "title": "交易订单", "icon": "TrendCharts"},
        {"key": "positions", "title": "当前持仓", "icon": "PieChart"},
        {"key": "news", "title": "新闻情绪", "icon": "Reading"},
        {"key": "ai", "title": "AI实时分析", "icon": "Cpu"},
        {"key": "backtest", "title": "历史回测", "icon": "Histogram"},
        {"key": "risk", "title": "风控中心", "icon": "Warning"},
        {"key": "reports", "title": "财务报表", "icon": "Document"},
        {"key": "settings", "title": "系统设置", "icon": "Setting"},
    ]
    # 管理员才显示用户管理
    if _user.role == 1:
        base_menus.append({"key": "users", "title": "用户管理", "icon": "User", "adminOnly": True})
    return success({
        "menus": base_menus,
        "role": _user.role,
        "username": _user.username,
        "nickname": _user.nickname,
    })


# ============== 前端静态托管 + 安装状态机拦截 ==============
# 生产环境：前端 npm run build 生成 dist/ 放在：
#   a) 项目根/frontend/dist（推荐，zip 打包就这么放）
#   b) 项目根/../frontend/dist（老仓库结构，兼容保留）
_candidate_frontend = [BASE_DIR / "frontend" / "dist", BASE_DIR.parent / "frontend" / "dist"]
FRONTEND_DIST: Path | None = next((p for p in _candidate_frontend if (p / "index.html").exists()), None)
# 实在没构建 dist，但目录存在且不是空，也给一个候选方便 Nginx alias
if FRONTEND_DIST is None:
    FRONTEND_DIST = next((p for p in _candidate_frontend if p.exists()), None)
# 安装状态拦截（WordPress 式）：未安装时，访问 / 或任何 SPA 路由 → 307 跳 /install
def _onepress_install_redirect_if_needed():
    """需要返回 Response 就返回；否则返回 None 表示继续走原逻辑。"""
    if not _onepress_is_installed():
        return RedirectResponse(url="/install", status_code=307)
    return None


if FRONTEND_DIST is not None and (FRONTEND_DIST / "assets").exists():
    # 静态资源（js/css/imgs）
    app.mount(
        "/assets",
        StaticFiles(directory=str(FRONTEND_DIST / "assets")),
        name="assets",
    )
if FRONTEND_DIST is not None:
    # 其他文件（favicon.ico / robots.txt …）
    app.mount(
        "/static",
        StaticFiles(directory=str(FRONTEND_DIST)),
        name="static",
    )


@app.get("/")
async def serve_index():
    """WordPress 式安装状态机：未安装访问根域名 → 自动 307 跳 /install"""
    rr = _onepress_install_redirect_if_needed()
    if rr is not None:
        return rr
    if FRONTEND_DIST is not None and (FRONTEND_DIST / "index.html").exists():
        return FileResponse(str(FRONTEND_DIST / "index.html"))
    # 前端还没构建 dist 时，给一个引导页（告诉用户 /docs /install 是能用的）
    unbuilt_html = r"""<!doctype html><title>策略交易系统</title><meta charset="utf-8" /><body style="margin:0;padding:40px;font-family:system-ui,-apple-system,Segoe UI,Microsoft YaHei,sans-serif;background:#0b1220;color:#e2e8f0;min-height:100vh">
<div style="max-width:780px;margin:0 auto">
<h1 style="background:linear-gradient(90deg,#60a5fa,#a78bfa,#f472b6);-webkit-background-clip:text;-webkit-text-fill-color:transparent;font-size:30px">📈 策略交易系统</h1>
<p style="color:#94a3b8">后端已启动 ✅ &nbsp; 前端 <code style="background:#0b1120;border:1px solid #334155;padding:2px 8px;border-radius:6px">frontend/dist</code> 未构建（不影响 /docs /api /health /install 使用）。</p>
<hr style="border:none;border-top:1px dashed #334155;margin:20px 0" />
<h3>常用入口</h3>
<ul style="line-height:2">
  <li><a style="color:#93c5fd" href="/install">/install</a> —— WordPress 式一键安装向导（首次部署必走）</li>
  <li><a style="color:#93c5fd" href="/docs">/docs</a> —— Swagger 接口文档（登录 / 测接口 / 生成 Token）</li>
  <li><a style="color:#93c5fd" href="/health">/health</a> —— 存活探测（Nginx / 宝塔探针）</li>
  <li><a style="color:#93c5fd" href="/api/v1/auth/login">/api/v1/auth/login</a> —— 登录接口</li>
</ul>
<p style="color:#94a3b8">构建前端（可选）：在 <code>frontend/</code> 目录执行 <code>npm install &amp;&amp; npm run build</code>，生成的 dist 放 <code>项目根/frontend/dist</code>，刷新此页即可正常看到 SPA 首页。</p>
</div></body>"""
    return HTMLResponse(content=unbuilt_html)


# 兼容 SPA 路由刷新（排除 /api /docs /health /install 等后端路径）
@app.get("/{full_path:path}")
async def spa_fallback(full_path: str, request = None):
    # 先处理安装状态：未安装 -> 跳 /install（但 /install 自身、/health、/docs、/api 等保留前缀不能跳，否则 307 死循环）
    reserved_prefixes = ("api", "docs", "redoc", "openapi.json", "health", "assets", "static", "install")
    first = full_path.split("/", 1)[0]
    if first in reserved_prefixes:
        # 交给其他路由处理；如果没人处理，返回 404，不要给前端 index.html
        from fastapi import HTTPException as _HTTPEx
        raise _HTTPEx(status_code=404, detail="Not Found")
    rr = _onepress_install_redirect_if_needed()
    if rr is not None:
        return rr
    if FRONTEND_DIST is None:
        # 没构建前端，直接走根引导
        from fastapi.responses import RedirectResponse as _RR
        return _RR(url="/", status_code=307)
    candidates = [
        FRONTEND_DIST / full_path,
        FRONTEND_DIST / f"{full_path}.html",
        FRONTEND_DIST / "index.html",
    ]
    for c in candidates:
        if c.exists() and c.is_file():
            return FileResponse(str(c))
    return FileResponse(str(FRONTEND_DIST / "index.html"))


# ============== 开发时直接运行 ==============
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=settings.SERVER_HOST,
        port=settings.SERVER_PORT,
        reload=settings.APP_DEBUG,
        workers=1 if settings.APP_DEBUG else 4,
        log_level="debug" if settings.APP_DEBUG else "info",
    )
