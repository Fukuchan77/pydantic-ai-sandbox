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

from typing import TYPE_CHECKING

import httpx
from pydantic_ai.models import Model

if TYPE_CHECKING:
    from ibm_watsonx_ai.foundation_models import ModelInference
    from pydantic_ai.messages import ModelMessage, ModelResponse
    from pydantic_ai.models import ModelRequestParameters
    from pydantic_ai.settings import ModelSettings

    from pydantic_ai_sandbox.config import Settings

# Spec-mandated underscore-prefixed name (plan.md §2.3); exported via
# ``__all__`` so pyright treats it as the module's public surface and does
# not flag the cross-module import in ``llm.factory`` as unused.
__all__ = ["_build_watsonx"]


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
        """Execute one non-streaming inference via ``ibm-watsonx-ai``.

        The message mapping, async ``ModelInference.achat`` call and
        ``ModelAPIError`` wrapping land in Task 5; Task 4 ships only the
        activation skeleton so the factory can return a real ``Model``.

        Raises:
            NotImplementedError: Always, until Task 5 wires the SDK request
                path. Fails loud rather than silently returning an empty
                response.
        """
        del messages, model_settings, model_request_parameters
        msg = "WatsonxSDKModel.request is implemented in Task 5 (SDK transport)."
        raise NotImplementedError(msg)


def _build_watsonx(settings: Settings) -> Model:
    """Build a watsonx-backed ``Model`` per ``WATSONX_TRANSPORT``. I/O-free.

    Follows the established ``_build_ollama(settings) -> Model`` shape
    (``structure.md``). Task 4 wires the SDK transport (the default) so the
    factory returns a real ``Model`` instance for ``LLM_PROVIDER=watsonx``; the
    explicit transport dispatch (sdk vs litellm) and the litellm branch land in
    Tasks 5.6 / 6.

    Args:
        settings: Frozen runtime settings; the credential gate has already
            validated the watsonx fields when watsonx is selected.

    Returns:
        A ``pydantic_ai.models.Model`` ready to be passed to
        :class:`pydantic_ai.Agent`.
    """
    return WatsonxSDKModel(settings)
