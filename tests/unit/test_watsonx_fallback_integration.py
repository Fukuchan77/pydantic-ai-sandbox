"""Fallback integration tests for the watsonx provider (Task 7.6).

Pins the three behaviours tasks.md T7.6 names, all hermetic (no SDK import,
no network) via ``FunctionModel`` substitutes — Req 7.1 / 7.2 / 7.4 / 9.8:

1. **Immediate failover when watsonx fails** — a watsonx member that raises
   ``ModelAPIError`` yields control to the next chain member, whose output is
   returned. ``FallbackModel`` treats only ``ModelAPIError`` (its default
   ``fallback_on``) as recoverable and tries each member exactly once with no
   retry loop, so a successful next-member answer *is* the proof of immediate
   failover. The construction-level no-retry pin (SDK ``max_retries=0``) is
   Task 7.5's job; this file pins the chain-level recovery (Req 7.1).
2. **watsonx no longer silently dropped** — Task 4.2 promoted ``watsonx`` out
   of ``_MVP_STUB_PROVIDERS`` into a real :func:`_build_watsonx` Model, so
   ``_build_fallback`` must keep it as a chain member rather than filtering it
   like the remaining stubs (``anthropic`` / ``bedrock``). The structural test
   builds ``FALLBACK_ORDER=ollama,watsonx`` and asserts a real
   :class:`WatsonxSDKModel` survives into ``FallbackModel.models`` (Req 7.2).
3. **``FALLBACK_ORDER=ollama,watsonx`` failover logged** — a chain whose first
   member (ollama) fails and whose second (watsonx) recovers emits a single
   ``invoke_agent`` span whose ``model_name`` attribute spells the entire chain
   (``"fallback:ollama,watsonx"``), so the failover is observable in
   instrumentation (Req 9.8). Mirrors the span surface pinned by
   ``tests/unit/test_fallback_failover.py``.

The substitutes come from :mod:`tests.support.model_fakes`
(``watsonx_function_model_failing``, Task 3.2) plus a locally-scoped success
fake — the same split ``test_fallback_failover.py`` uses, keeping the
parametric success ``text`` knob out of the shared support surface.

Characterization posture (same as Tasks 7.1 / 7.3 / 7.4 / 7.5): the source
landed earlier (Task 4.2 de-stubbing, Task 5.4 ``ModelAPIError`` wrapping,
Task 3.2 doubles), so these tests pin/guard the contract rather than drive new
code. The RED was the absent file (collection error).
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
from pydantic_ai import Agent
from pydantic_ai.exceptions import ModelAPIError
from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.models.function import FunctionModel

from pydantic_ai_sandbox.config import get_settings
from pydantic_ai_sandbox.llm.fallback import (
    # Spec-mandated underscore-prefixed name (plan.md §2.4) exported via
    # ``llm.fallback.__all__``; mirrors the import convention in
    # ``tests/unit/test_factory_fallback.py``.
    _build_fallback,  # pyright: ignore[reportPrivateUsage]
)
from pydantic_ai_sandbox.llm.providers.watsonx import WatsonxSDKModel
from tests.support.model_fakes import (
    function_model_raising,
    watsonx_function_model_failing,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from pydantic_ai.messages import ModelMessage
    from pydantic_ai.models.function import AgentInfo

    from tests.conftest import WatsonxSettingsFactory


# Mirrors the dummy Ollama values used by the T4/T5 dispatch + fallback tests so
# the hardcoded-model-ID guard (T2.1) keeps treating this module as clean.
DUMMY_OLLAMA_MODEL = "dummy-ollama-model"
DUMMY_OLLAMA_URL = "http://localhost:11434"


def _success_function_model(model_name: str, text: str) -> FunctionModel:
    """Locally-scoped success fake returning a single ``TextPart``.

    Kept here rather than in ``tests.support.model_fakes`` because no other
    test needs the parametric ``text`` knob — promoting it would widen the
    shared support surface for a single caller (the same reasoning
    ``tests/unit/test_fallback_failover.py`` records for its identical helper).
    """

    def _respond(
        _messages: list[ModelMessage],
        _info: AgentInfo,
    ) -> ModelResponse:
        return ModelResponse(parts=[TextPart(text)])

    return FunctionModel(_respond, model_name=model_name)


@pytest.fixture
def captured_spans() -> Iterator[TestExporter]:
    """Configure logfire with an in-memory exporter and pydantic-ai spans.

    Mirrors ``tests/unit/test_fallback_failover.py``'s fixture: a stripped-down
    :func:`logfire.testing.capfire` exposing just the trace surface needed to
    read the ``invoke_agent`` chain attribute. Each test gets a fresh exporter.
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


