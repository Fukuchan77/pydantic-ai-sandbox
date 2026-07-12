"""Failing tests for the HITL FastAPI app-factory (Task 6.1(a)).

Locks the HTTP contract before ``patterns_hitl.app`` exists (plan.md
HitlApp):

* ``POST /run`` with a prompt the agent answers directly returns
  ``{"status": "completed", "output": SupportOutput}`` (R8.1).
* ``POST /run`` with a prompt that hits an approval-gated tool call
  returns ``{"status": "pending_approval", "session_id", "approvals"}``
  (R8.2).
* ``POST /resume`` with an approval decision resumes the stopped run to a
  terminal ``SupportOutput`` (R8.3).
* ``POST /resume`` with a denial decision resumes the stopped run to an
  alternative terminal ``SupportOutput`` -- the tool never runs (R5.3).
* ``POST /resume`` against an unknown ``session_id`` returns ``404``
  (R8.5).
* ``POST /resume`` with a ``Decision`` that violates the
  ``approved``/``message``/``override_args`` mutual exclusivity returns
  ``422`` (plan.md Error Handling & Edge Cases).

Every test injects a ``FunctionModel``-scripted agent (via
``tests.support.function_model_scripts``, the same scripts Task 5.1
verified against the harness directly) and a fresh ``SessionStore()``
through ``create_app``'s DI seam, with ``instrument=False`` -- the
observability bootstrap itself is Task 6.1(b)'s concern
(``test_observability.py``), not this file's.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi.testclient import TestClient
from pydantic_ai.models.function import FunctionModel

from patterns_hitl.agent import build_agent
from patterns_hitl.app import create_app
from patterns_hitl.store import SessionStore
from tests.support.function_model_scripts import (
    apply_discount_call,
    call_counting_script,
    escalate_to_legal_call,
    final_result_call,
)

if TYPE_CHECKING:
    from fastapi import FastAPI
    from pydantic_ai import ToolCallPart


def _build_app(*phases: ToolCallPart) -> FastAPI:
    """Build a hermetic app wired to a call-counting FunctionModel + a fresh store."""
    agent = build_agent(FunctionModel(call_counting_script(*phases)))
    return create_app(agent=agent, store=SessionStore(), instrument=False)


def test_run_completes_directly_when_no_tool_needs_approval() -> None:
    """POST /run returns a completed SupportOutput when the model never defers."""
    app = _build_app(final_result_call())

    with TestClient(app) as client:
        response = client.post("/run", json={"prompt": "Summarize the duplicate charge."})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["output"]["requires_human_approval"] is False


def test_run_returns_pending_approval_for_a_gated_tool_call() -> None:
    """POST /run stops with a pending_approval payload when a tool call is gated."""
    app = _build_app(apply_discount_call(amount_usd=100.0), final_result_call())

    with TestClient(app) as client:
        response = client.post("/run", json={"prompt": "Apply a $100 discount."})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "pending_approval"
    assert body["session_id"]
    approvals = body["approvals"]
    assert len(approvals) == 1
    assert approvals[0]["tool_name"] == "apply_discount"
    assert approvals[0]["args"] == {"target_id": "cust-1", "amount_usd": 100.0}
    assert approvals[0]["tool_call_id"]


def test_resume_with_approval_completes_to_terminal_output() -> None:
    """POST /resume with an approval decision resumes through to a completed SupportOutput."""
    app = _build_app(
        apply_discount_call(amount_usd=100.0),
        final_result_call(requires_human_approval=True),
    )

    with TestClient(app) as client:
        pending = client.post("/run", json={"prompt": "Apply a $100 discount."}).json()
        tool_call_id = pending["approvals"][0]["tool_call_id"]

        response = client.post(
            "/resume",
            json={
                "session_id": pending["session_id"],
                "decisions": {tool_call_id: {"approved": True}},
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["output"]["requires_human_approval"] is True


def test_resume_with_denial_completes_with_an_alternative_output() -> None:
    """POST /resume with a denial decision never runs the tool but still terminates."""
    app = _build_app(
        apply_discount_call(amount_usd=100.0),
        final_result_call(requires_human_approval=False),
    )

    with TestClient(app) as client:
        pending = client.post("/run", json={"prompt": "Apply a $100 discount."}).json()
        tool_call_id = pending["approvals"][0]["tool_call_id"]

        response = client.post(
            "/resume",
            json={
                "session_id": pending["session_id"],
                "decisions": {
                    tool_call_id: {"approved": False, "message": "policy: amount too large"}
                },
            },
        )

    assert response.status_code == 200
    assert response.json()["status"] == "completed"


def test_resume_with_bare_denial_and_no_message_still_completes() -> None:
    """A denial with no message maps to a bare ToolDenied() -- the tool still never runs."""
    app = _build_app(
        apply_discount_call(amount_usd=100.0),
        final_result_call(requires_human_approval=False),
    )

    with TestClient(app) as client:
        pending = client.post("/run", json={"prompt": "Apply a $100 discount."}).json()
        tool_call_id = pending["approvals"][0]["tool_call_id"]

        response = client.post(
            "/resume",
            json={
                "session_id": pending["session_id"],
                "decisions": {tool_call_id: {"approved": False}},
            },
        )

    assert response.status_code == 200
    assert response.json()["status"] == "completed"


def test_resume_can_re_defer_a_second_pending_approval() -> None:
    """Approving the first pending call can surface a second pending_approval (R6.1)."""
    app = _build_app(
        apply_discount_call(amount_usd=100.0),
        escalate_to_legal_call(),
        final_result_call(requires_human_approval=True),
    )

    with TestClient(app) as client:
        first = client.post(
            "/run", json={"prompt": "Apply a $100 discount, escalate if needed."}
        ).json()
        first_tool_call_id = first["approvals"][0]["tool_call_id"]

        response = client.post(
            "/resume",
            json={
                "session_id": first["session_id"],
                "decisions": {first_tool_call_id: {"approved": True}},
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "pending_approval"
    assert body["session_id"] == first["session_id"]
    assert body["approvals"][0]["tool_name"] == "escalate_to_legal"


def test_resume_unknown_session_id_returns_404() -> None:
    """POST /resume against a session id the store never issued returns 404 (R8.5)."""
    app = _build_app(final_result_call())

    with TestClient(app) as client:
        response = client.post("/resume", json={"session_id": "does-not-exist", "decisions": {}})

    assert response.status_code == 404


def test_resume_decision_approved_with_message_is_rejected_as_422() -> None:
    """approved=True + message violates the Decision mutual exclusivity (plan.md Error Handling)."""
    app = _build_app(final_result_call())

    with TestClient(app) as client:
        response = client.post(
            "/resume",
            json={
                "session_id": "irrelevant",
                "decisions": {"call-1": {"approved": True, "message": "not allowed together"}},
            },
        )

    assert response.status_code == 422


def test_resume_decision_denied_with_override_args_is_rejected_as_422() -> None:
    """approved=False + override_args also violates the Decision mutual exclusivity."""
    app = _build_app(final_result_call())

    with TestClient(app) as client:
        response = client.post(
            "/resume",
            json={
                "session_id": "irrelevant",
                "decisions": {"call-1": {"approved": False, "override_args": {"amount_usd": 1.0}}},
            },
        )

    assert response.status_code == 422
