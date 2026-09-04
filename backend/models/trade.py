"""
交易订单 / 持仓 模型
"""
from sqlalchemy import (
    Column, Integer, String, SmallInteger, DECIMAL, Text,
    ForeignKey, DateTime, Index, Float
)
from sqlalchemy.orm import relationship

from backend.db.base import Base


class TradeOrder(Base):
    """交易订单表"""

    SIDE_LONG = 1   # 做多（买入开多 / 卖出平多）
    SIDE_SHORT = 2  # 做空（卖出开空 / 买入平空）

    TYPE_OPEN = 1   # 开仓
    TYPE_CLOSE = 2  # 平仓
    TYPE_LIQUIDATE = 3 # 强平

    STATUS_PENDING = 0    # 待下单
    STATUS_SUBMITTED = 1  # 已提交交易所
    STATUS_FILLED = 2     # 完全成交
    STATUS_PARTIAL = 3    # 部分成交
    STATUS_CANCELED = 4   # 已撤销
    STATUS_FAILED = 5     # 下单失败
    STATUS_TP = 6         # 止盈成交
    STATUS_SL = 7         # 止损成交
    STATUS_RISK_CLOSE = 8 # 风控强制平仓

    REASON_MANUAL = 1          # 手动
    REASON_SCORE_TRIGGER = 2   # 评分触发
    REASON_TP = 3              # 止盈
    REASON_SL = 4              # 止损
    REASON_RISK_DRAWDOWN = 5   # 单笔回撤超限
    REASON_RISK_DAILY = 6      # 日亏损超限
    REASON_RISK_COOLDOWN = 7   # 连续亏损冷静期
    REASON_SCORE_REVERSE = 8   # 评分反转

    __table_args__ = (
        Index("idx_acc_time", "exchange_account_id", "created_at"),
        Index("idx_symbol_status", "symbol", "status"),
    )

    exchange_account_id = Column(Integer, ForeignKey("exchange_accounts.id", ondelete="CASCADE"),
                                 index=True, comment="交易所子账号ID")
    strategy_id = Column(Integer, ForeignKey("strategy_configs.id", ondelete="SET NULL"),
                         nullable=True, index=True, comment="关联策略ID")
    user_id = Column(Integer, index=True, comment="用户ID(冗余)")
    exchange = Column(SmallInteger, comment="交易所: 1-币安 2-OKX")

    # 订单基础
    exchange_order_id = Column(String(128), default="", index=True, comment="交易所订单号")
    client_order_id = Column(String(128), index=True, comment="客户端自定义ID(确定性hash)")
    symbol = Column(String(32), index=True, comment="交易品种: BTC/ETH/...")
    side = Column(SmallInteger, comment="方向: 1-做多 2-做空")
    order_type = Column(SmallInteger, comment="类型: 1-开仓 2-平仓 3-强平")

    # 开平仓关联
    position_id = Column(Integer, ForeignKey("trade_positions.id", ondelete="SET NULL"),
                         nullable=True, index=True, comment="关联持仓ID")
    linked_open_order_id = Column(Integer, nullable=True, index=True,
                                  comment="对应的开仓订单ID(平仓时回填)")

    # 价格与数量
    leverage = Column(SmallInteger, default=3, comment="杠杆倍数(3-10)")
    order_price = Column(DECIMAL(18, 8), default=0, comment="下单价格")
    avg_fill_price = Column(DECIMAL(18, 8), default=0, comment="成交均价")
    quantity_contracts = Column(DECIMAL(18, 8), default=0, comment="成交合约张数")
    quantity_usdt = Column(DECIMAL(18, 8), default=0, comment="成交名义金额(USDT)")
    margin_used = Column(DECIMAL(18, 8), default=0, comment="占用保证金")

    # 止盈止损
    tp_price = Column(DECIMAL(18, 8), nullable=True, comment="止盈价")
    sl_price = Column(DECIMAL(18, 8), nullable=True, comment="止损价")
    tp_order_id = Column(String(128), default="", comment="止盈条件单ID")
    sl_order_id = Column(String(128), default="", comment="止损条件单ID")

    # 盈亏
    realized_pnl = Column(DECIMAL(18, 8), default=0, comment="已实现盈亏(USDT)")
    fee = Column(DECIMAL(18, 8), default=0, comment="手续费")
    pnl_ratio = Column(Float, default=0, comment="盈亏比例(相对于保证金)")

    # 状态与原因
    status = Column(SmallInteger, default=0, index=True, comment="订单状态")
    trigger_reason = Column(SmallInteger, default=0, comment="触发原因")
    trigger_score = Column(Float, nullable=True, comment="触发时综合评分")
    error_msg = Column(Text, default="", comment="失败原因/备注")

    # 时间
    submitted_at = Column(DateTime, nullable=True, comment="提交交易所时间")
    filled_at = Column(DateTime, nullable=True, comment="成交时间")

    # 关联
    account = relationship("ExchangeAccount", back_populates="orders")
    strategy = relationship("StrategyConfig", back_populates="orders")
    position = relationship("TradePosition", back_populates="orders")


