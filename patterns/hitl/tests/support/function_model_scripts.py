"""Reusable FunctionModel scripts for HITL stop/approve/resume tests.

The two-phase shape here (first call proposes an approval-gated tool call,
subsequent calls terminate) is the form verified against pydantic-ai-slim
2.9.0 in research.md I-1. It is generalized from "phase keyed by
``len(messages)``" to "phase keyed by call order" so the same builder covers
the re-defer case (Task 5.1(e)): a resumed run that itself proposes a
*second* approval-gated tool call is just a three-phase script, with no
message introspection required.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic_ai import ModelResponse, ToolCallPart

if TYPE_CHECKING:
    from collections.abc import Callable

    from pydantic_ai import ModelMessage
    from pydantic_ai.models.function import AgentInfo

__all__ = [
    "apply_discount_call",
    "call_counting_script",
    "escalate_to_legal_call",
    "final_result_call",
]


def apply_discount_call(*, target_id: str = "cust-1", amount_usd: float = 100.0) -> ToolCallPart:
    """Build a ToolCallPart invoking the conditionally-gated ``apply_discount`` tool."""
    return ToolCallPart("apply_discount", {"target_id": target_id, "amount_usd": amount_usd})


def escalate_to_legal_call(
    *, target_id: str = "cust-1", reason: str = "customer dispute"
) -> ToolCallPart:
    """Build a ToolCallPart invoking the unconditionally-gated ``escalate_to_legal`` tool."""
    return ToolCallPart("escalate_to_legal", {"target_id": target_id, "reason": reason})


def final_result_call(
    *,
    requires_human_approval: bool = False,
    action_plan: list[dict[str, object]] | None = None,
) -> ToolCallPart:
    """Build the terminal ``final_result`` output-tool call ending a run with a SupportOutput."""
    return ToolCallPart(
        "final_result",
        {
            "summary_of_issue": "customer disputes a duplicate charge",
            "reasoning": "the ledger shows the same charge posted twice",
            "requires_human_approval": requires_human_approval,
            "action_plan": action_plan or [],
        },
    )


def call_counting_script(
    *phases: ToolCallPart,
) -> Callable[[list[ModelMessage], AgentInfo], ModelResponse]:
    """Return a FunctionModel script that advances through ``phases`` by call order.

    Call N (0-indexed) returns ``phases[N]``, clamped to the last phase for
    any call beyond ``len(phases)`` so a script written for an exact number
    of stop/resume round-trips does not raise ``IndexError`` if a test drives
    it one call further than intended.
    """
    state = {"calls": 0}

    def script(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del messages, info
        index = min(state["calls"], len(phases) - 1)
        state["calls"] += 1
        return ModelResponse(parts=[phases[index]])

    return script
