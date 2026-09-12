"""
Gate.io API 客户端 — USDT 永续合约
支持：加密货币(BTC/ETH/SOL等) + 美股永续

Gate.io 期货API文档：https://docs.gate.com/docs/futures/en/
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable, Dict, List, Optional

import requests

from backend.core.logging_config import logger
from backend.config import get_settings
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


def _tf_seconds(timeframe: str) -> int:
    m = {
        "1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800,
        "1h": 3600, "2h": 7200, "4h": 14400, "6h": 21600,
        "8h": 28800, "12h": 43200, "1d": 86400, "1w": 604800,
    }
    return m.get(timeframe, 3600)


class GateFuturesClient(ExchangeClientBase):
    """Gate.io USDT永续合约客户端"""

    EXCHANGE_NAME = "Gate"

    SYMBOL_MAP = {
        # 加密货币
        "BTC": "BTC_USDT",
        "ETH": "ETH_USDT",
        "SOL": "SOL_USDT",
        "BNB": "BNB_USDT",
        "XRP": "XRP_USDT",
        "ADA": "ADA_USDT",
        "DOGE": "DOGE_USDT",
        "AVAX": "AVAX_USDT",
        "LINK": "LINK_USDT",
        # 贵金属
        "XAU": "XAU_USDT",
        "XAG": "XAG_USDT",
        # 能源
        "WTI": "WTI_USDT",
        # 美股
        "TSLA": "TSLA_USDT",
        "NVDA": "NVDA_USDT",
        "AAPL": "AAPL_USDT",
        "MSFT": "MSFT_USDT",
        "TCEHY": "TCEHY_USDT",
        "GOOGL": "GOOGL_USDT",
        "AMZN": "AMZN_USDT",
        "META": "META_USDT",
        "NFLX": "NFLX_USDT",
        "KO": "KO_USDT",
        "PG": "PG_USDT",
        "WMT": "WMT_USDT",
        "JNJ": "JNJ_USDT",
        "PEP": "PEP_USDT",
        "INTC": "INTC_USDT",
        "MCD": "MCD_USDT",
        "JPM": "JPM_USDT",
        "AMD": "AMD_USDT",
        "MSTR": "MSTR_USDT",
        "COIN": "COIN_USDT",
        "PLTR": "PLTR_USDT",
        "SMCI": "SMCI_USDT",
        "SKHYNIX": "SKHYNIX_USDT",
        "SNDK": "SNDK_USDT",
    }

    SETTLE = "usdt"

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
            self.BASE_URL = getattr(s, 'GATE_BASE_URL', '') or "https://fx-api-testnet.gateio.ws"
        else:
            self.BASE_URL = getattr(s, 'GATE_BASE_URL', '') or "https://api.gateio.ws"

        self._session = requests.Session()

    # ==========================================================
    # Gate.io v4 签名
    # ==========================================================
    def _sign(self, method: str, path: str, query: str, body: str, ts: str) -> str:
        body_hash = hashlib.sha512(body.encode("utf-8")).hexdigest()
        payload = f"{method}\n{path}\n{query}\n{body_hash}\n{ts}"
        return hmac.new(
            self.api_secret.encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha512,
        ).hexdigest()

    def _request(
        self,
        method: str,
        path: str,
        params: Optional[Dict] = None,
        body: Optional[Dict] = None,
        signed: bool = True,
    ) -> Any:
        url = f"{self.BASE_URL}{path}"
        query_str = ""
        body_str = ""

        if method.upper() == "GET":
            if params:
                query_str = "&".join(f"{k}={v}" for k, v in params.items())
                if query_str:
                    url = f"{url}?{query_str}"
        else:
            if body:
                body_str = json.dumps(body, separators=(",", ":"))

        ts = str(int(time.time()))
        headers = {"Content-Type": "application/json"}

        if signed:
            sign = self._sign(method.upper(), path, query_str, body_str, ts)
            headers["KEY"] = self.api_key
            headers["SIGN"] = sign
            headers["Timestamp"] = ts

        try:
            if method.upper() == "GET":
                resp = self._session.get(url, headers=headers, timeout=10)
            else:
                resp = self._session.post(url, headers=headers, data=body_str, timeout=10)
            data = resp.json()
        except Exception as e:
            raise ExchangeError(f"Gate 请求异常: {e}")

        if resp.status_code >= 400:
            err_label = data.get("label", "") if isinstance(data, dict) else ""
            err_msg = data.get("message", "") if isinstance(data, dict) else str(data)
            raise ExchangeError(f"Gate API 错误: HTTP {resp.status_code} {err_label} {err_msg}")

        return data

    # ==========================================================
    # 连接 / 关闭
    # ==========================================================
    def connect(self) -> None:
        try:
            contracts = self._request("GET", "/api/v4/futures/usdt/contracts", signed=False)
            for c in contracts:
                symbol = c.get("name", "")
                if not symbol:
                    continue
                qsize = c.get("quanto_multiplier", "0.0001")
                tsize = c.get("tick_size", "0.01")
                ex_sym = symbol.replace("_", "")
                self._step_size_cache[symbol] = Decimal(str(qsize))
                self._tick_size_cache[symbol] = Decimal(str(tsize))
            logger.info(f"[{self.EXCHANGE_NAME}] 交易规则缓存完成, 共 {len(self._step_size_cache)} 个符号")
        except Exception as e:
            logger.warning(f"[{self.EXCHANGE_NAME}] 拉取合约信息失败，使用默认精度: {e}")

    def close(self) -> None:
        try:
            self._session.close()
        except Exception:
            pass

    # ==========================================================
    # 行情：Ticker
    # ==========================================================
    def fetch_ticker(self, symbol: str) -> Ticker:
        ex_sym = self._to_ex_symbol(symbol)
        contract = f"{self.SETTLE}_{ex_sym}" if "_" not in ex_sym else ex_sym
        try:
            data = self._request("GET", f"/api/v4/futures/{self.SETTLE}/tickers",
                                 params={"contract": contract}, signed=False)
        except Exception as e:
            raise ExchangeError(f"Gate 拉取行情失败: {e}")

        if not data:
            raise ExchangeError(f"Gate 无行情数据: {ex_sym}")
        d = data[0] if isinstance(data, list) else data

        last_price = float(d.get("last", 0))
        change_pct = float(d.get("change_percentage", 0) or 0)

        return Ticker(
            symbol=symbol,
            last_price=last_price,
            bid_price=float(d.get("bid", 0) or d.get("bid_0", 0) or 0),
            ask_price=float(d.get("ask", 0) or d.get("ask_0", 0) or 0),
            high_24h=float(d.get("high", 0) or 0),
            low_24h=float(d.get("low", 0) or 0),
            volume_24h=float(d.get("volume", 0) or 0),
            change_pct_24h=change_pct,
            timestamp_ms=int(time.time() * 1000),
        )

    # ==========================================================
    # 行情：K线
    # ==========================================================
    def fetch_klines(
        self, symbol: str, timeframe: str, limit: int = 200, end_time: int = None,
    ) -> List[Candle]:
        ex_sym = self._to_ex_symbol(symbol)
        contract = f"{self.SETTLE}_{ex_sym}" if "_" not in ex_sym else ex_sym

        tf_map = {
            "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
            "1h": "1h", "2h": "2h", "4h": "4h", "6h": "6h",
            "8h": "8h", "12h": "12h", "1d": "1d", "1w": "7d",
        }
        interval = tf_map.get(timeframe, timeframe)

        params: Dict[str, Any] = {"contract": contract, "interval": interval, "limit": str(min(limit, 200))}
        if end_time:
            params["to"] = str(end_time)
        try:
            data = self._request("GET", f"/api/v4/futures/{self.SETTLE}/candlesticks",
                                 params=params, signed=False)
        except Exception as e:
            raise ExchangeError(f"Gate 拉取K线失败: {e}")

        candles: List[Candle] = []
        tf_sec = _tf_seconds(timeframe)
        if isinstance(data, list):
            sorted_data = sorted(data, key=lambda x: int(x.get("t", 0)))
            for k in sorted_data:
                open_time_ms = int(k.get("t", 0))
                candles.append(Candle(
                    symbol=symbol, timeframe=timeframe,
                    open_time_ms=open_time_ms,
                    open=float(k.get("o", 0)),
                    high=float(k.get("h", 0)),
                    low=float(k.get("l", 0)),
                    close=float(k.get("c", 0)),
                    volume=float(k.get("v", 0)) * float(k.get("q", 0) or 1),
                    close_time_ms=open_time_ms + tf_sec * 1000 - 1,
                ))
        return candles

    # ==========================================================
    # 行情：盘口
    # ==========================================================
    def fetch_orderbook(self, symbol: str, limit: int = 20) -> OrderBook:
        ex_sym = self._to_ex_symbol(symbol)
        contract = f"{self.SETTLE}_{ex_sym}" if "_" not in ex_sym else ex_sym
        try:
            data = self._request("GET", f"/api/v4/futures/{self.SETTLE}/order_book",
                                 params={"contract": contract, "limit": str(limit)}, signed=False)
        except Exception as e:
            raise ExchangeError(f"Gate 拉取深度失败: {e}")

        bids = []
        total = 0.0
        for b in data.get("bids", []):
            qty = float(b[1])
            total += qty
            bids.append(OrderBookEntry(price=float(b[0]), quantity=qty, total=total))
        asks = []
        total = 0.0
        for a in data.get("asks", []):
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
        contract = f"{self.SETTLE}_{ex_sym}" if "_" not in ex_sym else ex_sym
        try:
            data = self._request("GET", f"/api/v4/futures/{self.SETTLE}/my_trades",
                                 params={"contract": contract, "limit": str(limit)}, signed=False)
        except Exception as e:
            raise ExchangeError(f"Gate 拉取成交失败: {e}")

        trades: List[PublicTrade] = []
        if isinstance(data, list):
            for t in data:
                trades.append(PublicTrade(
                    symbol=symbol,
                    trade_id=str(t.get("id", "")),
                    price=float(t.get("price", 0)),
                    quantity=float(t.get("size", 0)),
                    quote_qty=float(t.get("price", 0)) * float(t.get("size", 0)),
                    side=SIDE_LONG if t.get("size", 0) > 0 else SIDE_SHORT,
                    timestamp_ms=int(t.get("create_time_ms", 0) or t.get("time", 0) or 0),
                    is_buyer_maker=False,
                ))
        return trades

    # ==========================================================
    # 持仓量
    # ==========================================================
    def fetch_open_interest(self, symbol: str) -> OpenInterest:
        ex_sym = self._to_ex_symbol(symbol)
        contract = f"{self.SETTLE}_{ex_sym}" if "_" not in ex_sym else ex_sym
        try:
            data = self._request("GET", f"/api/v4/futures/{self.SETTLE}/tickers",
                                 params={"contract": contract}, signed=False)
        except Exception as e:
            raise ExchangeError(f"Gate 拉取持仓量失败: {e}")

        d = data[0] if isinstance(data, list) else data
        oi = float(d.get("total_size", 0) or 0)
        last_price = float(d.get("last", 0) or 0)
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
            data = self._request("GET", f"/api/v4/futures/{self.SETTLE}/accounts", signed=True)
        except Exception as e:
            raise ExchangeError(f"Gate 拉取余额失败: {e}")

        total = float(data.get("total", 0) or 0)
        available = float(data.get("available", 0) or 0)
        used = float(data.get("order_margin", 0) or 0)
        upnl = float(data.get("unrealised_pnl", 0) or 0)
        return Balance(
            total=total, available=available, used_margin=used,
            unrealized_pnl=upnl, balance=total, currency="USDT",
        )

    # ==========================================================
    # 账户：持仓
    # ==========================================================
    def fetch_positions(self, symbols: Optional[List[str]] = None) -> List[Position]:
        try:
            data = self._request("GET", f"/api/v4/futures/{self.SETTLE}/positions", signed=True)
        except Exception as e:
            raise ExchangeError(f"Gate 拉取持仓失败: {e}")

        positions: List[Position] = []
        items = data if isinstance(data, list) else data.get("list", [])
        for p in items:
            contract = p.get("contract", "")
            ex_sym = contract.replace(f"{self.SETTLE}_", "") if contract.startswith(f"{self.SETTLE}_") else contract
            sym = self._from_ex_symbol(ex_sym)
            if symbols and sym not in symbols:
                continue
            size = float(p.get("size", 0) or 0)
            if size == 0:
                continue
            entry_price = float(p.get("entry_price", 0) or 0)
            mark_price = float(p.get("mark_price", 0) or 0)
            upnl = float(p.get("unrealised_pnl", 0) or 0)
            positions.append(Position(
                symbol=sym,
                side=SIDE_LONG if size > 0 else SIDE_SHORT,
                quantity=abs(size),
                entry_price=entry_price,
                mark_price=mark_price,
                unrealized_pnl=upnl,
                unrealized_pnl_pct=float(p.get("leverage", 1)) and upnl / (entry_price * abs(size) / float(p.get("leverage", 1)) * 100) if entry_price > 0 else 0,
                leverage=int(float(p.get("leverage", 1) or 1)),
                margin=float(p.get("margin", 0) or 0),
                liquidation_price=float(p.get("liq_price", 0) or 0),
                take_profit_price=float(p.get("take_profit", 0) or 0),
                stop_loss_price=float(p.get("stop_loss", 0) or 0),
                open_timestamp_ms=int(p.get("open_time_ms", 0) or 0),
                raw_position_id=str(p.get("id", "")),
            ))
        return positions

    # ==========================================================
    # 交易：设置杠杆
    # ==========================================================
    def set_leverage(self, symbol: str, leverage: int) -> bool:
        ex_sym = self._to_ex_symbol(symbol)
        contract = f"{self.SETTLE}_{ex_sym}" if "_" not in ex_sym else ex_sym
        try:
            self._request("POST", f"/api/v4/futures/{self.SETTLE}/positions",
                          params={"contract": contract}, body={"leverage": str(leverage)}, signed=True)
            return True
        except Exception as e:
            logger.warning(f"[Gate] 设置杠杆失败 {symbol}: {e}")
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
        contract = f"{self.SETTLE}_{ex_sym}" if "_" not in ex_sym else ex_sym
        size = abs(self._round_qty(symbol, quantity))
        if side == SIDE_SHORT:
            size = -size

        body: Dict[str, Any] = {
            "contract": contract,
            "size": str(size),
            "tif": "ioc" if order_type == ORDER_TYPE_MARKET else "poc",
            "reduce_only": False,
        }
        if order_type == ORDER_TYPE_MARKET:
            body["price"] = "0"
        else:
            body["price"] = str(self._round_price(symbol, price or 0))
        if client_order_id:
            body["text"] = client_order_id[:28]

        try:
            result = self._request("POST", f"/api/v4/futures/{self.SETTLE}/orders",
                                   body=body, signed=True)
        except ExchangeError as e:
            return Order(
                symbol=symbol, side=side, quantity=abs(size),
                order_type=order_type, price=price or 0,
                status=ORDER_STATUS_FAILED, error_msg=str(e),
                timestamp_ms=int(time.time() * 1000),
            )

        oid = str(result.get("id", ""))
        filled = float(result.get("size", 0) or 0)
        fill_price = float(result.get("fill_price", 0) or result.get("price", 0) or 0)

        return Order(
            exchange_order_id=oid,
            client_order_id=client_order_id,
            symbol=symbol, side=side,
            quantity=abs(float(size)),
            price=price or fill_price,
            filled_quantity=abs(filled),
            avg_fill_price=fill_price,
            status=ORDER_STATUS_FILLED if abs(filled) >= abs(size) * 0.99 else ORDER_STATUS_PARTIAL,
            timestamp_ms=int(result.get("create_time_ms", time.time() * 1000)),
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
            raise ExchangeError(f"Gate 无持仓 {symbol}")
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
        try:
            self._request("DELETE", f"/api/v4/futures/{self.SETTLE}/orders/{exchange_order_id}", signed=True)
            return True
        except Exception as e:
            logger.warning(f"[Gate] 撤单失败 {exchange_order_id}: {e}")
            return False

    def cancel_all_open_orders(self, symbol: str = "") -> int:
        params = {}
        if symbol:
            ex_sym = self._to_ex_symbol(symbol)
            params["contract"] = f"{self.SETTLE}_{ex_sym}" if "_" not in ex_sym else ex_sym
        try:
            self._request("DELETE", f"/api/v4/futures/{self.SETTLE}/orders", params=params, signed=True)
            return 1
        except Exception:
            return 0

    # ==========================================================
    # 交易：查询订单
    # ==========================================================
    def fetch_order(self, symbol: str, exchange_order_id: str = "", client_order_id: str = "") -> Order:
        try:
            if exchange_order_id:
                data = self._request("GET", f"/api/v4/futures/{self.SETTLE}/orders/{exchange_order_id}", signed=True)
            else:
                ex_sym = self._to_ex_symbol(symbol)
                contract = f"{self.SETTLE}_{ex_sym}" if "_" not in ex_sym else ex_sym
                data = self._request("GET", f"/api/v4/futures/{self.SETTLE}/orders",
                                     params={"contract": contract}, signed=True)
                if isinstance(data, list) and data:
                    data = data[0]
        except Exception as e:
            raise OrderNotFoundError(f"Gate 查询订单失败: {e}")

        return Order(
            exchange_order_id=str(data.get("id", "")),
            client_order_id=str(data.get("text", "")),
            symbol=symbol,
            side=SIDE_LONG if float(data.get("size", 0)) > 0 else SIDE_SHORT,
            quantity=abs(float(data.get("size", 0))),
            price=float(data.get("price", 0)),
            filled_quantity=abs(float(data.get("size", 0)) - float(data.get("left", 0))),
            avg_fill_price=float(data.get("fill_price", 0) or 0),
            status=ORDER_STATUS_FILLED if data.get("left") == "0" else ORDER_STATUS_PARTIAL,
            timestamp_ms=int(data.get("create_time_ms", 0) or 0),
        )

    # ==========================================================
    # 交易：设置止盈止损
    # ==========================================================
    def set_position_tp_sl(
        self,
        symbol: str,
        take_profit_price: Optional[float] = None,
        stop_loss_price: Optional[float] = None,
        position_id: str = "",
    ) -> bool:
        ex_sym = self._to_ex_symbol(symbol)
        contract = f"{self.SETTLE}_{ex_sym}" if "_" not in ex_sym else ex_sym
        body: Dict[str, Any] = {"contract": contract}
        if take_profit_price:
            body["take_profit"] = str(take_profit_price)
        if stop_loss_price:
            body["stop_loss"] = str(stop_loss_price)
        try:
            self._request("POST", f"/api/v4/futures/{self.SETTLE}/positions",
                          params={"contract": contract}, body=body, signed=True)
            return True
        except Exception as e:
            logger.warning(f"[Gate] 设置止盈止损失败 {symbol}: {e}")
            return False
