"""Gated Ollama integration tests for the HITL stop/approve/resume flow (Task 8.1).

Skipped unless ``RUN_INTEGRATION_PATTERNS=1``. Drives the real ``create_app``
app-factory (the same DI seam Task 6's hermetic tests use, plan.md HitlApp)
with a live Ollama model behind ``build_agent``, over ``httpx.ASGITransport``
-- no real network hop, but a real model completion. Two cases, matching this
lane's ``EXPECT_LIVE_TESTS=2`` (mise.toml, Task 7.1):

* an approval path: ``/run`` stops on an approval-gated tool call, ``/resume``
  approves it, and the run reaches a terminal ``SupportOutput``.
* a denial path: the same stop, but ``/resume`` denies the tool call and the
  run still reaches a terminal ``SupportOutput`` -- the tool never executes.

The prompt asks for a concrete ``apply_discount`` action with an amount well
above ``HitlSettings.risk_threshold_usd`` (default $50), the same
tool-forcing shape the hermetic ``FunctionModel``/``TestModel`` suites use
(``tests/support/function_model_scripts.apply_discount_call``), rather than a
free-form request -- this is what makes a live model's tool choice reliable
enough for an e2e assertion. Assertions stay at the contract level (has the
run reached a terminal answer with non-empty prose); the model's exact
wording is never asserted, since it is inherently non-deterministic.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import httpx
import pytest
from patterns_contracts import SupportOutput

from patterns_hitl.agent import build_agent
from patterns_hitl.app import create_app
from patterns_hitl.store import SessionStore

if TYPE_CHECKING:
    from collections.abc import Callable

    from pydantic_ai.models import Model

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION_PATTERNS") != "1",
    reason="integration lane gated by RUN_INTEGRATION_PATTERNS=1",
)

# A resumed run whose tool remains approval-gated can re-defer under the same
# session (plan.md R6.1); this bounds how many /resume round-trips a test
# drives before treating a still-pending run as a failure.
_MAX_RESUME_ROUND_TRIPS = 5

_DISCOUNT_PROMPT = (
    "Apply a $500.00 discount to customer cust-1's account to resolve a duplicate billing charge."
)


def _ollama_model() -> Model:
    """Build the Ollama-backed model from the environment (Req 12.1 / model-ID hygiene)."""
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.ollama import OllamaProvider

    # OpenAI-compatible /v1 path uses the server's default num_ctx (not the
    # model maximum), so this lane needs no context_window bound to avoid the
    # KV-cache OOM the llama-index lanes guard against (matches
    # patterns/sse and patterns/frameworks/pydantic-ai's live tests).
    model_name = os.environ["OLLAMA_MODEL_NAME"]
    base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1")
    return OpenAIChatModel(model_name=model_name, provider=OllamaProvider(base_url=base_url))


async def _run_until_completed(
    client: httpx.AsyncClient,
    prompt: str,
    decide: Callable[[dict[str, Any]], dict[str, Any]],
) -> dict[str, Any]:
    """Drive ``/run`` then ``/resume`` against a live agent until it completes.

    Args:
        client: An HTTP client bound to the app under test.
        prompt: The initial ``/run`` prompt.
        decide: Maps one ``approvals`` entry to the ``Decision`` payload this
            call sends back for it (an approval or a denial).

    Returns:
        The final response body, once its ``status`` is ``"completed"``.
    """
    response = await client.post("/run", json={"prompt": prompt})
    assert response.status_code == 200
    body: dict[str, Any] = response.json()
    assert body["status"] == "pending_approval", (
        f"the live model was expected to require approval, got: {body}"
    )
    for _ in range(_MAX_RESUME_ROUND_TRIPS):
        decisions = {approval["tool_call_id"]: decide(approval) for approval in body["approvals"]}
        response = await client.post(
            "/resume", json={"session_id": body["session_id"], "decisions": decisions}
        )
        assert response.status_code == 200
        body = response.json()
        if body["status"] == "completed":
            return body
    pytest.fail(
        f"run did not reach a completed answer after {_MAX_RESUME_ROUND_TRIPS} "
        f"resume round-trips: {body}"
    )


async def test_hitl_approval_path_against_live_ollama() -> None:
    """Approval e2e: stop -> approve -> resume -> terminal SupportOutput."""
    app = create_app(agent=build_agent(_ollama_model()), store=SessionStore(), instrument=False)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://hitl") as client:
        body = await _run_until_completed(
            client, _DISCOUNT_PROMPT, lambda _approval: {"approved": True}
        )

    output = SupportOutput.model_validate(body["output"])
    assert output.summary_of_issue.strip()
    assert output.reasoning.strip()


async def test_hitl_denial_path_against_live_ollama() -> None:
    """Denial e2e: stop -> deny -> resume -> alternative terminal SupportOutput."""
    app = create_app(agent=build_agent(_ollama_model()), store=SessionStore(), instrument=False)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://hitl") as client:
        body = await _run_until_completed(
            client,
            _DISCOUNT_PROMPT,
            lambda _approval: {
                "approved": False,
                "message": "policy: amount exceeds approval limit",
            },
        )

    output = SupportOutput.model_validate(body["output"])
    assert output.summary_of_issue.strip()
    assert output.reasoning.strip()
