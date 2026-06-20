"""Gated Ollama integration test for the Deep Research lane (Spec 009 Req 8.3, 9).

Skipped unless ``RUN_INTEGRATION_PATTERNS=1``. The single end-to-end test drives
the full ``run_deep_research`` pipeline against a *real* Ollama model, with the
deterministic ``FakeSearchProvider`` injected by default (live model x fake
search): web search is non-deterministic and network-bound, so a live search
backend is exercised only behind the second flag ``RUN_INTEGRATION_SEARCH=1``.

Assertions stay at the **contract** level (a ``ResearchReport`` with >=1 finding,
>=1 citation, and >=1 span from the injected instrumentation); exact text is never
asserted because a live model is non-deterministic — determinism is the offline
fakes' job, not this lane's. The framework-agnostic lane src reaches the model
only through the ``model`` DI seam, built here from pydantic-ai directly (a
dev/integration-only dependency).
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from patterns_contracts import LIVE_MAX_TOKENS, ResearchReport
from pydantic_ai.models.instrumented import InstrumentationSettings

from patterns_deep_research import load_search_provider, run_deep_research
from patterns_deep_research.observability import configure_tracing
from tests.support.fake_search import FakeSearchProvider

if TYPE_CHECKING:
    from pydantic_ai.models import Model

    from patterns_deep_research import SearchProvider

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION_PATTERNS") != "1",
    reason="integration lane gated by RUN_INTEGRATION_PATTERNS=1",
)

_QUERY = "What are the trade-offs of multi-agent research systems versus a single agent?"


def _ollama_model() -> Model:
    """Build the Ollama-backed model from the environment (model-ID hygiene)."""
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.ollama import OllamaProvider
    from pydantic_ai.settings import ModelSettings

    # OpenAI-compatible /v1 path uses the server's default num_ctx, so this lane
    # needs no context_window bound. Cap generation so each call returns promptly
    # under CPU contention (patterns_contracts.live_ollama).
    model_name = os.environ["OLLAMA_MODEL_NAME"]
    base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1")
    return OpenAIChatModel(
        model_name=model_name,
        provider=OllamaProvider(base_url=base_url),
        settings=ModelSettings(max_tokens=LIVE_MAX_TOKENS),
    )


def _search_provider() -> SearchProvider:
    """Use a live search backend only when RUN_INTEGRATION_SEARCH=1; else the fake."""
    if os.environ.get("RUN_INTEGRATION_SEARCH") == "1":
        return load_search_provider()
    return FakeSearchProvider()


async def test_deep_research_against_live_ollama() -> None:
    exporter = InMemorySpanExporter()
    provider = configure_tracing(exporter)
    instrumentation = InstrumentationSettings(tracer_provider=provider)

    report = await run_deep_research(
        _QUERY,
        model=_ollama_model(),
        search=_search_provider(),
        max_researchers=2,
        max_iterations=2,
        instrumentation=instrumentation,
    )

    # Contract shape, not the live model's exact words.
    assert isinstance(report, ResearchReport)
    assert report.report, "the live run must produce a non-empty report"
    assert report.findings, "the live run must produce at least one finding"
    assert report.citations, "the report must be grounded in at least one citation"
    # Instrumentation produced gen_ai.* spans across the pipeline (attributes not asserted).
    assert exporter.get_finished_spans(), "instrumented run must produce >=1 span (Req 9)"
