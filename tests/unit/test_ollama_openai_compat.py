"""Hermetic Ollama OpenAI-compatible request-path contract (Spec 014 R2.1/R2.2/R2.4).

`pydantic-ai-slim[openai]` + `litellm` have no overlapping `openai` SDK range
(ADR-2 in `pyproject.toml`), so the root project runs an *upstream-unsupported*
combination: `pydantic-ai-slim` held on its hub-verified floor paired with an
`openai` SDK 2.x. This module is the executable evidence that the one path
the sandbox actually exercises — `OllamaProvider -> OllamaModel (an
`OpenAIChatModel` subclass) -> Agent.run()` posting a non-streaming Chat
Completions request — still round-trips correctly under that combination,
plus the explicit version-floor/ceiling bounds that make the combination
well-defined in the first place.

Two independent contracts live here:

1. **Request-path compatibility** (`test_ollama_chat_completion_*`): a fake
   transport stands in for the Ollama daemon's OpenAI-compatible endpoint, so
   the actual installed `openai` SDK serializes the request and parses the
   response — no network, no real daemon. This exercises the *installed* SDK
   version directly, which makes it green against the *current*
   (post-Task-2.2) dependency floor, but it is **not** green against the
   pre-Task-2.2 floor (`pydantic-ai-slim>=2.31.1`): the monkeypatch target
   below (`create_async_httpx2_client`) does not exist in that older
   `pydantic_ai.providers._openai_compatible` module at all, so these tests
   would ERROR at fixture setup, not merely fail an assertion, on that older
   floor. It alone cannot carry this task's red evidence (plan.md DES-2.2);
   the version floor/ceiling tests below carry that.

   The fake transport is `httpx2.MockTransport`, not `respx`. As of
   `pydantic-ai-slim` 2.54.0, `OpenAICompatibleProvider._get_http_client()`
   (used by every OpenAI-compatible provider, including `OllamaProvider`)
   builds its own client via `create_async_httpx2_client()` when the caller
   does not pass an explicit `http_client` — which the sandbox's
   `OllamaProvider` construction never does
   (`src/pydantic_ai_sandbox/llm/providers/ollama.py`). That factory returns
   an `httpx2.AsyncClient`, a *separate* HTTP stack from legacy `httpx`
   (confirmed: `httpx2`/`httpcore2` are independent PyPI packages pulled in
   transitively by `pydantic-ai-slim`, coexisting with legacy `httpx` during
   an ecosystem transition — see `docs/hub-intake-2026-10.md`'s unrelated
   starlette/`TestClient` httpx2 note for the same transition observed
   elsewhere in this project). `respx` 0.23.1 (confirmed latest on PyPI as of
   2026-10-03) only patches legacy `httpx`, so a respx-mocked route is
   silently bypassed under this client and the test hits a real (failing)
   connection instead. `httpx2.MockTransport` is httpx2's own built-in,
   dependency-free mock transport — the direct httpx2 analogue of
   `httpx.MockTransport` — and needs no third-party package. The
   `ollama_model` fixture below monkeypatches
   `create_async_httpx2_client` at its import site in
   `pydantic_ai.providers._openai_compatible` (not at its definition site in
   `pydantic_ai._http`, since that module already bound the name into its
   own namespace via `from ... import ...`) to return a client wired to a
   `MockTransport` handler, and captures the single outgoing request into a
   shared `_CapturedRequest` box so each test can inspect it exactly as it
   previously read `respx`'s `route.calls.last`.
2. **Version floor/ceiling** (`test_installed_pydantic_ai_slim_meets_hub_verified_floor`,
   `test_installed_openai_sdk_stays_below_major_3`,
   `test_installed_openai_sdk_meets_httpx2_transport_floor`): installed
   `pydantic-ai-slim` must be at least `HUB_VERIFIED_PYDANTIC_AI_FLOOR`,
   installed `openai` must stay below major version 3, and installed
   `openai` must be at least `_OPENAI_SDK_HTTPX2_FLOOR` (2.47.0 — the first
   `openai` release whose `_httpx2` module accepts an `httpx2.AsyncClient`
   as `http_client=`; a lower `openai` would crash provider construction,
   not just this test, since pydantic-ai-slim's OpenAI-compatible providers
   always pass one — see contract 1 above). The pydantic-ai-slim floor was
   the red contract on the pre-Task-2.2 floor (`pydantic-ai-slim>=2.31.1`
   failed `2.31.1 < 2.54.0`); it is green once Task 2.2 raises the root
   dependency floor to match. The `_OPENAI_SDK_HTTPX2_FLOOR` guard was added
   after an independent VDD review caught that the original
   `openai>=2.20.0,<3.0.0` range admitted versions below 2.47.0 that crash
   under this pydantic-ai-slim floor (see `pyproject.toml` ADR-2).

``HUB_VERIFIED_PYDANTIC_AI_FLOOR`` is fixed as a module constant rather than
read from the hub repository at runtime, because this test module must stay
hermetic (Constitution Principle 6: no commit/sync coupling to another
repository's live state). The value, the hub commit it was confirmed
against, and the confirmation date are recorded immediately below it as a
comment and must be updated together:

* value: ``"2.54.0"``
* confirmed against hub `main`@`afbe6eb` (PR #78 merge), `services/api/uv.lock:2977`
* confirmed: 2026-10-03 (see `specs/014-hub-python-beta-lane/gap-analysis.md` §5.1)

Update triggers for the constant: (1) the monthly dependency-refresh pass
recorded in `docs/hub-intake-2026-10.md` (R3.2), and (2) any `mise run
hub:verify` run against a newer hub commit (R1/R3.3). Either trigger that
finds a newer hub-locked `pydantic-ai-slim` MUST raise this constant first,
confirm the resulting red state, and only then raise the root dependency
floor in `pyproject.toml` (R2.1's continuous guarantee from plan.md
DES-2.2) — never raise the floor and the constant out of order.
"""

