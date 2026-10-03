"""B1: the default limit applies to every HTTP request, whatever the router shape.

Ported from `services/api`'s `tests/e2e/test_rate_limiting_enforcement.py`
(the `fastapi<0.137` canary) and `test_middleware_rate_limit_global_envelope.py`,
minus the app-specific routes and auth.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

from patterns_rate_limit import RateLimiter, RateLimitMiddleware
from tests.support.apps import build_app, client_for

if TYPE_CHECKING:
    from starlette.types import Message, Scope


async def test_undecorated_route_is_limited() -> None:
    async with client_for(build_app("1/minute")) as client:
        assert (await client.get("/plain")).status_code == 200
        assert (await client.get("/plain")).status_code == 429


async def test_route_on_an_included_router_is_limited() -> None:
    # The slowapi regression: under fastapi>=0.137 this route was exempt.
    async with client_for(build_app("1/minute")) as client:
        assert (await client.get("/included/ping")).status_code == 200
        assert (await client.get("/included/ping")).status_code == 429


async def test_unrouted_path_is_counted_too() -> None:
    # Counting happens before routing, so a 404 probe spends budget like any request.
    async with client_for(build_app("1/minute")) as client:
        assert (await client.get("/missing")).status_code == 404
        assert (await client.get("/plain")).status_code == 429


async def test_default_limit_is_one_bucket_per_client_across_routes() -> None:
    # Deliberate difference from slowapi, which scoped per (client, endpoint).
    async with client_for(build_app("2/minute")) as client:
        assert (await client.get("/plain")).status_code == 200
        assert (await client.get("/included/ping")).status_code == 200
        assert (await client.get("/plain")).status_code == 429


async def test_success_headers_report_the_default_limit_and_decrement() -> None:
    async with client_for(build_app("1000/minute")) as client:
        first = await client.get("/plain")
        second = await client.get("/included/ping")

    assert first.headers["X-RateLimit-Limit"] == "1000"
    assert int(first.headers["X-RateLimit-Remaining"]) == 999
    assert int(second.headers["X-RateLimit-Remaining"]) == 998
    assert first.headers["X-RateLimit-Reset"].isdigit()
    assert "Retry-After" not in first.headers


async def test_limit_resets_after_the_window() -> None:
    # Ported from `test_rate_limit_reset_after_window`: the reset header is a
    # real epoch timestamp (it parses as a float, as the hub's test reads it).
    async with client_for(build_app("1/second")) as client:
        assert (await client.get("/plain")).status_code == 200
        blocked = await client.get("/plain")
        assert blocked.status_code == 429

        wait = float(blocked.headers["X-RateLimit-Reset"]) - time.time()
        assert 0 < wait <= 2  # rounded up to whole seconds
        await asyncio.sleep(wait + 0.05)
        assert (await client.get("/plain")).status_code == 200


async def test_non_http_scopes_pass_through_uncounted() -> None:
    seen: list[str] = []

    async def inner(scope: Scope, receive: object, send: object) -> None:
        seen.append(scope["type"])

    limiter = RateLimiter("1/minute")
    middleware = RateLimitMiddleware(inner, limiter)  # pyright: ignore[reportArgumentType]

    async def receive() -> Message:
        return {"type": "lifespan.startup"}

    async def send(message: Message) -> None:
        return None

    for _ in range(3):
        await middleware({"type": "lifespan"}, receive, send)
    assert seen == ["lifespan"] * 3
