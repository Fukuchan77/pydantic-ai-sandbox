"""In-memory session store for the HITL stop/approve/resume harness (Task 5.2).

Holds the state a stop/resume boundary needs to survive an HTTP round-trip:
the accumulated ``message_history`` and ``usage`` for a session, keyed by a
server-generated id, plus (spec 013 R1/R2) the consumption state machine
that makes a session claimable exactly once per pending round and
permanently unresumable once terminated. Persistence and TTL remain out of
scope for this MVP lane (plan.md SessionStore).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Literal
from uuid import uuid4

if TYPE_CHECKING:
    from pydantic_ai import ModelMessage, RunUsage

__all__ = ["SessionRecord", "SessionStore", "UnknownSessionError", "new_session_id"]

SessionState = Literal["pending", "in_flight", "consumed"]


def new_session_id() -> str:
    """Generate a fresh session id (spec 013 R1.1).

    The single point of id generation, backed by ``uuid.uuid4()`` (CPython's
    ``os.urandom``-seeded CSPRNG) -- centralized so it is the one place
    audited for randomness, rather than inlined at each call site (research.md AD-1).

    Returns:
        A random UUID4 string, unrelated to any other id this process has
        generated (R1.3).
    """
    return str(uuid4())


class UnknownSessionError(Exception):
    """A session id could not be claimed: unknown, in_flight, or consumed.

    Deliberately carries no detail distinguishing which of those three
    cases occurred (existence secrecy, spec 013 R1.2) -- the HTTP boundary
    maps this to a single fixed 404 body regardless of cause.
    """


@dataclass(frozen=True)
class SessionRecord:
    """A stopped or resumed run's carried-over state.

    Attributes:
        history: The full message history up to the last stop/resume point,
            fed back into the next ``agent.run(message_history=...)`` call.
        usage: The usage accumulated so far, fed back via
            ``agent.run(usage=...)`` so budgets are enforced across the
            stop/resume boundary rather than per-request (plan.md AD-4).
        state: Where this session sits in the consumption state machine
            (spec 013 R2, research.md AD-2): ``pending`` -- awaiting a
            claim; ``in_flight`` -- claimed, a resume is running against it;
            ``consumed`` -- terminated, never claimable again.
        pending_call_ids: The ``tool_call_id`` set a caller's decisions must
            be a subset of to resume this session (R2.3). Replaced wholesale
            on each re-defer by :meth:`SessionStore.settle_pending`, so a
            stale id from a prior round is never valid (R2.2).
    """

    history: list[ModelMessage]
    usage: RunUsage
    state: SessionState = "pending"
    pending_call_ids: frozenset[str] = frozenset()


class SessionStore:
    """In-memory, process-local session state (plan.md SessionStore, R8.4).

    Not durable and not shared across processes -- the lane's stated scope
    excludes persistence and TTL. A Durable Execution backend (Temporal /
    DBOS / Prefect, per the README's Durable Execution note) is the natural
    production replacement for this class, not an extension of it.
    """

    def __init__(self) -> None:
        self._records: dict[str, SessionRecord] = {}

    def create(
        self,
        history: list[ModelMessage],
        usage: RunUsage,
        pending_call_ids: frozenset[str] = frozenset(),
    ) -> str:
        """Persist a new, ``pending`` session's state and return its generated id.

        Args:
            history: The message history to store.
            usage: The usage accumulated so far.
            pending_call_ids: The tool call ids a caller may resolve when
                resuming this session (empty for a session with no pending
                approvals yet).

        Returns:
            A freshly generated session id (R1.1, R1.3).
        """
        session_id = new_session_id()
        self._records[session_id] = SessionRecord(
            history=history, usage=usage, pending_call_ids=pending_call_ids
        )
        return session_id

    def get(self, session_id: str) -> SessionRecord:
        """Look up a session's stored state without transitioning it.

        Args:
            session_id: The id returned by a prior :meth:`create` call.

        Returns:
            The session's current record.

        Raises:
            KeyError: If ``session_id`` is unknown. Callers at the HTTP
                boundary (``app.py``) map this to a 404 (R8.5).
        """
        return self._records[session_id]

    def claim(self, session_id: str) -> SessionRecord:
        """Claim a ``pending`` session, synchronously moving it to ``in_flight``.

        The transition happens before returning, with no ``await`` in
        between -- the caller (the HTTP boundary, Task 2) does not need any
        additional locking to make a second concurrent claim on the same
        session lose (research.md AD-2, plan.md H-1).

        Args:
            session_id: The id to claim.

        Returns:
            The now-``in_flight`` record.

        Raises:
            UnknownSessionError: If ``session_id`` is unknown, already
                ``in_flight``, or ``consumed`` -- all three raise the same
                exception with no distinguishing detail (R1.2, R2.1).
        """
        record = self._records.get(session_id)
        if record is None or record.state != "pending":
            raise UnknownSessionError
        claimed = replace(record, state="in_flight")
        self._records[session_id] = claimed
        return claimed

    def settle_pending(
        self,
        session_id: str,
        *,
        history: list[ModelMessage],
        usage: RunUsage,
        pending_call_ids: frozenset[str],
    ) -> None:
        """Return an ``in_flight`` session to ``pending`` after a re-defer.

        Replaces the stored history, usage, and ``pending_call_ids``
        wholesale -- the previous round's tool call ids are no longer part
        of the pending set once this returns (R2.2).

        Only ever called (Task 2) with a session id a prior :meth:`claim`
        already resolved, so an unknown id is not a case this guards
        against -- it would simply insert a fresh record under that id.

        Args:
            session_id: The session to settle.
            history: The message history up to the new stop point.
            usage: The usage accumulated so far.
            pending_call_ids: The new round's pending tool call ids.
        """
        self._records[session_id] = SessionRecord(
            history=history, usage=usage, state="pending", pending_call_ids=pending_call_ids
        )

    def consume(self, session_id: str) -> None:
        """Permanently terminate a session; no further claim will succeed.

        Args:
            session_id: The session to terminate.

        Raises:
            KeyError: If ``session_id`` is unknown -- see :meth:`settle_pending`.
        """
        self._records[session_id] = replace(self._records[session_id], state="consumed")

    def release(self, session_id: str) -> None:
        """Return an ``in_flight`` session to ``pending`` without altering its pending set.

        Used on the 409 (pending-set-violation) path: no tool has run, so
        the session must stay resumable exactly as it was before the claim
        (R2.3).

        Args:
            session_id: The session to release.

        Raises:
            KeyError: If ``session_id`` is unknown -- see :meth:`settle_pending`.
        """
        self._records[session_id] = replace(self._records[session_id], state="pending")
