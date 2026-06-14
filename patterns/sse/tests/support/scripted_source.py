"""Deterministic offline ``EventSource`` for the SSE lane's unit suite (R4.1/5.3/6.2).

``ScriptedEventSource`` is the offline producer the DI seam (``create_app``)
drives instead of a real agent. It yields a fixed ``SseEvent`` sequence in the
canonical order ``step_started -> tool_called -> token* -> completed`` (R4.1)
with a fixed token chunk list, so the delivered stream is byte-for-byte
reproducible across runs (NFR-2 / R5.3) -- no network, no model, no randomness.

Two seams let tests drive the app's failure and disconnect paths without
touching production code:

* ``fail_at=N`` raises a run-time error *after* yielding ``N`` events, so a test
  can prove the app terminates the stream with an ``error`` event rather than
  crashing or silently truncating (R4.3/4.4, exercised by Task 6);
* ``block_after=N`` yields ``N`` events and then blocks on an un-set event,
  parking the generator at an ``await`` so an injected ``http.disconnect`` can
  cancel it mid-stream and the cancellation/cleanup path is observable
  (R6, exercised by Task 7).

``cancelled`` / ``released`` record that the generator saw a ``CancelledError``
and that its ``finally`` ran -- the assertions the disconnect tests check.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from patterns_contracts import (
    CompletedEvent,
    StepStartedEvent,
    TokenEvent,
    ToolCalledEvent,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from patterns_contracts import SseEvent

__all__ = ["ScriptedEventSource"]

# Fixed token chunks make the delivered `token` stream deterministic (R5.3); they
# concatenate to the `completed` output below, mirroring a real incremental run.
_DEFAULT_TOKENS: tuple[str, ...] = ("Hel", "lo", " wor", "ld")
_DEFAULT_OUTPUT = "Hello world"


class ScriptedEventSource:
    """An ``EventSource`` that replays a fixed event script with failure/block seams."""

    def __init__(
        self,
        *,
        step: str = "classify",
        tool: tuple[str, str] | None = ("search", '{"q": "fixed"}'),
        tokens: tuple[str, ...] = _DEFAULT_TOKENS,
        output: str = _DEFAULT_OUTPUT,
        fail_at: int | None = None,
        fail_message: str = "scripted run-time failure",
        block_after: int | None = None,
    ) -> None:
        """Build the fixed event script and configure the failure/block seams.

        Args:
            step: Name carried by the leading ``StepStartedEvent``.
            tool: ``(tool, args_json)`` for a single ``ToolCalledEvent``; omit
                with ``None`` to script no tool call.
            tokens: Fixed incremental token chunks (deterministic, R5.3).
            output: Final ``CompletedEvent`` output (the joined tokens).
            fail_at: Raise a run-time error after yielding this many events.
            fail_message: Message of the raised ``RuntimeError``.
            block_after: Block on an un-set event after yielding this many
                events, parking the generator for disconnect injection.
        """
        script: list[SseEvent] = [StepStartedEvent(step=step)]
        if tool is not None:
            script.append(ToolCalledEvent(tool=tool[0], args_json=tool[1]))
        script.extend(TokenEvent(text=chunk) for chunk in tokens)
        script.append(CompletedEvent(output=output))
        self.script: list[SseEvent] = script
        self._fail_at = fail_at
        self._fail_message = fail_message
        self._block_after = block_after
        self._gate = asyncio.Event()
        self.cancelled = False
        self.released = False

    async def stream(self, query: str) -> AsyncIterator[SseEvent]:
        """Yield the scripted events, honouring the ``fail_at`` / ``block_after`` seams."""
        del query  # The script is fixed; the query does not steer offline output.
        try:
            # `index` counts events already yielded before this iteration, so the
            # seams read as "after yielding N events" (R4.3 fail / R6 block).
            for index, event in enumerate(self.script):
                if self._fail_at is not None and index == self._fail_at:
                    raise RuntimeError(self._fail_message)
                yield event
                if self._block_after is not None and index + 1 == self._block_after:
                    await self._gate.wait()  # park until cancelled (disconnect seam)
                await asyncio.sleep(0)  # cancellation checkpoint between events
        except asyncio.CancelledError:
            self.cancelled = True  # never swallow the cancellation (R6.3)
            raise
        finally:
            self.released = True  # resource-release sentinel (R6.1)