from __future__ import annotations

import json
from importlib.metadata import version as installed_version
from typing import TYPE_CHECKING

import httpx2
import pytest
from pydantic_ai import Agent
from pydantic_ai.settings import ModelSettings

from pydantic_ai_sandbox.config import get_settings
from pydantic_ai_sandbox.llm import get_model
from tests.support.version_compare import release_tuple

if TYPE_CHECKING:
    from collections.abc import Iterator

    from pydantic_ai.models import Model

    from tests.conftest import SettingsFactory

OLLAMA_BASE_URL = "http://ollama-compat-test.invalid/v1"
OLLAMA_MODEL_NAME = "dummy-ollama-model"
CHAT_COMPLETIONS_URL = f"{OLLAMA_BASE_URL}/chat/completions"

# See the module docstring for the provenance of this value — do not read it
# from the hub repository at test time.
HUB_VERIFIED_PYDANTIC_AI_FLOOR = "2.54.0"

# `pydantic-ai-slim`'s own `openai` extra requires `openai>=3.0.0` since
# 2.32.0 (research.md); staying below major 3 is exactly what ADR-2's direct
# `openai` dependency (bypassing that extra) is for.
_OPENAI_SDK_MAJOR_CEILING = 3

# First `openai` release whose `_httpx2` module accepts an `httpx2.AsyncClient`
# as the `http_client=` constructor argument — confirmed empirically via
# sequential venv installs: `openai._httpx2` is absent in 2.20.0/2.30.0/2.46.0
# and present starting at 2.47.0 (also confirmed present in 2.50.0/2.52.0/
# 2.54.0). Below this floor, constructing `AsyncOpenAI(http_client=an
# httpx2.AsyncClient())` raises `TypeError`; see `pyproject.toml` ADR-2.
_OPENAI_SDK_HTTPX2_FLOOR = "2.47.0"


def _chat_completion_response(*, content: str) -> httpx2.Response:
    """Build a minimal, schema-valid OpenAI Chat Completions JSON response."""
    return httpx2.Response(
        200,
        json={
            "id": "chatcmpl-ollama-compat-test",
            "object": "chat.completion",
            "created": 1_730_700_000,
            "model": OLLAMA_MODEL_NAME,
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": content},
                },
            ],
            "usage": {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6},
        },
    )