def test_watsonx_failure_triggers_immediate_failover_to_next_member() -> None:
    """A failing watsonx member yields immediately to the next chain member.

    Uses the shared ``watsonx_function_model_failing`` double (Task 3.2), which
    raises ``ModelAPIError`` — the exact class ``FallbackModel`` recovers by
    default. ``FallbackModel`` tries each member exactly once (no retry loop),
    so the second member answering proves the failover was *immediate*: control
    passed on the first watsonx raise rather than spinning or propagating the
    error (Req 7.1 / 7.2). The watsonx ``ModelAPIError`` never escapes — its
    absence from the result is the recovery proof.
    """
    watsonx_fail = watsonx_function_model_failing(model_name="watsonx")
    recovering = _success_function_model(
        model_name="ollama",
        text="answered after watsonx failed",
    )
    fallback = FallbackModel(watsonx_fail, recovering)
    agent = Agent(model=fallback)

    result = agent.run_sync("trigger watsonx failover")

    assert result.output == "answered after watsonx failed"


def test_build_fallback_keeps_watsonx_as_real_member(
    watsonx_settings_factory: WatsonxSettingsFactory,
) -> None:
    """``_build_fallback`` no longer silently drops watsonx (Req 7.2).

    Task 4.2 promoted ``watsonx`` out of ``_MVP_STUB_PROVIDERS`` into a real
    :func:`_build_watsonx` Model, so a ``FALLBACK_ORDER=ollama,watsonx`` chain
    must retain *both* members — the stub-skipping branch only filters the
    remaining stubs (``anthropic`` / ``bedrock``). This pins the regression:
    were watsonx re-stubbed, it would vanish from ``FallbackModel.models`` and
    the length / type assertions below would fail.

    Construction is I/O-free: ``_build_fallback`` → recursive ``get_model`` →
    ``_build_ollama`` (lazy client) and ``_build_watsonx`` →
    :class:`WatsonxSDKModel` (I/O-free ``__init__``, SDK client built lazily on
    first request). ``watsonx_settings_factory`` seats valid creds so the
    credential gate (config Task 2.2) passes for ``watsonx ∈ FALLBACK_ORDER``;
    the ``LLM_PROVIDER`` / ``FALLBACK_ORDER`` / ``OLLAMA_MODEL_NAME`` overrides
    reshape it into a fallback selection.
    """
    settings = watsonx_settings_factory(
        LLM_PROVIDER="fallback",
        FALLBACK_ORDER="ollama,watsonx",
        OLLAMA_BASE_URL=DUMMY_OLLAMA_URL,
        OLLAMA_MODEL_NAME=DUMMY_OLLAMA_MODEL,
    )
    # ``_build_fallback`` recurses via ``get_model`` → ``get_settings()`` (the
    # cached singleton), not the passed ``settings``; clear the cache so the
    # recursion reads the factory's monkeypatched env. Restore on teardown so a
    # stale watsonx-credentialled singleton cannot leak into later tests.
    get_settings.cache_clear()
    try:
        model = _build_fallback(settings)
    finally:
        get_settings.cache_clear()

    assert isinstance(model, FallbackModel)
    # Both members survive — watsonx is NOT filtered like a stub would be.
    assert len(model.models) == 2
    assert any(isinstance(member, WatsonxSDKModel) for member in model.models), (
        "watsonx was silently dropped from the fallback chain — it must resolve "
        "to a real WatsonxSDKModel (Task 4.2 de-stubbing, Req 7.2)."
    )


def test_ollama_watsonx_failover_is_logged_in_invoke_agent_span(
    captured_spans: TestExporter,
) -> None:
    """A ``FALLBACK_ORDER=ollama,watsonx`` failover surfaces the full chain (Req 9.8).

    Scenario mirrors the env-configured chain: ollama (the default/first member)
    fails, watsonx (the fallback) recovers. ``instrument_pydantic_ai`` emits one
    ``invoke_agent`` parent span whose ``model_name`` attribute spells the entire
    chain (``"fallback:ollama,watsonx"``) regardless of which member answered, so
    the failover is observable. Both provider names must appear, proving watsonx
    participates in (and is logged as part of) the chain. Filtered by the
    ``gen_ai.operation.name == "invoke_agent"`` attribute rather than the span
    ``name`` (which embeds the brittle local-binding variable name), per the
    convention in ``tests/unit/test_fallback_failover.py``.
    """
    ollama_fail = function_model_raising(
        ModelAPIError(model_name="ollama", message="simulated ollama failure"),
        model_name="ollama",
    )
    watsonx_recovering = _success_function_model(
        model_name="watsonx",
        text="watsonx recovered the ollama failure",
    )
    fallback = FallbackModel(ollama_fail, watsonx_recovering)
    agent = Agent(model=fallback)

    result = agent.run_sync("trigger ollama -> watsonx failover")

    assert result.output == "watsonx recovered the ollama failure"

    spans = captured_spans.exported_spans_as_dict(include_resources=False)
    invoke_agent_spans = [
        s for s in spans if s.get("attributes", {}).get("gen_ai.operation.name") == "invoke_agent"
    ]
    assert len(invoke_agent_spans) == 1, (
        f"expected exactly one invoke_agent span, got {len(invoke_agent_spans)}"
    )
    chain_attr = str(invoke_agent_spans[0]["attributes"].get("model_name", ""))
    assert "ollama" in chain_attr
    assert "watsonx" in chain_attr
