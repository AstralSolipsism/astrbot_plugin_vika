import asyncio
import time

import pytest

from vika_mcp.config import RateLimitConfig, ServerConfig
from vika_mcp.runtime.rate_limiter import AsyncTokenBucketRateLimiter, NoOpRateLimiter
from vika_mcp.standard_server import create_standard_mcp


class TestAsyncTokenBucketRateLimiter:
    def test_default_qps_allows_burst_then_throttles(self):
        limiter = AsyncTokenBucketRateLimiter(qps=5.0)

        async def run():
            start = time.monotonic()
            for _ in range(6):
                await limiter.acquire(1.0)
            elapsed = time.monotonic() - start
            # 容量为 5，第 6 个请求至少等待 0.15s
            assert elapsed >= 0.15

        asyncio.run(run())

    def test_low_qps_enforces_interval(self):
        limiter = AsyncTokenBucketRateLimiter(qps=1.0)

        async def run():
            start = time.monotonic()
            await limiter.acquire(1.0)
            await limiter.acquire(1.0)
            elapsed = time.monotonic() - start
            assert elapsed >= 0.9

        asyncio.run(run())

    def test_invalid_qps_raises(self):
        with pytest.raises(ValueError):
            AsyncTokenBucketRateLimiter(qps=0)
        with pytest.raises(ValueError):
            AsyncTokenBucketRateLimiter(qps=-1)


class TestNoOpRateLimiter:
    def test_does_not_delay(self):
        limiter = NoOpRateLimiter()

        async def run():
            start = time.monotonic()
            for _ in range(10):
                await limiter.acquire(1.0)
            elapsed = time.monotonic() - start
            assert elapsed < 0.1

        asyncio.run(run())


class TestRateLimitConfig:
    def test_defaults(self):
        cfg = RateLimitConfig()
        assert cfg.enabled is True
        assert cfg.qps == 5.0

    def test_server_config_defaults(self):
        cfg = ServerConfig()
        assert cfg.rate_limit.enabled is True
        assert cfg.rate_limit.qps == 5.0


class TestServerRateLimitIntegration:
    def test_visible_tools_are_rate_limited(self):
        server = create_standard_mcp(transport="stdio")

        async def run():
            start = time.monotonic()
            for _ in range(6):
                await server.call_tool("vika_guide", {})
            elapsed = time.monotonic() - start
            assert elapsed >= 0.15

        asyncio.run(run())

    def test_disabled_rate_limit(self, monkeypatch):
        monkeypatch.setenv("VIKAMCP_SERVER__RATE_LIMIT__ENABLED", "false")
        server = create_standard_mcp(transport="stdio")

        async def run():
            start = time.monotonic()
            for _ in range(6):
                await server.call_tool("vika_guide", {})
            elapsed = time.monotonic() - start
            assert elapsed < 0.1

        asyncio.run(run())

    def test_custom_qps_via_env(self, monkeypatch):
        monkeypatch.setenv("VIKAMCP_SERVER__RATE_LIMIT__QPS", "1")
        server = create_standard_mcp(transport="stdio")

        async def run():
            start = time.monotonic()
            await server.call_tool("vika_guide", {})
            await server.call_tool("vika_guide", {})
            elapsed = time.monotonic() - start
            assert elapsed >= 0.9

        asyncio.run(run())
