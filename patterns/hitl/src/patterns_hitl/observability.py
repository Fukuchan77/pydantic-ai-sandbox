"""Fail-soft Logfire observability bootstrap for the HITL lane (Task 6.2, R9.1).

Mirrors the root app's ``pydantic_ai_sandbox.logging_setup.configure_observability``
fail-soft contract, scaled down to this lane's single public entry point:
any exception escaping ``logfire.configure`` / ``instrument_pydantic_ai`` /
``instrument_fastapi`` must never abort app startup (plan.md Observability /
Error Handling & Edge Cases -- "観測性初期化失敗 -> 起動継続"). The bare
``Exception`` catch below is intentional for the same reason as the root
app's: Logfire transport failure modes are not enumerable in advance.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import logfire

if TYPE_CHECKING:
    from fastapi import FastAPI

__all__ = ["enable_observability"]


def enable_observability(app: FastAPI | None = None) -> bool:
    """Initialize Logfire instrumentation, fail-soft (R9.1).

    Args:
        app: The FastAPI application to instrument via
            ``logfire.instrument_fastapi``. When ``None``, only the
            Pydantic-AI instrumentation is wired -- callers that do not
            yet have an app instance (or that only care about agent
            spans) can skip the FastAPI leg entirely.

    Returns:
        ``True`` if the full configure + instrument sequence completed;
        ``False`` if any step raised. Callers must treat a ``False``
        return as "continue without observability", never as a reason to
        abort startup.
    """
    try:
        logfire.configure(send_to_logfire="if-token-present")
        logfire.instrument_pydantic_ai()
        if app is not None:
            logfire.instrument_fastapi(app)
    except Exception:  # noqa: BLE001 - fail-soft bootstrap: Logfire transport/instrumentor failure modes are not enumerable in advance (R9.1)
        return False
    return True
