"""Hermetic construction tests for :class:`WatsonxSDKModel` (Task 5.1).

Task 5.1 lands the SDK-transport **activation skeleton**: an I/O-free
``__init__`` that merely stores the validated :class:`Settings`, plus the
``system`` / ``model_name`` properties Pydantic AI instrumentation reads to
derive the ``gen_ai.system`` and ``gen_ai.request.model`` span attributes
(Req 8.1/8.3/8.4/8.6). The class itself was first introduced by Task 4 to let
the factory return a real ``Model``; these tests are the dedicated RED→GREEN
evidence that the skeleton meets the Task 5.1 contract and give the new branches
direct coverage for the 98% ratchet (the dispatch test in
``test_factory_dispatch.py`` only asserts ``isinstance(..., Model)`` and never
touches the properties or the defensive guard).

Boundary note: this file is the home Task 7.1 extends with the request-path
tests (message-mapping, ``ModelInference`` pinned to ``max_retries=0`` /
``validate=False``, response-mapping) once Tasks 5.2/5.3 wire the lazy SDK
client. Those depend on the live request path and are intentionally **not** here
— Task 5.1 owns construction only.

Covered requirements:

* **1.5** — construction performs no network I/O. Proven by detonating the
  ``httpx`` transport hooks (sync and async) and asserting the constructor still
  returns; the lazy SDK client (Task 5.2) keeps ``__init__`` egress-free.
* **3.4** — the model id is sourced from ``Settings`` (``WATSONX_MODEL_ID``),
  never a literal in ``src/``: ``model_name`` echoes the fixture-seated value.
* **8.6** (and via it 8.1/8.3/8.4) — ``system`` and ``model_name`` are the two
  properties Pydantic AI reads to stamp exactly the standard lean attribute set.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx

# Imported at module scope (not used by name) so the SDK's ``httpx_wrapper``
# builds its ``class HTTPXAsyncClient(httpx.AsyncClient)`` subclass against the
# *real* ``httpx.AsyncClient`` before any test substitutes it with a spy. A
# function-typed spy installed first would make that subclass statement raise
# ``TypeError`` at import time.
import ibm_watsonx_ai.foundation_models  # noqa: F401  # pyright: ignore[reportUnusedImport]
import pytest
from ibm_watsonx_ai.wml_client_error import WMLClientError
from pydantic_ai.exceptions import ModelAPIError
from pydantic_ai.messages import (
    ImageUrl,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models import Model, ModelRequestParameters
from pydantic_ai.tools import ToolDefinition

from pydantic_ai_sandbox.config import Settings
from pydantic_ai_sandbox.llm.providers.watsonx import (
    WatsonxSDKModel,
    _build_watsonx,  # pyright: ignore[reportPrivateUsage]
)
from tests.conftest import (
    WATSONX_TEST_APIKEY,
    WATSONX_TEST_MODEL_ID,
    WATSONX_TEST_PROJECT_ID,
    WATSONX_TEST_URL,
)

if TYPE_CHECKING:
    from tests.conftest import WatsonxSettingsFactory


class _NetworkAccessError(RuntimeError):
    """Raised by the patched httpx send hooks if anything attempts egress."""


def _explode_sync(*_args: Any, **_kwargs: Any) -> Any:
    raise _NetworkAccessError(
        "sync httpx.Client.send must not be called during WatsonxSDKModel construction",
    )


async def _explode_async(*_args: Any, **_kwargs: Any) -> Any:
    raise _NetworkAccessError(
        "async httpx.AsyncClient.send must not be called during WatsonxSDKModel construction",
    )


def test_system_property_returns_watsonx(
    watsonx_settings_factory: WatsonxSettingsFactory,
) -> None:
    """``system`` is the constant ``"watsonx"`` → drives ``gen_ai.system`` (Req 8.6).

    Pydantic AI instrumentation reads ``Model.system`` to stamp the
    ``gen_ai.system`` span attribute; a wrong or empty value would surface as a
    mislabelled (or absent) provider in observability (Req 8.1).
    """
    model = WatsonxSDKModel(watsonx_settings_factory())

    assert model.system == "watsonx"


def test_model_name_is_sourced_from_settings(
    watsonx_settings_factory: WatsonxSettingsFactory,
) -> None:
    """``model_name`` echoes ``WATSONX_MODEL_ID`` from Settings (Req 3.4/8.6).

    The id is never a literal in ``src/`` — it reaches the Model through
    :class:`Settings`, so the property must return exactly the env-seated value
    (the fixture's canonical ``WATSONX_TEST_MODEL_ID``). This is what
    instrumentation stamps as ``gen_ai.request.model``.
    """
    model = WatsonxSDKModel(watsonx_settings_factory())

    assert model.model_name == WATSONX_TEST_MODEL_ID


def test_construction_is_io_free(
    monkeypatch: pytest.MonkeyPatch,
    watsonx_settings_factory: WatsonxSettingsFactory,
) -> None:
    """Constructing the Model performs no network I/O (Req 1.5).

    Both ``httpx`` transport hooks are replaced with detonators, so any
    inadvertent probe during ``__init__`` surfaces as ``_NetworkAccessError``
    rather than slipping past as a swallowed timeout. The SDK client is built
    lazily on the first request (Task 5.2), so a stopped or unreachable watsonx
    endpoint cannot break process start.
    """
    settings = watsonx_settings_factory()
    monkeypatch.setattr(httpx.Client, "send", _explode_sync)
    monkeypatch.setattr(httpx.AsyncClient, "send", _explode_async)

    model = WatsonxSDKModel(settings)

    # Returning without exception is the load-bearing assertion; the isinstance
    # check keeps the test honest against a future fast-fail branch that might
    # return ``None`` instead of a Model.
    assert isinstance(model, Model)


def test_model_name_none_guard_raises_typeerror() -> None:
    """The defensive ``model_name`` guard fires when the id drifts to ``None``.

    The credential gate (config Task 2.2) rejects a missing ``WATSONX_MODEL_ID``
    at boot, so production never reaches this branch — but the guard defends
    against a *future* validator change that loosens the invariant. We simulate
    that post-drift state with Pydantic v2's :meth:`Settings.model_construct`
    escape hatch (no validators run) and assert the property fails loud with a
    greppable message rather than returning ``None`` and corrupting the
    ``gen_ai.request.model`` attribute downstream.
    """
    drifted = Settings.model_construct(watsonx_model_id=None)
    model = WatsonxSDKModel(drifted)

    with pytest.raises(TypeError, match="watsonx_model_id is None"):
        _ = model.model_name


# ---------------------------------------------------------------------------
# Task 5.2 — lazy ``_build_client`` (SDK client construction)
#
# ``_build_client`` is the lazily-invoked builder ``request`` (Task 5.3) calls
# on the first inference: it wires the ``ibm-watsonx-ai`` SDK client with the
# configured timeouts (Req 5.4) and ``max_retries=0`` (Req 6.1 / ADR-2), and
# pins ``validate=False`` (plan.md §Entity 2) so neither construction nor the
# first call fires an extra network validation round-trip. Because the SDK's
# ``APIClient`` authenticates over the network at construction, these tests
# stay hermetic by detonating-by-substitution: every SDK/transport constructor
# is replaced with a recording spy, so we assert the *wiring* without egress.
# ---------------------------------------------------------------------------


class _ConstructorSpy:
    """Records the keyword arguments a substituted constructor was called with.

    Each instance captures its own ``kwargs`` and registers itself in the
    shared ``instances`` list handed in by :func:`_spy_factory`, so a test can
    assert both the call arguments and how many times the constructor ran
    (lazy-caching evidence).
    """

    def __init__(self, _instances: list[_ConstructorSpy], **kwargs: Any) -> None:
        self.kwargs = kwargs
        _instances.append(self)


def _spy_factory() -> tuple[Any, list[_ConstructorSpy]]:
    """Return a ``(spy_class, instances)`` pair for one substituted constructor.

    The returned class swallows arbitrary kwargs (matching the real SDK
    constructors' keyword-only surfaces) and appends each instance to
    ``instances`` so the test can read back the recorded call(s).
    """
    instances: list[_ConstructorSpy] = []

    def _make(**kwargs: Any) -> _ConstructorSpy:
        return _ConstructorSpy(instances, **kwargs)

    return _make, instances


def _install_sdk_spies(
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, list[_ConstructorSpy]]:
    """Substitute ``Credentials`` / ``APIClient`` / ``ModelInference`` / httpx.

    Patches the four constructors ``_build_client`` reaches for with recording
    spies and returns a name→instances map so callers can introspect the wiring
    chain. ``httpx.AsyncClient`` is patched on the ``httpx`` module the provider
    imports at module scope; the three SDK symbols are patched on their defining
    modules so the function-local ``from ibm_watsonx_ai ... import`` picks up the
    spy at call time.
    """
    cred_spy, creds = _spy_factory()
    api_spy, api_clients = _spy_factory()
    mi_spy, model_inferences = _spy_factory()
    http_spy, http_clients = _spy_factory()

    # SDK symbols first (their modules are already imported at module scope),
    # then httpx last so no SDK import observes a function-typed AsyncClient.
    monkeypatch.setattr("ibm_watsonx_ai.Credentials", cred_spy)
    monkeypatch.setattr("ibm_watsonx_ai.APIClient", api_spy)
    monkeypatch.setattr("ibm_watsonx_ai.foundation_models.ModelInference", mi_spy)
    monkeypatch.setattr(httpx, "AsyncClient", http_spy)

    return {
        "credentials": creds,
        "api_clients": api_clients,
        "model_inferences": model_inferences,
        "http_clients": http_clients,
    }


def test_build_client_wires_credentials_no_retry_and_no_validate(
    monkeypatch: pytest.MonkeyPatch,
    watsonx_settings_factory: WatsonxSettingsFactory,
) -> None:
    """``_build_client`` wires the full SDK chain with no-retry / no-validate.

    Pins the load-bearing construction contract (Req 6.1 / ADR-2 + plan.md
    §Entity 2): ``ModelInference`` is built with ``max_retries=0`` and
    ``validate=False``, sourced ``model_id``, and the ``APIClient`` carrying the
    sourced ``project_id`` and the credential object; ``Credentials`` receives
    the unwrapped ``WATSONX_URL`` / ``WATSONX_APIKEY``.
    """
    spies = _install_sdk_spies(monkeypatch)
    model = WatsonxSDKModel(watsonx_settings_factory())

    client = model._build_client()  # pyright: ignore[reportPrivateUsage]

    cred = spies["credentials"][0]
    assert cred.kwargs["url"] == WATSONX_TEST_URL
    assert cred.kwargs["api_key"] == WATSONX_TEST_APIKEY  # unwrapped at the boundary

    api_client = spies["api_clients"][0]
    assert api_client.kwargs["credentials"] is cred
    assert api_client.kwargs["project_id"] == WATSONX_TEST_PROJECT_ID
    assert api_client.kwargs["async_httpx_client"] is spies["http_clients"][0]

    model_inference = spies["model_inferences"][0]
    assert model_inference.kwargs["model_id"] == WATSONX_TEST_MODEL_ID
    assert model_inference.kwargs["api_client"] is api_client
    assert model_inference.kwargs["max_retries"] == 0
    assert model_inference.kwargs["validate"] is False
    # The built client is returned for ``request`` (Task 5.3) to drive.
    assert client is model_inference


def test_build_client_applies_default_timeouts(
    monkeypatch: pytest.MonkeyPatch,
    watsonx_settings_factory: WatsonxSettingsFactory,
) -> None:
    """The async httpx client carries the 30s/120s connect/read defaults (Req 5.4).

    ``httpx.Timeout`` rejects a partial (connect, read) spec, so the provider
    seeds the read value as the overall default and overrides ``connect``; this
    asserts the two configured phases land on the wire regardless of how the
    write/pool phases are seeded.
    """
    spies = _install_sdk_spies(monkeypatch)
    model = WatsonxSDKModel(watsonx_settings_factory())

    model._build_client()  # pyright: ignore[reportPrivateUsage]

    timeout = spies["http_clients"][0].kwargs["timeout"]
    assert timeout.connect == 30
    assert timeout.read == 120


def test_build_client_applies_overridden_timeouts(
    monkeypatch: pytest.MonkeyPatch,
    watsonx_settings_factory: WatsonxSettingsFactory,
) -> None:
    """Env overrides for connect/read timeouts reach the httpx client (Req 5.4)."""
    spies = _install_sdk_spies(monkeypatch)
    settings = watsonx_settings_factory(
        WATSONX_TIMEOUT_CONNECT="15",
        WATSONX_TIMEOUT_READ="200",
    )
    model = WatsonxSDKModel(settings)

    model._build_client()  # pyright: ignore[reportPrivateUsage]

    timeout = spies["http_clients"][0].kwargs["timeout"]
    assert timeout.connect == 15
    assert timeout.read == 200


def test_build_client_is_lazily_cached(
    monkeypatch: pytest.MonkeyPatch,
    watsonx_settings_factory: WatsonxSettingsFactory,
) -> None:
    """The SDK client is built once and reused (Req 1.5 lazy-client contract).

    The first ``_build_client`` constructs the ``ModelInference``; subsequent
    calls return the cached instance without re-authenticating — proven by the
    spy registry holding exactly one ``ModelInference``.
    """
    spies = _install_sdk_spies(monkeypatch)
    model = WatsonxSDKModel(watsonx_settings_factory())

    first = model._build_client()  # pyright: ignore[reportPrivateUsage]
    second = model._build_client()  # pyright: ignore[reportPrivateUsage]

    assert first is second
    assert len(spies["model_inferences"]) == 1


def test_build_client_missing_apikey_raises_typeerror(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A drifted ``None`` api key fails loud before any SDK construction.

    The credential gate (config Task 2.2) makes this unreachable in production;
    the guard defends against a future validator loosening and keeps the
    ``SecretStr`` unwrap total. Simulated via ``model_construct`` (no validators)
    with the other three creds present so only the api-key branch fires.
    """
    _install_sdk_spies(monkeypatch)
    drifted = Settings.model_construct(
        watsonx_apikey=None,
        watsonx_url=WATSONX_TEST_URL,
        watsonx_project_id=WATSONX_TEST_PROJECT_ID,
        watsonx_model_id=WATSONX_TEST_MODEL_ID,
    )
    model = WatsonxSDKModel(drifted)

    with pytest.raises(TypeError, match="watsonx_apikey is None"):
        model._build_client()  # pyright: ignore[reportPrivateUsage]


# ---------------------------------------------------------------------------
# Task 5.3 — ``request``: message mapping → ``achat`` → ``ModelResponse``
#
# ``request`` is the live inference path. It maps the pydantic_ai
# ``list[ModelMessage]`` history (rendered instructions / system / user / tool
# parts and prior assistant tool-calls) to OpenAI-shaped dicts, hands them to
# the async ``ModelInference.achat`` built by ``_build_client`` (Task 5.2), and
# rebuilds a ``ModelResponse`` from the returned dict — text parts, tool-call
# parts, ``usage``, ``finish_reason`` and the provider response id (Req 2.7 /
# 9.11). These tests stay hermetic by substituting ``_build_client`` with a fake
# whose ``achat`` records the request payload and returns a canned response, so
# the mapping is asserted in both directions with zero egress. Error wrapping is
# Task 5.4; these exercise the happy path only.
# ---------------------------------------------------------------------------


class _FakeAchatClient:
    """Stand-in for ``ModelInference`` recording the ``achat`` request payload.

    ``achat`` captures every keyword argument into the shared ``recorder`` (so a
    test can assert the mapped ``messages`` / ``tools``) and returns the canned
    OpenAI-shaped ``response`` dict, mirroring the real async coroutine's
    signature without any network call.
    """

    def __init__(self, response: dict[str, Any], recorder: dict[str, Any]) -> None:
        self._response = response
        self._recorder = recorder

    async def achat(self, **kwargs: Any) -> dict[str, Any]:
        self._recorder.update(kwargs)
        return self._response


def _stub_achat(
    monkeypatch: pytest.MonkeyPatch,
    model: WatsonxSDKModel,
    response: dict[str, Any],
) -> dict[str, Any]:
    """Replace ``model._build_client`` with a recording fake; return the recorder.

    Keeps the request path hermetic: ``request`` calls ``_build_client`` then
    awaits ``achat`` on the result, so swapping the builder for one that yields
    a :class:`_FakeAchatClient` exercises the real mapping code without touching
    the SDK or the network.
    """
    recorder: dict[str, Any] = {}
    client = _FakeAchatClient(response, recorder)
    monkeypatch.setattr(model, "_build_client", lambda: client)
    return recorder


_TEXT_RESPONSE: dict[str, Any] = {
    "id": "chatcmpl-watsonx-text",
    "choices": [
        {
            "index": 0,
            "message": {"role": "assistant", "content": "Hello from watsonx"},
            "finish_reason": "stop",
        },
    ],
    "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
}

_TOOL_CALL_RESPONSE: dict[str, Any] = {
    "id": "chatcmpl-watsonx-tool",
    "choices": [
        {
            "index": 0,
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_kb_1",
                        "type": "function",
                        "function": {
                            "name": "search_kb",
                            "arguments": '{"query": "weather"}',
                        },
                    },
                ],
            },
            "finish_reason": "tool_calls",
        },
    ],
    "usage": {"prompt_tokens": 20, "completion_tokens": 4, "total_tokens": 24},
}


