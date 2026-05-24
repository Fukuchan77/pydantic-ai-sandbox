"""Unit tests for ``configure_observability`` (Task 7.1).

Locks plan.md §2.8 / Req 5.1, 5.2, 5.4:

* **Req 5.2** — calling ``configure_observability`` with ``LOGFIRE_TOKEN``
  unset MUST NOT raise; a single ``WARNING``-level log line MUST be
  emitted via the standard library logger so operators see the fail-soft
  transition.
* **Req 5.1** — the three ``logfire.instrument_*`` calls
  (``pydantic_ai`` / ``fastapi`` / ``httpx``) MUST all run on the success
  path. Mocking them at the module-level ``logfire`` binding inside
  ``logging_setup`` lets us assert call counts without standing up a real
  exporter.
* **Req 5.4** — the ``ScrubbingOptions`` handed to ``logfire.configure``
  MUST add ``prompt`` / ``tool_input`` / ``tool_output`` to the regex
  alphabet so the default INFO-level transport never carries raw
  user prompts or tool payloads.

The mock surface is intentionally narrow: only ``logfire.configure`` and
the three ``instrument_*`` entry points. Anything broader (e.g.
patching the whole module) would mask drift between our wrapper and
logfire's real signature, which is exactly the kind of regression Req
6.4 / Req 6.5 ask the suite to catch.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import logfire
import pytest
from fastapi import FastAPI

from pydantic_ai_sandbox.logging_setup import configure_observability

if TYPE_CHECKING:
    from tests.conftest import SettingsFactory


# Common minimal env that satisfies Settings without selecting any real
# provider transport. Hardcoding the model name keeps the Settings
# validator happy under LLM_PROVIDER=ollama; the actual provider value
# is irrelevant for these tests because we never run the agent.
_OLLAMA_BASE_ENV: dict[str, str] = {
    "LLM_PROVIDER": "ollama",
    "OLLAMA_MODEL_NAME": "dummy-ollama-model",
}


@pytest.fixture
def patched_logfire(monkeypatch: pytest.MonkeyPatch) -> dict[str, MagicMock]:
    """Replace logfire's configure + instrument_* entry points with mocks.

    Returns the dict of mocks keyed by attribute name so tests can read
    ``call_args`` / ``call_count`` directly. Patching at the
    ``pydantic_ai_sandbox.logging_setup.logfire`` namespace means any
    ``import logfire`` style usage inside the wrapper is captured (the
    module attribute is the live ``logfire`` package, so the mocks
    survive ``logfire.configure(...)`` calls without touching unrelated
    code paths).

    The :func:`logfire.configure` mock returns a ``MagicMock`` so the
    wrapper's chained ``logfire.configure(...).instrument_*`` would not
    explode if a future refactor adopted that style; current code calls
    them as module-level functions.
    """
    mocks = {
        "configure": MagicMock(return_value=MagicMock()),
        "instrument_pydantic_ai": MagicMock(),
        "instrument_fastapi": MagicMock(),
        "instrument_httpx": MagicMock(),
    }
    for name, mock in mocks.items():
        monkeypatch.setattr(f"pydantic_ai_sandbox.logging_setup.logfire.{name}", mock)
    return mocks


def test_configure_without_token_does_not_raise_and_emits_warning(
    settings_factory: SettingsFactory,
    patched_logfire: dict[str, MagicMock],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Req 5.2 — missing ``LOGFIRE_TOKEN`` is fail-soft + audible.

    The audibility half of Req 5.2 ("a one-line warning emitted via the
    configured logger") is asserted on the standard library logger's
    output via ``caplog`` rather than on any logfire-specific channel —
    operators routinely route stdlib logs to their own aggregator, and
    the spec explicitly says "the configured logger".
    """
    settings = settings_factory(**_OLLAMA_BASE_ENV)  # LOGFIRE_TOKEN omitted = None

    caplog.set_level(logging.WARNING, logger="pydantic_ai_sandbox.logging_setup")
    configure_observability(FastAPI(), settings)

    # Exactly one WARNING from our module (no spamming, no silence).
    module_warnings = [
        rec
        for rec in caplog.records
        if rec.name == "pydantic_ai_sandbox.logging_setup" and rec.levelno == logging.WARNING
    ]
    assert len(module_warnings) == 1, (
        f"expected exactly one fail-soft warning, got {len(module_warnings)}: "
        f"{[r.getMessage() for r in module_warnings]}"
    )
    assert "LOGFIRE_TOKEN" in module_warnings[0].getMessage(), (
        "warning must name the missing variable so operators can act on it"
    )


def test_configure_invokes_all_three_instrument_functions(
    settings_factory: SettingsFactory,
    patched_logfire: dict[str, MagicMock],
) -> None:
    """Req 5.1 — pydantic-ai + FastAPI + httpx instrumentation all run.

    Calling each ``instrument_*`` exactly once is the strict reading of
    Req 5.1 ("invoke ... during the FastAPI lifespan startup"). The
    ``instrument_fastapi`` mock additionally must receive the ``app``
    instance to wire HTTP-server spans, so we assert on that arg shape
    rather than just call count.
    """
    settings = settings_factory(**_OLLAMA_BASE_ENV, LOGFIRE_TOKEN="dummy-token")
    app = FastAPI()

    configure_observability(app, settings)

    assert patched_logfire["instrument_pydantic_ai"].call_count == 1
    assert patched_logfire["instrument_httpx"].call_count == 1
    assert patched_logfire["instrument_fastapi"].call_count == 1
    # ``instrument_fastapi`` takes the FastAPI app as a positional arg.
    fastapi_call = patched_logfire["instrument_fastapi"].call_args
    assert fastapi_call.args[0] is app, (
        "instrument_fastapi must receive the live FastAPI instance; "
        f"got args={fastapi_call.args!r} kwargs={fastapi_call.kwargs!r}"
    )


def test_configure_passes_scrubbing_extra_patterns(
    settings_factory: SettingsFactory,
    patched_logfire: dict[str, MagicMock],
) -> None:
    """Req 5.4 — prompt / tool_input / tool_output added to the scrubbing alphabet.

    The mock captures the keyword args handed to ``logfire.configure``;
    ``ScrubbingOptions.extra_patterns`` is a plain ``list[str]``, which
    we read directly. Asserting on a strict superset (``issuperset``)
    rather than equality leaves room for the wrapper to add more
    patterns later (e.g., ``api_key``) without re-baselining the test.
    """
    settings = settings_factory(**_OLLAMA_BASE_ENV, LOGFIRE_TOKEN="dummy-token")

    configure_observability(FastAPI(), settings)

    configure_call = patched_logfire["configure"].call_args
    scrubbing = configure_call.kwargs.get("scrubbing")
    assert isinstance(scrubbing, logfire.ScrubbingOptions), (
        f"scrubbing kwarg must be a ScrubbingOptions; got {type(scrubbing).__name__}"
    )
    extra = set(scrubbing.extra_patterns or [])
    required = {"prompt", "tool_input", "tool_output"}
    assert required.issubset(extra), (
        f"missing scrubbing patterns: required={required}, actual={extra}, diff={required - extra}"
    )
