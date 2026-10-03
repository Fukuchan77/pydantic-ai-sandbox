"""B2: the per-route dependency enforces a stricter limit than the global one.

Ported from `services/api`'s `test_llm_rate_limit_triggers_429_before_global_default`
and `test_middleware_llm_rate_limit.py`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import Depends, FastAPI

from patterns_rate_limit import RateLimiter, add_rate_limiting, rate_limit
from tests.support.apps import build_app, client_for

if TYPE_CHECKING:
    from starlette.requests import Request


async def test_route_limit_triggers_before_the_global_default() -> None:
    async with client_for(build_app("1000/minute", route_limit="3/minute")) as client:
        statuses = [(await client.get("/llm")).status_code for _ in range(4)]
        other = await client.get("/plain")

    assert statuses == [200, 200, 200, 429]
    # The stricter bucket is separate: other routes still have global budget.
    assert other.status_code == 200


async def test_route_success_still_reports_the_global_limit() -> None:
    async with client_for(build_app("1000/minute", route_limit="3/minute")) as client:
        response = await client.get("/llm")
    assert response.headers["X-RateLimit-Limit"] == "1000"


async def test_route_limit_can_be_read_per_request() -> None:
    def from_state(request: Request) -> str:
        limit = request.app.state.llm_rate_limit
        assert isinstance(limit, str)
        return limit

    app = FastAPI()
    app.state.llm_rate_limit = "1/minute"
    add_rate_limiting(app, RateLimiter("1000/minute"))

    @app.get("/llm", dependencies=[Depends(rate_limit(from_state))])
    async def llm() -> dict[str, bool]:  # pyright: ignore[reportUnusedFunction]
        return {"ok": True}

    async with client_for(app) as client:
        assert (await client.get("/llm")).status_code == 200
        assert (await client.get("/llm")).status_code == 429
