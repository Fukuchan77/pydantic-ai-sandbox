"""Provider-agnostic ``LiteLLMModel`` routing chat via ``litellm.acompletion()`` (plan.md C2).

A :class:`pydantic_ai.models.Model` subclass that executes one non-streaming chat
through ``litellm.acompletion()`` and adapts it to the Pydantic AI **V2 (Beta)**
``Model`` ABC. LiteLLM multiplexes the concrete backend from the route prefix
(e.g. ``watsonx/<model_id>``), so this reads as one more transport adapter
alongside ``anthropic.py`` / ``bedrock.py`` / ``ollama.py`` / ``watsonx.py`` — it
is **not** a new factory dispatch entry (watsonx still dispatches to
``_build_watsonx``, which internally selects the litellm transport).

The OpenAI-shaped message / tool / response mapping is delegated to the shared
``llm._openai_mapping`` module (Req 11 / ADR-1) so this transport and
``WatsonxSDKModel`` consume one implementation and cannot drift.

Boundary contract — what this module does **NOT** own:

* **Mapping logic.** Message/tool/usage/response shaping lives in
  ``_openai_mapping`` (delegated); this module only normalises the
  ``litellm.ModelResponse`` object into the ``dict`` that ``build_response``
  consumes, and calls the transport.
* **Environment parsing / validation.** Credentials, the route, timeouts and the
  ``WATSONX_PROJECT_ID`` reconciliation reach this model already resolved from
  :class:`pydantic_ai_sandbox.config.Settings` by the watsonx builder
  (``_build_litellm``); this model receives plain values and reads no environment.
* **Fallback composition.** Whether this model participates in a
  :class:`pydantic_ai.models.fallback.FallbackModel` chain belongs to
  ``llm.fallback``; this model's obligation is only that request failures surface
  as :class:`pydantic_ai.exceptions.ModelAPIError` so ``fallback_on`` can recover
  them (Task 2.3).

Construction is I/O-free (Req 1.3): the first network call is the first
:meth:`request`.

---------------------------------------------------------------------------
Attribution
---------------------------------------------------------------------------
The design of this adapter (a ``pydantic_ai.models.Model`` wrapping
``litellm.acompletion`` with route-prefix provider selection) is based on the
upstream open-source library:

* Library:  ``pydantic-ai-litellm`` (by ``mochow13``)
* Version:  targets ``pydantic-ai-slim>=1.95.0`` (V1); hand-reconciled here to
            the Pydantic AI V2 (Beta) ``Model`` ABC (``pydantic-ai==2.0.0b6``)
* Repo:     https://github.com/mochow13/pydantic-ai-litellm
* License:  MIT

MIT License — Copyright (c) the ``pydantic-ai-litellm`` authors. Permission is
hereby granted, free of charge, to any person obtaining a copy of this software
and associated documentation files (the "Software"), to deal in the Software
without restriction, including without limitation the rights to use, copy,
modify, merge, publish, distribute, sublicense, and/or sell copies of the
Software, and to permit persons to whom the Software is furnished to do so,
subject to the inclusion of the above copyright notice and this permission
notice in all copies or substantial portions of the Software. THE SOFTWARE IS
PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from functools import cached_property
from typing import TYPE_CHECKING, Any, cast

import httpx
from pydantic_ai.exceptions import ModelAPIError
from pydantic_ai.models import Model
from pydantic_ai.profiles import DEFAULT_PROFILE, ModelProfile, merge_profile

# Shared OpenAI-shaped mapping (Req 11 / ADR-1): the same helpers and
# ``build_response`` the watsonx SDK transport consumes. The ``_map_*`` names are
# spec-mandated underscore helpers imported across the module boundary; the scoped
# pyright suppressions acknowledge that hop without weakening the strict ruleset
# (tech.md typing convention).
from pydantic_ai_sandbox.llm._openai_mapping import (
    _map_messages,  # pyright: ignore[reportPrivateUsage]
    _map_tools,  # pyright: ignore[reportPrivateUsage]
    build_response,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from pydantic_ai import RunContext
    from pydantic_ai.messages import ModelMessage, ModelResponse
    from pydantic_ai.models import ModelRequestParameters, StreamedResponse
    from pydantic_ai.settings import ModelSettings


class LiteLLMModel(Model):
    """Pydantic AI ``Model`` executing one non-streaming chat via ``litellm.acompletion()``.

    Task 2.1 lands the I/O-free constructor and the ``model_name`` / ``system`` /
    ``profile`` properties that drive instrumentation and output-mode selection;
    Task 2.2 lands :meth:`request`. The ``system`` value is derived once from the
    route provider segment and is the *same* value stamped onto the response
    ``provider_name`` (Req 1.4 parity).
    """

    def __init__(
        self,
        *,
        model_name: str,
        api_key: str | None = None,
        api_base: str | None = None,
        custom_llm_provider: str | None = None,
        timeout_connect: float,
        timeout_read: float,
    ) -> None:
        """Store the route + transport config; perform no network I/O (Req 1.3).

        Args:
            model_name: The LiteLLM route ``<provider>/<model_id>`` (e.g.
                ``watsonx/ibm/granite-...``); LiteLLM selects the backend from the
                prefix.
            api_key: Already-unwrapped API key handed to ``acompletion``; never
                logged. Unwrapping the ``SecretStr`` is the builder's job
                (``_build_litellm``), so this model receives a plain value.
            api_base: Backend base URL (e.g. the watsonx URL).
            custom_llm_provider: Optional explicit LiteLLM provider override.
                Not set by ``_build_litellm`` (always ``None`` on the watsonx
                route); reserved for future generic-model wiring (Req 1.2).
            timeout_connect: Connect-phase timeout (seconds) → ``acompletion``.
            timeout_read: Read-phase timeout (seconds) → ``acompletion``.
        """
        super().__init__()
        self._model_name = model_name
        self._api_key = api_key
        self._api_base = api_base
        self._custom_llm_provider = custom_llm_provider
        self._timeout_connect = timeout_connect
        self._timeout_read = timeout_read
        # Derived once from the route provider segment (``<provider>/`` prefix),
        # falling back to ``"litellm"`` for a prefix-less route. The same value is
        # passed to ``build_response(provider_name=...)`` so ``gen_ai.system`` and
        # the response provider agree and match the SDK path (Req 1.4).
        self._system = model_name.split("/", 1)[0] if "/" in model_name else "litellm"

    @property
    def model_name(self) -> str:
        """Return the LiteLLM route → ``gen_ai.request.model`` (Req 1.2)."""
        return self._model_name

    @property
    def system(self) -> str:
        """Return the route provider segment → ``gen_ai.system`` (Req 1.4).

        ``"watsonx"`` for a ``watsonx/<id>`` route; ``"litellm"`` for a
        prefix-less route. Matches the SDK transport for the watsonx route so
        instrumentation is parity-equivalent across transports.
        """
        return self._system

    @cached_property
    def profile(self) -> ModelProfile:
        """Keep ``supports_json_schema_output`` falsy for tool-mode parity (Req 1.5).

        ``build_chat_agent`` wraps output in :class:`pydantic_ai.NativeOutput` /
        forces ``response_format`` only when the resolved profile reports
        ``supports_json_schema_output: True``. The watsonx route does not support
        that, and the SDK transport keeps the flag falsy, so this transport must
        too. The flag is forced ``False`` over the package default explicitly so a
        future change to ``DEFAULT_PROFILE`` cannot silently flip the output mode;
        all other default profile fields are preserved via the merge.
        """
        return merge_profile(DEFAULT_PROFILE, ModelProfile(supports_json_schema_output=False))

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        """Execute one non-streaming inference via ``litellm.acompletion()`` (Req 1.1).

        Maps the history and tool definitions to the OpenAI-shaped payload via the
        shared ``_openai_mapping`` helpers, calls ``acompletion`` with
        ``num_retries=0`` (Req 4.2 / ADR-2 — the fallback chain is the sole
        resilience layer) and both timeout phases shaped as
        ``httpx.Timeout(read, connect=connect)`` (Req 5.1), then normalises the
        returned ``litellm.ModelResponse`` object into the OpenAI-shaped ``dict``
        the shared :func:`build_response` consumes.

        The ``.model_dump()`` normalization is load-bearing for Req 2.4: it
        preserves ``tool_calls[].function.arguments`` as the raw JSON string the
        backend sent (Granite double-encodes its args), where attribute access or
        a re-parsing variant would corrupt them. ``build_response`` is then stamped
        with the route-derived ``system`` value (not a hard-coded ``"litellm"``) so
        the response provider matches ``gen_ai.system`` and the SDK path for the
        watsonx route.

        Per-request :class:`ModelSettings` are not forwarded — mapping them to
        ``acompletion`` parameters is out of scope for this transport, matching the
        SDK transport and pydantic_ai's silently-ignore convention
        (``models/CLAUDE.md``).

        Args:
            messages: The full conversation history to send.
            model_settings: Per-request settings; intentionally unused here.
            model_request_parameters: Carries the tool definitions advertised to
                the model (function tools + output tools).

        Returns:
            The mapped :class:`ModelResponse` (text/tool-call parts, usage, finish
            reason and provider response id), stamped with this transport's
            identity for instrumentation parity.

        Raises:
            ModelAPIError: For any failure raised by ``acompletion()`` — wrapped
                and chained via ``raise ... from`` so ``FallbackModel.fallback_on``
                (default ``(ModelAPIError,)``) can recover it (Req 4.1).
            NotImplementedError: For an unsupported (e.g. multimodal) message part
                — surfaced unwrapped from the mapping layer (fail loud); the map
                runs before the wrapped call, so it is never reached by the
                broad ``except`` (Req 4.3).
            UnexpectedModelBehavior: For a choiceless completion — surfaced
                unwrapped from :func:`build_response`, which sits outside the
                ``try`` so it is never misclassified as ``ModelAPIError`` (fail
                loud, Req 3.3 / 4.3).
        """
        del model_settings  # not mapped to acompletion params (see docstring)
        # Function-local import of the optional ``litellm`` dependency (Req 6.2):
        # ``llm.factory`` imports the watsonx module (and thus this one) eagerly, so
        # a module-level import would force the heavy ``litellm`` package on every
        # deployment — including SDK-only ones. The builder's import guard
        # (``_build_litellm``, Task 4.2) has already failed loud with a ``ValueError``
        # if the package is absent, so by request time it is present.
        import litellm

        openai_messages = _map_messages(messages)
        tools = _map_tools(model_request_parameters)
        # ``litellm``'s stubs type ``acompletion``'s ``messages`` / ``tools`` as
        # ``List[Unknown]`` (hence ``reportUnknownMemberType`` on the reference) and
        # ``timeout`` as ``float | int | None`` even though it forwards an
        # ``httpx.Timeout`` to the backend at runtime (research.md: both connect and
        # read phases reach the backend — Req 5.1). The scoped suppressions
        # acknowledge the loose stubs without weakening the strict ruleset.
        timeout = httpx.Timeout(self._timeout_read, connect=self._timeout_connect)
        # The broad ``except`` is deliberate and scoped to **only** the
        # ``acompletion`` call (Req 4.1). LiteLLM multiplexes many backends, each
        # raising its own provider-specific exception hierarchy (``litellm.*Error``,
        # ``httpx.*``, provider-SDK errors) with no shared base we could narrowly
        # name; so unlike the SDK transport's specific tuple, every transport
        # failure must be funnelled into ``ModelAPIError`` (chained via ``from``)
        # so ``FallbackModel.fallback_on`` (default ``(ModelAPIError,)``) can
        # recover it. ``.model_dump()`` and ``build_response`` sit **below** this
        # block precisely so a post-call mapping/response error
        # (``UnexpectedModelBehavior`` for a choiceless completion, Req 3.3) is
        # never misclassified as a recoverable ``ModelAPIError`` (Req 4.3).
        try:
            response = await litellm.acompletion(  # pyright: ignore[reportUnknownMemberType]
                model=self._model_name,
                messages=openai_messages,
                tools=tools,
                api_key=self._api_key,
                api_base=self._api_base,
                custom_llm_provider=self._custom_llm_provider,
                num_retries=0,
                timeout=timeout,  # pyright: ignore[reportArgumentType]
            )
        except Exception as exc:  # Req 4.1: every acompletion failure → ModelAPIError for fallback
            # BLE001 is intentionally not suppressed here: ruff's blind-except lane
            # flags only excepts that *swallow*; this one re-raises (``from exc``),
            # so it is already compliant. The breadth rationale is documented in the
            # block comment above the ``try``.
            msg = f"litellm request failed ({type(exc).__name__}): {exc}"
            raise ModelAPIError(model_name=self.model_name, message=msg) from exc
        # ``acompletion`` returns ``ModelResponse | CustomStreamWrapper`` per its
        # stubs; we never stream, so it is the non-streaming ``ModelResponse``.
        # ``.model_dump()`` yields the OpenAI-shaped dict ``build_response`` consumes,
        # preserving raw tool-call arg strings (Req 2.4). The suppression covers the
        # union member ``CustomStreamWrapper`` (which has no ``model_dump``) and the
        # stub's partially-unknown ``model_dump`` signature.
        raw = cast("dict[str, Any]", response.model_dump())  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
        return build_response(raw, model_name=self.model_name, provider_name=self.system)

    @asynccontextmanager
    async def request_stream(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
        run_context: RunContext[Any] | None = None,
    ) -> AsyncGenerator[StreamedResponse]:
        """Reject streaming — deferred to future work (Req 8.1-8.3).

        Streaming is out of scope for this transport (spec.md "Out of Scope"): the
        ``/chat`` endpoint issues a single non-streaming :meth:`request`. This
        override raises a greppable, model-named ``NotImplementedError`` **before
        any yield** rather than silently downgrading to a non-streaming request
        (Req 8.2) or inheriting the base ABC's generic message — so a future caller
        wiring streaming gets an explicit, actionable signal. The signature mirrors
        the base exactly so the override stays Liskov-compatible; the unreachable
        ``yield`` keeps it an async generator for the ``@asynccontextmanager``
        contract.

        Raises:
            NotImplementedError: Always — streaming support is deferred. The message
                names the model so the refusal is greppable (Req 8.3).
        """
        del messages, model_settings, model_request_parameters, run_context
        msg = f"LiteLLM streaming support deferred to future work (model: {self.model_name})"
        raise NotImplementedError(msg)
        yield  # pragma: no cover — unreachable; required to type as a generator