async def test_request_maps_text_response(
    monkeypatch: pytest.MonkeyPatch,
    watsonx_settings_factory: WatsonxSettingsFactory,
) -> None:
    """A text ``achat`` response maps to a ``ModelResponse`` text part (Req 2.7/9.11).

    Pins the response-mapping contract: the assistant ``content`` becomes a
    single :class:`TextPart`, ``usage`` maps prompt/completion → input/output
    tokens, ``finish_reason`` normalises ``"stop"`` → ``"stop"``, ``id`` →
    ``provider_response_id`` and the observability identity fields
    (``model_name`` / ``provider_name``) are stamped.
    """
    model = WatsonxSDKModel(watsonx_settings_factory())
    _stub_achat(monkeypatch, model, _TEXT_RESPONSE)

    messages: list[ModelMessage] = [ModelRequest(parts=[UserPromptPart("hello")])]
    result = await model.request(messages, None, ModelRequestParameters())

    assert len(result.parts) == 1
    part = result.parts[0]
    assert isinstance(part, TextPart)
    assert part.content == "Hello from watsonx"
    assert result.finish_reason == "stop"
    assert result.usage.input_tokens == 11
    assert result.usage.output_tokens == 7
    assert result.provider_response_id == "chatcmpl-watsonx-text"
    assert result.model_name == WATSONX_TEST_MODEL_ID
    assert result.provider_name == "watsonx"


