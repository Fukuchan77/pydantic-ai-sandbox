"""Failing tests for the session consumption state machine (Task 1.1b/2.1, spec 013 R1.2/R1.3/R2.1-2.4).

Two layers in one file:

* Store-layer coverage (Task 1, above) -- ``SessionStore.claim`` /
  ``settle_pending`` / ``consume`` / ``release`` drive the state machine
  directly, with no HTTP involved.
* API-layer coverage (Task 2.1, below) -- drives the same state machine
  through ``POST /run`` / ``POST /resume`` via ``TestClient`` and asserts
  the HTTP status mapping (404 / 409 / 429) that ``app.py`` (Task 2.2)
  implements on top of the store methods above.

The state machine (plan.md SessionLifecycle, research.md AD-2):

* ``claim()`` succeeds only from ``pending`` and synchronously transitions
  to ``in_flight`` -- unknown, ``in_flight``, and ``consumed`` ids all
  raise the *same* :class:`UnknownSessionError` with no information
  distinguishing which case occurred (existence secrecy, R1.2). The
  synchronous transition is what makes a second concurrent ``claim()``
  lose to the first (R2.1 concurrency note, plan.md H-1).
* ``settle_pending()`` returns an ``in_flight`` session to ``pending`` with
  a *replaced* ``pending_call_ids`` set -- the previous round's tool call
  ids are no longer valid after a re-defer (R2.2).
* ``release()`` returns an ``in_flight`` session to ``pending`` without
  touching ``pending_call_ids``, used by the 409 (pending-set-violation)
  path so the session stays resumable without any tool having run (R2.3).
* ``consume()`` ends a session permanently; nothing can claim it again
  (R2.1).

The API-layer cases below (Task 2.1) are RED against the current
``app.py``/``harness.py`` for a specific reason each:

(a) the current ``/resume`` 404 body is
    ``detail=f"unknown session_id: {exc.args[0]}"`` (``app.py:202``), which
    leaks both the session id and the word "unknown" -- R1.2 violation.
(b) ``app.py`` has no pending-set check at all yet -- any decision dict is
    forwarded straight to the harness.
(c)/(d) ``HitlBudgetExceededError`` is only caught by ``/resume``'s
    ``except KeyError`` block, which does not match it -- both routes
    currently surface it as an unhandled 500.
(e) depends on (b)'s pending-set check existing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient
from pydantic_ai import RunUsage, UsageLimits
from pydantic_ai.models.function import FunctionModel

from patterns_hitl.agent import build_agent
from patterns_hitl.app import create_app
from patterns_hitl.harness import HitlHarness, TerminalResult
from patterns_hitl.store import SessionStore, UnknownSessionError
from tests.support.function_model_scripts import (
    apply_discount_call,
    call_counting_script,
    escalate_to_legal_call,
    final_result_call,
)

if TYPE_CHECKING:
    from fastapi import FastAPI
    from pydantic_ai import ModelMessage, ModelResponse, ToolCallPart
    from pydantic_ai.models.function import AgentInfo


def test_claim_unknown_session_raises_unknown_session_error() -> None:
    """An id that was never created raises UnknownSessionError (R1.2)."""
    store = SessionStore()

    with pytest.raises(UnknownSessionError):
        store.claim("does-not-exist")


def test_claim_synchronously_transitions_pending_to_in_flight() -> None:
    """A successful claim on a pending session returns an in_flight record (R2.1)."""
    store = SessionStore()
    session_id = store.create([], RunUsage(), pending_call_ids=frozenset({"call-1"}))

    record = store.claim(session_id)

    assert record.state == "in_flight"
    assert record.pending_call_ids == frozenset({"call-1"})


def test_second_concurrent_claim_raises_the_same_error_as_unknown() -> None:
    """The first claim wins; a second claim on the now-in_flight session raises the same error as an unknown id (R2.1, H-1)."""
    store = SessionStore()
    session_id = store.create([], RunUsage(), pending_call_ids=frozenset({"call-1"}))
    store.claim(session_id)

    with pytest.raises(UnknownSessionError):
        store.claim(session_id)


def test_claim_after_consume_raises_the_same_error_as_unknown() -> None:
    """A terminated (consumed) session cannot be claimed again -- same error, no distinguishing detail (R1.2, R2.1)."""
    store = SessionStore()
    session_id = store.create([], RunUsage())
    store.claim(session_id)
    store.consume(session_id)

    with pytest.raises(UnknownSessionError):
        store.claim(session_id)


def test_settle_pending_returns_in_flight_to_pending_and_replaces_the_call_id_set() -> None:
    """A re-defer moves in_flight back to pending with the new round's pending_call_ids (R2.2)."""
    store = SessionStore()
    session_id = store.create([], RunUsage(), pending_call_ids=frozenset({"call-1"}))
    store.claim(session_id)

    store.settle_pending(
        session_id, history=[], usage=RunUsage(), pending_call_ids=frozenset({"call-2"})
    )
    record = store.claim(session_id)  # pending again -> claimable

    assert record.pending_call_ids == frozenset({"call-2"})


