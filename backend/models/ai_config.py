"""
AI 全局配置表（单例：永远只有 id=1 一行）
支持热生效：管理员 PUT /ai/config 写入 DB 后立即生效，无需重启服务
API Key 使用 backend.core.security 加密后落库（DB 无明文）
"""
from sqlalchemy import Column, Integer, String, SmallInteger, Text, DateTime, ForeignKey
from datetime import datetime

from backend.db.base import Base


class AIConfig(Base):
    """
    AI 供应商与密钥配置（全局单行）
    推荐所有写入都走 ai_config_service.upsert_current() 保证单例约束
    """

    SINGLETON_ID = 1

    # 供应商常量（与 AIAnalysisRecord 的 PROVIDER_* 对齐）
    PROVIDER_OPENAI = 1
    PROVIDER_ANTHROPIC = 2
    PROVIDER_CUSTOM = 3      # OneAPI / SiliconFlow / DeepSeek / Qwen / Doubao 等 OpenAI 兼容
    PROVIDER_LOCAL = 4       # Ollama / vLLM 本地部署

    PROVIDER_NAME_MAP = {
        PROVIDER_OPENAI: "openai",
        PROVIDER_ANTHROPIC: "anthropic",
        PROVIDER_CUSTOM: "custom",
        PROVIDER_LOCAL: "local",
    }
    NAME_PROVIDER_MAP = {v: k for k, v in PROVIDER_NAME_MAP.items()}

    provider = Column(SmallInteger, default=PROVIDER_CUSTOM, comment="供应商: 1-OpenAI 2-Anthropic 3-Custom 4-Local")
    model_name = Column(String(128), default="gpt-4o", comment="模型名，如 gpt-4o / deepseek-chat / qwen-plus")

    # OpenAI 兼容 Endpoint（custom/local 时必填；openai 时可留空走官方）
    api_endpoint = Column(String(512), default="", comment="API端点，OpenAI兼容协议填 /v1 或根URL")
    # API Key：加密后密文，绝不明文存（使用 backend.core.security.encrypt_api_key）
    api_key_encrypted = Column(Text, default="", comment="加密后的API Key密文")

    # 行为参数
    temperature = Column(Integer, default=3, comment="生成温度(0-10)，存整数/10：3 → 0.3")
    max_tokens = Column(Integer, default=800, comment="最大输出Token")
    request_timeout_sec = Column(Integer, default=30, comment="请求超时秒数")
    max_retries = Column(SmallInteger, default=2, comment="失败自动重试次数(不含首次)")

    # 审计
    updated_by = Column(Integer, ForeignKey("users.id"), nullable=True, comment="最后修改管理员ID")
    updated_username = Column(String(64), default="", comment="冗余最后修改人")
    last_verified_at = Column(DateTime, nullable=True, comment="最后一次连通性验证通过时间")
    last_error = Column(String(512), default="", comment="最后一次连通性验证错误")

    # ===== 工具方法 =====
    @property
    def provider_name(self) -> str:
        return self.PROVIDER_NAME_MAP.get(int(self.provider or 3), "custom")

    @classmethod
    def name_to_provider(cls, name: str) -> int:
        return cls.NAME_PROVIDER_MAP.get((name or "").strip().lower(), cls.PROVIDER_CUSTOM)
