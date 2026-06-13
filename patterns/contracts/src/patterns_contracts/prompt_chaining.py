"""Prompt-chaining pattern contracts (Spec 006-2a Req 1.3, 3.1).

This module is the single source of truth for the prompt-chaining pattern's
step/gate/result Pydantic models; the normative copy also lives in
``patterns/prompt-chaining/README.md`` fenced block, asserted equal by the
single-point drift test (Task 2.3). A chain runs typed steps sequentially with
a program-verification gate; a failing gate ends the chain early and is made
discernible from the result (``final_output=None``, ``gate.passed=False``) so
no silent continuation is possible (Req 3.3).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

__all__ = [
    "ChainResult",
    "ChainStep",
    "GateOutcome",
]


class ChainStep(BaseModel):
    """One completed step of the chain; its output feeds the next step's input."""

    name: str = Field(description="Step identifier within the chain.")
    output: str = Field(description="Step output, used as the next step's input.")


class GateOutcome(BaseModel):
    """Program-verification gate decision between chain steps."""

    passed: bool = Field(description="True when the gate accepts the chain so far.")
    detail: str = Field(description="Justification for the gate decision.")


class ChainResult(BaseModel):
    """Final output of the prompt-chaining pattern.

    ``final_output`` is ``None`` whenever the gate failed (``gate.passed`` is
    ``False``), so an early-terminated chain is always discernible from the
    result alone (Req 3.3).
    """

    steps: list[ChainStep] = Field(description="Steps executed before the gate decision.")
    gate: GateOutcome
    final_output: str | None = Field(
        default=None,
        description="Chain answer, or None when the gate failed and the chain stopped early.",
    )
