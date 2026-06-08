"""Unit tests for ``pydantic_ai_sandbox.llm.factory.get_model`` (Task 4.1).

Locks the dispatch contract from plan.md §2.2 / §2.3:

* ``get_model("ollama")`` returns a ``pydantic_ai.models.Model`` subclass
  instance — type assertion only, no I/O verification (T4.2 covers that).
* ``get_model("watsonx" | "anthropic" | "bedrock")`` raises
  :class:`NotImplementedError` whose message names the provider and
  points at the ``002-multi-provider`` follow-up spec so operators
  hitting this in production know where the work is tracked.
* ``get_model("unknown")`` raises :class:`ValueError` (Req 2.5 enforcement
  point — Settings-level validation is the front line; this is the
  defence-in-depth layer for callers that bypass Settings).
* ``get_model()`` with no argument consults
  ``Settings.llm_provider``; the test re-points the singleton at a
  watsonx-selected ``Settings`` and asserts the watsonx stub branch
  fires.

The factory's ``"fallback"`` branch is intentionally **not** tested here;
T5.4 lands the real wiring and adds its own coverage.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from pydantic_ai.models import Model

from pydantic_ai_sandbox.config import get_settings
from pydantic_ai_sandbox.llm import get_model
from pydantic_ai_sandbox.llm.factory import (
    # ``_MVP_STUB_PROVIDERS`` is spec-mandated underscore-prefixed naming
    # (plan.md §2.4) but listed in ``llm.factory.__all__`` as the module's
    # public surface; the suppression acknowledges that the test crosses
    # the module boundary by design.
    _MVP_STUB_PROVIDERS,  # pyright: ignore[reportPrivateUsage]
)

if TYPE_CHECKING:
    from tests.conftest import SettingsFactory


# Mirrors the constants in tests/unit/test_config.py — chosen to stay
# outside FORBIDDEN_MODEL_ID_LITERALS so the hardcoded-model-ID guard
# (T2.1) keeps treating this module as clean.
DUMMY_OLLAMA_MODEL = "dummy-ollama-model"
DUMMY_OLLAMA_URL = "http://localhost:11434"


def _seat_ollama_settings(settings_factory: SettingsFactory) -> None:
    """Build a happy-path Ollama Settings and seat it as the singleton.

    ``get_model`` reads through ``get_settings()``; tests therefore
    populate the lru_cache with a deterministic instance and clear it on
    teardown via ``finally`` blocks in the calling test.
    """
    settings_factory(
        LLM_PROVIDER="ollama",
        OLLAMA_BASE_URL=DUMMY_OLLAMA_URL,
        OLLAMA_MODEL_NAME=DUMMY_OLLAMA_MODEL,
    )
    get_settings.cache_clear()


def test_get_model_ollama_returns_pydantic_ai_model(
    settings_factory: SettingsFactory,
) -> None:
    _seat_ollama_settings(settings_factory)
    try:
        model = get_model("ollama")
    finally:
        get_settings.cache_clear()

    # The contract is "anything that satisfies the Model ABC". We do not
    # assert on the concrete class so the underlying Pydantic AI
    # implementation can evolve (e.g. OpenAIChatModel → renamed) without
    # breaking the dispatch test — the V2 surface test (T6.2) is the
    # place that pins the concrete API symbol.
    assert isinstance(model, Model)


@pytest.mark.parametrize("stub_provider", sorted(_MVP_STUB_PROVIDERS))
def test_get_model_stub_providers_raise_with_followup_hint(
    settings_factory: SettingsFactory,
    stub_provider: str,
) -> None:
    _seat_ollama_settings(settings_factory)
    try:
        with pytest.raises(NotImplementedError) as exc_info:
            get_model(stub_provider)
    finally:
        get_settings.cache_clear()

    msg = str(exc_info.value)
    # The provider name MUST be in the error so an operator reading a
    # production stack trace can tell which env var to flip.
    assert stub_provider in msg
    # The follow-up spec hint MUST be in the error so the reader knows
    # this is a tracked omission, not a bug — Req 2.4 wording.
    assert "002-multi-provider" in msg


def test_get_model_unknown_provider_raises_value_error(
    settings_factory: SettingsFactory,
) -> None:
    _seat_ollama_settings(settings_factory)
    try:
        with pytest.raises(ValueError, match="not-a-provider"):
            get_model("not-a-provider")
    finally:
        get_settings.cache_clear()


def test_get_model_no_arg_consults_settings_llm_provider(
    settings_factory: SettingsFactory,
) -> None:
    """``get_model()`` with no argument routes through ``Settings.llm_provider``.

    We seat a watsonx-selected Settings — supplying the four watsonx
    credentials now required by the boot-time gate (config Task 2.2) — and
    expect the watsonx stub branch to fire (watsonx is still a member of
    ``_MVP_STUB_PROVIDERS`` until Task 4.2), proving the dispatch reads
    ``Settings.llm_provider`` rather than defaulting to a hardcoded
    provider. Task 4.3 rewrites this case to assert a real Model instance.
    """
    settings_factory(
        LLM_PROVIDER="watsonx",
        WATSONX_APIKEY="k-watsonx-dispatch-secret",
        WATSONX_PROJECT_ID="proj-0000",
        WATSONX_URL="https://us-south.ml.cloud.ibm.com",
        WATSONX_MODEL_ID="dummy-watsonx-model",
    )
    get_settings.cache_clear()
    try:
        with pytest.raises(NotImplementedError) as exc_info:
            get_model()
    finally:
        get_settings.cache_clear()

    assert "watsonx" in str(exc_info.value)


def test_mvp_stub_providers_constant_matches_plan() -> None:
    """Lock the stub-provider alphabet so silent additions cannot slip.

    plan.md §2.4 names the constant ``_MVP_STUB_PROVIDERS`` and requires
    it to expose exactly ``{"watsonx", "anthropic", "bedrock"}``. T5.4
    (``_build_fallback``) reads the same constant to detect "all-stub"
    fallback compositions; drift here would silently break that guard.
    """
    expected = frozenset({"watsonx", "anthropic", "bedrock"})
    assert expected == _MVP_STUB_PROVIDERS
