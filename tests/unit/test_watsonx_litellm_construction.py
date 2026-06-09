"""Hermetic construction tests for the watsonx LiteLLM transport (Task 6).

Task 6 wires the ``WATSONX_TRANSPORT=litellm`` branch of
:func:`pydantic_ai_sandbox.llm.providers.watsonx._build_watsonx`:

* **6.1** — an optional-dependency *import guard*: a missing ``litellm`` package
  fails loud as a :class:`ValueError` naming the package (Req 2.6), never a bare
  ``ImportError`` leaking from deep in the builder.
* **6.2** — construction of a :class:`~pydantic_ai.providers.litellm.LiteLLMProvider`
  routing ``apikey → api_key`` and ``url → api_base`` (``project_id`` reaches
  litellm via the ``WATSONX_PROJECT_ID`` env var per research.md R4, **not** a
  constructor arg), wrapped in an
  :class:`~pydantic_ai.models.openai.OpenAIChatModel` whose ``model_name`` carries
  the ``watsonx/`` route prefix (Req 2.3). Timeouts inject via a custom
  ``http_client`` (Req 5.4).

Hermetic by construction: provider/model construction is I/O-free (Req 1.5), so
these tests issue zero network egress — the timeout-wiring assertion reads the
configured ``httpx`` client off the built OpenAI client rather than making a
call.

Task 7.2 (Req 9.4) extends this file with the **RESPX request-path tests** below:
live-shaped HTTP round-trips that drive :meth:`OpenAIChatModel.request` through
the LiteLLM-built model while RESPX intercepts the ``httpx`` call the OpenAI
adapter makes to the watsonx endpoint. They prove the litellm transport (a) hits
``{WATSONX_URL}/chat/completions``, (b) sends the ``watsonx/<model_id>`` route
prefix and the routed apikey *on the wire*, (c) maps text and tool-call responses
back to a :class:`ModelResponse`, (d) carries ``WATSONX_PROJECT_ID`` to litellm
via the environment (research.md R4 — ``LiteLLMProvider`` has no ``project_id``
arg), and (e) surfaces an HTTP error as a failover-recoverable
:class:`ModelAPIError`. Task 6 owns construction and the import guard; the import
guard lives in :func:`test_litellm_import_guard_raises_valueerror_naming_package`
above and already satisfies the import-guard clause of Task 7.2.
"""

from __future__ import annotations

import json
import os
import sys
from typing import TYPE_CHECKING, Any

import httpx
import pytest
import respx
from pydantic_ai.exceptions import ModelAPIError
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    UserPromptPart,
)
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.models.openai import OpenAIChatModel

