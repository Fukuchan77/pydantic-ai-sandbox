"""In-process ASGI driver that injects ``http.disconnect`` (R6.2, ADR-4).

httpx's ``ASGITransport`` fully buffers a finite response and never surfaces a
client's early close as ``http.disconnect`` (research.md I-3), so the happy-path
transport (R5) cannot exercise the cancel/cleanup path. This helper drives the
*same* ASGI app directly via ``await app(scope, receive, send)`` -- opening no
real socket, so it stays within R5/R6's hermetic, network-zero intent -- with a
custom ``receive`` that injects ``{"type": "http.disconnect"}`` once the app has
sent ``disconnect_after`` ``data:`` frames. That fires sse-starlette's
``_listen_for_disconnect``, which cancels its task group and propagates
``CancelledError`` into the streaming body generator (R6.1/6.2/6.3).

Pair it with ``ScriptedEventSource(block_after=N)``: the producer yields ``N``
events then parks on an un-set gate, so the body generator is suspended
mid-stream when the injected disconnect cancels it -- making the cancellation and
the ``finally`` cleanup deterministically observable rather than racing the
producer's natural completion.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from starlette.types import ASGIApp, Message, Scope

__all__ = ["DriveResult", "drive_until_disconnect"]

_DATA_PREFIX = "data:"


@dataclass
class DriveResult:
    """Outcome of one in-process ASGI run driven to an injected disconnect.

    Attributes:
        status: The ``http.response.start`` status code, or ``None`` if the app
            never started a response.
        body_text: The concatenated ``http.response.body`` payload captured
            before cancellation -- parseable with ``parse_sse_events``.
        data_frames: Number of ``data:`` frames observed on the wire.
        injected_disconnect: Whether the custom ``receive`` actually returned an
            ``http.disconnect`` message (distinguishes a real disconnect from a
            run that completed or wedged before the injection point).
    """

    status: int | None
    body_text: str
    data_frames: int
    injected_disconnect: bool


def _count_data_frames(chunks: list[bytes]) -> int:
    """Count ``data:`` frames across the captured body chunks (mirrors ``parse_sse_events``)."""
    text = b"".join(chunks).decode("utf-8", "replace")
    return sum(1 for line in text.splitlines() if line.startswith(_DATA_PREFIX))


async def drive_until_disconnect(
    app: ASGIApp,
    *,
    query: str,
    disconnect_after: int,
    timeout: float = 5.0,
) -> DriveResult:
    """Drive ``app`` in-process and inject ``http.disconnect`` after ``disconnect_after`` frames.

    Builds a ``POST /sse/runs`` HTTP scope, delivers the JSON body once, then
    arms a disconnect: the custom ``receive`` blocks until the ``send`` side has
    captured ``disconnect_after`` ``data:`` frames, after which it returns an
    ``http.disconnect`` message. Real sockets are never opened (ADR-4).

    Args:
        app: The ASGI app under test (a ``create_app`` instance).
        query: The query forwarded in the request body.
        disconnect_after: Inject ``http.disconnect`` once this many ``data:``
            frames have been sent (use the producer's ``block_after`` so the
            body generator is parked mid-stream when the disconnect lands).
        timeout: Hang guard; if the app does not return within this many seconds
            after the injection the cancel path is wedged and we fail loudly
            rather than blocking the suite.

    Returns:
        A ``DriveResult`` with the captured wire prefix and disconnect evidence.
    """
    body = json.dumps({"query": query}).encode()
    scope: Scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "path": "/sse/runs",
        "raw_path": b"/sse/runs",
        "query_string": b"",
        "root_path": "",
        "scheme": "http",
        "headers": [
            (b"host", b"sse"),
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
        ],
        "client": ("127.0.0.1", 12345),
        "server": ("sse", 80),
    }

    armed = asyncio.Event()
    chunks: list[bytes] = []
    request_delivered = False
    status: int | None = None
    disconnected = False

    async def receive() -> Message:
        nonlocal request_delivered, disconnected
        if not request_delivered:
            # First pull feeds FastAPI's body parsing; the rest of the channel is
            # the disconnect injector consumed by `_listen_for_disconnect`.
            request_delivered = True
            return {"type": "http.request", "body": body, "more_body": False}
        await armed.wait()
        disconnected = True
        return {"type": "http.disconnect"}

    async def send(message: Message) -> None:
        nonlocal status
        if message["type"] == "http.response.start":
            status = message["status"]
        elif message["type"] == "http.response.body":
            chunks.append(bytes(message.get("body", b"")))
            if not armed.is_set() and _count_data_frames(chunks) >= disconnect_after:
                armed.set()  # enough frames on the wire -> release the queued disconnect

    try:
        await asyncio.wait_for(app(scope, receive, send), timeout=timeout)
    except TimeoutError as exc:
        msg = (
            f"ASGI app did not return within {timeout}s after http.disconnect "
            "injection; the cancel/cleanup path is likely wedged."
        )
        raise AssertionError(msg) from exc

    text = b"".join(chunks).decode("utf-8", "replace")
    return DriveResult(
        status=status,
        body_text=text,
        data_frames=_count_data_frames(chunks),
        injected_disconnect=disconnected,
    )
