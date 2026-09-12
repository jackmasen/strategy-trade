"""
AI 接口限流 + 去重 + 缓存 综合优化模块
========================================
解决 AI 接口超频（HTTP 429）问题的核心手段：

1. 令牌桶限流（Token Bucket）
   - 全局按 provider+endpoint 维度统计请求频率
   - 超过 RPM 限制时排队等待或直接返回限流错误

2. SingleFlight 请求去重
   - 同一 symbol+timeframe+analysis_type 的并发请求，只发一次真实 API 调用
   - 其他请求等待共享结果，避免重复烧钱

3. 内存 LRU 缓存（比 DB 缓存更快）
   - 命中时零延迟返回，完全不触发 API 调用
   - 与 DB 缓存形成二级缓存体系

4. 并发控制
   - 限制同时进行的 AI 请求数量，避免瞬间打爆接口

5. 429 智能冷却
   - 触发 429 后自动冷却该 provider/key 一段时间
   - 冷却期内直接走降级，不再浪费请求
"""
from __future__ import annotations

import time
import threading
import asyncio
from collections import deque, OrderedDict
from dataclasses import dataclass, field
from typing import Dict, Optional, Callable, Any, Deque
from contextlib import contextmanager

from backend.core.logging_config import logger

_warn_last_ts: dict = {}

def _throttled_warn(key: str, msg: str, throttle_sec: float = 60.0) -> None:
    now = time.time()
    last = _warn_last_ts.get(key)
    if last is None or (now - last) > throttle_sec:
        logger.warning(msg)
        _warn_last_ts[key] = now


# ============================================================
# 1. 令牌桶限流器
# ============================================================
@dataclass
class TokenBucket:
    """令牌桶限流器（线程安全）

    用法：
        bucket = TokenBucket(rate=60, capacity=60)  # 60个/分钟，桶容量60
        if bucket.try_consume():
            # 执行请求
        else:
            # 限流了
    """
    rate: float = 60.0          # 每秒/每分钟补充的令牌数（由 rate_per_minute 控制）
    capacity: float = 60.0      # 桶容量（最大突发请求数）
    tokens: float = field(default=0.0)
    last_refill: float = field(default_factory=time.time)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    rate_per_minute: float = 60.0  # 每分钟速率

    def __post_init__(self):
        self.tokens = self.capacity
        self.rate = self.rate_per_minute / 60.0  # 转成每秒速率

    def try_consume(self, tokens: float = 1.0) -> bool:
        """尝试消费 tokens 个令牌，成功返回 True"""
        with self._lock:
            now = time.time()
            elapsed = now - self.last_refill
            # 补充令牌
            self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
            self.last_refill = now

            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            return False

    def wait_time(self, tokens: float = 1.0) -> float:
        """需要等待多少秒才能消费 tokens 个令牌（0 表示可以立即消费）"""
        with self._lock:
            now = time.time()
            elapsed = now - self.last_refill
            current_tokens = min(self.capacity, self.tokens + elapsed * self.rate)
            if current_tokens >= tokens:
                return 0.0
            deficit = tokens - current_tokens
            return deficit / self.rate if self.rate > 0 else float('inf')

    def set_rate(self, rate_per_minute: float):
        """动态调整速率（RPM）"""
        with self._lock:
            now = time.time()
            elapsed = now - self.last_refill
            self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
            self.last_refill = now
            self.rate_per_minute = rate_per_minute
            self.rate = rate_per_minute / 60.0
            # 容量也跟着调整（保持 1 分钟的突发量）
            self.capacity = max(5.0, rate_per_minute)


