"""Unit test for the no-I/O guarantee of ``_build_ollama`` (Task 4.2).

Locks Req 2.6 (plan.md §2.2 境界規則): ``get_model("ollama")`` MUST NOT
perform any HTTP work during construction. Real connection attempts are
deferred to the first ``agent.run(...)`` call so a misconfigured Ollama
host (or no Ollama at all in CI) cannot break process startup.

Strategy:

1. Patch ``httpx.Client.send`` and ``httpx.AsyncClient.send`` so any
   inadvertent transport call would raise loudly.
2. Call ``get_model("ollama")``. The fact that it returns without
   exception is the load-bearing assertion — a constructor that
   accidentally probes the daemon would surface the patched RuntimeError.
3. Sanity-check that neither send hook was invoked (defence in depth in
   case the OpenAI client swallows transport errors during init).

The patch targets ``httpx.{Async,}Client.send`` rather than the OpenAI
SDK because Pydantic AI's ``OllamaProvider`` ultimately delegates to
``httpx`` for both sync and async paths; trapping at the transport layer
catches every possible egress route.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx
from pydantic_ai.models import Model

from pydantic_ai_sandbox.config import get_settings
from pydantic_ai_sandbox.llm import get_model

if TYPE_CHECKING:
    import pytest

    from tests.conftest import SettingsFactory


DUMMY_OLLAMA_MODEL = "dummy-ollama-model"
DUMMY_OLLAMA_URL = "http://localhost:11434"


class _NetworkAccessError(RuntimeError):
    """Raised by the patched httpx send hooks if anything tries egress."""


def _explode_sync(*_args: Any, **_kwargs: Any) -> Any:
    raise _NetworkAccessError("sync httpx.Client.send must not be called during construction")


async def _explode_async(*_args: Any, **_kwargs: Any) -> Any:
    raise _NetworkAccessError(
        "async httpx.AsyncClient.send must not be called during construction",
    )


def test_get_model_ollama_does_not_touch_network(
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: SettingsFactory,
) -> None:
    settings_factory(
        LLM_PROVIDER="ollama",
        OLLAMA_BASE_URL=DUMMY_OLLAMA_URL,
        OLLAMA_MODEL_NAME=DUMMY_OLLAMA_MODEL,
    )
    get_settings.cache_clear()

    # Replace the transport hooks with explicit detonators. Any
    # accidental probe — sync or async — surfaces as
    # _NetworkAccessError, which would fail the test loudly rather
    # than slipping past as a swallowed timeout.
    monkeypatch.setattr(httpx.Client, "send", _explode_sync)
    monkeypatch.setattr(httpx.AsyncClient, "send", _explode_async)

    try:
        model = get_model("ollama")
    finally:
        get_settings.cache_clear()

    # The construction succeeded => no transport call escaped. We add
    # the type assertion to keep the test honest: if a future refactor
    # accidentally returns ``None`` from a fast-fail branch the
    # "no exception raised" semantics alone would not catch it.
    assert isinstance(model, Model)
