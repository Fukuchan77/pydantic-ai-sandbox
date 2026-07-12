"""Tests for the approval audit trail (Task 3.1/3.2, spec 013 R3.1-3.5).

Drives ``POST /resume`` with an injected :class:`~tests.support.in_memory_audit.InMemoryAuditEmitter`
so every assertion below is against real emitted events, with zero real
exporter I/O (R3.5):

* (a)/(b) approve / deny paths each emit exactly one event carrying
  ``session_id`` / ``tool_call_id`` / ``tool_name`` / ``decision`` /
  ``denial_message`` / ``timestamp`` (R3.1).
* (c) an override decision's event exposes only the overridden *keys*,
  never the raw values (R3.2, R3.3) -- covered both through a full
  ``/resume`` round trip and directly against the pure mapping function.
* (d) an emitter that always raises never fails or blocks the resume
  (R3.4).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi.testclient import TestClient
from pydantic_ai.models.function import FunctionModel

from patterns_hitl.agent import build_agent
from patterns_hitl.app import create_app
from patterns_hitl.audit import build_audit_event
from patterns_hitl.store import SessionStore
from tests.support.function_model_scripts import (
    apply_discount_call,
    call_counting_script,
    final_result_call,
)
from tests.support.in_memory_audit import InMemoryAuditEmitter, RaisingAuditEmitter

if TYPE_CHECKING:
    from fastapi import FastAPI
    from pydantic_ai import ToolCallPart

    from patterns_hitl.audit import AuditEmitter


def _build_app(*phases: ToolCallPart, audit_emitter: AuditEmitter) -> FastAPI:
    """Build a hermetic app wired to a call-counting FunctionModel + the given audit emitter."""
    agent = build_agent(FunctionModel(call_counting_script(*phases)))
    return create_app(
        agent=agent, store=SessionStore(), instrument=False, audit_emitter=audit_emitter
    )


def test_approve_decision_emits_one_event_with_the_expected_fields() -> None:
    """(a)/(b) A plain approve decision emits exactly one event carrying the required fields."""
    emitter = InMemoryAuditEmitter()
    app = _build_app(
        apply_discount_call(amount_usd=100.0), final_result_call(), audit_emitter=emitter
    )

    with TestClient(app) as client:
        pending = client.post("/run", json={"prompt": "Apply a $100 discount."}).json()
        session_id = pending["session_id"]
        tool_call_id = pending["approvals"][0]["tool_call_id"]

        response = client.post(
            "/resume",
            json={"session_id": session_id, "decisions": {tool_call_id: {"approved": True}}},
        )

    assert response.status_code == 200
    assert len(emitter.events) == 1
    event = emitter.events[0]
    assert event.session_id == session_id
    assert event.tool_call_id == tool_call_id
    assert event.tool_name == "apply_discount"
    assert event.decision == "approved"
    assert event.denial_message is None
    assert event.overridden_keys == ()
    assert event.timestamp is not None


def test_deny_decision_emits_one_event_with_the_denial_message() -> None:
    """(a) A deny decision emits exactly one event, carrying the denial message."""
    emitter = InMemoryAuditEmitter()
    app = _build_app(
        apply_discount_call(amount_usd=100.0), final_result_call(), audit_emitter=emitter
    )

    with TestClient(app) as client:
        pending = client.post("/run", json={"prompt": "Apply a $100 discount."}).json()
        session_id = pending["session_id"]
        tool_call_id = pending["approvals"][0]["tool_call_id"]

        response = client.post(
            "/resume",
            json={
                "session_id": session_id,
                "decisions": {tool_call_id: {"approved": False, "message": "not authorized"}},
            },
        )

    assert response.status_code == 200
    assert len(emitter.events) == 1
    event = emitter.events[0]
    assert event.decision == "denied"
    assert event.denial_message == "not authorized"


def test_override_decision_records_only_the_overridden_keys() -> None:
    """(c) An override decision's audit event exposes overridden_keys but never the raw values."""
    emitter = InMemoryAuditEmitter()
    app = _build_app(
        apply_discount_call(amount_usd=100.0), final_result_call(), audit_emitter=emitter
    )

    with TestClient(app) as client:
        pending = client.post("/run", json={"prompt": "Apply a $100 discount."}).json()
        session_id = pending["session_id"]
        tool_call_id = pending["approvals"][0]["tool_call_id"]

        response = client.post(
            "/resume",
            json={
                "session_id": session_id,
                "decisions": {
                    tool_call_id: {
                        "approved": True,
                        "override_args": {"target_id": "cust-9", "amount_usd": 12345.0},
                    }
                },
            },
        )

    assert response.status_code == 200
    assert len(emitter.events) == 1
    event = emitter.events[0]
    assert event.decision == "approved_with_override"
    assert event.overridden_keys == ("target_id", "amount_usd")
    serialized = event.model_dump_json()
    assert "cust-9" not in serialized
    assert "12345.0" not in serialized


def test_build_audit_event_never_carries_raw_override_values() -> None:
    """(c) The pure mapping function masks raw override values regardless of key names."""
    event = build_audit_event(
        session_id="sess-1",
        tool_call_id="call-1",
        tool_name="apply_discount",
        approved=True,
        override_args={"amount_usd": 98765.0, "reason": "confidential-override-reason"},
    )

    assert event.overridden_keys == ("amount_usd", "reason")
    serialized = event.model_dump_json()
    assert "98765.0" not in serialized
    assert "confidential-override-reason" not in serialized


def test_failing_emitter_does_not_fail_the_resume() -> None:
    """(d) An emitter that always raises never blocks or fails /resume (R3.4)."""
    app = _build_app(
        apply_discount_call(amount_usd=100.0),
        final_result_call(),
        audit_emitter=RaisingAuditEmitter(),
    )

    with TestClient(app) as client:
        pending = client.post("/run", json={"prompt": "Apply a $100 discount."}).json()
        session_id = pending["session_id"]
        tool_call_id = pending["approvals"][0]["tool_call_id"]

        response = client.post(
            "/resume",
            json={"session_id": session_id, "decisions": {tool_call_id: {"approved": True}}},
        )

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
