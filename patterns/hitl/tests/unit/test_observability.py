"""Failing tests for fail-soft observability bootstrap (Task 6.1(b)).

Locks R9.1 before ``patterns_hitl.observability`` exists (plan.md
Observability): this lane's ``pyproject.toml`` deliberately declares bare
``logfire`` rather than ``logfire[fastapi]``, so
``logfire.instrument_fastapi()`` has no ``opentelemetry-instrumentation-
fastapi`` package to call into and raises. In that environment --
combined with no ``LOGFIRE_TOKEN`` -- ``enable_observability`` must
swallow the failure and return ``False`` rather than raise, and
``create_app(..., instrument=True)`` must still boot and serve requests
normally.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic_ai.models.function import FunctionModel

from patterns_hitl.agent import build_agent
from patterns_hitl.app import create_app
from patterns_hitl.observability import enable_observability
from tests.support.function_model_scripts import call_counting_script, final_result_call

if TYPE_CHECKING:
    import pytest


def test_enable_observability_returns_false_without_raising_when_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No Logfire token + no fastapi instrumentor -> fail-soft False, never raises."""
    monkeypatch.delenv("LOGFIRE_TOKEN", raising=False)

    result = enable_observability(FastAPI())

    assert result is False


def test_create_app_with_instrumentation_enabled_still_boots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """instrument=True must not block startup when observability init fails (R9.1)."""
    monkeypatch.delenv("LOGFIRE_TOKEN", raising=False)
    agent = build_agent(FunctionModel(call_counting_script(final_result_call())))
    app = create_app(agent=agent, instrument=True)

    with TestClient(app) as client:
        response = client.post("/run", json={"prompt": "Summarize the duplicate charge."})

    assert response.status_code == 200


def test_enable_observability_without_an_app_returns_true(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no app to instrument, only configure + instrument_pydantic_ai run and succeed."""
    monkeypatch.delenv("LOGFIRE_TOKEN", raising=False)

    result = enable_observability()

    assert result is True
