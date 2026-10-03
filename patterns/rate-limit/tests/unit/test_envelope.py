"""B5 and B6: one 429 shape, reached from both enforcement paths.

Ported from `services/api`'s `test_middleware_rate_limit_global_envelope.py`
and `tests/unit/middleware/test_rate_limit_retry_after.py`.
"""

from __future__ import annotations

import limits

from patterns_rate_limit import RATE_LIMIT_CODE, RATE_LIMIT_MESSAGE
from tests.support.apps import build_app, client_for

_RATE_LIMIT_HEADERS = {"x-ratelimit-limit", "x-ratelimit-remaining", "x-ratelimit-reset"}
_WINDOW_SECONDS = limits.parse("1/minute").get_expiry()


async def _global_429() -> tuple[dict[str, object], dict[str, str]]:
    async with client_for(build_app("1/minute")) as client:
        await client.get("/plain")
        response = await client.get("/plain")
    assert response.status_code == 429
    return response.json(), dict(response.headers)


async def _route_429() -> tuple[dict[str, object], dict[str, str]]:
    async with client_for(build_app("1000/minute", route_limit="1/minute")) as client:
        await client.get("/llm")
        response = await client.get("/llm")
    assert response.status_code == 429
    return response.json(), dict(response.headers)


async def test_global_429_body_is_flat_message_and_code() -> None:
    body, _ = await _global_429()
    assert body == {"message": RATE_LIMIT_MESSAGE, "code": RATE_LIMIT_CODE}


async def test_global_429_carries_rate_limit_headers_and_retry_after() -> None:
    _, headers = await _global_429()
    assert set(headers) >= _RATE_LIMIT_HEADERS
    assert headers["x-ratelimit-limit"] == "1"
    assert headers["x-ratelimit-remaining"] == "0"


async def test_retry_after_is_delay_seconds_within_the_window() -> None:
    _, headers = await _global_429()
    retry_after = headers["retry-after"]
    # delay-seconds, not an HTTP-date; +1 allows the reset-time rounding.
    assert retry_after.isdigit()
    assert 1 <= int(retry_after) <= _WINDOW_SECONDS + 1


async def test_both_paths_return_the_same_429() -> None:
    global_body, global_headers = await _global_429()
    route_body, route_headers = await _route_429()

    assert global_body == route_body
    rate_headers = _RATE_LIMIT_HEADERS | {"retry-after", "content-type"}
    assert rate_headers <= set(global_headers)
    assert rate_headers <= set(route_headers)


async def test_route_429_reports_the_stricter_limit_once() -> None:
    async with client_for(build_app("1000/minute", route_limit="1/minute")) as client:
        await client.get("/llm")
        response = await client.get("/llm")

    limit_values = response.headers.get_list("X-RateLimit-Limit")
    assert limit_values == ["1"], "the global limit's header must not be appended beside it"
