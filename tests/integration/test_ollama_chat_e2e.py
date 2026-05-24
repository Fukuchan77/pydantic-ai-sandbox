"""End-to-end ``POST /chat`` test against a real Ollama daemon (Task 11.1).

Covers Req 3.5, 6.2, 10.3 — the only test in the MVP that proves the V2
Beta ``Agent`` + structured ``output_type`` coercion path round-trips
through a real LLM backend. Every other test in the suite uses
``TestModel`` / ``FunctionModel`` overrides (Req 10.2 network-free
discipline), so this file is the load-bearing E2E proof point.

Gating contract:

* ``RUN_INTEGRATION_OLLAMA=1`` MUST be set, otherwise the entire module
  is skipped via ``pytestmark`` (plan.md AD-5). The default ``mise run
  test`` lane never reaches this code.
* When the gate is on, ``OLLAMA_BASE_URL`` reachability is checked
  eagerly. **Unreachable Ollama is reported as a test FAILURE, not a
  skip** — the spec text in tasks.md T11.1 is explicit ("skip ではなく
  fail; CI lane の前提なので"). A skip here would let a broken CI lane
  appear green.

What is exercised:

1. ``create_app()`` lifespan: ``get_settings()`` env validation +
   ``configure_observability(...)`` (Logfire fail-soft path) + router
   registration.
2. The ``POST /chat`` route: ``Depends(get_chat_agent)`` →
   ``build_chat_agent()`` → ``get_model("ollama")`` →
   ``_build_ollama(settings)`` → ``OpenAIChatModel(provider=
   OllamaProvider(...))``.
3. The V2 Beta surface: ``await agent.run(req.message)`` and
   ``result.output`` coerced into :class:`ChatResponse` by Pydantic AI's
   structured-output validator.
4. The ``search_kb`` tool stub: the prompt explicitly asks the model to
   invoke knowledge-base search, so ``sources`` should contain at least
   one ``"kb-stub:<query>"`` entry. Real LLM nondeterminism is the
   typical failure surface here; that is the integration lane's job to
   surface.

Why a single test, not a parametrized matrix: tasks.md T11.1 lists one
sub-task with one scenario (200 + ChatResponse + non-empty sources).
Adding lower-confidence scenarios (e.g., long prompts, tool retries)
belongs in a follow-up lane and is out of scope for the MVP per
spec.md "Out of Scope".
"""

from __future__ import annotations

import os

import httpx
import pytest
from fastapi.testclient import TestClient

from pydantic_ai_sandbox.api.deps import get_chat_agent
from pydantic_ai_sandbox.config import get_settings
from pydantic_ai_sandbox.main import create_app
from pydantic_ai_sandbox.schemas.chat import ChatResponse

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION_OLLAMA") != "1",
    reason=(
        "RUN_INTEGRATION_OLLAMA=1 required to opt into the real-Ollama lane "
        "(plan.md AD-5). Default lane stays network-free per Req 10.2."
    ),
)


def _require_ollama_reachable(base_url: str) -> None:
    """Hard-precondition check: fail (not skip) when Ollama is unreachable.

    The ``RUN_INTEGRATION_OLLAMA=1`` gate already promised an operator-
    committed integration run (tasks.md T11.1: "skip ではなく fail; CI
    lane の前提"). Reporting a skip here would silently mask a broken
    CI lane — every reachable-but-unhealthy state must surface as a
    failure in the lane's summary.

    The probe targets ``<base_url>/models``: ``Settings.ollama_base_url``
    is the **OpenAI-compatible** surface (e.g. ``http://localhost:11434/v1``)
    that :class:`OllamaProvider` hands directly to ``AsyncOpenAI``. The
    OpenAI list-models endpoint lives at ``/models`` relative to that
    base, and Ollama implements it (``GET /v1/models`` returns the
    pulled-model catalogue). Probing ``/api/version`` would mistarget
    Ollama's *native* API which lives one level above ``/v1`` and would
    404 whenever the operator follows the canonical ``OLLAMA_BASE_URL``
    documented in ``.env.example``.

    Args:
        base_url: The ``Settings.ollama_base_url`` value (already
            stringified — pydantic ``HttpUrl`` carries a trailing slash
            so ``rstrip('/')`` normalises before joining).
    """
    probe_url = f"{base_url.rstrip('/')}/models"
    try:
        response = httpx.get(probe_url, timeout=5.0)
    except httpx.RequestError as exc:
        pytest.fail(
            f"Ollama unreachable at {probe_url}: {exc!r}. "
            f"The integration lane requires a running Ollama daemon — "
            f"start it with `ollama serve` and pull the configured model.",
        )
    if response.status_code != 200:
        pytest.fail(
            f"Ollama at {probe_url} returned HTTP {response.status_code}; "
            f"the daemon is not in a healthy state for the integration run. "
            f"Body: {response.text[:200]!r}",
        )