class TradePosition(Base):
    """当前/历史持仓表"""

    STATUS_OPEN = 1     # 持仓中
    STATUS_CLOSED = 2   # 已平仓
    STATUS_LIQUIDATED = 3 # 已强平

    __table_args__ = (
        Index("idx_acc_status", "exchange_account_id", "status"),
    )

    exchange_account_id = Column(Integer, ForeignKey("exchange_accounts.id", ondelete="CASCADE"),
                                 index=True, comment="交易所子账号ID")
    strategy_id = Column(Integer, ForeignKey("strategy_configs.id", ondelete="SET NULL"),
                         nullable=True, index=True, comment="策略ID")
    user_id = Column(Integer, index=True, comment="用户ID")
    exchange = Column(SmallInteger, comment="交易所")

    symbol = Column(String(32), index=True, comment="品种")
    side = Column(SmallInteger, comment="方向: 1-多 2-空")
    leverage = Column(SmallInteger, default=3, comment="杠杆")

    entry_price = Column(DECIMAL(18, 8), default=0, comment="开仓均价")
    mark_price = Column(DECIMAL(18, 8), default=0, comment="最新标记价")
    quantity_contracts = Column(DECIMAL(18, 8), default=0, comment="持仓张数")
    quantity_usdt = Column(DECIMAL(18, 8), default=0, comment="名义金额")
    margin_used = Column(DECIMAL(18, 8), default=0, comment="占用保证金")

    tp_price = Column(DECIMAL(18, 8), nullable=True, comment="止盈价")
    sl_price = Column(DECIMAL(18, 8), nullable=True, comment="止损价")

    # Trailing Stop 移动止损
    trailing_enabled = Column(Integer, default=0, comment="是否启用移动止损: 0-否 1-是")
    trailing_activation_pct = Column(Float, default=1.0, comment="激活移动止损的盈利百分比")
    trailing_distance_pct = Column(Float, default=0.5, comment="移动止损跟踪距离(%)")
    trailing_high_price = Column(DECIMAL(18, 8), nullable=True, comment="持仓期间最高价(多)/最低价(空)")

    unrealized_pnl = Column(DECIMAL(18, 8), default=0, comment="未实现盈亏")
    realized_pnl = Column(DECIMAL(18, 8), default=0, comment="平仓后已实现盈亏")
    pnl_ratio = Column(Float, default=0, comment="盈亏百分比")
    max_drawdown_ratio = Column(Float, default=0, comment="持仓期间最大回撤比例")
    fee_total = Column(DECIMAL(18, 8), default=0, comment="总手续费")

    status = Column(SmallInteger, default=1, index=True, comment="状态")
    close_reason = Column(SmallInteger, nullable=True, comment="平仓原因")
    entry_score = Column(Float, nullable=True, comment="开仓时评分")
    entry_time = Column(DateTime, nullable=True, comment="开仓时间")
    close_time = Column(DateTime, nullable=True, comment="平仓时间")
    close_price = Column(DECIMAL(18, 8), nullable=True, comment="平仓均价")
    holding_minutes = Column(Integer, default=0, comment="持仓时长(分钟)")

    orders = relationship("TradeOrder", back_populates="position")
    account = relationship("ExchangeAccount", back_populates="positions")
