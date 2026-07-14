"""HITL stop/approve/resume orchestration harness (Task 5.2).

One HTTP-shaped round-trip = one approval step (plan.md AD-3): ``start``
runs the agent from a fresh prompt and either returns a terminal
``SupportOutput`` or stops at the first approval-gated tool call;
``resume`` feeds a caller's approval decisions back in and returns the same
two-way result -- a further approval-gated tool call re-defers rather than
looping in-process, since the approver lives outside this process. Usage is
carried across the stop/resume boundary via :class:`~patterns_hitl.store.SessionStore`
so a run's budget (:data:`LIMITS`) is enforced cumulatively, not
per-request (plan.md AD-4); a budget overrun surfaces as
:class:`HitlBudgetExceededError` rather than pydantic-ai's raw
``UsageLimitExceeded`` so the HTTP layer (Task 6) has a lane-owned exception
to map.

``resume`` drives the spec 013 consumption state machine
(``store.py``'s ``settle_pending``/``consume``) rather than the plain
``update`` Task 5.2 used: a re-defer settles the session back to
``pending`` with the new round's ``pending_call_ids`` (R2.2), a terminal
result or a budget overrun consumes it permanently (R2.1, R2.4). The
pending-set membership check (409) and the ``claim``/``release`` calls
around it are the HTTP boundary's job (``app.py``, spec 013 R2.3) --
``resume`` itself only reads the record via ``store.get`` and trusts the
caller already resolved a pending vs. in-flight session.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic_ai import DeferredToolRequests, DeferredToolResults, UsageLimitExceeded, UsageLimits

from .agent import HitlDeps

if TYPE_CHECKING:
    from patterns_contracts import SupportOutput
    from pydantic_ai import Agent, ModelMessage, RunUsage, ToolApproved, ToolCallPart, ToolDenied

    from .store import SessionStore

__all__ = ["LIMITS", "HitlBudgetExceededError", "HitlHarness", "PendingResult", "TerminalResult"]

LIMITS = UsageLimits(request_limit=8, tool_calls_limit=10, total_tokens_limit=20_000)


class HitlBudgetExceededError(Exception):
    """Raised when accumulated usage across the stop/resume boundary exceeds the harness budget."""


@dataclass(frozen=True)
class PendingResult:
    """A run stopped with one or more approval-gated tool calls awaiting a decision.

    Attributes:
        session_id: The id under which the caller must resume this run.
        approvals: The pending tool calls, exposing ``tool_name`` / ``args``
            / ``tool_call_id`` directly (pydantic-ai's own
            ``ToolCallPart`` -- the harness does not re-wrap it, that is the
            HTTP boundary's job).
        history: The full message history up to this stop point.
        usage: The usage accumulated so far.
    """

    session_id: str
    approvals: list[ToolCallPart]
    history: list[ModelMessage]
    usage: RunUsage


@dataclass(frozen=True)
class TerminalResult:
    """A run reached a terminal structured answer.

    Attributes:
        session_id: The session this run completed under.
        output: The agent's terminal structured answer.
        history: The full message history up to completion.
        usage: The usage accumulated over the run.
    """

    session_id: str
    output: SupportOutput
    history: list[ModelMessage]
    usage: RunUsage


class HitlHarness:
    """Orchestrates one-step-per-round-trip stop/approve/resume runs over an agent + store."""

    def __init__(
        self,
        agent: Agent[HitlDeps, SupportOutput | DeferredToolRequests],
        store: SessionStore,
        *,
        usage_limits: UsageLimits = LIMITS,
    ) -> None:
        """Bind the harness to an agent and a session store.

        Args:
            agent: The agent to run, typically built by
                :func:`patterns_hitl.agent.build_agent`.
            store: Where stopped runs' history and usage are carried across
                the stop/resume boundary.
            usage_limits: The budget enforced on every run this harness
                drives; overridable so tests can inject a tight budget to
                make the overrun path deterministic.
        """
        self._agent = agent
        self._store = store
        self._usage_limits = usage_limits

    async def start(self, prompt: str) -> TerminalResult | PendingResult:
        """Run the agent from a fresh prompt.

        Args:
            prompt: The initial user prompt.

        Returns:
            A :class:`TerminalResult` if the run completed, or a
            :class:`PendingResult` if it stopped at an approval-gated tool
            call.

        Raises:
            HitlBudgetExceededError: If the run exceeds ``usage_limits``.
        """
        try:
            result = await self._agent.run(prompt, deps=HitlDeps(), usage_limits=self._usage_limits)
        except UsageLimitExceeded as exc:
            raise HitlBudgetExceededError(str(exc)) from exc
        history = result.all_messages()
        session_id = self._store.create(
            history, result.usage, pending_call_ids=_pending_call_ids(result.output)
        )
        outcome = self._to_result(session_id, result.output, history, result.usage)
        if isinstance(outcome, TerminalResult):
            self._store.consume(session_id)
        return outcome

    async def resume(
        self, session_id: str, decisions: dict[str, ToolApproved | ToolDenied]
    ) -> TerminalResult | PendingResult:
        """Resume a stopped run with approval decisions for its pending tool calls.

        Args:
            session_id: The id returned by a prior :meth:`start` or
                :meth:`resume` call that stopped with a
                :class:`PendingResult`.
            decisions: Approval decisions keyed by ``tool_call_id``.

        Returns:
            A :class:`TerminalResult` if the run completed, or a
            :class:`PendingResult` if a further approval-gated tool call
            re-deferred it under the same session.

        Raises:
            KeyError: If ``session_id`` is unknown.
            HitlBudgetExceededError: If the resumed run exceeds
                ``usage_limits`` once the session's carried-over usage is
                counted in. The session is consumed (permanently
                invalidated) before this is raised (spec 013 R2.4).
        """
        record = self._store.get(session_id)
        try:
            result = await self._agent.run(
                deps=HitlDeps(),
                message_history=record.history,
                deferred_tool_results=DeferredToolResults(approvals=dict(decisions.items())),
                usage=record.usage,
                usage_limits=self._usage_limits,
            )
        except UsageLimitExceeded as exc:
            self._store.consume(session_id)
            raise HitlBudgetExceededError(str(exc)) from exc
        history = result.all_messages()
        outcome = self._to_result(session_id, result.output, history, result.usage)
        if isinstance(outcome, PendingResult):
            self._store.settle_pending(
                session_id,
                history=history,
                usage=result.usage,
                pending_call_ids=_pending_call_ids(result.output),
            )
        else:
            self._store.consume(session_id)
        return outcome

    def _to_result(
        self,
        session_id: str,
        output: SupportOutput | DeferredToolRequests,
        history: list[ModelMessage],
        usage: RunUsage,
    ) -> TerminalResult | PendingResult:
        """Type-split an agent run's output into a Pending/Terminal result (plan.md R6.1)."""
        if isinstance(output, DeferredToolRequests):
            return PendingResult(session_id, list(output.approvals), history, usage)
        return TerminalResult(session_id, output, history, usage)


def _pending_call_ids(output: SupportOutput | DeferredToolRequests) -> frozenset[str]:
    """Extract the tool_call_id set a resume must resolve a subset of (spec 013 R2.2, R2.3)."""
    if isinstance(output, DeferredToolRequests):
        return frozenset(call.tool_call_id for call in output.approvals)
    return frozenset()