async def test_request_maps_tool_call_response(
    monkeypatch: pytest.MonkeyPatch,
    watsonx_settings_factory: WatsonxSettingsFactory,
) -> None:
    """A tool-call ``achat`` response maps to a ``ToolCallPart`` (Req 2.7/9.11).

    The OpenAI-shaped ``tool_calls`` entry must surface as a
    :class:`ToolCallPart` carrying the function name, the raw JSON arguments
    (parsed on demand via ``args_as_dict``) and the provider tool-call id, with
    ``finish_reason`` normalising ``"tool_calls"`` → ``"tool_call"``. Dropping
    the tool call would silently break the agent's tool / structured-output loop.
    """
    model = WatsonxSDKModel(watsonx_settings_factory())
    _stub_achat(monkeypatch, model, _TOOL_CALL_RESPONSE)

    messages: list[ModelMessage] = [ModelRequest(parts=[UserPromptPart("天気は?")])]
    result = await model.request(messages, None, ModelRequestParameters())

    assert len(result.parts) == 1
    part = result.parts[0]
    assert isinstance(part, ToolCallPart)
    assert part.tool_name == "search_kb"
    assert part.tool_call_id == "call_kb_1"
    assert part.args_as_dict() == {"query": "weather"}
    assert result.finish_reason == "tool_call"


