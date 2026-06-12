"""Hermetic timeout-passthrough tests for ``LiteLLMModel.request`` (Tasks 2.2 → 3.5).

Pins that both configured timeout phases reach :func:`litellm.acompletion` shaped
as ``httpx.Timeout(read, connect=connect)`` (Req 5.1 / 10.1) — the **same** shaping
the SDK transport applies to its ``httpx`` client
(``WatsonxSDKModel._build_client``, ``watsonx.py``: ``httpx.Timeout(read,
connect=connect)``), so timeout behaviour is parity-equivalent across transports.

Why the shape is load-bearing, not cosmetic: ``httpx.Timeout`` rejects a partial
``(connect, read)`` spec, so the read value seeds the overall default (covering the
write / pool phases) while ``connect`` overrides the connect phase. Passing a bare
single float instead would silently collapse both phases into one value — dropping
the distinct connect budget. These tests assert the timeout reaches ``acompletion``
as the structured ``httpx.Timeout`` object with **both** phases distinct and
correctly mapped, so that regression is caught.

``acompletion`` is mocked (kwarg-capturing stand-in), so no request leaves the
process.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx
import litellm
import pytest
from pydantic_ai.messages import ModelMessage, ModelRequest, UserPromptPart
from pydantic_ai.models import ModelRequestParameters

from pydantic_ai_sandbox.llm.providers.litellm import LiteLLMModel

if TYPE_CHECKING:
    from collections.abc import Callable

_ROUTE = "watsonx/dummy-watsonx-model"
# Distinct connect / read values (not the 30 / 120 defaults, and not equal to each
# other) so a single-float collapse OR a connect/read swap is caught, not masked by
# coincidentally-equal phases.
_CONNECT = 7.0
_READ = 300.0


def _model(*, timeout_connect: float = _CONNECT, timeout_read: float = _READ) -> LiteLLMModel:
    return LiteLLMModel(
        model_name=_ROUTE,
        timeout_connect=timeout_connect,
        timeout_read=timeout_read,
    )


def _text_response() -> litellm.ModelResponse:
    return litellm.ModelResponse(
        id="chatcmpl-timeout",
        object="chat.completion",
        created=0,
        model=_ROUTE,
        choices=[
            {
                "index": 0,
                "message": {"role": "assistant", "content": "ok"},
                "finish_reason": "stop",
            },
        ],
        usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    )


def _capturing(captured: dict[str, Any]) -> Callable[..., Any]:
    """An async ``acompletion`` stand-in that records its kwargs."""

    async def _fake(**kwargs: Any) -> Any:
        captured.update(kwargs)
        return _text_response()

    return _fake


async def _capture_timeout(
    monkeypatch: pytest.MonkeyPatch,
    model: LiteLLMModel,
) -> Any:
    """Drive one ``request`` and return the ``timeout`` kwarg seen by ``acompletion``."""
    captured: dict[str, Any] = {}
    monkeypatch.setattr(litellm, "acompletion", _capturing(captured))
    messages: list[ModelMessage] = [ModelRequest(parts=[UserPromptPart("hi")])]

    await model.request(messages, None, ModelRequestParameters())

    return captured["timeout"]


async def test_timeout_passed_as_httpx_timeout_instance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The ``timeout`` kwarg reaches ``acompletion`` as a structured ``httpx.Timeout``.

    Not a bare ``float``: a single scalar would collapse the connect and read
    phases into one budget, dropping the distinct connect timeout (Req 5.1). The
    structured object is what carries both phases through to the backend.
    """
    timeout = await _capture_timeout(monkeypatch, _model())

    assert isinstance(timeout, httpx.Timeout)
    assert not isinstance(timeout, float)


@pytest.mark.parametrize(
    ("connect", "read"),
    [
        (_CONNECT, _READ),  # distinct custom values
        (30.0, 120.0),  # the project defaults
        (15.0, 15.0),  # equal phases must still both be honoured
    ],
)
async def test_both_connect_and_read_phases_reach_acompletion(
    monkeypatch: pytest.MonkeyPatch,
    connect: float,
    read: float,
) -> None:
    """Both configured phases reach ``acompletion``, correctly mapped (Req 5.1 / 10.1).

    ``connect`` lands on ``httpx.Timeout.connect`` and ``read`` on
    ``httpx.Timeout.read`` — proving the configured values flow through verbatim
    (never hard-coded) and are not swapped. Exercising distinct values catches a
    single-float collapse; the defaults and the equal-phase case guard the
    boundaries.
    """
    timeout = await _capture_timeout(
        monkeypatch,
        _model(timeout_connect=connect, timeout_read=read),
    )

    assert timeout.connect == connect
    assert timeout.read == read


async def test_timeout_shape_matches_sdk_read_seeds_overall_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The read value seeds write / pool — parity with the SDK transport's shaping.

    Both transports construct ``httpx.Timeout(read, connect=connect)``: the read
    value is the positional default seeding every unset phase (write, pool) while
    ``connect`` overrides only the connect phase. Pinning ``write == pool == read``
    (and ``connect`` distinct) proves the exact documented shape — distinguishing it
    from an ``httpx.Timeout(connect=..., read=...)`` spelling that would leave
    write / pool unset — so the LiteLLM path stays parity-equivalent to the SDK
    ``httpx`` client (Req 5.1).
    """
    timeout = await _capture_timeout(monkeypatch, _model())

    assert timeout.connect == _CONNECT
    assert timeout.read == _READ
    # The read value seeds the overall default for the phases not explicitly set.
    assert timeout.write == _READ
    assert timeout.pool == _READ
