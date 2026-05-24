"""Unit tests for ``GET /healthz`` (Task 8.1).

Locks plan.md §2.7 / Req 1.3:

* the route returns HTTP 200 with at minimum
  ``{"status": "ok", "provider": <settings.llm_provider>}``;
* the ``provider`` field is sourced from the live ``Settings`` singleton,
  so flipping ``LLM_PROVIDER`` flips the response without code changes.

Both behaviours are exercised through ``fastapi.testclient.TestClient``
against ``create_app()`` (T8.2 surface) so the test simultaneously locks
the route's wiring (router included, ``Depends(get_settings_dep)`` reachable).

The helper :func:`_build_client` clears ``get_settings`` lru_cache before
constructing the app so the per-test env overrides reach the route — without
the clear, FastAPI's ``Depends`` would receive the cached singleton from a
prior test and the ``provider`` field would not move.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from pydantic_ai_sandbox.config import get_settings
from pydantic_ai_sandbox.main import create_app

if TYPE_CHECKING:
    from tests.conftest import SettingsFactory


def _build_client(settings_factory: SettingsFactory, **env: str | None) -> TestClient:
    """Apply env via ``settings_factory`` and return a fresh TestClient.

    The factory both validates the Settings (so tests fail fast on bad env
    combinations) and seats env vars via ``monkeypatch`` for the lifetime of
    the calling test. Clearing ``get_settings`` before ``create_app()`` makes
    the route's ``Depends`` chain pick up the per-test env rather than a
    stale singleton.
    """
    settings_factory(**env)
    get_settings.cache_clear()
    return TestClient(create_app())


def test_healthz_returns_status_ok_and_provider_ollama(
    settings_factory: SettingsFactory,
) -> None:
    """Default Ollama path returns the canonical health payload.

    Req 1.3 fixes the minimal shape ``{"status": "ok", "provider": ...}``;
    asserting on equality (not subset) here keeps the route honest about
    not silently widening the contract to extra keys before a spec
    amendment.
    """
    client = _build_client(
        settings_factory,
        LLM_PROVIDER="ollama",
        OLLAMA_MODEL_NAME="dummy-ollama-model",
    )

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "provider": "ollama"}


@pytest.mark.parametrize(
    ("provider_env", "extra_env", "expected_provider"),
    [
        pytest.param(
            "ollama",
            {"OLLAMA_MODEL_NAME": "dummy-ollama-model"},
            "ollama",
            id="ollama",
        ),
        pytest.param(
            "fallback",
            {
                "OLLAMA_MODEL_NAME": "dummy-ollama-model",
                "FALLBACK_ORDER": "ollama",
            },
            "fallback",
            id="fallback",
        ),
    ],
)
def test_healthz_provider_field_tracks_settings(
    settings_factory: SettingsFactory,
    provider_env: str,
    extra_env: dict[str, str],
    expected_provider: str,
) -> None:
    """Switching ``LLM_PROVIDER`` flips the response field with no code change.

    Drives the env-driven contract from plan.md §2.7: the route reads
    ``settings.llm_provider`` rather than a baked-in constant, so any future
    addition to the ``LLMProvider`` Literal that forgets to update the route
    surfaces here as a parametrise miss in Pyright (literal narrowing) plus
    a runtime mismatch.
    """
    client = _build_client(
        settings_factory,
        LLM_PROVIDER=provider_env,
        **extra_env,
    )

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json()["provider"] == expected_provider
