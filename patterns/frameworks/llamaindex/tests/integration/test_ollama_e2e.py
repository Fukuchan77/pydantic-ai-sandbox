"""Gated Ollama integration tests (Spec 005 Req 5; Spec 006-2a Req 8.1-8.3).

Skipped unless ``RUN_INTEGRATION_PATTERNS=1``. Assertions stay at the
contract level — route within vocabulary, >=1 worker result, non-empty
summary, ``steps>=1``, ``branches==n`` with a non-empty ``aggregate``,
``stop_reason`` within its closed vocabulary — never exact text (Req 5.2 /
Req 8.2). Model identity comes exclusively from ``OLLAMA_BASE_URL`` /
``OLLAMA_MODEL_NAME`` (Req 5.3 / Req 1.5 / Req 8.3).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import get_args

import pytest
from patterns_contracts import (
    LIVE_CONTEXT_WINDOW,
    LIVE_MAX_TOKENS,
    LIVE_REQUEST_TIMEOUT_SECONDS,
    LIVE_WORKFLOW_TIMEOUT_SECONDS,
    AgentRunResult,
    OptimizationResult,
    Route,
)

from patterns_llamaindex.autonomous_agent import run_autonomous_agent
from patterns_llamaindex.evaluator_optimizer import run_evaluator_optimizer
from patterns_llamaindex.orchestrator_workers import run_orchestrator
from patterns_llamaindex.parallelization import run_parallelization
from patterns_llamaindex.prompt_chaining import run_prompt_chain
from patterns_llamaindex.routing import run_routing

pytestmark = [
    pytest.mark.skipif(
        os.environ.get("RUN_INTEGRATION_PATTERNS") != "1",
        reason="integration lane gated by RUN_INTEGRATION_PATTERNS=1",
    ),
    # Temporarily quarantined from per-PR CI: once this lane actually runs
    # end-to-end (after the anyio/httpx/OOM/timeout fixes), the combined
    # three-lane integration job exceeds its 45-minute budget because
    # granite4.1:8b is slow on CPU runners. Keep the (now-working) lane code and
    # opt into it explicitly with RUN_LLAMAINDEX_INTEGRATION=1, pending the
    # CI-strategy review.
    pytest.mark.skipif(
        os.environ.get("RUN_LLAMAINDEX_INTEGRATION") != "1",
        reason="llamaindex live lane quarantined (CI budget); set RUN_LLAMAINDEX_INTEGRATION=1 to run",
    ),
]


def _ollama_llm() -> object:
    from llama_index.llms.ollama import Ollama  # pyright: ignore[reportMissingTypeStubs]

    # llama-index expects the daemon root URL; the repo-wide convention is
    # an OpenAI-style base ending in /v1, so strip it when present.
    base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1")
    base_url = base_url.removesuffix("/v1")
    # Shared live-Ollama knobs (patterns_contracts.live_ollama): a request timeout
    # well above the contended CPU latency, a bounded num_predict (the Ollama
    # generation cap), and -- critically on this llama-index path -- a bounded
    # context_window. llama-index forwards context_window as Ollama's num_ctx;
    # leaving it unset requests the model's full context (granite4.1 = 131072),
    # whose ~20 GB KV cache OOMs the runner's llama-server. Contract-level
    # assertions only require non-empty output, so the generation cap is safe.
    return Ollama(
        model=os.environ["OLLAMA_MODEL_NAME"],
        base_url=base_url,
        request_timeout=LIVE_REQUEST_TIMEOUT_SECONDS,
        context_window=LIVE_CONTEXT_WINDOW,
        additional_kwargs={"num_predict": LIVE_MAX_TOKENS},
    )


def _approve_all(_tool: str, _args: str) -> bool:
    """Approval hook that approves every dangerous tool call."""
    return True


@dataclass
class _NoopTool:
    """Minimal contracts ``Tool`` for the live loop.

    The autonomous pattern registers no model-side tool schema, so a real model
    returns a final answer rather than a tool call; the tool exists only to
    satisfy the required least-privilege allow-list (Req 6.4).
    """

    name: str = "noop"
    dangerous: bool = False

    def run(self, args: str) -> str:
        """Return a deterministic observation echoing ``args``."""
        return f"noop({args})"


async def test_routing_against_live_ollama() -> None:
    result = await run_routing(
        "I was billed twice for my subscription this month.",
        llm=_ollama_llm(),  # type: ignore[arg-type]
        timeout=LIVE_WORKFLOW_TIMEOUT_SECONDS,
    )
    assert result.route in get_args(Route)
    assert result.answer.strip()


async def test_orchestrator_against_live_ollama() -> None:
    result = await run_orchestrator(
        "List two advantages and two disadvantages of local LLM inference.",
        llm=_ollama_llm(),  # type: ignore[arg-type]
        max_workers=2,
        timeout=LIVE_WORKFLOW_TIMEOUT_SECONDS,
    )
    assert len(result.results) >= 1
    assert result.summary.strip()


async def test_prompt_chain_against_live_ollama() -> None:
    # Req 8.2 contract level: the chain records >=1 pre-gate step, each with a
    # non-empty output; final_output is left to the gate (text not asserted).
    result = await run_prompt_chain(
        "Write a short paragraph explaining what a local LLM is.",
        llm=_ollama_llm(),  # type: ignore[arg-type]
        timeout=LIVE_WORKFLOW_TIMEOUT_SECONDS,
    )
    assert len(result.steps) >= 1
    assert all(step.output.strip() for step in result.steps)


async def test_parallelization_against_live_ollama() -> None:
    # Req 8.2 contract level: fan-out restores exactly n branches and produces a
    # non-empty aggregate, regardless of the branch text the model returns.
    n = 2
    result = await run_parallelization(
        "List key considerations for running LLMs locally.",
        variant="sectioning",
        llm=_ollama_llm(),  # type: ignore[arg-type]
        n=n,
        timeout=LIVE_WORKFLOW_TIMEOUT_SECONDS,
    )
    assert len(result.branches) == n
    assert result.aggregate.strip()


async def test_evaluator_optimizer_against_live_ollama() -> None:
    # Req 8.2 contract level: stop_reason stays inside its closed vocabulary
    # (derived from the contract, not hardcoded) and final_output is non-empty.
    result = await run_evaluator_optimizer(
        "Write a one-sentence definition of edge computing.",
        llm=_ollama_llm(),  # type: ignore[arg-type]
        max_iterations=2,
    )
    assert result.stop_reason in get_args(OptimizationResult.model_fields["stop_reason"].annotation)
    assert result.final_output.strip()


async def test_autonomous_agent_against_live_ollama() -> None:
    # Req 8.2 contract level: the guardrail loop returns a stop_reason inside its
    # closed vocabulary and a non-negative cumulative budget.
    result = await run_autonomous_agent(
        "Answer concisely: what is 2 + 2?",
        llm=_ollama_llm(),  # type: ignore[arg-type]
        max_iterations=3,
        allowed_tools=[_NoopTool()],
        approval_hook=_approve_all,
        budget=1_000_000,
    )
    assert result.stop_reason in get_args(AgentRunResult.model_fields["stop_reason"].annotation)
    assert result.total_budget_spent >= 0
