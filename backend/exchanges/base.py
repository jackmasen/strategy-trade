"""
交易所抽象基类 + 工厂函数
所有交易所实现(Binance / OKX)必须遵循此接口，上层业务(评分/下单/风控)仅使用本文件方法

关键设计原则：
  1. 上层业务永远不直接调用 ccxt / python-binance / okx SDK，全部通过本基类
  2. 所有返回值使用 _types.py 中定义的统一 dataclass (Balance / Position / Order / Ticker / Candle)
  3. 下单数量自动按交易所 stepSize 做量化截断（避免精度问题导致失败）
  4. 抛出统一异常 ExchangeError / InsufficientBalanceError / OrderNotFoundError（由 core.exceptions 捕获）
"""
from __future__ import annotations

import asyncio
import time
import uuid
from abc import ABC, abstractmethod
from decimal import Decimal, ROUND_DOWN
from typing import Dict, List, Optional, Tuple

from backend.core.exceptions import (
    ExchangeError, InsufficientBalanceError, OrderNotFoundError,
    ExchangeNotImplementedError,
)
from backend.core.logging_config import logger
from ._types import (
    Balance, Position, Order, Ticker, Candle,
    OrderBook, PublicTrade, OpenInterest,
    SIDE_LONG, SIDE_SHORT,
    ORDER_TYPE_MARKET, ORDER_TYPE_LIMIT,
)


