"""
全局配置加载模块
统一从环境变量 / .env 文件读取配置，避免硬编码
"""
from functools import lru_cache
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    """应用配置映射"""

    # ---------- 基础 ----------
    APP_NAME: str = "TradingStrategySystem"
    APP_ENV: str = Field(default="development", pattern="^(development|staging|production)$")
    APP_DEBUG: bool = False
    APP_SECRET_KEY: str = "please_change_me"
    API_PREFIX: str = "/api/v1"

    SERVER_HOST: str = "0.0.0.0"
    SERVER_PORT: int = 8000

    # CORS 允许来源：生产环境应改为具体域名（逗号分隔），开发留 * 即可
    CORS_ALLOW_ORIGINS: str = "*"
    # 是否启用 Celery worker/beat 处理交易类定时任务（平仓巡检/策略自动执行/新闻采集）。
    # False（默认）：由 main.py 内置 APScheduler 兜底执行，无需 Redis/Celery 即可闭环。
    # True：交给 Celery 处理，APScheduler 跳过与之重叠的任务避免重复触发。
    CELERY_ENABLED: bool = False

    # ---------- MySQL ----------
    DB_HOST: str = "127.0.0.1"
    DB_PORT: int = 3306
    DB_USER: str = "root"
    DB_PASSWORD: str = ""
    DB_NAME: str = "trading_system"
    DB_CHARSET: str = "utf8mb4"
    # 本地无 MySQL 时可填 sqlite:///./trading_system.db 快速跑通；生产强制使用 MySQL
    DB_SQLITE_FALLBACK: str = ""

    @property
    def SQLALCHEMY_DATABASE_URI(self) -> str:
        # 优先：显式 sqlite fallback（运维模式/离线/无MySQL）
        if self.DB_SQLITE_FALLBACK:
            return self.DB_SQLITE_FALLBACK
        return (
            f"mysql+pymysql://{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}?charset={self.DB_CHARSET}"
        )

    # ---------- Redis ----------
    REDIS_HOST: str = "127.0.0.1"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: Optional[str] = None
    REDIS_DB: int = 0
    REDIS_DB_CELERY: int = 1

    @property
    def REDIS_URL(self) -> str:
        auth = f":{self.REDIS_PASSWORD}@" if self.REDIS_PASSWORD else ""
        return f"redis://{auth}{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    @property
    def CELERY_BROKER_URL(self) -> str:
        auth = f":{self.REDIS_PASSWORD}@" if self.REDIS_PASSWORD else ""
        return f"redis://{auth}{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB_CELERY}"

    @property
    def CELERY_RESULT_BACKEND(self) -> str:
        auth = f":{self.REDIS_PASSWORD}@" if self.REDIS_PASSWORD else ""
        # 使用 Redis DB 2 作为结果后端（与 Broker 分开）
        db = self.REDIS_DB_CELERY + 1 if self.REDIS_DB_CELERY < 15 else 1
        return f"redis://{auth}{self.REDIS_HOST}:{self.REDIS_PORT}/{db}"

    # ---------- JWT ----------
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440  # 24h
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # ---------- 币安 ----------
    BINANCE_MAIN_API_KEY: str = ""
    BINANCE_MAIN_API_SECRET: str = ""
    BINANCE_TESTNET: bool = True
    BINANCE_BASE_URL: str = "https://testnet.binancefuture.com"

    # ---------- OKX ----------
    OKX_MAIN_API_KEY: str = ""
    OKX_MAIN_API_SECRET: str = ""
    OKX_MAIN_PASSPHRASE: str = ""
    OKX_TESTNET: bool = True
    OKX_BASE_URL: str = "https://www.okx.com"

    # ---------- AI ----------
    AI_PROVIDER: str = "custom"  # openai / anthropic / custom / local
    AI_API_KEY: str = ""
    AI_API_ENDPOINT: str = ""
    AI_MODEL_NAME: str = "gpt-4o"

    # ---------- 新闻 ----------
    NEWSAPI_KEY: str = ""
    CRYPTOPANIC_TOKEN: str = ""
    # FRED：美联储圣路易斯分行开放 API（CPI/NFP/失业率/美债收益率等）。免费申请。
    FRED_API_KEY: str = ""
    # EIA：美国能源信息署开放 API（每周 WTI 原油/汽油库存、原油产量等）。免费申请。
    EIA_API_KEY: str = ""
    # Alpha Vantage：News & Sentiment API（加密/外汇/商品新闻+AI情绪分）。免费25次/天。
    # 申请：https://www.alphavantage.co/support/#api-key
    ALPHAVANTAGE_API_KEY: str = ""
    # NewsData.io：聚合新闻 API（200篇/天免费，支持关键词+分类+语言过滤）。
    # 申请：https://newsdata.io/register
    NEWSDATA_API_KEY: str = ""
    # Miniflux：自托管 RSS 聚合器（配合 RSSHub 可扩展到1000+新闻源，全部免费）。
    # 部署：Docker 一键部署，详见 deploy/ 目录。留空则跳过此源。
    MINIFLUX_URL: str = ""           # 如 http://127.0.0.1:8080 或 https://news.yourdomain.com
    MINIFLUX_API_KEY: str = ""       # Miniflux 设置页生成的 API Key
    MINIFLUX_USERNAME: str = ""      # 或用用户名密码认证（二选一）
    MINIFLUX_PASSWORD: str = ""

    # ---------- 代理池（访问美国新闻源 / 交易所 API 自动用，全部可留空=直连） ----------
    # 1) 最快：直接写固定代理列表，逗号分隔，格式 http://[user:pass@]host:port 或 socks5://...
    PROXY_HTTP_LIST: str = ""
    # 2) 从 URL 拉代理（返回一行一个代理或 JSON 数组），留空跳过
    PROXY_PROVIDER_URL: str = ""
    # 代理拉取间隔（分钟）。不填默认 20 分钟
    PROXY_REFRESH_MINUTES: int = 20
    # 代理默认 TTL（分钟）：从分配时刻算，超过这个时间就不分配新任务；留空默认 25 分钟
    PROXY_DEFAULT_TTL_MINUTES: int = 25
    # 代理获取超时（秒）：拿不到代理就自动降级到直连，避免卡死；留空默认 8 秒
    PROXY_FETCH_TIMEOUT_SECONDS: int = 8
    # 是否启用代理：false 时所有请求直连
    PROXY_ENABLED: bool = True

    # ---------- 告警 ----------
    DINGTALK_WEBHOOK: str = ""
    FEISHU_WEBHOOK: str = ""
    SMTP_HOST: str = ""
    SMTP_PORT: int = 465
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_TO: str = ""

    # ---------- GitHub 更新 ----------
    # 格式: owner/repo，如 "yourname/strategy-trade"
    GITHUB_REPO: str = ""
    # GitHub Token（可选，私有仓库或提高 API 限流用）
    GITHUB_TOKEN: str = ""

    # ---------- 风控默认 ----------
    DEFAULT_MAX_SINGLE_DRAWDOWN: float = 2.0
    DEFAULT_DAILY_MAX_LOSS: float = 5.0
    DEFAULT_MAX_POSITION_COUNT: int = 3
    DEFAULT_TOTAL_POSITION_RATIO: float = 50.0
    DEFAULT_SCORE_THRESHOLD: float = 5.0
    DEFAULT_LEVERAGE_MIN: int = 3
    DEFAULT_LEVERAGE_MAX: int = 10

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """全局单例获取配置（带缓存）"""
    return Settings()


def clear_settings_cache() -> None:
    """清除配置缓存，使后续 get_settings() 重新从 .env 读取。
    用于 APP_SECRET_KEY 等配置热变更后无需重启即可生效。"""
    get_settings.cache_clear()
