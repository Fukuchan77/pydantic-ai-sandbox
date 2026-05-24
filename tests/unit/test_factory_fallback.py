"""Unit tests for ``_build_fallback`` (Task 5.2).

Locks the contract from plan.md §2.4 and tasks.md T5.4:

* A ``FALLBACK_ORDER`` containing at least one real provider returns a
  ``FallbackModel`` instance — proves the env-driven member resolver is
  wired through ``get_model`` recursion (Req 4.1 / 4.2).
* A ``FALLBACK_ORDER`` whose every member is in ``_MVP_STUB_PROVIDERS``
  raises :class:`RuntimeError` at build time so the misconfiguration
  fails fast at app startup rather than at the first ``/chat`` call
  (Req 4.5 構成段). plan.md §2.4 names this the "all-stub" guard.
* Settings-level rejections (empty ``FALLBACK_ORDER`` / wholly unknown
  provider names) do **not** appear here: the
  ``Settings._check_provider_constraints`` validator runs first and
  raises ``pydantic.ValidationError`` before ``_build_fallback`` is ever
  invoked. Those cases are covered by ``tests/unit/test_config.py``;
  asserting them again here would test pydantic-settings, not
  ``_build_fallback``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from pydantic_ai.models.fallback import FallbackModel

from pydantic_ai_sandbox.config import get_settings
from pydantic_ai_sandbox.llm.fallback import (
    # Spec-mandated underscore-prefixed name (plan.md §2.4) exported via
    # ``llm.fallback.__all__``; mirrors the ``_MVP_STUB_PROVIDERS`` import
    # convention used by ``tests/unit/test_factory_dispatch.py``.
    _build_fallback,  # pyright: ignore[reportPrivateUsage]
)

if TYPE_CHECKING:
    from tests.conftest import SettingsFactory


# Mirrors the dummy values used by the T4 dispatch tests so the
# hardcoded-model-ID guard (T2.1) keeps treating this module as clean.
DUMMY_OLLAMA_MODEL = "dummy-ollama-model"
DUMMY_OLLAMA_URL = "http://localhost:11434"


def test_build_fallback_with_single_real_member_returns_fallback_model(
    settings_factory: SettingsFactory,
) -> None:
    """A single-member ``FALLBACK_ORDER`` produces a ``FallbackModel``.

    The MVP only ships one real provider (Ollama), so this minimal
    composition is the load-bearing happy-path: it proves the parser
    splits comma-separated names correctly (here: a degenerate one-item
    list) and that ``get_model("ollama")`` is recursively reachable from
    inside ``_build_fallback`` without re-entering the ``"fallback"``
    dispatch branch.
    """
    settings = settings_factory(
        LLM_PROVIDER="fallback",
        FALLBACK_ORDER="ollama",
        OLLAMA_BASE_URL=DUMMY_OLLAMA_URL,
        OLLAMA_MODEL_NAME=DUMMY_OLLAMA_MODEL,
    )
    get_settings.cache_clear()
    try:
        model = _build_fallback(settings)
    finally:
        get_settings.cache_clear()

    assert isinstance(model, FallbackModel)


def test_build_fallback_with_only_stub_members_raises_runtime_error(
    settings_factory: SettingsFactory,
) -> None:
    """All-stub configurations fail fast at build time (Req 4.5).

    ``watsonx`` and ``anthropic`` are both members of
    ``_MVP_STUB_PROVIDERS``. plan.md §2.4 mandates that ``_build_fallback``
    detect this configuration and raise ``RuntimeError`` instead of
    deferring the ``NotImplementedError`` until the first ``/chat`` call.
    The error message names the offending construct so the operator can
    locate the env var responsible.
    """
    settings = settings_factory(
        LLM_PROVIDER="fallback",
        FALLBACK_ORDER="watsonx,anthropic",
    )
    get_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError) as exc_info:
            _build_fallback(settings)
    finally:
        get_settings.cache_clear()

    msg = str(exc_info.value)
    # The message must mention FALLBACK_ORDER so the operator can grep
    # logs for the var name; the wording is asserted loosely so future
    # rephrasing does not break the test, but the env-var token is
    # load-bearing.
    assert "FALLBACK_ORDER" in msg


def test_build_fallback_skips_stub_members_when_real_members_remain(
    settings_factory: SettingsFactory,
) -> None:
    """Mixed configurations build successfully, ignoring stub members.

    plan.md §2.4 frames the all-stub case as the only build-time fail.
    A user staging a 002-multi-provider rollout (e.g.
    ``FALLBACK_ORDER=ollama,watsonx``) would otherwise hit the watsonx
    stub's ``NotImplementedError`` during recursive ``get_model`` calls
    — the implementation must therefore filter stubs out *before*
    iterating, leaving the FallbackModel chain populated with the real
    providers in their original order.
    """
    settings = settings_factory(
        LLM_PROVIDER="fallback",
        FALLBACK_ORDER="ollama,watsonx",
        OLLAMA_BASE_URL=DUMMY_OLLAMA_URL,
        OLLAMA_MODEL_NAME=DUMMY_OLLAMA_MODEL,
    )
    get_settings.cache_clear()
    try:
        model = _build_fallback(settings)
    finally:
        get_settings.cache_clear()

    assert isinstance(model, FallbackModel)
