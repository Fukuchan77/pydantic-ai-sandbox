"""Observability tests for the watsonx SDK transport (Task 7.7 / Req 8.5, 9.9).

This file is Req 9.9's and Req 8.5's authoritative home per the coverage matrix:

* **9.9** (FR-056) — an ``Agent.run`` against the watsonx SDK Model produces
  *non-empty* ``gen_ai.system`` and ``gen_ai.request.model`` span attributes.
  Task 5.1 proved the ``system`` / ``model_name`` *properties* in isolation;
  this drives them through a real ``Agent.run`` + ``instrument_pydantic_ai``
  so the end-to-end span surface is pinned, not just the property getters.
* **8.5** (FR-024) — the watsonx feature scrubs sensitive payloads using the
  *existing* ``extra_patterns=["prompt", "tool_input", "tool_output"]`` config
  **without adding provider-specific patterns**. ``test_logging_setup.py`` pins
  the superset (Req 5.4); this pins *equality* under a watsonx selection — the
  regression guard that activating watsonx did not widen the scrubbing alphabet
  with a ``watsonx_apikey`` / ``project_id`` stem.

The task description also asks this file to confirm, at the ``Agent.run`` grain,
two contracts Task 5 first pinned at the model grain (their authoritative homes
remain Tasks 5.4 / 5.1 in the coverage matrix):

* **error.class on failure** (Req 8.2) — a watsonx request failure surfaces the
  error class on the span. In pydantic_ai V2 Beta the carrier is the OTel
  ``exception`` event's ``exception.type`` on the ``chat`` span (V2 does not
  stamp a literal ``error.class`` *attribute* — the same V2 reality documented
  in ``test_fallback_failover.py``), and the wrapper class is our
  :class:`ModelAPIError`.
* **no extended attributes** (Req 8.3 / 8.4) — the watsonx Model contributes
  *only* ``system`` + ``model_name``; it injects no provider-specific
  (``watsonx.*``) attribute and forwards no per-request model parameters
  (``gen_ai.request.temperature`` / ``max_tokens`` / ``top_p`` — the
  ``del model_settings`` decision in ``request``). The token-usage and
  message-content attributes that pydantic_ai's instrumentation emits by default
  are generic across *every* provider and are governed by scrubbing (Req 8.5
  above), not by anything the watsonx Model adds — so this test asserts only on
  what the watsonx Model itself controls.

Hermetic posture (matches Tasks 7.1/7.3/7.4/7.5/7.6): the source already exists
(``system`` / ``model_name`` from Task 5.1, ``ModelAPIError`` wrapping from Task
5.4, the bare ``instrument_pydantic_ai`` + ``_SCRUBBING_EXTRA_PATTERNS`` from the
001-era ``logging_setup``), so these are characterization tests — RED is the
absent file (collection error); they pin the contract rather than drive new code.
The request path stays egress-free by substituting ``_build_client`` with a fake
``achat`` (the same technique as ``test_watsonx_sdk_construction.py``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

import httpx
import logfire
import pytest
from fastapi import FastAPI
from logfire.testing import (
    IncrementalIdGenerator,
    TestExporter,
    TimeGenerator,
)
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from pydantic_ai import Agent
from pydantic_ai.exceptions import ModelAPIError

from pydantic_ai_sandbox.llm.providers.watsonx import WatsonxSDKModel
from pydantic_ai_sandbox.logging_setup import (
    _SCRUBBING_EXTRA_PATTERNS,  # pyright: ignore[reportPrivateUsage]
    configure_observability,
)
from tests.conftest import WATSONX_TEST_MODEL_ID

if TYPE_CHECKING:
    from collections.abc import Iterator

    from tests.conftest import WatsonxSettingsFactory


# ---------------------------------------------------------------------------
# Span-capture fixture + hermetic ``achat`` fakes
#
# The fixture mirrors ``test_fallback_failover`` / ``test_logging_span_attributes``
# (same ``send_to_logfire=False`` + ``IncrementalIdGenerator`` recipe) so the span
# graph stays deterministic. The fakes substitute ``_build_client`` so the real
# ``request`` mapping runs with zero network egress.
# ---------------------------------------------------------------------------


@pytest.fixture
def captured_spans() -> Iterator[TestExporter]:
    """Wire logfire to an in-memory exporter and instrument pydantic-ai.

    Uses the *bare* :func:`logfire.instrument_pydantic_ai` (no
    ``InstrumentationSettings``) — the same call the production
    ``configure_observability`` makes — so the captured span surface matches
    what ships, and the watsonx Model's contribution (``gen_ai.system`` /
    ``gen_ai.request.model``) is asserted against the real instrumentation
    pipeline rather than a bespoke test configuration.
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