async def test_request_maps_text_and_tool_calls_together(
    monkeypatch: pytest.MonkeyPatch,
    watsonx_settings_factory: WatsonxSettingsFactory,
) -> None:
    """Text and tool-call parts coexist, in order, with no drops (Req 2.7).

    A response carrying both ``content`` and ``tool_calls`` must yield a
    :class:`TextPart` followed by a :class:`ToolCallPart` — neither is preferred
    over nor silently swallows the other.
    """
    response: dict[str, Any] = {
        "id": "chatcmpl-mixed",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "let me check",
                    "tool_calls": [
                        {
                            "id": "c1",
                            "type": "function",
                            "function": {"name": "search_kb", "arguments": "{}"},
                        },
                    ],
                },
                "finish_reason": "tool_calls",
            },
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
    }
    model = WatsonxSDKModel(watsonx_settings_factory())
    _stub_achat(monkeypatch, model, response)

    messages: list[ModelMessage] = [ModelRequest(parts=[UserPromptPart("hi")])]
    result = await model.request(messages, None, ModelRequestParameters())

    assert [type(p).__name__ for p in result.parts] == ["TextPart", "ToolCallPart"]


async def test_request_maps_message_history_to_openai_dicts(
    monkeypatch: pytest.MonkeyPatch,
    watsonx_settings_factory: WatsonxSettingsFactory,
) -> None:
    """instructions / user / assistant-tool-call / tool-return map to OpenAI roles (Req 2.7).

    Drives the full request-side mapping: the rendered ``instructions`` become a
    leading ``system`` message, a ``UserPromptPart`` becomes a ``user`` message,
    a prior ``ModelResponse`` carrying a ``ToolCallPart`` becomes an
    ``assistant`` message with an OpenAI ``tool_calls`` array, and a
    ``ToolReturnPart`` becomes a ``tool`` message keyed by ``tool_call_id`` — no
    part silently dropped.
    """
    model = WatsonxSDKModel(watsonx_settings_factory())
    recorder = _stub_achat(monkeypatch, model, _TEXT_RESPONSE)

    messages: list[ModelMessage] = [
        ModelRequest(
            parts=[UserPromptPart("天気は?")],
            instructions="be helpful",
        ),
        ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="search_kb",
                    args='{"query": "weather"}',
                    tool_call_id="c1",
                ),
            ],
        ),
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="search_kb",
                    content="sunny",
                    tool_call_id="c1",
                ),
            ],
        ),
    ]

    await model.request(messages, None, ModelRequestParameters())

    assert recorder["messages"] == [
        {"role": "system", "content": "be helpful"},
        {"role": "user", "content": "天気は?"},
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "c1",
                    "type": "function",
                    "function": {
                        "name": "search_kb",
                        "arguments": '{"query": "weather"}',
                    },
                },
            ],
        },
        {"role": "tool", "tool_call_id": "c1", "content": "sunny"},
    ]


