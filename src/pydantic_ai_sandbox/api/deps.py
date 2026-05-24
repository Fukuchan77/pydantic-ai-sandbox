"""FastAPI ``Depends`` factories (plan.md §2.7 / §4.1).

Two dependencies are exposed:

* :func:`get_settings_dep` — hands the cached :class:`Settings` instance to
  route handlers. Keeping the wrapper separate from
  :func:`pydantic_ai_sandbox.config.get_settings` gives the route layer one
  stable seam for testing without reaching into the
  :mod:`functools.lru_cache` directly.
* :func:`get_chat_agent` — returns the process-wide :class:`Agent` singleton
  used by the ``POST /chat`` route. Caching at this seam (rather than
  rebuilding per request) is what makes ``agent.override(model=...)``
  observable to the route handler from the test layer: a fresh agent per
  request would discard the override the test entered before the request.

Boundary contract from plan.md §4.1: this file owns ``Depends`` factories
and only ``Depends`` factories. The chat route imports both functions; the
health route imports :func:`get_settings_dep` only. T10.2 may add
``get_observability_dep`` (or similar) here when the lifespan grows
observability handles, but for now the module surface is closed at these
two callables.
"""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING

from pydantic_ai_sandbox.agents.chat_agent import build_chat_agent
from pydantic_ai_sandbox.config import get_settings

if TYPE_CHECKING:
    from pydantic_ai import Agent

    from pydantic_ai_sandbox.config import Settings
    from pydantic_ai_sandbox.schemas.chat import ChatResponse


def get_settings_dep() -> Settings:
    """Return the process-wide :class:`Settings` singleton for ``Depends``.

    Thin wrapper around :func:`pydantic_ai_sandbox.config.get_settings`
    that exists purely to give FastAPI a stable named dependency to
    introspect (``app.dependency_overrides`` keys on the function object).
    Calling :func:`get_settings` directly inside route handlers would work
    but would defeat per-test override hooks downstream tasks rely on.
    """
    return get_settings()


@lru_cache(maxsize=1)
def get_chat_agent() -> Agent[None, ChatResponse]:
    """Return the process-wide chat :class:`Agent` singleton for ``Depends``.

    The agent is built once via :func:`build_chat_agent` and cached. Two
    properties matter:

    1. **Override visibility** — ``agent.override(model=...)`` mutates
       contextvars on the agent instance. If this dependency rebuilt the
       agent per request, an override entered by the test fixture before
       ``client.post(...)`` would land on a stale instance the route
       handler never sees. Caching makes the override flow naturally
       through ``Depends(get_chat_agent)`` resolution.

    2. **Lazy I/O** — :func:`build_chat_agent` calls
       :func:`pydantic_ai_sandbox.llm.get_model`, which constructs the
       model adapter without performing HTTP I/O (Req 2.6). Caching the
       result means we pay the (cheap) construction cost once per
       process, matching the framework's "build once, override many"
       testing recipe.

    Tests reset the cache via :meth:`get_chat_agent.cache_clear` between
    scenarios to pick up per-test :class:`Settings` overrides — see
    ``tests/conftest.py::app_with_overrides``.
    """
    return build_chat_agent()
