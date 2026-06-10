"""Shared OpenAI-shaped message / tool / response mapping (Req 11 / plan.md C1).

The single implementation of the bidirectional OpenAI-shape mapping that both
the watsonx ``sdk`` transport (:class:`~pydantic_ai_sandbox.llm.providers.watsonx.WatsonxSDKModel`)
and the LiteLLM transport (:class:`~pydantic_ai_sandbox.llm.providers.litellm.LiteLLMModel`)
consume. The helpers were extracted verbatim from ``watsonx.py`` (feature
``002-watsonx-provider``) so the two transports cannot drift (ADR-1); the watsonx
SDK transport's *observable* behaviour is unchanged (Req 11.4) — the only edits
are transport-neutral fail-loud wording (the messages are shared across both
routes, so they name no single transport; tests assert on substrings).

Boundary contract — what this module does **NOT** own:

* **Transport / SDK calls.** No ``acompletion`` / ``achat`` invocation, no HTTP
  client, no timeout wiring. Each transport owns its own call site and hands the
  OpenAI-shaped ``dict`` it received to :func:`build_response`.
* **Error wrapping.** ``ModelAPIError`` classification is the transport's job;
  this module only raises the *mapping* errors that must fail loud
  (``NotImplementedError`` for unsupported parts, ``UnexpectedModelBehavior`` for
  a choiceless response — Req 4.3).
* **Credential / settings handling.** Purely data transformation; performs no
  I/O and reads no environment or :class:`Settings`.

:func:`build_response` is the one generalised entry point: the watsonx-specific
identity fields (``model_name`` / ``provider_name``) that the source method
hard-coded are lifted to keyword parameters so each transport stamps its own.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    SystemPromptPart,
    TextPart,
    ThinkingPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.usage import RequestUsage

if TYPE_CHECKING:
    from pydantic_ai.messages import (
        FinishReason,
        ModelMessage,
        ModelRequestPart,
        ModelResponsePart,
    )
    from pydantic_ai.models import ModelRequestParameters

# The mapping helpers are spec-mandated underscore-prefixed names (plan.md §C1):
# package-internal utilities consumed by the transport ``Model`` subclasses.
# Exported via ``__all__`` so pyright treats them as the module's public surface
# and importing modules acknowledge the cross-module hop with a scoped
# ``# pyright: ignore[reportPrivateUsage]`` (tech.md typing convention).
__all__ = [
    "_FINISH_REASON_MAP",
    "_map_assistant_message",
    "_map_messages",
    "_map_request_part",
    "_map_tools",
    "_map_usage",
    "_map_user_prompt",
    "build_response",
]

# OpenAI-style ``finish_reason`` keys (as returned in ``achat``'s response dict)
# → pydantic_ai's normalised ``FinishReason`` literal. An absent or unmapped key
# yields ``None``, matching pydantic_ai's own OpenAI Chat adapter rather than
# inventing a watsonx-specific value.
_FINISH_REASON_MAP: dict[str, FinishReason] = {
    "stop": "stop",
    "length": "length",
    "tool_calls": "tool_call",
    "content_filter": "content_filter",
    "function_call": "tool_call",
}


def _map_user_prompt(part: UserPromptPart) -> dict[str, Any]:
    """Map a :class:`UserPromptPart` to an OpenAI ``user`` message.

    Only text content is in scope for either transport. Multimodal items
    (images, audio, documents) raise :class:`NotImplementedError` naming the
    offending type rather than being dropped from the payload — vision is
    explicitly out of scope (spec.md "Out of Scope") and a silent drop would
    send the model a prompt missing context (Req 2.7, no silent drops).
    """
    content = part.content
    if isinstance(content, str):
        return {"role": "user", "content": content}

    segments: list[str] = []
    for item in content:
        if isinstance(item, str):
            segments.append(item)
        else:
            msg = (
                "text user content only; "
                f"multimodal item {type(item).__name__!r} is out of scope "
                "(vision unsupported)."
            )
            raise NotImplementedError(msg)
    return {"role": "user", "content": "".join(segments)}


def _map_assistant_message(response: ModelResponse) -> dict[str, Any]:
    """Map a prior :class:`ModelResponse` to an OpenAI ``assistant`` message.

    Replays the model's own earlier turn — text plus tool-call parts — back into
    the request history so multi-step tool loops keep their context. Thinking
    parts are reasoning artefacts, not API-required content, so they are
    intentionally not resent; any other part type is unsupported and raises
    rather than being silently dropped (Req 2.7).
    """
    segments: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    for part in response.parts:
        if isinstance(part, TextPart):
            segments.append(part.content)
        elif isinstance(part, ToolCallPart):
            tool_calls.append(
                {
                    "id": part.tool_call_id,
                    "type": "function",
                    "function": {
                        "name": part.tool_name,
                        "arguments": part.args_as_json_str(),
                    },
                },
            )
        elif isinstance(part, ThinkingPart):
            # Reasoning trace — not part of the OpenAI assistant message contract;
            # deliberately omitted (documented, not a silent drop).
            continue
        else:
            msg = f"Unsupported assistant message part: {type(part).__name__!r}."
            raise NotImplementedError(msg)

    message: dict[str, Any] = {"role": "assistant"}
    if segments:
        message["content"] = "".join(segments)
    if tool_calls:
        message["tool_calls"] = tool_calls
    return message


def _map_request_part(part: ModelRequestPart) -> dict[str, Any]:
    """Map a single :class:`ModelRequest` part to an OpenAI message dict.

    Exhaustively covers the four request-side parts of the ``ModelRequestPart``
    union — system prompts, user prompts, tool returns and retry prompts — so no
    part is silently dropped (Req 2.7); a future addition to the union would
    surface as a pyright error here rather than a runtime drop.
    """
    if isinstance(part, SystemPromptPart):
        return {"role": "system", "content": part.content}
    if isinstance(part, UserPromptPart):
        return _map_user_prompt(part)
    if isinstance(part, ToolReturnPart):
        return {
            "role": "tool",
            "tool_call_id": part.tool_call_id,
            "content": part.model_response_str(),
        }
    # ``RetryPromptPart`` is the only remaining member of the ``ModelRequestPart``
    # union; pyright proves exhaustiveness, so handling it here (rather than via a
    # redundant ``isinstance``) keeps the type-checker happy while still covering
    # every emitted part. A retry without a tool name is feedback on free-text /
    # native output (→ ``user``); with one it targets a specific tool call (→
    # ``tool``).
    if part.tool_name is None:
        return {"role": "user", "content": part.model_response()}
    return {
        "role": "tool",
        "tool_call_id": part.tool_call_id,
        "content": part.model_response(),
    }


def _map_messages(messages: list[ModelMessage]) -> list[dict[str, Any]]:
    """Map the pydantic_ai message history to OpenAI-shaped ``achat`` messages.

    Handles every request/response part the agent can emit — system prompts,
    rendered ``instructions``, user prompts, tool returns, retry prompts and
    prior assistant turns — raising on anything unmapped so a part is never
    silently dropped (Req 2.7). The rendered ``instructions`` string (the
    agent's system prompt, which arrives on :class:`ModelRequest` rather than as
    a :class:`SystemPromptPart`) is inserted as a leading ``system`` message,
    after any explicit system prompts, mirroring pydantic_ai's OpenAI adapter.
    """
    openai_messages: list[dict[str, Any]] = []
    instructions: str | None = None
    for message in messages:
        if isinstance(message, ModelRequest):
            if message.instructions is not None:
                instructions = message.instructions
            openai_messages.extend(_map_request_part(part) for part in message.parts)
        else:
            # Only ``ModelResponse`` remains in the ``ModelMessage`` union — a
            # prior assistant turn replayed into the request history.
            openai_messages.append(_map_assistant_message(message))

    if instructions is not None:
        insert_at = next(
            (i for i, m in enumerate(openai_messages) if m.get("role") != "system"),
            len(openai_messages),
        )
        openai_messages.insert(insert_at, {"role": "system", "content": instructions})
    return openai_messages


def _map_tools(
    model_request_parameters: ModelRequestParameters,
) -> list[dict[str, Any]] | None:
    """Map function + output tool definitions to OpenAI tool specs, or ``None``.

    The agent registers ordinary tools (e.g. ``search_kb``) and, in tool-mode
    structured output, an output tool; both must be advertised to ``achat`` for
    the model to call them — dropping them would silently disable tool calling
    and structured output (Req 2.7). Returns ``None`` when there are no tools so
    the SDK's optional ``tools`` argument stays unset.
    """
    definitions = [
        *model_request_parameters.function_tools,
        *model_request_parameters.output_tools,
    ]
    if not definitions:
        return None
    return [
        {
            "type": "function",
            "function": {
                "name": definition.name,
                "description": definition.description or "",
                "parameters": definition.parameters_json_schema,
            },
        }
        for definition in definitions
    ]


def _map_usage(raw_usage: dict[str, Any] | None) -> RequestUsage:
    """Map the OpenAI-shaped ``usage`` block to a :class:`RequestUsage`.

    watsonx returns ``prompt_tokens`` / ``completion_tokens``; an absent usage
    block yields a zeroed :class:`RequestUsage` rather than failing (the response
    is still usable — usage is observability metadata, not load-bearing output).
    """
    if not raw_usage:
        return RequestUsage()
    return RequestUsage(
        input_tokens=raw_usage.get("prompt_tokens", 0),
        output_tokens=raw_usage.get("completion_tokens", 0),
    )


def build_response(
    raw: dict[str, Any],
    *,
    model_name: str,
    provider_name: str,
) -> ModelResponse:
    """Build a :class:`ModelResponse` from an OpenAI-shaped completion ``dict``.

    Maps ``choices[0].message`` exhaustively — assistant ``content`` →
    :class:`TextPart`, each ``tool_calls`` entry → :class:`ToolCallPart`
    (name, raw JSON arguments, id) — plus ``usage``, ``finish_reason`` and
    the response ``id`` (Req 9.11). An empty ``content`` with no tool calls
    yields an empty ``parts`` list (a valid, if degenerate, response;
    ``models/CLAUDE.md`` rule 433), but a response carrying no ``choices`` at
    all is malformed and raises.

    Generalised from ``WatsonxSDKModel._build_response`` (Req 11 / plan.md C1):
    the watsonx-specific identity fields it hard-coded (``self.model_name`` /
    ``provider_name="watsonx"``) are lifted to the ``model_name`` /
    ``provider_name`` keyword parameters so both transports stamp their own
    values for instrumentation parity (Req 1.4). The tool-call ``arguments`` are
    surfaced as the raw value the backend sent (never re-encoded), so a
    double-encoded Granite arg string is faithful (Req 2.4).

    Args:
        raw: The OpenAI-shaped completion ``dict`` (watsonx ``achat`` returns one
            directly; the LiteLLM transport supplies ``ModelResponse.model_dump()``).
        model_name: The model identity to stamp → ``gen_ai.request.model``.
        provider_name: The provider identity to stamp → matches ``gen_ai.system``.

    Returns:
        The mapped :class:`ModelResponse` with the standard identity fields
        (``model_name`` / ``provider_name``) stamped for instrumentation.

    Raises:
        UnexpectedModelBehavior: If the response has no ``choices``.
    """
    choices: list[Any] = raw.get("choices") or []
    if not choices:
        msg = "completion response contained no choices."
        raise UnexpectedModelBehavior(msg)
    choice: dict[str, Any] = choices[0]
    message: dict[str, Any] = choice.get("message") or {}

    parts: list[ModelResponsePart] = []
    content: Any = message.get("content")
    if content:
        parts.append(TextPart(content))
    tool_calls: list[Any] = message.get("tool_calls") or []
    for call in tool_calls:
        function: dict[str, Any] = call.get("function") or {}
        parts.append(
            ToolCallPart(
                tool_name=function.get("name", ""),
                args=function.get("arguments"),
                tool_call_id=call.get("id", ""),
            ),
        )

    # ``dict.get`` widens to ``Any | None``; collapse to ``Any`` so the
    # lookup key satisfies the map's ``str`` parameter, and short-circuit a
    # missing/empty reason to ``None`` (pydantic_ai's unmapped-key default).
    finish_reason_key: Any = choice.get("finish_reason")
    return ModelResponse(
        parts=parts,
        usage=_map_usage(raw.get("usage")),
        model_name=model_name,
        provider_name=provider_name,
        provider_response_id=raw.get("id"),
        finish_reason=(_FINISH_REASON_MAP.get(finish_reason_key) if finish_reason_key else None),
    )