async def test_request_forwards_tool_definitions(
    monkeypatch: pytest.MonkeyPatch,
    watsonx_settings_factory: WatsonxSettingsFactory,
) -> None:
    """Tool definitions reach ``achat`` as OpenAI tool specs (Req 2.7).

    The agent's tool-mode structured output and the ``search_kb`` tool only work
    if the tool *definitions* from ``ModelRequestParameters`` are forwarded;
    omitting them would silently disable tool calling for the watsonx provider.
    """
    model = WatsonxSDKModel(watsonx_settings_factory())
    recorder = _stub_achat(monkeypatch, model, _TEXT_RESPONSE)

    params = ModelRequestParameters(
        function_tools=[
            ToolDefinition(
                name="search_kb",
                parameters_json_schema={
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                },
                description="kb lookup",
            ),
        ],
    )

    messages: list[ModelMessage] = [ModelRequest(parts=[UserPromptPart("hi")])]
    await model.request(messages, None, params)

    assert recorder["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "search_kb",
                "description": "kb lookup",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                },
            },
        },
    ]


async def test_request_rejects_multimodal_user_content(
    monkeypatch: pytest.MonkeyPatch,
    watsonx_settings_factory: WatsonxSettingsFactory,
) -> None:
    """Non-text user content fails loud rather than being silently dropped (Req 2.7).

    Vision / multimodal input is out of scope for the SDK transport; an
    ``ImageUrl`` in the user prompt must raise ``NotImplementedError`` rather
    than vanish from the mapped payload.
    """
    model = WatsonxSDKModel(watsonx_settings_factory())
    _stub_achat(monkeypatch, model, _TEXT_RESPONSE)

    messages: list[ModelMessage] = [
        ModelRequest(
            parts=[UserPromptPart(content=[ImageUrl(url="https://example.com/a.png")])],
        ),
    ]

    with pytest.raises(NotImplementedError, match="multimodal"):
        await model.request(messages, None, ModelRequestParameters())


