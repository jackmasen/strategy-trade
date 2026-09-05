"""
交易所子账号模型
"""
from sqlalchemy import Column, Integer, String, Boolean, SmallInteger, DECIMAL, Text, ForeignKey, DateTime
from sqlalchemy.orm import relationship

from backend.db.base import Base


class ExchangeAccount(Base):
    """交易所子账号（绑定API密钥）"""

    EXCHANGE_BINANCE = 1
    EXCHANGE_OKX = 2
    EXCHANGE_BYBIT = 3

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True, comment="所属用户ID")
    exchange = Column(SmallInteger, index=True, comment="交易所: 1-币安 2-OKX 3-Bybit")
    sub_account_name = Column(String(64), default="", comment="子账号名称(展示用)")
    sub_account_id = Column(String(128), default="", comment="交易所分配的子账号ID")
    api_key = Column(String(255), nullable=False, comment="API Key(加密存储)")
    api_secret = Column(String(255), nullable=False, comment="API Secret(加密存储)")
    api_passphrase = Column(String(128), default="", comment="OKX Passphrase(加密存储)")
    ip_whitelist = Column(String(512), default="", comment="IP白名单(逗号分隔)")
    initial_balance = Column(DECIMAL(18, 8), default=0, comment="初始划转余额(USDT)")
    current_balance = Column(DECIMAL(18, 8), default=0, comment="当前账户权益(USDT)")
    available_balance = Column(DECIMAL(18, 8), default=0, comment="可用余额(USDT)")
    margin_balance = Column(DECIMAL(18, 8), default=0, comment="保证金余额")
    unrealized_pnl = Column(DECIMAL(18, 8), default=0, comment="未实现盈亏")
    realized_pnl_total = Column(DECIMAL(18, 8), default=0, comment="累计已实现盈亏")
    leverage_max = Column(SmallInteger, default=5, comment="该账号允许最大杠杆")
    balance_updated_at = Column(DateTime, nullable=True, comment="余额刷新时间")
    status = Column(SmallInteger, default=1, comment="状态: 1-启用 0-禁用 2-API异常")
    testnet = Column(Boolean, default=True, comment="是否测试网")
    remark = Column(Text, default="", comment="备注")

    owner = relationship("User", back_populates="exchange_accounts")
    orders = relationship("TradeOrder", back_populates="account", cascade="all, delete-orphan")
    positions = relationship("TradePosition", back_populates="account", cascade="all, delete-orphan")
