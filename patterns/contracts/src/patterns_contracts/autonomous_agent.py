"""Autonomous-agent pattern contracts (Spec 006-2a Req 1.3, 6.1, ADR-7).

This module is the single source of truth for the autonomous-agent pattern's
step/result Pydantic models, its closed ``stop_reason`` vocabulary, and the tool
abstraction (``Tool`` Protocol + ``ApprovalHook`` alias) shared by all three
lanes. The Pydantic models' normative copy also lives in
``patterns/autonomous-agent/README.md`` fenced block, asserted equal by the
single-point drift test (Task 2.3); the drift parser skips ``Tool`` and
``ApprovalHook`` (no ``model_fields``) — their cross-lane agreement is the type
system's responsibility (pyright strict), not the drift test's.

The pattern is a manual tool loop with four contract-level guardrails
(max_iterations / allowed_tools / approval_hook / budget); ``stop_reason`` is
the closed vocabulary that records which guardrail (or completion) stopped the
loop. Budget figures are non-negative token counts (cost conversion is deferred
to a future iteration, per Req 6.1).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal, Protocol

from pydantic import BaseModel, Field

__all__ = [
    "AgentRunResult",
    "AgentStep",
    "ApprovalHook",
    "Tool",
]


class Tool(Protocol):
    """Tool abstraction for the autonomous-agent loop (ADR-7).

    A lane's concrete tool is matched against ``allowed_tools`` by ``name``
    (least privilege, Req 6.4); ``dangerous`` flags operations that must clear
    ``approval_hook`` before running (Req 6.5).
    """

    name: str
    """Tool identifier matched against the allowed-tools list."""
    dangerous: bool
    """True when invoking the tool requires human approval first."""

    def run(self, args: str) -> str:
        """Execute the tool with string ``args`` and return an observation string."""
        ...


ApprovalHook = Callable[[str, str], bool]
"""Human-approval seam for dangerous tools: ``(tool_name, args) -> approved``.

Returning ``False`` denies the call; the loop then stops with
``stop_reason="denied"`` (Req 6.5).
"""


class AgentStep(BaseModel):
    """One iteration of the autonomous-agent loop."""

    index: int = Field(description="Zero-based iteration number.")
    tool: str = Field(description="Name of the tool invoked in this iteration.")
    observation: str = Field(description="Environment feedback returned by the tool.")
    budget_spent: int = Field(
        ge=0,
        description="Token budget consumed by this iteration (non-negative).",
    )


class AgentRunResult(BaseModel):
    """Final output of the autonomous-agent pattern.

    ``final_output`` is ``None`` when the loop stopped before completing the goal
    (a guardrail fired). ``stop_reason`` records which guardrail — or completion —
    ended the loop (Req 6.2).
    """

    steps: list[AgentStep] = Field(description="Recorded loop iterations.")
    final_output: str | None = Field(
        default=None,
        description="Goal answer, or None when a guardrail stopped the loop first.",
    )
    stop_reason: Literal["completed", "max_iterations", "budget_exceeded", "denied"] = Field(
        description="Closed vocabulary recording why the loop stopped.",
    )
    total_budget_spent: int = Field(
        ge=0,
        description="Cumulative token budget consumed across all steps (non-negative).",
    )
