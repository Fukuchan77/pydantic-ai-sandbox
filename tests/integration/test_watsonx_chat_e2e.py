"""End-to-end ``POST /chat`` test against a real watsonx.ai backend (Task 8 / Task 6).

The opt-in watsonx counterpart to ``test_ollama_chat_e2e.py``. It is the
only test in the suite that round-trips the V2 Beta ``Agent`` +
structured ``output_type`` coercion path through a *live* watsonx.ai
endpoint — for **both** transports the feature ships:

* the ``sdk`` transport's ``ModelInference.achat`` round-trip, and
* the ``litellm`` transport's ``litellm.acompletion()`` routing
  (feature ``003`` / Task 6 / Req 10.3).

Every other watsonx test is hermetic (``FunctionModel`` / httpx
send-patches / RESPX / mocked ``acompletion``), so this file is the
load-bearing E2E proof point for Req 10.

Two lanes live here:

1. :func:`test_post_chat_against_real_watsonx_returns_structured_chat_response`
   — **parametrized over both transports** (``sdk`` / ``litellm``). It
   forces ``WATSONX_TRANSPORT`` per parameter so a single
   ``RUN_INTEGRATION_WATSONX=1`` run exercises *both* transports through
   the full FastAPI ``/chat`` route (Task 7.4: "confirm both ``sdk`` and
   ``litellm`` transports work end-to-end"). It pins the 200 + structured
   :class:`ChatResponse` contract — i.e. the response transformation and
   the ``search_kb`` tool round-trip (the path through which Granite's
   double-encoded tool-call arguments are surfaced, Req 2.4) — identically
   for each transport.
2. :func:`test_litellm_lane_parity_env_routing_and_observability`
   — the **litellm-only** lane. It drives the agent directly with an
   in-memory span exporter so it can assert the contracts a hermetic test
   cannot reach for the live transport (Task 6 bullets):

   * **``WATSONX_PROJECT_ID`` env routing** (ADR-3 / Req 7.2) — the
     *builder* writes the validated project id into ``os.environ`` (the
     ``.env``-loaded-but-not-exported silent-404 class this feature exists
     to kill).
   * **observability parity** — ``gen_ai.system == "watsonx"`` (matching
     the SDK lane, Req 1.4 parity) and ``gen_ai.request.model ==
     "watsonx/<model_id>"`` (the LiteLLM route) on the ``chat`` span.
   ``num_retries=0`` honoring is **deliberately not asserted in this lane**
   (Task 7.4 live finding, see ``do.md``). Two independent reasons make a
   happy-path upstream-POST count unfit for the job:

   1. **The inference call is invisible to ``instrument_httpx``.** LiteLLM
      issues the watsonx chat completion over its own (aiohttp) transport;
      only the auxiliary IAM-token POST rides the ``httpx`` client that
      ``instrument_httpx`` patches. So the inference attempt never surfaces
      as an httpx span — the count comes back ``0``, not ``1``.
   2. **A successful request cannot reveal a retry budget.** Retries fire
      only on a *retryable failure*; on the happy path there is exactly one
      attempt whether ``num_retries`` is ``0`` or ``N``. A success-path count
      therefore cannot distinguish a honored ``num_retries=0`` from a dropped
      one.

   ``num_retries=0`` is instead pinned hermetically by the kwarg-passthrough
   unit test (``acompletion`` receives ``num_retries=0``). Genuinely proving
   *suppression* needs a forced-failure lane — inject a retryable error and
   assert exactly one LiteLLM attempt via a LiteLLM callback (transport-
   agnostic) — which is deferred to future work.

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
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import logfire
import pytest
from fastapi.testclient import TestClient
from logfire.testing import TestExporter
from opentelemetry.sdk.trace.export import SimpleSpanProcessor

from pydantic_ai_sandbox.agents.chat_agent import build_chat_agent
from pydantic_ai_sandbox.api.deps import get_chat_agent
from pydantic_ai_sandbox.config import get_settings
from pydantic_ai_sandbox.llm import get_model
from pydantic_ai_sandbox.main import create_app
from pydantic_ai_sandbox.schemas.chat import ChatResponse

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION_WATSONX") != "1",
    reason=(
        "RUN_INTEGRATION_WATSONX=1 required to opt into the real-watsonx lane "
        "(Req 10.1). Default lane stays network-free per Req 9.10."
    ),
)


# The same tool-inviting prompt the Ollama lane uses: it explicitly asks the
# model to call ``search_kb`` first, driving the tool-call round-trip through
# which a Granite model's double-encoded tool arguments are surfaced (Req 2.4).
_TOOL_PROMPT = (
    "search_kb ツールを呼び出して 'pydantic-ai-v2' を調べ、その結果を踏まえて簡潔に答えてください。"
)


@pytest.mark.parametrize("transport", ["sdk", "litellm"])
def test_post_chat_against_real_watsonx_returns_structured_chat_response(
    transport: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``POST /chat`` yields a valid ``ChatResponse`` for both transports (Task 7.4).

    Parametrized over ``WATSONX_TRANSPORT`` so one ``RUN_INTEGRATION_WATSONX=1``
    run exercises **both** the SDK and LiteLLM transports through the full chain
    against a live watsonx.ai backend (Req 10.2 / 10.3):

    1. ``create_app()`` runs the lifespan, validating env + watsonx
       credentials via :class:`Settings` and bootstrapping observability.
    2. ``GET /healthz`` returns 200 and echoes ``provider == "watsonx"``,
       proving the app is up and routed at the configured provider before
       any LLM traffic (the ``provider`` is ``LLM_PROVIDER`` and so is
       ``"watsonx"`` for *either* transport).
    3. ``POST /chat`` resolves ``Depends(get_chat_agent)`` →
       ``build_chat_agent()`` → ``get_model("watsonx")`` →
       ``_build_watsonx(settings)`` → (``WatsonxSDKModel`` |
       ``_build_litellm``), threads the real watsonx-backed model in (no
       override), and ``await agent.run(message)`` round-trips with the
       endpoint.
    4. ``result.output`` is coerced into :class:`ChatResponse` by Pydantic
       AI's structured-output validator and re-validated here, pinning both
       the route's ``response_model`` serialisation surface and the agent's
       output coercion — i.e. the **response transformation** for the active
       transport.

    The transport is **forced** per parameter (overriding any operator
    ``WATSONX_TRANSPORT``) so the lane is the source of truth for "both
    transports work", not the operator's shell. The cache clears reset both
    ``get_settings`` and ``get_chat_agent`` so the forced transport + the
    operator-supplied real ``WATSONX_*`` / ``LLM_PROVIDER=watsonx``
    environment are observed afresh — earlier unit tests in the same pytest
    process populated those caches against synthetic
    ``watsonx_settings_factory`` values, and stale cache state would
    silently misroute this run to dummy credentials or the wrong transport.
    """
    # Force the transport under test, then reset both lru_cache singletons so
    # the forced value and the operator's real creds are read afresh. Without
    # the resets, an earlier unit test that built a Settings instance with the
    # synthetic WATSONX_TEST_* creds (or a different transport) would leave it
    # pinned in cache and this run would misroute.
    monkeypatch.setenv("WATSONX_TRANSPORT", transport)
    get_settings.cache_clear()
    get_chat_agent.cache_clear()

    settings = get_settings()
    assert settings.llm_provider == "watsonx", (
        "the watsonx integration lane requires LLM_PROVIDER=watsonx so /chat "
        f"routes to _build_watsonx; got {settings.llm_provider!r}. Set "
        "LLM_PROVIDER=watsonx alongside the WATSONX_* credentials."
    )
    assert settings.watsonx_transport == transport, (
        f"forced WATSONX_TRANSPORT={transport!r} was not honored by Settings; "
        f"got {settings.watsonx_transport!r}. A stale get_settings cache or a "
        "shadowing .env value would cause this."
    )

    app = create_app()
    # ``with TestClient(app)`` triggers the lifespan startup so env +
    # credential-gate validation and observability bootstrapping run before
    # any request — bypassing it would mask construction-time failures.
    with TestClient(app) as client:
        # Liveness first — the app is up and tagged with the active provider
        # before any LLM round-trip.
        health = client.get("/healthz")
        assert health.status_code == 200, (
            f"expected 200 from /healthz, got {health.status_code}: {health.text[:500]}"
        )
        assert health.json() == {"status": "ok", "provider": "watsonx"}

        response = client.post("/chat", json={"message": _TOOL_PROMPT})

    assert response.status_code == 200, (
        f"expected 200 from real watsonx backend at {settings.watsonx_url} "
        f"with model {settings.watsonx_model_id} via the "
        f"{settings.watsonx_transport} transport, got "
        f"{response.status_code}: {response.text[:500]}"
    )

    # ``ChatResponse.model_validate`` is the V2 Beta ``output_type`` contract
    # under test (Req 10.2). Re-validating the wire payload pins both the
    # route's ``response_model=ChatResponse`` serialisation and the agent's
    # output coercion; asserting raw JSON keys would let a refactor that drops
    # ``response_model`` silently widen the contract.
    parsed = ChatResponse.model_validate(response.json())
    assert isinstance(parsed.answer, str)
    assert parsed.answer.strip(), (
        "agent returned an empty answer; watsonx may have failed to produce "
        "a structured ChatResponse — inspect the output_type retry budget "
        "and the raw watsonx response."
    )

    # Structural validity of ``sources`` (Req 10.2). Like the SDK lane, this
    # does NOT require ``sources`` to be non-empty: Req 10.2 pins the minimal
    # contract ("ChatResponse structure is valid"), and whether watsonx elects
    # to invoke ``search_kb`` is model-dependent. When it *does* invoke the
    # tool, a clean 200 + valid ChatResponse is the live proof that the
    # tool-call argument round-trip (incl. Granite double-encoded args, Req
    # 2.4) was surfaced and parsed without corruption.
    assert isinstance(parsed.sources, list)
    assert all(isinstance(s, str) for s in parsed.sources), (
        f"search_kb returns list[str] but found non-string entries in "
        f"sources={parsed.sources!r}; investigate V2 tool-result coercion "
        f"or stub return-type drift."
    )


