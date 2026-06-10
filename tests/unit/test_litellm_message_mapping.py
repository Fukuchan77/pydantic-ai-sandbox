"""Hermetic message/tool-mapping tests for ``LiteLLMModel.request`` (Tasks 2.2 → 3.2).

Pins that ``request()`` maps the conversation via ``_map_messages`` and the tool
definitions via ``_map_tools`` from the shared ``_openai_mapping`` module before
calling :func:`litellm.acompletion`, and that an unsupported message part fails
loud as :class:`NotImplementedError` (a mapping error — surfaced unwrapped, never
silently dropped). ``acompletion`` is mocked, so no request leaves the process.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import litellm
import pytest
from pydantic_ai.messages import ImageUrl, ModelMessage, ModelRequest, UserPromptPart
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.tools import ToolDefinition

# The shared mapping helpers ``request()`` is required to delegate to (Req 11):
# asserting ``acompletion`` receives exactly their output proves the single-
# implementation reuse, not merely an equivalent inline shape. The scoped
# suppressions acknowledge the cross-module underscore hop (tech.md convention).
from pydantic_ai_sandbox.llm._openai_mapping import (
    _map_messages,  # pyright: ignore[reportPrivateUsage]
    _map_tools,  # pyright: ignore[reportPrivateUsage]
)
from pydantic_ai_sandbox.llm.providers.litellm import LiteLLMModel

if TYPE_CHECKING:
    from collections.abc import Callable

_ROUTE = "watsonx/dummy-watsonx-model"


def _model() -> LiteLLMModel:
    return LiteLLMModel(model_name=_ROUTE, timeout_connect=30.0, timeout_read=120.0)


def _text_response() -> litellm.ModelResponse:
    return litellm.ModelResponse(
        id="chatcmpl-map",
        object="chat.completion",
        created=0,
        model=_ROUTE,
        choices=[
            {
                "index": 0,
                "message": {"role": "assistant", "content": "ok"},
                "finish_reason": "stop",
            },
        ],
        usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    )


def _capturing(captured: dict[str, Any]) -> Callable[..., Any]:
    """An async ``acompletion`` stand-in that records its kwargs."""

    async def _fake(**kwargs: Any) -> Any:
        captured.update(kwargs)
        return _text_response()

    return _fake


async def test_request_maps_messages_via_openai_mapping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The history is mapped via ``_map_messages`` to OpenAI-shaped messages."""
    captured: dict[str, Any] = {}
    monkeypatch.setattr(litellm, "acompletion", _capturing(captured))
    messages: list[ModelMessage] = [ModelRequest(parts=[UserPromptPart("hello")])]

    await _model().request(messages, None, ModelRequestParameters())

    assert captured["messages"] == [{"role": "user", "content": "hello"}]
    # Delegation proof (Req 11): the payload is exactly the shared helper's output,
    # not an equivalent inline mapping that could later drift from the SDK path.
    assert captured["messages"] == _map_messages(messages)
    assert captured["model"] == _ROUTE


async def test_request_maps_tools_via_openai_mapping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Function tools are advertised to ``acompletion`` via ``_map_tools``."""
    captured: dict[str, Any] = {}
    monkeypatch.setattr(litellm, "acompletion", _capturing(captured))
    messages: list[ModelMessage] = [ModelRequest(parts=[UserPromptPart("hi")])]
    params = ModelRequestParameters(
        function_tools=[
            ToolDefinition(
                name="search_kb",
                description="Search the KB",
                parameters_json_schema={"type": "object", "properties": {}},
            ),
        ],
    )

    await _model().request(messages, None, params)

    assert captured["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "search_kb",
                "description": "Search the KB",
                "parameters": {"type": "object", "properties": {}},
            },
        },
    ]
    # Delegation proof (Req 11): the advertised tools are exactly the shared
    # helper's output, pinning single-implementation reuse with the SDK path.
    assert captured["tools"] == _map_tools(params)


async def test_request_passes_none_tools_when_no_definitions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no tools registered, ``tools`` is ``None`` (the SDK arg stays unset)."""
    captured: dict[str, Any] = {}
    monkeypatch.setattr(litellm, "acompletion", _capturing(captured))
    messages: list[ModelMessage] = [ModelRequest(parts=[UserPromptPart("hi")])]

    await _model().request(messages, None, ModelRequestParameters())

    assert captured["tools"] is None


async def test_request_unsupported_part_raises_notimplemented(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A multimodal user part raises ``NotImplementedError`` before any call.

    Mapping errors fail loud (never silently dropped) and are not wrapped as
    ``ModelAPIError``; the raise happens during ``_map_messages``, before
    ``acompletion`` is reached.
    """

    async def _must_not_call(**_kwargs: Any) -> Any:
        msg = "acompletion must not be called when mapping fails"
        raise AssertionError(msg)

    monkeypatch.setattr(litellm, "acompletion", _must_not_call)
    messages: list[ModelMessage] = [
        ModelRequest(parts=[UserPromptPart(content=[ImageUrl(url="https://example.com/x.png")])]),
    ]

    with pytest.raises(NotImplementedError):
        await _model().request(messages, None, ModelRequestParameters())