_TEXT_RESPONSE: dict[str, Any] = {
    "id": "chatcmpl-watsonx-obs",
    "choices": [
        {
            "index": 0,
            "message": {"role": "assistant", "content": "hello from watsonx"},
            "finish_reason": "stop",
        },
    ],
    "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
}


class _FakeAchatClient:
    """Stand-in for ``ModelInference`` returning a canned ``achat`` response."""

    def __init__(self, response: dict[str, Any]) -> None:
        self._response = response

    async def achat(self, **_kwargs: Any) -> dict[str, Any]:
        return self._response


class _FailingAchatClient:
    """Stand-in for ``ModelInference`` whose ``achat`` raises a transport error."""

    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    async def achat(self, **_kwargs: Any) -> dict[str, Any]:
        raise self._exc


def _chat_span(exporter: TestExporter) -> dict[str, Any]:
    """Return the single ``chat`` span, filtered by the OTel operation attribute.

    Filtering on ``gen_ai.operation.name == "chat"`` (rather than the span
    ``name``, which embeds the model id and so is brittle) mirrors
    ``test_logging_span_attributes`` / ``test_fallback_failover``.
    """
    spans = exporter.exported_spans_as_dict(include_resources=False)
    chat_spans = [
        s for s in spans if s.get("attributes", {}).get("gen_ai.operation.name") == "chat"
    ]
    assert len(chat_spans) == 1, (
        f"expected exactly one 'chat' span, got {len(chat_spans)} "
        f"from spans={[s.get('name') for s in spans]}"
    )
    return chat_spans[0]


# ---------------------------------------------------------------------------
# Req 9.9 / 8.1 — Agent.run emits non-empty gen_ai.system + gen_ai.request.model
# ---------------------------------------------------------------------------


def test_agent_run_emits_non_empty_watsonx_system_and_model_id(
    monkeypatch: pytest.MonkeyPatch,
    watsonx_settings_factory: WatsonxSettingsFactory,
    captured_spans: TestExporter,
) -> None:
    """A watsonx ``Agent.run`` stamps the provider + model-id span attributes (Req 9.9).

    Drives a real :class:`WatsonxSDKModel` through ``Agent.run_sync`` with
    ``instrument_pydantic_ai`` active and asserts the ``chat`` span carries
    *non-empty* ``gen_ai.system`` (watsonx's :pyattr:`system` property) and
    ``gen_ai.request.model`` (its :pyattr:`model_name`, sourced from
    ``WATSONX_MODEL_ID``). The literal values are asserted (``"watsonx"`` /
    the fixture model id) rather than merely "truthy" so a mislabelled provider
    or a swapped model id fails loudly — non-emptiness alone would not catch a
    wrong-but-present value.
    """
    model = WatsonxSDKModel(watsonx_settings_factory())
    monkeypatch.setattr(model, "_build_client", lambda: _FakeAchatClient(_TEXT_RESPONSE))
    agent = Agent(model=model)

    result = agent.run_sync("ping watsonx for span emission")

    # Confirm the run completed end-to-end before inspecting spans; a
    # half-finished run could publish partial spans and mislead the assertions.
    assert result.output == "hello from watsonx"

    chat_attrs = _chat_span(captured_spans)["attributes"]

    # Provider half of Req 9.9: ``gen_ai.provider.name`` is the >=v1.30 key and
    # ``gen_ai.system`` the legacy alias; pydantic_ai V2 populates both from the
    # Model's ``system`` property. Reading either keeps the test tolerant of the
    # eventual deprecation while failing loudly if BOTH vanish (provider
    # attribution gone entirely).
    provider_attr = chat_attrs.get("gen_ai.provider.name") or chat_attrs.get("gen_ai.system")
    assert provider_attr == "watsonx", (
        f"chat span missing watsonx provider attribute; attrs={chat_attrs}"
    )

    # Model-id half of Req 9.9: ``gen_ai.request.model`` is the OTel key for the
    # requested model id, derived from the Model's ``model_name`` property.
    request_model = chat_attrs.get("gen_ai.request.model")
    assert request_model == WATSONX_TEST_MODEL_ID, (
        f"chat span gen_ai.request.model wrong; got {request_model!r}, attrs={chat_attrs}"
    )
    # Belt-and-braces on the literal Req 9.9 wording ("non-empty").
    assert provider_attr
    assert request_model