class _CapturedRequest:
    """Mutable single-slot box for the last request seen by the mock transport.

    A plain holder (rather than returning the request directly from the
    fixture) because the request does not exist yet when the fixture runs —
    it is only produced once a test calls ``agent.run()``.
    """

    def __init__(self) -> None:
        self.request: httpx2.Request | None = None


@pytest.fixture
def ollama_model(
    settings_factory: SettingsFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[Model, _CapturedRequest]]:
    """Build the real sandbox Ollama model (`get_model("ollama")`) against a dummy host.

    No real HTTP ever leaves this fixture — construction is pure (Req 2.6,
    `test_factory_ollama_no_io.py`), and the only network client the model
    will ever use is wired to an `httpx2.MockTransport` (see module
    docstring) that answers with a canned "pong" Chat Completions response.
    The returned `_CapturedRequest` box is where each test reads back the
    single request `agent.run()` sends.
    """
    captured = _CapturedRequest()

    def handler(request: httpx2.Request) -> httpx2.Response:
        captured.request = request
        return _chat_completion_response(content="pong")

    def mock_create_async_httpx2_client(**_kwargs: object) -> httpx2.AsyncClient:
        return httpx2.AsyncClient(transport=httpx2.MockTransport(handler))

    monkeypatch.setattr(
        "pydantic_ai.providers._openai_compatible.create_async_httpx2_client",
        mock_create_async_httpx2_client,
    )
    settings_factory(
        LLM_PROVIDER="ollama",
        OLLAMA_BASE_URL=OLLAMA_BASE_URL,
        OLLAMA_MODEL_NAME=OLLAMA_MODEL_NAME,
    )
    get_settings.cache_clear()
    try:
        yield get_model("ollama"), captured
    finally:
        get_settings.cache_clear()


async def test_ollama_chat_completion_normal_response_round_trips_through_openai_sdk(
    ollama_model: tuple[Model, _CapturedRequest],
) -> None:
    """A mocked Chat Completions reply reaches `Agent.run().output` unchanged.

    Exercises the full `OllamaProvider -> OllamaModel -> Agent.run()` chain
    with the installed `openai` SDK doing the real request serialization
    and response parsing — only the transport is faked.
    """
    model, _captured = ollama_model
    agent: Agent[None, str] = Agent(model)
    result = await agent.run("ping")

    assert result.output == "pong", (
        f"expected the mocked Chat Completions content to flow through "
        f"unchanged, got {result.output!r}"
    )


async def test_ollama_chat_completion_sends_expected_model_and_messages(
    ollama_model: tuple[Model, _CapturedRequest],
) -> None:
    """The outgoing request body names the configured model and the user turn.

    Pins the request-serialization half of the contract: a regression that
    dropped the model name or mangled message roles would still produce a
    200 response (the mock does not depend on the body) but would be caught
    here.
    """
    model, captured = ollama_model
    agent: Agent[None, str] = Agent(model)
    await agent.run("ping")

    assert captured.request is not None, "mock transport was never called"
    assert captured.request.method == "POST", (
        f"expected the Chat Completions call to be a POST, got {captured.request.method!r}"
    )
    assert str(captured.request.url) == CHAT_COMPLETIONS_URL, (
        f"expected the request to target {CHAT_COMPLETIONS_URL!r}, "
        f"got {captured.request.url!r} — a regression here would still return "
        f"200 (the mock transport answers any URL/method) but would mean the "
        f"OpenAI-compatible client is no longer hitting the configured Ollama "
        f"endpoint"
    )
    sent_body = json.loads(captured.request.content)
    assert sent_body["model"] == OLLAMA_MODEL_NAME, (
        f"expected the request body's model field to be {OLLAMA_MODEL_NAME!r}, "
        f"got {sent_body.get('model')!r} in body {sent_body!r}"
    )
    assert sent_body["messages"] == [{"role": "user", "content": "ping"}], (
        f"expected a single user-role message carrying the prompt verbatim, "
        f"got {sent_body.get('messages')!r}"
    )