def test_settle_pending_invalidates_the_previous_rounds_call_ids() -> None:
    """The prior round's tool_call_id is not silently carried over into the new pending set (R2.2)."""
    store = SessionStore()
    session_id = store.create([], RunUsage(), pending_call_ids=frozenset({"call-1"}))
    store.claim(session_id)

    store.settle_pending(
        session_id, history=[], usage=RunUsage(), pending_call_ids=frozenset({"call-2"})
    )
    record = store.get(session_id)

    assert "call-1" not in record.pending_call_ids


def test_release_restores_in_flight_to_pending_without_touching_pending_call_ids() -> None:
    """release() undoes a claim (409 path) -- the session stays resumable, no tool has run (R2.3)."""
    store = SessionStore()
    session_id = store.create([], RunUsage(), pending_call_ids=frozenset({"call-1"}))
    store.claim(session_id)

    store.release(session_id)
    record = store.claim(session_id)  # re-claimable after release

    assert record.state == "in_flight"
    assert record.pending_call_ids == frozenset({"call-1"})


def test_consume_ends_the_session_permanently() -> None:
    """Once consumed, a session cannot be claimed again -- it is not resumable (R2.1)."""
    store = SessionStore()
    session_id = store.create([], RunUsage())
    store.claim(session_id)

    store.consume(session_id)

    with pytest.raises(UnknownSessionError):
        store.claim(session_id)


async def test_start_consumes_the_session_when_the_run_completes_terminally() -> None:
    """A /run that finishes with no pending approval leaves no claimable session behind.

    ``harness.resume`` already consumes on a terminal outcome (R2.1); ``harness.start``
    must be symmetric so a prompt that never touches an approval-gated tool does not
    leave a permanently-``pending``, indefinitely-claimable record in the store.
    """
    agent = build_agent(FunctionModel(call_counting_script(final_result_call())))
    store = SessionStore()
    harness = HitlHarness(agent, store)

    result = await harness.start("Just answer directly, no discount needed.")

    assert isinstance(result, TerminalResult)
    with pytest.raises(UnknownSessionError):
        store.claim(result.session_id)


# --- API layer (Task 2.1): HTTP status mapping over /run + /resume ---------


def _build_app(*phases: ToolCallPart, usage_limits: UsageLimits | None = None) -> FastAPI:
    """Build a hermetic app wired to a call-counting FunctionModel + a fresh store.

    Mirrors ``test_api.py``'s helper of the same name, plus an optional
    ``usage_limits`` seam (Task 2.1(c)/(d)) so a test can inject a budget
    tight enough to force ``HitlBudgetExceededError`` deterministically.
    """
    agent = build_agent(FunctionModel(call_counting_script(*phases)))
    if usage_limits is None:
        return create_app(agent=agent, store=SessionStore(), instrument=False)
    return create_app(
        agent=agent, store=SessionStore(), instrument=False, usage_limits=usage_limits
    )


def test_resume_after_terminal_completion_returns_404_and_leaks_nothing() -> None:
    """(a) A second /resume on a now-consumed session is 404 with a fixed, non-identifying body."""
    app = _build_app(
        apply_discount_call(amount_usd=100.0),
        final_result_call(requires_human_approval=True),
    )

    with TestClient(app) as client:
        pending = client.post("/run", json={"prompt": "Apply a $100 discount."}).json()
        session_id = pending["session_id"]
        tool_call_id = pending["approvals"][0]["tool_call_id"]

        first_resume = client.post(
            "/resume",
            json={"session_id": session_id, "decisions": {tool_call_id: {"approved": True}}},
        )
        assert first_resume.status_code == 200
        assert first_resume.json()["status"] == "completed"

        second_resume = client.post(
            "/resume",
            json={"session_id": session_id, "decisions": {tool_call_id: {"approved": True}}},
        )

    assert second_resume.status_code == 404
    detail = second_resume.json()["detail"].lower()
    assert session_id not in detail
    assert "unknown" not in detail
    assert "expired" not in detail
    assert "consumed" not in detail


def test_resume_with_unknown_session_id_returns_the_same_404_body_as_consumed() -> None:
    """An id that was never issued gets the identical fixed body a consumed session gets (R1.2)."""
    app = _build_app(final_result_call())

    with TestClient(app) as client:
        response = client.post(
            "/resume",
            json={"session_id": "does-not-exist", "decisions": {"whatever": {"approved": True}}},
        )

    assert response.status_code == 404
    detail = response.json()["detail"].lower()
    assert "does-not-exist" not in detail
    assert "unknown" not in detail


