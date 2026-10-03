"""Small FastAPI apps the unit suite drives in-process over ``ASGITransport``."""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
from fastapi import APIRouter, Depends, FastAPI

from patterns_rate_limit import RateLimiter, add_rate_limiting, rate_limit

if TYPE_CHECKING:
    from limits.aio.storage import Storage

__all__ = ["build_app", "client_for"]


def build_app(
    default_limit: str = "1000/minute",
    *,
    route_limit: str = "2/minute",
    storage: Storage | None = None,
    limiter: RateLimiter | None = None,
) -> FastAPI:
    """Build an app with an undecorated route, an included router, and a stricter route.

    ``/included/ping`` lives on an ``APIRouter`` passed through
    ``include_router``: since fastapi 0.137 that router is wrapped in
    ``_IncludedRouter`` rather than flattened into ``app.routes``, which is the
    exact shape that silently disabled slowapi's global limit (B1 canary).
    A passed ``limiter`` replaces the one built from ``default_limit``/``storage``.
    """
    app = FastAPI()
    add_rate_limiting(app, limiter or RateLimiter(default_limit, storage=storage))

    @app.get("/plain")
    async def plain() -> dict[str, bool]:  # pyright: ignore[reportUnusedFunction]
        return {"ok": True}

    @app.get("/llm", dependencies=[Depends(rate_limit(route_limit))])
    async def llm() -> dict[str, bool]:  # pyright: ignore[reportUnusedFunction]
        return {"ok": True}

    router = APIRouter(prefix="/included")

    @router.get("/ping")
    async def ping() -> dict[str, bool]:  # pyright: ignore[reportUnusedFunction]
        return {"ok": True}

    app.include_router(router)
    return app


def client_for(app: FastAPI) -> httpx.AsyncClient:
    """Return an in-process client; no socket is opened."""
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver")
