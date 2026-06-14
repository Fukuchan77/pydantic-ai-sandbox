"""Parallelization pattern contracts (Spec 006-2a Req 1.3, 4.1).

This module is the single source of truth for the parallelization pattern's
branch/result Pydantic models and its closed ``variant`` vocabulary; the
normative copy also lives in ``patterns/parallelization/README.md`` fenced
block, asserted equal by the single-point drift test (Task 2.3). A single
contract covers both fan-out variants via the ``variant`` Literal: ``sectioning``
(independent subtasks) and ``voting`` (same task, majority vote). ``branches``
is restored in deterministic ``index`` order regardless of completion order
(Req 4.4).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

__all__ = [
    "Branch",
    "ParallelResult",
]


class Branch(BaseModel):
    """One parallel branch's output, keyed by its deterministic order index."""

    index: int = Field(description="Deterministic ordering key for branch restoration.")
    output: str = Field(description="Branch output.")


class ParallelResult(BaseModel):
    """Final output of the parallelization pattern."""

    variant: Literal["sectioning", "voting"] = Field(
        description="Fan-out variant: sectioning (independent subtasks) or voting (majority).",
    )
    branches: list[Branch] = Field(description="Branch outputs restored in ascending index order.")
    aggregate: str = Field(description="Aggregated result across branches.")
