"""
Redis 分布式锁工具
用于多 Worker /多进程部署时防止策略重复执行和重复下单。

用法：
    from backend.core.distributed_lock import acquire_lock, release_lock

    lock_key = f"strategy_run:{strategy_id}"
    if not acquire_lock(lock_key, expire_seconds=120):
        logger.info(f"策略 {strategy_id} 已被其他 Worker 锁定，跳过")
        return
    try:
        # 执行策略...
    finally:
        release_lock(lock_key)
"""
from __future__ import annotations

import uuid
import threading
import time
from typing import Optional

from backend.core.logging_config import logger
from backend.config import get_settings

_redis_client = None


def _get_redis():
    """惰性初始化 Redis 客户端（单例）"""
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    try:
        import redis as redis_lib
        s = get_settings()
        _redis_client = redis_lib.Redis(
            host=s.REDIS_HOST,
            port=s.REDIS_PORT,
            password=s.REDIS_PASSWORD,
            db=s.REDIS_DB,
            decode_responses=True,
            socket_connect_timeout=3,
            socket_timeout=3,
        )
        _redis_client.ping()
    except Exception as e:
        logger.warning(f"[DistributedLock] Redis 不可用，分布式锁降级为无锁模式: {e}")
        _redis_client = False  # 标记为不可用，避免每次都重试
    return _redis_client if _redis_client is not False else None


def acquire_lock(key: str, expire_seconds: int = 120, token: Optional[str] = None) -> bool:
    """
    尝试获取分布式锁（非阻塞）。
    使用 SET key value NX EX 实现，保证原子性。
    返回 True 表示获取成功，False 表示锁已被持有。
    如果 Redis 不可用，返回 True（降级为无锁模式，由调用方决定是否继续）。
    token 可外部传入（配合 release_lock 实现安全释放），不传则内部生成。
    """
    r = _get_redis()
    if r is None:
        return True
    if token is None:
        token = uuid.uuid4().hex
    try:
        ok = r.set(key, token, nx=True, ex=expire_seconds)
        return bool(ok)
    except Exception as e:
        logger.warning(f"[DistributedLock] 获取锁失败 key={key}: {e}，降级放行")
        return True


def release_lock(key: str, token: Optional[str] = None) -> None:
    """
    释放分布式锁。
    如果 token 不匹配（锁已过期被其他人获取），不删除。
    """
    r = _get_redis()
    if r is None:
        return
    try:
        if token:
            # Lua 脚本保证原子性：只有 token 匹配才删除
            lua = """
            if redis.call('get', KEYS[1]) == ARGV[1] then
                return redis.call('del', KEYS[1])
            else
                return 0
            end
            """
            r.eval(lua, 1, key, token)
        else:
            r.delete(key)
    except Exception as e:
        logger.warning(f"[DistributedLock] 释放锁失败 key={key}: {e}")


class StrategyLock:
    """上下文管理器：策略执行级别的分布式锁（含 Watchdog 自动续期）"""

    def __init__(self, strategy_id: int, symbol: str = "", timeframe: str = "", expire_seconds: int = 120):
        self.key = f"strategy:{strategy_id}:{symbol}:{timeframe}" if symbol else f"strategy:{strategy_id}"
        self.expire_seconds = expire_seconds
        self.token = uuid.uuid4().hex
        self.acquired = False
        self._watchdog_thread = None
        self._watchdog_stop = threading.Event()

    def __enter__(self):
        self.acquired = acquire_lock(self.key, self.expire_seconds, token=self.token)
        if self.acquired:
            self._watchdog_stop.clear()
            self._watchdog_thread = threading.Thread(
                target=self._renew_loop, daemon=True, name=f"lock-watchdog-{self.key}"
            )
            self._watchdog_thread.start()
        return self.acquired

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._watchdog_stop.set()
        if self.acquired:
            release_lock(self.key, self.token)
        self.acquired = False
        return False

    def _renew_loop(self):
        """Watchdog：每 expire/3 秒续期一次，防止长任务锁过期"""
        renew_interval = max(self.expire_seconds // 3, 10)
        while not self._watchdog_stop.wait(timeout=renew_interval):
            if not self.acquired:
                break
            r = _get_redis()
            if r is None:
                break
            try:
                lua = """
                if redis.call('get', KEYS[1]) == ARGV[1] then
                    return redis.call('expire', KEYS[1], ARGV[2])
                else
                    return 0
                end
                """
                result = r.eval(lua, 1, self.key, self.token, str(self.expire_seconds))
                if not result:
                    logger.warning(f"[DistributedLock] Watchdog 续期失败 key={self.key}，锁可能已被释放")
                    break
            except Exception as e:
                logger.warning(f"[DistributedLock] Watchdog 续期异常 key={self.key}: {e}")
                break
