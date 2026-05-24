"""Runtime configuration loaded from environment variables.

Implements the ``Settings`` contract from plan.md §2.1: a frozen
``pydantic_settings.BaseSettings`` view of the deployment environment that
fails fast at construction time on:

* missing ``OLLAMA_MODEL_NAME`` when ``LLM_PROVIDER=ollama`` (Req 1.2)
* empty / wholly-unknown ``FALLBACK_ORDER`` when ``LLM_PROVIDER=fallback``
  (Req 4.5 構文段)
* unknown ``LLM_PROVIDER`` value (Req 2.5 前段, enforced via ``Literal``)

The single public function ``get_settings()`` returns a process-wide
singleton via :func:`functools.lru_cache`. Tests reset the cache with
``get_settings.cache_clear()`` between configurations.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import HttpUrl, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LLMProvider = Literal["ollama", "watsonx", "anthropic", "bedrock", "fallback"]
"""Authoritative provider alphabet — must stay in lockstep with the
``ModelFactory`` dispatch table (T4.3) and ``_build_fallback`` member
resolver (T5.4)."""

_KNOWN_FALLBACK_MEMBERS: frozenset[str] = frozenset(
    {"ollama", "watsonx", "anthropic", "bedrock"},
)
"""Provider names that may legally appear inside ``FALLBACK_ORDER``.

The ``"fallback"`` sentinel is intentionally excluded — recursive
fallback composition is undefined behaviour in the MVP."""


class Settings(BaseSettings):
    """Frozen typed view of the runtime environment.

    All provider-specific credentials are optional so tests and local
    development can construct a partial ``Settings`` without supplying
    secrets they do not need. Cross-field invariants are enforced by
    :meth:`_check_provider_constraints`.

    Attributes:
        app_env: Deployment tier hint — ``development`` / ``staging`` /
            ``production``. Free-form string; downstream consumers MAY
            narrow it later.
        log_level: Standard ``logging`` level name (``DEBUG`` / ``INFO``
            / ``WARNING`` / ``ERROR``). Free-form to avoid coupling.
        llm_provider: Selected backend — see :data:`LLMProvider`.
        ollama_base_url: HTTP base for the local Ollama daemon.
        ollama_model_name: Required when ``llm_provider == "ollama"``.
        ollama_api_key: Optional bearer for hosted Ollama deployments.
        watsonx_*: Optional IBM watsonx.ai credentials, populated only
            when that provider is selected (or referenced via
            ``FALLBACK_ORDER``).
        anthropic_*: Optional Anthropic direct-API credentials.
        bedrock_*: Optional AWS Bedrock credentials and inference-profile
            identifiers.
        fallback_order: Comma-separated provider names defining the
            ``FallbackModel`` member order (T5.4).
        logfire_token: Optional Logfire token; absence triggers
            ``send_to_logfire='if-token-present'`` (T7.3).
        log_sensitive_payloads: Opt-in flag that disables payload
            scrubbing (T7.3); kept opt-in to satisfy Req 5.4.
    """

    model_config = SettingsConfigDict(
        env_file=None,
        case_sensitive=False,
        extra="ignore",
        frozen=True,
    )

    app_env: str = "development"
    log_level: str = "INFO"
    llm_provider: LLMProvider = "ollama"

    ollama_base_url: HttpUrl = HttpUrl("http://localhost:11434")
    ollama_model_name: str | None = None
    ollama_api_key: str | None = None

    watsonx_url: str | None = None
    watsonx_apikey: str | None = None
    watsonx_project_id: str | None = None
    watsonx_model_id: str | None = None
    watsonx_transport: Literal["sdk", "litellm"] | None = None

    anthropic_api_key: str | None = None
    anthropic_model: str | None = None

    bedrock_region: str | None = None
    bedrock_model_id: str | None = None
    bedrock_inference_profile_id: str | None = None

    fallback_order: str = ""
    logfire_token: str | None = None
    log_sensitive_payloads: bool = False

    @model_validator(mode="after")
    def _check_provider_constraints(self) -> Settings:
        """Enforce cross-field invariants tied to the selected provider.

        Raises:
            ValueError: When ``llm_provider == "ollama"`` and
                ``ollama_model_name`` is unset, or when
                ``llm_provider == "fallback"`` and ``fallback_order`` is
                empty / contains only unknown member names. Pydantic
                wraps the raised ``ValueError`` into a ``ValidationError``
                before it reaches the caller.
        """
        if self.llm_provider == "ollama" and not self.ollama_model_name:
            msg = (
                "OLLAMA_MODEL_NAME is required when LLM_PROVIDER=ollama; "
                "set the env var or switch LLM_PROVIDER."
            )
            raise ValueError(msg)

        if self.llm_provider == "fallback":
            members = [m.strip() for m in self.fallback_order.split(",") if m.strip()]
            if not members:
                msg = (
                    "FALLBACK_ORDER must name at least one provider when "
                    "LLM_PROVIDER=fallback (e.g. FALLBACK_ORDER=ollama,anthropic)."
                )
                raise ValueError(msg)

            unknown = [m for m in members if m not in _KNOWN_FALLBACK_MEMBERS]
            if len(unknown) == len(members):
                msg = (
                    "FALLBACK_ORDER must contain at least one known provider "
                    f"name from {sorted(_KNOWN_FALLBACK_MEMBERS)}; "
                    f"got only unknown entries: {unknown}."
                )
                raise ValueError(msg)

        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide :class:`Settings` singleton.

    Cached via :func:`functools.lru_cache` so repeated FastAPI
    ``Depends`` resolutions and agent-construction paths share a single
    instance. Tests reset the cache with
    ``get_settings.cache_clear()`` to exercise different env states.
    """
    return Settings()
