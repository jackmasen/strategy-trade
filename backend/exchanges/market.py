"""
行情市场管理器 MarketManager (单例)
核心设计（对应经验 525474 的高频减压原则）：
  - WS 回调只做 O(1) 内存写入，绝不写DB/推前端/做策略
  - K线聚合在内存增量更新，周期闭合时才触发事件
  - 后台定时线程 (ticker_flush/klines_flush) 做批处理 + 推送到订阅者
  - 无真实 WS 时，自动退化为 REST 轮询 (FallbackPoller)，保证离线可用
  - 单例：MarketManager.get_instance() / 由 FastAPI lifespan 启动/关闭
"""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Set, Tuple

from backend.core.logging_config import logger
from ._types import Ticker, Candle, SIDE_LONG, SIDE_SHORT, OpenInterest
from .base import ExchangeClientBase


# 订阅回调类型
TickerCallback = Callable[[Ticker], None]
KlineCallback = Callable[[Candle, bool], None]   # (kline, closed)


# ---------------- K 线桶：增量聚合 ----------------
@dataclass
class _KlineBucket:
    candle: Candle
    _dirty: bool = True

    def update_tick(self, price: float, volume: float = 0.0) -> None:
        """tick 过来，更新当前 OHLCV"""
        if price <= 0:
            return
        if self.candle.open == 0:
            self.candle.open = price
        self.candle.close = price
        if price > self.candle.high or self.candle.high == 0:
            self.candle.high = price
        if price < self.candle.low or self.candle.low == 0:
            self.candle.low = price
        if volume > 0:
            self.candle.volume += volume
        self._dirty = True


