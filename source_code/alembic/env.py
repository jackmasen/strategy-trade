"""
Alembic 迁移环境配置
从 backend.config 动态读取数据库 URI，确保与应用配置一致
"""
from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context

import sys
import os

# 将项目根目录加入 sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.config import get_settings
from backend.db.base import Base

# 导入所有模型，确保 Alembic 能 autogenerate 检测到
from backend.models.user import *  # noqa
from backend.models.exchange import *  # noqa
from backend.models.strategy import *  # noqa
from backend.models.trade import *  # noqa
from backend.models.analytics import *  # noqa
from backend.models.ai_config import *  # noqa

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 动态设置数据库 URI（覆盖 alembic.ini 中的静态配置）
settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.SQLALCHEMY_DATABASE_URI)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """离线模式：生成 SQL 脚本"""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """在线模式：直接执行迁移"""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
