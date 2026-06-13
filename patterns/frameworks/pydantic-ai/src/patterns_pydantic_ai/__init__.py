"""PydanticAI lane of the cross-framework pattern collection (Spec 005)."""

from patterns_contracts import (
    OrchestratedResult,
    Route,
    RoutedAnswer,
    RouteDecision,
    SubTask,
    TaskPlan,
    WorkerResult,
)

from patterns_pydantic_ai.observability import configure_tracing
from patterns_pydantic_ai.orchestrator_workers import run_orchestrator
from patterns_pydantic_ai.routing import run_routing

__all__ = [
    "OrchestratedResult",
    "Route",
    "RouteDecision",
    "RoutedAnswer",
    "SubTask",
    "TaskPlan",
    "WorkerResult",
    "configure_tracing",
    "run_orchestrator",
    "run_routing",
]
