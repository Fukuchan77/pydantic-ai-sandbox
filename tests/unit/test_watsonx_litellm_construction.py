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

Boundary note: this is the file Task 7.2 extends with the RESPX request-path
tests (live-shaped HTTP round-trips through the OpenAI adapter); Task 6 owns
construction and the import guard only.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Any

import httpx
import pytest
from pydantic_ai.models.openai import OpenAIChatModel

from pydantic_ai_sandbox.llm.providers.watsonx import (
    _build_watsonx,  # pyright: ignore[reportPrivateUsage]
)
from tests.conftest import (
    WATSONX_TEST_APIKEY,
    WATSONX_TEST_MODEL_ID,
    WATSONX_TEST_URL,
)

if TYPE_CHECKING:
    from tests.conftest import WatsonxSettingsFactory


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
