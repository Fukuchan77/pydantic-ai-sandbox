"""Gated Ollama integration tests (Spec 005 Req 5).

Skipped unless ``RUN_INTEGRATION_PATTERNS=1``. Assertions stay at the
contract level (route within vocabulary, >=1 worker result, non-empty
summary) — never exact text (Req 5.2). Model identity comes exclusively
from ``OLLAMA_BASE_URL`` / ``OLLAMA_MODEL_NAME`` (Req 5.3 / Req 1.5).
"""

from __future__ import annotations

import os
from typing import get_args

import pytest

from patterns_pydantic_ai.contracts import Route
from patterns_pydantic_ai.orchestrator_workers import run_orchestrator
from patterns_pydantic_ai.routing import run_routing

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION_PATTERNS") != "1",
    reason="integration lane gated by RUN_INTEGRATION_PATTERNS=1",
)


def _ollama_model() -> object:
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.ollama import OllamaProvider

    model_name = os.environ["OLLAMA_MODEL_NAME"]
    base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1")
    return OpenAIChatModel(model_name=model_name, provider=OllamaProvider(base_url=base_url))


async def test_routing_against_live_ollama() -> None:
    model = _ollama_model()
    result = await run_routing("I was billed twice for my subscription this month.", model=model)  # type: ignore[arg-type]
    assert result.route in get_args(Route)
    assert result.answer.strip()


async def test_orchestrator_against_live_ollama() -> None:
    model = _ollama_model()
    result = await run_orchestrator(
        "List two advantages and two disadvantages of local LLM inference.",
        model=model,  # type: ignore[arg-type]
        max_workers=2,
    )
    assert len(result.results) >= 1
    assert result.summary.strip()
