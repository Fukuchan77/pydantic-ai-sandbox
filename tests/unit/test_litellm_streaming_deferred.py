"""Hermetic streaming-deferral tests for ``LiteLLMModel.request_stream`` (Tasks 2.4 → 3.6).

``request_stream`` is an ``@asynccontextmanager`` that raises
``NotImplementedError`` **before any yield** — streaming is deferred to future
work and must never silently downgrade to a non-streaming request (Req 8.1/8.2).
The message is greppable and names the model so a future caller wiring streaming
gets an explicit signal rather than the base ABC's generic refusal (Req 8.3).
Entering the context manager raises before any transport call, so no request
leaves the process.
"""

from __future__ import annotations

import pytest
from pydantic_ai.messages import ModelMessage, ModelRequest, UserPromptPart
from pydantic_ai.models import ModelRequestParameters

from pydantic_ai_sandbox.llm.providers.litellm import LiteLLMModel

_ROUTE = "watsonx/dummy-watsonx-model"


def _model() -> LiteLLMModel:
    return LiteLLMModel(model_name=_ROUTE, timeout_connect=30.0, timeout_read=120.0)


async def test_request_stream_raises_not_implemented() -> None:
    """Entering ``request_stream`` raises ``NotImplementedError`` before any yield (Req 8.1)."""
    model = _model()
    messages: list[ModelMessage] = [ModelRequest(parts=[UserPromptPart("hi")])]

    with pytest.raises(NotImplementedError):
        async with model.request_stream(messages, None, ModelRequestParameters()):
            pass  # pragma: no cover — context entry raises before the body runs


async def test_request_stream_message_is_greppable_and_names_model() -> None:
    """The refusal carries the greppable deferral message and the model route (Req 8.3).

    The match text is unique to this override (absent from the base ABC's generic
    ``NotImplementedError``), so a caller can grep for ``streaming support
    deferred`` and the route is named for an actionable signal.
    """
    model = _model()
    messages: list[ModelMessage] = [ModelRequest(parts=[UserPromptPart("hi")])]

    with pytest.raises(NotImplementedError, match="streaming support deferred") as excinfo:
        async with model.request_stream(messages, None, ModelRequestParameters()):
            pass  # pragma: no cover — context entry raises before the body runs

    assert _ROUTE in str(excinfo.value)


async def test_request_stream_raises_before_any_yield_without_downgrading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The refusal precedes any yield and never downgrades to a request (Req 8.1/8.2).

    Two failure modes are pinned that the bare ``pytest.raises`` cases above cover
    only implicitly:

    * **Body never runs.** ``@asynccontextmanager`` raises on ``__aenter__`` (the
      generator raises before reaching its ``yield``), so the ``async with`` body
      must never execute. A sentinel proves the raise *precedes* the yield rather
      than surfacing from inside the managed block — the literal "before any yield"
      clause of the task.
    * **No silent downgrade.** ``request_stream`` must not quietly fall back to a
      non-streaming ``acompletion`` call (Req 8.2). ``litellm.acompletion`` is
      detonated; reaching it fails the test, proving streaming is refused outright
      rather than serviced by the non-streaming path.
    """
    import litellm

    def _detonate(**_: object) -> object:
        msg = "request_stream must not downgrade to acompletion (Req 8.2)"
        raise AssertionError(msg)

    monkeypatch.setattr(litellm, "acompletion", _detonate)

    model = _model()
    messages: list[ModelMessage] = [ModelRequest(parts=[UserPromptPart("hi")])]
    body_ran = False

    with pytest.raises(NotImplementedError, match="streaming support deferred"):
        async with model.request_stream(messages, None, ModelRequestParameters()):
            body_ran = True  # pragma: no cover — context entry raises before the body runs

    assert body_ran is False
