"""
Bybit v5 API 客户端 — USDT 永续合约
支持：加密货币(BTC/ETH/SOL) + 商品(XAU黄金/XAG白银/WTI原油) + 美股(TSLA/NVDA/AAPL/MSFT/SNDK等)

Bybit TradFi 永续合约支持黄金(XAUUSDT)、白银(XAGUSDT)、原油(CLUSDT)、美股(TSLAUSDT等)
是系统接入 XAU/WTI/美股 K线数据的首选交易所

API文档：https://bybit-exchange.github.io/docs/v5/intro
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import threading
import time
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
from typing import Any, Callable, Dict, List, Optional

import requests

from backend.core.logging_config import logger
from backend.core.config import get_settings
from backend.core.exceptions import (
    ExchangeError, InsufficientBalanceError, OrderNotFoundError,
)
from .base import ExchangeClientBase
from ._types import (
    Balance, Position, Order, Ticker, Candle,
    OrderBook, OrderBookEntry, PublicTrade, OpenInterest,
    SIDE_LONG, SIDE_SHORT,
    ORDER_TYPE_MARKET, ORDER_TYPE_LIMIT,
    ORDER_STATUS_PENDING, ORDER_STATUS_FILLED, ORDER_STATUS_PARTIAL,
    ORDER_STATUS_CANCELED, ORDER_STATUS_FAILED,
)


def _tf_ms(timeframe: str) -> int:
    m = {
        "1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000,
        "1h": 3_600_000, "2h": 7_200_000, "4h": 14_400_000, "6h": 21_600_000,
        "12h": 43_200_000, "1d": 86_400_000,
    }
    return m.get(timeframe, 3_600_000)


class BybitFuturesClient(ExchangeClientBase):
    """Bybit v5 API — 线性永续合约(USDT本位)，含 TradFi 商品/美股"""

    EXCHANGE_NAME = "Bybit"

    SYMBOL_MAP = {
        # 加密货币
        "BTC": "BTCUSDT",
        "ETH": "ETHUSDT",
        "SOL": "SOLUSDT",
        # 贵金属 (Bybit TradFi 永续)
        "XAU": "XAUUSDT",
        "XAG": "XAGUSDT",
        # 能源 (Bybit 原油永续 CLUSDT)
        "WTI": "CLUSDT",
        # 美股-科技 (Bybit TradFi 美股永续)
        "TSLA": "TSLAUSDT",
        "NVDA": "NVDAUSDT",
        "AAPL": "AAPLUSDT",
        "MSFT": "MSFTUSDT",
        # 美股-中概
        "TCEHY": "TCEHYUSDT",
        # 美股-半导体
        "SKHYNIX": "SKHYNIXUSDT",
        "SNDK": "SNDKUSDT",
    }

    def __init__(
        self, api_key: str, api_secret: str,
        passphrase: str = "", testnet: bool = True,
        exchange_account_id: int = 0,
    ):
        super().__init__(
            api_key=api_key, api_secret=api_secret, passphrase=passphrase,
            testnet=testnet, exchange_account_id=exchange_account_id,
        )
        s = get_settings()
        if testnet:
            self.BASE_URL = getattr(s, 'BYBIT_BASE_URL', '') or "https://api-testnet.bybit.com"
            self.WS_URL = "wss://stream-testnet.bybit.com/v5/public/linear"
        else:
            self.BASE_URL = getattr(s, 'BYBIT_BASE_URL', '') or "https://api.bybit.com"
            self.WS_URL = "wss://stream.bybit.com/v5/public/linear"

        self._session = requests.Session()
        self._ws_loop: Optional[asyncio.AbstractEventLoop] = None
        self._ws_thread: Optional[threading.Thread] = None
        self._ws_stop = threading.Event()
        self._ws_conn = None
        self._ws_symbols: List[str] = []
        self._ws_on_ticker: Optional[Callable[[Ticker], Any]] = None
        self._ws_on_kline: Optional[Callable[[Candle, bool], Any]] = None

    # ==========================================================
    # Bybit v5 签名
    # ==========================================================
    def _sign(self, timestamp: str, param_str: str) -> str:
        recv_window = "5000"
        prehash = f"{timestamp}{self.api_key}{recv_window}{param_str}"
        return hmac.new(
            self.api_secret.encode("utf-8"),
            prehash.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def _request(
        self, method: str, path: str,
        params: Optional[Dict] = None,
        body: Optional[Dict] = None,
        signed: bool = True,
        category: str = "linear",
    ) -> Dict:
        url = f"{self.BASE_URL}{path}"
        ts = str(int(time.time() * 1000))

        headers = {"Content-Type": "application/json"}
        param_str = ""

        if method.upper() == "GET":
            if params is None:
                params = {}
            if category and "category" not in params:
                params["category"] = category
            param_str = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
            if param_str:
                url = f"{url}?{param_str}"
        else:
            if body is None:
                body = {}
            if category and "category" not in body:
                body["category"] = category
            param_str = json.dumps(body, separators=(",", ":"))

        if signed:
            sign = self._sign(ts, param_str)
            headers["X-BAPI-API-TIMESTAMP"] = ts
            headers["X-BAPI-KEY"] = self.api_key
            headers["X-BAPI-SIGN"] = sign
            headers["X-BAPI-RECV-WINDOW"] = "5000"

        try:
            if method.upper() == "GET":
                resp = self._session.get(url, headers=headers, timeout=10)
            else:
                resp = self._session.post(url, headers=headers, json=body, timeout=10)
            data = resp.json()
        except Exception as e:
            raise ExchangeError(f"Bybit 请求异常: {e}")

        if data.get("retCode", 0) != 0:
            raise ExchangeError(f"Bybit API 错误: retCode={data.get('retCode')} msg={data.get('retMsg')}")
        return data.get("result", {})

    # ==========================================================
    # 连接 / 关闭
    # ==========================================================
    def connect(self) -> None:
        try:
            result = self._request("GET", "/v5/market/instruments-info", signed=False, category="linear")
            for item in result.get("list", []):
                sym = item.get("symbol", "")
                lot_size = item.get("lotSizeFilter", {})
                step = lot_size.get("qtyStep", "0.001")
                tick = lot_size.get("tickSize", "0.01")
                self._step_size_cache[sym] = Decimal(step)
                self._tick_size_cache[sym] = Decimal(tick)
            logger.info(f"[{self.EXCHANGE_NAME}] 交易规则缓存完成, 共 {len(self._step_size_cache)} 个符号")
        except Exception as e:
            logger.warning(f"[{self.EXCHANGE_NAME}] 拉取 instruments-info 失败，使用默认精度: {e}")

    def close(self) -> None:
        self.stop_ws()
        try:
            self._session.close()
        except Exception:
            pass

    # ==========================================================
    # 行情：Ticker
    # ==========================================================
    def fetch_ticker(self, symbol: str) -> Ticker:
        ex_sym = self._to_ex_symbol(symbol)
        try:
            result = self._request("GET", "/v5/market/tickers", params={"symbol": ex_sym}, signed=False, category="linear")
        except Exception as e:
            raise ExchangeError(f"Bybit 拉取行情失败: {e}")

        items = result.get("list", [])
        if not items:
            raise ExchangeError(f"Bybit 无行情数据: {ex_sym}")
        d = items[0]

        last_price = float(d.get("lastPrice", 0))
        prev_price = float(d.get("prevPrice24h", 0) or 0)
        change_pct = ((last_price - prev_price) / prev_price * 100) if prev_price > 0 else 0.0

        return Ticker(
            symbol=symbol,
            last_price=last_price,
            bid_price=float(d.get("bid1Price", 0)),
            ask_price=float(d.get("ask1Price", 0)),
            high_24h=float(d.get("highPrice24h", 0)),
            low_24h=float(d.get("lowPrice24h", 0)),
            volume_24h=float(d.get("volume24h", 0)),
            change_pct_24h=change_pct,
            timestamp_ms=int(d.get("ts", int(time.time() * 1000))),
        )

    # ==========================================================
    # 行情：K线
    # ==========================================================
    def fetch_klines(
        self, symbol: str, timeframe: str, limit: int = 200, end_time: int = None,
    ) -> List[Candle]:
        ex_sym = self._to_ex_symbol(symbol)
        tf_map = {
            "1m": "1", "5m": "5", "15m": "15", "30m": "30",
            "1h": "60", "4h": "240", "1d": "D",
            "1w": "W", "1M": "M",
            "1y": "M",
        }
        tf = tf_map.get(timeframe, timeframe)
        try:
            params: Dict[str, Any] = {"symbol": ex_sym, "interval": tf, "limit": str(min(limit, 200))}
            if end_time:
                params["end"] = str(end_time)
            result = self._request("GET", "/v5/market/kline", params=params, signed=False, category="linear")
        except Exception as e:
            raise ExchangeError(f"Bybit 拉取K线失败: {e}")

        candles: List[Candle] = []
        # Bybit 返回：startTime, open, high, low, close, volume, turnover（按时间倒序）
        for k in reversed(result.get("list", [])):
            open_time_ms = int(k[0])
            candles.append(Candle(
                symbol=symbol, timeframe=timeframe,
                open_time_ms=open_time_ms,
                open=float(k[1]),
                high=float(k[2]),
                low=float(k[3]),
                close=float(k[4]),
                volume=float(k[5]),
                close_time_ms=open_time_ms + _tf_ms(timeframe) - 1,
            ))
        return candles

    # ==========================================================
    # 行情：盘口
    # ==========================================================
    def fetch_orderbook(self, symbol: str, limit: int = 20) -> OrderBook:
        ex_sym = self._to_ex_symbol(symbol)
        try:
            result = self._request("GET", "/v5/market/orderbook", params={
                "symbol": ex_sym, "limit": str(limit),
            }, signed=False, category="linear")
        except Exception as e:
            raise ExchangeError(f"Bybit 拉取深度失败: {e}")

        bids = []
        total = 0.0
        for b in result.get("b", []):
            qty = float(b[1])
            total += qty
            bids.append(OrderBookEntry(price=float(b[0]), quantity=qty, total=total))
        asks = []
        total = 0.0
        for a in result.get("a", []):
            qty = float(a[1])
            total += qty
            asks.append(OrderBookEntry(price=float(a[0]), quantity=qty, total=total))
        return OrderBook(
            symbol=symbol, bids=bids, asks=asks,
            timestamp_ms=int(time.time() * 1000),
        )

    # ==========================================================
    # 行情：近期成交
    # ==========================================================
    def fetch_recent_trades(self, symbol: str, limit: int = 50) -> List[PublicTrade]:
        ex_sym = self._to_ex_symbol(symbol)
        try:
            result = self._request("GET", "/v5/market/recent-trade", params={
                "symbol": ex_sym, "limit": str(limit),
            }, signed=False, category="linear")
        except Exception as e:
            raise ExchangeError(f"Bybit 拉取成交失败: {e}")

        trades: List[PublicTrade] = []
        for t in result.get("list", []):
            is_buyer_maker = t.get("isBuyerMaker", False)
            trades.append(PublicTrade(
                symbol=symbol,
                trade_id=str(t.get("execId", "")),
                price=float(t.get("price", 0)),
                quantity=float(t.get("size", 0)),
                quote_qty=float(t.get("price", 0)) * float(t.get("size", 0)),
                side=SIDE_LONG if not is_buyer_maker else SIDE_SHORT,
                timestamp_ms=int(t.get("time", 0)),
                is_buyer_maker=is_buyer_maker,
            ))
        return trades

    # ==========================================================
    # 持仓量
    # ==========================================================
    def fetch_open_interest(self, symbol: str) -> OpenInterest:
        ex_sym = self._to_ex_symbol(symbol)
        try:
            result = self._request("GET", "/v5/market/open-interest", params={
                "symbol": ex_sym,
            }, signed=False, category="linear")
        except Exception as e:
            raise ExchangeError(f"Bybit 拉取持仓量失败: {e}")

        items = result.get("list", [])
        if not items:
            return OpenInterest(symbol=symbol)
        d = items[0]
        oi = float(d.get("openInterest", 0))
        last_price = float(d.get("lastPrice", 0) or 0)
        return OpenInterest(
            symbol=symbol,
            open_interest=oi,
            open_interest_usdt=oi * last_price,
            timestamp_ms=int(time.time() * 1000),
        )

    # ==========================================================
    # 账户：余额
    # ==========================================================
    def fetch_balance(self) -> Balance:
        try:
            result = self._request("GET", "/v5/account/wallet-balance", signed=True, category="linear")
        except Exception as e:
            raise ExchangeError(f"Bybit 拉取余额失败: {e}")

        accounts = result.get("list", [])
        if not accounts:
            return Balance()
        acc = accounts[0]
        total = float(acc.get("totalWalletBalance", 0))
        available = float(acc.get("availableBalance", 0))
        used = float(acc.get("totalInitialMargin", 0))
        upnl = float(acc.get("totalUnrealisedPnl", 0))
        wallet = float(acc.get("accountType", "") and acc.get("totalWalletBalance", 0) or total)
        return Balance(
            total=total, available=available, used_margin=used,
            unrealized_pnl=upnl, balance=wallet, currency="USDT",
        )

    # ==========================================================
    # 账户：持仓
    # ==========================================================
    def fetch_positions(self, symbols: Optional[List[str]] = None) -> List[Position]:
        try:
            result = self._request("GET", "/v5/position/list", signed=True, category="linear")
        except Exception as e:
            raise ExchangeError(f"Bybit 拉取持仓失败: {e}")

        positions: List[Position] = []
        for p in result.get("list", []):
            ex_sym = p.get("symbol", "")
            sym = self._from_ex_symbol(ex_sym)
            if symbols and sym not in symbols:
                continue
            side_str = p.get("side", "")
            qty = float(p.get("size", 0))
            if qty == 0:
                continue
            positions.append(Position(
                symbol=sym,
                side=SIDE_LONG if side_str == "Buy" else SIDE_SHORT,
                quantity=qty,
                entry_price=float(p.get("avgPrice", 0)),
                mark_price=float(p.get("markPrice", 0)),
                unrealized_pnl=float(p.get("unrealisedPnl", 0)),
                unrealized_pnl_pct=float(p.get("curRealisedPnl", 0)),
                leverage=int(float(p.get("leverage", 1))),
                margin=float(p.get("positionValue", 0) or p.get("positionIM", 0) or 0),
                liquidation_price=float(p.get("liqPrice", 0) or 0),
                take_profit_price=float(p.get("takeProfit", 0) or 0),
                stop_loss_price=float(p.get("stopLoss", 0) or 0),
                open_timestamp_ms=int(p.get("createdTime", 0) or 0),
                raw_position_id=p.get("positionIdx", ""),
            ))
        return positions

    # ==========================================================
    # 交易：设置杠杆
    # ==========================================================
    def set_leverage(self, symbol: str, leverage: int) -> bool:
        ex_sym = self._to_ex_symbol(symbol)
        try:
            self._request("POST", "/v5/position/set-leverage", body={
                "symbol": ex_sym,
                "buyLeverage": str(leverage),
                "sellLeverage": str(leverage),
            }, signed=True, category="linear")
            return True
        except Exception as e:
            logger.warning(f"[Bybit] 设置杠杆失败 {symbol}: {e}")
            return False

    # ==========================================================
    # 交易：下单
    # ==========================================================
    def place_order(
        self,
        symbol: str,
        side: int,
        quantity: float,
        order_type: str = ORDER_TYPE_MARKET,
        price: Optional[float] = None,
        leverage: int = 3,
        take_profit_pct: Optional[float] = None,
        stop_loss_pct: Optional[float] = None,
        take_profit_price: Optional[float] = None,
        stop_loss_price: Optional[float] = None,
        client_order_id: str = "",
    ) -> Order:
        self.set_leverage(symbol, leverage)
        ex_sym = self._to_ex_symbol(symbol)
        side_str = "Buy" if side == SIDE_LONG else "Sell"
        qty = self._round_qty(symbol, quantity)

        body: Dict[str, Any] = {
            "symbol": ex_sym,
            "side": side_str,
            "qty": str(qty),
            "orderType": "Market" if order_type == ORDER_TYPE_MARKET else "Limit",
            "timeInForce": "IOC" if order_type == ORDER_TYPE_MARKET else "PostOnly",
        }
        if price and order_type == ORDER_TYPE_LIMIT:
            body["price"] = str(self._round_price(symbol, price))
        if client_order_id:
            body["orderLinkId"] = client_order_id[:16]

        try:
            result = self._request("POST", "/v5/order/create", body=body, signed=True, category="linear")
        except ExchangeError as e:
            return Order(
                symbol=symbol, side=side, quantity=qty,
                order_type=order_type, price=price or 0,
                status=ORDER_STATUS_FAILED, error_msg=str(e),
                timestamp_ms=int(time.time() * 1000),
            )

        oid = result.get("orderId", "")
        filled = float(result.get("orderQty", 0) or 0)
        avg_price = float(result.get("avgPrice", 0) or 0)

        return Order(
            exchange_order_id=oid,
            client_order_id=client_order_id,
            symbol=symbol, side=side,
            quantity=qty, price=price or 0,
            filled_quantity=filled,
            avg_fill_price=avg_price,
            status=ORDER_STATUS_FILLED if filled >= qty * 0.99 else ORDER_STATUS_PARTIAL,
            timestamp_ms=int(result.get("createdTime", time.time() * 1000)),
        )

    # ==========================================================
    # 交易：平仓
    # ==========================================================
    def close_position(
        self,
        symbol: str,
        side: int,
        quantity: Optional[float] = None,
        order_type: str = ORDER_TYPE_MARKET,
        price: Optional[float] = None,
        client_order_id: str = "",
    ) -> Order:
        close_side = SIDE_SHORT if side == SIDE_LONG else SIDE_LONG
        positions = self.fetch_positions([symbol])
        pos = next((p for p in positions if p.symbol == symbol), None)
        if not pos:
            raise ExchangeError(f"Bybit 无持仓 {symbol}")
        qty = quantity or pos.quantity
        return self.place_order(
            symbol=symbol, side=close_side, quantity=qty,
            order_type=order_type, price=price,
            client_order_id=client_order_id,
        )

    # ==========================================================
    # 交易：撤销订单
    # ==========================================================
    def cancel_order(self, symbol: str, exchange_order_id: str, client_order_id: str = "") -> bool:
        ex_sym = self._to_ex_symbol(symbol)
        body = {"symbol": ex_sym, "orderId": exchange_order_id}
        if client_order_id:
            body["orderLinkId"] = client_order_id
        try:
            self._request("POST", "/v5/order/cancel", body=body, signed=True, category="linear")
            return True
        except Exception:
            return False

    def cancel_all_open_orders(self, symbol: Optional[str] = None) -> int:
        body: Dict[str, Any] = {}
        if symbol:
            body["symbol"] = self._to_ex_symbol(symbol)
        try:
            self._request("POST", "/v5/order/cancel-all", body=body, signed=True, category="linear")
            return 1
        except Exception:
            return 0

    # ==========================================================
    # 交易：查询订单
    # ==========================================================
    def fetch_order(self, symbol: str, exchange_order_id: str, client_order_id: str = "") -> Order:
        ex_sym = self._to_ex_symbol(symbol)
        params = {"symbol": ex_sym, "orderId": exchange_order_id}
        if client_order_id:
            params["orderLinkId"] = client_order_id
        try:
            result = self._request("GET", "/v5/order/realtime", params=params, signed=True, category="linear")
        except Exception as e:
            raise OrderNotFoundError(f"Bybit 订单查询失败: {e}")

        items = result.get("list", [])
        if not items:
            raise OrderNotFoundError(f"Bybit 订单不存在: {exchange_order_id}")
        o = items[0]
        side_str = o.get("side", "")
        status_str = o.get("status", "")
        qty = float(o.get("qty", 0))
        filled = float(o.get("cumExecQty", 0))
        avg_price = float(o.get("avgPrice", 0) or 0)

        st = ORDER_STATUS_PENDING
        if status_str == "Filled":
            st = ORDER_STATUS_FILLED
        elif status_str == "PartiallyFilled":
            st = ORDER_STATUS_PARTIAL
        elif status_str == "Cancelled":
            st = ORDER_STATUS_CANCELED
        elif status_str == "Rejected":
            st = ORDER_STATUS_FAILED

        return Order(
            exchange_order_id=o.get("orderId", ""),
            client_order_id=o.get("orderLinkId", ""),
            symbol=symbol,
            side=SIDE_LONG if side_str == "Buy" else SIDE_SHORT,
            quantity=qty,
            price=float(o.get("price", 0) or 0),
            filled_quantity=filled,
            avg_fill_price=avg_price,
            status=st,
            timestamp_ms=int(o.get("createdTime", 0) or 0),
        )

    # ==========================================================
    # TP/SL
    # ==========================================================
    def set_position_tp_sl(
        self,
        symbol: str,
        side: int,
        take_profit_price: Optional[float] = None,
        stop_loss_price: Optional[float] = None,
    ) -> bool:
        ex_sym = self._to_ex_symbol(symbol)
        body: Dict[str, Any] = {"symbol": ex_sym}
        if take_profit_price:
            body["takeProfit"] = str(self._round_price(symbol, take_profit_price))
            body["tpTriggerBy"] = "LastPrice"
        if stop_loss_price:
            body["stopLoss"] = str(self._round_price(symbol, stop_loss_price))
            body["slTriggerBy"] = "LastPrice"
        if not (take_profit_price or stop_loss_price):
            return False
        try:
            self._request("POST", "/v5/position/trading-stop", body=body, signed=True, category="linear")
            return True
        except Exception as e:
            logger.warning(f"[Bybit] 设置TP/SL失败 {symbol}: {e}")
            return False

    # ==========================================================
    # WebSocket 行情
    # ==========================================================
    def start_ws(self, symbols: List[str], on_ticker=None, on_kline=None) -> None:
        if not symbols:
            return
        self._ws_symbols = symbols
        self._ws_on_ticker = on_ticker
        self._ws_on_kline = on_kline
        self._ws_stop.clear()

        def _run():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._ws_loop = loop
            loop.run_until_complete(self._ws_loop_main())

        self._ws_thread = threading.Thread(target=_run, daemon=True)
        self._ws_thread.start()
        logger.info(f"[{self.EXCHANGE_NAME}] WS 启动，订阅 {len(symbols)} 个品种")

    def stop_ws(self) -> None:
        self._ws_stop.set()
        if self._ws_loop:
            try:
                asyncio.run_coroutine_threadsafe(self._ws_stop_async(), self._ws_loop)
            except Exception:
                pass
        if self._ws_thread:
            self._ws_thread.join(timeout=3)
        logger.info(f"[{self.EXCHANGE_NAME}] WS 已停止")

    async def _ws_stop_async(self):
        if self._ws_conn:
            try:
                await self._ws_conn.close()
            except Exception:
                pass

    async def _ws_loop_main(self):
        try:
            import websockets
        except ImportError:
            logger.error("[Bybit] websockets 未安装，WS 行情不可用")
            return

        # 订阅 topics
        topics = []
        for sym in self._ws_symbols:
            ex_sym = self._to_ex_symbol(sym)
            topics.append(f"tickers.{ex_sym}")
            topics.append(f"kline.60.{ex_sym}")
            topics.append(f"kline.240.{ex_sym}")

        while not self._ws_stop.is_set():
            try:
                async with websockets.connect(self.WS_URL, ping_interval=20, ping_timeout=10) as ws:
                    sub_msg = {"op": "subscribe", "args": topics}
                    await ws.send(json.dumps(sub_msg))
                    logger.info(f"[{self.EXCHANGE_NAME}] WS 订阅成功 {len(topics)} 个topic")

                    while not self._ws_stop.is_set():
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=30)
                        except asyncio.TimeoutError:
                            await ws.send(json.dumps({"op": "ping"}))
                            continue

                        try:
                            msg = json.loads(raw)
                        except Exception:
                            continue

                        topic_name = msg.get("topic", "")
                        data = msg.get("data", {})

                        # Ticker
                        if topic_name.startswith("tickers."):
                            ex_sym = topic_name.replace("tickers.", "")
                            sym = self._from_ex_symbol(ex_sym)
                            if self._ws_on_ticker and data:
                                last = float(data.get("lastPrice", 0))
                                prev = float(data.get("prevPrice24h", 0) or 0)
                                chg = ((last - prev) / prev * 100) if prev > 0 else 0
                                t = Ticker(
                                    symbol=sym,
                                    last_price=last,
                                    bid_price=float(data.get("bid1Price", 0) or 0),
                                    ask_price=float(data.get("ask1Price", 0) or 0),
                                    high_24h=float(data.get("highPrice24h", 0) or 0),
                                    low_24h=float(data.get("lowPrice24h", 0) or 0),
                                    volume_24h=float(data.get("volume24h", 0) or 0),
                                    change_pct_24h=chg,
                                    timestamp_ms=int(data.get("ts", time.time() * 1000)),
                                )
                                self._ws_on_ticker(t)

                        # Kline
                        elif topic_name.startswith("kline."):
                            parts = topic_name.split(".")
                            if len(parts) >= 3:
                                interval_str = parts[1]
                                ex_sym = ".".join(parts[2:])
                                sym = self._from_ex_symbol(ex_sym)
                                tf = {"60": "1h", "240": "4h"}.get(interval_str, "1h")
                                for k_data in data if isinstance(data, list) else [data]:
                                    if not isinstance(k_data, dict):
                                        continue
                                    start_ms = int(k_data.get("start", 0))
                                    confirm = k_data.get("confirm", "0") == "1"
                                    candle = Candle(
                                        symbol=sym, timeframe=tf,
                                        open_time_ms=start_ms,
                                        open=float(k_data.get("open", 0)),
                                        high=float(k_data.get("high", 0)),
                                        low=float(k_data.get("low", 0)),
                                        close=float(k_data.get("close", 0)),
                                        volume=float(k_data.get("volume", 0)),
                                        close_time_ms=start_ms + _tf_ms(tf) - 1,
                                    )
                                    if self._ws_on_kline:
                                        self._ws_on_kline(candle, confirm)

            except Exception as e:
                if self._ws_stop.is_set():
                    break
                logger.warning(f"[{self.EXCHANGE_NAME}] WS 断线重连: {e}")
                time.sleep(3)
