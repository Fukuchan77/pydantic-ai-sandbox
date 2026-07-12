"""In-memory session store for the HITL stop/approve/resume harness (Task 5.2).

Holds the one piece of state a stop/resume boundary needs to survive an HTTP
round-trip: the accumulated ``message_history`` and ``usage`` for a session,
keyed by a server-generated id. Persistence, TTL, and consumption semantics
(pop-on-resume) are explicitly out of scope for this MVP lane (plan.md
SessionStore -- 013 extends this).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import uuid4

if TYPE_CHECKING:
    from pydantic_ai import ModelMessage, RunUsage

__all__ = ["SessionRecord", "SessionStore"]


@dataclass(frozen=True)
class SessionRecord:
    """A stopped or resumed run's carried-over state.

    Attributes:
        history: The full message history up to the last stop/resume point,
            fed back into the next ``agent.run(message_history=...)`` call.
        usage: The usage accumulated so far, fed back via
            ``agent.run(usage=...)`` so budgets are enforced across the
            stop/resume boundary rather than per-request (plan.md AD-4).
    """

    history: list[ModelMessage]
    usage: RunUsage


class SessionStore:
    """In-memory, process-local session state (plan.md SessionStore, R8.4).

    Not durable and not shared across processes -- the lane's stated scope
    excludes persistence and TTL. A Durable Execution backend (Temporal /
    DBOS / Prefect, per the README's Durable Execution note) is the natural
    production replacement for this class, not an extension of it.
    """

    def __init__(self) -> None:
        self._records: dict[str, SessionRecord] = {}

    def create(self, history: list[ModelMessage], usage: RunUsage) -> str:
        """Persist a new session's state and return its generated id.

        Args:
            history: The message history to store.
            usage: The usage accumulated so far.

        Returns:
            A freshly generated session id.
        """
        session_id = str(uuid4())
        self._records[session_id] = SessionRecord(history=history, usage=usage)
        return session_id

    def get(self, session_id: str) -> SessionRecord:
        """Look up a session's stored state.

        Args:
            session_id: The id returned by a prior :meth:`create` call.

        Returns:
            The session's current record.

        Raises:
            KeyError: If ``session_id`` is unknown. Callers at the HTTP
                boundary (``app.py``) map this to a 404 (R8.5).
        """
        return self._records[session_id]

    def update(self, session_id: str, history: list[ModelMessage], usage: RunUsage) -> None:
        """Overwrite an existing session's state after a resume.

        Args:
            session_id: The id returned by a prior :meth:`create` call.
            history: The message history to store.
            usage: The usage accumulated so far.

        Raises:
            KeyError: If ``session_id`` is unknown.
        """
        if session_id not in self._records:
            raise KeyError(session_id)
        self._records[session_id] = SessionRecord(history=history, usage=usage)
