"""Hermetic response-mapping tests for ``LiteLLMModel.request`` (Tasks 2.2 → 3.3).

Exercises the load-bearing normalization path: ``litellm.acompletion()`` returns a
``litellm.ModelResponse`` **object**, which ``request()`` converts via
``.model_dump()`` into the OpenAI-shaped ``dict`` the shared ``build_response``
consumes. ``.model_dump()`` (not attribute access) is required because it
preserves ``tool_calls[].function.arguments`` as the **raw JSON string** the
backend sent — so Granite's double-encoded args survive faithfully (Req 2.4).

Also pins finish-reason mapping (the full ``_FINISH_REASON_MAP`` plus the
absent / unmapped key → ``None`` branches, Req 3.2), absent-usage → zeroed
``RequestUsage``, and a choiceless response raising
:class:`UnexpectedModelBehavior` unwrapped (Req 3.3). ``acompletion`` is mocked,
so no request leaves the process.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import litellm
import pytest
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    TextPart,
    ToolCallPart,
    UserPromptPart,
)
from pydantic_ai.models import ModelRequestParameters

from pydantic_ai_sandbox.llm.providers.litellm import LiteLLMModel

if TYPE_CHECKING:
    from collections.abc import Callable

_ROUTE = "watsonx/dummy-watsonx-model"


def _model() -> LiteLLMModel:
    return LiteLLMModel(model_name=_ROUTE, timeout_connect=30.0, timeout_read=120.0)


def _returning(response: Any) -> Callable[..., Any]:
    async def _fake(**_kwargs: Any) -> Any:
        return response

    return _fake


async def _request_with(monkeypatch: pytest.MonkeyPatch, response: Any) -> Any:
    monkeypatch.setattr(litellm, "acompletion", _returning(response))
    messages: list[ModelMessage] = [ModelRequest(parts=[UserPromptPart("hello")])]
    return await _model().request(messages, None, ModelRequestParameters())


async def test_text_response_maps_to_text_part(monkeypatch: pytest.MonkeyPatch) -> None:
    """A text completion round-trips through ``.model_dump()`` → ``build_response``."""
    response = litellm.ModelResponse(
        id="chatcmpl-text",
        object="chat.completion",
        created=0,
        model=_ROUTE,
        choices=[
            {
                "index": 0,
                "message": {"role": "assistant", "content": "hi there"},
                "finish_reason": "stop",
            },
        ],
        usage={"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
    )

    result = await _request_with(monkeypatch, response)

    assert len(result.parts) == 1
    part = result.parts[0]
    assert isinstance(part, TextPart)
    assert part.content == "hi there"
    assert result.finish_reason == "stop"
    assert result.usage.input_tokens == 5
    assert result.usage.output_tokens == 3
    assert result.provider_response_id == "chatcmpl-text"
    assert result.model_name == _ROUTE


async def test_tool_call_arguments_preserved_as_raw_json_string(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Double-encoded tool-call ``arguments`` survive as the raw string (Req 2.4).

    ``.model_dump()`` keeps ``function.arguments`` as the exact JSON string the
    backend sent — Granite double-encodes its args, and re-parsing would corrupt
    them. The :class:`ToolCallPart` must carry that raw string verbatim.
    """
    double_encoded = json.dumps(json.dumps({"query": "weather"}))
    response = litellm.ModelResponse(
        id="chatcmpl-tool",
        object="chat.completion",
        created=0,
        model=_ROUTE,
        choices=[
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_kb_1",
                            "type": "function",
                            "function": {"name": "search_kb", "arguments": double_encoded},
                        },
                    ],
                },
                "finish_reason": "tool_calls",
            },
        ],
        usage={"prompt_tokens": 20, "completion_tokens": 4, "total_tokens": 24},
    )

    result = await _request_with(monkeypatch, response)

    assert len(result.parts) == 1
    part = result.parts[0]
    assert isinstance(part, ToolCallPart)
    assert part.tool_name == "search_kb"
    assert part.tool_call_id == "call_kb_1"
    # The raw, double-encoded JSON string is surfaced verbatim — not re-parsed.
    assert part.args == double_encoded
    # finish_reason "tool_calls" normalises to pydantic_ai's "tool_call".
    assert result.finish_reason == "tool_call"


class _StubResponse:
    """A minimal ``acompletion`` return whose ``model_dump`` yields ``raw``."""

    def __init__(self, raw: dict[str, Any]) -> None:
        self._raw = raw

    def model_dump(self) -> dict[str, Any]:
        return self._raw


async def test_absent_usage_yields_zeroed_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    """A response with no ``usage`` block yields a zeroed ``RequestUsage`` (Req 3.4)."""
    stub = _StubResponse(
        {
            "id": "chatcmpl-nousage",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "ok"},
                    "finish_reason": "stop",
                },
            ],
        },
    )

    result = await _request_with(monkeypatch, stub)

    assert result.usage.input_tokens == 0
    assert result.usage.output_tokens == 0


async def test_empty_choices_raises_unexpected_model_behavior(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A choiceless completion raises ``UnexpectedModelBehavior`` unwrapped (Req 3.3)."""
    stub = _StubResponse({"id": "chatcmpl-empty", "choices": []})

    with pytest.raises(UnexpectedModelBehavior):
        await _request_with(monkeypatch, stub)


# Sentinel distinguishing an *absent* ``finish_reason`` key from an explicit
# ``None`` value — both must normalise to ``None`` but exercise different
# branches of ``build_response`` (``choice.get(...)`` missing vs. falsy).
_ABSENT = object()


@pytest.mark.parametrize(
    ("raw_finish_reason", "expected"),
    [
        ("stop", "stop"),
        ("length", "length"),
        ("tool_calls", "tool_call"),
        ("content_filter", "content_filter"),
        ("function_call", "tool_call"),
        ("made_up_reason", None),  # unmapped key → None (pydantic_ai default, Req 3.2)
        (None, None),  # explicit null reason → None (Req 3.2)
        (_ABSENT, None),  # absent key entirely → None (Req 3.2)
    ],
)
async def test_finish_reason_mapping(
    monkeypatch: pytest.MonkeyPatch,
    raw_finish_reason: object,
    expected: str | None,
) -> None:
    """Finish-reason keys map per ``_FINISH_REASON_MAP``; absent/unmapped → ``None`` (Req 3.2).

    Drives the mapping through the full ``request()`` → ``.model_dump()`` →
    ``build_response`` path (not the shared helper in isolation), pinning that the
    LiteLLM transport surfaces every mapped key and collapses an absent, explicitly
    ``None``, or unrecognised key to ``None`` — the same normalisation the SDK
    transport applies, for observability parity.
    """
    choice: dict[str, Any] = {
        "index": 0,
        "message": {"role": "assistant", "content": "ok"},
    }
    if raw_finish_reason is not _ABSENT:
        choice["finish_reason"] = raw_finish_reason
    stub = _StubResponse({"id": "chatcmpl-fr", "choices": [choice]})

    result = await _request_with(monkeypatch, stub)

    assert result.finish_reason == expected