def test_post_chat_against_real_ollama_returns_structured_chat_response() -> None:
    """``POST /chat`` against real Ollama yields a ``ChatResponse`` with sources.

    The full chain is exercised end-to-end:

    1. ``create_app()`` runs the lifespan, validating env via
       :class:`Settings` and bootstrapping observability.
    2. The route resolves ``Depends(get_chat_agent)``, which calls
       ``build_chat_agent()`` and threads the real Ollama-backed model
       in (no override — this is the only test in the suite where the
       agent talks to a real backend).
    3. ``await agent.run(message)`` round-trips with the daemon; the
       returned ``result.output`` is a :class:`ChatResponse` instance,
       and FastAPI serialises it via ``response_model=ChatResponse``.
    4. The prompt explicitly invites a knowledge-base search, so the
       agent's instructions ("知識ベース検索が必要な場合は ``search_kb``
       ツールを呼び出してから回答してください") drive the model to
       invoke the stub, which echoes ``"kb-stub:<query>"`` back into
       :attr:`ChatResponse.sources`.

    The cache clears at the top reset both ``get_settings`` and
    ``get_chat_agent`` so the integration env (operator-supplied real
    ``OLLAMA_*`` values) is observed afresh — earlier unit tests in the
    same pytest process populated those caches against synthetic test
    settings, and stale cache state would silently misroute this run
    to a dummy Ollama URL.
    """
    # Reset both lru_cache singletons before reading the operator-supplied
    # environment. Without these resets, an earlier unit test that called
    # settings_factory(LLM_PROVIDER='ollama', OLLAMA_MODEL_NAME='dummy-...')
    # would leave a Settings instance pinned to the dummy values in cache,
    # and the integration test would route to a non-existent host.
    get_settings.cache_clear()
    get_chat_agent.cache_clear()

    settings = get_settings()
    _require_ollama_reachable(str(settings.ollama_base_url))

    app = create_app()
    # ``with TestClient(app)`` triggers the lifespan startup (Req 1.4 / 4.5
    # / 5.1 chain). Bypassing it would leave observability uninitialised
    # and miss any provider-construction issues that the dry-run catches.
    with TestClient(app) as client:
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
        f"expected 200 from real Ollama backend at {settings.ollama_base_url} "
        f"with model {settings.ollama_model_name}, got "
        f"{response.status_code}: {response.text[:500]}"
    )

    # ``ChatResponse.model_validate`` is the V2 Beta ``output_type``
    # contract under test (Req 6.2). Asserting on raw JSON keys would
    # let a future refactor that drops ``response_model=ChatResponse``
    # silently widen the wire contract — this round-trip pins both the
    # route's serialisation surface and the agent's output coercion.
    parsed = ChatResponse.model_validate(response.json())
    assert isinstance(parsed.answer, str)
    assert parsed.answer.strip(), (
        "agent returned an empty answer; the model may have failed to "
        "produce a structured ChatResponse — check Ollama logs for the "
        "raw response and inspect the output_type retry budget."
    )

    # Req 6.2 + tasks.md T11.1: sources must be non-empty AND every entry
    # must be a string (search_kb returns list[str]). A non-string entry
    # would indicate either schema drift in the stub or a bug in V2's
    # tool-result coercion path.
    assert isinstance(parsed.sources, list)
    assert parsed.sources, (
        "expected ``sources`` to contain at least one entry from the "
        "search_kb stub (Req 6.2). The model did not invoke the tool — "
        "this is the typical failure mode for under-instructed models. "
        "Review the agent instructions in agents/chat_agent.py and the "
        "Ollama logs for the tool-call decision."
    )
    assert all(isinstance(s, str) for s in parsed.sources), (
        f"search_kb stub returns list[str] but found non-string entries "
        f"in sources={parsed.sources!r}; investigate V2 tool-result "
        f"coercion or stub return-type drift."
    )
