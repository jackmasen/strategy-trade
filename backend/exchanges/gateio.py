"""
Gate.io v4 API 客户端 — USDT 永续合约
支持：加密货币(BTC/ETH/SOL) + 贵金属(XAU黄金/XAG白银) + 能源(WTI原油) + 美股(TSLA/NVDA/AAPL等)

API文档：https://www.gate.io/docs/developers/apiv4/zh_CN/
签名：HMAC-SHA512，格式：timestamp + method + path + body
Header: KEY=api_key, SIGN=signature, Timestamp=timestamp
"""
from __future__ import annotations

import asyncio
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


def _tf_ms(timeframe: str) -> int:
    m = {
        "1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000,
        "1h": 3_600_000, "2h": 7_200_000, "3h": 10_800_000, "4h": 14_400_000, "6h": 21_600_000,
        "12h": 43_200_000, "1d": 86_400_000,
    }
    return m.get(timeframe, 3_600_000)


# Gate.io 原生支持的 K线周期（与 v4 API interval 对应）
# 不原生支持的周期需要从更小周期聚合
NATIVE_TF_MAP = {
    "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
    "1h": "1h", "2h": "2h", "4h": "4h", "6h": "6h", "12h": "12h",
    "1d": "1d", "1w": "1w",
}

# 需要聚合的周期 -> 源周期（Gate.io 不原生支持，从更小周期聚合）
AGGREGATED_TF_MAP = {
    "3m": "1m",    # 3m 从 1m K线聚合
    "3h": "1h",    # 3h 从 1h K线聚合
    "1M": "1d",    # 月线从日线聚合
}


def _is_native_tf(timeframe: str) -> bool:
    """判断周期是否为 Gate.io 原生支持"""
    return timeframe in NATIVE_TF_MAP


def _get_aggregate_source(timeframe: str) -> Optional[str]:
    """获取聚合源周期（不支持的周期返回 None）"""
    return AGGREGATED_TF_MAP.get(timeframe)


