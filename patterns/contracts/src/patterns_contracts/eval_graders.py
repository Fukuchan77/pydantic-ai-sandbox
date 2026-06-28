"""Shared eval-graders contract (Spec 011 Req 1.1-1.3, 1.5, 3.1, 3.3).

This module is the single source of truth for the cross-pattern outcome+behavior
grader contract: the ``Rating`` vocabulary, the per-axis ``AxisScore`` model, the
aggregate ``GradeReport`` model, and the injected ``Judge[SubjectT]`` Protocol
seam. Unlike the per-pattern contracts, the normative copy lives in the
*cross-cutting* README ``patterns/EVAL-GRADERS.md`` fenced block, asserted equal
by the single-point drift test (Spec 011 Task 2.2); the drift parser skips the
``Judge`` Protocol (no ``model_fields``) just as it skips ``Tool`` -- its
cross-lane agreement is the type system's responsibility (pyright strict), not
the drift test's.

This grader layer is an *offline / CI* scoring concern that coexists with --
never replaces -- the runtime convergence gates (``OptimizationResult`` /
``ResearchReport`` / ``AgentRunResult``), per ADR-4. Independence (self-eval
avoidance) is an implementation discipline (distinct-model injection, physical
Generator/Evaluator separation), so the contract stays pure data plus the
optional ``judge_id`` provenance metadata and does NOT encode self-eval-forbidden
flags as type constraints (ADR-3 / Req 3.3).
"""

from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel, Field, field_validator

__all__ = [
    "AxisScore",
    "GradeReport",
    "Judge",
    "Rating",
]

Rating = Literal["1", "2", "3", "4", "5", "unknown"]
"""Discrete per-axis rating: ``"1"``-``"5"``, or ``"unknown"`` for evidence-deficient
axes that must not be silently scored (Req 1.2 / 2.4). A string Literal (not an
int one) keeps the drift parser symmetric across README and package (research.md
AD-1)."""


class AxisScore(BaseModel):
    """One scored criterion on either the outcome or the behavior axis."""

    criterion: str = Field(
        description="Axis criterion name, e.g. correctness / tool_use_discipline.",
    )
    rating: Rating = Field(description='Discrete 1-5 rating, or "unknown" if evidence is lacking.')
    rationale: str = Field(
        description="Why this rating was assigned; empty/whitespace is rejected."
    )

    @field_validator("rationale")
    @classmethod
    def _rationale_must_not_be_blank(cls, value: str) -> str:
        """Reject empty/whitespace-only rationale (silent-empty ban, Req 1.5)."""
        if not value.strip():
            raise ValueError("rationale must not be empty or whitespace-only")
        return value


class GradeReport(BaseModel):
    """Outcome+behavior multi-axis grade for a single graded subject."""

    outcome_scores: list[AxisScore] = Field(
        description="Axes scoring the final artifact (physically separated, Req 1.2).",
    )
    behavior_scores: list[AxisScore] = Field(
        description="Axes scoring the process/behavior (physically separated, Req 1.2).",
    )
    aggregate: float = Field(
        description="Partial-credit aggregate score; scale is harness-defined (Req 1.3).",
    )
    judge_id: str | None = Field(
        default=None,
        description="Optional provenance of the judge that produced this report (Req 3.3).",
    )


class Judge[SubjectT](Protocol):
    """Injection seam for an independent grader (Req 3.1).

    A lane supplies a concrete judge (or a deterministic fake in tests) that
    scores a ``subject`` -- the pattern's runtime result -- into a
    ``GradeReport``. The drift parser skips this Protocol (no ``model_fields``),
    as it does ``Tool``.
    """

    async def grade(self, subject: SubjectT, /) -> GradeReport:
        """Score ``subject`` and return its outcome+behavior ``GradeReport``."""
        ...