# ---------------------------------------------------------------------------
# Task 5.4 — SDK-failure wrapping into ``ModelAPIError`` (no retries)
#
# ``request`` MUST translate every SDK failure — the SDK base
# ``WMLClientError`` (and its subclasses: ``ApiRequestFailure``,
# ``AuthenticationError``, rate-limit, …) and the underlying httpx errors
# (``TimeoutException`` / ``ConnectError`` / any ``httpx.HTTPError``) — into
# :class:`pydantic_ai.exceptions.ModelAPIError`. ``FallbackModel``'s default
# ``fallback_on`` is ``(ModelAPIError,)`` (pydantic_ai 2.0.0b6), so a raw SDK or
# httpx error would *not* trigger failover and Req 7.1/7.2/9.8 would break in the
# real chain even while passing in isolation (plan.md Entity 2 — "the single
# highest-risk correctness point in the feature"). There are **no provider-level
# retries** (Req 6.1/6.3/6.4): the failing call is made exactly once. The error
# wrapping covers both the lazy first-call client build (Req 4.4 — unreachable
# endpoint / DNS failure on the first API call) and the ``achat`` call itself.
# These tests stay hermetic by substituting ``_build_client`` / ``achat`` with
# fakes that raise; no SDK construction or network egress occurs.
# ---------------------------------------------------------------------------


class _FakeSDKSubError(WMLClientError):
    """A stand-in ``WMLClientError`` subclass with the plain base constructor.

    The real SDK subclasses (``ApiRequestFailure`` / ``AuthenticationError``)
    require a ``response`` argument, which is awkward to fabricate hermetically.
    This local subclass inherits ``WMLClientError``'s ``(error_msg, ...)``
    constructor unchanged, so it proves the ``except WMLClientError`` catch
    covers *every* SDK error subclass without coupling the test to a specific
    SDK error's signature.
    """


class _FailingAchatClient:
    """Stand-in for ``ModelInference`` whose ``achat`` always raises.

    Counts invocations so a test can prove the failing call is made exactly
    once — the no-retry contract (Req 6.1): there is no provider-level retry
    loop, the first failure propagates immediately.
    """

    def __init__(self, exc: Exception) -> None:
        self._exc = exc
        self.calls = 0

    async def achat(self, **_kwargs: Any) -> dict[str, Any]:
        self.calls += 1
        raise self._exc


def _stub_failing_achat(
    monkeypatch: pytest.MonkeyPatch,
    model: WatsonxSDKModel,
    exc: Exception,
) -> _FailingAchatClient:
    """Replace ``model._build_client`` with a client whose ``achat`` raises ``exc``."""
    client = _FailingAchatClient(exc)
    monkeypatch.setattr(model, "_build_client", lambda: client)
    return client


