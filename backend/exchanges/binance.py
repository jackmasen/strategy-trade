"""
币安 Binance USDⓈ-M 永续合约 API 封装
优先使用 python-binance SDK；不可用时自动 fallback 到 HMAC signed HTTP 请求 + REST 直连
所有返回值统一成 _types.py dataclass
"""
from __future__ import annotations

import hashlib
import hmac
import time
import asyncio
import json
import threading
from decimal import Decimal
from typing import Dict, List, Optional, Callable, Any
from urllib.parse import urlencode

import requests

from backend.config import get_settings
from backend.core.logging_config import logger
from backend.core.exceptions import (
    ExchangeError, InsufficientBalanceError, OrderNotFoundError,
)
from ._types import (
    Balance, Position, Order, Ticker, Candle,
    OrderBook, OrderBookEntry, PublicTrade, OpenInterest,
    SIDE_LONG, SIDE_SHORT,
    ORDER_TYPE_MARKET, ORDER_TYPE_LIMIT,
    ORDER_STATUS_FILLED, ORDER_STATUS_SUBMITTED, ORDER_STATUS_CANCELED,
    ORDER_STATUS_PARTIAL, ORDER_STATUS_FAILED, ORDER_STATUS_PENDING,
)
from .base import ExchangeClientBase


class BinanceFuturesClient(ExchangeClientBase):
    EXCHANGE_NAME = "Binance"

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
            self.BASE_URL = s.BINANCE_BASE_URL or "https://testnet.binancefuture.com"
            self.WS_URL = "wss://stream.binancefuture.com/ws"
        else:
            self.BASE_URL = "https://fapi.binance.com"
            self.WS_URL = "wss://fstream.binance.com/ws"
        self._session = requests.Session()
        self._session.headers.update({"X-MBX-APIKEY": self.api_key})
        # python-binance 可选
        self._sdk_client = None
        try:
            from binance.cm_futures import CMFutures  # noqa
            from binance.um_futures import UMFutures
            self._sdk_client = UMFutures(
                key=api_key, secret=api_secret,
                base_url=self.BASE_URL,
            )
        except Exception:
            self._sdk_client = None
        # --------- WebSocket 状态 ---------
        self._ws_loop: Optional[asyncio.AbstractEventLoop] = None
        self._ws_thread: Optional[threading.Thread] = None
        self._ws_stop = threading.Event()
        self._ws_conn = None  # websockets 连接对象（在 loop 线程中访问）
        self._ws_symbols: List[str] = []
        self._ws_on_ticker: Optional[Callable[[Ticker], Any]] = None
        self._ws_on_kline: Optional[Callable[[Candle, bool], Any]] = None
        # --------- 时钟偏移校正（单位：ms）----------
        self._clock_offset_ms: int = 0
        self._clock_offset_valid: bool = False

    def _ensure_clock_offset(self):
        """获取 Binance 服务器时钟偏移并缓存，避免每次请求都校验"""
        if self._clock_offset_valid:
            return
        try:
            srv = self._request("GET", "/fapi/v1/time", signed=False)
            srv_time = int(srv.get("serverTime", 0))
            if srv_time > 0:
                local_ms = int(time.time() * 1000)
                self._clock_offset_ms = srv_time - local_ms
                self._clock_offset_valid = True
                logger.debug(f"[Binance] 时钟偏移校正: {self._clock_offset_ms:+d} ms")
        except Exception as e:
            logger.debug(f"[Binance] 时钟偏移校正失败（将使用默认容差）: {e}")

    # ==========================================================
    # 签名辅助
    # ==========================================================
    def _sign(self, params: Dict) -> Dict:
        if "timestamp" not in params:
            self._ensure_clock_offset()
            params["timestamp"] = int(time.time() * 1000) + self._clock_offset_ms
        if "recvWindow" not in params:
            params["recvWindow"] = 5000
        query = urlencode(params, True)
        sig = hmac.new(
            self.api_secret.encode("utf-8"),
            query.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        params["signature"] = sig
        return params

    def _request(self, method: str, path: str, signed: bool = False, params: Optional[Dict] = None, data: Optional[Dict] = None) -> Dict:
        url = f"{self.BASE_URL}{path}"
        p = dict(params or {})
        d = dict(data or {})
        if signed:
            if method.upper() == "GET":
                p = self._sign(p)
            else:
                d = self._sign(d)
        try:
            r = self._session.request(method, url, params=p, data=d, timeout=15)
        except Exception as e:
            raise ExchangeError(f"Binance HTTP请求失败: {e}")
        if r.status_code >= 400:
            try:
                j = r.json()
                msg = j.get("msg") or r.text
                code = j.get("code", 0)
            except Exception:
                msg = r.text; code = 0
            # 常见错误码 -> 具体异常
            if code in (-2010, -2019):
                raise InsufficientBalanceError(msg or "余额不足")
            if code == -2013:
                raise OrderNotFoundError(msg or "订单不存在")
            raise ExchangeError(f"币安API错误 code={code} msg={msg}")
        try:
            return r.json()
        except Exception:
            raise ExchangeError(f"币安返回非JSON: {r.text[:200]}")

    # ==========================================================
    # 生命周期
    # ==========================================================
    def connect(self) -> None:
        # 拉取交易规则并缓存 stepSize / tickSize
        try:
            exinfo = self._request("GET", "/fapi/v1/exchangeInfo", signed=False)
            for s in exinfo.get("symbols", []):
                sym = self._from_ex_symbol(s["symbol"])
                for f in s.get("filters", []):
                    if f["filterType"] == "LOT_SIZE":
                        self._step_size_cache[sym] = Decimal(f["stepSize"])
                    elif f["filterType"] == "PRICE_FILTER":
                        self._tick_size_cache[sym] = Decimal(f["tickSize"])
            logger.info(f"[{self.EXCHANGE_NAME}] 交易规则缓存完成, 共 {len(self._step_size_cache)} 个符号")
        except Exception as e:
            logger.warning(f"[{self.EXCHANGE_NAME}] 拉取 exchangeInfo 失败，使用默认精度: {e}")

    def close(self) -> None:
        try:
            self._session.close()
        except Exception:
            pass

    # ==========================================================
    # 余额 & 持仓
    # ==========================================================
    def fetch_balance(self) -> Balance:
        # 优先 SDK
        try:
            if self._sdk_client:
                info = self._sdk_client.balance()
            else:
                info = self._request("GET", "/fapi/v2/balance", signed=True)
        except Exception as e:
            raise ExchangeError(f"拉取余额失败: {e}")
        bal = Balance()
        for item in info:
            if item.get("asset") == "USDT":
                bal.total = float(item.get("crossWalletBalance", 0)) + float(item.get("crossUnPnl", 0))
                bal.balance = float(item.get("balance", 0))
                bal.available = float(item.get("availableBalance", 0))
                bal.unrealized_pnl = float(item.get("crossUnPnl", 0))
                break
        # 从 account 拉已用保证金
        try:
            if self._sdk_client:
                acc = self._sdk_client.account()
            else:
                acc = self._request("GET", "/fapi/v2/account", signed=True)
            bal.used_margin = float(acc.get("totalMarginBalance", 0)) - float(acc.get("availableBalance", 0))
        except Exception:
            pass
        return bal

    def fetch_positions(self, symbols: Optional[List[str]] = None) -> List[Position]:
        try:
            if self._sdk_client:
                data = self._sdk_client.get_position_risk()
            else:
                data = self._request("GET", "/fapi/v2/positionRisk", signed=True)
        except Exception as e:
            raise ExchangeError(f"拉取持仓失败: {e}")
        result: List[Position] = []
        syms_set = set(symbols) if symbols else None
        for p in data:
            sym = self._from_ex_symbol(p["symbol"])
            if syms_set and sym not in syms_set:
                continue
            amt = float(p.get("positionAmt", 0))
            if amt == 0:
                continue
            side = SIDE_LONG if amt > 0 else SIDE_SHORT
            pos = Position(
                symbol=sym,
                side=side,
                quantity=abs(amt),
                entry_price=float(p.get("entryPrice", 0)),
                mark_price=float(p.get("markPrice", 0)),
                unrealized_pnl=float(p.get("unRealizedProfit", 0)),
                unrealized_pnl_pct=float(p.get("unRealizedProfit", 0)) / max(0.0001, float(p.get("notional", 1))) * 100,
                leverage=int(p.get("leverage", 1)),
                margin=float(p.get("initialMargin", 0)),
                liquidation_price=float(p.get("liquidationPrice", 0)),
                take_profit_price=0.0,  # TP/SL 需从 /fapi/v1/openOrders 补查
                stop_loss_price=0.0,
                open_timestamp_ms=int(p.get("updateTime", 0)),
                raw_position_id=f"{p['symbol']}_{'LONG' if side == 1 else 'SHORT'}",
            )
            result.append(pos)
        return result

    # ==========================================================
    # 下单 / 平仓 / 撤单
    # ==========================================================
    def set_leverage(self, symbol: str, leverage: int) -> bool:
        """设置杠杆（public）"""
        try:
            if self._sdk_client:
                self._sdk_client.change_leverage(symbol=self._to_ex_symbol(symbol), leverage=leverage)
            else:
                self._request("POST", "/fapi/v1/leverage", signed=True, data={
                    "symbol": self._to_ex_symbol(symbol),
                    "leverage": leverage,
                })
            return True
        except Exception as e:
            logger.warning(f"[{self.EXCHANGE_NAME}] 设置杠杆失败(symbol={symbol} lev={leverage}): {e}")
            return False

    def _set_margin_mode(self, symbol: str, mode: str = "cross") -> None:
        try:
            if self._sdk_client:
                self._sdk_client.change_margin_type(symbol=self._to_ex_symbol(symbol), marginType=mode.upper())
            else:
                self._request("POST", "/fapi/v1/marginType", signed=True, data={
                    "symbol": self._to_ex_symbol(symbol),
                    "marginType": mode.upper(),
                })
        except Exception as e:
            logger.warning(f"[{self.EXCHANGE_NAME}] 设置保证金模式失败(symbol={symbol} mode={mode}): {e}")

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
        margin_mode: str = "cross",
    ) -> Order:
        ex_sym = self._to_ex_symbol(symbol)
        # 0. 设置杠杆与逐仓/全仓模式
        self.set_leverage(symbol, leverage)
        self._set_margin_mode(symbol, margin_mode)

        # 1. 下单
        qty = self._round_qty(symbol, quantity)
        if qty <= 0:
            raise ExchangeError(f"下单数量过小，经 stepSize 截断后为 0")
        side_str = "BUY" if side == SIDE_LONG else "SELL"
        params: Dict = {
            "symbol": ex_sym,
            "side": side_str,
            "type": order_type.upper(),
            "quantity": f"{qty}",
            "newClientOrderId": client_order_id or self._client_order_id(),
        }
        if order_type == ORDER_TYPE_LIMIT and price:
            params["price"] = f"{self._round_price(symbol, price)}"
            params["timeInForce"] = "GTX"
        try:
            if self._sdk_client:
                raw = self._sdk_client.new_order(**params)
            else:
                raw = self._request("POST", "/fapi/v1/order", signed=True, data=params)
        except InsufficientBalanceError:
            raise
        except OrderNotFoundError:
            raise
        except Exception as e:
            raise ExchangeError(f"下单失败: {e}")

        order = Order(
            exchange_order_id=str(raw.get("orderId", "")),
            client_order_id=raw.get("clientOrderId", ""),
            symbol=symbol,
            side=side,
            order_type=order_type,
            quantity=float(raw.get("origQty", qty)),
            price=float(raw.get("price", price or 0)),
            filled_quantity=float(raw.get("executedQty", 0)),
            avg_fill_price=float(raw.get("avgPrice", 0)),
            status=ORDER_STATUS_FILLED if raw.get("status") == "FILLED" else ORDER_STATUS_SUBMITTED,
            timestamp_ms=int(raw.get("updateTime", raw.get("transactTime", int(time.time()*1000)))),
        )
        # 如果是市价单但 avgPrice=0，自己拉一下 ticker 估算
        if order.avg_fill_price <= 0 and order.filled_quantity > 0:
            try:
                order.avg_fill_price = self.fetch_ticker(symbol).last_price
            except Exception:
                pass

        # 2. 设置 TP/SL (条件单) —— 优先绝对价模式，否则百分比模式
        tpsl_ok = True
        has_tp = take_profit_price is not None or (take_profit_pct is not None and take_profit_pct > 0)
        has_sl = stop_loss_price is not None or (stop_loss_pct is not None and stop_loss_pct > 0)
        if (has_tp or has_sl) and order.status == ORDER_STATUS_FILLED and order.avg_fill_price > 0:
            # 百分比转绝对价（若未传绝对价）
            tp_abs = take_profit_price
            sl_abs = stop_loss_price
            entry = order.avg_fill_price
            if tp_abs is None and take_profit_pct:
                if side == SIDE_LONG:
                    tp_abs = entry * (1 + take_profit_pct / 100)
                else:
                    tp_abs = entry * (1 - take_profit_pct / 100)
            if sl_abs is None and stop_loss_pct:
                if side == SIDE_LONG:
                    sl_abs = entry * (1 - stop_loss_pct / 100)
                else:
                    sl_abs = entry * (1 + stop_loss_pct / 100)
            try:
                self._set_tp_sl_condorders_abs(symbol, side, tp_abs, sl_abs)
            except Exception as e:
                logger.error(f"[{self.EXCHANGE_NAME}] TP/SL设置失败(order_id={order.exchange_order_id}): {e} — 持仓无止损保护!")
                tpsl_ok = False
        if not tpsl_ok:
            order.error_msg = "TP/SL设置失败，持仓无止损保护"

        return order

    def _set_tp_sl_condorders_abs(
        self, symbol: str, side: int,
        tp_price: Optional[float], sl_price: Optional[float],
    ):
        """用绝对价设置 TP/SL 条件单"""
        ex_sym = self._to_ex_symbol(symbol)
        # 平掉相反方向：做多平仓=SELL；做空平仓=BUY
        close_side = "SELL" if side == SIDE_LONG else "BUY"

        if tp_price and tp_price > 0:
            tp = self._round_price(symbol, tp_price)
            payload = {
                "symbol": ex_sym,
                "side": close_side,
                "type": "TAKE_PROFIT_MARKET",
                "closePosition": "true",
                "stopPrice": f"{tp}",
                "workingType": "MARK_PRICE",
                "newClientOrderId": self._client_order_id(),
            }
            if self._sdk_client:
                self._sdk_client.new_order(**payload)
            else:
                self._request("POST", "/fapi/v1/order", signed=True, data=payload)

        if sl_price and sl_price > 0:
            sl = self._round_price(symbol, sl_price)
            payload = {
                "symbol": ex_sym,
                "side": close_side,
                "type": "STOP_MARKET",
                "closePosition": "true",
                "stopPrice": f"{sl}",
                "workingType": "MARK_PRICE",
                "newClientOrderId": self._client_order_id(),
            }
            if self._sdk_client:
                self._sdk_client.new_order(**payload)
            else:
                self._request("POST", "/fapi/v1/order", signed=True, data=payload)

    def close_position(
        self,
        symbol: str,
        side: int,
        quantity: Optional[float] = None,
        order_type: str = ORDER_TYPE_MARKET,
        price: Optional[float] = None,
        client_order_id: str = "",
    ) -> Order:
        # 先找当前持仓数量
        positions = self.fetch_positions([symbol])
        target_qty = 0.0
        for p in positions:
            if p.symbol == symbol and p.side == side:
                target_qty = p.quantity
                break
        if target_qty <= 0:
            raise ExchangeError(f"{symbol} 无对应持仓可平")
        if quantity is None:
            qty = target_qty
        else:
            qty = min(quantity, target_qty)

        # 方向相反
        close_side = SIDE_SHORT if side == SIDE_LONG else SIDE_LONG
        # 先取消该方向已挂的 TP/SL（避免双重平仓）
        try:
            self.cancel_all_open_orders(symbol)
        except Exception:
            pass
        return self.place_order(
            symbol=symbol, side=close_side, quantity=qty,
            order_type=order_type, price=price, leverage=1,
            client_order_id=client_order_id,
        )

    def cancel_order(self, symbol: str, exchange_order_id: str, client_order_id: str = "") -> bool:
        ex_sym = self._to_ex_symbol(symbol)
        params = {"symbol": ex_sym}
        if exchange_order_id:
            params["orderId"] = int(exchange_order_id) if exchange_order_id.isdigit() else None
        if client_order_id:
            params["origClientOrderId"] = client_order_id
        try:
            if self._sdk_client:
                self._sdk_client.cancel_order(**{k: v for k, v in params.items() if v is not None})
            else:
                self._request("DELETE", "/fapi/v1/order", signed=True, data={k: v for k, v in params.items() if v is not None})
            return True
        except OrderNotFoundError:
            raise
        except Exception as e:
            raise ExchangeError(f"撤单失败: {e}")

    def cancel_all_open_orders(self, symbol: Optional[str] = None) -> int:
        if not symbol:
            # 全市场撤单，币安需要逐个 symbol 处理；为安全起见先抛出"请指定symbol"
            raise ExchangeError("币安全站撤单需指定 symbol")
        ex_sym = self._to_ex_symbol(symbol)
        try:
            if self._sdk_client:
                self._sdk_client.cancel_open_orders(symbol=ex_sym)
            else:
                self._request("DELETE", "/fapi/v1/allOpenOrders", signed=True, data={"symbol": ex_sym})
            return 99
        except Exception as e:
            raise ExchangeError(f"撤销全部挂单失败: {e}")

    def fetch_order(self, symbol: str, exchange_order_id: str, client_order_id: str = "") -> Order:
        ex_sym = self._to_ex_symbol(symbol)
        params = {"symbol": ex_sym}
        if exchange_order_id:
            params["orderId"] = int(exchange_order_id) if exchange_order_id.isdigit() else None
        if client_order_id:
            params["origClientOrderId"] = client_order_id
        try:
            if self._sdk_client:
                raw = self._sdk_client.query_order(**{k: v for k, v in params.items() if v is not None})
            else:
                raw = self._request("GET", "/fapi/v1/order", signed=True, params={k: v for k, v in params.items() if v is not None})
        except OrderNotFoundError:
            raise
        except Exception as e:
            raise ExchangeError(f"查询订单失败: {e}")
        status_map = {
            "NEW": ORDER_STATUS_SUBMITTED,
            "PARTIALLY_FILLED": ORDER_STATUS_PARTIAL,
            "FILLED": ORDER_STATUS_FILLED,
            "CANCELED": ORDER_STATUS_CANCELED,
            "EXPIRED": ORDER_STATUS_CANCELED,
            "REJECTED": ORDER_STATUS_FAILED,
        }
        side_map = {"BUY": SIDE_LONG, "SELL": SIDE_SHORT}
        return Order(
            exchange_order_id=str(raw.get("orderId", "")),
            client_order_id=raw.get("clientOrderId", ""),
            symbol=symbol,
            side=side_map.get(raw.get("side"), 0),
            order_type=ORDER_TYPE_LIMIT if raw.get("type") == "LIMIT" else ORDER_TYPE_MARKET,
            quantity=float(raw.get("origQty", 0)),
            price=float(raw.get("price", 0)),
            filled_quantity=float(raw.get("executedQty", 0)),
            avg_fill_price=float(raw.get("avgPrice", 0)),
            status=status_map.get(raw.get("status"), ORDER_STATUS_PENDING),
            timestamp_ms=int(raw.get("updateTime", raw.get("time", 0))),
        )

    # ==========================================================
    # 行情
    # ==========================================================
    def fetch_ticker(self, symbol: str) -> Ticker:
        ex_sym = self._to_ex_symbol(symbol)
        try:
            if self._sdk_client:
                data = self._sdk_client.ticker_24hr_price_change_statistics(symbol=ex_sym)
            else:
                data = self._request("GET", "/fapi/v1/ticker/24hr", params={"symbol": ex_sym})
        except Exception as e:
            raise ExchangeError(f"拉取行情失败: {e}")
        return Ticker(
            symbol=symbol,
            last_price=float(data.get("lastPrice", 0)),
            bid_price=float(data.get("bidPrice", 0)),
            ask_price=float(data.get("askPrice", 0)),
            high_24h=float(data.get("highPrice", 0)),
            low_24h=float(data.get("lowPrice", 0)),
            volume_24h=float(data.get("volume", 0)),
            change_pct_24h=float(data.get("priceChangePercent", 0)),
            timestamp_ms=int(time.time() * 1000),
        )

    def fetch_klines(
        self, symbol: str, timeframe: str, limit: int = 200, end_time: int = None,
    ) -> List[Candle]:
        ex_sym = self._to_ex_symbol(symbol)
        tf = {"1m":"1m","5m":"5m","15m":"15m","1h":"1h","4h":"4h","1d":"1d","1w":"1w","1M":"1M","1y":"1M"}.get(timeframe, timeframe)
        try:
            if self._sdk_client and not end_time:
                data = self._sdk_client.klines(symbol=ex_sym, interval=tf, limit=limit)
            else:
                params = {"symbol": ex_sym, "interval": tf, "limit": limit}
                if end_time:
                    params["endTime"] = end_time
                data = self._request("GET", "/fapi/v1/klines", params=params)
        except Exception as e:
            raise ExchangeError(f"拉取K线失败: {e}")
        candles: List[Candle] = []
        for k in data:
            candles.append(Candle(
                symbol=symbol,
                timeframe=timeframe,
                open_time_ms=int(k[0]),
                open=float(k[1]),
                high=float(k[2]),
                low=float(k[3]),
                close=float(k[4]),
                volume=float(k[5]),
                close_time_ms=int(k[6]),
            ))
        return candles

    def fetch_orderbook(self, symbol: str, limit: int = 20) -> OrderBook:
        ex_sym = self._to_ex_symbol(symbol)
        try:
            data = self._request("GET", "/fapi/v1/depth", params={"symbol": ex_sym, "limit": limit})
        except Exception as e:
            raise ExchangeError(f"拉取深度失败: {e}")
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
            symbol=symbol,
            bids=bids,
            asks=asks,
            timestamp_ms=int(data.get("E", time.time() * 1000)),
        )

    def fetch_recent_trades(self, symbol: str, limit: int = 50) -> List[PublicTrade]:
        ex_sym = self._to_ex_symbol(symbol)
        try:
            data = self._request("GET", "/fapi/v1/trades", params={"symbol": ex_sym, "limit": limit})
        except Exception as e:
            raise ExchangeError(f"拉取近期成交失败: {e}")
        trades = []
        for t in data:
            is_buyer_maker = t.get("isBuyerMaker", False)
            side = SIDE_SHORT if is_buyer_maker else SIDE_LONG  # 主动买入=1, 主动卖出=2
            price = float(t.get("price", 0))
            qty = float(t.get("qty", 0))
            trades.append(PublicTrade(
                symbol=symbol,
                trade_id=str(t.get("id", "")),
                price=price,
                quantity=qty,
                quote_qty=price * qty,
                side=side,
                timestamp_ms=int(t.get("time", 0)),
                is_buyer_maker=is_buyer_maker,
            ))
        trades.sort(key=lambda x: x.timestamp_ms, reverse=True)  # 最新在前
        return trades

    def fetch_open_interest(self, symbol: str) -> OpenInterest:
        ex_sym = self._to_ex_symbol(symbol)
        try:
            data = self._request("GET", "/fapi/v1/openInterest", params={"symbol": ex_sym})
        except Exception as e:
            raise ExchangeError(f"拉取持仓量失败: {e}")
        oi = float(data.get("openInterest", 0))
        # 估算 USDT 价值（用最近价，如不可用则用0）
        oi_usdt = 0.0
        try:
            ticker = self.fetch_ticker(symbol)
            oi_usdt = oi * ticker.last_price
        except Exception:
            pass
        return OpenInterest(
            symbol=symbol,
            open_interest=oi,
            open_interest_usdt=oi_usdt,
            timestamp_ms=int(data.get("time", time.time() * 1000)),
        )

    # ==========================================================
    # 设置持仓 TP/SL (单独调整)
    # ==========================================================
    def set_position_tp_sl(
        self,
        symbol: str,
        side: int,
        take_profit_price: Optional[float] = None,
        stop_loss_price: Optional[float] = None,
    ) -> bool:
        # 1) 先清掉旧 TP/SL
        try:
            self.cancel_all_open_orders(symbol)
        except Exception:
            pass
        # 2) 重新下发条件单
        ex_sym = self._to_ex_symbol(symbol)
        close_side = "SELL" if side == SIDE_LONG else "BUY"
        try:
            if take_profit_price:
                payload = {
                    "symbol": ex_sym, "side": close_side,
                    "type": "TAKE_PROFIT_MARKET", "closePosition": "true",
                    "stopPrice": f"{self._round_price(symbol, take_profit_price)}",
                    "workingType": "MARK_PRICE",
                    "newClientOrderId": self._client_order_id(),
                }
                if self._sdk_client: self._sdk_client.new_order(**payload)
                else: self._request("POST", "/fapi/v1/order", signed=True, data=payload)
            if stop_loss_price:
                payload = {
                    "symbol": ex_sym, "side": close_side,
                    "type": "STOP_MARKET", "closePosition": "true",
                    "stopPrice": f"{self._round_price(symbol, stop_loss_price)}",
                    "workingType": "MARK_PRICE",
                    "newClientOrderId": self._client_order_id(),
                }
                if self._sdk_client: self._sdk_client.new_order(**payload)
                else: self._request("POST", "/fapi/v1/order", signed=True, data=payload)
            return True
        except Exception as e:
            raise ExchangeError(f"调整TP/SL失败: {e}")

    # ==========================================================
    # WebSocket 行情推送
    # ==========================================================
    def start_ws(
        self,
        symbols: List[str],
        on_ticker=None,
        on_kline=None,
    ) -> None:
        """
        启动后台线程，订阅 Binance 公共 WS：
        - 24hr ticker: <sym>@ticker
        - K线 1h/4h: <sym>@kline_1h / @kline_4h
        on_ticker / on_kline 回调需在 O(1) 内完成，避免阻塞 WS 接收线程
        """
        if self._ws_thread and self._ws_thread.is_alive():
            logger.debug("[Binance] WS 已在运行，先停止再重启")
            self.stop_ws()
        self._ws_symbols = [s.upper() for s in symbols]
        self._ws_on_ticker = on_ticker
        self._ws_on_kline = on_kline
        self._ws_stop.clear()
        self._ws_thread = threading.Thread(
            target=self._ws_worker_entry, name="binance_ws", daemon=True,
        )
        self._ws_thread.start()

    def stop_ws(self) -> None:
        """停止 WS 连接与后台线程"""
        self._ws_stop.set()
        if self._ws_loop and self._ws_loop.is_running():
            try:
                asyncio.run_coroutine_threadsafe(self._ws_close_async(), self._ws_loop)
            except Exception:
                pass
        if self._ws_thread:
            self._ws_thread.join(timeout=3.0)
            self._ws_thread = None
        self._ws_loop = None
        self._ws_conn = None
        logger.info("[Binance] WS 已停止")

    # --------- WS 内部实现 ---------
    def _ws_worker_entry(self) -> None:
        try:
            asyncio.run(self._ws_main_async())
        except Exception as e:
            if not self._ws_stop.is_set():
                logger.warning(f"[Binance] WS 异常退出: {e}")

    async def _ws_close_async(self) -> None:
        if self._ws_conn:
            try:
                await self._ws_conn.close()
            except Exception:
                pass
            self._ws_conn = None

    async def _ws_main_async(self) -> None:
        try:
            import websockets
        except ImportError:
            logger.warning("[Binance] websockets 库未安装，WS 功能不可用（将使用 REST 轮询 fallback）")
            return
        self._ws_loop = asyncio.get_running_loop()

        # 构造订阅 streams：每个 symbol 订阅 ticker + 1h/4h K线
        streams: List[str] = []
        for sym in self._ws_symbols:
            ex_sym = self._to_ex_symbol(sym).lower()  # 例 btcusdt
            streams.append(f"{ex_sym}@ticker")
            streams.append(f"{ex_sym}@kline_1h")
            streams.append(f"{ex_sym}@kline_4h")
        if not streams:
            return
        # Binance WS URL 格式: wss://host/stream?streams=a/b/c
        url = f"{self.WS_URL}/stream?streams={'/'.join(streams)}"
        logger.info(f"[Binance] WS 连接: {self.WS_URL}  streams={len(streams)}")

        reconnect_delay = 1.0
        while not self._ws_stop.is_set():
            try:
                async with websockets.connect(url, ping_interval=30, ping_timeout=20, close_timeout=3) as ws:
                    self._ws_conn = ws
                    reconnect_delay = 1.0
                    logger.info(f"[Binance] WS 已连接, 订阅 {len(streams)} streams")
                    while not self._ws_stop.is_set():
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
                        except asyncio.TimeoutError:
                            continue
                        try:
                            msg = json.loads(raw)
                        except Exception:
                            continue
                        self._ws_dispatch(msg)
            except Exception as e:
                if self._ws_stop.is_set():
                    break
                logger.info(f"[Binance] WS 断开，{reconnect_delay:.1f}s 后重连: {e}")
                await asyncio.sleep(min(reconnect_delay, 10.0))
                reconnect_delay *= 1.5

    def _ws_dispatch(self, msg: Dict) -> None:
        """解析 Binance stream 消息，调用回调"""
        stream = msg.get("stream", "")
        data = msg.get("data") or {}
        if not stream or not isinstance(data, dict):
            return
        parts = stream.split("@", 1)
        if len(parts) != 2:
            return
        ex_sym_lower, channel = parts[0], parts[1]
        # ex_sym_lower 例 btcusdt → 反查 symbol（BTC）
        symbol = None
        for s in self._ws_symbols:
            if self._to_ex_symbol(s).lower() == ex_sym_lower:
                symbol = s
                break
        if not symbol:
            return

        # 1) ticker
        if channel == "ticker":
            try:
                t = Ticker(
                    symbol=symbol,
                    last_price=float(data.get("c", 0)),
                    bid_price=float(data.get("b", 0)),
                    ask_price=float(data.get("a", 0)),
                    high_24h=float(data.get("h", 0)),
                    low_24h=float(data.get("l", 0)),
                    volume_24h=float(data.get("v", 0)),
                    change_pct_24h=float(data.get("P", 0)),
                    timestamp_ms=int(data.get("E", int(time.time()*1000))),
                )
                if self._ws_on_ticker:
                    self._ws_on_ticker(t)
            except Exception:
                pass
            return

        # 2) kline
        if channel.startswith("kline_"):
            tf = channel[len("kline_"):]
            k = data.get("k") or {}
            closed = bool(k.get("x", False))
            try:
                candle = Candle(
                    symbol=symbol,
                    timeframe=tf,
                    open_time_ms=int(k.get("t", 0)),
                    open=float(k.get("o", 0)),
                    high=float(k.get("h", 0)),
                    low=float(k.get("l", 0)),
                    close=float(k.get("c", 0)),
                    volume=float(k.get("v", 0)),
                    close_time_ms=int(k.get("T", 0)),
                )
                if self._ws_on_kline:
                    self._ws_on_kline(candle, closed)
            except Exception:
                pass
            return
