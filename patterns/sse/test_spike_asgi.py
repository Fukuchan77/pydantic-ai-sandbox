"""Task 0 Spike (Spec 008-2c). THROWAWAY — confirms ADR-4 / Risk R-1.

Empirically verifies, against the *installed* httpx 0.28.1 / sse-starlette
3.4.4 / fastapi 0.136.3, the two behaviors the design depends on:

  (a) R5 happy path — a finite ``EventSourceResponse`` stream is fully buffered
      by ``httpx.ASGITransport`` and retrievable as one body that parses into
      the complete event list (no incremental delivery required).

  (b) R6 disconnect — httpx's normal client API does NOT propagate an early
      close as ``http.disconnect`` (I-3), so the cancel/cleanup path is proven
      by driving the same ASGI app directly via ``app(scope, receive, send)``
      and injecting ``{"type": "http.disconnect"}`` after K body frames. This
      must reach the body generator's ``except CancelledError`` + ``finally``.

This is a decision gate: if both checks pass, ADR-4 holds and Wave 1 may start.
The file is replaced/removed by Task 1 — nothing here is production code.
"""

import asyncio
from collections.abc import AsyncIterator

import httpx
from fastapi import FastAPI, Request
from sse_starlette.sse import EventSourceResponse

# Safety cap so a never-terminating generator can never hang ASGITransport
# (Risk R-2). The disconnect spike trips far below this.
_MAX_EVENTS = 1000


def _build_app(gen_factory: object) -> FastAPI:
    app = FastAPI()

    @app.get("/sse/spike")
    async def sse_spike(request: Request) -> EventSourceResponse:
        return EventSourceResponse(gen_factory(request))  # type: ignore[operator]

    return app


async def test_asgitransport_buffers_finite_stream() -> None:
    """ADR-4(a): finite stream fully buffered and retrievable via ASGITransport."""

    async def gen(_request: Request) -> AsyncIterator[dict[str, str]]:
        for i in range(3):
            yield {"event": "token", "data": f"chunk-{i}"}
        yield {"event": "completed", "data": "done"}

    app = _build_app(gen)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://spike"
    ) as client:
        resp = await client.get("/sse/spike")
        body = resp.text

    # The complete finite stream comes back in one buffered body, terminal
    # marker included — confirms full-buffer behavior (no streaming needed).
    assert resp.status_code == 200
    assert body.count("event: token") == 3
    assert "chunk-0" in body and "chunk-2" in body
    assert "event: completed" in body


async def test_scope_drive_disconnect_reaches_cleanup() -> None:
    """ADR-4(b): injected http.disconnect cancels the body gen -> finally runs."""
    state = {"yielded": 0, "cancelled": False, "cleanup": False}

    async def gen(_request: Request) -> AsyncIterator[dict[str, str]]:
        try:
            i = 0
            while i < _MAX_EVENTS:
                yield {"event": "token", "data": f"chunk-{i}"}
                state["yielded"] = i + 1
                i += 1
                await asyncio.sleep(0.005)  # cancellation checkpoint
            yield {"event": "completed", "data": "done"}
        except asyncio.CancelledError:
            state["cancelled"] = True
            raise  # never swallow the cancellation (R6.3)
        finally:
            state["cleanup"] = True  # resource release sentinel (R6.1)

    app = _build_app(gen)

    k = 3
    frames: list[bytes] = []
    disconnect_now = asyncio.Event()
    request_sent = False

    async def receive() -> dict[str, object]:
        nonlocal request_sent
        if not request_sent:
            request_sent = True
            return {"type": "http.request", "body": b"", "more_body": False}
        await disconnect_now.wait()  # block until K frames observed
        return {"type": "http.disconnect"}

    async def send(message: dict[str, object]) -> None:
        if message["type"] == "http.response.body":
            body = message.get("body", b"")
            if isinstance(body, bytes) and b"data:" in body:
                frames.append(body)
                if len(frames) >= k and not disconnect_now.is_set():
                    disconnect_now.set()

    scope: dict[str, object] = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "GET",
        "path": "/sse/spike",
        "raw_path": b"/sse/spike",
        "query_string": b"",
        "root_path": "",
        "headers": [],
        "scheme": "http",
        "server": ("spike", 80),
        "client": ("test", 12345),
    }

    # 5s guard: if disconnect were NOT honored the generator would run to the
    # safety cap (~5s of sleeps) — still bounded, but the asserts below would
    # then fail loudly rather than hang.
    await asyncio.wait_for(app(scope, receive, send), timeout=10.0)

    assert len(frames) >= k, "did not observe K data frames before disconnect"
    assert state["cancelled"] is True, "CancelledError never reached body gen"
    assert state["cleanup"] is True, "finally cleanup did not run"
    assert state["yielded"] < _MAX_EVENTS, "generator was not stopped early"
