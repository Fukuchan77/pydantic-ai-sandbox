"""Tests for ``create_app()`` lifespan fallback dry-run (Task 10.1).

Locks plan.md §2.9 / Req 4.5: when ``LLM_PROVIDER=fallback`` is selected
the FastAPI lifespan must construct the fallback chain eagerly so a
misconfigured deployment fails at boot rather than at the first
``/chat`` request. Three branches matter:

1. ``FALLBACK_ORDER=anthropic,bedrock`` — every member is in
   ``_MVP_STUB_PROVIDERS``. ``_build_fallback`` raises ``RuntimeError``;
   the lifespan must propagate it so ``with TestClient(app)`` aborts at
   startup and no request traffic ever sees a half-built chain.
2. ``FALLBACK_ORDER=ollama`` — the chain is buildable; startup completes
   and the request phase becomes reachable. ``GET /healthz`` is the
   smallest live-route assertion that proves the lifespan yielded.
3. ``LLM_PROVIDER=ollama`` — the lifespan must skip ``_build_fallback``
   entirely. Constructing it would be wasted work and would couple an
   Ollama-only deployment to ``FALLBACK_ORDER`` semantics.

The ``with TestClient(...)`` pattern is load-bearing here: Starlette
runs the lifespan only when the TestClient is entered as a context
manager. Plain ``TestClient(app)`` (used by ``tests/unit/test_health.py``)
bypasses lifespan, which is why those tests do not exercise this
contract — and why the new tests cannot piggy-back on the existing
helper.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from pydantic_ai_sandbox.config import get_settings
from pydantic_ai_sandbox.main import create_app

if TYPE_CHECKING:
    from tests.conftest import SettingsFactory


def test_lifespan_fails_fast_when_fallback_order_is_all_stub(
    settings_factory: SettingsFactory,
) -> None:
    """All-stub ``FALLBACK_ORDER`` aborts startup before requests flow.

    Req 4.5 構成段 mandates that ``LLM_PROVIDER=fallback`` with every
    member in ``_MVP_STUB_PROVIDERS`` raises at boot, not at the first
    ``/chat`` call. Entering ``with TestClient(app)`` triggers the
    lifespan startup phase; the propagated ``RuntimeError`` surfaces
    from ``__enter__`` and the inner ``pass`` body never executes.

    The error message must mention ``FALLBACK_ORDER`` so operators can
    grep logs for the offending env var (mirrored from the
    ``test_factory_fallback`` contract).

    Uses ``anthropic,bedrock`` — the providers that remain stubs after
    002-watsonx-provider promotes watsonx — so the all-stub scenario does
    not trip the new watsonx credential gate (config Task 2.2).
    """
    settings_factory(
        LLM_PROVIDER="fallback",
        FALLBACK_ORDER="anthropic,bedrock",
    )
    get_settings.cache_clear()

    app = create_app()
    with pytest.raises(RuntimeError) as exc_info, TestClient(app):
        pass  # pragma: no cover — startup must abort before this line.

    assert "FALLBACK_ORDER" in str(exc_info.value)


def test_lifespan_succeeds_for_fallback_with_real_member(
    settings_factory: SettingsFactory,
) -> None:
    """``FALLBACK_ORDER=ollama`` lets the lifespan complete cleanly.

    With at least one real provider in the chain ``_build_fallback``
    returns a ``FallbackModel``; the lifespan discards the return value
    (the spec is explicit that the dry-run validates *constructability*
    only) and yields control to the request phase. ``/healthz`` is the
    smallest reachable route that proves startup actually finished —
    asserting on ``provider == "fallback"`` doubles as a regression
    guard against a future refactor that hard-coded the response.
    """
    settings_factory(
        LLM_PROVIDER="fallback",
        FALLBACK_ORDER="ollama",
        OLLAMA_MODEL_NAME="dummy-ollama-model",
    )
    get_settings.cache_clear()

    app = create_app()
    with TestClient(app) as client:
        response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json()["provider"] == "fallback"


def test_lifespan_skips_build_fallback_when_provider_is_ollama(
    settings_factory: SettingsFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ollama-only deployments must not pay the fallback dry-run cost.

    The lifespan branches on ``settings.llm_provider == "fallback"``;
    with ``LLM_PROVIDER=ollama`` the dry-run is skipped entirely.
    Patching the *imported reference* on
    :mod:`pydantic_ai_sandbox.main` (not the source module) is the
    standard pytest-monkeypatch idiom for call-count spying — it leaves
    other tests' use of ``_build_fallback`` untouched and surfaces the
    branch decision as a single integer assertion.
    """
    settings_factory(
        LLM_PROVIDER="ollama",
        OLLAMA_MODEL_NAME="dummy-ollama-model",
    )
    get_settings.cache_clear()

    spy = MagicMock(name="_build_fallback_spy")
    monkeypatch.setattr("pydantic_ai_sandbox.main._build_fallback", spy)

    app = create_app()
    with TestClient(app) as client:
        response = client.get("/healthz")

    assert response.status_code == 200
    assert spy.call_count == 0
