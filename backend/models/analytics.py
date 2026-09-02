"""
新闻采集 / AI分析 / 风控日志 / 回测 / 报表 / 自我进化 模型
"""
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, SmallInteger, DECIMAL, Text,
    ForeignKey, JSON, DateTime, Index, Float, Boolean
)
from sqlalchemy.orm import relationship

from backend.db.base import Base


class NewsArticle(Base):
    """新闻文章表（原始采集数据）"""

    SENTIMENT_POSITIVE = 1
    SENTIMENT_NEUTRAL = 0
    SENTIMENT_NEGATIVE = -1

    SOURCE_NEWSAPI = 1
    SOURCE_CRYPTOPANIC = 2
    SOURCE_JIN10 = 3       # 金十数据
    SOURCE_REDDIT = 4
    SOURCE_TWITTER = 5
    SOURCE_CUSTOM = 99

    # —— 新增：国际主流媒体 ——
    SOURCE_COINDESK = 10        # CoinDesk（加密媒体标杆）
    SOURCE_COINTELEGRAPH = 11   # CoinTelegraph
    SOURCE_THEBLOCK = 12        # The Block
    SOURCE_REUTERS = 20         # 路透社（宏观+大宗商品）
    SOURCE_BLOOMBERG = 21       # 彭博（美联储/机构）
    SOURCE_CNBC = 22            # CNBC（美股+能源）
    SOURCE_MARKETWATCH = 23     # MarketWatch（WSJ旗下）
    SOURCE_WSJ = 24             # 华尔街日报
    SOURCE_OILPRICE = 30        # OilPrice.com（原油）
    SOURCE_EIA = 31             # 美国能源信息署 EIA Weekly
    SOURCE_IEA = 32             # 国际能源署
    SOURCE_KITCO = 33           # Kitco（黄金/贵金属权威）
    SOURCE_FRED = 40            # 圣路易斯联储 FRED
    SOURCE_FOMC = 41            # FOMC 美联储声明/会议纪要
    SOURCE_CME_FEDWATCH = 42    # CME FedWatch 利率概率
    SOURCE_ALPHAVANTAGE = 50   # Alpha Vantage News & Sentiment
    SOURCE_NEWSDATA = 51       # NewsData.io 聚合新闻

    # —— 新增：中文财经媒体 ——
    SOURCE_CLS = 60            # 财联社电报
    SOURCE_BISHIJIE = 61       # 币世界
    SOURCE_WALLSTREETCN = 62   # 华尔街见闻
    SOURCE_DECRYPT = 63        # Decrypt（加密英文）
    SOURCE_DAILYFX = 64       # DailyFX（宏观经济/非农）
    SOURCE_INVESTING = 65     # Investing.com

    SOURCE_NAME_MAP = {
        SOURCE_NEWSAPI: "NewsAPI", SOURCE_CRYPTOPANIC: "CryptoPanic",
        SOURCE_JIN10: "金十数据", SOURCE_REDDIT: "Reddit",
        SOURCE_TWITTER: "Twitter/X", SOURCE_CUSTOM: "自定义",
        SOURCE_COINDESK: "CoinDesk", SOURCE_COINTELEGRAPH: "CoinTelegraph",
        SOURCE_THEBLOCK: "The Block", SOURCE_REUTERS: "Reuters",
        SOURCE_BLOOMBERG: "Bloomberg", SOURCE_CNBC: "CNBC",
        SOURCE_MARKETWATCH: "MarketWatch", SOURCE_WSJ: "WSJ",
        SOURCE_OILPRICE: "OilPrice.com", SOURCE_EIA: "EIA",
        SOURCE_IEA: "IEA", SOURCE_KITCO: "Kitco",
        SOURCE_FRED: "FRED", SOURCE_FOMC: "FOMC",
        SOURCE_CME_FEDWATCH: "CME FedWatch",
        SOURCE_ALPHAVANTAGE: "Alpha Vantage",
        SOURCE_NEWSDATA: "NewsData.io",
        SOURCE_CLS: "财联社", SOURCE_BISHIJIE: "币世界",
        SOURCE_WALLSTREETCN: "华尔街见闻", SOURCE_DECRYPT: "Decrypt",
        SOURCE_DAILYFX: "DailyFX", SOURCE_INVESTING: "Investing.com",
    }

    __table_args__ = (
        Index("idx_published", "published_at"),
        Index("idx_symbol_sentiment", "related_symbols", "sentiment"),
    )

    source = Column(SmallInteger, default=99, comment="数据源: 1-NewsAPI 2-CryptoPanic 3-金十 ...")
    source_id = Column(String(255), default="", comment="原始来源ID(用于去重)")
    title = Column(String(512), nullable=False, comment="新闻标题")
    summary = Column(Text, default="", comment="摘要/内容")
    content = Column(Text, default="", comment="完整正文")
    url = Column(String(1024), default="", comment="原文链接")
    image_url = Column(String(1024), default="", comment="配图")
    author = Column(String(128), default="", comment="作者")
    source_name = Column(String(128), default="", comment="来源名称(如 Reuters)")

    # 分类与标签
    category = Column(String(64), default="", comment="分类: macro/regulation/exchange/onchain")
    tags = Column(JSON, default=list, comment="标签列表")
    related_symbols = Column(JSON, default=list, comment="关联币种: [BTC,ETH,...]")

    # 情绪分析
    sentiment = Column(SmallInteger, default=0, comment="情绪: 1正面 0中性 -1负面")
    sentiment_score = Column(Float, default=0, comment="情绪分数(-1.0 ~ 1.0)")
    sentiment_keywords = Column(JSON, default=list, comment="命中的关键词")
    impact_level = Column(SmallInteger, default=1, comment="影响级别: 1-低 2-中 3-高 4-重大")

    published_at = Column(DateTime, index=True, comment="发布时间")
    analyzed_at = Column(DateTime, nullable=True, comment="分析处理时间")
    is_hot = Column(Boolean, default=False, comment="是否热点新闻")