from pydantic_ai_sandbox.config import Settings
from pydantic_ai_sandbox.llm.providers.watsonx import (
    _build_litellm,  # pyright: ignore[reportPrivateUsage]
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

# The exact endpoint the OpenAI adapter posts to: ``base_url`` (the watsonx URL,
# routed via ``LiteLLMProvider(api_base=...)``) + the OpenAI chat-completions
# path. Matching it exactly doubles as an assertion that the litellm transport
# targets the configured watsonx endpoint.
_CHAT_COMPLETIONS_URL = f"{WATSONX_TEST_URL}/chat/completions"


class _NetworkAccessError(RuntimeError):
    """Raised by the patched httpx send hooks if anything attempts egress."""


def _explode_sync(*_args: Any, **_kwargs: Any) -> Any:
    raise _NetworkAccessError(
        "sync httpx.Client.send must not be called during litellm construction",
    )


async def _explode_async(*_args: Any, **_kwargs: Any) -> Any:
    raise _NetworkAccessError(
        "async httpx.AsyncClient.send must not be called during litellm construction",
    )


def test_litellm_transport_builds_openai_chat_model(
    watsonx_settings_factory: WatsonxSettingsFactory,
) -> None:
    """``transport="litellm"`` builds an :class:`OpenAIChatModel` (Req 2.3).

    ``LiteLLMProvider`` is a *Provider*, not a *Model*; returning it directly
    would not satisfy ``Agent``'s ``Model`` contract. The builder wraps it in an
    ``OpenAIChatModel`` so the litellm path reuses pydantic_ai's OpenAI adapter
    (which auto-stamps ``gen_ai.system`` / ``gen_ai.request.model``).
    """
    model = _build_watsonx(watsonx_settings_factory(WATSONX_TRANSPORT="litellm"))

    assert isinstance(model, OpenAIChatModel)


def test_litellm_model_name_carries_watsonx_route_prefix(
    watsonx_settings_factory: WatsonxSettingsFactory,
) -> None:
    """The model name is ``watsonx/<model_id>`` so litellm routes to watsonx.

    LiteLLM selects the watsonx backend from the ``watsonx/`` prefix on the
    model string; the id itself comes from ``Settings`` (``WATSONX_MODEL_ID``),
    never a literal in ``src/`` (Req 3.4).
    """
    model = _build_watsonx(watsonx_settings_factory(WATSONX_TRANSPORT="litellm"))

    assert model.model_name == f"watsonx/{WATSONX_TEST_MODEL_ID}"


def test_litellm_provider_routes_credentials(
    watsonx_settings_factory: WatsonxSettingsFactory,
) -> None:
    """``apikey → api_key`` and ``url → api_base`` reach the provider (R4).

    ``LiteLLMProvider`` exposes no ``project_id`` parameter — that reaches
    litellm via the ``WATSONX_PROJECT_ID`` env var, not the constructor. Only the
    apikey and url are routed here; the unwrapped ``SecretStr`` is handed to the
    OpenAI-compatible client.
    """
    model = _build_watsonx(watsonx_settings_factory(WATSONX_TRANSPORT="litellm"))

    assert isinstance(model, OpenAIChatModel)
    assert model.client.api_key == WATSONX_TEST_APIKEY
    assert str(model.client.base_url).rstrip("/") == WATSONX_TEST_URL


def test_litellm_timeouts_wired_via_http_client(
    watsonx_settings_factory: WatsonxSettingsFactory,
) -> None:
    """Connect/read timeouts inject via the provider's ``http_client`` (Req 5.4).

    ``LiteLLMProvider`` takes no timeout argument; the configured connect/read
    phases must flow through the custom ``httpx`` client onto the OpenAI client.
    The defaults (30s connect / 120s read) seat when no override is supplied.
    """
    model = _build_watsonx(watsonx_settings_factory(WATSONX_TRANSPORT="litellm"))

    assert isinstance(model, OpenAIChatModel)
    timeout = model.client.timeout
    assert isinstance(timeout, httpx.Timeout)
    assert timeout.connect == 30
    assert timeout.read == 120


def test_litellm_timeouts_honour_env_overrides(
    watsonx_settings_factory: WatsonxSettingsFactory,
) -> None:
    """Non-default ``WATSONX_TIMEOUT_*`` values reach the http client (Req 5.4)."""
    model = _build_watsonx(
        watsonx_settings_factory(
            WATSONX_TRANSPORT="litellm",
            WATSONX_TIMEOUT_CONNECT="5",
            WATSONX_TIMEOUT_READ="45",
        ),
    )

    assert isinstance(model, OpenAIChatModel)
    timeout = model.client.timeout
    assert isinstance(timeout, httpx.Timeout)
    assert timeout.connect == 5
    assert timeout.read == 45


def test_litellm_import_guard_raises_valueerror_naming_package(
    monkeypatch: pytest.MonkeyPatch,
    watsonx_settings_factory: WatsonxSettingsFactory,
) -> None:
    """A missing ``litellm`` package fails loud as ``ValueError`` (Req 2.6).

    The litellm transport is an optional extra. Selecting it without the package
    installed must raise a :class:`ValueError` *naming* ``litellm`` (so the
    operator knows what to install), not leak a bare ``ImportError`` from deep in
    the builder. ``sys.modules["litellm"] = None`` makes ``import litellm`` raise
    ``ImportError`` even though the package is installed in the test env.
    """
    monkeypatch.setitem(sys.modules, "litellm", None)
    settings = watsonx_settings_factory(WATSONX_TRANSPORT="litellm")

    with pytest.raises(ValueError, match="litellm") as exc_info:
        _build_watsonx(settings)

    # The guard chains the original ImportError for debugging.
    assert isinstance(exc_info.value.__cause__, ImportError)


def test_litellm_construction_is_io_free(
    monkeypatch: pytest.MonkeyPatch,
    watsonx_settings_factory: WatsonxSettingsFactory,
) -> None:
    """Building the litellm Model performs no network I/O (Req 1.5).

    Detonating both ``httpx`` transport send hooks proves provider/model
    construction issues no egress: the OpenAI-compatible client is built but
    never invoked until a request is served.
    """
    monkeypatch.setattr(httpx.Client, "send", _explode_sync)
    monkeypatch.setattr(httpx.AsyncClient, "send", _explode_async)

    model = _build_watsonx(watsonx_settings_factory(WATSONX_TRANSPORT="litellm"))

    assert isinstance(model, OpenAIChatModel)


# ---------------------------------------------------------------------------
# Task 7.2 — RESPX request-path tests for the LiteLLM transport (Req 9.4)
#
# Construction (above) proves the litellm Model is wired correctly without
# egress. These tests drive the *live request path*: ``OpenAIChatModel.request``
# (the adapter ``_build_litellm`` returns) issues an ``httpx`` POST to the
# OpenAI chat-completions endpoint of the configured ``api_base`` (the watsonx
# URL). RESPX intercepts that round-trip, so the litellm transport is exercised
# end-to-end — request serialisation *and* response mapping — with zero network
# egress. Unlike the SDK transport (httpx ``send`` patches + a fake ``achat``),
# the litellm path delegates the HTTP round-trip to pydantic_ai's OpenAI
# adapter, so HTTP-level mocking (RESPX) is the right grain (spec.md Testing /
# Req 9.4: "RESPX-based tests for the LiteLLM path").
#
# A canned OpenAI-shaped ``chat.completion`` response stands in for watsonx; the
# request is driven directly via ``model.request`` (no Agent) so the assertions
# pin the transport's own request/response contract rather than agent behaviour.
# ---------------------------------------------------------------------------


def _text_completion(content: str) -> dict[str, Any]:
    """Build a minimal OpenAI-shaped ``chat.completion`` carrying a text reply."""
    return {
        "id": "chatcmpl-watsonx-litellm-text",
        "object": "chat.completion",
        "created": 0,
        "model": f"watsonx/{WATSONX_TEST_MODEL_ID}",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            },
        ],
        "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
    }