class RateLimiterManager:
    """全局限流器管理器（按 key 维度管理多个令牌桶）

    key 可以是：
    - "provider:openai" — 按提供商
    - "endpoint:https://api.openai.com/v1" — 按接口地址
    - "key:sk-xxx" — 按具体 API Key（不建议，Key 会脱敏）
    """
    _instance = None
    _lock = threading.Lock()

    def __init__(self):
        self._buckets: Dict[str, TokenBucket] = {}
        self._default_rpm = 20  # 默认每分钟 20 次请求（保守值）

    @classmethod
    def get_instance(cls) -> "RateLimiterManager":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def _get_bucket(self, key: str, rpm: Optional[float] = None) -> TokenBucket:
        if key not in self._buckets:
            self._buckets[key] = TokenBucket(rate_per_minute=rpm or self._default_rpm)
        return self._buckets[key]

    def try_acquire(self, key: str, tokens: float = 1.0, rpm: Optional[float] = None) -> bool:
        """尝试获取令牌，返回是否成功"""
        bucket = self._get_bucket(key, rpm)
        return bucket.try_consume(tokens)

    def get_wait_time(self, key: str, tokens: float = 1.0) -> float:
        """获取需要等待的时间（秒）"""
        bucket = self._get_bucket(key)
        return bucket.wait_time(tokens)

    def set_rate(self, key: str, rpm: float):
        """设置某个 key 的速率（RPM）"""
        bucket = self._get_bucket(key, rpm)
        bucket.set_rate(rpm)

    def trigger_rate_limit(self, key: str, retry_after_seconds: float = 60.0):
        """触发 429 后，主动降低速率并冷却一段时间

        策略：将速率降到当前的 50%，最少 5 RPM
        """
        bucket = self._get_bucket(key)
        current_rpm = bucket.rate_per_minute
        new_rpm = max(5.0, current_rpm * 0.5)
        bucket.set_rate(new_rpm)
        _throttled_warn(f"trigger_limit_{key}", f"[RateLimiter] 触发限流 {key}: RPM {current_rpm:.0f} → {new_rpm:.0f}，冷却 {retry_after_seconds:.0f}s")
        # 清空令牌，强制冷却
        with bucket._lock:
            bucket.tokens = 0
            bucket.last_refill = time.time() + retry_after_seconds

    def recover_rate(self, key: str, step_rpm: float = 2.0):
        """请求成功时逐步恢复速率"""
        bucket = self._get_bucket(key)
        if bucket.rate_per_minute < self._default_rpm:
            new_rpm = min(self._default_rpm, bucket.rate_per_minute + step_rpm)
            bucket.set_rate(new_rpm)


# ============================================================
# 2. SingleFlight 请求去重
# ============================================================
@dataclass
class InflightRequest:
    """正在进行中的请求（供其他相同请求等待共享）"""
    event: threading.Event = field(default_factory=threading.Event)
    result: Any = None
    error: Optional[Exception] = None
    start_time: float = field(default_factory=time.time)


class SingleFlight:
    """SingleFlight 去重器（线程安全）

    同一 key 的并发请求只执行一次，其余等待结果。

    用法：
        sf = SingleFlight()
        result = sf.do("BTC_4h_score", lambda: call_ai_api(...))
    """
    def __init__(self):
        self._requests: Dict[str, InflightRequest] = {}
        self._lock = threading.Lock()

    def do(self, key: str, fn: Callable[[], Any], timeout: float = 60.0) -> Any:
        """执行 fn，如果已有同 key 请求在进行中则等待共享结果

        返回 fn 的执行结果，或抛出 fn 的异常
        """
        with self._lock:
            if key in self._requests:
                # 已有在途请求，等待
                inflight = self._requests[key]
                is_first = False
            else:
                # 第一个请求，创建 in-flight 记录
                inflight = InflightRequest()
                self._requests[key] = inflight
                is_first = True

        if not is_first:
            # 等待在途请求完成
            inflight.event.wait(timeout=timeout)
            if inflight.error is not None:
                raise inflight.error
            return inflight.result

        # 第一个请求，实际执行
        try:
            result = fn()
            inflight.result = result
        except Exception as e:
            inflight.error = e
            raise
        finally:
            inflight.event.set()
            # 清理（稍等一下让等待者取到结果）
            def _cleanup():
                time.sleep(0.1)
                with self._lock:
                    if key in self._requests and self._requests[key] is inflight:
                        del self._requests[key]
            t = threading.Thread(target=_cleanup, daemon=True)
            t.start()

        return result


# ============================================================
# 3. LRU 内存缓存
# ============================================================
class LRUCache:
    """线程安全的 LRU 缓存

    用法：
        cache = LRUCache(max_size=1000, ttl_seconds=300)
        cache.set("key", value)
        value = cache.get("key")  # None 表示未命中
    """
    def __init__(self, max_size: int = 500, ttl_seconds: int = 300):
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self._cache: OrderedDict[str, tuple] = OrderedDict()  # key -> (value, expire_time)
        self._lock = threading.Lock()

    def get(self, key: str) -> Optional[Any]:
        """获取缓存，未命中或已过期返回 None"""
        with self._lock:
            if key not in self._cache:
                return None
            value, expire_time = self._cache[key]
            if time.time() > expire_time:
                # 已过期，删除
                del self._cache[key]
                return None
            # 移到末尾（最近使用）
            self._cache.move_to_end(key)
            return value

    def set(self, key: str, value: Any, ttl_seconds: Optional[int] = None):
        """设置缓存"""
        ttl = ttl_seconds or self.ttl_seconds
        expire_time = time.time() + ttl
        with self._lock:
            if key in self._cache:
                # 更新并移到末尾
                self._cache[key] = (value, expire_time)
                self._cache.move_to_end(key)
            else:
                # 新增
                self._cache[key] = (value, expire_time)
                # 超过容量，淘汰最久未使用的
                if len(self._cache) > self.max_size:
                    self._cache.popitem(last=False)

    def invalidate(self, key: str):
        """删除指定缓存"""
        with self._lock:
            self._cache.pop(key, None)

    def clear(self):
        """清空所有缓存"""
        with self._lock:
            self._cache.clear()

    def size(self) -> int:
        """当前缓存数量（粗略，不清理过期项）"""
        with self._lock:
            return len(self._cache)