class AIAnalysisRecord(Base):
    """AI 分析调用记录"""

    PROVIDER_OPENAI = 1
    PROVIDER_ANTHROPIC = 2
    PROVIDER_CUSTOM = 3
    PROVIDER_LOCAL = 4

    __table_args__ = (
        Index("idx_symbol_time", "symbol", "created_at"),
    )

    user_id = Column(Integer, nullable=True, index=True, comment="调用用户(手动调用时)")
    provider = Column(SmallInteger, default=3, comment="供应商")
    model_name = Column(String(128), default="", comment="模型名称")

    analysis_type = Column(String(64), default="score",
                           comment="分析类型: score-评分/紧急持仓分析/新闻解读/策略优化")
    symbol = Column(String(32), nullable=True, index=True, comment="关联品种")
    timeframe = Column(String(16), default="", comment="关联周期")

    prompt_snapshot = Column(Text, default="", comment="提示词快照(脱敏)")
    input_data = Column(JSON, default=dict, comment="输入数据(指标/新闻/持仓快照)")

    ai_response_raw = Column(Text, default="", comment="AI原始回复")
    ai_score = Column(Float, nullable=True, comment="AI给出的分数(0-3或0-10)")
    ai_direction = Column(String(8), default="neutral", comment="AI建议方向")
    ai_reason = Column(Text, default="", comment="AI分析理由")

    tokens_prompt = Column(Integer, default=0, comment="提示词消耗Token")
    tokens_completion = Column(Integer, default=0, comment="输出消耗Token")
    cost_usd = Column(Float, default=0, comment="调用成本(美元)")
    latency_ms = Column(Integer, default=0, comment="耗时(毫秒)")
    success = Column(Boolean, default=True, comment="是否调用成功")
    error_msg = Column(String(1024), default="", comment="错误信息")


