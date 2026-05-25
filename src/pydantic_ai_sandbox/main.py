"""FastAPI app factory (plan.md §2.9 / Req 1.3, 3.1, 4.5, 5.1).

Single public entry point :func:`create_app` composes the production
shape of the application:

1. Reads :class:`Settings` once via :func:`get_settings` (the cached
   singleton) inside the lifespan startup phase so env validation
   happens before any request is served (Req 1.4 / 4.5).
2. Calls :func:`configure_observability` to wire Logfire +
   OpenTelemetry instrumentation (Req 5.1). The call is fail-soft —
   Logfire transport errors are swallowed inside
   :mod:`pydantic_ai_sandbox.logging_setup` so observability problems
   never abort startup.
3. **Eagerly constructs the FallbackModel chain** when
   ``settings.llm_provider == "fallback"`` (Req 4.5 構成段). The return
   value is intentionally discarded — the dry-run validates
   *constructability* only; the per-request agent gets its model from
   :func:`pydantic_ai_sandbox.llm.get_model` via the cached
   ``Depends(get_chat_agent)``. An all-stub ``FALLBACK_ORDER`` raises
   :class:`RuntimeError` from :func:`_build_fallback`; we let it
   propagate so Starlette's ASGI lifespan turns it into a startup
   failure and ``TestClient.__enter__`` (or a real Uvicorn boot) aborts.
4. Registers the ``/healthz`` and ``/chat`` routers. Both routers are
   declared in :mod:`pydantic_ai_sandbox.api.routes` and carry no app-
   global state, so the registration is order-insensitive.

The module-level ``app = create_app()`` binding gives
``uvicorn pydantic_ai_sandbox.main:app`` (and any other ASGI runner) an
importable target. It is built once at import time; tests that need a
fresh app per scenario call :func:`create_app` directly (after
:func:`get_settings.cache_clear`) to side-step the singleton.

Boundary contract from plan.md §2.9: this module *composes* — it
contains no request-handling logic, no provider selection, and no
schema definitions. Each lifespan responsibility delegates to a single
component (config / logging_setup / llm.fallback / api.routes).
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from fastapi import FastAPI

from pydantic_ai_sandbox.api.routes.chat import router as chat_router
from pydantic_ai_sandbox.api.routes.health import router as health_router
from pydantic_ai_sandbox.config import get_settings
from pydantic_ai_sandbox.llm.fallback import (
    _build_fallback,  # pyright: ignore[reportPrivateUsage]
)
from pydantic_ai_sandbox.logging_setup import configure_observability

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Startup/shutdown hook running the boot-time validation chain.

    The startup phase performs three actions in fixed order:

    1. ``settings = get_settings()`` — fails fast with
       ``pydantic.ValidationError`` if env is malformed (Req 1.4 / 4.5
       構文段).
    2. ``configure_observability(app, settings)`` — fail-soft Logfire
       init + OTel instrumentation (Req 5.1, 5.2, 5.5).
    3. ``_build_fallback(settings)`` when
       ``settings.llm_provider == "fallback"`` — eager dry-run that
       raises ``RuntimeError`` for an all-stub ``FALLBACK_ORDER``
       (Req 4.5 構成段). The constructed ``FallbackModel`` is discarded
       because per-request agents resolve their model independently
       through :func:`pydantic_ai_sandbox.api.deps.get_chat_agent`.

    The shutdown phase is currently a no-op; the ``yield`` separates
    the two halves. Future work (background tasks, connection pools)
    would slot in after the ``yield``.
    """
    settings = get_settings()
    configure_observability(app, settings)
    if settings.llm_provider == "fallback":
        # Discard the return value: the per-request agent owns its own
        # model resolution via Depends(get_chat_agent). This call exists
        # solely so misconfigurations surface at boot (Req 4.5 構成段).
        _build_fallback(settings)
    yield


def create_app() -> FastAPI:
    """Construct the production FastAPI application.

    Returns a fully-wired :class:`FastAPI` instance with the lifespan
    composed in :func:`_lifespan` and both routers registered. Callers
    that exercise the lifespan (``mise run dev`` / ``uv run uvicorn
    pydantic_ai_sandbox.main:app``, ``with TestClient(app)``) get the
    boot-time validation chain; callers that bypass it
    (``TestClient(app)`` without ``with``) still receive a functional
    app — the routes themselves do not depend on lifespan side effects,
    by design.

    The function is deliberately small: every responsibility of any
    weight lives in a dedicated module (config / logging_setup /
    llm.fallback / api.routes) so plan.md §2.9's "compose only" rule
    holds. Adding a new route is a one-line ``include_router`` change;
    adding a new boot-time check is a one-line addition inside
    :func:`_lifespan`.
    """
    app = FastAPI(
        title="pydantic-ai-sandbox",
        version="0.1.0",
        lifespan=_lifespan,
    )
    app.include_router(health_router)
    app.include_router(chat_router)
    return app


app: FastAPI = create_app()
"""Module-level FastAPI binding for ``uvicorn pydantic_ai_sandbox.main:app``.

Built once at import time. Tests that need a fresh app per scenario
call :func:`create_app` directly (after :func:`get_settings.cache_clear`)
to side-step this singleton — see ``tests/unit/test_health.py`` and
``tests/unit/test_app_lifespan_fallback_dryrun.py``.
"""
