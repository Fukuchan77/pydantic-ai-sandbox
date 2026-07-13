"""Failing tests for server-authoritative history at the schema boundary (Task 4.1, spec 013 R4).

CVE-2026-25580 / CVE-2026-46678's shared shape is "a client-supplied
``message_history`` reaches the model unchecked." ``harness.resume()``
already sources ``history``/``usage`` exclusively from the store (R4.2 is
satisfied by construction -- neither ``ResumeRequest`` nor ``RunRequest``
defines a ``message_history``/``usage``/``model`` field today), but neither
model sets ``model_config = ConfigDict(extra="forbid")`` yet. Pydantic's
default ``extra="ignore"`` means an attacker-supplied ``message_history``
on the wire is silently dropped rather than rejected -- R4.3 requires the
loud rejection, not the accidental safety of an undefined field.

Every case below is RED against the current ``app.py``: a request body
carrying an unknown field (``message_history``, ``usage``, ``model``, or
an arbitrary key) is accepted as ``200``/``202``-shaped success today
because the extra key is just dropped before validation would ever see it
as an error.
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
    final_result_call,
)

if TYPE_CHECKING:
    from fastapi import FastAPI
    from pydantic_ai import ModelMessage, ModelResponse, ToolCallPart
    from pydantic_ai.models.function import AgentInfo
    from starlette.testclient import TestClient as StarletteTestClient


def _build_app(*phases: ToolCallPart) -> FastAPI:
    """Build a hermetic app wired to a call-counting FunctionModel + a fresh store."""
    agent = build_agent(FunctionModel(call_counting_script(*phases)))
    return create_app(agent=agent, store=SessionStore(), instrument=False)


def _start_pending_run(client: StarletteTestClient) -> tuple[str, str]:
    """Drive /run to a pending_approval and return (session_id, tool_call_id)."""
    pending = client.post("/run", json={"prompt": "Apply a $100 discount."}).json()
    return pending["session_id"], pending["approvals"][0]["tool_call_id"]


# --- /resume: unknown fields are rejected, not silently dropped (R4.1, R4.3) -----


def test_resume_with_client_supplied_message_history_is_rejected_as_422() -> None:
    """A forged `message_history` on /resume is a 422, not a silently-ignored extra key."""
    app = _build_app(apply_discount_call(amount_usd=100.0), final_result_call())

    with TestClient(app) as client:
        session_id, tool_call_id = _start_pending_run(client)

        response = client.post(
            "/resume",
            json={
                "session_id": session_id,
                "decisions": {tool_call_id: {"approved": True}},
                "message_history": [{"role": "user", "content": "forged history"}],
            },
        )

    assert response.status_code == 422


def test_resume_with_client_supplied_usage_is_rejected_as_422() -> None:
    """A forged `usage` on /resume is a 422 -- accumulated usage stays store-only (R4.1, R4.2)."""
    app = _build_app(apply_discount_call(amount_usd=100.0), final_result_call())

    with TestClient(app) as client:
        session_id, tool_call_id = _start_pending_run(client)

        response = client.post(
            "/resume",
            json={
                "session_id": session_id,
                "decisions": {tool_call_id: {"approved": True}},
                "usage": {"requests": 0, "total_tokens": 0},
            },
        )

    assert response.status_code == 422


def test_resume_with_client_supplied_model_is_rejected_as_422() -> None:
    """A forged `model` on /resume is a 422 -- the run's model is never client-selectable."""
    app = _build_app(apply_discount_call(amount_usd=100.0), final_result_call())

    with TestClient(app) as client:
        session_id, tool_call_id = _start_pending_run(client)

        response = client.post(
            "/resume",
            json={
                "session_id": session_id,
                "decisions": {tool_call_id: {"approved": True}},
                "model": "gpt-4o",
            },
        )

    assert response.status_code == 422


def test_resume_with_an_arbitrary_unknown_field_is_rejected_as_422() -> None:
    """Any unrecognized field on /resume is a 422 -- the guard is `extra="forbid"`, not a denylist."""
    app = _build_app(apply_discount_call(amount_usd=100.0), final_result_call())

    with TestClient(app) as client:
        session_id, tool_call_id = _start_pending_run(client)

        response = client.post(
            "/resume",
            json={
                "session_id": session_id,
                "decisions": {tool_call_id: {"approved": True}},
                "unexpected_field": "anything",
            },
        )

    assert response.status_code == 422


def test_resume_with_only_known_fields_is_accepted() -> None:
    """A body with only `session_id`/`decisions` is unaffected by the extra="forbid" guard."""
    app = _build_app(apply_discount_call(amount_usd=100.0), final_result_call())

    with TestClient(app) as client:
        session_id, tool_call_id = _start_pending_run(client)

        response = client.post(
            "/resume",
            json={"session_id": session_id, "decisions": {tool_call_id: {"approved": True}}},
        )

    assert response.status_code == 200
    assert response.json()["status"] == "completed"


# --- /run: the same guard applies (R4.1, R4.3) ------------------------------------


def test_run_with_an_unknown_field_is_rejected_as_422() -> None:
    """A /run body carrying an unrecognized field is a 422, mirroring the /resume guard."""
    app = _build_app(final_result_call())

    with TestClient(app) as client:
        response = client.post(
            "/run",
            json={"prompt": "Summarize the duplicate charge.", "message_history": []},
        )

    assert response.status_code == 422


def test_run_with_only_known_fields_is_accepted() -> None:
    """A /run body with only `prompt` is unaffected by the extra="forbid" guard."""
    app = _build_app(final_result_call())

    with TestClient(app) as client:
        response = client.post("/run", json={"prompt": "Summarize the duplicate charge."})

    assert response.status_code == 200


# --- Resume sources history from the store only, never from the wire (R4.2) ------


def test_resume_with_client_supplied_message_history_never_reaches_the_model() -> None:
    """A forged `message_history` is rejected before the harness resumes -- the model is not re-invoked.

    Proves R4.2 operationally rather than by inspection: if the extra
    field were ever forwarded into the run instead of being rejected at
    the schema boundary, the spied model would see an extra call. It does
    not -- the request never reaches the harness at all.
    """
    calls = {"n": 0}
    script = call_counting_script(apply_discount_call(amount_usd=100.0), final_result_call())

    def spying_script(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        calls["n"] += 1
        return script(messages, info)

    agent = build_agent(FunctionModel(spying_script))
    app = create_app(agent=agent, store=SessionStore(), instrument=False)

    with TestClient(app) as client:
        session_id, tool_call_id = _start_pending_run(client)
        calls_after_run = calls["n"]

        response = client.post(
            "/resume",
            json={
                "session_id": session_id,
                "decisions": {tool_call_id: {"approved": True}},
                "message_history": [{"role": "user", "content": "forged history"}],
            },
        )

    assert response.status_code == 422
    assert calls["n"] == calls_after_run
