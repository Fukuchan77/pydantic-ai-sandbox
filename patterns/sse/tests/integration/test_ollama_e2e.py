"""Gated Ollama integration test for the SSE lane (Spec 008-2c Req 3.3, 7.1).

Skipped unless ``RUN_INTEGRATION_PATTERNS=1``. The single end-to-end test drives a
routing-shaped pydantic-ai ``Agent`` against a *real* Ollama model and maps its
``run_stream_events`` stream to the ``SseEvent`` contract through an in-test adapter
(research.md I-1), feeding that adapter as the ``EventSource`` into ``create_app`` --
the very DI seam the offline scripted fake uses. ``InstrumentationSettings`` rides
the same injected ``TracerProvider`` so ``gen_ai.*`` spans flow alongside the app's
own ``sse.stream`` span.

Assertions stay at the **contract** level (Req 3.3 / R4.1 order / each ``data``
``model_validate`` / span>=1); exact text is never asserted because a live model is
non-deterministic -- determinism (NFR-2 / R5.3) is the offline scripted fake's job,
not this lane's. The framework-agnostic ``patterns_pydantic_ai`` lane is never
imported (NFR-3): the adapter is built here from pydantic-ai directly, which is a
dev/integration-only dependency of this lane.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import httpx
import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from patterns_contracts import (
    CompletedEvent,
    StepStartedEvent,
    TokenEvent,
    ToolCalledEvent,
)
from pydantic_ai import Agent, AgentRunResultEvent
from pydantic_ai.messages import (
    FunctionToolCallEvent,
    PartDeltaEvent,
    PartStartEvent,
    TextPart,
    TextPartDelta,
)
from pydantic_ai.models.instrumented import InstrumentationSettings, instrument_model

from patterns_sse import create_app, parse_sse_events
from patterns_sse.observability import configure_tracing

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from patterns_contracts import SseEvent
    from pydantic_ai.messages import AgentStreamEvent
    from pydantic_ai.models import Model

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION_PATTERNS") != "1",
    reason="integration lane gated by RUN_INTEGRATION_PATTERNS=1",
)

# A routing-shaped specialist prompt (research.md I-1): one model request, plain
# str output, no tools -- the live run naturally yields step_started + token*
# (tool_called stays at zero, which R4.1 allows). Kept minimal so the model
# answers briefly; exact text is never asserted.
_INSTRUCTIONS = (
    "You are a customer-support assistant. Answer the user's question "
    "concisely in one or two sentences."
)

_QUERY = "I was billed twice for my subscription this month -- what should I do?"


def _ollama_model() -> Model:
    """Build the Ollama-backed model from the environment (Req 7.3 / model-ID hygiene)."""
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.ollama import OllamaProvider

    model_name = os.environ["OLLAMA_MODEL_NAME"]
    base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1")
    return OpenAIChatModel(model_name=model_name, provider=OllamaProvider(base_url=base_url))


def _agent_event_to_sse(event: AgentStreamEvent | AgentRunResultEvent[str]) -> SseEvent | None:
    """Map one pydantic-ai stream event to its ``SseEvent`` member (research.md I-1).

    Returns ``None`` for events outside the SSE contract vocabulary (part ends, tool
    results, non-text deltas, thinking parts) -- the producer forwards only mapped
    events, preserving the canonical ``step_started -> tool_called* -> token* ->
    completed`` order (R4.1).

    Args:
        event: A ``run_stream_events`` item -- an ``AgentStreamEvent`` or the
            terminal ``AgentRunResultEvent``.

    Returns:
        The matching ``SseEvent``, or ``None`` when the event has no contract mapping.
    """
    if isinstance(event, PartStartEvent):
        # A text part starting opens the answer step; non-text part starts (tools,
        # thinking) carry no step signal -- FunctionToolCallEvent owns tool_called.
        return StepStartedEvent(step="answer") if isinstance(event.part, TextPart) else None
    if isinstance(event, PartDeltaEvent):
        delta = event.delta
        if isinstance(delta, TextPartDelta) and delta.content_delta:
            return TokenEvent(text=delta.content_delta)
        return None
    if isinstance(event, FunctionToolCallEvent):
        return ToolCalledEvent(tool=event.part.tool_name, args_json=event.part.args_as_json_str())
    if isinstance(event, AgentRunResultEvent):
        return CompletedEvent(output=str(event.result.output))
    return None


class _PydanticAIEventSource:
    """``EventSource`` adapter over a pydantic-ai run's event stream (research.md I-1, NFR-3).

    Structurally satisfies ``patterns_sse.EventSource``: ``stream`` is a plain method
    returning an async generator. It drives ``agent.run_stream_events`` as an async
    context manager (so the background run task is cleaned up deterministically when
    the consumer stops early) and maps each event to its ``SseEvent`` via
    :func:`_agent_event_to_sse`, dropping events with no contract mapping.
    """

    def __init__(self, agent: Agent[None, str]) -> None:
        self._agent = agent

    async def stream(self, query: str) -> AsyncIterator[SseEvent]:
        """Yield the ordered ``SseEvent`` sequence for ``query`` from the live run."""
        async with self._agent.run_stream_events(query) as events:
            async for event in events:
                mapped = _agent_event_to_sse(event)
                if mapped is not None:
                    yield mapped


async def test_sse_delivery_against_live_ollama() -> None:
    # Real path: a routing-shaped Agent on an Ollama model, streamed through the
    # run_stream_events -> SseEvent adapter, delivered by the real create_app /
    # EventSourceResponse pipeline and buffered by ASGITransport (ADR-4a). The same
    # injected TracerProvider backs both the app span and the model's gen_ai.* spans.
    exporter = InMemorySpanExporter()
    provider = configure_tracing(exporter)
    instrumentation = InstrumentationSettings(tracer_provider=provider)

    model = instrument_model(_ollama_model(), instrumentation)
    agent = Agent[None, str](
        model=model,
        output_type=str,
        instructions=_INSTRUCTIONS,
        deps_type=type(None),
    )
    app = create_app(event_source=_PydanticAIEventSource(agent), tracer_provider=provider)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://sse") as client:
        resp = await client.post("/sse/runs", json={"query": _QUERY})

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")

    events = parse_sse_events(resp.text)
    types = [event.type for event in events]

    # R4.1: the stream opens on a step and ends on exactly one terminal marker, with
    # nothing after it -- the contract shape, not the live model's exact event text.
    assert types, "the live run must deliver at least one event"
    assert types[0] == "step_started"
    terminal = {"completed", "error"}
    assert types[-1] in terminal
    assert all(t not in terminal for t in types[:-1]), "a terminal marker must end the stream once"
    assert any(isinstance(event, TokenEvent) for event in events), (
        "the live stream must emit tokens"
    )

    # R4.2 / R5.2: every delivered data payload re-validates from its own dump.
    for event in events:
        assert type(event).model_validate(event.model_dump()) == event

    # R7.1: the injected instrumentation produced at least one span (the app's
    # sse.stream span and/or the model's gen_ai.* spans); attributes are not asserted (R7.3).
    assert exporter.get_finished_spans(), "instrumented run must produce >=1 span (R7.1)"
