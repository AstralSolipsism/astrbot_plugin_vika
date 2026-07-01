import asyncio
import time
from typing import Optional


class AsyncTokenBucketRateLimiter:
    """异步全局令牌桶限速器。

    用于限制 MCP 工具调用的全局速率，避免请求过于频繁导致后端或本地资源问题。
    默认 QPS 为 5，允许与 QPS 等量的短时突发。
    """

    def __init__(self, qps: float = 5.0, capacity: Optional[float] = None) -> None:
        if qps <= 0:
            raise ValueError("qps must be positive")
        self.qps = float(qps)
        self.capacity = float(capacity if capacity is not None else self.qps)
        if self.capacity <= 0:
            raise ValueError("capacity must be positive")
        self._tokens: float = self.capacity
        self._last_update = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self, tokens: float = 1.0) -> None:
        """获取指定数量的令牌，必要时异步等待。"""
        if tokens <= 0:
            return
        if tokens > self.capacity:
            # 单次请求超过桶容量时，将其拆分为容量允许的最大值处理，
            # 避免永远满足不了的请求饿死。
            tokens = self.capacity

        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_update
            self._tokens = min(self.capacity, self._tokens + elapsed * self.qps)
            self._last_update = now

            if self._tokens >= tokens:
                self._tokens -= tokens
                return

            deficit = tokens - self._tokens
            wait_seconds = deficit / self.qps
            self._tokens = 0.0
            self._last_update = now + wait_seconds

        await asyncio.sleep(wait_seconds)


class NoOpRateLimiter:
    """空实现，用于禁用限速时保持调用接口一致。"""

    async def acquire(self, tokens: float = 1.0) -> None:
        return
