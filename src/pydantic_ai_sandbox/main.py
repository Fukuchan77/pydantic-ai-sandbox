"""FastAPI app factory skeleton (plan.md §2.9 / T8.2).

This is the **bootstrap-stage** ``create_app`` — it registers routes only
and uses a no-op lifespan, deliberately deferring observability wiring
and fallback dry-run construction to T10.2. Splitting the surface in
two keeps the T7 / T8 TDD cycle independent of T10's responsibilities;
T7.2 (logging resilience) reaches into :func:`configure_observability`
explicitly rather than relying on the lifespan to call it, so the
boundary contract here stays minimal.

The ``app`` module-level binding is exposed so ``fastapi dev
app/main.py`` and ``fastapi run app/main.py`` work without code
changes when T10.2 enriches the lifespan.
"""

from __future__ import annotations

from fastapi import FastAPI

from pydantic_ai_sandbox.api.routes.health import router as health_router


def create_app() -> FastAPI:
    """Construct the FastAPI application with the minimum route set.

    The skeleton:

    1. Instantiates a bare :class:`FastAPI` (default no-op lifespan);
    2. Registers the ``/healthz`` router;
    3. Returns the instance for callers (TestClient, ``fastapi dev``,
       and the full ``main:app`` binding once T10.2 wires the lifespan).

    Settings are not loaded eagerly here — they flow into route handlers
    via :func:`pydantic_ai_sandbox.api.deps.get_settings_dep` so the
    process-wide :func:`get_settings` cache stays the single seat of
    env validation. T10.2 will add lifespan logic that pre-loads
    settings + observability + fallback dry-run on top of this skeleton.
    """
    app = FastAPI(title="pydantic-ai-sandbox", version="0.1.0")
    app.include_router(health_router)
    return app


app: FastAPI = create_app()
"""Module-level FastAPI binding for ``fastapi dev``/``fastapi run``.

Built once at import time. Tests that need a fresh app per scenario call
:func:`create_app` directly (after :func:`get_settings.cache_clear`) to
side-step this singleton — see ``tests/unit/test_health.py``.
"""