class GateioFuturesClient(ExchangeClientBase):
    """Gate.io v4 API — USDT 永续合约，含 TradFi 商品/美股"""

    EXCHANGE_NAME = "Gate.io"

    SYMBOL_MAP = {
        # 加密货币
        "BTC": "BTC_USDT",
        "ETH": "ETH_USDT",
        "SOL": "SOL_USDT",
        # 贵金属
        "XAU": "XAU_USDT",
        "XAG": "XAG_USDT",
        # 能源 (WTI 原油永续)
        "WTI": "WTI_USDT",
        # 美股-科技
        "TSLA": "TSLA_USDT",
        "NVDA": "NVDA_USDT",
        "AAPL": "AAPL_USDT",
        "MSFT": "MSFT_USDT",
        # 美股-半导体
        "SKHYNIX": "SKHYNIX_USDT",
        "SNDK": "SNDK_USDT",
        "INTC": "INTC_USDT",
        "AMD": "AMD_USDT",
        # 美股-消费
        "KO": "KO_USDT",
        "PG": "PG_USDT",
        "PEP": "PEP_USDT",
        "MCD": "MCD_USDT",
        # 美股-零售
        "WMT": "WMT_USDT",
        # 美股-医药
        "JNJ": "JNJ_USDT",
        # 美股-金融
        "JPM": "JPM_USDT",
        # 美股-AI/加密概念
        "MSTR": "MSTR_USDT",
        "COIN": "COIN_USDT",
        "PLTR": "PLTR_USDT",
        "SMCI": "SMCI_USDT",
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
            self.BASE_URL = getattr(s, 'GATEIO_BASE_URL', '') or "https://fx-api-testnet.gateio.ws/api/v4"
            self.WS_URL = "wss://fx-ws-testnet.gateio.ws/v4/ws/usdt"
        else:
            self.BASE_URL = getattr(s, 'GATEIO_BASE_URL', '') or "https://api.gateio.ws/api/v4"
            self.WS_URL = "wss://fx-ws.gateio.ws/v4/ws/usdt"

        self._session = requests.Session()
        self._ws_loop: Optional[asyncio.AbstractEventLoop] = None
        self._ws_thread: Optional[threading.Thread] = None
        self._ws_stop = threading.Event()
        self._ws_conn = None
        self._ws_symbols: List[str] = []
        self._ws_timeframes: List[str] = []
        self._ws_on_ticker: Optional[Callable[[Ticker], Any]] = None
        self._ws_on_kline: Optional[Callable[[Candle, bool], Any]] = None

    # ==========================================================
    # Gate.io v4 签名
    # 签名格式：HMAC-SHA512(timestamp + method + path + body)
    # Header: KEY / SIGN / Timestamp
    # ==========================================================
    def _sign(self, timestamp: str, method: str, path: str, body_str: str) -> str:
        prehash = f"{timestamp}{method.upper()}{path}{body_str}"
        return hmac.new(
            self.api_secret.encode("utf-8"),
            prehash.encode("utf-8"),
            hashlib.sha512,
        ).hexdigest()

    def _request(
        self, method: str, path: str,
        params: Optional[Dict] = None,
        body: Optional[Dict] = None,
        signed: bool = True,
    ) -> Any:
        url = f"{self.BASE_URL}{path}"
        ts = str(int(time.time()))

        headers = {"Content-Type": "application/json"}
        body_str = ""

        if method.upper() == "GET":
            if params is None:
                params = {}
            if params:
                query_str = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
                url = f"{url}?{query_str}"
                # 签名 path 含 query string
                sign_path = f"{path}?{query_str}"
            else:
                sign_path = path
        else:
            sign_path = path
            if body is not None:
                body_str = json.dumps(body, separators=(",", ":"))

        if signed:
            sign = self._sign(ts, method, sign_path, body_str)
            headers["KEY"] = self.api_key
            headers["SIGN"] = sign
            headers["Timestamp"] = ts

        try:
            if method.upper() == "GET":
                resp = self._session.get(url, headers=headers, timeout=10)
            elif method.upper() == "POST":
                resp = self._session.post(url, headers=headers, data=body_str, timeout=10)
            elif method.upper() == "DELETE":
                resp = self._session.delete(url, headers=headers, data=body_str, timeout=10)
            else:
                resp = self._session.request(method, url, headers=headers, data=body_str, timeout=10)
            data = resp.json()
        except Exception as e:
            raise ExchangeError(f"Gate.io 请求异常: {e}")

        # Gate.io 错误处理：非 2xx 状态码或含 error 字段
        if isinstance(data, dict) and data.get("error"):
            err = data.get("error", {})
            code = err.get("code", 0)
            msg = err.get("message", "")
            # 余额不足
            if code == 80001 or "insufficient balance" in msg.lower():
                raise InsufficientBalanceError(f"Gate.io 余额不足: {msg}")
            # 订单不存在
            if code == 80002 or "order not found" in msg.lower():
                raise OrderNotFoundError(f"Gate.io 订单不存在: {msg}")
            raise ExchangeError(f"Gate.io API 错误: code={code} msg={msg}")

        if resp.status_code >= 400:
            raise ExchangeError(f"Gate.io HTTP {resp.status_code}: {resp.text[:200]}")

        return data

    # ==========================================================
    # 连接 / 关闭
    # ==========================================================
    def connect(self) -> None:
        try:
            # 获取合约列表，缓存精度信息
            result = self._request("GET", "/futures/usdt/contracts", signed=False)
            for item in result if isinstance(result, list) else result.get("contracts", []):
                sym = item.get("name", "")
                # 数量精度（下单步长）
                order_size_min = item.get("order_size_min", "0.001")
                # 价格精度（tick_size）
                quanto_multiplier = item.get("quanto_multiplier", "0.01")
                # 使用 order_price_round / mark_price_round 作为价格精度
                price_precision = item.get("order_price_round", "0.01")
                self._step_size_cache[sym] = Decimal(str(order_size_min))
                self._tick_size_cache[sym] = Decimal(str(price_precision))
            logger.info(f"[{self.EXCHANGE_NAME}] 交易规则缓存完成, 共 {len(self._step_size_cache)} 个符号")
        except Exception as e:
            logger.warning(f"[{self.EXCHANGE_NAME}] 拉取 contracts 失败，使用默认精度: {e}")

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
            result = self._request("GET", "/futures/usdt/tickers", params={"contract": ex_sym}, signed=False)
        except Exception as e:
            raise ExchangeError(f"Gate.io 拉取行情失败: {e}")

        items = result if isinstance(result, list) else result.get("tickers", [])
        if not items:
            raise ExchangeError(f"Gate.io 无行情数据: {ex_sym}")
        d = items[0] if isinstance(items, list) else items

        last_price = float(d.get("last", 0))
        prev_price = float(d.get("low_24h", 0) or 0)
        # Gate.io 返回 change_percentage 是百分比字符串，如 "5.12" 表示 +5.12%
        change_pct = float(d.get("change_percentage", 0) or 0)

        return Ticker(
            symbol=symbol,
            last_price=last_price,
            bid_price=float(d.get("highest_bid", 0) or 0),
            ask_price=float(d.get("lowest_ask", 0) or 0),
            high_24h=float(d.get("high_24h", 0) or 0),
            low_24h=float(d.get("low_24h", 0) or 0),
            volume_24h=float(d.get("volume_24h", 0) or 0),
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

        # 判断是否需要聚合
        agg_source = _get_aggregate_source(timeframe)
        if agg_source:
            return self._fetch_aggregated_klines(symbol, timeframe, agg_source, limit, end_time)

        # 原生支持的周期：直接拉取
        tf = NATIVE_TF_MAP.get(timeframe, timeframe)
        try:
            params: Dict[str, Any] = {"contract": ex_sym, "interval": tf, "limit": str(min(limit, 1000))}
            if end_time:
                params["end"] = str(end_time)
            result = self._request("GET", "/futures/usdt/candlesticks", params=params, signed=False)
        except Exception as e:
            raise ExchangeError(f"Gate.io 拉取K线失败: {e}")

        candles: List[Candle] = []
        # Gate.io 返回：[[timestamp, volume, close, high, low, open], ...] 按时间升序
        for k in result if isinstance(result, list) else result.get("candlesticks", []):
            if not isinstance(k, list) or len(k) < 6:
                continue
            open_time_ms = int(float(k[0]) * 1000)
            candles.append(Candle(
                symbol=symbol, timeframe=timeframe,
                open_time_ms=open_time_ms,
                open=float(k[5]),
                high=float(k[3]),
                low=float(k[4]),
                close=float(k[2]),
                volume=float(k[1]),
                close_time_ms=open_time_ms + _tf_ms(timeframe) - 1,
            ))
        return candles

    def _fetch_aggregated_klines(
        self, symbol: str, target_tf: str, source_tf: str, limit: int = 200, end_time: int = None,
    ) -> List[Candle]:
        """从更小周期 K 线聚合生成目标周期 K 线（如 3h 从 1h 聚合）"""
        target_ms = _tf_ms(target_tf)
        source_ms = _tf_ms(source_tf)
        ratio = target_ms // source_ms
        if ratio <= 1:
            raise ExchangeError(f"聚合周期错误: {target_tf} 不能从 {source_tf} 聚合")

        # 多拉 ratio 倍的源 K 线，确保能凑够 limit 根目标 K 线
        source_limit = min(limit * ratio + ratio, 1000)
        source_candles = self.fetch_klines(symbol, source_tf, limit=source_limit, end_time=end_time)
        if not source_candles:
            return []

        # 聚合：按目标周期边界分组
        aggregated: List[Candle] = []
        group: List[Candle] = []

        for c in source_candles:
            # 计算该根源 K 线所属的目标周期开盘时间
            target_open_ms = (c.open_time_ms // target_ms) * target_ms
            if not group:
                group = [c]
            else:
                prev_target_open = (group[0].open_time_ms // target_ms) * target_ms
                if prev_target_open == target_open_ms:
                    group.append(c)
                else:
                    # 上一组聚合完成
                    if len(group) == ratio:
                        aggregated.append(self._merge_candles(symbol, target_tf, group))
                    group = [c]

        # 处理最后一组
        if group and len(group) == ratio:
            aggregated.append(self._merge_candles(symbol, target_tf, group))

        return aggregated[-limit:]

    @staticmethod
    def _merge_candles(symbol: str, timeframe: str, group: List[Candle]) -> Candle:
        """将多根小周期 K 线合并为一根大周期 K 线"""
        first = group[0]
        last = group[-1]
        high = max(c.high for c in group)
        low = min(c.low for c in group)
        volume = sum(c.volume for c in group)
        target_ms = _tf_ms(timeframe)
        open_ms = (first.open_time_ms // target_ms) * target_ms
        return Candle(
            symbol=symbol, timeframe=timeframe,
            open_time_ms=open_ms,
            open=first.open,
            high=high,
            low=low,
            close=last.close,
            volume=volume,
            close_time_ms=open_ms + target_ms - 1,
        )

    # ==========================================================
    # 行情：盘口
    # ==========================================================
    def fetch_orderbook(self, symbol: str, limit: int = 20) -> OrderBook:
        ex_sym = self._to_ex_symbol(symbol)
        try:
            result = self._request("GET", "/futures/usdt/order_book", params={
                "contract": ex_sym, "limit": str(limit),
            }, signed=False)
        except Exception as e:
            raise ExchangeError(f"Gate.io 拉取深度失败: {e}")

        bids = []
        total = 0.0
        for b in result.get("bids", []):
            qty = float(b[1])
            total += qty
            bids.append(OrderBookEntry(price=float(b[0]), quantity=qty, total=total))
        asks = []
        total = 0.0
        for a in result.get("asks", []):
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
            result = self._request("GET", "/futures/usdt/trades", params={
                "contract": ex_sym, "limit": str(limit),
            }, signed=False)
        except Exception as e:
            raise ExchangeError(f"Gate.io 拉取成交失败: {e}")

        trades: List[PublicTrade] = []
        for t in result if isinstance(result, list) else result.get("trades", []):
            size = float(t.get("size", 0))
            price = float(t.get("price", 0))
            # Gate.io: size > 0 表示买入，size < 0 表示卖出
            is_buyer_maker = size < 0
            trades.append(PublicTrade(
                symbol=symbol,
                trade_id=str(t.get("id", "")),
                price=price,
                quantity=abs(size),
                quote_qty=price * abs(size),
                side=SIDE_LONG if size > 0 else SIDE_SHORT,
                timestamp_ms=int(float(t.get("create_time_ms", time.time() * 1000))),
                is_buyer_maker=is_buyer_maker,
            ))
        return trades

    # ==========================================================
    # 持仓量（从 ticker 中获取）
    # ==========================================================
    def fetch_open_interest(self, symbol: str) -> OpenInterest:
        ex_sym = self._to_ex_symbol(symbol)
        try:
            result = self._request("GET", "/futures/usdt/tickers", params={"contract": ex_sym}, signed=False)
        except Exception as e:
            raise ExchangeError(f"Gate.io 拉取持仓量失败: {e}")

        items = result if isinstance(result, list) else result.get("tickers", [])
        if not items:
            return OpenInterest(symbol=symbol)
        d = items[0] if isinstance(items, list) else items
        oi = float(d.get("open_interest", 0) or 0)
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
            result = self._request("GET", "/futures/usdt/accounts", signed=True)
        except Exception as e:
            raise ExchangeError(f"Gate.io 拉取余额失败: {e}")

        if isinstance(result, list):
            acc = result[0] if result else {}
        else:
            acc = result

        total = float(acc.get("total", 0) or 0)
        available = float(acc.get("available", 0) or 0)
        used = float(acc.get("order_margin", 0) or 0) + float(acc.get("position_margin", 0) or 0)
        upnl = float(acc.get("unrealised_pnl", 0) or 0)
        wallet = float(acc.get("total", 0) or 0)
        return Balance(
            total=total + upnl, available=available, used_margin=used,
            unrealized_pnl=upnl, balance=wallet, currency="USDT",
        )

    # ==========================================================
    # 账户：持仓
    # ==========================================================
    def fetch_positions(self, symbols: Optional[List[str]] = None) -> List[Position]:
        try:
            result = self._request("GET", "/futures/usdt/positions", signed=True)
        except Exception as e:
            raise ExchangeError(f"Gate.io 拉取持仓失败: {e}")

        positions: List[Position] = []
        pos_list = result if isinstance(result, list) else result.get("positions", [])
        for p in pos_list:
            ex_sym = p.get("contract", "")
            sym = self._from_ex_symbol(ex_sym)
            if symbols and sym not in symbols:
                continue
            size = float(p.get("size", 0))
            if size == 0:
                continue
            # Gate.io: size > 0 表示多仓，size < 0 表示空仓
            side = SIDE_LONG if size > 0 else SIDE_SHORT
            qty = abs(size)
            positions.append(Position(
                symbol=sym,
                side=side,
                quantity=qty,
                entry_price=float(p.get("entry_price", 0) or 0),
                mark_price=float(p.get("mark_price", 0) or 0),
                unrealized_pnl=float(p.get("unrealised_pnl", 0) or 0),
                unrealized_pnl_pct=float(p.get("pnl", 0) or 0),
                leverage=int(float(p.get("leverage", 1) or 1)),
                margin=float(p.get("margin", 0) or 0),
                liquidation_price=float(p.get("liq_price", 0) or 0),
                take_profit_price=float(p.get("price_profit", 0) or 0),
                stop_loss_price=float(p.get("price_stop", 0) or 0),
                open_timestamp_ms=int(float(p.get("update_time_ms", 0) or 0)),
                raw_position_id=p.get("position_id", ""),
            ))
        return positions

    # ==========================================================
    # 交易：设置杠杆
    # ==========================================================
    def set_leverage(self, symbol: str, leverage: int) -> bool:
        ex_sym = self._to_ex_symbol(symbol)
        try:
            self._request("POST", f"/futures/usdt/positions/{ex_sym}/leverage", body={
                "leverage": str(leverage),
            }, signed=True)
            return True
        except Exception as e:
            logger.warning(f"[Gate.io] 设置杠杆失败 {symbol}: {e}")
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
        qty = self._round_qty(symbol, quantity)

        # Gate.io: size > 0 = 买入开多 / 卖出平空；size < 0 = 卖出开空 / 买入平多
        size = qty if side == SIDE_LONG else -qty

        body: Dict[str, Any] = {
            "contract": ex_sym,
            "size": str(size),
            "price": str(self._round_price(symbol, price)) if price and order_type == ORDER_TYPE_LIMIT else "0",
            "tif": "ioc" if order_type == ORDER_TYPE_MARKET else "gtc",
        }
        if order_type == ORDER_TYPE_MARKET:
            body["price"] = "0"  # 市价单价格设为 0

        # TP/SL：通过 price_profit / price_stop 字段
        if take_profit_price:
            body["price_profit"] = str(self._round_price(symbol, take_profit_price))
        elif take_profit_pct and take_profit_pct > 0:
            # 按百分比计算止盈价
            ref_price = price or self._get_last_price(symbol)
            if ref_price > 0:
                if side == SIDE_LONG:
                    tp_price = ref_price * (1 + take_profit_pct / 100)
                else:
                    tp_price = ref_price * (1 - take_profit_pct / 100)
                body["price_profit"] = str(self._round_price(symbol, tp_price))

        if stop_loss_price:
            body["price_stop"] = str(self._round_price(symbol, stop_loss_price))
        elif stop_loss_pct and stop_loss_pct > 0:
            ref_price = price or self._get_last_price(symbol)
            if ref_price > 0:
                if side == SIDE_LONG:
                    sl_price = ref_price * (1 - stop_loss_pct / 100)
                else:
                    sl_price = ref_price * (1 + stop_loss_pct / 100)
                body["price_stop"] = str(self._round_price(symbol, sl_price))

        if client_order_id:
            body["text"] = client_order_id[:32]

        try:
            result = self._request("POST", "/futures/usdt/orders", body=body, signed=True)
        except ExchangeError as e:
            return Order(
                symbol=symbol, side=side, quantity=qty,
                order_type=order_type, price=price or 0,
                status=ORDER_STATUS_FAILED, error_msg=str(e),
                timestamp_ms=int(time.time() * 1000),
            )

        oid = str(result.get("id", "") or result.get("order_id", ""))
        filled = abs(float(result.get("size", 0) or 0))
        avg_price = float(result.get("fill_price", 0) or 0)
        status_str = result.get("status", "open")

        st = ORDER_STATUS_PENDING
        if status_str in ("finished", "closed"):
            st = ORDER_STATUS_FILLED
        elif status_str == "open":
            st = ORDER_STATUS_PARTIAL if filled > 0 else ORDER_STATUS_PENDING
        elif status_str == "cancelled":
            st = ORDER_STATUS_CANCELED
        elif status_str == "failed":
            st = ORDER_STATUS_FAILED

        return Order(
            exchange_order_id=oid,
            client_order_id=client_order_id,
            symbol=symbol, side=side,
            quantity=qty, price=price or 0,
            filled_quantity=filled,
            avg_fill_price=avg_price,
            status=st,
            timestamp_ms=int(float(result.get("create_time_ms", time.time() * 1000))),
        )

    def _get_last_price(self, symbol: str) -> float:
        """获取最新成交价（用于 TP/SL 百分比计算）"""
        try:
            t = self.fetch_ticker(symbol)
            return t.last_price
        except Exception:
            return 0.0

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
            raise ExchangeError(f"Gate.io 无持仓 {symbol}")
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
        try:
            self._request("DELETE", f"/futures/usdt/orders/{exchange_order_id}", params={
                "contract": ex_sym,
            }, signed=True)
            return True
        except OrderNotFoundError:
            return False
        except Exception:
            return False

    def cancel_all_open_orders(self, symbol: Optional[str] = None) -> int:
        params: Dict[str, Any] = {}
        if symbol:
            params["contract"] = self._to_ex_symbol(symbol)
        try:
            self._request("DELETE", "/futures/usdt/orders", params=params, signed=True)
            return 1
        except Exception:
            return 0

    # ==========================================================
    # 交易：查询订单
    # ==========================================================
    def fetch_order(self, symbol: str, exchange_order_id: str, client_order_id: str = "") -> Order:
        ex_sym = self._to_ex_symbol(symbol)
        try:
            result = self._request("GET", f"/futures/usdt/orders/{exchange_order_id}", params={
                "contract": ex_sym,
            }, signed=True)
        except OrderNotFoundError:
            raise
        except Exception as e:
            raise OrderNotFoundError(f"Gate.io 订单查询失败: {e}")

        o = result
        size = float(o.get("size", 0))
        side = SIDE_LONG if size > 0 else SIDE_SHORT
        qty = abs(size)
        filled = abs(float(o.get("left", qty) or 0))
        filled = qty - abs(float(o.get("left", 0) or 0))
        avg_price = float(o.get("fill_price", 0) or 0)
        status_str = o.get("status", "open")

        st = ORDER_STATUS_PENDING
        if status_str in ("finished", "closed"):
            st = ORDER_STATUS_FILLED
        elif status_str == "open":
            st = ORDER_STATUS_PARTIAL if filled > 0 else ORDER_STATUS_PENDING
        elif status_str == "cancelled":
            st = ORDER_STATUS_CANCELED
        elif status_str == "failed":
            st = ORDER_STATUS_FAILED

        return Order(
            exchange_order_id=str(o.get("id", "")),
            client_order_id=o.get("text", ""),
            symbol=symbol,
            side=side,
            quantity=qty,
            price=float(o.get("price", 0) or 0),
            filled_quantity=filled,
            avg_fill_price=avg_price,
            status=st,
            timestamp_ms=int(float(o.get("create_time_ms", 0) or 0)),
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
        body: Dict[str, Any] = {}
        if take_profit_price is not None:
            body["price_profit"] = str(self._round_price(symbol, take_profit_price))
        if stop_loss_price is not None:
            body["price_stop"] = str(self._round_price(symbol, stop_loss_price))
        if not (take_profit_price is not None or stop_loss_price is not None):
            return False
        try:
            self._request("POST", f"/futures/usdt/positions/{ex_sym}/risk_limit_structure", body=body, signed=True)
            return True
        except Exception as e:
            logger.warning(f"[Gate.io] 设置TP/SL失败 {symbol}: {e}")
            return False

    # ==========================================================
    # WebSocket 行情
    # ==========================================================
    def start_ws(self, symbols: List[str], on_ticker=None, on_kline=None, timeframes: Optional[List[str]] = None) -> None:
        if not symbols:
            return
        self._ws_symbols = symbols
        # 默认订阅 1h/4h；可传入更多周期（只订阅原生支持的）
        if timeframes is None:
            timeframes = ["1h", "4h"]
        # 过滤只保留原生支持的周期（聚合周期无法直接订阅）
        self._ws_timeframes = [tf for tf in timeframes if _is_native_tf(tf)]
        if not self._ws_timeframes:
            self._ws_timeframes = ["1h", "4h"]
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
        logger.info(f"[{self.EXCHANGE_NAME}] WS 启动，订阅 {len(symbols)} 个品种, 周期={self._ws_timeframes}")

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
            logger.error("[Gate.io] websockets 未安装，WS 行情不可用")
            return

        # 订阅 channels
        channels = []
        # 构建 interval -> timeframe 反向映射
        interval_to_tf = {NATIVE_TF_MAP[tf]: tf for tf in self._ws_timeframes if tf in NATIVE_TF_MAP}
        for sym in self._ws_symbols:
            ex_sym = self._to_ex_symbol(sym)
            channels.append({"channel": "futures.tickers", "payload": [ex_sym]})
            for interval in interval_to_tf.keys():
                channels.append({"channel": "futures.candlesticks", "payload": [interval, ex_sym]})

        while not self._ws_stop.is_set():
            try:
                async with websockets.connect(self.WS_URL, ping_interval=20, ping_timeout=10) as ws:
                    self._ws_conn = ws
                    # 订阅
                    for ch in channels:
                        sub_msg = {"time": int(time.time()), "channel": ch["channel"], "event": "subscribe", "payload": ch["payload"]}
                        await ws.send(json.dumps(sub_msg))
                    logger.info(f"[{self.EXCHANGE_NAME}] WS 订阅成功 {len(channels)} 个channel")

                    while not self._ws_stop.is_set():
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=30)
                        except asyncio.TimeoutError:
                            await ws.send(json.dumps({"time": int(time.time()), "channel": "futures.ping", "event": "ping"}))
                            continue

                        try:
                            msg = json.loads(raw)
                        except Exception:
                            continue

                        event = msg.get("event", "")
                        if event in ("subscribe", "unsubscribe", "pong"):
                            continue

                        channel = msg.get("channel", "")
                        data = msg.get("result", msg.get("data", []))

                        # Ticker
                        if channel == "futures.tickers":
                            ticker_list = data if isinstance(data, list) else [data]
                            for t_data in ticker_list:
                                ex_sym = t_data.get("contract", "")
                                sym = self._from_ex_symbol(ex_sym)
                                if self._ws_on_ticker and t_data:
                                    last = float(t_data.get("last", 0))
                                    change_pct = float(t_data.get("change_percentage", 0) or 0)
                                    t = Ticker(
                                        symbol=sym,
                                        last_price=last,
                                        bid_price=float(t_data.get("highest_bid", 0) or 0),
                                        ask_price=float(t_data.get("lowest_ask", 0) or 0),
                                        high_24h=float(t_data.get("high_24h", 0) or 0),
                                        low_24h=float(t_data.get("low_24h", 0) or 0),
                                        volume_24h=float(t_data.get("volume_24h", 0) or 0),
                                        change_pct_24h=change_pct,
                                        timestamp_ms=int(time.time() * 1000),
                                    )
                                    self._ws_on_ticker(t)

                        # Kline
                        elif channel == "futures.candlesticks":
                            kline_list = data if isinstance(data, list) else [data]
                            for k_data in kline_list:
                                if not isinstance(k_data, dict):
                                    continue
                                ex_sym = k_data.get("contract", "")
                                sym = self._from_ex_symbol(ex_sym)
                                interval_str = k_data.get("interval", "1h")
                                # 动态映射 interval -> timeframe
                                tf = None
                                for t, iv in NATIVE_TF_MAP.items():
                                    if iv == interval_str:
                                        tf = t
                                        break
                                if tf is None:
                                    tf = "1h"  # 兜底
                                start_ms = int(float(k_data.get("t", 0)) * 1000)
                                confirm = k_data.get("final", False) is True
                                candle = Candle(
                                    symbol=sym, timeframe=tf,
                                    open_time_ms=start_ms,
                                    open=float(k_data.get("o", 0)),
                                    high=float(k_data.get("h", 0)),
                                    low=float(k_data.get("l", 0)),
                                    close=float(k_data.get("c", 0)),
                                    volume=float(k_data.get("v", 0)),
                                    close_time_ms=start_ms + _tf_ms(tf) - 1,
                                )
                                if self._ws_on_kline:
                                    self._ws_on_kline(candle, confirm)

            except Exception as e:
                if self._ws_stop.is_set():
                    break
                logger.warning(f"[{self.EXCHANGE_NAME}] WS 断线重连: {e}")
                time.sleep(3)
