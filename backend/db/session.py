"""
数据库会话管理
提供同步+异步两种 Engine/Session 工厂，以及 FastAPI 依赖注入
"""
from __future__ import annotations

from typing import Generator, AsyncGenerator
from urllib.parse import urlparse

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.ext.asyncio import (
    create_async_engine,
    AsyncSession,
    async_sessionmaker,
)
from contextlib import contextmanager, asynccontextmanager

from backend.config import get_settings

settings = get_settings()


# ============== 同步（主流用法，简单稳定） ==============
_db_url = settings.SQLALCHEMY_DATABASE_URI
_parsed_db = urlparse(_db_url)
_is_sqlite = _parsed_db.scheme.startswith("sqlite")

if _is_sqlite:
    # SQLite: 禁用 pool_pre_ping（不支持）+ NullPool 避免多线程写冲突 + check_same_thread=False
    from sqlalchemy.pool import NullPool
    engine = create_engine(
        _db_url,
        poolclass=NullPool,
        echo=settings.APP_DEBUG,
        future=True,
        connect_args={"check_same_thread": False},
    )
else:
    engine = create_engine(
        _db_url,
        pool_pre_ping=True,
        pool_size=20,
        max_overflow=50,
        pool_recycle=3600,
        echo=settings.APP_DEBUG,
        future=True,
    )

# 同步引擎别名（health_check.py 用 engine_sync）
engine_sync = engine

SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
    class_=Session,
)


def get_db() -> Generator[Session, None, None]:
    """FastAPI 同步依赖注入：每个请求一个 Session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def db_session_scope():
    """非请求上下文（Celery/脚本）使用的 Session 上下文管理器"""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# 对外别名，Celery/脚本里 `from backend.db.session import session_maker as sm; sm() as db:`
# 注意：必须在 db_session_scope 定义之后再赋值（避免前向引用 NameError）
session_maker = db_session_scope


# ============== 异步（高并发接口可选） ==============
# 把 pymysql 连接串替换成 asyncmy（如使用异步需额外安装 asyncmy）
# SQLite 场景：异步不支持 asyncmy 前缀转换，直接沿用同步 sqlite URL（aio-sqlite 可选驱动），
# 这样即使异步场景也能启动，不会因 scheme 非法导致 API 起不来。
def _async_db_url() -> str:
    if _is_sqlite:
        return _db_url
    return settings.SQLALCHEMY_DATABASE_URI.replace("mysql+pymysql", "mysql+asyncmy")


_async_url = _async_db_url()
if _is_sqlite:
    # SQLite 异步：SQLAlchemy 原生不提供 aiosqlite 驱动，我们保持同步即可
    # 这里做一个"可启动"兜底：复用同步 engine（使用同一个数据库文件）
    # 但 async_sessionmaker 需要 async engine；若不可用则构造一个假的 async engine
    # 会在真正调用时报错，但我们 API 默认用同步（get_db），不影响启动。
    # 更稳妥方案：如果检测到 asyncmy 未装且是 sqlite，直接退回同步空实现
    try:
        from sqlalchemy.ext.asyncio import create_async_engine as _create_async
        async_engine = _create_async(
            _async_url,
            echo=settings.APP_DEBUG,
        )
    except Exception:
        # 终极兜底：仍然创建一个同步 engine（避免 import 时 NameError）；
        # 实际 API 只要不走 get_async_db 就 OK
        async_engine = engine  # type: ignore
else:
    async_engine = create_async_engine(
        _async_url,
        pool_pre_ping=True,
        pool_size=20,
        max_overflow=50,
        pool_recycle=3600,
        echo=settings.APP_DEBUG,
    )

AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    expire_on_commit=False,
    class_=AsyncSession,
)


async def get_async_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 异步依赖注入"""
    async with AsyncSessionLocal() as session:
        yield session