class RiskEventLog(Base):
    """风控事件日志"""

    TYPE_SINGLE_DRAWDOWN = 1  # 单笔回撤超限
    TYPE_DAILY_LOSS = 2       # 日亏损超限
    TYPE_CONSECUTIVE_LOSS = 3 # 连续亏损
    TYPE_POSITION_LIMIT = 4   # 持仓数超限
    TYPE_API_ERROR = 5        # 交易所API异常
    TYPE_ABNORMAL_PRICE = 6   # 异常行情(插针)
    TYPE_FORCE_CLOSE = 7      # 强制平仓
    TYPE_COOLDOWN_START = 8   # 进入冷静期
    TYPE_COOLDOWN_END = 9     # 冷静期结束

    SEVERITY_INFO = 1
    SEVERITY_WARN = 2
    SEVERITY_DANGER = 3

    __table_args__ = (
        Index("idx_type_time", "event_type", "created_at"),
        Index("idx_risk_acc_time", "exchange_account_id", "created_at"),
    )

    user_id = Column(Integer, index=True, comment="用户ID")
    exchange_account_id = Column(Integer, nullable=True, index=True, comment="交易所子账号ID")
    strategy_id = Column(Integer, nullable=True, index=True, comment="策略ID")
    symbol = Column(String(32), nullable=True, index=True, comment="关联品种")
    order_id = Column(Integer, nullable=True, index=True, comment="关联订单ID")
    position_id = Column(Integer, nullable=True, index=True, comment="关联持仓ID")

    event_type = Column(SmallInteger, index=True, comment="风控事件类型")
    severity = Column(SmallInteger, default=1, comment="严重程度: 1-提醒 2-警告 3-危险")

    title = Column(String(255), comment="事件标题")
    detail = Column(Text, default="", comment="事件详情")
    snapshot = Column(JSON, default=dict, comment="当时数据快照")

    action_taken = Column(SmallInteger, default=0, comment="采取的动作: 0-仅记录 1-撤单 2-平仓 3-暂停策略")
    notified = Column(Boolean, default=False, comment="是否已推送通知")


class BacktestRun(Base):
    """回测任务表"""

    STATUS_PENDING = 0
    STATUS_RUNNING = 1
    STATUS_SUCCESS = 2
    STATUS_FAILED = 3

    __table_args__ = (
        Index("idx_user_time", "user_id", "created_at"),
    )

    user_id = Column(Integer, index=True, comment="用户ID")
    strategy_id = Column(Integer, ForeignKey("strategy_configs.id", ondelete="SET NULL"),
                         nullable=True, comment="基于的策略ID")
    run_name = Column(String(255), default="", comment="回测命名")

    # 回测参数快照
    symbols = Column(JSON, default=list, comment="回测品种")
    timeframe = Column(String(32), default="4h", comment="回测周期")
    date_start = Column(DateTime, comment="回测开始日期")
    date_end = Column(DateTime, comment="回测结束日期")
    initial_capital = Column(DECIMAL(18, 8), default=10000, comment="初始资金(USDT)")
    fee_rate = Column(Float, default=0.04, comment="手续费率(%)")
    slippage = Column(Float, default=0.05, comment="滑点(%)")
    param_snapshot = Column(JSON, default=dict, comment="策略参数完整快照")

    # 回测结果指标
    status = Column(SmallInteger, default=0, index=True, comment="状态")
    progress = Column(SmallInteger, default=0, comment="进度百分比0-100")
    total_return_pct = Column(Float, nullable=True, comment="总收益率(%)")
    annual_return_pct = Column(Float, nullable=True, comment="年化收益率(%)")
    max_drawdown_pct = Column(Float, nullable=True, comment="最大回撤(%)")
    sharpe_ratio = Column(Float, nullable=True, comment="夏普比率")
    sortino_ratio = Column(Float, nullable=True, comment="索提诺比率")
    calmar_ratio = Column(Float, nullable=True, comment="卡玛比率")
    win_rate = Column(Float, nullable=True, comment="胜率(%)")
    profit_factor = Column(Float, nullable=True, comment="盈亏比")
    total_trades = Column(Integer, default=0, comment="总交易笔数")
    win_trades = Column(Integer, default=0, comment="盈利笔数")
    loss_trades = Column(Integer, default=0, comment="亏损笔数")
    avg_win_pct = Column(Float, nullable=True, comment="平均单笔盈利(%)")
    avg_loss_pct = Column(Float, nullable=True, comment="平均单笔亏损(%)")
    max_consecutive_wins = Column(Integer, default=0, comment="最大连胜")
    max_consecutive_losses = Column(Integer, default=0, comment="最大连败")
    equity_curve = Column(JSON, default=list, comment="权益曲线(按日)")
    trades_detail = Column(JSON, default=list, comment="逐笔交易明细(精简)")
    per_symbol_stats = Column(JSON, default=dict, comment="分品种统计")
    per_score_bucket_stats = Column(JSON, default=dict, comment="分评分区间统计")
    error_msg = Column(Text, default="", comment="错误信息")
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)


