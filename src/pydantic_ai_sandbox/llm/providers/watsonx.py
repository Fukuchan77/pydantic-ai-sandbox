"""IBM watsonx.ai provider builder and SDK-backed Model (Req 1.3 / plan.md Phase 1).

This module owns watsonx *Model construction*: the transport dispatch in
:func:`_build_watsonx` and the :class:`WatsonxSDKModel` that adapts the
``ibm-watsonx-ai`` SDK to the Pydantic AI ``Model`` ABC (message mapping,
``ModelAPIError`` wrapping, lazy client, ``system`` / ``model_name``).

Boundary contract — what this module does **NOT** own:

* **Environment parsing / validation.** Credentials, the ``WATSONX_TRANSPORT``
  selector, URL-format and timeout validation all live in
  :class:`pydantic_ai_sandbox.config.Settings`. By the time a builder here
  receives ``settings`` the values are already validated, and the credential
  gate (config Task 2.2) has guaranteed the four watsonx fields are present
  whenever watsonx is the selected provider. This module reads settings; it
  never re-validates them.
* **Fallback composition.** Whether watsonx participates in a
  :class:`pydantic_ai.models.fallback.FallbackModel` chain, and the
  silent-drop of stub providers, belong to
  :mod:`pydantic_ai_sandbox.llm.fallback`. This module's only obligation to
  the chain is that request failures surface as
  :class:`pydantic_ai.exceptions.ModelAPIError` so ``fallback_on`` can recover
  them (Task 5).
* **Installing the optional ``litellm`` package.** The litellm transport
  branch import-guards the dependency (Task 6); provisioning it is a
  deployment concern, not this module's.

Construction is I/O-free (Req 1.5): the SDK client is built lazily on the
first request (Task 5) so a stopped or unreachable watsonx endpoint cannot
break process start. The model-ID literal is never spelled here — it reaches
us through :class:`Settings` (``WATSONX_MODEL_ID``); a hardcoded value would
be caught by ``tests/unit/test_no_hardcoded_model_ids.py`` and the pre-commit
``forbid-hardcoded-model-ids`` hook.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, cast

import httpx
from pydantic_ai.exceptions import ModelAPIError, UnexpectedModelBehavior
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
from pydantic_ai.models import Model
from pydantic_ai.usage import RequestUsage

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from ibm_watsonx_ai.foundation_models import ModelInference
    from pydantic_ai import RunContext
    from pydantic_ai.messages import (
        FinishReason,
        ModelMessage,
        ModelRequestPart,
        ModelResponsePart,
    )
    from pydantic_ai.models import ModelRequestParameters, StreamedResponse
    from pydantic_ai.settings import ModelSettings

    from pydantic_ai_sandbox.config import Settings

# Spec-mandated underscore-prefixed name (plan.md §2.3); exported via
# ``__all__`` so pyright treats it as the module's public surface and does
# not flag the cross-module import in ``llm.factory`` as unused.
__all__ = ["_build_watsonx"]

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

    Only text content is in scope for the SDK transport. Multimodal items
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
                "watsonx SDK transport supports text user content only; "
                f"multimodal item {type(item).__name__!r} is out of scope."
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


class WatsonxSDKModel(Model):
    """Pydantic AI ``Model`` adapting the ``ibm-watsonx-ai`` SDK.

    Task 4 lands the **activation skeleton**: an I/O-free constructor plus the
    ``system`` / ``model_name`` properties that let Pydantic AI instrumentation
    derive the ``gen_ai.system`` and ``gen_ai.request.model`` span attributes
    (Req 8.3/8.6). The request body, the lazily-built SDK client, timeout
    wiring and the ``ModelAPIError`` mapping land in Task 5 (SDK transport);
    until then :meth:`request` fails loud rather than returning a placeholder.
    """

    def __init__(self, settings: Settings) -> None:
        """Store validated settings; perform no network I/O (Req 1.5).

        The application :class:`Settings` is held under ``_app_settings``
        rather than the base class's ``_settings`` slot, which Pydantic AI
        reserves for per-request ``ModelSettings`` defaults — overwriting it
        would corrupt model-settings merging.

        Args:
            settings: Frozen runtime settings. The watsonx credential gate
                (config Task 2.2) guarantees ``watsonx_apikey`` /
                ``watsonx_project_id`` / ``watsonx_url`` / ``watsonx_model_id``
                are present whenever watsonx is the selected provider.
        """
        super().__init__()
        self._app_settings = settings
        # Lazily built on the first request (Task 5.2 / Req 1.5); ``None`` until
        # then so ``__init__`` performs no network I/O.
        self._client: ModelInference | None = None

    @property
    def system(self) -> str:
        """Return ``"watsonx"`` → ``gen_ai.system`` (Req 8.3/8.6)."""
        return "watsonx"

    @property
    def model_name(self) -> str:
        """Return the configured model id → ``gen_ai.request.model`` (Req 8.6).

        Raises:
            TypeError: If ``watsonx_model_id`` is ``None`` — unreachable when
                watsonx is selected because the credential gate rejects that
                configuration at boot; the guard is defensive against a future
                validator change (mirrors the Ollama builder's invariant
                check).
        """
        model_id = self._app_settings.watsonx_model_id
        if model_id is None:
            msg = (
                "watsonx_model_id is None at WatsonxSDKModel.model_name time — "
                "the credential gate (config) should have rejected this "
                "configuration; did the cross-field validator change?"
            )
            raise TypeError(msg)
        return model_id

    def _build_client(self) -> ModelInference:
        """Build (once) and cache the ``ibm-watsonx-ai`` inference client.

        Invoked lazily on the first request (Task 5.3), never in ``__init__``:
        the SDK's ``APIClient`` authenticates over the network at construction,
        so deferring it keeps ``WatsonxSDKModel`` construction I/O-free (Req 1.5)
        and lets a stopped or unreachable watsonx endpoint fail at request time
        rather than at process start. The built client is memoised on
        ``self._client`` so subsequent requests reuse the same authenticated
        session.

        Wiring (research.md R3):

        * Timeouts (Req 5.4) inject via the async httpx client handed to
          ``APIClient`` — ``Credentials`` carries no timeout argument.
          ``httpx.Timeout`` rejects a partial ``(connect, read)`` spec, so the
          read value seeds the overall default (covering write/pool) and
          ``connect`` overrides the connect phase.
        * ``max_retries=0`` (Req 6.1 / ADR-2) disables the SDK's default retry
          loop; the fallback chain is the sole resilience layer.
        * ``validate=False`` (plan.md §Entity 2) suppresses the SDK's extra
          network validation round-trip, removing a second failure surface on
          the first call.

        Returns:
            The memoised :class:`~ibm_watsonx_ai.foundation_models.ModelInference`
            client, built against the validated watsonx settings.

        Raises:
            TypeError: If ``watsonx_apikey`` is ``None`` — unreachable when
                watsonx is selected because the credential gate (config Task 2.2)
                rejects it at boot; the guard keeps the ``SecretStr`` unwrap
                total and fails loud against a future validator change.
        """
        if self._client is not None:
            return self._client

        settings = self._app_settings
        apikey = settings.watsonx_apikey
        if apikey is None:
            msg = (
                "watsonx_apikey is None at WatsonxSDKModel._build_client time — "
                "the credential gate (config) should have rejected this "
                "configuration; did the cross-field validator change?"
            )
            raise TypeError(msg)

        # Import the SDK lazily so importing this module (and the factory that
        # pulls it in unconditionally) stays cheap for non-watsonx deployments;
        # the heavy SDK only loads when a watsonx request is actually served.
        from ibm_watsonx_ai import APIClient, Credentials
        from ibm_watsonx_ai.foundation_models import ModelInference

        # Unwrap the SecretStr only here, at the SDK boundary (tech.md secrets
        # convention); the value is never logged.
        credentials = Credentials(
            url=settings.watsonx_url,
            api_key=apikey.get_secret_value(),
        )
        async_http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                settings.watsonx_timeout_read,
                connect=settings.watsonx_timeout_connect,
            ),
        )
        api_client = APIClient(
            credentials=credentials,
            project_id=settings.watsonx_project_id,
            async_httpx_client=async_http_client,
        )
        client = ModelInference(
            model_id=settings.watsonx_model_id,
            api_client=api_client,
            max_retries=0,
            validate=False,
        )
        self._client = client
        return client

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        """Execute one non-streaming inference via ``ibm-watsonx-ai`` (Req 2.7).

        Maps the pydantic_ai message history and tool definitions to the
        OpenAI-shaped payload :meth:`ModelInference.achat` expects, awaits the
        async call on the lazily-built SDK client (Task 5.2), and rebuilds a
        :class:`ModelResponse` from the returned dict.

        Per-request :class:`ModelSettings` (temperature, max-tokens, …) are not
        forwarded: mapping them to the SDK's chat parameters is out of scope for
        this transport, and pydantic_ai's convention is to silently ignore
        unsupported settings rather than fail (``models/CLAUDE.md`` rule 912).

        Args:
            messages: The full conversation history to send.
            model_settings: Per-request settings; intentionally unused here.
            model_request_parameters: Carries the tool definitions advertised to
                the model (function tools + output tools).

        Returns:
            The mapped :class:`ModelResponse` (text parts, tool-call parts,
            usage, finish reason and provider response id).

        Every SDK failure — the SDK base ``WMLClientError`` (covering its
        subclasses: ``ApiRequestFailure``, ``AuthenticationError``,
        ``ExceededLimitOfAPICalls`` [rate limit], ``ReadingDataTimeoutError``, …)
        and the underlying httpx errors (``TimeoutException`` / ``ConnectError``
        and any other ``httpx.HTTPError``) — is wrapped into
        :class:`pydantic_ai.exceptions.ModelAPIError` with **no retries**
        (Req 4.4/5.6/6.2/6.3/6.4/8.2). ``FallbackModel``'s default ``fallback_on``
        is ``(ModelAPIError,)``, so an *unwrapped* SDK / httpx error would break
        failover (plan.md Entity 2). Both the lazy first-call client build (whose
        ``APIClient`` authenticates over the network — Req 4.4) and the ``achat``
        call sit inside the guarded block; the original error is chained via
        ``raise ... from`` so ``error.class`` carries the wrapper while the cause
        preserves the underlying failure for debugging.

        Args:
            messages: The full conversation history to send.
            model_settings: Per-request settings; intentionally unused here.
            model_request_parameters: Carries the tool definitions advertised to
                the model (function tools + output tools).

        Returns:
            The mapped :class:`ModelResponse` (text parts, tool-call parts,
            usage, finish reason and provider response id).

        Raises:
            ModelAPIError: For every SDK / httpx transport failure, so the
                fallback chain can recover it. Mapping errors (unsupported parts,
                malformed responses) are *not* wrapped — they surface as
                ``NotImplementedError`` / :class:`UnexpectedModelBehavior` and are
                not swallowed.
        """
        del model_settings  # not mapped to chat params (see docstring)
        openai_messages = _map_messages(messages)
        tools = _map_tools(model_request_parameters)
        # Import the SDK error base lazily (same rationale as ``_build_client``):
        # keep importing this module cheap for non-watsonx deployments — the SDK
        # only loads when a watsonx request is actually served.
        from ibm_watsonx_ai.wml_client_error import WMLClientError

        try:
            client = self._build_client()
            # ``ModelInference.achat`` is typed by the SDK as returning a bare
            # ``dict`` (no key/value generics), so pyright sees its member type
            # as partially unknown; cast the result to the concrete shape
            # ``_build_response`` consumes and silence the single member warning
            # rather than letting the unknown propagate into the mapper.
            raw = cast(
                "dict[str, Any]",
                await client.achat(messages=openai_messages, tools=tools),  # pyright: ignore[reportUnknownMemberType]
            )
        except (WMLClientError, httpx.HTTPError) as exc:
            # ``httpx.HTTPError`` is the base of ``TimeoutException`` /
            # ``ConnectError`` / ``HTTPStatusError``, so the two bases together
            # cover every SDK and transport failure the call can raise. Anything
            # else (e.g. a programming bug) propagates unwrapped — fail loud.
            msg = f"watsonx request failed ({type(exc).__name__}): {exc}"
            raise ModelAPIError(model_name=self.model_name, message=msg) from exc
        return self._build_response(raw)

    def _build_response(self, raw: dict[str, Any]) -> ModelResponse:
        """Build a :class:`ModelResponse` from an OpenAI-shaped ``achat`` dict.

        Maps ``choices[0].message`` exhaustively — assistant ``content`` →
        :class:`TextPart`, each ``tool_calls`` entry → :class:`ToolCallPart`
        (name, raw JSON arguments, id) — plus ``usage``, ``finish_reason`` and
        the response ``id`` (Req 9.11). An empty ``content`` with no tool calls
        yields an empty ``parts`` list (a valid, if degenerate, response;
        ``models/CLAUDE.md`` rule 433), but a response carrying no ``choices`` at
        all is malformed and raises.

        Args:
            raw: The dict returned by :meth:`ModelInference.achat`.

        Returns:
            The mapped :class:`ModelResponse` with the standard identity fields
            (``model_name`` / ``provider_name``) stamped for instrumentation.

        Raises:
            UnexpectedModelBehavior: If the response has no ``choices``.
        """
        choices: list[Any] = raw.get("choices") or []
        if not choices:
            msg = "watsonx achat response contained no choices."
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
            model_name=self.model_name,
            provider_name="watsonx",
            provider_response_id=raw.get("id"),
            finish_reason=(
                _FINISH_REASON_MAP.get(finish_reason_key) if finish_reason_key else None
            ),
        )

    @asynccontextmanager
    async def request_stream(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
        run_context: RunContext[Any] | None = None,
    ) -> AsyncGenerator[StreamedResponse]:
        """Reject streaming — out of scope for the watsonx SDK transport (Req 2.1).

        The ``Model`` ABC's default ``request_stream`` already raises a *generic*
        ``NotImplementedError``; this override makes the refusal deliberate and
        watsonx-specific. Streaming is explicitly out of scope (spec.md "Out of
        Scope"): the ``/chat`` endpoint issues a single non-streaming
        :meth:`request`. Failing loud here means a future caller wiring streaming
        gets an explicit, greppable signal rather than a silent or misleading
        default. The signature mirrors the base exactly so the override stays
        Liskov-compatible; the unreachable ``yield`` keeps it an async generator
        for the ``@asynccontextmanager`` contract.

        Raises:
            NotImplementedError: Always — streaming is unsupported.
        """
        del messages, model_settings, model_request_parameters, run_context
        msg = (
            "watsonx SDK transport does not support streaming responses "
            "(out of scope); the /chat endpoint issues a single non-streaming "
            "request via WatsonxSDKModel.request."
        )
        raise NotImplementedError(msg)
        yield  # pragma: no cover — unreachable; required to type as a generator


def _build_litellm(settings: Settings) -> Model:
    """Build the LiteLLM-routed watsonx ``Model`` (Task 6). I/O-free.

    The litellm transport reuses pydantic_ai's OpenAI adapter: a
    :class:`~pydantic_ai.providers.litellm.LiteLLMProvider` carries the
    credentials and the timeout-wired HTTP client, wrapped in an
    :class:`~pydantic_ai.models.openai.OpenAIChatModel` whose ``model_name``
    carries the ``watsonx/`` route prefix LiteLLM uses to select the backend
    (Req 2.3). ``OpenAIChatModel`` accepts a ``Provider``; its adapter
    auto-stamps ``gen_ai.system`` / ``gen_ai.request.model`` for instrumentation.

    Credential routing (research.md R4 / ADR-3): ``LiteLLMProvider`` exposes
    ``api_key`` / ``api_base`` but **no** ``project_id`` — so ``apikey`` and
    ``url`` are routed explicitly while ``project_id`` reaches litellm via the
    ``WATSONX_PROJECT_ID`` env var the deployment already sets, never a
    constructor arg. Timeouts (Req 5.4) inject via the custom ``http_client``
    (``LiteLLMProvider`` takes no timeout argument); ``httpx.Timeout`` rejects a
    partial ``(connect, read)`` spec, so the read value seeds the overall default
    and ``connect`` overrides the connect phase — the same shaping as the SDK
    client (:meth:`WatsonxSDKModel._build_client`).

    The optional ``litellm`` package, the OpenAI adapter and the provider are all
    imported function-locally (not at module scope): :mod:`llm.factory` imports
    this module unconditionally, so a top-level import would force these heavy
    dependencies on every deployment — including SDK-only and ollama-only ones
    that never select the litellm transport.

    Args:
        settings: Frozen runtime settings; the credential gate has already
            validated the watsonx fields when watsonx is selected.

    Returns:
        An :class:`OpenAIChatModel` routed through LiteLLM to watsonx.

    Raises:
        ValueError: If the optional ``litellm`` package is not installed (Req
            2.6) — naming the package so the operator knows what to install.
        TypeError: If ``watsonx_apikey`` / ``watsonx_model_id`` are ``None`` —
            unreachable when watsonx is selected (the credential gate rejects
            that at boot); defensive against a future validator change, matching
            the SDK builder's fail-loud invariants.
    """
    # Import guard (Req 2.6): the litellm transport is an optional extra. A
    # missing package must fail loud as a ``ValueError`` naming ``litellm`` — not
    # a bare ``ImportError`` leaking from deep in the builder — so the operator
    # knows exactly what to install.
    try:
        import litellm  # noqa: F401  # pyright: ignore[reportUnusedImport]
    except ImportError as exc:
        msg = (
            "WATSONX_TRANSPORT=litellm requires the optional 'litellm' package, "
            "which is not installed. Install it ('uv sync --extra litellm') or "
            "use the default SDK transport (WATSONX_TRANSPORT=sdk)."
        )
        raise ValueError(msg) from exc

    # OpenAI adapter + LiteLLM provider imported here (not at module scope) for
    # the same reason as the SDK import in ``_build_client``.
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.litellm import LiteLLMProvider

    apikey = settings.watsonx_apikey
    model_id = settings.watsonx_model_id
    if apikey is None or model_id is None:
        msg = (
            "watsonx_apikey/watsonx_model_id is None at _build_litellm time — "
            "the credential gate (config) should have rejected this "
            "configuration; did the cross-field validator change?"
        )
        raise TypeError(msg)

    http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(
            settings.watsonx_timeout_read,
            connect=settings.watsonx_timeout_connect,
        ),
    )
    provider = LiteLLMProvider(
        # Unwrap the SecretStr only here, at the SDK boundary (tech.md secrets
        # convention); the value is never logged.
        api_key=apikey.get_secret_value(),
        api_base=settings.watsonx_url,
        http_client=http_client,
    )
    return OpenAIChatModel(
        model_name=f"watsonx/{model_id}",
        provider=provider,
    )


def _build_watsonx(settings: Settings) -> Model:
    """Build a watsonx-backed ``Model`` per ``WATSONX_TRANSPORT``. I/O-free.

    Follows the established ``_build_ollama(settings) -> Model`` shape
    (``structure.md``) and is the factory's entry point for
    ``LLM_PROVIDER=watsonx`` (:func:`llm.factory.get_model`). Dispatches on the
    already-validated ``watsonx_transport`` selector (config Task 2.3 normalises
    it to one of ``"sdk"`` / ``"litellm"``, defaulting to ``"sdk"``):

    * ``"sdk"`` → :class:`WatsonxSDKModel`, the ``ibm-watsonx-ai`` transport
      (Task 5). Construction is I/O-free — the SDK client is built lazily on the
      first request (Req 1.5).
    * ``"litellm"`` → :func:`_build_litellm`, the LiteLLM-routed transport
      (Task 6) with its optional-dependency import-guard. Also I/O-free — the
      OpenAI-compatible client is built but not invoked until a request is
      served.

    Args:
        settings: Frozen runtime settings; the credential gate has already
            validated the watsonx fields when watsonx is selected.

    Returns:
        A ``pydantic_ai.models.Model`` ready to be passed to
        :class:`pydantic_ai.Agent`.

    Raises:
        ValueError: For ``watsonx_transport == "litellm"`` when the optional
            ``litellm`` package is not installed (Req 2.6).
    """
    if settings.watsonx_transport == "sdk":
        return WatsonxSDKModel(settings)
    # ``watsonx_transport`` is a validated ``Literal["sdk", "litellm"]`` (config
    # Task 2.3), so the only remaining value is ``"litellm"``.
    return _build_litellm(settings)