# ============================================================
# 4. 并发控制器
# ============================================================
class ConcurrencyLimiter:
    """并发数限制（信号量模式）

    限制同时进行的 AI 请求总数，避免瞬间并发过高触发 429。
    """
    def __init__(self, max_concurrent: int = 5):
        self._semaphore = threading.Semaphore(max_concurrent)
        self._max = max_concurrent
        self._active = 0
        self._lock = threading.Lock()

    @contextmanager
    def acquire(self, timeout: float = 30.0):
        """获取并发槽位，用完自动释放

        用法：
            with limiter.acquire(timeout=10):
                do_ai_request()
        """
        acquired = self._semaphore.acquire(timeout=timeout)
        if not acquired:
            raise TimeoutError(f"并发请求过多，等待 {timeout}s 仍未获得槽位")
        with self._lock:
            self._active += 1
        try:
            yield
        finally:
            with self._lock:
                self._active -= 1
            self._semaphore.release()

    @property
    def active_count(self) -> int:
        with self._lock:
            return self._active

    @property
    def available(self) -> int:
        return self._max - self.active_count

    def set_max(self, max_concurrent: int):
        """动态调整最大并发数"""
        diff = max_concurrent - self._max
        self._max = max_concurrent
        if diff > 0:
            for _ in range(diff):
                self._semaphore.release()
        # 减少的情况：信号量不支持直接减少，靠自然消耗


