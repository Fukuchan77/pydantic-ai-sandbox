"""Failover behavioural tests for ``FallbackModel`` (Task 5.3).

Spec text: "``FallbackModel(failing_fn, success_fn)`` を直接構築 ...
``Agent(model=fallback).run(...)`` が success_fn の出力を返すこと",
"logfire span 属性 (provider 名 / error class) が含まれることを assert".

Pydantic AI V2's ``FallbackModel.request`` recovers from
``ModelAPIError`` (the default ``fallback_on``) and emits a single
successful ``chat`` span via ``instrument_pydantic_ai`` — the failed
attempts do not appear as separate spans, but the ``invoke_agent``
parent span carries the entire chain in ``model_name`` (e.g.
``"fallback:fake-fail-provider,fake-success-provider"``). That string
satisfies the "provider 名" half of the requirement directly, and is the
only span surface where the failed provider's identity survives.

For the "error class" half we fall back to the all-fail path: when every
member raises, ``FallbackModel`` re-raises a ``FallbackExceptionGroup``
whose ``.exceptions`` list carries the original ``ModelAPIError``
instances. That object is the canonical record of "which exception
classes drove the failover decision" — span attributes are not
emitted for failed attempts in V2 Beta, so the ExceptionGroup is the
authoritative artifact.

This file therefore expresses the requirement in two complementary
assertions: (1) the success-after-failure happy path with a span-text
assertion on the surviving chain, (2) the all-fail path with an
ExceptionGroup-shape assertion on the recovered error classes.
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
from pydantic_ai.exceptions import FallbackExceptionGroup, ModelAPIError
from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.models.function import FunctionModel

from tests.support.model_fakes import function_model_raising

if TYPE_CHECKING:
    from collections.abc import Iterator

    from pydantic_ai.messages import ModelMessage
    from pydantic_ai.models.function import AgentInfo


@pytest.fixture
def captured_spans() -> Iterator[TestExporter]:
    """Configure logfire with an in-memory exporter and pydantic-ai spans.

    Mirrors the body of :func:`logfire.testing.capfire` but stripped to
    just the trace surface this test cares about. Yielding rather than
    returning lets pytest reset logfire's global state between tests if
    that ever becomes necessary; for now the exporter starts empty per
    test because each invocation gets a fresh instance.
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


def _success_function_model(model_name: str, text: str) -> FunctionModel:
    """Locally-scoped success fake — kept here rather than in
    ``model_fakes`` because no other test needs the parametric
    ``text`` knob; promoting it would widen the support surface for a
    single caller."""

    def _respond(
        _messages: list[ModelMessage],
        _info: AgentInfo,
    ) -> ModelResponse:
        return ModelResponse(parts=[TextPart(text)])

    return FunctionModel(_respond, model_name=model_name)


def test_failover_returns_success_member_output(captured_spans: TestExporter) -> None:
    """A failing first member yields control to the second, surfacing its output.

    Uses ``ModelAPIError`` because that is the only exception class
    ``FallbackModel`` treats as recoverable by default — handing in a
    plain ``RuntimeError`` would propagate without engaging the fallback
    path and silently weaken the test. The model_name strings on each
    fake bubble up into the span attribute the second assertion reads.
    """
    fail_model = function_model_raising(
        ModelAPIError(model_name="fake-fail-provider", message="simulated failure"),
        model_name="fake-fail-provider",
    )
    success_model = _success_function_model(
        model_name="fake-success-provider",
        text="hello from the second member",
    )
    fallback = FallbackModel(fail_model, success_model)
    agent = Agent(model=fallback)

    result = agent.run_sync("trigger the chain")

    assert result.output == "hello from the second member"

    # ``invoke_agent`` is the parent span; its ``model_name`` attribute
    # spells the entire fallback chain ("fallback:<a>,<b>") regardless of
    # which member ultimately answered. Both fake provider names must
    # appear so the test fails loudly if FallbackModel ever stops
    # threading the failed member into the span surface. The span's
    # ``name`` field embeds the agent variable name (pydantic-ai
    # introspects the binding) which is brittle — filter by the
    # ``gen_ai.operation.name == "invoke_agent"`` attribute instead so
    # this test stays insensitive to local-binding renames.
    spans = captured_spans.exported_spans_as_dict(include_resources=False)
    invoke_agent_spans = [
        s for s in spans if s.get("attributes", {}).get("gen_ai.operation.name") == "invoke_agent"
    ]
    assert len(invoke_agent_spans) == 1, (
        f"expected exactly one invoke_agent span, got {len(invoke_agent_spans)}"
    )
    chain_attr = str(invoke_agent_spans[0]["attributes"].get("model_name", ""))
    assert "fake-fail-provider" in chain_attr
    assert "fake-success-provider" in chain_attr


def test_all_members_failing_raises_exception_group_with_original_error_classes() -> None:
    """When every member raises, the recovered exception group preserves the
    original error classes — the load-bearing artifact for "error class" assertion.

    ``instrument_pydantic_ai`` does not stamp failed-attempt info on the
    success span (see module docstring); the exception object is
    therefore the authoritative carrier of the error-class identity that
    drove each failover decision. Asserting on
    ``FallbackExceptionGroup.exceptions`` proves the failover path
    actually iterated through every member rather than short-circuiting
    on the first raise.
    """
    err_a = ModelAPIError(model_name="fake-a", message="boom-a")
    err_b = ModelAPIError(model_name="fake-b", message="boom-b")
    fallback = FallbackModel(
        function_model_raising(err_a, model_name="fake-a"),
        function_model_raising(err_b, model_name="fake-b"),
    )
    agent = Agent(model=fallback)

    with pytest.raises(FallbackExceptionGroup) as exc_info:
        agent.run_sync("force all failures")

    recovered = list(exc_info.value.exceptions)
    assert len(recovered) == 2
    # Identity check, not just isinstance, because the spec wants the
    # exact error instances threaded through — proving FallbackModel
    # did not wrap or replace them.
    assert recovered[0] is err_a
    assert recovered[1] is err_b
