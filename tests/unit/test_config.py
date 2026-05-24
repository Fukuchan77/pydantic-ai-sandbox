"""Unit tests for ``pydantic_ai_sandbox.config.Settings`` (Task 3.2).

Locks the env-var contract from plan.md §2.1:

* normal path — LLM_PROVIDER=ollama + required vars → constructs cleanly.
* fail-fast — missing OLLAMA_MODEL_NAME under provider=ollama surfaces a
  ValidationError naming the offending env var (Req 1.2).
* fail-fast — provider=fallback with empty / all-unknown FALLBACK_ORDER is
  rejected at Settings construction (Req 4.5 構文段).
* fail-fast — unknown LLM_PROVIDER value is rejected (Req 2.5 前段).
* LOGFIRE_TOKEN absence does not block startup (Req 5.2 前段).

Note on exception class: tasks.md T3.2 mentions "ValueError" for
fallback / unknown-provider cases. In Pydantic v2 a validator raising
``ValueError`` is wrapped into :class:`pydantic.ValidationError` before
reaching the caller, and ``ValidationError`` is *not* a subclass of
``ValueError``. The tests therefore assert on ``ValidationError`` (the
class actually surfaced) and inspect the error chain / message for the
expected wording.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, get_args, get_type_hints

import pytest
from pydantic import ValidationError

from pydantic_ai_sandbox.config import Settings, get_settings

if TYPE_CHECKING:
    from tests.conftest import SettingsFactory


# A placeholder model name that is intentionally outside
# FORBIDDEN_MODEL_ID_LITERALS so these tests cannot inadvertently regress
# the hardcoded-model-ID guard (T2.1) when scanned.
DUMMY_OLLAMA_MODEL = "dummy-ollama-model"
DUMMY_OLLAMA_URL = "http://localhost:11434"


def test_ollama_happy_path_returns_frozen_literal_provider(
    settings_factory: SettingsFactory,
) -> None:
    settings = settings_factory(
        LLM_PROVIDER="ollama",
        OLLAMA_BASE_URL=DUMMY_OLLAMA_URL,
        OLLAMA_MODEL_NAME=DUMMY_OLLAMA_MODEL,
    )

    # llm_provider must be normalised to the Literal alphabet; equality
    # check is enough — the type system guarantees the rest at static time.
    assert settings.llm_provider == "ollama"
    assert settings.ollama_model_name == DUMMY_OLLAMA_MODEL

    # frozen=True (plan §2.1): mutation must be blocked.
    with pytest.raises(ValidationError):
        settings.llm_provider = "anthropic"  # pyright: ignore[reportAttributeAccessIssue]


def test_llm_provider_literal_alphabet_is_authoritative() -> None:
    """Lock the Literal alphabet so silent additions can't slip through.

    plan.md §2.1 specifies five providers; tasks downstream (T4.x, T5.x)
    branch on this exact set. If anyone adds or renames a provider the
    Literal hint is the one place that must change in lockstep with the
    factory dispatch table — this test surfaces the drift.
    """
    hints = get_type_hints(Settings)
    literal_args = set(get_args(hints["llm_provider"]))
    assert literal_args == {"ollama", "watsonx", "anthropic", "bedrock", "fallback"}


def test_ollama_provider_requires_model_name(
    settings_factory: SettingsFactory,
) -> None:
    with pytest.raises(ValidationError) as exc_info:
        settings_factory(
            LLM_PROVIDER="ollama",
            OLLAMA_BASE_URL=DUMMY_OLLAMA_URL,
            OLLAMA_MODEL_NAME=None,
        )

    # The validator MUST name the offending variable so operators can fix
    # the deployment from the error alone (Req 1.2).
    assert "OLLAMA_MODEL_NAME" in str(exc_info.value)


def test_unknown_llm_provider_is_rejected(
    settings_factory: SettingsFactory,
) -> None:
    with pytest.raises(ValidationError) as exc_info:
        settings_factory(LLM_PROVIDER="foobar")

    # Pydantic's Literal-mismatch error mentions the offending value;
    # we assert that hint to guard against accidental ``str`` widening.
    assert "foobar" in str(exc_info.value)


def test_fallback_provider_rejects_empty_order(
    settings_factory: SettingsFactory,
) -> None:
    with pytest.raises(ValidationError) as exc_info:
        settings_factory(
            LLM_PROVIDER="fallback",
            FALLBACK_ORDER="",
        )

    assert "FALLBACK_ORDER" in str(exc_info.value)


def test_fallback_provider_rejects_only_unknown_members(
    settings_factory: SettingsFactory,
) -> None:
    with pytest.raises(ValidationError) as exc_info:
        settings_factory(
            LLM_PROVIDER="fallback",
            FALLBACK_ORDER="not-a-provider,also-bogus",
        )

    msg = str(exc_info.value)
    assert "FALLBACK_ORDER" in msg
    assert "not-a-provider" in msg or "also-bogus" in msg


def test_fallback_provider_accepts_known_member(
    settings_factory: SettingsFactory,
) -> None:
    """``FALLBACK_ORDER=ollama`` must parse — the unknown-only check is
    not a blanket ban on single-member lists."""
    settings = settings_factory(
        LLM_PROVIDER="fallback",
        OLLAMA_BASE_URL=DUMMY_OLLAMA_URL,
        OLLAMA_MODEL_NAME=DUMMY_OLLAMA_MODEL,
        FALLBACK_ORDER="ollama",
    )
    assert settings.fallback_order == "ollama"


def test_logfire_token_optional(settings_factory: SettingsFactory) -> None:
    settings = settings_factory(
        LLM_PROVIDER="ollama",
        OLLAMA_BASE_URL=DUMMY_OLLAMA_URL,
        OLLAMA_MODEL_NAME=DUMMY_OLLAMA_MODEL,
        LOGFIRE_TOKEN=None,
    )

    assert settings.logfire_token is None
    # Explicitly check the field surfaces — Req 5.2 前段 ("Settings 自体は成立")
    # depends on this attribute existing and being None when the env var
    # is unset.
    assert hasattr(settings, "logfire_token")


def test_get_settings_is_cached(
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: SettingsFactory,  # used for env-clearing side-effect; clear cache below.
) -> None:
    """``get_settings`` returns a process-wide singleton (lru_cache).

    The factory fixture clears the env first; then we configure a happy
    path manually and assert two calls return the *same* object.
    """
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_BASE_URL", DUMMY_OLLAMA_URL)
    monkeypatch.setenv("OLLAMA_MODEL_NAME", DUMMY_OLLAMA_MODEL)

    get_settings.cache_clear()
    first = get_settings()
    second = get_settings()
    try:
        assert first is second
    finally:
        get_settings.cache_clear()
