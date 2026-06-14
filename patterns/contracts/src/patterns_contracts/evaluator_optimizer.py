"""Evaluator-optimizer pattern contracts (Spec 006-2a Req 1.3, 5.1).

This module is the single source of truth for the evaluator-optimizer pattern's
iteration/result Pydantic models and its closed ``verdict`` / ``stop_reason``
vocabularies; the normative copy also lives in
``patterns/evaluator-optimizer/README.md`` fenced block, asserted equal by the
single-point drift test (Task 2.3). A generator/evaluator loop repeats until the
evaluator returns ``pass`` or ``max_iterations`` is reached; ``revise`` feedback
flows into the next iteration's generator input (Req 5.3).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

__all__ = [
    "Iteration",
    "OptimizationResult",
]


class Iteration(BaseModel):
    """One generate-then-evaluate iteration of the loop."""

    index: int = Field(description="Zero-based iteration number.")
    candidate: str = Field(description="Generator candidate for this iteration.")
    verdict: Literal["pass", "revise"] = Field(description="Evaluator decision for the candidate.")
    feedback: str = Field(description="Evaluator feedback fed into the next iteration on revise.")


class OptimizationResult(BaseModel):
    """Final output of the evaluator-optimizer pattern."""

    iterations: list[Iteration] = Field(description="Recorded generate/evaluate iterations.")
    final_output: str = Field(description="Final accepted (or last) candidate.")
    stop_reason: Literal["passed", "max_iterations"] = Field(
        description="Why the loop stopped: evaluator passed, or iteration cap reached.",
    )