class QuantSignalRecord(Base):
    """AI量化信号历史记录表
    每根K线闭合时记录一次信号，用于回测验证信号有效性"""

    __table_args__ = (
        Index("idx_qsig_symbol_time", "symbol", "timestamp"),
        Index("idx_qsig_timeframe_time", "timeframe", "timestamp"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(32), index=True, comment="品种")
    timeframe = Column(String(16), default="4h", comment="周期")
    timestamp = Column(Integer, index=True, comment="信号时间戳(unix秒)")

    # 综合信号
    composite_score = Column(Float, comment="综合评分(-10~+10)")
    direction = Column(String(16), default="neutral", comment="信号方向: bullish/bearish/neutral")
    confidence = Column(Float, comment="置信度(0~100)")
    market_regime = Column(String(32), default="ranging", comment="市场状态")

    # 交易建议
    entry_price = Column(Float, comment="入场价")
    stop_loss = Column(Float, comment="止损价")
    take_profit = Column(Float, comment="止盈价")
    suggested_leverage = Column(Integer, default=1, comment="建议杠杆")
    position_size_pct = Column(Float, comment="建议仓位(%)")
    risk_reward_ratio = Column(Float, comment="盈亏比")

    # 7大因子快照
    factor_scores = Column(JSON, default=dict, comment="各因子得分")
    factor_details = Column(JSON, default=dict, comment="各因子详情")

    # 回测验证结果（延迟填充）
    outcome = Column(String(16), nullable=True, comment="事后结果: hit_tp/hit_sl/expired")
    outcome_return_pct = Column(Float, nullable=True, comment="事后收益率(%)")
    outcome_bars = Column(Integer, nullable=True, comment="事后多少根K线触发")
    verified = Column(Boolean, default=False, comment="是否已验证")


# ============================================================
# 自我进化系统
# ============================================================
class FalseSignalPattern(Base):
    """假信号模式表
    从历史验证信号中自动挖掘"哪些因子组合容易导致假信号"
    """

    __tablename__ = "false_signal_patterns"
    __table_args__ = (
        Index("idx_fsp_pattern_key", "pattern_key", unique=True),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    pattern_key = Column(String(128), unique=True, comment="模式唯一标识（因子组合哈希）")
    pattern_type = Column(String(32), comment="模式类型: factor_combo/regime/volatility")
    description = Column(Text, comment="模式描述")

    # 统计
    total_signals = Column(Integer, default=0, comment="符合该模式的信号总数")
    false_count = Column(Integer, default=0, comment="假信号数量（止损/过期）")
    win_count = Column(Integer, default=0, comment="正确信号数量（止盈）")
    win_rate = Column(Float, default=0, comment="胜率")
    avg_return_pct = Column(Float, default=0, comment="平均收益率")
    profit_factor = Column(Float, default=0, comment="盈亏比")

    # 因子特征
    factor_conditions = Column(JSON, default=dict, comment="触发该模式的因子条件")
    market_regime = Column(String(32), comment="常见市场状态")

    # 建议
    suggestion = Column(Text, comment="改进建议")
    severity = Column(String(16), default="low", comment="严重程度: low/medium/high/critical")

    detected_at = Column(DateTime, default=datetime.utcnow, comment="首次发现时间")
    last_updated = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class FactorPerformanceStat(Base):
    """因子表现统计表
    每个因子在不同市场状态下的胜率贡献，用于动态调整权重
    """

    __tablename__ = "factor_performance_stats"
    __table_args__ = (
        Index("idx_fps_factor_regime", "factor_name", "market_regime", unique=True),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    factor_name = Column(String(64), comment="因子名称")
    market_regime = Column(String(32), default="all", comment="市场状态(all/trending/ranging/volatile)")
    symbol = Column(String(32), default="ALL", comment="品种")

    # 方向准确率
    bullish_correct = Column(Integer, default=0, comment="看涨正确次数")
    bullish_wrong = Column(Integer, default=0, comment="看涨错误次数")
    bearish_correct = Column(Integer, default=0, comment="看跌正确次数")
    bearish_wrong = Column(Integer, default=0, comment="看跌错误次数")

    # 综合指标
    accuracy = Column(Float, default=0, comment="方向准确率")
    correlation = Column(Float, default=0, comment="与最终收益的相关系数")
    importance_score = Column(Float, default=0, comment="重要性评分(0-100)")

    # 建议权重
    suggested_weight = Column(Float, default=0, comment="建议权重")
    current_weight = Column(Float, default=0, comment="当前权重")

    sample_size = Column(Integer, default=0, comment="样本量")
    last_updated = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class EvolutionProposal(Base):
    """进化优化方案表
    AI分析历史数据后生成的策略优化建议
    """

    __tablename__ = "evolution_proposals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    proposal_type = Column(String(32), comment="方案类型: parameter/weight/threshold/strategy/new_factor")
    title = Column(String(256), comment="方案标题")
    description = Column(Text, comment="详细描述")

    # 当前 vs 提议
    current_config = Column(JSON, default=dict, comment="当前配置")
    proposed_config = Column(JSON, default=dict, comment="提议配置")

    # 预期收益
    expected_win_rate_improvement = Column(Float, default=0, comment="预期胜率提升(%)")
    expected_profit_factor_improvement = Column(Float, default=0, comment="预期盈亏比提升")
    expected_drawdown_reduction = Column(Float, default=0, comment="预期回撤降低(%)")
    confidence = Column(Float, default=0, comment="方案置信度(0-100)")

    # 依据
    evidence_summary = Column(Text, comment="依据摘要")
    supporting_patterns = Column(JSON, default=list, comment="支撑的假信号模式ID列表")
    backtest_evidence_id = Column(Integer, nullable=True, comment="回测验证ID")

    # 状态
    status = Column(String(16), default="pending", comment="pending/accepted/rejected/applied")
    applied_at = Column(DateTime, nullable=True, comment="应用时间")

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class EvolutionRun(Base):
    """进化运行记录表
    每次进化分析的运行记录
    """

    __tablename__ = "evolution_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_type = Column(String(32), comment="运行类型: full/false_signals/factor_stats/proposals")
    status = Column(String(16), default="running", comment="running/completed/failed")
    symbols_analyzed = Column(Integer, default=0, comment="分析品种数")
    signals_analyzed = Column(Integer, default=0, comment="分析信号数")
    patterns_found = Column(Integer, default=0, comment="发现模式数")
    proposals_generated = Column(Integer, default=0, comment="生成方案数")
    error_message = Column(Text, nullable=True)

    started_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)


class DailyFinancialReport(Base):
    """每日财务报表（按用户+子账号聚合，凌晨自动生成）"""

    __table_args__ = (
        Index("idx_user_acc_date", "user_id", "exchange_account_id", "report_date", unique=True),
    )

    user_id = Column(Integer, index=True, comment="用户ID")
    exchange_account_id = Column(Integer, nullable=True, index=True, comment="子账号ID(空=全账号汇总)")
    report_date = Column(String(16), index=True, comment="报表日期 YYYY-MM-DD")

    # 账户余额
    start_balance = Column(DECIMAL(18, 8), default=0, comment="期初权益")
    end_balance = Column(DECIMAL(18, 8), default=0, comment="期末权益")
    net_deposit = Column(DECIMAL(18, 8), default=0, comment="当日净转入")
    net_withdraw = Column(DECIMAL(18, 8), default=0, comment="当日净转出")

    # 盈亏
    realized_pnl = Column(DECIMAL(18, 8), default=0, comment="已实现盈亏")
    unrealized_pnl = Column(DECIMAL(18, 8), default=0, comment="未实现盈亏(收盘时)")
    total_pnl = Column(DECIMAL(18, 8), default=0, comment="当日总盈亏")
    total_pnl_pct = Column(Float, default=0, comment="当日收益率(%)")
    fee_total = Column(DECIMAL(18, 8), default=0, comment="手续费合计")

    # 交易统计
    trade_count = Column(Integer, default=0, comment="当日交易笔数(平仓算1笔)")
    order_count = Column(Integer, default=0, comment="当日下单次数")
    long_count = Column(Integer, default=0, comment="做多笔数")
    short_count = Column(Integer, default=0, comment="做空笔数")
    win_count = Column(Integer, default=0, comment="盈利笔数")
    loss_count = Column(Integer, default=0, comment="亏损笔数")
    win_rate = Column(Float, default=0, comment="当日胜率(%)")
    profit_factor = Column(Float, default=0, comment="当日盈亏比")
    avg_holding_minutes = Column(Integer, default=0, comment="平均持仓时长(分钟)")

    # 风险指标
    max_position_count = Column(Integer, default=0, comment="当日最大同时持仓数")
    max_drawdown_daily = Column(Float, default=0, comment="当日最大回撤(%)")
    max_single_loss_pct = Column(Float, default=0, comment="单笔最大亏损(%)")
    max_single_win_pct = Column(Float, default=0, comment="单笔最大盈利(%)")
    risk_event_count = Column(Integer, default=0, comment="触发风控事件次数")

    # 品种维度（JSON聚合）
    per_symbol_summary = Column(JSON, default=dict, comment="分品种汇总")
    per_timeframe_summary = Column(JSON, default=dict, comment="分周期汇总")
    per_score_bucket_summary = Column(JSON, default=dict, comment="分评分区间汇总")


class WeeklyFinancialReport(Base):
    """周度财务报表"""

    __table_args__ = (
        Index("idx_user_week", "user_id", "week_key", unique=True),
    )

    user_id = Column(Integer, index=True)
    exchange_account_id = Column(Integer, nullable=True, index=True)
    week_key = Column(String(16), index=True, comment="YYYY-WW")
    week_start = Column(String(16))
    week_end = Column(String(16))

    start_balance = Column(DECIMAL(18, 8), default=0)
    end_balance = Column(DECIMAL(18, 8), default=0)
    total_pnl = Column(DECIMAL(18, 8), default=0)
    total_pnl_pct = Column(Float, default=0)
    sharpe_ratio = Column(Float, nullable=True)
    max_drawdown_pct = Column(Float, nullable=True)
    total_trade_count = Column(Integer, default=0)
    win_rate = Column(Float, default=0)
    profit_factor = Column(Float, default=0)
    fee_total = Column(DECIMAL(18, 8), default=0)


class MonthlyFinancialReport(Base):
    """月度财务报表"""

    __table_args__ = (
        Index("idx_user_month", "user_id", "month_key", unique=True),
    )

    user_id = Column(Integer, index=True)
    exchange_account_id = Column(Integer, nullable=True, index=True)
    month_key = Column(String(16), index=True, comment="YYYY-MM")

    start_balance = Column(DECIMAL(18, 8), default=0)
    end_balance = Column(DECIMAL(18, 8), default=0)
    total_pnl = Column(DECIMAL(18, 8), default=0)
    total_pnl_pct = Column(Float, default=0)
    btc_benchmark_pct = Column(Float, nullable=True, comment="BTC同期涨跌幅对比")
    eth_benchmark_pct = Column(Float, nullable=True)
    sharpe_ratio = Column(Float, nullable=True)
    sortino_ratio = Column(Float, nullable=True)
    max_drawdown_pct = Column(Float, nullable=True)
    calmar_ratio = Column(Float, nullable=True)
    total_trade_count = Column(Integer, default=0)
    win_rate = Column(Float, default=0)
    profit_factor = Column(Float, default=0)
    win_streak_best = Column(Integer, default=0)
    loss_streak_worst = Column(Integer, default=0)
    fee_total = Column(DECIMAL(18, 8), default=0)
    per_symbol = Column(JSON, default=dict)
