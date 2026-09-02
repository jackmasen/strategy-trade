"""
模型模块聚合导出
所有ORM模型在此import，确保 Alembic/SQLAlchemy 能扫描到
"""
from backend.db.base import Base

# 用户
from backend.models.user import User, OperationLog

# 交易所
from backend.models.exchange import ExchangeAccount

# 策略 & 评分
from backend.models.strategy import StrategyConfig, ScoreRecord

# 交易
from backend.models.trade import TradeOrder, TradePosition

# 分析/新闻/风控/回测/报表/进化
from backend.models.analytics import (
    NewsArticle,
    AIAnalysisRecord,
    RiskEventLog,
    BacktestRun,
    QuantSignalRecord,
    FalseSignalPattern,
    FactorPerformanceStat,
    EvolutionProposal,
    EvolutionRun,
    DailyFinancialReport,
    WeeklyFinancialReport,
    MonthlyFinancialReport,
)

# AI 全局配置
from backend.models.ai_config import AIConfig

# 系统全局配置
from backend.models.system_config import SystemConfig

# AI多API故障转移
from backend.models.ai_api_key import AiApiKey

# 系统管理（备份/更新/健康检测）
from backend.models.system_admin import SystemUpdateRecord, SystemBackupRecord, SystemHealthReport

# K线布局
from backend.models.kline_layout import KlineLayout

__all__ = [
    "Base",
    "User",
    "OperationLog",
    "ExchangeAccount",
    "StrategyConfig",
    "ScoreRecord",
    "TradeOrder",
    "TradePosition",
    "NewsArticle",
    "AIAnalysisRecord",
    "RiskEventLog",
    "BacktestRun",
    "DailyFinancialReport",
    "WeeklyFinancialReport",
    "MonthlyFinancialReport",
    "AIConfig",
    "SystemConfig",
    "AiApiKey",
    "SystemUpdateRecord",
    "SystemBackupRecord",
    "SystemHealthReport",
    "KlineLayout",
]