# ============================================================
# 5. 全局 AI 请求协调器（整合所有优化手段）
# ============================================================
class AIRequestCoordinator:
    """
    AI 请求全局协调器（单例）

    整合：限流 + 去重 + 缓存 + 并发控制
    所有 AI 请求都应该通过此协调器发起，统一管控频率。

    调用流程：
    1. 先查内存缓存 → 命中直接返回
    2. 再查 SingleFlight → 有在途请求则等待共享
    3. 检查并发数 → 超了则等待或拒绝
    4. 检查限流 → 超了则等待或降级
    5. 执行真实请求 → 写缓存 → 返回
    """
    _instance = None
    _lock = threading.Lock()

    def __init__(self):
        # 默认配置（可以通过 AI 配置页面动态调整）
        self.default_rpm = 20          # 默认每分钟 20 次（按 provider 维度）
        self.max_concurrent = 5        # 最大并发 5 个请求
        self.cache_ttl = 180           # 内存缓存 3 分钟（比 DB 15 分钟短，保证一定新鲜度）
        self.cache_max_size = 200      # 最多缓存 200 个结果

        # 组件
        self.rate_limiter = RateLimiterManager.get_instance()
        self.single_flight = SingleFlight()
        self.cache = LRUCache(max_size=self.cache_max_size, ttl_seconds=self.cache_ttl)
        self.concurrency = ConcurrencyLimiter(max_concurrent=self.max_concurrent)

        # 统计
        self._stats = {
            "cache_hits": 0,
            "dedup_hits": 0,
            "rate_limited": 0,
            "total_requests": 0,
            "success_requests": 0,
            "failed_requests": 0,
        }
        self._stats_lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> "AIRequestCoordinator":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def _cache_key(self, symbol: str, timeframe: str, analysis_type: str) -> str:
        return f"ai:{symbol.upper()}:{timeframe}:{analysis_type}"

    def _rate_key(self, provider: str, endpoint: str = "") -> str:
        # 用 provider + endpoint 作为限流维度
        if endpoint:
            return f"provider:{provider}|ep:{endpoint[:80]}"
        return f"provider:{provider}"

    def _incr_stat(self, key: str):
        with self._stats_lock:
            self._stats[key] = self._stats.get(key, 0) + 1

    def get_stats(self) -> dict:
        with self._stats_lock:
            return dict(self._stats)

    def configure(self, *, rpm: Optional[int] = None, max_concurrent: Optional[int] = None,
                  cache_ttl: Optional[int] = None):
        """动态调整配置"""
        if rpm is not None and rpm > 0:
            self.default_rpm = rpm
            logger.info(f"[AI-Coord] 调整默认 RPM: {rpm}")
        if max_concurrent is not None and max_concurrent > 0:
            self.max_concurrent = max_concurrent
            self.concurrency.set_max(max_concurrent)
            logger.info(f"[AI-Coord] 调整最大并发: {max_concurrent}")
        if cache_ttl is not None and cache_ttl > 0:
            self.cache_ttl = cache_ttl
            logger.info(f"[AI-Coord] 调整缓存 TTL: {cache_ttl}s")

    def execute(
        self,
        *,
        symbol: str,
        timeframe: str,
        analysis_type: str = "score",
        provider: str = "custom",
        endpoint: str = "",
        request_fn: Callable[[], Any],
        allow_wait: bool = True,
        max_wait_seconds: float = 15.0,
    ) -> tuple[Any, str]:
        """
        执行 AI 请求（受限流/去重/缓存/并发管控）

        返回: (result, source)
        source: "cache"（缓存命中） / "dedup"（去重共享） / "live"（真实请求） / "rate_limited"（被限流）

        被限流时 result 为 None，调用方应走降级逻辑。
        """
        symbol = symbol.upper()
        cache_key = self._cache_key(symbol, timeframe, analysis_type)
        dedup_key = f"{cache_key}:{provider}"
        rate_key = self._rate_key(provider, endpoint)

        self._incr_stat("total_requests")

        # Step 1: 内存缓存命中 → 直接返回
        cached = self.cache.get(cache_key)
        if cached is not None:
            self._incr_stat("cache_hits")
            return cached, "cache"

        # Step 2: SingleFlight 去重
        # 注意：SingleFlight 内部会处理并发等待
        def _do_request():
            # Step 3: 并发控制
            try:
                with self.concurrency.acquire(timeout=max_wait_seconds):
                    # Step 4: 限流检查
                    wait_time = self.rate_limiter.get_wait_time(rate_key)
                    if wait_time > 0:
                        if allow_wait and wait_time <= max_wait_seconds:
                            # 可以等，睡一会儿
                            time.sleep(min(wait_time + 0.1, max_wait_seconds))
                        else:
                            # 不能等或等太久 → 限流
                            self._incr_stat("rate_limited")
                            _throttled_warn(f"rate_limited_{rate_key}", f"[AI-Coord] 限流触发: {rate_key}, 需等待 {wait_time:.1f}s，已拒绝")
                            return None, "rate_limited"

                    if not self.rate_limiter.try_acquire(rate_key, rpm=self.default_rpm):
                        self._incr_stat("rate_limited")
                        return None, "rate_limited"

                    # Step 5: 执行真实请求
                    result = request_fn()

                    # 成功 → 写缓存
                    if result is not None and getattr(result, 'success', True):
                        self.cache.set(cache_key, result, ttl_seconds=self.cache_ttl)
                        self._incr_stat("success_requests")
                        # 成功请求，逐步恢复速率
                        self.rate_limiter.recover_rate(rate_key)
                    else:
                        self._incr_stat("failed_requests")

                    return result, "live"
            except TimeoutError:
                self._incr_stat("rate_limited")
                _throttled_warn(f"concurrent_timeout_{symbol}_{timeframe}", f"[AI-Coord] 并发等待超时: {symbol} {timeframe}")
                return None, "rate_limited"

        try:
            result, source = self.single_flight.do(dedup_key, _do_request, timeout=max_wait_seconds + 30)
            if source == "dedup" or (isinstance(source, str) and source != "live" and source != "cache"):
                # SingleFlight 返回的是共享结果，标记为 dedup
                if source != "cache" and source != "live" and source != "rate_limited":
                    self._incr_stat("dedup_hits")
                    source = "dedup"
            return result, source
        except Exception as e:
            # SingleFlight 里第一个请求抛异常，把异常传出去
            self._incr_stat("failed_requests")
            raise

    def notify_429(self, provider: str, endpoint: str = "", retry_after: float = 60.0):
        """通知协调器遇到了 429 限流，触发冷却"""
        rate_key = self._rate_key(provider, endpoint)
        self.rate_limiter.trigger_rate_limit(rate_key, retry_after_seconds=retry_after)

    def invalidate_cache(self, symbol: str = "", timeframe: str = "", analysis_type: str = ""):
        """主动失效缓存（比如有重大新闻更新时）"""
        if not symbol and not timeframe and not analysis_type:
            self.cache.clear()
            return
        # 粗略匹配：构造前缀匹配
        prefix = f"ai:{symbol.upper() if symbol else ''}"
        # 简单起见，全清（实际生产可以做前缀匹配遍历）
        if symbol and timeframe and analysis_type:
            self.cache.invalidate(self._cache_key(symbol, timeframe, analysis_type))
        else:
            # 部分匹配的情况下，保守地清掉该 symbol 的所有缓存
            # LRUCache 没有遍历删除能力，直接全清（缓存量不大，可接受）
            self.cache.clear()
