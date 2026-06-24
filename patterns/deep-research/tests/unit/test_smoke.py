"""Smoke + hermetic-guard tests for the Deep Research lane (Spec 009 Req 1.1/1.3, 8.1).

Three concerns live here:

* the lane package ``patterns_deep_research`` imports cleanly;
* importing it pulls in **no sibling lane** (NFR-3) — contract sharing flows only
  through the ``patterns_contracts`` path dependency;
* a *fake one-pass* through the whole pipeline (``run_deep_research`` driven by a
  ``TestModel`` and the ``FakeSearchProvider``) completes with zero network I/O
  under the autouse ``block_network`` guard, and a load-bearing case proves the
  guard actually fires.
"""

from __future__ import annotations

import importlib
import socket
import sys

import pytest
from patterns_contracts import ResearchReport

from patterns_deep_research import run_deep_research
from tests.support.fake_search import FakeSearchProvider
from tests.support.hermetic import NetworkReachError
from tests.support.model_fakes import plan_payload, scripted_model

SIBLING_LANES = frozenset(
    {
        "patterns_pydantic_ai",
        "patterns_beeai",
        "patterns_llamaindex",
        "patterns_rag",
        "patterns_sse",
    }
)


def test_patterns_deep_research_imports() -> None:
    import patterns_deep_research

    assert patterns_deep_research.__name__ == "patterns_deep_research"


def test_no_sibling_lane_imports() -> None:
    importlib.import_module("patterns_deep_research")

    leaked = SIBLING_LANES & set(sys.modules)
    assert not leaked, f"deep-research lane must not import sibling lanes: {sorted(leaked)}"


def test_block_network_guard_loud_fails_on_internet_connect() -> None:
    # Load-bearing proof the autouse guard is not vacuous: a real AF_INET connect
    # is intercepted before any I/O (a loopback closed port would otherwise raise
    # ConnectionRefusedError).
    with (
        socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock,
        pytest.raises(NetworkReachError),
    ):
        sock.connect(("127.0.0.1", 9))


async def test_fake_one_pass_runs_hermetically() -> None:
    # Full pipeline under the guard: run_deep_research over a scripted FunctionModel
    # + FakeSearchProvider, all offline. The scripted finding cites a real corpus
    # source so the run produces a grounded report. (TestModel is unsuitable for the
    # full pass: it emits arbitrary cited_sources that fail grounding by design.)
    model = scripted_model(plan=plan_payload(["What is the lead/sub-researcher split?"]))
    report = await run_deep_research(
        "What are the trade-offs of multi-agent research systems?",
        model=model,
        search=FakeSearchProvider(),
        max_researchers=2,
        max_iterations=2,
    )
    assert isinstance(report, ResearchReport)
    assert report.report
    assert report.citations  # grounded in a real corpus source
