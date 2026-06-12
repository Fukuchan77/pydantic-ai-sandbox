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
from typing import TYPE_CHECKING, Literal
from urllib.parse import urlparse

from pydantic import HttpUrl, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

if TYPE_CHECKING:
    from pydantic import ValidationInfo

_WATSONX_TRANSPORTS: tuple[str, ...] = ("sdk", "litellm")
"""Valid ``WATSONX_TRANSPORT`` values; the validator's error message lists
these verbatim (Req 2.5)."""

_WATSONX_URL_SCHEMES: frozenset[str] = frozenset({"http", "https"})
"""Accepted ``WATSONX_URL`` protocols (plan.md §Contract 2: ``^https?://``)."""

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
    # Secret-typed credentials: ``SecretStr`` overrides ``__repr__`` /
    # ``__str__`` to return ``"**********"`` so a stray ``logger.warning(
    # ..., exc_info=True)`` or interpolated ``f"{settings}"`` cannot
    # leak the raw value. Recover the literal at SDK call sites via
    # :meth:`SecretStr.get_secret_value` (see ``llm/providers/ollama.py``
    # and ``logging_setup.py``).
    ollama_api_key: SecretStr | None = None

    watsonx_url: str | None = None
    watsonx_apikey: SecretStr | None = None
    watsonx_project_id: str | None = None
    watsonx_model_id: str | None = None
    # Normalized to lower-case and defaulted to ``"sdk"`` by
    # :meth:`_normalize_watsonx_transport` (Req 2.2/2.4/2.5).
    watsonx_transport: Literal["sdk", "litellm"] = "sdk"
    # Connect/read timeouts (seconds) applied to both transports (Req 5.1-5.4).
    # Validated positive by :meth:`_validate_watsonx_timeout` (Req 5.5).
    watsonx_timeout_connect: int = 30
    watsonx_timeout_read: int = 120

    anthropic_api_key: SecretStr | None = None
    anthropic_model: str | None = None

    bedrock_region: str | None = None
    bedrock_model_id: str | None = None
    bedrock_inference_profile_id: str | None = None

    fallback_order: str = ""
    logfire_token: SecretStr | None = None
    log_sensitive_payloads: bool = False

    @field_validator("watsonx_transport", mode="before")
    @classmethod
    def _normalize_watsonx_transport(cls, value: object) -> str:
        """Lower-case ``WATSONX_TRANSPORT`` and default it to ``"sdk"``.

        Runs before the ``Literal`` check so ``SDK`` / ``LiteLLM`` are accepted
        case-insensitively (Req 2.4) and an unset / blank value falls back to
        the ``sdk`` default (Req 2.2). An out-of-set value raises a
        ``ValueError`` whose message lists the valid values (Req 2.5),
        replacing Pydantic's generic ``Literal`` error.
        """
        if value is None:
            return "sdk"
        if not isinstance(value, str):
            msg = f"WATSONX_TRANSPORT must be one of {_WATSONX_TRANSPORTS}; got {value!r}."
            raise ValueError(msg)
        normalized = value.strip().lower()
        if not normalized:
            return "sdk"
        if normalized not in _WATSONX_TRANSPORTS:
            msg = f"WATSONX_TRANSPORT must be one of {_WATSONX_TRANSPORTS}; got {value!r}."
            raise ValueError(msg)
        return normalized

    @field_validator("watsonx_timeout_connect", "watsonx_timeout_read", mode="before")
    @classmethod
    def _validate_watsonx_timeout(cls, value: object, info: ValidationInfo) -> int:
        """Reject non-numeric / non-positive timeout values (Req 5.5).

        The env var name is the upper-cased field name
        (``watsonx_timeout_connect`` → ``WATSONX_TIMEOUT_CONNECT``), so the
        message points operators straight at the offending variable.
        """
        env_name = (info.field_name or "watsonx_timeout").upper()
        try:
            parsed = int(value)  # type: ignore[arg-type]  # str/int from env
        except TypeError, ValueError:
            msg = f"{env_name} must be a positive integer (seconds); got {value!r}."
            raise ValueError(msg) from None
        if parsed <= 0:
            msg = f"{env_name} must be a positive integer (seconds); got {parsed}."
            raise ValueError(msg)
        return parsed

    @field_validator("watsonx_url", mode="after")
    @classmethod
    def _validate_watsonx_url(cls, value: str | None) -> str | None:
        """Validate ``WATSONX_URL`` structure only — no network call.

        Uses :func:`urllib.parse.urlparse` to require an ``http(s)`` scheme and
        a non-empty host (Req 4.1); reachability is deferred to runtime
        (Req 4.3). An invalid structure fails fast with a detailed message
        (Req 4.2).
        """
        if value is None:
            return None
        parsed = urlparse(value)
        if parsed.scheme not in _WATSONX_URL_SCHEMES or not parsed.netloc:
            msg = (
                "WATSONX_URL must be a valid URL with an http(s):// scheme and a "
                "host (e.g. https://us-south.ml.cloud.ibm.com); "
                f"got {value!r}."
            )
            raise ValueError(msg)
        return value

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

        # watsonx credential gate (Req 3.1/3.2/3.3). Fires when watsonx is
        # actually selected — directly (LLM_PROVIDER=watsonx) or as a member of
        # an active fallback chain (LLM_PROVIDER=fallback with watsonx in
        # FALLBACK_ORDER). Intentionally stricter than the Ollama gate: a
        # partially-credentialled watsonx in the chain must fail at boot rather
        # than defer to the first failover (plan.md Entity 1, SC-004/SC-005).
        fallback_members = {m.strip().lower() for m in self.fallback_order.split(",")}
        watsonx_selected = self.llm_provider == "watsonx" or (
            self.llm_provider == "fallback" and "watsonx" in fallback_members
        )
        if watsonx_selected:
            required = {
                "WATSONX_APIKEY": self.watsonx_apikey,
                "WATSONX_PROJECT_ID": self.watsonx_project_id,
                "WATSONX_URL": self.watsonx_url,
                "WATSONX_MODEL_ID": self.watsonx_model_id,
            }
            missing = [name for name, val in required.items() if not val]
            if missing:
                msg = (
                    f"{missing[0]} is required when watsonx is selected "
                    "(LLM_PROVIDER=watsonx or watsonx in FALLBACK_ORDER); "
                    f"missing: {missing}."
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
