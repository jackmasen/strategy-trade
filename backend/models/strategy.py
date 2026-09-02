"""
交易策略 / 评分模型
"""
from sqlalchemy import (
    Column, Integer, String, Boolean, SmallInteger, DECIMAL, Text,
    ForeignKey, JSON, DateTime, Index, Float
)
from sqlalchemy.orm import relationship

from backend.db.base import Base


class StrategyConfig(Base):
    """策略配置表（每个用户可配置多套策略）"""

    MODE_AUTO = 1     # 全自动
    MODE_SEMIAUTO = 2 # 半自动（触发后需要确认）
    MODE_SIMULATE = 3 # 模拟盘（不下真实单）

    TF_1H = "1h"
    TF_4H = "4h"
    TF_BOTH = "1h,4h"

    DIR_LONG_SHORT = 0
    DIR_LONG_ONLY = 1
    DIR_SHORT_ONLY = 2

    LEVERAGE_FIXED = 1   # 固定杠杆
    LEVERAGE_DYNAMIC = 2 # 动态杠杆（按评分映射）

    # 策略类型
    TYPE_STANDARD = "standard"   # 标准策略（5指标评分引擎）
    TYPE_EMV = "emv"             # EMV策略（10层过滤趋势跟踪）

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True, comment="所属用户ID")
    strategy_name = Column(String(128), nullable=False, comment="策略名称")
    strategy_type = Column(String(32), default="standard", comment="策略类型: standard-标准5指标 / emv-EMV趋势跟踪")
    description = Column(Text, default="", comment="策略描述")

    # 交易品种配置（JSON数组）
    symbols = Column(JSON, default=list, comment="启用品种: [BTC,ETH,SOL,XAU,WTI]")
    exchange_id = Column(Integer, ForeignKey("exchange_accounts.id", ondelete="SET NULL"),
                         nullable=True, index=True, comment="关联交易所子账号ID")

    # 周期与模式
    timeframe = Column(String(32), default="1h,4h", comment="交易周期: 1h / 4h / 1h,4h")
    direction_mode = Column(SmallInteger, default=0, comment="交易方向: 0-多空都做 1-只做多 2-只做空")
    run_mode = Column(SmallInteger, default=3, comment="运行模式: 1-全自动 2-半自动 3-模拟盘")

    # 评分阈值
    score_threshold = Column(Float, default=5.0, comment="开仓最低评分(0-10)")
    strong_score_threshold = Column(Float, default=8.0, comment="强信号评分阈值(激进杠杆)")

    # 评分权重
    weight_technical = Column(Float, default=0.4, comment="技术指标权重")
    weight_news = Column(Float, default=0.3, comment="新闻情绪权重")
    weight_ai = Column(Float, default=0.3, comment="AI分析权重")

    # 杠杆
    leverage_mode = Column(SmallInteger, default=1, comment="杠杆模式: 1-固定 2-动态")
    leverage_fixed = Column(SmallInteger, default=3, comment="固定杠杆倍数(3-10)")
    leverage_low_score = Column(SmallInteger, default=3, comment="低评分杠杆倍数")
    leverage_mid_score = Column(SmallInteger, default=5, comment="中评分杠杆倍数")
    leverage_high_score = Column(SmallInteger, default=8, comment="高评分杠杆倍数")

    # 止盈止损
    tp_ratio = Column(Float, default=4.0, comment="止盈比例(%)")
    sl_ratio = Column(Float, default=2.0, comment="止损比例(%)")
    use_exchange_tpsl = Column(Boolean, default=True, comment="是否使用交易所条件单止盈止损")

    # 仓位管理
    single_position_ratio = Column(Float, default=10.0, comment="单笔仓位占账户权益比例(%)")
    total_position_ratio = Column(Float, default=50.0, comment="总仓位上限(%)")
    max_position_count = Column(SmallInteger, default=3, comment="最大同时持仓数")
    max_single_drawdown = Column(Float, default=2.0, comment="单笔最大回撤(%)")

    # 风控
    daily_max_loss = Column(Float, default=5.0, comment="日最大亏损比例(%)，触发后当日停止交易")
    consecutive_loss_pause = Column(SmallInteger, default=3, comment="连续亏损N单后暂停交易")
    cooldown_hours = Column(Integer, default=24, comment="暂停交易冷却时长(小时)")

    # 启用与排序
    is_active = Column(Boolean, default=True, comment="是否启用")
    priority = Column(Integer, default=0, comment="优先级(大的先执行)")

    owner = relationship("User", back_populates="strategies")
    orders = relationship("TradeOrder", back_populates="strategy")
    score_records = relationship("ScoreRecord", back_populates="strategy", cascade="all, delete-orphan")


class ScoreRecord(Base):
    """评分记录表：每次K线收盘后的评分快照"""

    __table_args__ = (
        Index("idx_symbol_tf_time", "symbol", "timeframe", "candle_close_time"),
    )

    strategy_id = Column(Integer, ForeignKey("strategy_configs.id", ondelete="CASCADE"),
                         index=True, comment="策略ID")
    symbol = Column(String(32), index=True, comment="交易品种: BTC/ETH/SOL/XAU/WTI")
    timeframe = Column(String(16), index=True, comment="周期: 1h/4h")
    candle_close_time = Column(DateTime, index=True, comment="K线收盘时间")
    candle_close_price = Column(DECIMAL(18, 8), default=0, comment="收盘价")

    # 各分项评分
    score_technical = Column(Float, default=0, comment="技术指标评分(0-4)")
    score_news = Column(Float, default=0, comment="新闻情绪评分(0-3)")
    score_ai = Column(Float, default=0, comment="AI分析评分(0-3)")
    score_total = Column(Float, default=0, comment="综合评分(0-10)", index=True)

    # 技术指标快照（供回溯分析）
    ma_short = Column(DECIMAL(18, 8), nullable=True, comment="短期均线")
    ma_long = Column(DECIMAL(18, 8), nullable=True, comment="长期均线")
    macd = Column(DECIMAL(18, 8), nullable=True)
    macd_signal = Column(DECIMAL(18, 8), nullable=True)
    rsi = Column(Float, nullable=True)
    bb_upper = Column(DECIMAL(18, 8), nullable=True)
    bb_middle = Column(DECIMAL(18, 8), nullable=True)
    bb_lower = Column(DECIMAL(18, 8), nullable=True)
    volume_ratio = Column(Float, nullable=True, comment="成交量倍率(相对20日均量)")

    # 建议方向
    suggested_direction = Column(String(8), default="neutral",
                                 comment="建议方向: long/short/neutral")
    suggested_leverage = Column(SmallInteger, default=3, comment="建议杠杆倍数")
    trigger_trade = Column(Boolean, default=False, comment="是否触发了交易")

    # AI/新闻快照
    news_count_positive = Column(Integer, default=0)
    news_count_negative = Column(Integer, default=0)
    ai_reason = Column(Text, default="", comment="AI分析理由")

    # 7因子快照
    market_regime = Column(String(32), nullable=True, comment="市场状态")
    factor_scores = Column(JSON, default=dict, comment="各因子得分(-10~+10)")
    factor_confidence = Column(JSON, default=dict, comment="各因子置信度(0-100)")
    factor_details = Column(JSON, default=dict, comment="各因子详情")

    strategy = relationship("StrategyConfig", back_populates="score_records")
