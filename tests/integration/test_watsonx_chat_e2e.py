"""End-to-end ``POST /chat`` test against a real watsonx.ai backend (Task 8).

The opt-in watsonx counterpart to ``test_ollama_chat_e2e.py``. It is the
only test in the suite that round-trips the V2 Beta ``Agent`` +
structured ``output_type`` coercion path through a *live* watsonx.ai
endpoint (the SDK transport's ``ModelInference.achat`` round-trip, or the
litellm transport's OpenAI-compatible POST, depending on
``WATSONX_TRANSPORT``). Every other watsonx test is hermetic
(``FunctionModel`` / httpx send-patches / RESPX), so this file is the
load-bearing E2E proof point for Req 10.

Gating contract (Req 10.1, plan.md AD-5 mirror):

* ``RUN_INTEGRATION_WATSONX=1`` MUST be set, otherwise the entire module
  is skipped via ``pytestmark``. The default ``mise run test`` lane never
  reaches this code, keeping the suite network-free (Req 9.10 / SC-002).
* When the gate is on, the operator is committing to a live run. Missing
  credentials do **not** skip: ``get_settings()`` runs the watsonx
  credential gate (Task 2.2) and raises ``ValueError`` naming the absent
  variable, which surfaces as a test ERROR (a failure), not a skip. A
  broken integration lane must never appear green — the same fail-not-skip
  posture the Ollama lane enforces with its reachability probe.

Why no eager reachability probe (unlike the Ollama lane): Ollama is a
*local daemon* that may simply not be running, so its lane probes
``/v1/models`` to convert "process down" into an explicit failure.
watsonx.ai is a *hosted SaaS* endpoint with no equivalent unauthenticated
liveness surface, and construction is I/O-free by contract (Req 1.5) — the
first network hit is the ``/chat`` request itself. A misconfigured or
unreachable endpoint therefore surfaces as the ``/chat`` route returning
HTTP 500 (the wrapped ``ModelAPIError`` propagates: ``LLM_PROVIDER=watsonx``
is a *direct* selection with no fallback to recover it), which fails the
``status_code == 200`` assertion below. The ``/chat`` round-trip is thus
its own liveness check — no separate probe is needed.

Statelessness (Req 10.3 / SC-021): watsonx.ai chat completions in scope
are stateless single requests, so there is deliberately no
resource-cleanup logic — nothing is created that must be torn down.

What is exercised:

1. ``create_app()`` lifespan: ``get_settings()`` env + credential-gate
   validation and ``configure_observability(...)``.
2. ``GET /healthz`` → 200, tagged with the active ``watsonx`` provider
   (Task 8.2).
3. ``POST /chat`` → 200 with a structurally valid :class:`ChatResponse`
   (Task 8.2 / Req 10.2): the agent's ``output_type`` coercion and the
   route's ``response_model=ChatResponse`` are pinned end-to-end against a
   real watsonx response.
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from pydantic_ai_sandbox.api.deps import get_chat_agent
from pydantic_ai_sandbox.config import get_settings
from pydantic_ai_sandbox.main import create_app
from pydantic_ai_sandbox.schemas.chat import ChatResponse

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION_WATSONX") != "1",
    reason=(
        "RUN_INTEGRATION_WATSONX=1 required to opt into the real-watsonx lane "
        "(Req 10.1). Default lane stays network-free per Req 9.10."
    ),
)


def test_post_chat_against_real_watsonx_returns_structured_chat_response() -> None:
    """``GET /healthz`` is 200 and ``POST /chat`` yields a valid ``ChatResponse``.

    The full chain is exercised end-to-end against a live watsonx.ai
    backend (Req 10.2):

    1. ``create_app()`` runs the lifespan, validating env + watsonx
       credentials via :class:`Settings` and bootstrapping observability.
    2. ``GET /healthz`` returns 200 and echoes ``provider == "watsonx"``,
       proving the app is up and routed at the configured provider before
       any LLM traffic (Task 8.2).
    3. The ``POST /chat`` route resolves ``Depends(get_chat_agent)`` →
       ``build_chat_agent()`` → ``get_model("watsonx")`` →
       ``_build_watsonx(settings)``, threads the real watsonx-backed model
       in (no override), and ``await agent.run(message)`` round-trips with
       the endpoint.
    4. ``result.output`` is coerced into :class:`ChatResponse` by Pydantic
       AI's structured-output validator and re-validated here, pinning both
       the route's ``response_model`` serialisation surface and the agent's
       output coercion (Req 10.2 "ChatResponse structure is valid").

    The cache clears at the top reset both ``get_settings`` and
    ``get_chat_agent`` so the operator-supplied real ``WATSONX_*`` /
    ``LLM_PROVIDER=watsonx`` environment is observed afresh — earlier unit
    tests in the same pytest process populated those caches against
    synthetic ``watsonx_settings_factory`` values, and stale cache state
    would silently misroute this run to dummy credentials.
    """
    # Reset both lru_cache singletons before reading the operator-supplied
    # environment. Without these resets, an earlier unit test that built a
    # Settings instance with the synthetic WATSONX_TEST_* creds (or a
    # non-watsonx LLM_PROVIDER) would leave it pinned in cache, and this
    # run would route to dummy values rather than the live endpoint.
    get_settings.cache_clear()
    get_chat_agent.cache_clear()

    settings = get_settings()
    assert settings.llm_provider == "watsonx", (
        "the watsonx integration lane requires LLM_PROVIDER=watsonx so /chat "
        f"routes to _build_watsonx; got {settings.llm_provider!r}. Set "
        "LLM_PROVIDER=watsonx alongside the WATSONX_* credentials."
    )

    app = create_app()
    # ``with TestClient(app)`` triggers the lifespan startup so env +
    # credential-gate validation and observability bootstrapping run before
    # any request — bypassing it would mask construction-time failures.
    with TestClient(app) as client:
        # Task 8.2: liveness first — the app is up and tagged with the
        # active provider before any LLM round-trip.
        health = client.get("/healthz")
        assert health.status_code == 200, (
            f"expected 200 from /healthz, got {health.status_code}: {health.text[:500]}"
        )
        assert health.json() == {"status": "ok", "provider": "watsonx"}

        response = client.post(
            "/chat",
            json={
                "message": (
                    "search_kb ツールを呼び出して 'pydantic-ai-v2' を調べ、"
                    "その結果を踏まえて簡潔に答えてください。"
                ),
            },
        )

    assert response.status_code == 200, (
        f"expected 200 from real watsonx backend at {settings.watsonx_url} "
        f"with model {settings.watsonx_model_id} via the "
        f"{settings.watsonx_transport} transport, got "
        f"{response.status_code}: {response.text[:500]}"
    )

    # ``ChatResponse.model_validate`` is the V2 Beta ``output_type``
    # contract under test (Req 10.2). Re-validating the wire payload pins
    # both the route's ``response_model=ChatResponse`` serialisation and the
    # agent's output coercion; asserting raw JSON keys would let a refactor
    # that drops ``response_model`` silently widen the contract.
    parsed = ChatResponse.model_validate(response.json())
    assert isinstance(parsed.answer, str)
    assert parsed.answer.strip(), (
        "agent returned an empty answer; watsonx may have failed to produce "
        "a structured ChatResponse — inspect the output_type retry budget "
        "and the raw watsonx response."
    )

    # Structural validity of ``sources`` (Req 10.2). Unlike the Ollama lane,
    # this lane does NOT require ``sources`` to be non-empty: Req 10.2 pins
    # the minimal contract ("ChatResponse structure is valid"), and whether
    # watsonx elects to invoke ``search_kb`` is model-dependent. The
    # list[str] shape is what the schema guarantees and is asserted; the
    # tool-invocation behaviour is the hermetic suite's concern (Task 7.6),
    # not the live lane's.
    assert isinstance(parsed.sources, list)
    assert all(isinstance(s, str) for s in parsed.sources), (
        f"search_kb returns list[str] but found non-string entries in "
        f"sources={parsed.sources!r}; investigate V2 tool-result coercion "
        f"or stub return-type drift."
    )