# ---------------- 主管理器 ----------------
class MarketManager:
    _instance: Optional["MarketManager"] = None
    _instance_lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> "MarketManager":
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = MarketManager()
            return cls._instance

    def __init__(self):
        # 交易所 client
        self._clients: Dict[str, ExchangeClientBase] = {}  # key: f"{exchange}_{account_id}"
        # 主用 client（用来拉 REST/fallback）：第一个注册的
        self._primary_client: Optional[ExchangeClientBase] = None

        # ---------- 价格缓存 ----------
        self._price_lock = threading.Lock()
        self._tickers: Dict[str, Ticker] = {}
        self._tickers_prev: Dict[str, Ticker] = {}  # 上次 flush，用于判断是否变化

        # ---------- K 线缓存 ----------
        self._kline_lock = threading.Lock()
        # key: (symbol, timeframe)
        self._kline_history: Dict[Tuple[str, str], List[Candle]] = {}
        self._kline_open_bucket: Dict[Tuple[str, str], _KlineBucket] = {}

        # ---------- OI / 资金费率缓存 ----------
        self._oi_lock = threading.Lock()
        self._open_interest: Dict[str, OpenInterest] = {}
        self._oi_history: Dict[str, List[float]] = {}  # symbol -> [oi_usdt, ...] 最近60个
        self._funding_rate: Dict[str, float] = {}  # symbol -> funding_rate
        self._long_short_ratio: Dict[str, float] = {}  # symbol -> long/short ratio

        # ---------- 订阅 ----------
        self._sub_lock = threading.Lock()
        self._ticker_subs: Dict[str, Dict[str, TickerCallback]] = {}   # symbol -> {sub_id: cb}
        self._kline_subs: Dict[Tuple[str, str], Dict[str, KlineCallback]] = {}
        self._symbols_subscribed: Set[str] = set()

        # ---------- 生命周期 ----------
        self._running = False
        self._threads: List[threading.Thread] = []
        self._stop_event = threading.Event()

    # ==========================================================
    #  注册交易所 client
    # ==========================================================
    def register_client(self, client: ExchangeClientBase) -> None:
        key = f"{client.EXCHANGE_NAME}_{client.exchange_account_id}"
        self._clients[key] = client
        if self._primary_client is None:
            self._primary_client = client
        logger.info(f"[Market] 注册交易所 {key}, 主用={self._primary_client.EXCHANGE_NAME}")

    def has_client(self) -> bool:
        return self._primary_client is not None

    def reload_demo_client(self) -> None:
        """重新加载演示API客户端（管理员更新配置后调用）"""
        from backend.db.session import SessionLocal
        from backend.routers.exchange import _try_get_demo_client

        db = SessionLocal()
        try:
            client = _try_get_demo_client(db)
            if client:
                self.register_client(client)
                logger.info("[Market] 演示API客户端已刷新")
            else:
                logger.info("[Market] 演示API未启用或配置不完整")
        finally:
            db.close()

    # ==========================================================
    #  启动 / 关闭
    # ==========================================================
    def start(self, symbols: Optional[List[str]] = None) -> None:
        if self._running:
            return
        if symbols:
            for s in symbols:
                self.subscribe_ticker(s, lambda *a, **k: None)
        self._running = True
        self._stop_event.clear()

        # 1) 预加载历史 K 线 (for 指标)
        if self._primary_client:
            default_symbols = ["BTC", "ETH", "SOL", "XAU", "WTI", "SAND", "HBAR"]
            symbols_to_load = symbols or list(self._symbols_subscribed) or default_symbols
            for sym in symbols_to_load:
                for tf in ("1h", "4h"):
                    try:
                        self._prefetch_klines(sym, tf)
                    except Exception as e:
                        logger.warning(f"[Market] 预加载K线失败 {sym}{tf}: {e}")

        # 2) 启动主用 client 的 WS 行情（失败不影响，后台继续用 REST fallback）
        if self._primary_client:
            all_syms = list(symbols or self._symbols_subscribed) or ["BTC", "ETH", "SOL", "XAU", "WTI", "SAND", "HBAR"]
            try:
                self._primary_client.start_ws(
                    symbols=all_syms,
                    on_ticker=self._on_ws_ticker,
                    on_kline=self._on_ws_kline,
                )
                logger.info(f"[Market] WS 行情已启动 ({self._primary_client.EXCHANGE_NAME}), symbols={all_syms}")
            except Exception as e:
                logger.warning(f"[Market] WS 启动失败，将使用 REST fallback: {e}")

        # 3) 后台 flush ticker 线程 (每 1s)
        self._threads.append(self._spawn_daemon(self._ticker_flush_loop, name="mm_ticker_flush"))

        # 4) 后台 flush K 线 + 检查闭合 (每 1s)
        self._threads.append(self._spawn_daemon(self._kline_flush_loop, name="mm_kline_flush"))

        # 5) REST fallback 轮询线程 (每 5s；有 WS 时 WS 会覆盖其结果)
        self._threads.append(self._spawn_daemon(self._rest_fallback_loop, name="mm_rest_fallback"))

        # 6) OI / 资金费率 定时刷新线程 (每 60s)
        self._threads.append(self._spawn_daemon(self._oi_refresh_loop, name="mm_oi_refresh"))

        logger.info(f"[Market] 启动成功, symbols={list(self._symbols_subscribed)}")

    def stop(self) -> None:
        self._stop_event.set()
        self._running = False
        # 先停所有 WS 连接
        for c in self._clients.values():
            try:
                c.stop_ws()
            except Exception:
                pass
        for t in self._threads:
            t.join(timeout=3.0)
        self._threads.clear()
        logger.info("[Market] 已停止")

    # ==========================================================
    #  订阅接口（业务层调用）
    # ==========================================================
    def subscribe_ticker(self, symbol: str, callback: TickerCallback) -> str:
        sub_id = uuid.uuid4().hex[:12]
        with self._sub_lock:
            self._ticker_subs.setdefault(symbol, {})[sub_id] = callback
            self._symbols_subscribed.add(symbol)
        return sub_id

    def unsubscribe_ticker(self, symbol: str, sub_id: str) -> None:
        with self._sub_lock:
            cb_map = self._ticker_subs.get(symbol, {})
            cb_map.pop(sub_id, None)
            # 若没人订阅了，可以保留 symbol (fallback 仍需)

    def subscribe_kline(self, symbol: str, timeframe: str, callback: KlineCallback) -> str:
        sub_id = uuid.uuid4().hex[:12]
        with self._sub_lock:
            self._kline_subs.setdefault((symbol, timeframe), {})[sub_id] = callback
            self._symbols_subscribed.add(symbol)
        return sub_id

    # ==========================================================
    #  数据访问（读取内存 O(1)）
    # ==========================================================
    def get_price(self, symbol: str) -> Optional[float]:
        with self._price_lock:
            t = self._tickers.get(symbol)
            return t.last_price if t else None

    def get_ticker(self, symbol: str) -> Optional[Ticker]:
        with self._price_lock:
            t = self._tickers.get(symbol)
            return Ticker(**t.to_dict()) if t else None

    def get_klines(self, symbol: str, timeframe: str, limit: int = 200) -> List[Candle]:
        """获取指定品种周期K线，包含当前未闭合根（末尾）"""
        key = (symbol, timeframe)
        with self._kline_lock:
            hist = list(self._kline_history.get(key, []))
            # 追加未闭合桶
            bucket = self._kline_open_bucket.get(key)
            if bucket:
                hist = hist + [bucket.candle]
            # 预加载缺失（后台线程，不阻塞当前请求）
            if len(hist) < 50 and self._primary_client:
                import threading as _th
                _th.Thread(target=self._safe_prefetch, args=(symbol, timeframe), daemon=True).start()
            return hist[-limit:]

    # ============================================================
    #  OI / 资金费率
    # ============================================================
    def get_open_interest(self, symbol: str) -> Optional[OpenInterest]:
        """获取当前持仓量"""
        with self._oi_lock:
            oi = self._open_interest.get(symbol)
            return OpenInterest(**oi.to_dict()) if oi else None

    def get_oi_history(self, symbol: str, limit: int = 60) -> List[float]:
        """获取OI历史序列（USDT价值）"""
        with self._oi_lock:
            hist = list(self._oi_history.get(symbol, []))
            return hist[-limit:]

    def get_funding_rate(self, symbol: str) -> float:
        """获取资金费率（默认0.01%）"""
        with self._oi_lock:
            return self._funding_rate.get(symbol, 0.0001)

    def get_long_short_ratio(self, symbol: str) -> float:
        """获取多空比（默认1.0）"""
        with self._oi_lock:
            return self._long_short_ratio.get(symbol, 1.0)

    # ==========================================================
    #  WS 回调入口（必须 O(1)）
    # ==========================================================
    def on_ws_ticker(self, ticker: Ticker) -> None:
        """WS ticker 到达：只写缓存"""
        if not ticker or ticker.last_price <= 0:
            return
        sym = ticker.symbol
        with self._price_lock:
            self._tickers[sym] = ticker
        # 同步更新对应 1h/4h 的当前 K 桶
        self._update_open_kline_buckets(sym, ticker.last_price, ticker.volume_24h)

    def on_ws_kline(self, candle: Candle, closed: bool) -> None:
        """WS K线 到达：若 closed 就 append history，否则更新桶"""
        key = (candle.symbol, candle.timeframe)
        with self._kline_lock:
            if closed:
                hist = self._kline_history.setdefault(key, [])
                # 去重：若最后一根 open_time 相同就替换
                if hist and hist[-1].open_time_ms == candle.open_time_ms:
                    hist[-1] = candle
                else:
                    hist.append(candle)
                # 限制历史长度，防内存无限增长
                if len(hist) > 600:
                    hist[:] = hist[-600:]
                self._kline_open_bucket.pop(key, None)
            else:
                # 未闭合：直接放成 open bucket
                self._kline_open_bucket[key] = _KlineBucket(candle=Candle(**candle.to_dict()))

    # ==========================================================
    #  内部：K线桶更新
    # ==========================================================
    def _update_open_kline_buckets(self, symbol: str, price: float, volume: float) -> None:
        # 我们只维护 1h 和 4h (策略使用)；其他周期按需扩展
        tfs = ("1h", "4h")
        now_ms = int(time.time() * 1000)
        with self._kline_lock:
            for tf in tfs:
                key = (symbol, tf)
                bucket_ms = _tf_bucket_ms(tf)
                open_ms = (now_ms // bucket_ms) * bucket_ms
                close_ms = open_ms + bucket_ms - 1
                bucket = self._kline_open_bucket.get(key)
                if (not bucket) or bucket.candle.open_time_ms != open_ms:
                    # 周期推进：旧桶成历史
                    if bucket:
                        hist = self._kline_history.setdefault(key, [])
                        if not hist or hist[-1].open_time_ms != bucket.candle.open_time_ms:
                            hist.append(bucket.candle)
                            if len(hist) > 600:
                                hist[:] = hist[-600:]
                    # 新桶
                    c = Candle(
                        symbol=symbol, timeframe=tf,
                        open_time_ms=open_ms, close_time_ms=close_ms,
                        open=price, high=price, low=price, close=price, volume=0,
                    )
                    self._kline_open_bucket[key] = _KlineBucket(candle=c)
                else:
                    bucket.update_tick(price, 0)  # volume 已通过 volume_24h 反映，但K线量从WS kline获取

    # ==========================================================
    #  WS 回调（只做 O(1) 内存写入！）
    # ==========================================================
    def _on_ws_ticker(self, ticker: Ticker) -> None:
        """WS ticker: 写入价格缓存，并更新 1h/4h K线桶 OHLC"""
        with self._price_lock:
            self._tickers[ticker.symbol] = ticker
        # 同步更新 K 线桶的最新价
        price = ticker.last_price
        if price <= 0:
            return
        now_ms = int(time.time() * 1000)
        with self._kline_lock:
            for tf in ("1h", "4h"):
                key = (ticker.symbol, tf)
                bucket = self._kline_open_bucket.get(key)
                if bucket is None:
                    bucket_ms = _tf_bucket_ms(tf)
                    open_ms = (now_ms // bucket_ms) * bucket_ms
                    close_ms = open_ms + bucket_ms - 1
                    c = Candle(
                        symbol=ticker.symbol, timeframe=tf,
                        open_time_ms=open_ms, close_time_ms=close_ms,
                        open=price, high=price, low=price, close=price, volume=0,
                    )
                    self._kline_open_bucket[key] = _KlineBucket(candle=c)
                else:
                    bucket.update_tick(price, 0)

    def _on_ws_kline(self, candle: Candle, closed: bool) -> None:
        """WS kline: 直接覆盖 open bucket；如果 closed，则把旧桶落历史"""
        key = (candle.symbol, candle.timeframe)
        with self._kline_lock:
            if closed:
                # 写入历史（去重：按 open_time_ms）
                hist = list(self._kline_history.get(key, []))
                if hist and hist[-1].open_time_ms == candle.open_time_ms:
                    hist[-1] = candle
                else:
                    hist.append(candle)
                hist.sort(key=lambda c: c.open_time_ms)
                self._kline_history[key] = hist[-600:]
                # 清空当前桶（下一个 ticker 更新会自动重建）
                self._kline_open_bucket.pop(key, None)
            else:
                self._kline_open_bucket[key] = _KlineBucket(candle=candle)
            # 如果是 1h/4h K线闭合了，触发一次评分信号 -> flush 循环会通知订阅者，这里不用

    def _safe_prefetch(self, symbol: str, timeframe: str) -> None:
        try:
            self._prefetch_klines(symbol, timeframe)
        except Exception:
            pass

    def _prefetch_klines(self, symbol: str, timeframe: str) -> None:
        """启动时用 REST 预拉 200 根历史 K 线填充 memory"""
        if not self._primary_client:
            return
        key = (symbol, timeframe)
        data = self._primary_client.fetch_klines(symbol, timeframe, limit=200)
        if not data:
            return
        with self._kline_lock:
            # 去掉重复的当前桶
            existing = self._kline_history.get(key, [])
            existing_times = {c.open_time_ms for c in existing}
            merged = list(existing) + [c for c in data if c.open_time_ms not in existing_times]
            merged.sort(key=lambda c: c.open_time_ms)
            self._kline_history[key] = merged[-600:]
            # 如果最新的那根 close_time_ms > now，说明它是未闭合的，放到 open bucket
            if merged and merged[-1].close_time_ms > int(time.time() * 1000):
                last = merged.pop()
                self._kline_open_bucket[key] = _KlineBucket(candle=last)
                self._kline_history[key] = merged[-600:]
        logger.debug(f"[Market] 预加载 {symbol}{timeframe} 共 {len(data)} 根K线")

    # ==========================================================
    #  后台线程
    # ==========================================================
    def _spawn_daemon(self, target, name: str) -> threading.Thread:
        t = threading.Thread(target=target, name=name, daemon=True)
        t.start()
        return t

    def _ticker_flush_loop(self) -> None:
        """每 1s：比较价格是否变化 -> 通知订阅者（不做DB）"""
        while not self._stop_event.is_set():
            try:
                self._stop_event.wait(1.0)
                with self._price_lock, self._sub_lock:
                    for sym, cb_map in list(self._ticker_subs.items()):
                        ticker = self._tickers.get(sym)
                        if not ticker:
                            continue
                        prev = self._tickers_prev.get(sym)
                        changed = (
                            prev is None
                            or abs(ticker.last_price - prev.last_price) > 1e-8
                            or ticker.timestamp_ms != prev.timestamp_ms
                        )
                        if not changed or not cb_map:
                            continue
                        # 推送给每个订阅者
                        for _cid, cb in list(cb_map.items()):
                            try:
                                cb(ticker)
                            except Exception as e:
                                logger.debug(f"[Market] ticker 回调异常 {sym}: {e}")
                        self._tickers_prev[sym] = Ticker(**ticker.to_dict())
            except Exception as e:
                logger.debug(f"[Market] ticker_flush 异常: {e}")

    def _kline_flush_loop(self) -> None:
        """每 1s：
         - 检查 open bucket 是否到期（过期就闭合并入历史）
         - 通知 K线订阅者
        """
        while not self._stop_event.is_set():
            try:
                self._stop_event.wait(1.0)
                now_ms = int(time.time() * 1000)
                closed_items: List[Tuple[Tuple[str, str], Candle]] = []
                with self._kline_lock:
                    for key, bucket in list(self._kline_open_bucket.items()):
                        c = bucket.candle
                        if now_ms > c.close_time_ms:
                            closed_items.append((key, c))
                            # 入历史
                            hist = self._kline_history.setdefault(key, [])
                            if not hist or hist[-1].open_time_ms != c.open_time_ms:
                                hist.append(c)
                            if len(hist) > 600:
                                hist[:] = hist[-600:]
                            self._kline_open_bucket.pop(key, None)

                # 通知 K 线订阅者
                with self._sub_lock:
                    for key, c in closed_items:
                        cb_map = self._kline_subs.get(key, {})
                        for _cid, cb in list(cb_map.items()):
                            try:
                                cb(c, True)
                            except Exception as e:
                                logger.debug(f"[Market] kline 闭合回调异常: {e}")
                    # 未闭合 K 线：每 5s 推一次节流（不每次都推）
                    now_int = int(time.time())
                    if now_int % 5 == 0:
                        with self._kline_lock:
                            for key, bucket in list(self._kline_open_bucket.items()):
                                cb_map = self._kline_subs.get(key, {})
                                if not cb_map:
                                    continue
                                snap = Candle(**bucket.candle.to_dict())
                                for _cid, cb in list(cb_map.items()):
                                    try:
                                        cb(snap, False)
                                    except Exception as e:
                                        logger.debug(f"[Market] kline 更新回调异常: {e}")
            except Exception as e:
                logger.debug(f"[Market] kline_flush 异常: {e}")

    def _rest_fallback_loop(self) -> None:
        """每 5s：若有订阅的 symbol 没在 _tickers 中，就用 REST 拉 ticker；
        并按 ticker price 更新 open kline bucket（离线 fallback）"""
        while not self._stop_event.is_set():
            try:
                # 每 5s
                for _ in range(5):
                    if self._stop_event.is_set():
                        return
                    time.sleep(1.0)
                if not self._primary_client:
                    continue
                # 只处理已订阅 + 主用5品种
                syms = list(self._symbols_subscribed) or ["BTC", "ETH", "SOL", "XAU", "WTI", "SAND", "HBAR"]
                for sym in syms:
                    try:
                        ticker = self._primary_client.fetch_ticker(sym)
                        self._on_ws_ticker(ticker)
                    except Exception as e:
                        logger.debug(f"[Market] REST fallback ticker {sym} 失败: {e}")
            except Exception as e:
                logger.debug(f"[Market] rest_fallback 异常: {e}")

    def _oi_refresh_loop(self) -> None:
        """每 60s：拉取持仓量(OI)、资金费率、多空比
        加密货币从交易所API拉取，黄金/原油用模拟数据"""
        while not self._stop_event.is_set():
            try:
                # 每 60s
                for _ in range(60):
                    if self._stop_event.is_set():
                        return
                    time.sleep(1.0)
                if not self._primary_client:
                    continue
                syms = list(self._symbols_subscribed) or ["BTC", "ETH", "SOL", "XAU", "WTI", "SAND", "HBAR"]
                for sym in syms:
                    try:
                        # 加密货币从真实API拉取
                        if sym in ["BTC", "ETH", "SOL"]:
                            self._refresh_crypto_oi(sym)
                        else:
                            # 黄金/原油用模拟数据（基于价格波动）
                            self._simulate_commodity_oi(sym)
                    except Exception as e:
                        logger.debug(f"[Market] OI refresh {sym} 失败: {e}")
                logger.debug(f"[Market] OI刷新完成: {syms}")
            except Exception as e:
                logger.debug(f"[Market] oi_refresh 异常: {e}")

    def _refresh_crypto_oi(self, symbol: str) -> None:
        """从交易所API刷新加密货币OI和资金费率"""
        try:
            oi = self._primary_client.fetch_open_interest(symbol)
            with self._oi_lock:
                self._open_interest[symbol] = oi
                # 记录历史
                hist = self._oi_history.setdefault(symbol, [])
                hist.append(oi.open_interest_usdt)
                if len(hist) > 60:
                    hist[:] = hist[-60:]
            logger.debug(f"[Market] OI {symbol}: {oi.open_interest_usdt:.0f} USDT")
        except Exception as e:
            logger.debug(f"[Market] 拉取OI失败 {symbol}: {e}")

        # 资金费率（尝试从ticker或单独API获取，失败则用默认值）
        try:
            if hasattr(self._primary_client, 'fetch_funding_rate'):
                fr = self._primary_client.fetch_funding_rate(symbol)
                with self._oi_lock:
                    self._funding_rate[symbol] = fr
        except Exception:
            pass  # 使用默认值

    def _simulate_commodity_oi(self, symbol: str) -> None:
        """模拟黄金/原油等商品的OI和资金费率数据
        基于价格波动率和趋势生成合理的模拟值"""
        with self._price_lock:
            ticker = self._tickers.get(symbol)
        if not ticker:
            return

        price = ticker.last_price
        # 基础OI = 价格 * 模拟持仓量系数
        base_oi = price * 100000  # 模拟10万手
        # 添加随机波动 ±5%
        import random
        oi_usdt = base_oi * (1 + random.uniform(-0.05, 0.05))
        # 资金费率：接近0，±0.01%波动
        funding = random.uniform(-0.0001, 0.0002)
        # 多空比：0.8 ~ 1.2 之间
        ls_ratio = random.uniform(0.85, 1.15)

        oi = OpenInterest(
            symbol=symbol,
            open_interest=oi_usdt / price if price > 0 else 0,
            open_interest_usdt=oi_usdt,
            timestamp_ms=int(time.time() * 1000),
        )
        with self._oi_lock:
            self._open_interest[symbol] = oi
            self._funding_rate[symbol] = funding
            self._long_short_ratio[symbol] = ls_ratio
            hist = self._oi_history.setdefault(symbol, [])
            hist.append(oi_usdt)
            if len(hist) > 60:
                hist[:] = hist[-60:]

    def reload_demo_client(self):
        """从系统配置重新加载演示API client（管理员保存演示配置后调用）"""
        try:
            from backend.db.session import SessionLocal
            from backend.routers.settings import _get_config_value
            from backend.models.system_config import SystemConfig

            db = SessionLocal()
            try:
                enabled = _get_config_value(db, "demo_api_enabled", False)
                if not enabled:
                    logger.info("[Market] 演示API未启用，跳过reload")
                    return

                exchange_str = _get_config_value(db, "demo_api_exchange", "binance") or "binance"
                api_key = _get_config_value(db, "demo_api_key", "") or ""
                api_secret = _get_config_value(db, "demo_api_secret", "") or ""
                testnet = _get_config_value(db, "demo_api_testnet", True)

                if not api_key or not api_secret:
                    logger.warning("[Market] 演示API Key/Secret为空，跳过reload")
                    return

                exchange_id = 1 if exchange_str == "binance" else 2
                client = ExchangeClientBase.create(
                    exchange=exchange_id, api_key=api_key, api_secret=api_secret,
                    passphrase="", testnet=bool(testnet), exchange_account_id=0,
                )
                client.connect()
                self.register_client(client)
                if not self._running:
                    self.start(["BTC", "ETH", "SOL"])

                logger.info(f"[Market] 演示API client已加载 (exchange={exchange_str}, testnet={testnet})")
            finally:
                db.close()
        except Exception as e:
            logger.warning(f"[Market] reload_demo_client失败: {e}")


def _tf_bucket_ms(tf: str) -> int:
    m = {"1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800,
         "1h": 3600, "2h": 7200, "4h": 14400, "6h": 21600, "8h": 28800,
         "12h": 43200, "1d": 86400}
    return m.get(tf, 3600) * 1000