"""B4: a failing primary storage degrades to memory instead of failing requests.

The live Redis half of B4 is ``tests/integration/test_redis.py``.
"""

from __future__ import annotations

import logging

import pytest
from limits.aio.storage import MemoryStorage, RedisStorage
from limits.errors import StorageError

from patterns_rate_limit import RateLimiter
from tests.support.apps import build_app, client_for


class _DownStorage(MemoryStorage):
    """A storage whose every counting call fails, like an unreachable Redis."""

    def __init__(self) -> None:
        super().__init__()
        self.calls = 0
        self.up = False

    async def incr(self, key: str, expiry: float, amount: int = 1) -> int:
        self.calls += 1
        if not self.up:
            raise StorageError(ConnectionError("redis down"))
        return await super().incr(key, expiry, amount)


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


async def test_requests_are_served_and_limited_while_degraded(
    caplog: pytest.LogCaptureFixture,
) -> None:
    storage = _DownStorage()
    with caplog.at_level(logging.WARNING, logger="patterns_rate_limit.limiter"):
        async with client_for(build_app("2/minute", storage=storage)) as client:
            statuses = [(await client.get("/plain")).status_code for _ in range(3)]

    assert statuses == [200, 200, 429]
    assert storage.calls == 1, "the primary is not retried inside the cooldown"
    assert [r.message for r in caplog.records if "falling back" in r.message]


async def test_primary_is_retried_after_the_cooldown() -> None:
    storage = _DownStorage()
    clock = _Clock()
    limiter = RateLimiter("10/minute", storage=storage, monotonic=clock, recovery_seconds=30)

    await limiter.hit(limiter.default_limit, "client")
    assert limiter.degraded

    clock.now = 29.0
    await limiter.hit(limiter.default_limit, "client")
    assert storage.calls == 1

    storage.up = True
    clock.now = 31.0
    decision = await limiter.hit(limiter.default_limit, "client")
    assert storage.calls == 2
    assert not limiter.degraded
    assert decision.allowed


def test_plain_redis_uri_maps_to_the_async_redispy_storage() -> None:
    # Construction only; no connection is attempted until the first hit.
    limiter = RateLimiter("1/minute", storage_uri="redis://localhost:6379/0")
    primary = limiter._primary  # pyright: ignore[reportPrivateUsage]
    assert isinstance(primary, RedisStorage)


def test_memory_uri_is_used_as_is() -> None:
    limiter = RateLimiter("1/minute", storage_uri="async+memory://")
    primary = limiter._primary  # pyright: ignore[reportPrivateUsage]
    assert isinstance(primary, MemoryStorage)


def test_no_uri_means_memory_only() -> None:
    limiter = RateLimiter("1/minute")
    assert limiter._primary is None  # pyright: ignore[reportPrivateUsage]
    assert not limiter.degraded


def test_synchronous_storage_uri_is_rejected() -> None:
    with pytest.raises(ValueError, match="async"):
        RateLimiter("1/minute", storage_uri="memory://")
