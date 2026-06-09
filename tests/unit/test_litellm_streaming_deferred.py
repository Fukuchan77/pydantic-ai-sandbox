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
