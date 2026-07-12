"""Failing tests for the session consumption state machine (Task 1.1b, spec 013 R1.2/R1.3/R2.1/R2.2/R2.3).

Store-layer coverage only (Task 1) -- ``SessionStore.claim`` /
``settle_pending`` / ``consume`` / ``release`` do not exist yet on
``patterns_hitl.store``. Task 2 extends this same file with API-layer
(``TestClient``) cases for the HTTP status mapping; this file's scope stays
at the store boundary.

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
"""

from __future__ import annotations

import pytest
from pydantic_ai import RunUsage

from patterns_hitl.store import SessionStore, UnknownSessionError


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
