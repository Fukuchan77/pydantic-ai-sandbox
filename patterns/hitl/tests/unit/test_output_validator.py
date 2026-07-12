"""Failing tests for the HITL agent's approval-policy output validator (Task 4.1).

Locks Req 3.5: an ``@output_validator`` that raises ``ModelRetry`` with corrective
natural-language feedback when ``action_plan`` carries an amount above the configured
risk threshold while ``requires_human_approval`` is ``False``, so the model self-corrects
within the run's retry budget -- and that a model which never self-corrects exhausts that
budget with a loud failure rather than silently accepting the policy violation.
"""

from __future__ import annotations

import pytest
from patterns_contracts import SupportOutput
from pydantic_ai import ModelMessage, ModelResponse, ToolCallPart, UnexpectedModelBehavior
from pydantic_ai.models.function import AgentInfo, FunctionModel

from patterns_hitl.agent import HitlDeps, build_agent
from patterns_hitl.settings import HitlSettings

_CUSTOMER_ID = "cust-1"


def _final_result_call(*, amount_usd: float, requires_human_approval: bool) -> ToolCallPart:
    """Build the terminal output-tool call a FunctionModel script returns to end a run."""
    return ToolCallPart(
        "final_result",
        {
            "summary_of_issue": "customer disputes a duplicate charge",
            "reasoning": "the ledger shows the same charge posted twice",
            "requires_human_approval": requires_human_approval,
            "action_plan": [
                {"action_type": "DISCOUNT", "target_id": _CUSTOMER_ID, "amount_usd": amount_usd},
            ],
        },
    )


def test_output_validator_retries_on_policy_violation_then_succeeds() -> None:
    """A policy-violating terminal answer earns one ModelRetry, then a fix succeeds."""
    violating_amount = HitlSettings().risk_threshold_usd + 50.0
    calls = 0

    def script(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        nonlocal calls
        calls += 1
        if calls == 1:
            return ModelResponse(
                parts=[
                    _final_result_call(amount_usd=violating_amount, requires_human_approval=False)
                ]
            )
        return ModelResponse(
            parts=[_final_result_call(amount_usd=violating_amount, requires_human_approval=True)]
        )

    agent = build_agent(FunctionModel(script))

    result = agent.run_sync("A customer disputes a duplicate charge.", deps=HitlDeps())

    assert calls == 2
    assert isinstance(result.output, SupportOutput)
    assert result.output.requires_human_approval is True


def test_output_validator_exhausts_retry_budget_and_raises() -> None:
    """A model that never self-corrects exhausts the retry budget with a loud failure."""
    violating_amount = HitlSettings().risk_threshold_usd + 50.0

    def always_violating_script(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(
            parts=[_final_result_call(amount_usd=violating_amount, requires_human_approval=False)]
        )

    agent = build_agent(FunctionModel(always_violating_script))

    with pytest.raises(UnexpectedModelBehavior):
        agent.run_sync("A customer disputes a duplicate charge.", deps=HitlDeps())
