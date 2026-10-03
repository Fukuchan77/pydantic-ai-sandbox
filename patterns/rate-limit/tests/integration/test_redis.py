"""B4 against a real Redis: shared counting, and degrading when it is unreachable.

Gated on ``RATE_LIMIT_REDIS_URL`` (CI points it at a ``redis:7-alpine`` service
container). The ``patterns:test:integration:rate-limit`` task sets
``EXPECT_LIVE_TESTS`` so an all-skipped run fails instead of passing green.
"""

from __future__ import annotations

import os
import socket
import uuid

import pytest

from patterns_rate_limit import RateLimiter
from tests.support.apps import build_app, client_for

REDIS_URL = os.environ.get("RATE_LIMIT_REDIS_URL")

pytestmark = pytest.mark.skipif(not REDIS_URL, reason="RATE_LIMIT_REDIS_URL is not set")


def _closed_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


async def test_two_limiters_share_one_redis_bucket() -> None:
    # Two processes behind a load balancer: the second sees the first's hits.
    assert REDIS_URL
    key = f"client-{uuid.uuid4()}"
    first = RateLimiter("2/minute", storage_uri=REDIS_URL)
    second = RateLimiter("2/minute", storage_uri=REDIS_URL)

    assert (await first.hit(first.default_limit, key)).allowed
    assert (await second.hit(second.default_limit, key)).allowed
    decision = await first.hit(first.default_limit, key)

    assert not decision.allowed
    assert not first.degraded
    assert not second.degraded


async def test_app_returns_429_counted_on_redis() -> None:
    assert REDIS_URL
    key = f"client-{uuid.uuid4()}"
    limiter = RateLimiter("1/minute", storage_uri=REDIS_URL, key_func=lambda _: key)

    async with client_for(build_app(limiter=limiter)) as client:
        assert (await client.get("/plain")).status_code == 200
        response = await client.get("/plain")

    assert response.status_code == 429
    assert response.headers["Retry-After"].isdigit()
    assert not limiter.degraded


async def test_unreachable_redis_degrades_to_memory() -> None:
    limiter = RateLimiter("1/minute", storage_uri=f"redis://127.0.0.1:{_closed_port()}/0")

    first = await limiter.hit(limiter.default_limit, "client")
    second = await limiter.hit(limiter.default_limit, "client")

    assert limiter.degraded
    assert first.allowed
    assert not second.allowed
