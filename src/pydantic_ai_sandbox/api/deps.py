"""FastAPI ``Depends`` factories (plan.md §2.7 / T8.2 skeleton).

Currently exposes a single dependency, :func:`get_settings_dep`, that
hands the cached :class:`Settings` instance to route handlers. Keeping
the wrapper separate from :func:`pydantic_ai_sandbox.config.get_settings`
gives the route layer one stable seam for testing (``app.dependency_
overrides[get_settings_dep] = ...``) without touching the
:mod:`functools.lru_cache` directly.

T9.3 will add ``get_chat_agent_dep`` here; T10.2 will keep this module
unchanged. The boundary contract from plan.md §4.1 ("``Depends``
ファクトリ") owns this file, and only this file.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic_ai_sandbox.config import get_settings

if TYPE_CHECKING:
    from pydantic_ai_sandbox.config import Settings


def get_settings_dep() -> Settings:
    """Return the process-wide :class:`Settings` singleton for ``Depends``.

    Thin wrapper around :func:`pydantic_ai_sandbox.config.get_settings`
    that exists purely to give FastAPI a stable named dependency to
    introspect (``app.dependency_overrides`` keys on the function object).
    Calling :func:`get_settings` directly inside route handlers would work
    but would defeat per-test override hooks downstream tasks rely on.
    """
    return get_settings()
