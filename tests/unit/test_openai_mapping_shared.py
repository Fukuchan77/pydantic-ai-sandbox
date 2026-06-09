"""Hermetic, transport-agnostic tests for ``llm._openai_mapping`` (Task 1.5).

These exercise the shared OpenAI-shaped mapping module (C1 / Req 11) **directly**
— not through any transport — so the contract both ``WatsonxSDKModel`` and the
forthcoming ``LiteLLMModel`` depend on is pinned in one place and cannot drift
(ADR-1). Identity fields (``model_name`` / ``provider_name``) are stamped with
arbitrary, non-watsonx values to prove :func:`build_response` was genuinely
generalised (Req 11) rather than re-hardcoding ``"watsonx"``.

Covered behaviour (Task 1.5 contract):

* message / tool / usage maps and the full request-history role mapping;
* ``_FINISH_REASON_MAP`` coverage incl. the unmapped/absent → ``None`` default;
* an unsupported (multimodal) part raises ``NotImplementedError`` naming the type;
* a choiceless response raises ``UnexpectedModelBehavior``;
* an absent ``usage`` block yields a zeroed ``RequestUsage``;
* tool-call ``arguments`` are surfaced as the **raw JSON string** the backend
  sent — a double-encoded Granite arg string is preserved, never re-encoded
  (Req 2.4).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.messages import (
    ImageUrl,
    ModelRequest,
    ModelResponse,
    RetryPromptPart,
    SystemPromptPart,
    TextPart,
    ThinkingPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.tools import ToolDefinition
from pydantic_ai.usage import RequestUsage

from pydantic_ai_sandbox.llm._openai_mapping import (
    _FINISH_REASON_MAP,  # pyright: ignore[reportPrivateUsage]
    _map_assistant_message,  # pyright: ignore[reportPrivateUsage]
    _map_messages,  # pyright: ignore[reportPrivateUsage]
    _map_request_part,  # pyright: ignore[reportPrivateUsage]
    _map_tools,  # pyright: ignore[reportPrivateUsage]
    _map_usage,  # pyright: ignore[reportPrivateUsage]
    _map_user_prompt,  # pyright: ignore[reportPrivateUsage]
    build_response,
)

if TYPE_CHECKING:
    from pydantic_ai.messages import FinishReason, ModelMessage

# Arbitrary, deliberately non-watsonx identities: build_response must stamp
# whatever the caller passes (Req 11 generalisation), so using a different
# provider here proves the value is not re-hardcoded to "watsonx".
_MODEL_NAME = "litellm-route/some-model"
_PROVIDER_NAME = "some-provider"


# --------------------------------------------------------------------------- #
# Message-part mapping                                                         #
# --------------------------------------------------------------------------- #
def test_map_user_prompt_str_content() -> None:
    assert _map_user_prompt(UserPromptPart("hello")) == {
        "role": "user",
        "content": "hello",
    }


def test_map_user_prompt_concatenates_list_of_text() -> None:
    part = UserPromptPart(content=["foo", "bar"])
    assert _map_user_prompt(part) == {"role": "user", "content": "foobar"}


def test_map_user_prompt_multimodal_raises_naming_type() -> None:
    part = UserPromptPart(content=[ImageUrl(url="https://example.com/a.png")])
    with pytest.raises(NotImplementedError, match="ImageUrl"):
        _map_user_prompt(part)


def test_map_request_part_system_prompt() -> None:
    assert _map_request_part(SystemPromptPart(content="be helpful")) == {
        "role": "system",
        "content": "be helpful",
    }


def test_map_request_part_tool_return() -> None:
    part = ToolReturnPart(tool_name="search_kb", content="sunny", tool_call_id="c1")
    assert _map_request_part(part) == {
        "role": "tool",
        "tool_call_id": "c1",
        "content": "sunny",
    }


def test_map_request_part_retry_without_tool_to_user() -> None:
    mapped = _map_request_part(RetryPromptPart(content="try again"))
    assert mapped["role"] == "user"
    assert isinstance(mapped["content"], str)


def test_map_request_part_retry_with_tool_to_tool() -> None:
    part = RetryPromptPart(content="bad args", tool_name="search_kb", tool_call_id="c1")
    mapped = _map_request_part(part)
    assert mapped["role"] == "tool"
    assert mapped["tool_call_id"] == "c1"


def test_map_assistant_message_text_and_tool_calls() -> None:
    response = ModelResponse(
        parts=[
            TextPart("let me check"),
            ToolCallPart(
                tool_name="search_kb",
                args='{"query": "weather"}',
                tool_call_id="c1",
            ),
        ],
    )
    assert _map_assistant_message(response) == {
        "role": "assistant",
        "content": "let me check",
        "tool_calls": [
            {
                "id": "c1",
                "type": "function",
                "function": {"name": "search_kb", "arguments": '{"query": "weather"}'},
            },
        ],
    }


def test_map_assistant_message_omits_thinking_parts() -> None:
    response = ModelResponse(parts=[ThinkingPart(content="reasoning"), TextPart("done")])
    mapped = _map_assistant_message(response)
    assert mapped == {"role": "assistant", "content": "done"}


# --------------------------------------------------------------------------- #
# Full history mapping                                                         #
# --------------------------------------------------------------------------- #
def test_map_messages_full_history_roles_and_order() -> None:
    messages: list[ModelMessage] = [
        ModelRequest(parts=[UserPromptPart("天気は?")], instructions="be helpful"),
        ModelResponse(
            parts=[ToolCallPart(tool_name="search_kb", args="{}", tool_call_id="c1")],
        ),
        ModelRequest(
            parts=[ToolReturnPart(tool_name="search_kb", content="sunny", tool_call_id="c1")],
        ),
    ]
    assert _map_messages(messages) == [
        {"role": "system", "content": "be helpful"},
        {"role": "user", "content": "天気は?"},
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "c1",
                    "type": "function",
                    "function": {"name": "search_kb", "arguments": "{}"},
                },
            ],
        },
        {"role": "tool", "tool_call_id": "c1", "content": "sunny"},
    ]


def test_map_messages_instructions_inserted_after_explicit_system() -> None:
    messages: list[ModelMessage] = [
        ModelRequest(
            parts=[SystemPromptPart(content="explicit"), UserPromptPart("hi")],
            instructions="rendered",
        ),
    ]
    assert _map_messages(messages) == [
        {"role": "system", "content": "explicit"},
        {"role": "system", "content": "rendered"},
        {"role": "user", "content": "hi"},
    ]


# --------------------------------------------------------------------------- #
# Tool mapping                                                                 #
# --------------------------------------------------------------------------- #
def test_map_tools_returns_none_when_no_tools() -> None:
    assert _map_tools(ModelRequestParameters()) is None


def test_map_tools_maps_function_and_output_tools() -> None:
    params = ModelRequestParameters(
        function_tools=[
            ToolDefinition(
                name="search_kb",
                parameters_json_schema={
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                },
                description="kb lookup",
            ),
        ],
        output_tools=[
            ToolDefinition(
                name="final_result",
                parameters_json_schema={"type": "object", "properties": {}},
            ),
        ],
    )
    assert _map_tools(params) == [
        {
            "type": "function",
            "function": {
                "name": "search_kb",
                "description": "kb lookup",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "final_result",
                # An absent description maps to "" rather than None.
                "description": "",
                "parameters": {"type": "object", "properties": {}},
            },
        },
    ]


# --------------------------------------------------------------------------- #
# Usage mapping                                                                #
# --------------------------------------------------------------------------- #
def test_map_usage_present() -> None:
    usage = _map_usage({"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18})
    assert usage.input_tokens == 11
    assert usage.output_tokens == 7


@pytest.mark.parametrize("raw_usage", [None, {}])
def test_map_usage_absent_yields_zeroed(raw_usage: dict[str, Any] | None) -> None:
    usage = _map_usage(raw_usage)
    assert usage == RequestUsage()
    assert usage.input_tokens == 0
    assert usage.output_tokens == 0


# --------------------------------------------------------------------------- #
# Finish-reason map                                                           #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("stop", "stop"),
        ("length", "length"),
        ("tool_calls", "tool_call"),
        ("content_filter", "content_filter"),
        ("function_call", "tool_call"),
    ],
)
def test_finish_reason_map_covers_every_key(key: str, expected: FinishReason) -> None:
    assert _FINISH_REASON_MAP[key] == expected


# --------------------------------------------------------------------------- #
# Response building                                                            #
# --------------------------------------------------------------------------- #
def _completion(message: dict[str, Any], **extra: Any) -> dict[str, Any]:
    """Build a minimal OpenAI-shaped completion dict around ``message``."""
    choice: dict[str, Any] = {"index": 0, "message": message}
    choice.update(extra)
    return {"id": "cmpl-1", "choices": [choice]}


def test_build_response_stamps_caller_identity_and_text() -> None:
    raw = _completion(
        {"role": "assistant", "content": "hi there"},
        finish_reason="stop",
    )
    raw["usage"] = {"prompt_tokens": 3, "completion_tokens": 5}
    result = build_response(raw, model_name=_MODEL_NAME, provider_name=_PROVIDER_NAME)

    assert [type(p).__name__ for p in result.parts] == ["TextPart"]
    text = result.parts[0]
    assert isinstance(text, TextPart)
    assert text.content == "hi there"
    assert result.finish_reason == "stop"
    assert result.usage.input_tokens == 3
    assert result.usage.output_tokens == 5
    assert result.provider_response_id == "cmpl-1"
    # Generalisation proof: the caller's identity is stamped verbatim.
    assert result.model_name == _MODEL_NAME
    assert result.provider_name == _PROVIDER_NAME


def test_build_response_preserves_double_encoded_tool_args() -> None:
    # A Granite-style double-encoded arg string: a JSON string whose *value* is
    # itself JSON. build_response must surface it raw, never re-encoding it.
    inner = json.dumps({"city": "Tokyo"})  # '{"city": "Tokyo"}'
    double_encoded = json.dumps(inner)  # '"{\\"city\\": \\"Tokyo\\"}"'
    raw = _completion(
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "get_weather", "arguments": double_encoded},
                },
            ],
        },
        finish_reason="tool_calls",
    )
    result = build_response(raw, model_name=_MODEL_NAME, provider_name=_PROVIDER_NAME)

    assert len(result.parts) == 1
    call = result.parts[0]
    assert isinstance(call, ToolCallPart)
    assert call.tool_name == "get_weather"
    assert call.tool_call_id == "call_1"
    # Surfaced faithfully: the exact raw string, neither parsed nor re-encoded.
    assert call.args == double_encoded
    assert isinstance(call.args, str)
    assert result.finish_reason == "tool_call"


def test_build_response_empty_choices_raises() -> None:
    with pytest.raises(UnexpectedModelBehavior, match="no choices"):
        build_response(
            {"id": "x", "choices": []},
            model_name=_MODEL_NAME,
            provider_name=_PROVIDER_NAME,
        )


def test_build_response_missing_choices_key_raises() -> None:
    with pytest.raises(UnexpectedModelBehavior, match="no choices"):
        build_response({"id": "x"}, model_name=_MODEL_NAME, provider_name=_PROVIDER_NAME)


def test_build_response_absent_usage_yields_zeroed() -> None:
    raw = _completion({"role": "assistant", "content": "hi"}, finish_reason="stop")
    result = build_response(raw, model_name=_MODEL_NAME, provider_name=_PROVIDER_NAME)
    assert result.usage == RequestUsage()


def test_build_response_unmapped_finish_reason_is_none() -> None:
    raw = _completion({"role": "assistant", "content": "hi"}, finish_reason="surprise")
    result = build_response(raw, model_name=_MODEL_NAME, provider_name=_PROVIDER_NAME)
    assert result.finish_reason is None


def test_build_response_absent_finish_reason_is_none() -> None:
    raw = _completion({"role": "assistant", "content": "hi"})
    result = build_response(raw, model_name=_MODEL_NAME, provider_name=_PROVIDER_NAME)
    assert result.finish_reason is None


def test_build_response_empty_message_yields_no_parts() -> None:
    raw = _completion({"role": "assistant"}, finish_reason="stop")
    result = build_response(raw, model_name=_MODEL_NAME, provider_name=_PROVIDER_NAME)
    assert result.parts == []
