"""The global limit (B1) and the stricter per-route limit (B2) over one `RateLimiter`.

`RateLimitMiddleware` is plain ASGI, not `BaseHTTPMiddleware`, and it never
looks at the application's routes. slowapi's global limit broke under
fastapi 0.137 because `_find_route_handler` walked `app.routes` and stopped
finding endpoints once included routers were wrapped in `_IncludedRouter`;
this middleware counts every HTTP request before routing happens, so the
router's internal shape cannot switch it off.

One consequence differs from slowapi on purpose: slowapi scoped its default
limit per (client, endpoint), which needs the endpoint and therefore the
route walk. Here the default limit is one bucket per client across all
routes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from limits import parse
from starlette.datastructures import MutableHeaders
from starlette.requests import Request

from patterns_rate_limit.limiter import RateLimitDecision, RateLimiter

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from fastapi import FastAPI
    from starlette.responses import JSONResponse
    from starlette.types import ASGIApp, Message, Receive, Scope, Send

__all__ = [
    "RateLimitExceededError",
    "RateLimitMiddleware",
    "add_rate_limiting",
    "get_rate_limiter",
    "rate_limit",
]


class RateLimitExceededError(Exception):
    """Raised by the `rate_limit` dependency; carries the decision to render."""

    def __init__(self, decision: RateLimitDecision) -> None:
        super().__init__("rate limit exceeded")
        self.decision = decision


class RateLimitMiddleware:
    """Count every HTTP request against the limiter's default limit (B1).

    Args:
        app: The wrapped ASGI application.
        limiter: The shared limiter (also reachable as ``app.state.rate_limiter``).
    """

    def __init__(self, app: ASGIApp, limiter: RateLimiter) -> None:
        self.app = app
        self.limiter = limiter

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Reject over-limit requests; stamp `X-RateLimit-*` on the rest."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        limiter = self.limiter
        decision = await limiter.hit(limiter.default_limit, limiter.key_func(Request(scope)))
        if not decision.allowed:
            await limiter.exceeded_response(decision)(scope, receive, send)
            return

        headers = limiter.headers(decision, retry_after=False)

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                response_headers = MutableHeaders(scope=message)
                for name, value in headers.items():
                    # A per-route 429 already carries the stricter limit's
                    # headers; the global ones must not be appended beside them.
                    if name not in response_headers:
                        response_headers.append(name, value)
            await send(message)

        await self.app(scope, receive, send_with_headers)


def add_rate_limiting(app: FastAPI, limiter: RateLimiter) -> RateLimiter:
    """Install ``limiter`` on ``app``: state, middleware, and the 429 handler.

    Args:
        app: The application to protect.
        limiter: The limiter both enforcement paths share.

    Returns:
        RateLimiter: ``limiter``, for chaining.
    """
    app.state.rate_limiter = limiter
    app.add_middleware(RateLimitMiddleware, limiter=limiter)

    # `async def` is safe now. slowapi swapped an `async def` handler for its
    # own default one; nothing here inspects the handler's shape.
    async def handle_exceeded(request: Request, exc: Exception) -> JSONResponse:
        assert isinstance(exc, RateLimitExceededError)
        return get_rate_limiter(request).exceeded_response(exc.decision)

    app.add_exception_handler(RateLimitExceededError, handle_exceeded)
    return limiter


def get_rate_limiter(request: Request) -> RateLimiter:
    """Return the limiter `add_rate_limiting` stored on the request's app.

    Args:
        request: The incoming request.

    Returns:
        RateLimiter: The application's limiter.
    """
    limiter = request.app.state.rate_limiter
    assert isinstance(limiter, RateLimiter)
    return limiter


def rate_limit(limit: str | Callable[[Request], str]) -> Callable[[Request], Awaitable[None]]:
    """Build a route dependency enforcing a stricter limit on top of the global one (B2).

    Args:
        limit: A `limits` string, or a function reading it per request (the
            hub resolves `llm_rate_limit` from the app's injected settings).

    Returns:
        Callable: A dependency for ``dependencies=[Depends(...)]``.
    """

    async def enforce(request: Request) -> None:
        limiter = get_rate_limiter(request)
        item = parse(limit(request) if callable(limit) else limit)
        decision = await limiter.hit(item, limiter.key_func(request))
        if not decision.allowed:
            raise RateLimitExceededError(decision)

    return enforce
