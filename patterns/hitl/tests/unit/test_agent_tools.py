"""Failing tests for HITL agent tool wiring (Spec 012-agentic-ai-design Task 4.1).

Locks two approval-adjacent tool paths before ``patterns_hitl.agent`` exists:

* ``search_customer_context`` carries no approval gate, so ``TestModel(call_tools=[...])``
  (Req 10.3 -- scoped so a ``requires_approval`` tool doesn't turn every result into
  ``DeferredToolRequests``) drives the run straight to a terminal ``SupportOutput``.
* ``apply_discount`` is conditionally gated (Req 5.4): below the configured risk
  threshold it executes without raising ``ApprovalRequired``.
"""

from __future__ import annotations

from patterns_contracts import SupportOutput
from pydantic_ai.models.test import TestModel

from patterns_hitl.agent import HitlDeps, build_agent


def test_approval_not_required_tool_terminates_with_support_output() -> None:
    """search_customer_context has no approval gate, so the run reaches SupportOutput directly."""
    model = TestModel(call_tools=["search_customer_context"])
    agent = build_agent(model)

    result = agent.run_sync("The customer disputes a duplicate charge.", deps=HitlDeps())

    assert isinstance(result.output, SupportOutput)


def test_apply_discount_below_threshold_executes_without_approval() -> None:
    """apply_discount below the risk threshold runs straight through -- no ApprovalRequired."""
    model = TestModel(call_tools=["apply_discount"])
    agent = build_agent(model)

    result = agent.run_sync("Apply a small courtesy discount.", deps=HitlDeps())

    assert isinstance(result.output, SupportOutput)
