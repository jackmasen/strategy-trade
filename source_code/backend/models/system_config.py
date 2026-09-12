"""
系统全局配置表（key-value 模式）
存储 SMTP、新闻API、通用参数等所有系统级配置
所有敏感字段（密码、API Key）加密后存储
"""
from sqlalchemy import Column, Integer, String, Text, DateTime
from datetime import datetime

from backend.db.base import Base


class SystemConfig(Base):
    """
    系统配置表（key-value模式）
    支持分类存储，前端按分类读写
    """

    __tablename__ = "system_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    config_key = Column(String(128), unique=True, index=True, comment="配置键名")
    config_value = Column(Text, default="", comment="配置值(JSON字符串或纯文本)")
    config_type = Column(String(32), default="string", comment="值类型: string/int/bool/json/encrypted")
    category = Column(String(64), default="general", comment="分类: general/exchange/news/notify/ai")
    description = Column(String(256), default="", comment="配置说明")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, comment="最后更新时间")
    updated_by = Column(Integer, nullable=True, comment="最后修改人ID")
