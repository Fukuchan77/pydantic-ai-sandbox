"""``GET /healthz`` route (plan.md §2.7 / Req 1.3).

Returns ``{"status": "ok", "provider": <settings.llm_provider>}`` with
HTTP 200. The provider field is sourced from :class:`Settings` via the
:func:`get_settings_dep` ``Depends`` factory so flipping ``LLM_PROVIDER``
flips the response with no code change — an explicit Req 1.3 requirement
exercised by ``tests/unit/test_health.py``.

Boundary rules from plan.md §2.7:

* the handler does not touch ``ModelFactory`` or any agent — health
  must not depend on a reachable LLM backend (Ollama may be down while
  the API is up);
* the response shape is intentionally narrow (just ``status`` and
  ``provider``); operational metrics belong elsewhere.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends

from pydantic_ai_sandbox.api.deps import get_settings_dep

if TYPE_CHECKING:
    from pydantic_ai_sandbox.config import Settings

router = APIRouter()


@router.get("/healthz")
def get_healthz(
    settings: Settings = Depends(get_settings_dep),  # noqa: B008 — FastAPI Depends idiom.
) -> dict[str, str]:
    """Return a static liveness payload tagged with the active provider.

    The handler is sync because no I/O is performed; the response is
    derived entirely from in-memory :class:`Settings`. Returning a plain
    ``dict`` lets FastAPI fall back to its default JSON encoder without
    spawning a Pydantic model just to carry two strings.
    """
    return {"status": "ok", "provider": settings.llm_provider}
