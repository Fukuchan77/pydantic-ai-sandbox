"""Span attribute test for ``Agent.run`` (Task 7.4 / Req 5.3).

Req 5.3 (verbatim): "WHEN an LLM call is dispatched through any provider
the system SHALL emit at least one trace span attributed to the agent
run; span attributes SHALL include the active provider name and model
ID."

The test runs the production ``ChatAgent`` once with
``agent.override(model=TestModel())`` so no real backend is required, and
inspects the captured spans for the OpenTelemetry GenAI semantic-
convention attributes pydantic-ai V2's ``instrument_pydantic_ai`` emits:

* ``gen_ai.provider.name`` (and the legacy alias ``gen_ai.system``) —
  carries the provider identity (``"test"`` here, in production
  ``"openai"`` for the Ollama path through the OpenAI-compatible
  adapter, etc.).
* ``gen_ai.request.model`` — carries the model ID requested.
* ``model_name`` — pydantic-ai's own attribute on the parent
  ``invoke_agent`` span, mirrors the model identifier.

Asserting the canonical OTel keys (rather than only ``model_name``)
makes the test fail loudly if the upstream library renames or drops the
GenAI semantic-convention surface. That breakage is exactly what Req
6.4 / Req 6.5 want surfaced early — drift in the V2 instrumentation
contract MUST not silently bypass observability tests.

Failure modes covered by sibling tests (T5.3 ``test_fallback_failover``)
are out of scope here; T7.4 only proves the happy-path span shape so
the assertion stays narrow.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import logfire
import pytest
from logfire.testing import (
    IncrementalIdGenerator,
    TestExporter,
    TimeGenerator,
)
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from pydantic_ai.models.test import TestModel

from pydantic_ai_sandbox.agents import build_chat_agent
from pydantic_ai_sandbox.schemas.chat import ChatResponse

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture
def captured_spans() -> Iterator[TestExporter]:
    """Wire logfire to an in-memory exporter and instrument pydantic-ai.

    Mirrors ``test_fallback_failover``'s fixture (T5.3) — same
    ``send_to_logfire=False`` + ``IncrementalIdGenerator`` recipe so the
    span graph stays deterministic across runs and can be diffed without
    timestamp / random-ID noise.
    """
    exporter = TestExporter()
    logfire.configure(
        send_to_logfire=False,
        console=False,
        advanced=logfire.AdvancedOptions(
            id_generator=IncrementalIdGenerator(),
            ns_timestamp_generator=TimeGenerator(),
        ),
        additional_span_processors=[SimpleSpanProcessor(exporter)],
    )
    logfire.instrument_pydantic_ai()
    yield exporter


def test_agent_run_emits_span_with_provider_and_model_id(
    captured_spans: TestExporter,
) -> None:
    """A single ``agent.run`` produces a ``chat`` span carrying provider + model ID.

    The chat span is the canonical surface where pydantic-ai V2 stamps
    the ``gen_ai.*`` semantic-convention attributes; the parent
    ``invoke_agent`` span carries the convenience ``model_name``
    attribute. Asserting on the chat span keeps the test aligned with
    the OTel GenAI spec rather than pydantic-ai's private convenience
    surface.

    ``TestModel`` reports its ``system`` as ``"test"`` and its
    ``model_name`` as ``"test"`` — both are constants exposed by the
    upstream class, so the test assertion uses the literal ``"test"``
    rather than introspecting the model object (which would risk
    mirroring the implementation back at itself and silently passing
    even if the attribute keys disappeared).
    """
    agent = build_chat_agent(model=TestModel())

    with agent.override(model=TestModel()):
        # ``run_sync`` keeps the test free of asyncio-mode ceremony — the
        # agent path under test is identical to the async one (V2's
        # ``run_sync`` is a thin wrapper around ``asyncio.run(run(...))``).
        result = agent.run_sync("ping the agent for span emission")

    # The structured-output coercion is not the focus here, but checking
    # it confirms the run actually completed end-to-end before we look
    # at the span exporter — a half-finished run could publish partial
    # spans and cause confusing assertion failures downstream.
    assert isinstance(result.output, ChatResponse)

    spans = captured_spans.exported_spans_as_dict(include_resources=False)
    assert spans, "instrument_pydantic_ai must emit at least one span per agent run"

    chat_spans = [
        s for s in spans if s.get("attributes", {}).get("gen_ai.operation.name") == "chat"
    ]
    assert len(chat_spans) >= 1, (
        f"expected at least one 'chat' operation span, got {len(chat_spans)} "
        f"from spans={[s.get('name') for s in spans]}"
    )

    chat_attrs = chat_spans[0]["attributes"]
    # Provider half of Req 5.3: OTel GenAI semantic convention.
    # ``gen_ai.provider.name`` is the new key (>=v1.30) and
    # ``gen_ai.system`` is the legacy alias both keys are populated by
    # pydantic-ai V2's instrumentation; checking either keeps the test
    # tolerant of upstream's eventual deprecation, while still failing
    # loudly if BOTH disappear (which would mean provider attribution
    # is gone entirely).
    provider_attr = chat_attrs.get("gen_ai.provider.name") or chat_attrs.get("gen_ai.system")
    assert provider_attr == "test", (
        f"chat span missing provider attribute (provider.name / system); attrs={chat_attrs}"
    )

    # Model-ID half of Req 5.3: ``gen_ai.request.model`` is the OTel
    # GenAI key for the model identifier the agent requested.
    request_model = chat_attrs.get("gen_ai.request.model")
    assert request_model == "test", (
        f"chat span missing gen_ai.request.model attribute; got {request_model!r}, "
        f"attrs={chat_attrs}"
    )
