"""
AI多API故障转移模型
支持配置多个AI API Key，按优先级自动切换
"""
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, func
from backend.db.base import Base


class AiApiKey(Base):
    __tablename__ = "ai_api_keys"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(64), nullable=False, comment="名称（主用/备用1/备用2）")
    provider = Column(String(32), default="custom", comment="供应商: openai/anthropic/custom/local")
    model_name = Column(String(128), default="gpt-4o", comment="模型名称")
    api_endpoint = Column(String(256), default="", comment="API地址")
    api_key_encrypted = Column(Text, default="", comment="API Key(加密)")
    priority = Column(Integer, default=10, comment="优先级(数字越小越优先)")
    status = Column(String(16), default="active", comment="active/failed/disabled")
    fail_count = Column(Integer, default=0, comment="连续失败次数")
    last_checked = Column(DateTime, nullable=True, comment="最后检测时间")
    last_error = Column(Text, default="", comment="上次错误信息")
    temperature = Column(Integer, default=3, comment="温度(0-10)")
    max_tokens = Column(Integer, default=800, comment="最大Token")
    request_timeout_sec = Column(Integer, default=30, comment="请求超时(秒)")
    max_retries = Column(Integer, default=2, comment="最大重试次数")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