# ---------------------------------------------------------------------------
# Req 8.2 — error class surfaces on the span when a watsonx request fails
# ---------------------------------------------------------------------------


def test_agent_run_failure_records_error_class_on_chat_span(
    monkeypatch: pytest.MonkeyPatch,
    watsonx_settings_factory: WatsonxSettingsFactory,
    captured_spans: TestExporter,
) -> None:
    """A failed watsonx request records the error class on the ``chat`` span (Req 8.2).

    A transport failure (``httpx.ReadTimeout``) from ``achat`` is wrapped by
    ``request`` into :class:`ModelAPIError` (Task 5.4) and propagates out of the
    agent. pydantic_ai V2 records it on the ``chat`` span as an OTel
    ``exception`` event whose ``exception.type`` is the fully-qualified
    :class:`ModelAPIError` — that event *is* the "error class" surface in V2
    Beta (a literal ``error.class`` span attribute is not emitted; same V2
    reality the fallback-failover suite documents). The identity attributes
    (``gen_ai.system`` / ``gen_ai.request.model``) must still be present on the
    failed span so error traces stay attributable.
    """
    model = WatsonxSDKModel(watsonx_settings_factory())
    boom = httpx.ReadTimeout("read timed out")
    monkeypatch.setattr(model, "_build_client", lambda: _FailingAchatClient(boom))
    agent = Agent(model=model)

    with pytest.raises(ModelAPIError):
        agent.run_sync("trigger a watsonx failure")

    chat_span = _chat_span(captured_spans)
    chat_attrs = chat_span["attributes"]

    # Identity attributes survive the failure (attribution of the error trace).
    provider_attr = chat_attrs.get("gen_ai.provider.name") or chat_attrs.get("gen_ai.system")
    assert provider_attr == "watsonx"
    assert chat_attrs.get("gen_ai.request.model") == WATSONX_TEST_MODEL_ID

    exception_events = [e for e in chat_span.get("events", []) if e.get("name") == "exception"]
    assert len(exception_events) >= 1, (
        f"failed chat span must record an exception event; events={chat_span.get('events')}"
    )
    error_class = exception_events[0].get("attributes", {}).get("exception.type", "")
    assert "ModelAPIError" in error_class, (
        f"error class on the span must be the wrapped ModelAPIError; got {error_class!r}"
    )


# ---------------------------------------------------------------------------
# Req 8.3 / 8.4 — the watsonx Model adds no provider-specific / model-parameter
# attributes (the lean attribute set)
# ---------------------------------------------------------------------------


def test_watsonx_chat_span_carries_no_extended_attributes(
    monkeypatch: pytest.MonkeyPatch,
    watsonx_settings_factory: WatsonxSettingsFactory,
    captured_spans: TestExporter,
) -> None:
    """The watsonx Model injects no extended / provider-specific attributes (Req 8.3/8.4).

    The watsonx Model contributes only ``system`` + ``model_name``. This pins the
    two facets it actually controls:

    * **No model parameters.** ``request`` deliberately drops ``model_settings``
      (``del model_settings`` — ``models/CLAUDE.md`` rule 912), and the run here
      supplies none, so the ``chat`` span carries no
      ``gen_ai.request.{temperature,max_tokens,top_p,frequency_penalty}``.
      (Those keys *do* appear when a caller passes ``model_settings`` — but that
      is generic pydantic_ai instrumentation reading the *caller's* settings, not
      anything the watsonx Model emits.)
    * **No provider-specific namespace.** No ``watsonx.``-prefixed attribute is
      stamped — the Model does not smuggle latency/cost/raw-payload extras under
      a custom key.

    Token-usage (``gen_ai.usage.*``) and message-content (``gen_ai.input/output
    .messages``) attributes are pydantic_ai instrumentation defaults shared by
    every provider and governed by scrubbing (Req 8.5, covered separately), so
    they are intentionally *not* asserted against here — doing so would test the
    upstream library, not the watsonx Model.
    """
    model = WatsonxSDKModel(watsonx_settings_factory())
    monkeypatch.setattr(model, "_build_client", lambda: _FakeAchatClient(_TEXT_RESPONSE))
    agent = Agent(model=model)

    agent.run_sync("ping with no model settings")

    chat_attrs = _chat_span(captured_spans)["attributes"]

    forbidden_param_keys = {
        "gen_ai.request.temperature",
        "gen_ai.request.max_tokens",
        "gen_ai.request.top_p",
        "gen_ai.request.frequency_penalty",
        "gen_ai.request.presence_penalty",
    }
    present_params = forbidden_param_keys & set(chat_attrs)
    assert not present_params, (
        f"watsonx Model must forward no model parameters; leaked={present_params}"
    )

    watsonx_namespaced = [k for k in chat_attrs if k.startswith("watsonx.")]
    assert not watsonx_namespaced, (
        f"watsonx Model must add no provider-specific span attributes; got {watsonx_namespaced}"
    )