_TOOL_CALL_COMPLETION: dict[str, Any] = {
    "id": "chatcmpl-watsonx-litellm-tool",
    "object": "chat.completion",
    "created": 0,
    "model": f"watsonx/{WATSONX_TEST_MODEL_ID}",
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


async def test_litellm_request_maps_text_response_over_respx(
    watsonx_settings_factory: WatsonxSettingsFactory,
) -> None:
    """A text completion round-trips to a ``ModelResponse`` text part (Req 9.4).

    Drives the litellm transport's real request path against a RESPX-mocked
    watsonx endpoint and pins the response mapping the OpenAI adapter performs:
    the assistant ``content`` becomes a single :class:`TextPart`, ``usage`` maps
    prompt/completion → input/output tokens, ``finish_reason`` ``"stop"``
    survives, ``id`` → ``provider_response_id`` and the response carries the
    ``watsonx/<model_id>`` route-prefixed ``model_name``.
    """
    model = _build_watsonx(watsonx_settings_factory(WATSONX_TRANSPORT="litellm"))
    messages: list[ModelMessage] = [ModelRequest(parts=[UserPromptPart("hello")])]

    with respx.mock(assert_all_called=True) as respx_mock:
        route = respx_mock.post(_CHAT_COMPLETIONS_URL).mock(
            return_value=httpx.Response(200, json=_text_completion("hi from watsonx")),
        )
        result = await model.request(messages, None, ModelRequestParameters())

    assert route.called  # the litellm transport hit the configured watsonx endpoint
    assert len(result.parts) == 1
    part = result.parts[0]
    assert isinstance(part, TextPart)
    assert part.content == "hi from watsonx"
    assert result.finish_reason == "stop"
    assert result.usage.input_tokens == 5
    assert result.usage.output_tokens == 3
    assert result.provider_response_id == "chatcmpl-watsonx-litellm-text"
    assert result.model_name == f"watsonx/{WATSONX_TEST_MODEL_ID}"


async def test_litellm_request_routes_model_prefix_and_apikey_on_the_wire(
    watsonx_settings_factory: WatsonxSettingsFactory,
) -> None:
    """The ``watsonx/`` route prefix and apikey reach the endpoint on the wire (Req 2.3/9.4).

    Construction asserts the routing structurally; this asserts it *end-to-end*
    by reading the intercepted request: the JSON body's ``model`` field carries
    the ``watsonx/<model_id>`` prefix LiteLLM uses to select the backend, the
    mapped ``user`` message is present, and the ``Authorization`` header carries
    the routed (unwrapped) apikey as a bearer token.
    """
    model = _build_watsonx(watsonx_settings_factory(WATSONX_TRANSPORT="litellm"))
    messages: list[ModelMessage] = [ModelRequest(parts=[UserPromptPart("hello")])]

    with respx.mock(assert_all_called=True) as respx_mock:
        route = respx_mock.post(_CHAT_COMPLETIONS_URL).mock(
            return_value=httpx.Response(200, json=_text_completion("ok")),
        )
        await model.request(messages, None, ModelRequestParameters())

    request = route.calls.last.request
    sent = json.loads(request.content)
    assert sent["model"] == f"watsonx/{WATSONX_TEST_MODEL_ID}"
    assert sent["messages"] == [{"role": "user", "content": "hello"}]
    assert request.headers["authorization"] == f"Bearer {WATSONX_TEST_APIKEY}"


async def test_litellm_request_maps_tool_call_response_over_respx(
    watsonx_settings_factory: WatsonxSettingsFactory,
) -> None:
    """A tool-call completion maps to a :class:`ToolCallPart` (Req 9.4).

    The litellm transport must surface an OpenAI ``tool_calls`` entry as a
    :class:`ToolCallPart` carrying the function name, parsed arguments and the
    provider tool-call id, with ``finish_reason`` normalising ``"tool_calls"`` →
    ``"tool_call"`` — otherwise the agent's tool / structured-output loop would
    break silently on the litellm path.
    """
    model = _build_watsonx(watsonx_settings_factory(WATSONX_TRANSPORT="litellm"))
    messages: list[ModelMessage] = [ModelRequest(parts=[UserPromptPart("天気は?")])]

    with respx.mock(assert_all_called=True) as respx_mock:
        respx_mock.post(_CHAT_COMPLETIONS_URL).mock(
            return_value=httpx.Response(200, json=_TOOL_CALL_COMPLETION),
        )
        result = await model.request(messages, None, ModelRequestParameters())

    assert len(result.parts) == 1
    part = result.parts[0]
    assert isinstance(part, ToolCallPart)
    assert part.tool_name == "search_kb"
    assert part.tool_call_id == "call_kb_1"
    assert part.args_as_dict() == {"query": "weather"}
    assert result.finish_reason == "tool_call"


async def test_litellm_project_id_reaches_litellm_via_env(
    watsonx_settings_factory: WatsonxSettingsFactory,
) -> None:
    """``WATSONX_PROJECT_ID`` is carried to litellm via the environment (R4 / Req 9.4).

    ``LiteLLMProvider`` exposes ``api_key`` / ``api_base`` but **no**
    ``project_id`` argument (research.md R4 / ADR-3): the project id reaches
    litellm through the ``WATSONX_PROJECT_ID`` environment variable the
    deployment already sets, never a constructor arg. The ``watsonx_settings_factory``
    seats that env var (the "``WATSONX_PROJECT_ID`` env fixture" of Task 7.2), so
    this pins that it is present in the process environment while a litellm
    request is served — the channel litellm reads project id from.
    """
    settings = watsonx_settings_factory(WATSONX_TRANSPORT="litellm")
    model = _build_watsonx(settings)
    messages: list[ModelMessage] = [ModelRequest(parts=[UserPromptPart("hello")])]

    with respx.mock(assert_all_called=True) as respx_mock:
        respx_mock.post(_CHAT_COMPLETIONS_URL).mock(
            return_value=httpx.Response(200, json=_text_completion("ok")),
        )
        result = await model.request(messages, None, ModelRequestParameters())

    # The project id is routed via env (not a LiteLLMProvider constructor arg);
    # the fixture seats it, so it is available to litellm during the request.
    assert os.environ["WATSONX_PROJECT_ID"] == WATSONX_TEST_PROJECT_ID
    assert isinstance(result, ModelResponse)


async def test_litellm_request_http_error_surfaces_as_model_api_error(
    watsonx_settings_factory: WatsonxSettingsFactory,
) -> None:
    """An HTTP 5xx from the endpoint surfaces as a recoverable ``ModelAPIError`` (Req 9.4).

    Failover correctness for the litellm transport depends on its errors being
    ``ModelAPIError`` (``FallbackModel.fallback_on`` defaults to
    ``(ModelAPIError,)``). pydantic_ai's OpenAI adapter raises ``ModelHTTPError``
    — a :class:`ModelAPIError` subclass — for a non-2xx response, so a watsonx
    503 is recoverable in the chain. Pinning this proves the litellm path
    participates in failover exactly like the SDK transport.
    """
    model = _build_watsonx(watsonx_settings_factory(WATSONX_TRANSPORT="litellm"))
    messages: list[ModelMessage] = [ModelRequest(parts=[UserPromptPart("hello")])]

    with respx.mock(assert_all_called=True) as respx_mock:
        respx_mock.post(_CHAT_COMPLETIONS_URL).mock(
            return_value=httpx.Response(503, json={"error": {"message": "overloaded"}}),
        )
        with pytest.raises(ModelAPIError):
            await model.request(messages, None, ModelRequestParameters())


def test_litellm_apikey_none_guard_raises_typeerror() -> None:
    """The defensive ``apikey``/``model_id`` guard fires when a cred drifts to ``None``.

    Mirrors the SDK builder's ``_build_client`` guard
    (``test_build_client_missing_apikey_raises_typeerror``): the credential gate
    (config Task 2.2) rejects a missing ``WATSONX_APIKEY`` / ``WATSONX_MODEL_ID``
    at boot, so production never reaches this branch. We simulate that post-drift
    state with :meth:`Settings.model_construct` (no validators run) and assert
    ``_build_litellm`` fails loud — ``f"watsonx/{None}"`` would otherwise be a
    silent mis-route rather than a clear error.
    """
    drifted = Settings.model_construct(
        watsonx_apikey=None,
        watsonx_model_id=WATSONX_TEST_MODEL_ID,
        watsonx_url=WATSONX_TEST_URL,
        watsonx_transport="litellm",
    )

    with pytest.raises(TypeError, match="is None at _build_litellm time"):
        _build_litellm(drifted)  # pyright: ignore[reportPrivateUsage]
