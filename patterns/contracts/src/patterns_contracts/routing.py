"""Routing pattern contracts (Spec 006-2a Req 1.3).

This module is the single source of truth for the routing pattern's input/output
Pydantic models and its closed ``Route`` vocabulary; the normative copy also
lives in ``patterns/routing/README.md`` fenced block, asserted equal by the
single-point drift test (Task 2.3). Ported unchanged from the per-lane
``contracts.py`` duplicates of Spec 005 (NFR-3).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

__all__ = [
    "Route",
    "RouteDecision",
    "RoutedAnswer",
]

Route = Literal["billing", "technical", "general"]
"""Closed routing vocabulary (Req 2.3): values outside this Literal fail
validation instead of silently falling back."""


class RouteDecision(BaseModel):
    """Classifier output for the routing pattern."""

    route: Route = Field(description="Which specialist lane should answer the query.")
    reasoning: str = Field(description="One-sentence justification for the chosen route.")


class RoutedAnswer(BaseModel):
    """Final output of the routing pattern."""

    route: Route = Field(description="Route that produced the answer.")
    answer: str = Field(description="Specialist answer to the user query.")