async def test_ollama_chat_completion_forwards_model_settings_timeout(
    ollama_model: tuple[Model, _CapturedRequest],
) -> None:
    """`ModelSettings(timeout=...)` reaches the actual httpx2 request.

    `OpenAIChatModel` forwards `model_settings['timeout']` into the OpenAI
    SDK call's `timeout=` kwarg (`pydantic_ai/models/openai.py`), which the
    SDK turns into a per-request timeout extension. Reading it back off the
    captured request — rather than timing a real delayed response, which
    the mock transport does not enforce — proves the forwarding wiring
    without a slow, flaky, real-time test.
    """
    model, captured = ollama_model
    configured_timeout = 12.5
    agent: Agent[None, str] = Agent(model)
    await agent.run("ping", model_settings=ModelSettings(timeout=configured_timeout))

    assert captured.request is not None, "mock transport was never called"
    sent_timeout = captured.request.extensions.get("timeout")
    assert sent_timeout == {
        "connect": configured_timeout,
        "read": configured_timeout,
        "write": configured_timeout,
        "pool": configured_timeout,
    }, (
        f"expected ModelSettings(timeout={configured_timeout}) to reach the "
        f"httpx2 request as a uniform {configured_timeout}s timeout, got "
        f"{sent_timeout!r} — check model_settings forwarding in the "
        f"installed pydantic-ai's OpenAIChatModel"
    )


def test_installed_pydantic_ai_slim_meets_hub_verified_floor() -> None:
    """Installed `pydantic-ai-slim` must be >= the hub-verified floor (R2.1).

    Red on the pre-Task-2.2 `pydantic-ai-slim>=2.31.1` floor (2.31.1 <
    2.54.0); green once Task 2.2 raises the root dependency floor to match.
    """
    installed = installed_version("pydantic-ai-slim")
    assert release_tuple(installed) >= release_tuple(HUB_VERIFIED_PYDANTIC_AI_FLOOR), (
        f"installed pydantic-ai-slim is {installed}, which is older than the "
        f"hub-verified floor {HUB_VERIFIED_PYDANTIC_AI_FLOOR!r} (see this "
        f"module's docstring for the hub commit/date this floor was "
        f"confirmed against). Raise the pydantic-ai-slim dependency in "
        f"pyproject.toml to at least this floor."
    )


def test_installed_openai_sdk_stays_below_major_3() -> None:
    """Installed `openai` must stay below major version 3 (ADR-2).

    `litellm` has not adopted the `openai` 3.x SDK as of this constant's
    confirmation date (see `pyproject.toml` ADR-2); crossing major 3 would
    force litellm back to a release with known vulnerabilities.
    """
    installed = installed_version("openai")
    major = release_tuple(installed)[0]
    assert major < _OPENAI_SDK_MAJOR_CEILING, (
        f"installed openai is {installed} (major {major}), which has crossed "
        f"the ADR-2 ceiling of major {_OPENAI_SDK_MAJOR_CEILING}. Re-check "
        f"litellm's declared openai range before lifting this cap — see "
        f"pyproject.toml ADR-2."
    )


def test_installed_openai_sdk_meets_httpx2_transport_floor() -> None:
    """Installed `openai` must be new enough to accept an `httpx2.AsyncClient`.

    pydantic-ai-slim's OpenAI-compatible providers (incl. Ollama) always
    construct an `httpx2.AsyncClient` and pass it as `http_client=` when the
    caller does not supply one (see this module's docstring, contract 1) —
    which `src/pydantic_ai_sandbox/llm/providers/ollama.py` never does. An
    `openai` below `_OPENAI_SDK_HTTPX2_FLOOR` raises `TypeError` the moment
    the provider is constructed, before any request is sent, so this guard
    is independent from (and stricter than) the major-version ceiling above.
    """
    installed = installed_version("openai")
    assert release_tuple(installed) >= release_tuple(_OPENAI_SDK_HTTPX2_FLOOR), (
        f"installed openai is {installed}, which predates the httpx2 "
        f"transport-acceptance floor {_OPENAI_SDK_HTTPX2_FLOOR!r}. "
        f"Constructing AsyncOpenAI(http_client=<an httpx2.AsyncClient>) under "
        f"an older openai raises TypeError (see pyproject.toml ADR-2) — this "
        f"would crash every Ollama-provider call, not just this test. Raise "
        f"the openai floor in pyproject.toml to at least this version."
    )