# ---------------------------------------------------------------------------
# Req 8.5 — scrubbing unchanged: no watsonx-specific extra_patterns added
# ---------------------------------------------------------------------------

_CANONICAL_EXTRA_PATTERNS = ("prompt", "tool_input", "tool_output")
"""The exact scrubbing alphabet extension the 001-era logging owns (Req 5.4)."""


def test_scrubbing_extra_patterns_constant_unchanged_by_watsonx() -> None:
    """The scrubbing alphabet extension is exactly the canonical triple (Req 8.5).

    Source-of-truth guard: activating the watsonx provider must NOT add a
    provider-specific scrubbing stem (e.g. ``watsonx_apikey`` / ``project_id``).
    Asserting *equality* (not a superset) on the module constant catches any
    such addition — complementing ``test_logging_setup``'s superset check which
    would stay green even if a watsonx pattern were appended.
    """
    assert tuple(_SCRUBBING_EXTRA_PATTERNS) == _CANONICAL_EXTRA_PATTERNS


@pytest.fixture
def patched_logfire(monkeypatch: pytest.MonkeyPatch) -> dict[str, MagicMock]:
    """Replace logfire's configure + instrument_* entry points with mocks.

    Mirrors ``test_logging_setup``'s fixture so we can read the ``scrubbing``
    kwarg handed to :func:`logfire.configure` without standing up a real
    exporter or running instrumentation side effects.
    """
    mocks = {
        "configure": MagicMock(return_value=MagicMock()),
        "instrument_pydantic_ai": MagicMock(),
        "instrument_fastapi": MagicMock(),
        "instrument_httpx": MagicMock(),
    }
    for name, mock in mocks.items():
        monkeypatch.setattr(f"pydantic_ai_sandbox.logging_setup.logfire.{name}", mock)
    return mocks


def test_configure_under_watsonx_passes_exactly_canonical_patterns(
    watsonx_settings_factory: WatsonxSettingsFactory,
    patched_logfire: dict[str, MagicMock],
) -> None:
    """``configure_observability`` under a watsonx selection scrubs the exact triple (Req 8.5).

    Behavioural counterpart to the constant guard: with ``LLM_PROVIDER=watsonx``
    (and valid creds so :class:`Settings` validates), the ``ScrubbingOptions``
    reaching :func:`logfire.configure` must carry **exactly**
    ``["prompt", "tool_input", "tool_output"]`` — no watsonx-specific pattern
    added, no canonical pattern dropped. Equality is the load-bearing assertion
    (``test_logging_setup`` already pins the superset).
    """
    settings = watsonx_settings_factory(LOGFIRE_TOKEN="dummy-token")

    configure_observability(FastAPI(), settings)

    configure_call = patched_logfire["configure"].call_args
    scrubbing = configure_call.kwargs.get("scrubbing")
    assert isinstance(scrubbing, logfire.ScrubbingOptions), (
        f"scrubbing kwarg must be a ScrubbingOptions; got {type(scrubbing).__name__}"
    )
    assert tuple(scrubbing.extra_patterns or []) == _CANONICAL_EXTRA_PATTERNS, (
        f"watsonx must not change the scrubbing alphabet; got {scrubbing.extra_patterns}"
    )
