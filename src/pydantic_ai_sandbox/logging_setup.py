"""Logfire bootstrap (plan.md §2.8 / Req 5.1, 5.2, 5.4, 5.5).

Single public entry point :func:`configure_observability` runs the
fail-soft Logfire init sequence:

1. Emit an explicit one-line ``WARNING`` when ``LOGFIRE_TOKEN`` is unset
   (Req 5.2). The standard library logger is the carrier so operators
   routing logs through their own aggregator see the transition without
   needing Logfire to be reachable.
2. Call :func:`logfire.configure` with
   ``send_to_logfire='if-token-present'`` (research.md R-2 — the
   officially-supported fail-soft API) and a scrubbing argument selected
   by ``settings.log_sensitive_payloads`` (Req 5.4 / plan.md §2.8 opt-in
   branch): the default-deny path passes :class:`logfire.ScrubbingOptions`
   extending the default redaction patterns with ``prompt`` /
   ``tool_input`` / ``tool_output``; the opt-in path passes ``False`` to
   disable redaction entirely AND emits a second ``WARNING`` naming the
   override so operators cannot accidentally leave it on in production.
3. Wire :func:`logfire.instrument_pydantic_ai`,
   :func:`logfire.instrument_fastapi`, and :func:`logfire.instrument_httpx`
   so every Pydantic-AI agent run, FastAPI request, and outbound HTTPX
   call shares the same trace surface (Req 5.1).

Any exception escaping the configure / instrument sequence is caught and
recorded as a single ``WARNING`` log line — the spec is explicit that
observability failures MUST NOT propagate to API responses (Req 5.5).
The bare ``Exception`` catch is intentional: the failure modes of the
Logfire transport are not enumerable in advance (network, OTel SDK,
auth, JSON encoding), and re-raising would defeat the entire
"observability is best-effort" contract.

Boundary: this module owns Logfire init only. Per-request span emission
is delegated to ``instrument_pydantic_ai`` (T6 owns the agent surface)
and ``instrument_fastapi`` (the route handlers stay framework-only).
T10.2 will call :func:`configure_observability` from the FastAPI
lifespan; this module deliberately does not register itself.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Literal

import logfire

if TYPE_CHECKING:
    from fastapi import FastAPI

    from pydantic_ai_sandbox.config import Settings

__all__ = ["configure_observability"]

logger = logging.getLogger(__name__)
"""Module-level stdlib logger.

The ``__name__`` discriminator (``pydantic_ai_sandbox.logging_setup``)
lets operators target our fail-soft messages with a per-module log-
level override without touching the wider ``pydantic_ai_sandbox``
namespace. ``tests/unit/test_logging_setup.py`` filters ``caplog``
records by exactly this name.
"""

_SCRUBBING_EXTRA_PATTERNS: tuple[str, ...] = ("prompt", "tool_input", "tool_output")
"""Regex stems added to Logfire's default scrubbing alphabet (Req 5.4).

Logfire matches each pattern case-insensitively against attribute
*keys*, so listing the bare nouns covers ``prompt``, ``user_prompt``,
``tool_input_payload``, etc. without needing per-call shaping. Default
Logfire patterns (``password``, ``api_key``, ...) remain in effect; this
tuple is additive."""


def configure_observability(app: FastAPI, settings: Settings) -> None:
    """Initialize Logfire + OpenTelemetry instrumentation, fail-soft.

    Args:
        app: The FastAPI application instance to instrument. Passed to
            :func:`logfire.instrument_fastapi` so HTTP server spans
            attach to the live router.
        settings: Active runtime configuration. ``settings.logfire_token``
            drives the ``send_to_logfire='if-token-present'`` decision;
            ``settings.app_env`` flows into Logfire's ``environment``
            tag so production / staging / dev traces stay separable.

    Returns:
        None. The function is intentionally side-effect-only — callers
        (notably the FastAPI lifespan in T10.2) treat a successful
        return as "do not block startup", regardless of whether Logfire
        actually came up.

    Notes:
        Req 5.2 (token unset → fail-soft + warning): a single
        ``WARNING`` is emitted before ``logfire.configure`` runs, so
        operators see the message even when the configure path itself
        succeeds quietly.

        Req 5.4 opt-in branch (plan.md §2.8): when
        ``settings.log_sensitive_payloads`` is ``True``, ``scrubbing=False``
        is handed to :func:`logfire.configure` (Logfire's documented
        sentinel for "disable redaction entirely") and a second
        ``WARNING`` naming the env var is emitted via the stdlib
        logger. Two warnings are intentional — one is the diagnostic
        breadcrumb and the other is the audit-trail that the operator
        explicitly opted into raw payload visibility.

        Req 5.5 (transport exceptions must not propagate): the
        configure + instrument sequence is wrapped in a single bare
        ``except Exception`` catch. ``BaseException`` (KeyboardInterrupt,
        SystemExit) is NOT caught — those still abort startup as the
        operator intended. The warning carries ``exc_info=True`` so the
        full traceback reaches log aggregators for diagnosis.
    """
    if not settings.logfire_token:
        logger.warning(
            "LOGFIRE_TOKEN is unset; Logfire transport disabled (fail-soft mode).",
        )

    # Req 5.4: scrubbing is default-on with extra patterns; the opt-in
    # branch hands Logfire its documented ``False`` sentinel to disable
    # redaction. The annotation widens the binding so pyright accepts
    # both paths under strict mode without an assignment-type narrowing.
    scrubbing_config: logfire.ScrubbingOptions | Literal[False]
    if settings.log_sensitive_payloads:
        logger.warning(
            "LOG_SENSITIVE_PAYLOADS=true; payload scrubbing is DISABLED. "
            "Raw prompts and tool I/O may flow to Logfire — keep this "
            "off in production unless you are actively debugging.",
        )
        scrubbing_config = False
    else:
        scrubbing_config = logfire.ScrubbingOptions(
            extra_patterns=list(_SCRUBBING_EXTRA_PATTERNS),
        )

    # Recover the raw secret only at the SDK boundary (``SecretStr`` keeps
    # the value redacted in repr/str everywhere else — see config.py
    # docstring). ``None`` propagates unchanged so the
    # ``send_to_logfire='if-token-present'`` fail-soft branch still fires.
    raw_token = (
        settings.logfire_token.get_secret_value() if settings.logfire_token is not None else None
    )

    try:
        logfire.configure(
            send_to_logfire="if-token-present",
            token=raw_token,
            service_name="pydantic_ai_sandbox",
            environment=settings.app_env,
            scrubbing=scrubbing_config,
        )
        logfire.instrument_pydantic_ai()
        logfire.instrument_fastapi(app)
        logfire.instrument_httpx()
    except Exception:  # noqa: BLE001 — Req 5.5: fail-soft, Logfire failures are not enumerable (see below)
        # Bare-Exception catch is the explicit fail-soft contract for
        # Req 5.5: Logfire transport failure modes are not enumerable in
        # advance (network, OTel SDK, auth, JSON encoding) and re-raising
        # would defeat the "observability is best-effort" guarantee. The
        # narrower BaseException remains uncaught, so KeyboardInterrupt /
        # SystemExit still abort startup as intended.
        logger.warning(
            "Logfire initialisation failed; continuing without observability.",
            exc_info=True,
        )
