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
import pytest
from pydantic_ai.models import Model

from pydantic_ai_sandbox.config import Settings
from pydantic_ai_sandbox.llm.providers.watsonx import WatsonxSDKModel
from tests.conftest import WATSONX_TEST_MODEL_ID

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
