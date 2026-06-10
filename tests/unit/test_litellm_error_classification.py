"""Hermetic error-classification tests for ``LiteLLMModel.request`` (Tasks 2.3 → 3.4).

Every exception raised by ``litellm.acompletion()`` is wrapped as
:class:`pydantic_ai.exceptions.ModelAPIError`, chained via ``raise ... from`` and
naming the model, so ``FallbackModel.fallback_on`` (default ``(ModelAPIError,)``)
can recover it (Req 4.1). The broad ``except`` scopes **only** the ``acompletion``
call: the subsequent ``.model_dump()`` / ``build_response`` sit outside the
``try``, so a post-call mapping/response error (``UnexpectedModelBehavior`` for a
choiceless completion, ``NotImplementedError`` for an unsupported part) surfaces
unwrapped and fails loud — never misclassified as a recoverable ``ModelAPIError``
(Req 4.3). ``acompletion`` is mocked, so no request leaves the process.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import litellm
import pytest
from pydantic_ai import Agent
from pydantic_ai.exceptions import ModelAPIError, UnexpectedModelBehavior
from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, TextPart, UserPromptPart
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.models.function import FunctionModel

from pydantic_ai_sandbox.llm.providers.litellm import LiteLLMModel

if TYPE_CHECKING:
    from collections.abc import Callable

    from pydantic_ai.models.function import AgentInfo

_ROUTE = "watsonx/dummy-watsonx-model"


def _model() -> LiteLLMModel:
    return LiteLLMModel(model_name=_ROUTE, timeout_connect=30.0, timeout_read=120.0)


def _raising(exc: BaseException) -> Callable[..., Any]:
    """An async ``acompletion`` stand-in that always raises ``exc``."""

    async def _fake(**_kwargs: Any) -> Any:
        raise exc

    return _fake


async def _request(monkeypatch: pytest.MonkeyPatch, fake: Callable[..., Any]) -> Any:
    monkeypatch.setattr(litellm, "acompletion", fake)
    messages: list[ModelMessage] = [ModelRequest(parts=[UserPromptPart("hi")])]
    return await _model().request(messages, None, ModelRequestParameters())


async def test_acompletion_error_wrapped_as_model_api_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An ``acompletion`` failure surfaces as ``ModelAPIError``, chained (Req 4.1).

    ``FallbackModel`` recovers ``ModelAPIError``, so the original exception must be
    re-raised wrapped (with the cause preserved via ``raise ... from``) rather than
    escaping the chain.
    """
    original = RuntimeError("backend exploded")

    with pytest.raises(ModelAPIError) as excinfo:
        await _request(monkeypatch, _raising(original))

    assert excinfo.value.__cause__ is original


async def test_wrapped_error_names_the_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """The wrapped ``ModelAPIError`` carries the model route for diagnostics.

    ``model_name`` rides the dedicated ``ModelAPIError.model_name`` attribute (it
    surfaces on the instrumentation span), not the free-text message — matching the
    SDK transport's wrapping convention.
    """
    with pytest.raises(ModelAPIError) as excinfo:
        await _request(monkeypatch, _raising(ValueError("boom")))

    assert excinfo.value.model_name == _ROUTE


@pytest.mark.parametrize(
    "exc",
    [
        RuntimeError("runtime"),
        ValueError("value"),
        KeyError("key"),
        TimeoutError("timeout"),
        ConnectionError("connection"),
    ],
)
async def test_broad_except_wraps_any_exception_type(
    monkeypatch: pytest.MonkeyPatch,
    exc: Exception,
) -> None:
    """The broad ``except`` wraps **every** exception type (Req 4.1).

    LiteLLM multiplexes many backends, each with its own exception hierarchy and no
    shared narrowly-nameable base — so unlike the SDK transport (which catches a
    specific tuple and lets a programming-bug ``RuntimeError`` fail loud), this
    transport must wrap *anything* ``acompletion`` raises so the fallback chain can
    recover it. Every type lands as ``ModelAPIError``.
    """
    with pytest.raises(ModelAPIError):
        await _request(monkeypatch, _raising(exc))


async def test_post_call_mapping_error_not_wrapped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A choiceless completion raises ``UnexpectedModelBehavior`` unwrapped (Req 4.3).

    ``acompletion`` succeeds; the empty-``choices`` failure is raised by
    ``build_response`` **after** the ``try`` block, so it must surface unwrapped —
    proving the broad ``except`` scopes only the ``acompletion`` call and never
    misclassifies a mapping/response error as a recoverable ``ModelAPIError``.
    """

    class _EmptyChoices:
        def model_dump(self) -> dict[str, Any]:
            return {"id": "chatcmpl-empty", "choices": []}

    async def _fake(**_kwargs: Any) -> Any:
        return _EmptyChoices()

    monkeypatch.setattr(litellm, "acompletion", _fake)
    messages: list[ModelMessage] = [ModelRequest(parts=[UserPromptPart("hi")])]

    with pytest.raises(UnexpectedModelBehavior):
        await _model().request(messages, None, ModelRequestParameters())


def _recovering_function_model(model_name: str, text: str) -> FunctionModel:
    """A success fake returning a single ``TextPart`` — the recovering chain member.

    Kept local (not promoted to ``tests.support.model_fakes``) for the same reason
    ``tests/unit/test_watsonx_fallback_integration.py`` records: no other test needs
    the parametric ``text`` knob, so promoting it would widen the shared support
    surface for a single caller.
    """

    def _respond(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[TextPart(text)])

    return FunctionModel(_respond, model_name=model_name)


def test_litellm_failure_recovered_by_fallback_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failing ``LiteLLMModel`` is recovered by ``FallbackModel`` end-to-end (Req 10.2).

    This closes the loop the unit-level wrapping tests above only assert one half
    of: they prove ``acompletion`` failures become ``ModelAPIError``; this proves
    that classification is *actionable* — a real :class:`LiteLLMModel` (with
    ``acompletion`` monkeypatched to raise) seated first in a
    :class:`FallbackModel` yields control to the next member, whose answer is
    returned. ``FallbackModel``'s default ``fallback_on`` is ``(ModelAPIError,)``
    and it tries each member exactly once (no retry loop), so the recovering
    member answering *is* the proof: the LiteLLM failure never escapes the chain.

    Mirrors the failover shape of
    ``tests/unit/test_watsonx_fallback_integration.py`` but with a genuine
    ``LiteLLMModel`` as the failing member (not a ``FunctionModel`` double), so the
    transport's own broad-except → ``ModelAPIError`` wrapping is what is exercised.
    Hermetic: ``acompletion`` is mocked, so no request leaves the process.
    """
    monkeypatch.setattr(
        litellm,
        "acompletion",
        _raising(RuntimeError("backend exploded")),
    )
    litellm_fail = _model()
    recovering = _recovering_function_model(
        model_name="ollama",
        text="answered after litellm failed",
    )
    agent = Agent(model=FallbackModel(litellm_fail, recovering))

    result = agent.run_sync("trigger litellm failover")

    assert result.output == "answered after litellm failed"
