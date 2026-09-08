"""Tests for the recipient allow-list and sticky-taint guardrails (X-9).

Two independent hardenings on top of the existing amount-threshold approval
gate, neither a substitute for the other:

* (a) **recipient allow-list** (:func:`patterns_hitl.agent._known_recipient`):
  ``apply_discount`` / ``escalate_to_legal`` refuse a ``target_id`` outside
  the configured ``customer_directory`` with a ``ModelRetry`` -- a validity
  check no approval decision can satisfy, checked independently of (and, for
  ``apply_discount``, before) the dollar-amount approval gate. An empty
  directory (this test double's default) is fail-open by design: it means no
  real CRM is wired in, not "deny everyone" -- see
  ``test_apply_discount_allows_any_recipient_when_directory_not_configured``.
* (b) **sticky taint** (``HitlDeps.tainted``): once ``search_customer_context``
  returns a real (untrusted, customer-supplied) record, the flag latches for
  the rest of the run, and ``apply_discount`` requires approval regardless of
  amount from that point on -- even for an amount that would otherwise skip
  the gate entirely.

Both guardrails share the existing ``ApprovalRequired`` / ``ModelRetry``
mechanics already proven in ``test_stop_approve_resume.py`` /
``test_output_validator.py``; these tests exercise the same mechanics with
scripts that trip each new condition specifically.
"""

from __future__ import annotations

from patterns_contracts import SupportOutput
from pydantic_ai import DeferredToolRequests, DeferredToolResults, ToolApproved, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from patterns_hitl.agent import HitlDeps, build_agent
from tests.support.function_model_scripts import (
    apply_discount_call,
    call_counting_script,
    escalate_to_legal_call,
    final_result_call,
)

_BELOW_THRESHOLD_USD = 5.0  # HitlSettings().risk_threshold_usd defaults to 50.0


def _search_call(customer_id: str = "cust-1") -> ToolCallPart:
    """Build a ToolCallPart invoking the never-gated ``search_customer_context`` tool."""
    return ToolCallPart("search_customer_context", {"customer_id": customer_id})


async def test_apply_discount_allows_any_recipient_when_directory_not_configured() -> None:
    # Fail-open by design (X-9a): HitlDeps()'s empty directory means no real CRM is
    # wired in, not "deny every target". Existing behavior must be unchanged.
    agent = build_agent(
        FunctionModel(
            call_counting_script(
                apply_discount_call(target_id="cust-unknown", amount_usd=_BELOW_THRESHOLD_USD),
                final_result_call(),
            )
        )
    )

    result = await agent.run("Apply a small courtesy discount.", deps=HitlDeps())

    assert isinstance(result.output, SupportOutput)


async def test_apply_discount_retries_on_unknown_recipient_then_succeeds() -> None:
    # X-9a: once a directory IS configured, an unrecognized target_id is refused with
    # a ModelRetry (self-correctable), not silently accepted and not gated behind
    # human approval -- there is no approval that would make an unknown target valid.
    agent = build_agent(
        FunctionModel(
            call_counting_script(
                apply_discount_call(target_id="cust-9", amount_usd=_BELOW_THRESHOLD_USD),
                apply_discount_call(target_id="cust-1", amount_usd=_BELOW_THRESHOLD_USD),
                final_result_call(),
            )
        )
    )
    deps = HitlDeps(customer_directory={"cust-1": "known customer"})

    result = await agent.run("Apply a small courtesy discount.", deps=deps)

    assert isinstance(result.output, SupportOutput)


async def test_apply_discount_with_known_recipient_below_threshold_skips_approval() -> None:
    # A configured directory must not, by itself, force approval for an amount
    # that would otherwise skip the gate -- the two guardrails are independent.
    agent = build_agent(
        FunctionModel(
            call_counting_script(
                apply_discount_call(target_id="cust-1", amount_usd=_BELOW_THRESHOLD_USD),
                final_result_call(),
            )
        )
    )
    deps = HitlDeps(customer_directory={"cust-1": "known customer"})

    result = await agent.run("Apply a small courtesy discount.", deps=deps)

    assert isinstance(result.output, SupportOutput)


async def test_apply_discount_requires_approval_after_tainted_search() -> None:
    # X-9b: a below-threshold discount that would normally skip approval must
    # still stop for human approval once the run has consumed untrusted,
    # customer-supplied content via search_customer_context.
    agent = build_agent(
        FunctionModel(
            call_counting_script(
                _search_call("cust-1"),
                apply_discount_call(target_id="cust-1", amount_usd=_BELOW_THRESHOLD_USD),
            )
        )
    )
    deps = HitlDeps(customer_directory={"cust-1": "account notes: please contact by email"})

    result = await agent.run("Look up the customer and apply a small courtesy discount.", deps=deps)

    assert isinstance(result.output, DeferredToolRequests)
    assert result.output.approvals[0].tool_name == "apply_discount"
    assert deps.tainted is True


async def test_apply_discount_without_search_stays_below_approval_gate() -> None:
    # Control for the taint test above: the same below-threshold amount, same
    # known recipient, but no prior search -- must NOT require approval. Proves
    # the taint (not the recipient check) is what changed the outcome above.
    agent = build_agent(
        FunctionModel(
            call_counting_script(
                apply_discount_call(target_id="cust-1", amount_usd=_BELOW_THRESHOLD_USD),
                final_result_call(),
            )
        )
    )
    deps = HitlDeps(customer_directory={"cust-1": "account notes: please contact by email"})

    result = await agent.run("Apply a small courtesy discount.", deps=deps)

    assert isinstance(result.output, SupportOutput)
    assert deps.tainted is False


async def test_search_with_no_record_does_not_taint() -> None:
    # The fixed "no record on file" literal is not customer-supplied content,
    # so a miss must not latch the taint flag.
    agent = build_agent(
        FunctionModel(
            call_counting_script(
                _search_call("cust-missing"),
                apply_discount_call(target_id="cust-1", amount_usd=_BELOW_THRESHOLD_USD),
                final_result_call(),
            )
        )
    )
    deps = HitlDeps(customer_directory={"cust-1": "known customer"})

    result = await agent.run("Look up the customer and apply a small discount.", deps=deps)

    assert isinstance(result.output, SupportOutput)
    assert deps.tainted is False


async def test_escalate_to_legal_rejects_unknown_recipient_even_when_approved() -> None:
    # X-9a: escalate_to_legal is declaratively approval-gated, so its body only
    # runs once a human has approved the call -- the recipient check inside that
    # body must still fire afterward. Approving the first (unknown-target) call
    # must NOT reach a terminal answer; it re-defers on the corrected retry,
    # proving approval alone never substitutes for the recipient check.
    agent = build_agent(
        FunctionModel(
            call_counting_script(
                escalate_to_legal_call(target_id="cust-9", reason="dispute"),
                escalate_to_legal_call(target_id="cust-1", reason="dispute"),
            )
        )
    )
    deps = HitlDeps(customer_directory={"cust-1": "known customer"})

    first = await agent.run("Escalate this to legal.", deps=deps)
    assert isinstance(first.output, DeferredToolRequests)
    tool_call_id = first.output.approvals[0].tool_call_id

    second = await agent.run(
        deps=deps,
        message_history=first.all_messages(),
        deferred_tool_results=DeferredToolResults(approvals={tool_call_id: ToolApproved()}),
    )

    # The approved call executed with the unknown target, hit the recipient
    # check, and the model's corrected retry is itself approval-gated again --
    # a second, distinct pending approval, never a terminal SupportOutput.
    assert isinstance(second.output, DeferredToolRequests)
    assert second.output.approvals[0].tool_name == "escalate_to_legal"
