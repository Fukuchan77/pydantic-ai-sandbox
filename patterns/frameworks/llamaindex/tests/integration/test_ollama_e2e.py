"""Gated Ollama integration tests (Spec 005 Req 5).

Skipped unless ``RUN_INTEGRATION_PATTERNS=1``. Contract-level assertions
only (Req 5.2); model identity from env only (Req 5.3 / 1.5).
"""

from __future__ import annotations

import os
from typing import get_args

import pytest

from patterns_llamaindex.contracts import Route
from patterns_llamaindex.orchestrator_workers import run_orchestrator
from patterns_llamaindex.routing import run_routing

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION_PATTERNS") != "1",
    reason="integration lane gated by RUN_INTEGRATION_PATTERNS=1",
)


def _ollama_llm() -> object:
    from llama_index.llms.ollama import Ollama  # pyright: ignore[reportMissingTypeStubs]

    # llama-index expects the daemon root URL; the repo-wide convention is
    # an OpenAI-style base ending in /v1, so strip it when present.
    base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1")
    base_url = base_url.removesuffix("/v1")
    return Ollama(
        model=os.environ["OLLAMA_MODEL_NAME"],
        base_url=base_url,
        request_timeout=180.0,
    )


async def test_routing_against_live_ollama() -> None:
    result = await run_routing(
        "I was billed twice for my subscription this month.",
        llm=_ollama_llm(),  # type: ignore[arg-type]
    )
    assert result.route in get_args(Route)
    assert result.answer.strip()


async def test_orchestrator_against_live_ollama() -> None:
    result = await run_orchestrator(
        "List two advantages and two disadvantages of local LLM inference.",
        llm=_ollama_llm(),  # type: ignore[arg-type]
        max_workers=2,
    )
    assert len(result.results) >= 1
    assert result.summary.strip()
