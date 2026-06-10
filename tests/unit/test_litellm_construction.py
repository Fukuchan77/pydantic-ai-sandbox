"""Hermetic construction + observability/output-mode parity tests for ``LiteLLMModel``.

Drives Task 2.1 (the I/O-free ``__init__`` and the ``model_name`` / ``system`` /
``profile`` properties) and the parity clauses Task 3.1 verifies (Req 1.4 / 1.5 /
10.6): the ``system`` value derived from the route provider segment, the same
value stamped onto the built ``ModelResponse.provider_name`` (SDK-path parity),
and a ``profile`` that keeps ``supports_json_schema_output`` falsy so
``build_chat_agent`` does not force ``NativeOutput`` / ``response_format``.

Every case is hermetic: construction issues no network egress, and the single
``provider_name``-parity case mocks :func:`litellm.acompletion` so no request
leaves the process.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx
import litellm
from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, UserPromptPart
from pydantic_ai.models import ModelRequestParameters

from pydantic_ai_sandbox.llm.providers.litellm import LiteLLMModel

if TYPE_CHECKING:
    from collections.abc import Callable

    import pytest

_WATSONX_ROUTE = "watsonx/dummy-watsonx-model"


def _model(model_name: str = _WATSONX_ROUTE, **overrides: Any) -> LiteLLMModel:
    """Build a ``LiteLLMModel`` with default (connect, read) timeouts."""
    params: dict[str, Any] = {
        "model_name": model_name,
        "timeout_connect": 30.0,
        "timeout_read": 120.0,
    }
    params.update(overrides)
    return LiteLLMModel(**params)


def _text_completion() -> litellm.ModelResponse:
    """A minimal OpenAI-shaped text completion as a real ``litellm.ModelResponse``."""
    return litellm.ModelResponse(
        id="chatcmpl-parity",
        object="chat.completion",
        created=0,
        model=_WATSONX_ROUTE,
        choices=[
            {
                "index": 0,
                "message": {"role": "assistant", "content": "hi"},
                "finish_reason": "stop",
            },
        ],
        usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    )


class _NetworkAccessError(RuntimeError):
    """Raised by the patched httpx send hooks if anything attempts egress."""


def test_init_is_io_free(monkeypatch: pytest.MonkeyPatch) -> None:
    """Constructing the model performs no network I/O (Req 1.3).

    Detonating both ``httpx`` transport send hooks proves construction issues no
    egress — the first network call is the first :meth:`request`.
    """

    def _explode_sync(*_a: Any, **_k: Any) -> Any:
        raise _NetworkAccessError("sync httpx.Client.send must not run at construction")

    async def _explode_async(*_a: Any, **_k: Any) -> Any:
        raise _NetworkAccessError("async httpx.AsyncClient.send must not run at construction")

    monkeypatch.setattr(httpx.Client, "send", _explode_sync)
    monkeypatch.setattr(httpx.AsyncClient, "send", _explode_async)

    model = _model()

    assert isinstance(model, LiteLLMModel)


def test_model_name_returns_route() -> None:
    """``model_name`` returns the configured LiteLLM route verbatim (Req 1.2/9.x)."""
    assert _model(_WATSONX_ROUTE).model_name == _WATSONX_ROUTE


def test_system_derives_watsonx_from_route_prefix() -> None:
    """``system`` is the route provider segment → ``"watsonx"`` (Req 1.4 / 10.6).

    The instrumentation ``gen_ai.system`` attribute must match the SDK transport
    for the watsonx route, so it is derived from the ``<provider>/`` prefix.
    """
    assert _model("watsonx/ibm/granite-3").system == "watsonx"


def test_system_falls_back_to_litellm_for_prefixless_route() -> None:
    """A route with no ``<provider>/`` prefix falls back to ``"litellm"`` (Req 1.4)."""
    assert _model("granite-3").system == "litellm"


def test_profile_keeps_json_schema_output_falsy() -> None:
    """``profile`` keeps ``supports_json_schema_output`` falsy (Req 1.5).

    Tool-mode parity with the SDK transport: a truthy flag would make
    ``build_chat_agent`` wrap output in ``NativeOutput`` / force ``response_format``,
    which the watsonx route does not support.
    """
    assert _model().profile.get("supports_json_schema_output", False) is False


async def test_response_provider_name_matches_system(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The built ``ModelResponse`` identity fields match ``system`` / route (Req 1.4 / 10.6 parity).

    The same route-derived ``system`` value passed to ``build_response`` must
    surface on the response, so ``gen_ai.system`` and the response provider agree
    and match the SDK path for the watsonx route. The ``model_name`` (route) is
    likewise stamped, so ``gen_ai.request.model`` agrees too — together these
    prove full observability parity, not just the provider segment.
    """
    fake: Callable[..., Any] = _returning(_text_completion())
    monkeypatch.setattr(litellm, "acompletion", fake)
    model = _model()
    messages: list[ModelMessage] = [ModelRequest(parts=[UserPromptPart("hello")])]

    result = await model.request(messages, None, ModelRequestParameters())

    assert isinstance(result, ModelResponse)
    assert result.provider_name == model.system == "watsonx"
    assert result.model_name == model.model_name == _WATSONX_ROUTE


def _returning(response: Any) -> Any:
    """An async ``acompletion`` stand-in that ignores kwargs and returns ``response``."""

    async def _fake(**_kwargs: Any) -> Any:
        return response

    return _fake
