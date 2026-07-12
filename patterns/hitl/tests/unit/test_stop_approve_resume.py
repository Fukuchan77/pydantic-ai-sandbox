"""Failing tests for the HITL stop/approve/resume harness (Task 5.1).

Locks the orchestration contract before ``patterns_hitl.harness`` /
``patterns_hitl.store`` exist (plan.md HitlHarness / SessionStore):

* (a) a run that hits an approval-gated tool call stops with a
  ``PendingResult`` exposing ``tool_name`` / ``args`` / ``tool_call_id``.
* (b) ``ToolApproved`` resumes the run through to a terminal
  ``SupportOutput`` (``TerminalResult``).
* (c) ``ToolApproved(override_args=...)`` executes the tool with the
  overridden arguments, not the model's originally proposed ones.
* (d) ``ToolDenied(message=...)`` never executes the tool; the model sees
  the denial reason and still reaches a terminal answer.
* (e) a resumed run that itself proposes a second approval-gated tool call
  re-defers with a second ``PendingResult`` under the *same* session id;
  approving that second call resumes it through to a terminal answer.
* (f) usage accumulates across the stop/resume boundary via
  ``SessionStore``; a tight budget raises the harness's dedicated
  ``HitlBudgetExceededError`` rather than pydantic-ai's raw
  ``UsageLimitExceeded``.

FunctionModel scripts are call-order driven
(``function_model_scripts.call_counting_script``), generalizing the
two-phase script verified in research.md I-1 to the three-phase re-defer
case without any ``messages``-length introspection.
"""

from __future__ import annotations

import pytest
from pydantic_ai import ToolApproved, ToolCallPart, ToolDenied, ToolReturnPart, UsageLimits
from pydantic_ai.models.function import FunctionModel

from patterns_hitl.agent import build_agent
from patterns_hitl.harness import (
    HitlBudgetExceededError,
    HitlHarness,
    PendingResult,
    TerminalResult,
)
from patterns_hitl.store import SessionStore
from tests.support.function_model_scripts import (
    apply_discount_call,
    call_counting_script,
    escalate_to_legal_call,
    final_result_call,
)


def _harness(*phases: ToolCallPart, usage_limits: UsageLimits | None = None) -> HitlHarness:
    """Build a harness wired to a call-counting FunctionModel + a fresh in-memory store."""
    agent = build_agent(FunctionModel(call_counting_script(*phases)))
    store = SessionStore()
    if usage_limits is None:
        return HitlHarness(agent, store)
    return HitlHarness(agent, store, usage_limits=usage_limits)


async def test_stop_exposes_pending_tool_call() -> None:
    """(a) A run that hits an approval-gated tool call stops with a PendingResult."""
    harness = _harness(apply_discount_call(amount_usd=100.0), final_result_call())

    result = await harness.start("Apply a $100 discount.")

    assert isinstance(result, PendingResult)
    pending = result.approvals[0]
    assert pending.tool_name == "apply_discount"
    assert pending.args == {"target_id": "cust-1", "amount_usd": 100.0}
    assert pending.tool_call_id


async def test_approve_resumes_to_terminal_support_output() -> None:
    """(b) Approving the pending call resumes the run through to SupportOutput."""
    harness = _harness(
        apply_discount_call(amount_usd=100.0),
        final_result_call(requires_human_approval=True),
    )
    pending = await harness.start("Apply a $100 discount.")
    assert isinstance(pending, PendingResult)
    tool_call_id = pending.approvals[0].tool_call_id

    result = await harness.resume(pending.session_id, {tool_call_id: ToolApproved()})

    assert isinstance(result, TerminalResult)
    assert result.output.requires_human_approval is True


async def test_approve_with_override_args_executes_overridden_amount() -> None:
    """(c) ToolApproved(override_args=...) executes the tool with the overridden arguments."""
    harness = _harness(apply_discount_call(amount_usd=100.0), final_result_call())
    pending = await harness.start("Apply a $100 discount.")
    assert isinstance(pending, PendingResult)
    tool_call_id = pending.approvals[0].tool_call_id

    result = await harness.resume(
        pending.session_id,
        {tool_call_id: ToolApproved(override_args={"target_id": "cust-1", "amount_usd": 5.0})},
    )

    assert isinstance(result, TerminalResult)
    tool_returns = [
        part.content
        for message in result.history
        for part in message.parts
        if isinstance(part, ToolReturnPart) and part.tool_name == "apply_discount"
    ]
    assert tool_returns == ["applied $5.00 discount to cust-1"]


async def test_deny_skips_tool_execution_and_model_offers_alternative() -> None:
    """(d) ToolDenied(message=...) never executes the tool; the model sees the denial reason."""
    harness = _harness(
        apply_discount_call(amount_usd=100.0),
        final_result_call(requires_human_approval=False),
    )
    pending = await harness.start("Apply a $100 discount.")
    assert isinstance(pending, PendingResult)
    tool_call_id = pending.approvals[0].tool_call_id

    result = await harness.resume(
        pending.session_id, {tool_call_id: ToolDenied(message="policy: amount too large")}
    )

    assert isinstance(result, TerminalResult)
    denied_returns = [
        part
        for message in result.history
        for part in message.parts
        if isinstance(part, ToolReturnPart) and part.tool_name == "apply_discount"
    ]
    assert len(denied_returns) == 1
    assert denied_returns[0].outcome == "denied"
    assert denied_returns[0].content == "policy: amount too large"


async def test_resume_can_re_defer_with_a_stable_session_id() -> None:
    """(e) A resumed run that hits a second approval-gated tool re-defers under the same session."""
    harness = _harness(
        apply_discount_call(amount_usd=100.0),
        escalate_to_legal_call(),
        final_result_call(requires_human_approval=True),
    )
    first = await harness.start("Apply a $100 discount, escalate if needed.")
    assert isinstance(first, PendingResult)
    first_tool_call_id = first.approvals[0].tool_call_id

    second = await harness.resume(first.session_id, {first_tool_call_id: ToolApproved()})

    assert isinstance(second, PendingResult)
    assert second.session_id == first.session_id
    assert second.approvals[0].tool_name == "escalate_to_legal"

    second_tool_call_id = second.approvals[0].tool_call_id
    third = await harness.resume(second.session_id, {second_tool_call_id: ToolApproved()})

    assert isinstance(third, TerminalResult)
    assert third.session_id == first.session_id
    assert third.output.requires_human_approval is True


async def test_usage_accumulates_across_resume_and_raises_dedicated_error_over_budget() -> None:
    """(f) SessionStore-held usage carries into resume; a tight budget raises the dedicated error."""
    tight_limits = UsageLimits(request_limit=8, tool_calls_limit=10, total_tokens_limit=80)
    harness = _harness(
        apply_discount_call(amount_usd=100.0),
        final_result_call(),
        usage_limits=tight_limits,
    )
    pending = await harness.start("Apply a $100 discount.")
    assert isinstance(pending, PendingResult)
    tool_call_id = pending.approvals[0].tool_call_id

    with pytest.raises(HitlBudgetExceededError):
        await harness.resume(pending.session_id, {tool_call_id: ToolApproved()})


async def test_start_over_budget_raises_dedicated_error() -> None:
    """A budget already too tight for the very first request raises on `start`, not just resume."""
    minimal_limits = UsageLimits(request_limit=8, tool_calls_limit=10, total_tokens_limit=1)
    harness = _harness(
        apply_discount_call(amount_usd=100.0),
        final_result_call(),
        usage_limits=minimal_limits,
    )

    with pytest.raises(HitlBudgetExceededError):
        await harness.start("Apply a $100 discount.")
