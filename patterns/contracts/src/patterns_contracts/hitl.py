"""HITL (human-in-the-loop) structured-output contracts (Spec 012 Req 2.1-2.3).

This module is the single source of truth for the HITL lane's agent output
shape; the normative copy also lives in the ``patterns/hitl/README.md``
fenced block, asserted equal by the single-point drift test once the
``hitl`` README is registered. The ``patterns_hitl`` lane imports these via
the ``patterns/contracts`` path dependency rather than duplicating them
(NFR-3).

The contract owns only the structured-output shape and ``action_type``'s
closed vocabulary -- the approval-decision representation itself
(pydantic-ai's ``ToolApproved``/``ToolDenied``) is used as-is by the lane and
is not re-modeled here.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

__all__ = [
    "ActionType",
    "ResolutionAction",
    "SupportOutput",
]

ActionType = Literal["DISCOUNT", "UPGRADE", "ESCALATE"]


class ResolutionAction(BaseModel):
    """A single concrete remediation step proposed by the support agent."""

    action_type: ActionType = Field(description="Which kind of remediation this step performs.")
    target_id: str = Field(description="Identifier of the entity the action applies to.")
    amount_usd: float = Field(ge=0, description="Monetary amount involved, in USD; never negative.")


class SupportOutput(BaseModel):
    """Terminal structured output of the HITL support agent."""

    summary_of_issue: str = Field(description="Concise restatement of the customer's issue.")
    reasoning: str = Field(description="The agent's rationale for the proposed action plan.")
    requires_human_approval: bool = Field(
        description="Whether any step in action_plan needed human sign-off before executing."
    )
    action_plan: list[ResolutionAction] = Field(
        description="Ordered remediation steps, both auto-approved and human-approved."
    )