@pytest.fixture
def captured_spans() -> Iterator[TestExporter]:
    """Wire logfire to an in-memory exporter and instrument pydantic-ai + httpx.

    Uses the *bare* :func:`logfire.instrument_pydantic_ai` /
    :func:`logfire.instrument_httpx` (no ``InstrumentationSettings``) — the same
    calls the production ``configure_observability`` makes — so the captured
    span surface matches what ships and the ``chat`` span identity attributes
    (``gen_ai.system`` / ``gen_ai.request.model``) can be asserted against the
    SDK lane.
    """
    exporter = TestExporter()
    logfire.configure(
        send_to_logfire=False,
        console=False,
        additional_span_processors=[SimpleSpanProcessor(exporter)],
    )
    logfire.instrument_pydantic_ai()
    logfire.instrument_httpx()
    yield exporter


def _chat_spans(exporter: TestExporter) -> list[dict[str, Any]]:
    """Return every ``chat`` span (one per model request), by the OTel op attr.

    Filtering on ``gen_ai.operation.name == "chat"`` (rather than the span
    ``name``, which embeds the model id and so is brittle) mirrors
    ``test_watsonx_observability`` / ``test_logging_span_attributes``. A
    tool-calling run legitimately produces more than one ``chat`` span (one to
    decide the tool call, one after the tool result), so this returns the list
    rather than asserting a single span.
    """
    spans = exporter.exported_spans_as_dict(include_resources=False)
    return [s for s in spans if s.get("attributes", {}).get("gen_ai.operation.name") == "chat"]