@pytest.mark.parametrize(
    ("exc", "label"),
    [
        (WMLClientError("watsonx api request failed"), "WMLClientError"),
        (_FakeSDKSubError("auth rejected"), "WMLClientError subclass"),
        (httpx.ReadTimeout("read timed out"), "httpx timeout"),
        (httpx.ConnectError("connection refused"), "httpx connect error"),
        (httpx.HTTPError("generic transport error"), "httpx.HTTPError base"),
    ],
)
async def test_request_wraps_sdk_failures_in_model_api_error(
    monkeypatch: pytest.MonkeyPatch,
    watsonx_settings_factory: WatsonxSettingsFactory,
    exc: Exception,
    label: str,
) -> None:
    """Every SDK / httpx failure from ``achat`` surfaces as ``ModelAPIError``.

    Pins the load-bearing failover contract (plan.md Entity 2): the SDK base
    ``WMLClientError`` and any subclass, plus the underlying httpx errors
    (timeout → Req 5.6, connect → Req 4.4, and the ``HTTPError`` base covering
    the rest), are all caught and re-raised as
    :class:`pydantic_ai.exceptions.ModelAPIError` so ``FallbackModel.fallback_on``
    recovers them. The original error is chained via ``__cause__`` (debugging is
    not lost) and its class name is carried in the message; ``model_name`` is the
    configured watsonx model so the span's ``gen_ai.request.model`` stays correct.
    """
    model = WatsonxSDKModel(watsonx_settings_factory())
    _stub_failing_achat(monkeypatch, model, exc)

    messages: list[ModelMessage] = [ModelRequest(parts=[UserPromptPart("hi")])]
    with pytest.raises(ModelAPIError) as excinfo:
        await model.request(messages, None, ModelRequestParameters())

    assert excinfo.value.__cause__ is exc, label
    assert excinfo.value.model_name == WATSONX_TEST_MODEL_ID
    assert type(exc).__name__ in str(excinfo.value)


async def test_request_wraps_first_call_client_build_failure(
    monkeypatch: pytest.MonkeyPatch,
    watsonx_settings_factory: WatsonxSettingsFactory,
) -> None:
    """A failure building the SDK client on the first call wraps too (Req 4.4).

    The SDK client is built lazily on the first request and its ``APIClient``
    authenticates over the network, so an unreachable endpoint or DNS failure
    surfaces from ``_build_client`` — not ``achat``. That first-call failure must
    also become a :class:`ModelAPIError` so failover still recovers it.
    """
    model = WatsonxSDKModel(watsonx_settings_factory())
    boom = httpx.ConnectError("name resolution failed")

    def _raise() -> Any:
        raise boom

    monkeypatch.setattr(model, "_build_client", _raise)

    messages: list[ModelMessage] = [ModelRequest(parts=[UserPromptPart("hi")])]
    with pytest.raises(ModelAPIError) as excinfo:
        await model.request(messages, None, ModelRequestParameters())

    assert excinfo.value.__cause__ is boom


async def test_request_does_not_retry_on_failure(
    monkeypatch: pytest.MonkeyPatch,
    watsonx_settings_factory: WatsonxSettingsFactory,
) -> None:
    """The failing ``achat`` is invoked exactly once — no retries (Req 6.1/6.3/6.4).

    Provider-level resilience is delegated entirely to the fallback chain (the
    Ollama-consistent decision); ``request`` must not retry the failed call. The
    counting fake proves a single invocation.
    """
    model = WatsonxSDKModel(watsonx_settings_factory())
    client = _stub_failing_achat(monkeypatch, model, WMLClientError("boom"))

    messages: list[ModelMessage] = [ModelRequest(parts=[UserPromptPart("hi")])]
    with pytest.raises(ModelAPIError):
        await model.request(messages, None, ModelRequestParameters())

    assert client.calls == 1


async def test_request_propagates_unexpected_error_unwrapped(
    monkeypatch: pytest.MonkeyPatch,
    watsonx_settings_factory: WatsonxSettingsFactory,
) -> None:
    """A non-SDK / non-httpx error is *not* wrapped — fail loud (boundary).

    The wrapping is deliberately scoped to ``WMLClientError`` + ``httpx.HTTPError``
    (plan.md Entity 2). An unexpected error type (here a programming-bug
    ``RuntimeError``) must propagate unchanged rather than be masked as a
    recoverable ``ModelAPIError``; over-catching would hide real defects and
    silently trigger failover on bugs.
    """
    model = WatsonxSDKModel(watsonx_settings_factory())
    sentinel = RuntimeError("unexpected non-API failure")
    _stub_failing_achat(monkeypatch, model, sentinel)

    messages: list[ModelMessage] = [ModelRequest(parts=[UserPromptPart("hi")])]
    with pytest.raises(RuntimeError, match="unexpected non-API failure"):
        await model.request(messages, None, ModelRequestParameters())