class ExchangeClientBase(ABC):
    """交易所对接统一接口"""

    # --------- 子类需要实现的属性 ---------
    EXCHANGE_NAME: str = "base"
    # 符号映射：内部 BTC -> 交易所 BTCUSDT / BTC-USDT-SWAP
    SYMBOL_MAP: Dict[str, str] = {
        # 加密货币
        "BTC": "BTCUSDT",
        "ETH": "ETHUSDT",
        "SOL": "SOLUSDT",

        # 贵金属
        "XAU": "XAUUSDT",   # 如交易所不支持贵金属，子类覆盖
        "XAG": "XAGUSDT",   # 白银
        # 能源
        "WTI": "WTIUSDT",   # 原油
        # 美股-科技
        "TSLA": "TSLAUSDT",  # 特斯拉
        "NVDA": "NVDAUSDT",  # 英伟达
        "AAPL": "AAPLUSDT",  # 苹果
        "MSFT": "MSFTUSDT",  # 微软
        # 美股-中概
        "TCEHY": "TCEHYUSDT",  # 腾讯 ADR
        # 美股-半导体
        "SKHYNIX": "SKHYNIXUSDT",  # SK海力士 永续合约
        "SNDK": "SNDKUSDT",        # 闪迪 永续合约
    }
    # 交易对步进精度 (从交易所拉取后缓存)
    _step_size_cache: Dict[str, Decimal] = {}
    _tick_size_cache: Dict[str, Decimal] = {}

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        passphrase: str = "",
        testnet: bool = True,
        exchange_account_id: int = 0,
    ):
        self.api_key = api_key
        self.api_secret = api_secret
        self.passphrase = passphrase
        self.testnet = testnet
        self.exchange_account_id = exchange_account_id
        self._client = None           # 实际 sdk client
        self._ws_client = None        # 实际 ws client

    # ==========================================================
    #  工厂函数（上层调用入口）
    # ==========================================================
    @classmethod
    def create(
        cls,
        exchange: int,
        api_key: str,
        api_secret: str,
        passphrase: str = "",
        testnet: bool = True,
        exchange_account_id: int = 0,
    ) -> "ExchangeClientBase":
        """
        工厂：按 exchange 编号（来自 exchange_account.exchange 字段）返回对应实现
        exchange: 1=币安 Binance, 2=OKX
        """
        if exchange == 1:
            from .binance import BinanceFuturesClient
            return BinanceFuturesClient(
                api_key=api_key, api_secret=api_secret,
                testnet=testnet, exchange_account_id=exchange_account_id,
            )
        elif exchange == 2:
            from .okx import OKXFuturesClient
            return OKXFuturesClient(
                api_key=api_key, api_secret=api_secret, passphrase=passphrase,
                testnet=testnet, exchange_account_id=exchange_account_id,
            )
        elif exchange == 3:
            from .bybit import BybitFuturesClient
            return BybitFuturesClient(
                api_key=api_key, api_secret=api_secret, passphrase=passphrase,
                testnet=testnet, exchange_account_id=exchange_account_id,
            )
        else:
            raise ExchangeNotImplementedError(f"未知交易所编号: {exchange}")

    # ==========================================================
    #  公用辅助（非抽象，子类可直接复用）
    # ==========================================================
    def _to_ex_symbol(self, symbol: str) -> str:
        """内部 BTC -> 交易所原生 BTCUSDT / BTC-USDT-SWAP"""
        if symbol in self.SYMBOL_MAP:
            return self.SYMBOL_MAP[symbol]
        # 未映射就原样返回（支持自定义符号）
        return symbol

    def _from_ex_symbol(self, ex_symbol: str) -> str:
        """交易所原生 -> 内部 BTC"""
        # 去掉后缀 USDT / -USDT-SWAP
        for k, v in self.SYMBOL_MAP.items():
            if v == ex_symbol:
                return k
        # 通用回退：去掉末尾 USDT
        if ex_symbol.endswith("USDT"):
            return ex_symbol[:-4]
        if ex_symbol.endswith("-SWAP"):
            return ex_symbol.replace("-USDT-SWAP", "").replace("-SWAP", "")
        return ex_symbol

    def _client_order_id(self) -> str:
        """生成跨交易所兼容的客户端订单ID（长度限制各不相同，统一16字符uuid前缀）"""
        return ("s" + uuid.uuid4().hex)[:16]

    def _round_qty(self, symbol: str, qty: float) -> float:
        """按 stepSize 向下取整数量，避免下单精度错误"""
        step = self._step_size_cache.get(symbol)
        if not step:
            # 如未缓存，返回8位小数（保守值），实际首次调用应 refresh_symbol_rules
            return float(Decimal(str(qty)).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN))
        d_qty = Decimal(str(qty))
        d_step = Decimal(str(step))
        rounded = (d_qty / d_step).to_integral_value(rounding=ROUND_DOWN) * d_step
        return float(rounded)

    def _round_price(self, symbol: str, price: float) -> float:
        tick = self._tick_size_cache.get(symbol)
        if not tick:
            return float(Decimal(str(price)).quantize(Decimal("0.00000001")))
        d_price = Decimal(str(price))
        d_tick = Decimal(str(tick))
        rounded = (d_price / d_tick).to_integral_value(rounding=ROUND_DOWN) * d_tick
        return float(rounded)

    # ==========================================================
    #  抽象接口（子类实现）
    # ==========================================================

    # ---- 连接 / 初始化 ----
    @abstractmethod
    def connect(self) -> None:
        """初始化 REST client、拉取 symbol 精度规则缓存"""
        ...

    @abstractmethod
    def close(self) -> None:
        ...

    # ---- 余额 & 持仓 ----
    @abstractmethod
    def fetch_balance(self) -> Balance:
        """拉取 USDT 本位余额/权益"""
        ...

    @abstractmethod
    def fetch_positions(self, symbols: Optional[List[str]] = None) -> List[Position]:
        """
        拉取所有/指定币种的持仓
        返回 List[Position]，无持仓返回空列表
        注意：应把 'long / short' 两向持仓展开成 2 条 Position（side=1 / side=2）
        """
        ...

    # ---- 下单 / 撤单 ----
    @abstractmethod
    def place_order(
        self,
        symbol: str,
        side: int,
        quantity: float,            # 币数量，非 USDT
        order_type: str = ORDER_TYPE_MARKET,
        price: Optional[float] = None,
        leverage: int = 3,
        # TP/SL 两种传参模式二选一：
        #   1) 百分比模式：take_profit_pct=3.0 表示相对 entry +3%
        #   2) 绝对价格模式：take_profit_price=72000 表示绝对止盈价
        #   若同传：优先用绝对 price 模式
        take_profit_pct: Optional[float] = None,
        stop_loss_pct: Optional[float] = None,
        take_profit_price: Optional[float] = None,
        stop_loss_price: Optional[float] = None,
        # 自定义 client_order_id（若空则自动生成）
        client_order_id: str = "",
    ) -> Order:
        """
        市价/限价开仓 (下单前自动设置杠杆 + 下单后挂 TP/SL)
        返回订单对象(含成交均价/数量)
        失败抛 ExchangeError/InsufficientBalanceError
        """
        ...

    @abstractmethod
    def set_leverage(self, symbol: str, leverage: int) -> bool:
        """
        设置某币的杠杆倍数(3-10x)；设置失败抛 ExchangeError
        返回 True 表示成功或已生效
        """
        ...

    @abstractmethod
    def close_position(
        self,
        symbol: str,
        side: int,
        quantity: Optional[float] = None,  # None 表示全平
        order_type: str = ORDER_TYPE_MARKET,
        price: Optional[float] = None,
        client_order_id: str = "",
    ) -> Order:
        """
        平多/平空；默认市价全平
        返回平仓订单(含已实现盈亏)
        """
        ...

    @abstractmethod
    def cancel_order(self, symbol: str, exchange_order_id: str, client_order_id: str = "") -> bool:
        """撤单，成功返回 True；订单不存在抛 OrderNotFoundError"""
        ...

    @abstractmethod
    def cancel_all_open_orders(self, symbol: Optional[str] = None) -> int:
        """撤销全部挂单，返回撤掉的数量"""
        ...

    @abstractmethod
    def fetch_order(self, symbol: str, exchange_order_id: str, client_order_id: str = "") -> Order:
        """查询订单状态"""
        ...

    # ---- 行情（REST 拉取，启动/校验时用） ----
    @abstractmethod
    def fetch_ticker(self, symbol: str) -> Ticker:
        ...

    @abstractmethod
    def fetch_klines(
        self,
        symbol: str,
        timeframe: str,          # 1m/5m/15m/1h/4h/1d
        limit: int = 200,
    ) -> List[Candle]:
        """
        拉取 K 线（用于技术指标），返回按 open_time 升序
        limit 建议 200 根（足够覆盖 MA200）
        """
        ...

    # ---- 深度盘口 / 近期成交 / 持仓量 ----
    @abstractmethod
    def fetch_orderbook(self, symbol: str, limit: int = 20) -> OrderBook:
        """拉取深度盘口"""
        ...

    @abstractmethod
    def fetch_recent_trades(self, symbol: str, limit: int = 50) -> List[PublicTrade]:
        """拉取近期成交记录"""
        ...

    @abstractmethod
    def fetch_open_interest(self, symbol: str) -> OpenInterest:
        """拉取当前持仓量"""
        ...

    # ---- 设置 TP/SL (已持仓后单独调整) ----
    @abstractmethod
    def set_position_tp_sl(
        self,
        symbol: str,
        side: int,
        take_profit_price: Optional[float] = None,
        stop_loss_price: Optional[float] = None,
    ) -> bool:
        ...

    # ---- WS 行情（可选，由 market.py 统一管理） ----
    def start_ws(
        self,
        symbols: List[str],
        on_ticker=None,          # callback(ticker: Ticker) - O(1) 内完成！
        on_kline=None,           # callback(candle: Candle, closed: bool)
    ) -> None:
        raise ExchangeNotImplementedError(f"{self.EXCHANGE_NAME} 未实现 WS 行情")

    def stop_ws(self) -> None:
        ...