def test_resume_with_decision_outside_pending_set_returns_409_and_runs_no_tool() -> None:
    """(b) A decision for a tool_call_id the session never proposed is 409; the model never runs again."""
    calls = {"n": 0}
    script = call_counting_script(apply_discount_call(amount_usd=100.0), final_result_call())

    def spying_script(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        calls["n"] += 1
        return script(messages, info)

    agent = build_agent(FunctionModel(spying_script))
    app = create_app(agent=agent, store=SessionStore(), instrument=False)

    with TestClient(app) as client:
        pending = client.post("/run", json={"prompt": "Apply a $100 discount."}).json()
        session_id = pending["session_id"]
        calls_after_run = calls["n"]

        response = client.post(
            "/resume",
            json={
                "session_id": session_id,
                "decisions": {"not-a-real-call-id": {"approved": True}},
            },
        )

    assert response.status_code == 409
    assert calls["n"] == calls_after_run


def test_resume_with_one_bad_key_among_valid_ones_rejects_the_whole_request() -> None:
    """(b) Even one out-of-set tool_call_id rejects the entire decisions dict, not just that key."""
    app = _build_app(apply_discount_call(amount_usd=100.0), final_result_call())

    with TestClient(app) as client:
        pending = client.post("/run", json={"prompt": "Apply a $100 discount."}).json()
        session_id = pending["session_id"]
        real_tool_call_id = pending["approvals"][0]["tool_call_id"]

        response = client.post(
            "/resume",
            json={
                "session_id": session_id,
                "decisions": {
                    real_tool_call_id: {"approved": True},
                    "not-a-real-call-id": {"approved": True},
                },
            },
        )

    assert response.status_code == 409


def test_resume_after_409_leaves_the_session_pending_and_resumable() -> None:
    """(b) After a 409, the session is released back to pending and a correct decision still resolves it."""
    app = _build_app(apply_discount_call(amount_usd=100.0), final_result_call())

    with TestClient(app) as client:
        pending = client.post("/run", json={"prompt": "Apply a $100 discount."}).json()
        session_id = pending["session_id"]
        real_tool_call_id = pending["approvals"][0]["tool_call_id"]

        rejected = client.post(
            "/resume",
            json={
                "session_id": session_id,
                "decisions": {"not-a-real-call-id": {"approved": True}},
            },
        )
        assert rejected.status_code == 409

        recovered = client.post(
            "/resume",
            json={"session_id": session_id, "decisions": {real_tool_call_id: {"approved": True}}},
        )

    assert recovered.status_code == 200
    assert recovered.json()["status"] == "completed"


def test_resume_over_budget_returns_429_and_invalidates_the_session() -> None:
    """(c) A tight budget hit during /resume is 429; the session is then 404 on any further /resume."""
    tight_limits = UsageLimits(request_limit=8, tool_calls_limit=10, total_tokens_limit=80)
    app = _build_app(
        apply_discount_call(amount_usd=100.0), final_result_call(), usage_limits=tight_limits
    )

    with TestClient(app) as client:
        pending = client.post("/run", json={"prompt": "Apply a $100 discount."}).json()
        session_id = pending["session_id"]
        tool_call_id = pending["approvals"][0]["tool_call_id"]

        over_budget = client.post(
            "/resume",
            json={"session_id": session_id, "decisions": {tool_call_id: {"approved": True}}},
        )
        assert over_budget.status_code == 429

        after = client.post(
            "/resume",
            json={"session_id": session_id, "decisions": {tool_call_id: {"approved": True}}},
        )

    assert after.status_code == 404


def test_run_over_budget_returns_429_and_saves_no_session() -> None:
    """(d) A budget too tight for the very first /run request is 429; no session is left behind."""
    minimal_limits = UsageLimits(request_limit=8, tool_calls_limit=10, total_tokens_limit=1)
    app = _build_app(
        apply_discount_call(amount_usd=100.0), final_result_call(), usage_limits=minimal_limits
    )

    with TestClient(app) as client:
        response = client.post("/run", json={"prompt": "Apply a $100 discount."})
        assert response.status_code == 429

        follow_up = client.post(
            "/resume",
            json={
                "session_id": "whatever-id-a-client-might-guess",
                "decisions": {"whatever": {"approved": True}},
            },
        )

    assert follow_up.status_code == 404


def test_resume_after_re_defer_rejects_the_stale_tool_call_id_with_409() -> None:
    """(e) After a re-defer, the previous round's tool_call_id is no longer valid -- 409, not re-applied."""
    app = _build_app(
        apply_discount_call(amount_usd=100.0),
        escalate_to_legal_call(),
        final_result_call(requires_human_approval=True),
    )

    with TestClient(app) as client:
        first = client.post(
            "/run", json={"prompt": "Apply a $100 discount, escalate if needed."}
        ).json()
        session_id = first["session_id"]
        first_tool_call_id = first["approvals"][0]["tool_call_id"]

        second = client.post(
            "/resume",
            json={"session_id": session_id, "decisions": {first_tool_call_id: {"approved": True}}},
        ).json()
        assert second["status"] == "pending_approval"

        stale_replay = client.post(
            "/resume",
            json={"session_id": session_id, "decisions": {first_tool_call_id: {"approved": True}}},
        )

    assert stale_replay.status_code == 409
