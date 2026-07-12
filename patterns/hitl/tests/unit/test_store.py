"""Direct unit tests for the in-memory HITL session store (Task 5.2).

``patterns_hitl.harness.HitlHarness`` only ever calls :meth:`SessionStore.get`
on a session id it just resolved a moment earlier via :meth:`SessionStore.create`
or a prior :meth:`SessionStore.get`, so its own tests never exercise the
unknown-session-id error paths. Those paths are still part of
``SessionStore``'s own public contract (plan.md SessionStore -- a future
caller, e.g. 013's state-machine extension or ``app.py``'s 404 mapping,
depends on them raising rather than silently no-oping), so they are locked
here directly against the store instead.
"""

from __future__ import annotations

from pydantic_ai import RunUsage

from patterns_hitl.store import SessionRecord, SessionStore


def test_create_then_get_round_trips_the_stored_record() -> None:
    """A session created with a history and usage is retrievable unchanged."""
    store = SessionStore()
    usage = RunUsage(input_tokens=10, output_tokens=5, requests=1)

    session_id = store.create([], usage)
    record = store.get(session_id)

    assert record == SessionRecord(history=[], usage=usage)


def test_update_overwrites_the_stored_record() -> None:
    """update replaces a session's history and usage in place."""
    store = SessionStore()
    session_id = store.create([], RunUsage(requests=1))
    updated_usage = RunUsage(requests=2)

    store.update(session_id, [], updated_usage)

    assert store.get(session_id) == SessionRecord(history=[], usage=updated_usage)


def test_get_unknown_session_id_raises_key_error() -> None:
    """An unresolved session id raises KeyError -- app.py maps this to a 404 (R8.5)."""
    store = SessionStore()

    try:
        store.get("does-not-exist")
    except KeyError as exc:
        assert exc.args == ("does-not-exist",)
    else:
        raise AssertionError("expected KeyError")


def test_update_unknown_session_id_raises_key_error() -> None:
    """update on an unresolved session id raises KeyError rather than silently creating one."""
    store = SessionStore()

    try:
        store.update("does-not-exist", [], RunUsage())
    except KeyError as exc:
        assert exc.args == ("does-not-exist",)
    else:
        raise AssertionError("expected KeyError")