def test_litellm_lane_parity_env_routing_and_observability(
    monkeypatch: pytest.MonkeyPatch,
    captured_spans: TestExporter,
) -> None:
    """The litellm transport: env routing + observability parity (Task 6 / 7.4).

    Drives the agent **directly** (not via the FastAPI route) so the in-memory
    span exporter wired by :func:`captured_spans` is not clobbered by the app's
    ``configure_observability``. It asserts the four contracts only the live
    LiteLLM lane can prove (Req 10.3):

    * **``WATSONX_PROJECT_ID`` env routing (ADR-3 / Req 7.2).** The id is
      removed from ``os.environ`` before construction — proving the *builder*
      writes it, not that it happened to be exported (a ``.env``-loaded
      deployment leaves it unset in ``os.environ``, LiteLLM's watsonx path reads
      ``os.environ`` directly, and the result is the silent 404 this feature
      exists to kill). ``monkeypatch`` restores the original value on teardown.
    * **Response transformation.** ``result.output`` is a valid
      :class:`ChatResponse` with a non-empty ``answer`` (the
      ``acompletion`` → ``.model_dump()`` → ``build_response`` path produced a
      coercible structured output).
    * **Observability parity (Req 1.4 / 10.6).** The ``chat`` span carries
      ``gen_ai.system == "watsonx"`` (the SAME value the SDK lane stamps — the
      route-derived provider segment, not a hard-coded ``"litellm"``) and
      ``gen_ai.request.model == "watsonx/<model_id>"`` (the LiteLLM route).

    ``num_retries=0`` honoring is **not** asserted here — see the module
    docstring for why a happy-path upstream-POST count cannot prove it (LiteLLM's
    inference call rides an aiohttp transport invisible to ``instrument_httpx``,
    and a successful request reveals no retry budget). It is pinned hermetically
    by the kwarg-passthrough unit test; a forced-failure live lane is future work.
    """
    monkeypatch.setenv("WATSONX_TRANSPORT", "litellm")
    get_settings.cache_clear()
    get_chat_agent.cache_clear()

    settings = get_settings()
    assert settings.llm_provider == "watsonx", (
        "the watsonx integration lane requires LLM_PROVIDER=watsonx; got "
        f"{settings.llm_provider!r}."
    )
    assert settings.watsonx_transport == "litellm"
    # The boot credential gate guarantees these are present when watsonx is
    # selected; assert so the env-routing / route assertions below read a
    # concrete value rather than ``None``.
    assert settings.watsonx_project_id is not None
    assert settings.watsonx_model_id is not None

    # WATSONX_PROJECT_ID env routing (ADR-3): delete it from os.environ first so
    # the post-build assertion proves the builder wrote it (raising=False — it
    # may live only in the operator's .env, never exported, which is exactly the
    # case ADR-3 reconciles). monkeypatch restores the original on teardown.
    monkeypatch.delenv("WATSONX_PROJECT_ID", raising=False)
    model = get_model("watsonx")
    assert os.environ.get("WATSONX_PROJECT_ID") == settings.watsonx_project_id, (
        "_build_litellm must reconcile WATSONX_PROJECT_ID into os.environ for "
        "LiteLLM's watsonx path (ADR-3); it was not set after construction. A "
        ".env-only project id would otherwise leave LiteLLM unable to route and "
        "produce a silent 404."
    )
    # Property-level parity (also asserted on the span below): the route is the
    # watsonx-prefixed model id and the system segment is "watsonx".
    assert model.system == "watsonx"
    assert model.model_name == f"watsonx/{settings.watsonx_model_id}"

    agent = build_chat_agent(model=model)
    result = agent.run_sync(_TOOL_PROMPT)

    # Response transformation: a coercible, non-empty structured output.
    assert isinstance(result.output, ChatResponse)
    assert result.output.answer.strip(), (
        "litellm transport produced an empty answer; inspect the "
        "acompletion → model_dump → build_response path and the raw response."
    )

    chat_spans = _chat_spans(captured_spans)
    assert chat_spans, (
        "no 'chat' span was captured for the litellm run; instrument_pydantic_ai "
        "did not see the request — the run may not have reached the model."
    )

    # Observability parity (Req 1.4 / 10.6): the first chat span's identity
    # attributes match the SDK lane. ``gen_ai.provider.name`` is the >=1.30 key
    # and ``gen_ai.system`` the legacy alias; reading either keeps the assertion
    # tolerant of the deprecation while failing loud if BOTH vanish.
    chat_attrs = chat_spans[0]["attributes"]
    provider_attr = chat_attrs.get("gen_ai.provider.name") or chat_attrs.get("gen_ai.system")
    assert provider_attr == "watsonx", (
        f"litellm chat span must stamp gen_ai.system == 'watsonx' (parity with "
        f"the SDK lane, Req 1.4), not the route prefix or 'litellm'; attrs={chat_attrs}"
    )
    request_model = chat_attrs.get("gen_ai.request.model")
    assert request_model == f"watsonx/{settings.watsonx_model_id}", (
        f"litellm chat span gen_ai.request.model must be the LiteLLM route "
        f"'watsonx/{settings.watsonx_model_id}'; got {request_model!r}, attrs={chat_attrs}"
    )
