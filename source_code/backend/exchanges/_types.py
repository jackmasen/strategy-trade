"""
通用交易数据结构 - 统一 Binance/OKX 的返回格式
避免不同交易所字段名/枚举值不同，上层业务只认本文件类型
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional, List


# ---------- 枚举 ----------
SIDE_LONG = 1   # 做多
SIDE_SHORT = 2  # 做空

ORDER_TYPE_MARKET = "market"   # 市价
ORDER_TYPE_LIMIT = "limit"     # 限价

ORDER_STATUS_PENDING   = 0
ORDER_STATUS_SUBMITTED = 1
ORDER_STATUS_FILLED    = 2
ORDER_STATUS_PARTIAL   = 3
ORDER_STATUS_CANCELED  = 4
ORDER_STATUS_FAILED    = 5


# ---------- 账户余额/权益 ----------
@dataclass
class Balance:
    total: float = 0.0          # 账户总权益 (USDT)
    available: float = 0.0      # 可用余额
    used_margin: float = 0.0    # 已占用保证金
    unrealized_pnl: float = 0.0 # 未实现盈亏
    balance: float = 0.0        # 钱包余额(不含浮盈)
    currency: str = "USDT"

    def to_dict(self):
        return asdict(self)


# ---------- 持仓 ----------
@dataclass
class Position:
    symbol: str
    side: int                     # 1多 / 2空
    quantity: float = 0.0         # 持仓数量(币数量)
    entry_price: float = 0.0      # 开仓均价
    mark_price: float = 0.0       # 标记价格
    unrealized_pnl: float = 0.0   # 未实现盈亏(USDT)
    unrealized_pnl_pct: float = 0.0  # 未实现盈亏率 %
    leverage: int = 1             # 杠杆倍数
    margin: float = 0.0           # 占用保证金
    liquidation_price: float = 0.0 # 强平价
    take_profit_price: float = 0.0
    stop_loss_price: float = 0.0
    max_drawdown_pct: float = 0.0
    open_timestamp_ms: int = 0
    # 交易所原始持仓ID，用于精确平仓
    raw_position_id: str = ""

    def to_dict(self):
        return asdict(self)


# ---------- 订单 ----------
@dataclass
class Order:
    exchange_order_id: str = ""   # 交易所订单ID
    client_order_id: str = ""     # 客户端自定义ID
    symbol: str = ""
    side: int = 0                 # 1多 2空
    order_type: str = ORDER_TYPE_MARKET
    quantity: float = 0.0         # 下单数量(币)
    price: float = 0.0            # 限价单才有
    filled_quantity: float = 0.0  # 已成交数量
    avg_fill_price: float = 0.0   # 成交均价
    realized_pnl: float = 0.0     # 已实现盈亏
    fee: float = 0.0              # 手续费
    status: int = ORDER_STATUS_PENDING
    error_msg: str = ""
    timestamp_ms: int = 0
    # 减仓/平仓时，关联的持仓ID
    close_position_id: str = ""

    def to_dict(self):
        return asdict(self)


# ---------- 行情 ----------
@dataclass
class Ticker:
    symbol: str
    last_price: float = 0.0
    bid_price: float = 0.0
    ask_price: float = 0.0
    high_24h: float = 0.0
    low_24h: float = 0.0
    volume_24h: float = 0.0
    change_pct_24h: float = 0.0
    timestamp_ms: int = 0

    def to_dict(self):
        return asdict(self)


@dataclass
class Candle:
    """K线 (统一成 1h / 4h)"""
    symbol: str
    timeframe: str                # 1m / 5m / 15m / 1h / 4h / 1d
    open_time_ms: int
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0
    volume: float = 0.0
    close_time_ms: int = 0

    def to_dict(self):
        return asdict(self)

    @property
    def mid(self) -> float:
        return (self.high + self.low) / 2


# ---------- 深度盘口 ----------
@dataclass
class OrderBookEntry:
    price: float = 0.0
    quantity: float = 0.0
    total: float = 0.0      # 累计量

    def to_dict(self):
        return asdict(self)


@dataclass
class OrderBook:
    symbol: str
    bids: List[OrderBookEntry] = field(default_factory=list)   # 买盘
    asks: List[OrderBookEntry] = field(default_factory=list)   # 卖盘
    timestamp_ms: int = 0

    def to_dict(self):
        return {
            "symbol": self.symbol,
            "bids": [e.to_dict() for e in self.bids],
            "asks": [e.to_dict() for e in self.asks],
            "timestamp_ms": self.timestamp_ms,
        }


# ---------- 近期成交 ----------
@dataclass
class PublicTrade:
    symbol: str
    trade_id: str = ""
    price: float = 0.0
    quantity: float = 0.0
    quote_qty: float = 0.0     # 成交金额(USDT)
    side: int = 0              # 1=主动买入(买方吃单), 2=主动卖出(卖方吃单)
    timestamp_ms: int = 0
    is_buyer_maker: bool = False

    def to_dict(self):
        return asdict(self)


# ---------- 持仓量 ----------
@dataclass
class OpenInterest:
    symbol: str
    open_interest: float = 0.0      # 持仓量(币数量)
    open_interest_usdt: float = 0.0 # 持仓价值(USDT)
    timestamp_ms: int = 0

    def to_dict(self):
        return asdict(self)