# ---------------------------------------------------------------------------
# Task 5.5 — ``request_stream`` is a deliberate fail-loud (streaming out of scope)
#
# The ``Model`` ABC supplies a default ``request_stream`` that raises a *generic*
# ``NotImplementedError`` ("Streamed requests not supported by this ...").
# Task 5.5 overrides it with a watsonx-specific *out-of-scope* message so the
# refusal is an intentional design decision (streaming is out of scope for the
# ``/chat`` single-request transport — spec.md "Out of Scope") rather than an
# inherited accident. The match asserts on text unique to our override (absent
# from the base message) so this is a genuine RED before the override lands.
# ---------------------------------------------------------------------------


async def test_request_stream_raises_out_of_scope(
    watsonx_settings_factory: WatsonxSettingsFactory,
) -> None:
    """``request_stream`` fails loud as out of scope (Req 2.1).

    Streaming is out of scope for the watsonx SDK transport; entering the
    ``request_stream`` async context manager must raise ``NotImplementedError``
    with a watsonx-specific out-of-scope message (not the base ABC's generic
    one), so a future caller wiring streaming gets an explicit, greppable
    refusal rather than a silent or misleading default.
    """
    model = WatsonxSDKModel(watsonx_settings_factory())

    messages: list[ModelMessage] = [ModelRequest(parts=[UserPromptPart("hi")])]
    with pytest.raises(NotImplementedError, match="out of scope"):
        async with model.request_stream(messages, None, ModelRequestParameters()):
            pass  # pragma: no cover — context entry raises before the body runs


# ---------------------------------------------------------------------------
# Task 5.6 — ``_build_watsonx`` transport dispatch (SDK branch)
#
# ``_build_watsonx`` is the factory entry point (``llm.factory.get_model`` routes
# ``LLM_PROVIDER=watsonx`` here). It dispatches on the validated
# ``WATSONX_TRANSPORT`` selector: ``"sdk"`` (the default) builds a
# ``WatsonxSDKModel`` (Req 2.1). The ``"litellm"`` branch — with its dependency
# import-guard — is Task 6's; until it lands ``_build_watsonx`` must fail loud on
# that selector rather than silently returning the SDK model (which would mask
# the unbuilt transport). Construction stays I/O-free (Req 1.5): the dispatch
# only constructs the lazy-client Model, it issues no network call.
# ---------------------------------------------------------------------------


def test_build_watsonx_sdk_transport_returns_sdk_model(
    watsonx_settings_factory: WatsonxSettingsFactory,
) -> None:
    """``transport="sdk"`` builds a :class:`WatsonxSDKModel` (Req 2.1).

    The explicit selector resolves to the SDK transport — the same Model the
    factory dispatch test asserts for the default provider, here pinned to the
    concrete subtype so a future transport addition cannot silently reroute the
    SDK selector.
    """
    model = _build_watsonx(watsonx_settings_factory(WATSONX_TRANSPORT="sdk"))

    assert isinstance(model, WatsonxSDKModel)


def test_build_watsonx_defaults_to_sdk_transport(
    watsonx_settings_factory: WatsonxSettingsFactory,
) -> None:
    """An unset ``WATSONX_TRANSPORT`` defaults to the SDK transport (Req 2.1).

    The config validator maps unset → ``"sdk"`` (Task 2.3), so ``_build_watsonx``
    with no transport override must still build a :class:`WatsonxSDKModel`.
    """
    model = _build_watsonx(watsonx_settings_factory())

    assert isinstance(model, WatsonxSDKModel)


def test_build_watsonx_is_io_free(
    monkeypatch: pytest.MonkeyPatch,
    watsonx_settings_factory: WatsonxSettingsFactory,
) -> None:
    """``_build_watsonx`` performs no network I/O (Req 1.5).

    Dispatch constructs the lazy-client :class:`WatsonxSDKModel` only; the SDK
    client is built on the first request (Task 5.2). Detonating both httpx
    transport hooks proves the builder issues no egress at construction.
    """
    monkeypatch.setattr(httpx.Client, "send", _explode_sync)
    monkeypatch.setattr(httpx.AsyncClient, "send", _explode_async)

    model = _build_watsonx(watsonx_settings_factory())

    assert isinstance(model, Model)


# Task 6 lands the real ``transport="litellm"`` branch (import guard + LiteLLM
# provider construction); its dedicated tests live in
# ``test_watsonx_litellm_construction.py``. The Task 5.6 placeholder that
# asserted a ``NotImplementedError`` fail-loud was removed atomically with that
# branch — keeping it would assert behaviour the implementation no longer has.
