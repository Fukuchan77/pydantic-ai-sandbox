"""Resilience tests for ``configure_observability`` (Task 7.2 / Req 5.5).

Req 5.5: "IF Logfire transport raises a transient error during request
processing THEN the request SHALL still complete; observability failures
SHALL NOT propagate to the API response."

We model "Logfire transport raises" by forcing :func:`logfire.configure`
to raise during startup-equivalent setup, then assert that:

1. :func:`configure_observability` swallows the exception (does not
   re-raise) so a future T10.2 lifespan can call it without aborting
   app startup.
2. ``GET /healthz`` continues to return HTTP 200 through a TestClient.

T8.2's ``create_app`` skeleton uses a no-op lifespan today, so the test
explicitly invokes ``configure_observability`` on the freshly built app
to mirror the wiring T10.2 will eventually make implicit. This keeps
the resilience contract observable from inside Task 7's scope without
prematurely binding T10.2's lifespan changes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi.testclient import TestClient

from pydantic_ai_sandbox.config import get_settings
from pydantic_ai_sandbox.logging_setup import configure_observability
from pydantic_ai_sandbox.main import create_app

if TYPE_CHECKING:
    import pytest

    from tests.conftest import SettingsFactory


def _raise_runtime_error(**_kwargs: object) -> None:
    """Stand-in for a broken :func:`logfire.configure`.

    Module-level so it pickles cleanly if pytest's xdist plugin ever
    needs to ship the test to a worker. The double-underscore arg names
    silence ARG-style ruff rules that would otherwise complain about
    unused parameters here.
    """
    msg = "simulated logfire transport failure (T7.2 resilience probe)"
    raise RuntimeError(msg)


def test_healthz_succeeds_when_logfire_configure_raises(
    settings_factory: SettingsFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``/healthz`` keeps returning 200 even when ``logfire.configure`` blows up.

    The patch target is the ``logfire`` attribute on
    :mod:`pydantic_ai_sandbox.logging_setup`, not the global
    ``logfire`` package. ``import logfire`` inside the wrapper binds the
    same module object, so attribute-level ``setattr`` reaches the call
    site without leaking the patch into unrelated tests (monkeypatch
    restores after teardown).

    The test calls :func:`configure_observability` *after* building the
    app rather than wiring it into the lifespan, because T8.2's
    skeleton lifespan is intentionally a no-op. The contract proven
    here ("calling the wrapper does not abort the surrounding code")
    is the same one T10.2 will compose into ``app.lifespan`` later.
    """
    settings = settings_factory(
        LLM_PROVIDER="ollama",
        OLLAMA_MODEL_NAME="dummy-ollama-model",
        LOGFIRE_TOKEN="dummy-token",
    )
    monkeypatch.setattr(
        "pydantic_ai_sandbox.logging_setup.logfire.configure",
        _raise_runtime_error,
    )
    get_settings.cache_clear()

    app = create_app()
    # The act under test: this MUST NOT propagate the RuntimeError.
    configure_observability(app, settings)

    client = TestClient(app)
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
