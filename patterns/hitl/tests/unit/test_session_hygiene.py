"""Failing tests for session id hygiene (Task 1.1a, spec 013 R1.1/R1.3).

``SessionStore`` generates ids inline today (``str(uuid4())`` in
:meth:`SessionStore.create`, store.py:60). Spec 013 requires that
generation be centralized behind a single ``new_session_id()`` function so
there is exactly one place that can be audited for CSPRNG use (R1.1), and
that two sessions created from identical input still get distinct,
non-sequential ids (R1.3) -- neither a counter nor a timestamp, which a
``uuid4()`` value is not.
"""

from __future__ import annotations

from uuid import UUID

from pydantic_ai import RunUsage

from patterns_hitl.store import SessionStore, new_session_id


def test_new_session_id_returns_a_random_uuid4() -> None:
    """new_session_id centralizes id generation on CSPRNG uuid4 (R1.1)."""
    session_id = new_session_id()

    assert UUID(session_id).version == 4


def test_new_session_id_called_twice_yields_different_ids() -> None:
    """Two calls in the same process are unrelated -- not a counter or timestamp (R1.3)."""
    first = new_session_id()
    second = new_session_id()

    assert first != second
    assert UUID(first).version == 4
    assert UUID(second).version == 4


def test_create_from_identical_input_yields_different_session_ids() -> None:
    """Two sessions created from the same history/usage (same prompt) still diverge (R1.3)."""
    store = SessionStore()
    usage = RunUsage(requests=1)

    first = store.create([], usage)
    second = store.create([], usage)

    assert first != second
    assert UUID(first).version == 4
    assert UUID(second).version == 4
