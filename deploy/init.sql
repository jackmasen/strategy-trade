-- ==========================================================
-- 策略交易系统 - 数据库初始化（MySQL 8.0+）
-- 使用方法二选一：
--   A) 推荐：系统启动时 SQLAlchemy 自动建表（main.py lifespan 已集成）
--   B) 手动：先执行本文件创建数据库，再启动后端 ORM 自动建表
-- ==========================================================

-- 1. 创建数据库（若不存在）
CREATE DATABASE IF NOT EXISTS `trading_system`
    DEFAULT CHARACTER SET utf8mb4
    DEFAULT COLLATE utf8mb4_unicode_ci;

USE `trading_system`;

-- ==========================================================
--  说明：以下 10 张表由 SQLAlchemy 自动生成
--  （main.py lifespan 中执行 Base.metadata.create_all）
--  本 SQL 仅记录表名、字段与 ORM 模型对齐关系，供人工审核：
--
--   users                 对应 backend.models.user.User
--   sys_operation_log     对应 backend.models.user.OperationLog
--   exchange_account      对应 backend.models.exchange.ExchangeAccount
--   strategy_config       对应 backend.models.strategy.StrategyConfig
--   score_record          对应 backend.models.strategy.ScoreRecord
--   trade_order           对应 backend.models.trade.TradeOrder
--   trade_position        对应 backend.models.trade.TradePosition
--   news_article          对应 backend.models.analytics.NewsArticle
--   ai_analysis_record    对应 backend.models.analytics.AIAnalysisRecord
--   risk_event_log        对应 backend.models.analytics.RiskEventLog
--   backtest_run          对应 backend.models.analytics.BacktestRun
--   daily_fin_report      对应 backend.models.analytics.DailyFinancialReport
--   weekly_fin_report     对应 backend.models.analytics.WeeklyFinancialReport
--   monthly_fin_report    对应 backend.models.analytics.MonthlyFinancialReport
--
--  执行完本 SQL 创建数据库后，请：
--    1) 编辑项目根目录 .env，填写 DB_* / REDIS_* / 交易所 API Key
--    2) 启动后端：uvicorn main:app --host 0.0.0.0 --port 8000
--    3) 首次启动会自动建表 + 写入 seed_data：
--         admin / Admin@2024   (超级管理员)
--         trader / Trader@2024 (运营账号)
-- ==========================================================
