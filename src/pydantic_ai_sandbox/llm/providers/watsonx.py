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

import os
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, cast

import httpx
from pydantic_ai.exceptions import ModelAPIError
from pydantic_ai.models import Model

# Shared OpenAI-shaped mapping (Req 11 / ADR-1): the helpers and ``build_response``
# now live in ``llm._openai_mapping`` so this transport and ``LiteLLMModel`` consume
# one implementation. The ``_map_*`` names are spec-mandated underscore helpers
# imported across the module boundary; the scoped pyright suppressions acknowledge
# that hop without weakening the strict ruleset (tech.md typing convention).
from pydantic_ai_sandbox.llm._openai_mapping import (
    _map_messages,  # pyright: ignore[reportPrivateUsage]
    _map_tools,  # pyright: ignore[reportPrivateUsage]
    build_response,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from ibm_watsonx_ai.foundation_models import ModelInference
    from pydantic_ai import RunContext
    from pydantic_ai.messages import ModelMessage, ModelResponse
    from pydantic_ai.models import ModelRequestParameters, StreamedResponse
    from pydantic_ai.settings import ModelSettings

    from pydantic_ai_sandbox.config import Settings

# ``_build_watsonx`` is the spec-mandated underscore-prefixed factory entry
# (plan.md §2.3). The three shared mapping utilities are **re-exported** here
# (Task 1.4): they were part of ``watsonx.py``'s public surface in feature
# ``002`` before the C1 extraction, so listing them in ``__all__`` preserves
# that surface byte-for-byte (Req 11.3/11.4) and marks the cross-module imports
# as intentional re-exports (pyright/ruff treat ``__all__`` membership as use).
# The underscore names already carry the ``# pyright: ignore[reportPrivateUsage]``
# on their import below (tech.md cross-module underscore convention).
__all__ = [
    "_build_watsonx",
    "_map_messages",
    "_map_tools",
    "build_response",
]


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

        Thin adapter over the shared :func:`build_response` (Req 11 / ADR-1):
        stamps this transport's identity (``model_name`` /
        ``provider_name="watsonx"``) onto the response so ``gen_ai.request.model``
        and ``gen_ai.system`` satisfy the instrumentation contract. The mapping
        logic — including the no-``choices`` :class:`UnexpectedModelBehavior`
        guard — now lives in ``_openai_mapping``; the *observable* behaviour is
        unchanged from the original in-module method (Req 11.4). The only edit is
        transport-neutral fail-loud wording, since the messages are now shared
        with the LiteLLM route (tests assert on substrings, so no regression).

        Args:
            raw: The dict returned by :meth:`ModelInference.achat`.

        Returns:
            The mapped :class:`ModelResponse` with the standard identity fields
            (``model_name`` / ``provider_name``) stamped for instrumentation.

        Raises:
            UnexpectedModelBehavior: If the response has no ``choices`` (raised by
                the shared :func:`build_response`).
        """
        return build_response(
            raw,
            model_name=self.model_name,
            provider_name="watsonx",
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
    """Build the LiteLLM-routed watsonx ``Model`` (Task 4 / C3). I/O-free.

    Constructs the provider-agnostic
    :class:`~pydantic_ai_sandbox.llm.providers.litellm.LiteLLMModel`, which routes
    chat through ``litellm.acompletion()`` with the ``watsonx/<model_id>`` route
    prefix LiteLLM uses to select the watsonx backend (Req 7.1). This replaces the
    former ``OpenAIChatModel`` / ``LiteLLMProvider`` construction, which POSTed to
    ``/chat/completions`` — an endpoint watsonx.ai does not expose (the 002
    live-verified 404).

    Credential / config routing:

    * The ``SecretStr`` apikey is unwrapped via ``.get_secret_value()`` **only
      here**, at this boundary (tech.md secrets convention), and handed to the
      model as a plain value it never logs (Req 7.3/7.5).
    * ``watsonx_url`` is routed as ``api_base`` (Req 7.1); ``watsonx_timeout_connect``
      / ``watsonx_timeout_read`` flow to the model, which shapes them into
      ``httpx.Timeout(read, connect=connect)`` on each request — the same shaping
      as the SDK client (:meth:`WatsonxSDKModel._build_client`), so both phases
      reach the backend (Req 5.2).
    * ``WATSONX_PROJECT_ID`` is reconciled into ``os.environ`` (research.md ADR-3):
      LiteLLM's watsonx path reads the project id from the process environment
      directly, not from an ``acompletion`` kwarg, and a deployment loading
      ``Settings`` from a ``.env`` file would otherwise leave it unset in
      ``os.environ`` even though ``settings.watsonx_project_id`` is populated. The
      value is sourced from the already-validated setting (Req 7.2).

    Setting ``os.environ`` is a process-global mutation inside an otherwise
    I/O-free, side-effect-free builder (against the construction convention,
    tech.md); it is accepted only because LiteLLM reads ``os.environ`` **directly**
    (ADR-3). The hermetic test for this branch uses ``monkeypatch`` so the write
    does not leak across tests; if the live lane (Req 10.3) confirms an
    ``acompletion(project_id=...)`` kwarg works, prefer that and drop the env write.

    The optional ``litellm`` package and the ``LiteLLMModel`` adapter are imported
    function-locally (not at module scope): :mod:`llm.factory` imports this module
    unconditionally, so a top-level ``import litellm`` would force the heavy
    optional dependency on every deployment — including SDK-only and ollama-only
    ones that never select the litellm transport.

    Args:
        settings: Frozen runtime settings; the credential gate has already
            validated the watsonx fields when watsonx is selected.

    Returns:
        A :class:`LiteLLMModel` routed through LiteLLM to watsonx.

    Raises:
        ValueError: If the optional ``litellm`` package is not installed (Req
            6.1) — naming the package + install command so the operator knows what
            to do.
        TypeError: If ``watsonx_apikey`` / ``watsonx_model_id`` /
            ``watsonx_project_id`` are ``None`` — unreachable when watsonx is
            selected (the credential gate rejects that at boot); defensive against
            a future validator change, matching the SDK builder's fail-loud
            invariants.
    """
    # Import guard (Req 6.1): the litellm transport is an optional extra. A
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

    # The ``LiteLLMModel`` adapter imported here (not at module scope) for the same
    # reason as the SDK import in ``_build_client``: keep importing this module
    # cheap for deployments that never select the litellm transport.
    from pydantic_ai_sandbox.llm.providers.litellm import LiteLLMModel

    apikey = settings.watsonx_apikey
    model_id = settings.watsonx_model_id
    if apikey is None or model_id is None:
        msg = (
            "watsonx_apikey/watsonx_model_id is None at _build_litellm time — "
            "the credential gate (config) should have rejected this "
            "configuration; did the cross-field validator change?"
        )
        raise TypeError(msg)

    # Reconcile WATSONX_PROJECT_ID into the process environment for LiteLLM's
    # watsonx path (ADR-3). The boot credential gate guarantees
    # ``watsonx_project_id`` is present when watsonx is selected, so a ``None``
    # here is a defensive invariant (mirroring the apikey/model-id guard above),
    # not a user-facing path — the gate already emits the actionable message, so
    # this is not duplicated with a divergent one.
    project_id = settings.watsonx_project_id
    if project_id is None:  # pragma: no cover - unreachable past the boot credential gate
        msg = (
            "watsonx_project_id is None at _build_litellm time — "
            "the credential gate (config) should have rejected this "
            "configuration; did the cross-field validator change?"
        )
        raise TypeError(msg)
    os.environ["WATSONX_PROJECT_ID"] = project_id

    return LiteLLMModel(
        model_name=f"watsonx/{model_id}",
        # Unwrap the SecretStr only here, at the boundary (tech.md secrets
        # convention); the value is never logged.
        api_key=apikey.get_secret_value(),
        api_base=settings.watsonx_url,
        timeout_connect=settings.watsonx_timeout_connect,
        timeout_read=settings.watsonx_timeout_read,
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
      (Task 4 / C3) with its optional-dependency import-guard. Also I/O-free —
      the :class:`~pydantic_ai_sandbox.llm.providers.litellm.LiteLLMModel` is
      constructed but its first ``litellm.acompletion()`` call is deferred until
      a request is served.

    Args:
        settings: Frozen runtime settings; the credential gate has already
            validated the watsonx fields when watsonx is selected.

    Returns:
        A ``pydantic_ai.models.Model`` ready to be passed to
        :class:`pydantic_ai.Agent`.

    Raises:
        ValueError: For ``watsonx_transport == "litellm"`` when the optional
            ``litellm`` package is not installed (Req 6.1).
    """
    if settings.watsonx_transport == "sdk":
        return WatsonxSDKModel(settings)
    # ``watsonx_transport`` is a validated ``Literal["sdk", "litellm"]`` (config
    # Task 2.3), so the only remaining value is ``"litellm"``.
    return _build_litellm(settings)
