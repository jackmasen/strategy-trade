"""
OKX 统一账户 USDT本位 SWAP 永续合约 API 封装
统一账户模式：Trade/Account 接口走 /api/v5/*
签名方式：OKX v5 HMAC-SHA256(timestamp + method + path + body) + Base64
返回值统一成 _types.py dataclass
"""
from __future__ import annotations

import base64
import hmac
import hashlib
import time
import asyncio
import json
import threading
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, List, Optional, Callable, Any

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


class OKXFuturesClient(ExchangeClientBase):
    EXCHANGE_NAME = "OKX"

    SYMBOL_MAP = {
        # 加密货币
        "BTC": "BTC-USDT-SWAP",
        "ETH": "ETH-USDT-SWAP",
        "SOL": "SOL-USDT-SWAP",
        "SAND": "SAND-USDT-SWAP",
        "HBAR": "HBAR-USDT-SWAP",
        # 贵金属
        "XAU": "XAU-USDT-SWAP",  # OKX 有 XAU 合约
        "XAG": "XAG-USDT-SWAP",  # OKX 有 XAG 合约
        # 能源
        "WTI": "CL-USDT-SWAP",  # OKX WTI原油合约 (ICE CL)
        # 美股-科技
        "TSLA": "TSLA-USDT-SWAP",  # 特斯拉
        "NVDA": "NVDA-USDT-SWAP",  # 英伟达
        "AAPL": "AAPL-USDT-SWAP",  # 苹果
        "MSFT": "MSFT-USDT-SWAP",  # 微软
        # 美股-中概
        "TCEHY": "TCEHY-USDT-SWAP",  # 腾讯 ADR
        # 美股-半导体
        "SKHYNIX": "SKHYNIX-USDT-SWAP",  # SK海力士
        "SNDK": "SNDK-USDT-SWAP",        # 闪迪
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
            self.BASE_URL = "https://www.okx.com" if not s.OKX_BASE_URL else s.OKX_BASE_URL
            # 官方Demo: https://www.okx.com 也接受模拟盘请求(参数 x-simulated-trading: 1)
            self.USE_SIMULATED = True
        else:
            self.BASE_URL = s.OKX_BASE_URL or "https://www.okx.com"
            self.USE_SIMULATED = False
        self._session = requests.Session()
        # WS URL（正式/模拟盘同一地址，公共频道无需登录）
        self.WS_URL = "wss://ws.okx.com:8443/ws/v5/public"
        # --------- WebSocket 状态 ---------
        self._ws_loop: Optional[asyncio.AbstractEventLoop] = None
        self._ws_thread: Optional[threading.Thread] = None
        self._ws_stop = threading.Event()
        self._ws_conn = None
        self._ws_symbols: List[str] = []
        self._ws_on_ticker: Optional[Callable[[Ticker], Any]] = None
        self._ws_on_kline: Optional[Callable[[Candle, bool], Any]] = None

    # ==========================================================
    # OKX v5 签名
    # ==========================================================
    def _iso_timestamp(self) -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

    def _sign_okx(self, timestamp: str, method: str, request_path: str, body_str: str) -> str:
        prehash = f"{timestamp}{method.upper()}{request_path}{body_str}"
        digest = hmac.new(
            self.api_secret.encode("utf-8"),
            prehash.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        return base64.b64encode(digest).decode("utf-8")

    def _request(self, method: str, path: str, params: Optional[Dict] = None, body: Optional[Dict] = None, signed: bool = True) -> Dict:
        import json
        # GET -> query；POST -> json body
        qs = ""
        if params:
            qs = "?" + "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        request_path = path + qs
        body_str = json.dumps(body, separators=(",", ":")) if body and method.upper() != "GET" else ""

        headers = {
            "Content-Type": "application/json",
        }
        if signed:
            ts = self._iso_timestamp()
            headers["OK-ACCESS-KEY"] = self.api_key
            headers["OK-ACCESS-SIGN"] = self._sign_okx(ts, method, request_path, body_str)
            headers["OK-ACCESS-TIMESTAMP"] = ts
            headers["OK-ACCESS-PASSPHRASE"] = self.passphrase
            if self.USE_SIMULATED:
                headers["x-simulated-trading"] = "1"

        url = f"{self.BASE_URL}{request_path}"
        try:
            if method.upper() == "GET":
                r = self._session.request(method, url, headers=headers, timeout=30)
            else:
                r = self._session.request(method, url, json=body or {}, headers=headers, timeout=30)
        except Exception as e:
            raise ExchangeError(f"OKX HTTP请求失败: {e}")

        if r.status_code >= 400:
            raise ExchangeError(f"OKX HTTP {r.status_code}: {r.text[:300]}")
        try:
            j = r.json()
        except Exception:
            raise ExchangeError(f"OKX 返回非JSON: {r.text[:200]}")

        code = j.get("code", "")
        msg = j.get("msg", "")
        if code != "0":
            # code 文档: 51001余额不足  51603订单不存在
            if code in ("51001", "51008"):
                raise InsufficientBalanceError(msg or "余额不足")
            if code in ("51603", "51605"):
                raise OrderNotFoundError(msg or "订单不存在")
            raise ExchangeError(f"OKX API错误 code={code} msg={msg}")
        return j

    # ==========================================================
    # 生命周期
    # ==========================================================
    def connect(self) -> None:
        try:
            # 拉取 instruments 缓存精度
            resp = self._request("GET", "/api/v5/public/instruments", params={
                "instType": "SWAP",
            }, signed=False)
            for inst in resp.get("data", []):
                sym = self._from_ex_symbol(inst.get("instId", ""))
                if not sym:
                    continue
                lot_sz = inst.get("lotSz", "0.0001")
                tick_sz = inst.get("tickSz", "0.01")
                try:
                    self._step_size_cache[sym] = Decimal(lot_sz)
                    self._tick_size_cache[sym] = Decimal(tick_sz)
                except Exception:
                    pass
            logger.info(f"[{self.EXCHANGE_NAME}] 交易规则缓存完成, 共 {len(self._step_size_cache)} 个符号")
        except Exception as e:
            logger.warning(f"[{self.EXCHANGE_NAME}] 拉取 instruments 失败，使用默认精度: {e}")

    def close(self) -> None:
        try:
            self._session.close()
        except Exception:
            pass

    # ==========================================================
    # 余额 & 持仓
    # ==========================================================
    def fetch_balance(self) -> Balance:
        try:
            resp = self._request("GET", "/api/v5/account/balance", params={"ccy": "USDT"})
        except Exception as e:
            raise ExchangeError(f"拉取余额失败: {e}")
        bal = Balance()
        data = resp.get("data", [])
        if not data:
            return bal
        acc = data[0]
        # totalEq = 账户总权益
        details = acc.get("details", [])
        usdt = details[0] if details else {}
        bal.total = float(acc.get("totalEq", 0))
        bal.balance = float(usdt.get("cashBal", 0))
        bal.available = float(usdt.get("availEq", usdt.get("availBal", 0)))
        bal.unrealized_pnl = float(usdt.get("upl", 0))
        bal.used_margin = float(usdt.get("eq", 0)) - float(usdt.get("availEq", usdt.get("availBal", 0)))
        return bal

    def fetch_positions(self, symbols: Optional[List[str]] = None) -> List[Position]:
        params = {"instType": "SWAP"}
        if symbols:
            ids = ",".join(self._to_ex_symbol(s) for s in symbols)
            params["instId"] = ids
        try:
            resp = self._request("GET", "/api/v5/account/positions", params=params)
        except Exception as e:
            raise ExchangeError(f"拉取持仓失败: {e}")
        result: List[Position] = []
        sym_set = set(symbols) if symbols else None
        for p in resp.get("data", []):
            sym = self._from_ex_symbol(p.get("instId", ""))
            if sym_set and sym not in sym_set:
                continue
            pos_side = p.get("posSide", "")  # long / short / net
            amt = float(p.get("pos", 0))
            if amt == 0:
                continue
            if pos_side == "net":
                side = SIDE_LONG if amt > 0 else SIDE_SHORT
            else:
                side = SIDE_LONG if pos_side == "long" else SIDE_SHORT
            upl = float(p.get("upl", 0))
            notional = abs(float(p.get("notionalUsd", 1)))
            result.append(Position(
                symbol=sym,
                side=side,
                quantity=abs(amt),
                entry_price=float(p.get("avgPx", 0)),
                mark_price=float(p.get("markPx", 0)),
                unrealized_pnl=upl,
                unrealized_pnl_pct=upl / max(0.0001, notional) * 100,
                leverage=int(float(p.get("lever", 1))),
                margin=float(p.get("margin", 0)),
                liquidation_price=float(p.get("liqPx", 0)),
                take_profit_price=float(p.get("tpTriggerPx", 0) or 0),
                stop_loss_price=float(p.get("slTriggerPx", 0) or 0),
                open_timestamp_ms=int(p.get("cTime", 0)),
                raw_position_id=p.get("posId", ""),
            ))
        return result

    # ==========================================================
    # 下单 / 平仓 / 撤单
    # ==========================================================
    def set_leverage(self, symbol: str, leverage: int, side: Optional[int] = None, margin_mode: str = "cross") -> bool:
        """public 设置杠杆：OKX 需要方向，默认双向都设"""
        ex_sym = self._to_ex_symbol(symbol)
        sides_to_set = [side] if side else [SIDE_LONG, SIDE_SHORT]
        ok = True
        for sd in sides_to_set:
            pos_side = "long" if sd == SIDE_LONG else "short"
            try:
                self._request("POST", "/api/v5/account/set-leverage", body={
                    "instId": ex_sym,
                    "lever": str(leverage),
                    "mgnMode": margin_mode,
                    "posSide": pos_side,
                })
            except Exception as e:
                logger.warning(f"[OKX] 设置杠杆失败(symbol={symbol} lev={leverage} side={sd}): {e}")
                ok = False
        return ok

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
        # 1. 设置杠杆（带保证金模式）
        self.set_leverage(symbol, leverage, side, margin_mode=margin_mode)
        # 2. 下单数量精度
        qty = self._round_qty(symbol, quantity)
        if qty <= 0:
            raise ExchangeError(f"下单数量过小，经 stepSize 截断后为 0")
        td_mode = margin_mode  # "cross" 或 "isolated"
        pos_side = "long" if side == SIDE_LONG else "short"
        # OKX side: buy/sell；做多开=buy；做空开=sell
        side_str = "buy" if side == SIDE_LONG else "sell"

        body = {
            "instId": ex_sym,
            "tdMode": td_mode,
            "ccy": "USDT",
            "clOrdId": client_order_id or self._client_order_id(),
            "side": side_str,
            "posSide": pos_side,
            "ordType": "market" if order_type == ORDER_TYPE_MARKET else "limit",
            "sz": f"{qty}",
        }
        if order_type == ORDER_TYPE_LIMIT and price:
            body["px"] = f"{self._round_price(symbol, price)}"

        try:
            resp = self._request("POST", "/api/v5/trade/order", body=body)
        except InsufficientBalanceError:
            raise
        except OrderNotFoundError:
            raise
        except Exception as e:
            raise ExchangeError(f"下单失败: {e}")
        data = resp.get("data", [{}])[0]
        ord_id = data.get("ordId", "")
        cl_id = data.get("clOrdId", body["clOrdId"])
        # OKX 下单返回一般不直接带成交信息，需要查询订单详情（市价单通常秒成交）
        try:
            order = self.fetch_order(symbol, exchange_order_id=ord_id, client_order_id=cl_id)
        except Exception as e:
            logger.warning(f"[OKX] 下单后查订单失败，返回占位订单: {e}")
            order = Order(
                exchange_order_id=ord_id, client_order_id=cl_id,
                symbol=symbol, side=side, order_type=order_type,
                quantity=qty, price=price or 0,
                status=ORDER_STATUS_SUBMITTED,
                timestamp_ms=int(time.time() * 1000),
            )

        # 3. TP/SL —— OKX 用 /api/v5/trade/order-algo；优先绝对价，否则百分比换算
        tpsl_ok = True
        has_tp = take_profit_price is not None or (take_profit_pct is not None and take_profit_pct > 0)
        has_sl = stop_loss_price is not None or (stop_loss_pct is not None and stop_loss_pct > 0)
        if (has_tp or has_sl) and order.status in (ORDER_STATUS_FILLED, ORDER_STATUS_SUBMITTED) and order.avg_fill_price > 0:
            entry = order.avg_fill_price
            tp_abs = take_profit_price
            sl_abs = stop_loss_price
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
                self._set_algo_tp_sl_abs(symbol, side, tp_abs, sl_abs)
            except Exception as e:
                logger.error(f"[OKX] TP/SL设置失败(order_id={order.exchange_order_id}): {e} — 持仓无止损保护!")
                tpsl_ok = False
        if not tpsl_ok:
            order.error_msg = "TP/SL设置失败，持仓无止损保护"
        return order

    def _set_algo_tp_sl_abs(
        self, symbol: str, side: int,
        tp_price: Optional[float], sl_price: Optional[float],
    ):
        """OKX 用绝对价设置止盈止损算法单"""
        ex_sym = self._to_ex_symbol(symbol)
        pos_side = "long" if side == SIDE_LONG else "short"
        close_side = "sell" if side == SIDE_LONG else "buy"

        if tp_price and tp_price > 0:
            tp_body = {
                "instId": ex_sym, "tdMode": "cross",
                "side": close_side, "posSide": pos_side,
                "ordType": "take_profit",
                "sz": "0",
                "tpTriggerPx": f"{self._round_price(symbol, tp_price)}",
                "tpOrdPx": "-1",
                "tpTriggerPxType": "mark",
            }
            self._request("POST", "/api/v5/trade/order-algo", body=tp_body)

        if sl_price and sl_price > 0:
            sl_body = {
                "instId": ex_sym, "tdMode": "cross",
                "side": close_side, "posSide": pos_side,
                "ordType": "stop_loss",
                "sz": "0",
                "slTriggerPx": f"{self._round_price(symbol, sl_price)}",
                "slOrdPx": "-1",
                "slTriggerPxType": "mark",
            }
            self._request("POST", "/api/v5/trade/order-algo", body=sl_body)

    def close_position(
        self,
        symbol: str,
        side: int,
        quantity: Optional[float] = None,
        order_type: str = ORDER_TYPE_MARKET,
        price: Optional[float] = None,
        client_order_id: str = "",
    ) -> Order:
        # 查当前持仓
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

        close_side = SIDE_SHORT if side == SIDE_LONG else SIDE_LONG
        # 先取消该币TP/SL算法单(防止双重平仓)
        try:
            self._request("POST", "/api/v5/trade/cancel-algos", body={
                "instId": self._to_ex_symbol(symbol),
            })
        except Exception:
            pass
        return self.place_order(
            symbol=symbol, side=close_side, quantity=qty,
            order_type=order_type, price=price, leverage=1,
            client_order_id=client_order_id,
        )

    def cancel_order(self, symbol: str, exchange_order_id: str, client_order_id: str = "") -> bool:
        ex_sym = self._to_ex_symbol(symbol)
        body = {"instId": ex_sym}
        if exchange_order_id:
            body["ordId"] = exchange_order_id
        if client_order_id:
            body["clOrdId"] = client_order_id
        try:
            self._request("POST", "/api/v5/trade/cancel-order", body=body)
            return True
        except OrderNotFoundError:
            raise
        except Exception as e:
            raise ExchangeError(f"撤单失败: {e}")

    def cancel_all_open_orders(self, symbol: Optional[str] = None) -> int:
        if not symbol:
            # 全部撤单：遍历所有挂单再撤，为安全起见请指定 symbol
            raise ExchangeError("OKX全站撤单需指定 symbol")
        try:
            resp = self._request("POST", "/api/v5/trade/cancel-batch-orders", body={
                "instId": self._to_ex_symbol(symbol),
            })
            count = 0
            for d in resp.get("data", []):
                if d.get("sCode") == "0":
                    count += 1
            return count
        except Exception as e:
            raise ExchangeError(f"撤销全部挂单失败: {e}")

    def fetch_order(self, symbol: str, exchange_order_id: str, client_order_id: str = "") -> Order:
        ex_sym = self._to_ex_symbol(symbol)
        params = {"instId": ex_sym}
        if exchange_order_id:
            params["ordId"] = exchange_order_id
        if client_order_id:
            params["clOrdId"] = client_order_id
        try:
            resp = self._request("GET", "/api/v5/trade/order", params=params)
        except OrderNotFoundError:
            raise
        except Exception as e:
            raise ExchangeError(f"查询订单失败: {e}")
        data = resp.get("data", [])
        if not data:
            raise OrderNotFoundError("订单不存在")
        o = data[0]
        state_map = {
            "canceled": ORDER_STATUS_CANCELED,
            "live":     ORDER_STATUS_SUBMITTED,
            "partially_filled": ORDER_STATUS_PARTIAL,
            "filled":   ORDER_STATUS_FILLED,
            "mmp_canceled": ORDER_STATUS_CANCELED,
            "rejected": ORDER_STATUS_FAILED,
        }
        side_int = SIDE_LONG if o.get("side") == "buy" else SIDE_SHORT
        return Order(
            exchange_order_id=o.get("ordId", ""),
            client_order_id=o.get("clOrdId", ""),
            symbol=symbol,
            side=side_int,
            order_type=ORDER_TYPE_LIMIT if o.get("ordType") == "limit" else ORDER_TYPE_MARKET,
            quantity=float(o.get("sz", 0)),
            price=float(o.get("px", 0)),
            filled_quantity=float(o.get("accFillSz", 0)),
            avg_fill_price=float(o.get("avgPx", 0)),
            realized_pnl=float(o.get("pnl", 0)),
            fee=float(o.get("fee", 0)),
            status=state_map.get(o.get("state"), ORDER_STATUS_PENDING),
            error_msg=o.get("failReason", ""),
            timestamp_ms=int(o.get("uTime", o.get("cTime", int(time.time() * 1000)))),
        )

    # ==========================================================
    # 行情
    # ==========================================================
    def fetch_ticker(self, symbol: str) -> Ticker:
        ex_sym = self._to_ex_symbol(symbol)
        try:
            resp = self._request("GET", "/api/v5/market/ticker", params={"instId": ex_sym}, signed=False)
        except Exception as e:
            raise ExchangeError(f"拉取行情失败: {e}")
        data = resp.get("data", [{}])[0]
        last_price = float(data.get("last", 0))
        sod = float(data.get("sodUtc8", 0) or 0)
        change_pct = ((last_price - sod) / sod * 100) if sod > 0 else 0.0
        return Ticker(
            symbol=symbol,
            last_price=last_price,
            bid_price=float(data.get("bidPx", 0)),
            ask_price=float(data.get("askPx", 0)),
            high_24h=float(data.get("high24h", 0)),
            low_24h=float(data.get("low24h", 0)),
            volume_24h=float(data.get("vol24h", 0)),
            change_pct_24h=change_pct,
            timestamp_ms=int(data.get("ts", int(time.time() * 1000))),
        )

    def fetch_klines(
        self, symbol: str, timeframe: str, limit: int = 200, end_time: int = None,
    ) -> List[Candle]:
        ex_sym = self._to_ex_symbol(symbol)
        tf_map = {
            "1m": "1m", "5m": "5m", "15m": "15m",
            "1h": "1H", "4h": "4H", "1d": "1Dutc",
            "1w": "1Wutc", "1M": "1Mutc",
            "1y": "1Mutc",
        }
        tf = tf_map.get(timeframe, timeframe)
        try:
            params = {
                "instId": ex_sym, "bar": tf, "limit": str(limit),
            }
            if end_time:
                params["before"] = str(end_time)
            resp = self._request("GET", "/api/v5/market/candles", params=params, signed=False)
        except Exception as e:
            raise ExchangeError(f"拉取K线失败: {e}")
        candles: List[Candle] = []
        # OKX 返回：ts,o,h,l,c,vol,volCcy,volCcyQuote,confirm（按时间倒序）
        for k in reversed(resp.get("data", [])):
            candles.append(Candle(
                symbol=symbol, timeframe=timeframe,
                open_time_ms=int(k[0]),
                open=float(k[1]),
                high=float(k[2]),
                low=float(k[3]),
                close=float(k[4]),
                volume=float(k[5]),
                close_time_ms=int(k[0]) + _tf_ms(timeframe) - 1,
            ))
        return candles

    def fetch_orderbook(self, symbol: str, limit: int = 20) -> OrderBook:
        ex_sym = self._to_ex_symbol(symbol)
        try:
            resp = self._request("GET", "/api/v5/market/books", params={
                "instId": ex_sym, "sz": str(limit),
            }, signed=False)
        except Exception as e:
            raise ExchangeError(f"拉取深度失败: {e}")
        data = (resp.get("data") or [{}])[0]
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
            timestamp_ms=int(data.get("ts", time.time() * 1000)),
        )

    def fetch_recent_trades(self, symbol: str, limit: int = 50) -> List[PublicTrade]:
        ex_sym = self._to_ex_symbol(symbol)
        try:
            resp = self._request("GET", "/api/v5/market/trades", params={
                "instId": ex_sym, "limit": str(limit),
            }, signed=False)
        except Exception as e:
            raise ExchangeError(f"拉取近期成交失败: {e}")
        trades = []
        for t in resp.get("data", []):
            side = SIDE_LONG if t.get("side") == "buy" else SIDE_SHORT
            price = float(t.get("px", 0))
            qty = float(t.get("sz", 0))
            trades.append(PublicTrade(
                symbol=symbol,
                trade_id=str(t.get("tradeId", "")),
                price=price,
                quantity=qty,
                quote_qty=price * qty,
                side=side,
                timestamp_ms=int(t.get("ts", 0)),
                is_buyer_maker=(t.get("side") == "sell"),
            ))
        trades.sort(key=lambda x: x.timestamp_ms, reverse=True)
        return trades

    def fetch_open_interest(self, symbol: str) -> OpenInterest:
        ex_sym = self._to_ex_symbol(symbol)
        try:
            resp = self._request("GET", "/api/v5/public/open-interest", params={
                "instId": ex_sym,
            }, signed=False)
        except Exception as e:
            raise ExchangeError(f"拉取持仓量失败: {e}")
        data = (resp.get("data") or [{}])[0]
        oi = float(data.get("oi", 0))
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
            timestamp_ms=int(data.get("ts", time.time() * 1000)),
        )

    # ==========================================================
    # 单独调整 TP/SL
    # ==========================================================
    def set_position_tp_sl(
        self,
        symbol: str,
        side: int,
        take_profit_price: Optional[float] = None,
        stop_loss_price: Optional[float] = None,
    ) -> bool:
        ex_sym = self._to_ex_symbol(symbol)
        pos_side = "long" if side == SIDE_LONG else "short"
        close_side = "sell" if side == SIDE_LONG else "buy"
        # 先撤销已存在的 algo 单
        try:
            self._request("POST", "/api/v5/trade/cancel-algos", body={
                "instId": ex_sym,
            })
        except Exception:
            pass
        try:
            if take_profit_price:
                self._request("POST", "/api/v5/trade/order-algo", body={
                    "instId": ex_sym, "tdMode": "cross",
                    "side": close_side, "posSide": pos_side,
                    "ordType": "take_profit", "sz": "0",
                    "tpTriggerPx": f"{self._round_price(symbol, take_profit_price)}",
                    "tpOrdPx": "-1", "tpTriggerPxType": "mark",
                })
            if stop_loss_price:
                self._request("POST", "/api/v5/trade/order-algo", body={
                    "instId": ex_sym, "tdMode": "cross",
                    "side": close_side, "posSide": pos_side,
                    "ordType": "stop_loss", "sz": "0",
                    "slTriggerPx": f"{self._round_price(symbol, stop_loss_price)}",
                    "slOrdPx": "-1", "slTriggerPxType": "mark",
                })
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
        """订阅 OKX 公共频道：tickers / candle1H / candle4H"""
        if self._ws_thread and self._ws_thread.is_alive():
            logger.debug("[OKX] WS 已在运行，先停止再重启")
            self.stop_ws()
        self._ws_symbols = [s.upper() for s in symbols]
        self._ws_on_ticker = on_ticker
        self._ws_on_kline = on_kline
        self._ws_stop.clear()
        self._ws_thread = threading.Thread(
            target=self._ws_worker_entry, name="okx_ws", daemon=True,
        )
        self._ws_thread.start()

    def stop_ws(self) -> None:
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
        logger.info("[OKX] WS 已停止")

    # --------- WS 内部 ---------
    def _ws_worker_entry(self) -> None:
        try:
            asyncio.run(self._ws_main_async())
        except Exception as e:
            if not self._ws_stop.is_set():
                logger.warning(f"[OKX] WS 异常退出: {e}")

    async def _ws_close_async(self) -> None:
        if self._ws_conn:
            try:
                # 先发送 unsubscribe，减少服务器端资源占用
                await self._ws_conn.send(json.dumps({"op": "unsubscribe", "args": []}))
            except Exception:
                pass
            try:
                await self._ws_conn.close()
            except Exception:
                pass
            self._ws_conn = None

    async def _ws_main_async(self) -> None:
        try:
            import websockets
        except ImportError:
            logger.warning("[OKX] websockets 库未安装，WS 功能不可用（将使用 REST 轮询 fallback）")
            return
        self._ws_loop = asyncio.get_running_loop()

        # 构造订阅列表
        args: List[Dict] = []
        for sym in self._ws_symbols:
            ex_sym = self._to_ex_symbol(sym)  # 例 BTC-USDT-SWAP
            args.append({"channel": "tickers", "instId": ex_sym})
            args.append({"channel": "candle1H", "instId": ex_sym})
            args.append({"channel": "candle4H", "instId": ex_sym})
        if not args:
            return

        subscribe_payload = json.dumps({"op": "subscribe", "args": args})
        reconnect_delay = 1.0

        while not self._ws_stop.is_set():
            try:
                async with websockets.connect(
                    self.WS_URL, ping_interval=30, ping_timeout=20, close_timeout=3,
                ) as ws:
                    self._ws_conn = ws
                    reconnect_delay = 1.0
                    logger.info(f"[OKX] WS 已连接，订阅 {len(args)} 频道")
                    await ws.send(subscribe_payload)
                    # 定时发送 ping 保持连接（OKX 30s 内无消息会断开）
                    last_ping = time.time()
                    while not self._ws_stop.is_set():
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
                        except asyncio.TimeoutError:
                            # 心跳
                            if time.time() - last_ping > 20:
                                try:
                                    await ws.send("ping")
                                    last_ping = time.time()
                                except Exception:
                                    break
                            continue
                        if raw == "pong":
                            last_ping = time.time()
                            continue
                        try:
                            msg = json.loads(raw)
                        except Exception:
                            continue
                        self._ws_dispatch(msg)
            except Exception as e:
                if self._ws_stop.is_set():
                    break
                reconnect_delay = min(reconnect_delay * 1.5, 60.0)
                logger.info(f"[OKX] WS 断开，{reconnect_delay:.1f}s 后重连: {e}")
                await asyncio.sleep(reconnect_delay)

    def _ws_dispatch(self, msg: Dict) -> None:
        """解析 OKX WS 推送消息，调用回调"""
        if not isinstance(msg, dict):
            return
        # 心跳/订阅响应忽略
        evt = msg.get("event")
        if evt in ("subscribe", "unsubscribe", "login", "error"):
            if evt == "error":
                logger.debug(f"[OKX] WS 事件: {msg}")
            return
        arg = msg.get("arg") or {}
        channel = arg.get("channel", "")
        inst_id = arg.get("instId", "")
        # 根据 instId 反查 symbol
        symbol = None
        for s in self._ws_symbols:
            if self._to_ex_symbol(s) == inst_id:
                symbol = s
                break
        if not symbol:
            return
        data = msg.get("data") or []
        if not isinstance(data, list) or not data:
            return

        # 1) tickers
        if channel == "tickers":
            try:
                d = data[0]
                last = float(d.get("last", 0))
                sod = float(d.get("sodUtc0", 0) or 0)
                change_pct = ((last - sod) / sod * 100) if sod > 0 else 0.0
                t = Ticker(
                    symbol=symbol,
                    last_price=last,
                    bid_price=float(d.get("bidPx", 0)),
                    ask_price=float(d.get("askPx", 0)),
                    high_24h=float(d.get("high24h", 0)),
                    low_24h=float(d.get("low24h", 0)),
                    volume_24h=float(d.get("vol24h", 0)),
                    change_pct_24h=change_pct,
                    timestamp_ms=int(d.get("ts", int(time.time()*1000))),
                )
                if self._ws_on_ticker:
                    self._ws_on_ticker(t)
            except Exception:
                pass
            return

        # 2) candle1H / candle4H
        if channel.startswith("candle"):
            tf_raw = channel[len("candle"):]  # 1H / 4H
            tf = tf_raw.lower()  # 1h / 4h
            try:
                row = data[0]
                # OKX candles： [ts, o, h, l, c, vol, volCcy, volCcyQuote, confirm]
                ts = int(row[0])
                confirm = str(row[8]) if len(row) > 8 else "0"
                closed = confirm == "1"
                candle = Candle(
                    symbol=symbol,
                    timeframe=tf,
                    open_time_ms=ts,
                    open=float(row[1]),
                    high=float(row[2]),
                    low=float(row[3]),
                    close=float(row[4]),
                    volume=float(row[5]),
                    close_time_ms=ts + _tf_ms(tf) - 1,
                )
                if self._ws_on_kline:
                    self._ws_on_kline(candle, closed)
            except Exception:
                pass
            return


def _tf_ms(tf: str) -> int:
    m = {"1m": 60, "5m": 5*60, "15m": 15*60, "1h": 3600, "4h": 4*3600, "1d": 86400}
    return m.get(tf, 3600) * 1000
