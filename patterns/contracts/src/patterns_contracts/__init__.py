"""Dependency-zero shared contracts for the cross-framework agent patterns.

This package is the single source of truth for the six patterns' input/output
Pydantic models, ``Literal`` vocabularies, and the autonomous-agent tool
abstraction (Spec 006-2a Req 1.3). Each framework lane imports it via a
``tool.uv.sources`` path dependency rather than duplicating the contracts
(NFR-3); the normative copy of every model also lives in the matching
``patterns/<pattern>/README.md`` fenced block, asserted equal by the
single-point drift test.

The flat re-export surface (``from patterns_contracts import ...``) is
established here (Task 1.4): every model and type alias defined in the
per-pattern submodules is re-exported from the package root so consumers
depend on a stable, submodule-agnostic import path.
"""

from patterns_contracts.autonomous_agent import (
    AgentRunResult,
    AgentStep,
    ApprovalHook,
    Tool,
)
from patterns_contracts.deep_research import (
    BriefReadyEvent,
    Finding,
    FindingReadyEvent,
    PlanReadyEvent,
    ProgressEvent,
    ReportReadyEvent,
    ResearchBrief,
    ResearcherStartedEvent,
    ResearchNote,
    ResearchPlan,
    ResearchReport,
    SearchQuery,
    SearchResult,
    SubQuestion,
)
from patterns_contracts.eval_graders import AxisScore, GradeReport, Judge, Rating
from patterns_contracts.evaluator_optimizer import Iteration, OptimizationResult
from patterns_contracts.live_ollama import (
    LIVE_CONTEXT_WINDOW,
    LIVE_MAX_TOKENS,
    LIVE_REQUEST_TIMEOUT_SECONDS,
    LIVE_WORKFLOW_TIMEOUT_SECONDS,
)
from patterns_contracts.orchestrator_workers import (
    OrchestratedResult,
    SubTask,
    TaskPlan,
    WorkerResult,
)
from patterns_contracts.parallelization import Branch, ParallelResult
from patterns_contracts.prompt_chaining import ChainResult, ChainStep, GateOutcome
from patterns_contracts.rag import Citation, RagAnswer, RetrievedChunk
from patterns_contracts.routing import Route, RoutedAnswer, RouteDecision
from patterns_contracts.sse import (
    CompletedEvent,
    ErrorEvent,
    SseEvent,
    StepStartedEvent,
    TokenEvent,
    ToolCalledEvent,
)

__all__ = [
    "LIVE_CONTEXT_WINDOW",
    "LIVE_MAX_TOKENS",
    "LIVE_REQUEST_TIMEOUT_SECONDS",
    "LIVE_WORKFLOW_TIMEOUT_SECONDS",
    "AgentRunResult",
    "AgentStep",
    "ApprovalHook",
    "AxisScore",
    "Branch",
    "BriefReadyEvent",
    "ChainResult",
    "ChainStep",
    "Citation",
    "CompletedEvent",
    "ErrorEvent",
    "Finding",
    "FindingReadyEvent",
    "GateOutcome",
    "GradeReport",
    "Iteration",
    "Judge",
    "OptimizationResult",
    "OrchestratedResult",
    "ParallelResult",
    "PlanReadyEvent",
    "ProgressEvent",
    "RagAnswer",
    "Rating",
    "ReportReadyEvent",
    "ResearchBrief",
    "ResearchNote",
    "ResearchPlan",
    "ResearchReport",
    "ResearcherStartedEvent",
    "RetrievedChunk",
    "Route",
    "RouteDecision",
    "RoutedAnswer",
    "SearchQuery",
    "SearchResult",
    "SseEvent",
    "StepStartedEvent",
    "SubQuestion",
    "SubTask",
    "TaskPlan",
    "TokenEvent",
    "Tool",
    "ToolCalledEvent",
    "WorkerResult",
]
