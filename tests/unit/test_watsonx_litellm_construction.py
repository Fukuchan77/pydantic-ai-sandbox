"""Hermetic construction tests for the watsonx LiteLLM transport (Task 4 / C3).

Task 4 rewrites the ``WATSONX_TRANSPORT=litellm`` branch of
:func:`pydantic_ai_sandbox.llm.providers.watsonx._build_litellm` to construct the
provider-agnostic :class:`~pydantic_ai_sandbox.llm.providers.litellm.LiteLLMModel`,
replacing the former ``OpenAIChatModel`` / ``LiteLLMProvider`` construction. That
old path POSTed to ``/chat/completions`` — an endpoint watsonx.ai does not expose
(the 002 live-verified 404) — so this file is retargeted from the removed adapter
to the builder's new construction contract:

* **4.1** — the ``watsonx/<model_id>`` route prefix LiteLLM uses to select the
  watsonx backend, the unwrapped ``SecretStr`` apikey, ``watsonx_url`` routed as
  ``api_base``, and connect/read timeout passthrough.
* **4.2** — the optional-dependency import guard: a missing ``litellm`` package
  fails loud as a :class:`ValueError` naming the package + install command
  (Req 6.1), never a bare ``ImportError`` leaking from deep in the builder.
* **4.3** — ``WATSONX_PROJECT_ID`` reconciled into ``os.environ`` for LiteLLM's
  watsonx path (research.md ADR-3: LiteLLM reads the project id from the process
  environment directly), sourced from the validated ``settings.watsonx_project_id``.

Hermetic by construction: the builder is I/O-free (Req 1.5), so these tests issue
zero network egress. The litellm *request* path (message/tool/response mapping,
error wrapping, timeout shaping on the wire) is covered by the mocked-
``acompletion`` ``test_litellm_*`` suite, not here — this file owns construction
only (Task 5.1 boundary).
"""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING, Any

import httpx
import pytest

from pydantic_ai_sandbox.config import Settings
from pydantic_ai_sandbox.llm.providers.litellm import LiteLLMModel
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


def test_litellm_transport_builds_litellm_model(
    watsonx_settings_factory: WatsonxSettingsFactory,
) -> None:
    """``transport="litellm"`` builds a :class:`LiteLLMModel` (Req 7.1).

    The rewrite returns the provider-agnostic ``LiteLLMModel`` (which routes via
    ``litellm.acompletion``) rather than the removed ``OpenAIChatModel`` /
    ``LiteLLMProvider`` adapter that targeted an endpoint watsonx.ai does not
    expose.
    """
    model = _build_watsonx(watsonx_settings_factory(WATSONX_TRANSPORT="litellm"))

    assert isinstance(model, LiteLLMModel)


def test_litellm_model_name_carries_watsonx_route_prefix(
    watsonx_settings_factory: WatsonxSettingsFactory,
) -> None:
    """The route is ``watsonx/<model_id>`` so litellm selects the watsonx backend (Req 7.1).

    LiteLLM picks the watsonx backend from the ``watsonx/`` prefix; the id itself
    comes from ``Settings`` (``WATSONX_MODEL_ID``), never a literal in ``src/``.
    """
    model = _build_watsonx(watsonx_settings_factory(WATSONX_TRANSPORT="litellm"))

    assert model.model_name == f"watsonx/{WATSONX_TEST_MODEL_ID}"


def test_litellm_api_key_unwrapped_and_routed(
    watsonx_settings_factory: WatsonxSettingsFactory,
) -> None:
    """The ``SecretStr`` apikey is unwrapped at this boundary and handed to the model (Req 7.3).

    Unwrapping happens *only* in ``_build_litellm`` (``.get_secret_value()``); the
    model receives a plain value. Asserting the stored value equals the test
    apikey proves the boundary unwrap occurred.
    """
    model = _build_watsonx(watsonx_settings_factory(WATSONX_TRANSPORT="litellm"))

    assert isinstance(model, LiteLLMModel)
    assert model._api_key == WATSONX_TEST_APIKEY  # pyright: ignore[reportPrivateUsage]


def test_litellm_url_routed_as_api_base(
    watsonx_settings_factory: WatsonxSettingsFactory,
) -> None:
    """``watsonx_url`` reaches the model as ``api_base`` (Req 7.1)."""
    model = _build_watsonx(watsonx_settings_factory(WATSONX_TRANSPORT="litellm"))

    assert isinstance(model, LiteLLMModel)
    assert model._api_base == WATSONX_TEST_URL  # pyright: ignore[reportPrivateUsage]


def test_litellm_timeouts_passed_through_defaults(
    watsonx_settings_factory: WatsonxSettingsFactory,
) -> None:
    """Default connect/read timeouts (30/120) reach the model (Req 5.2).

    The model shapes these into ``httpx.Timeout(read, connect=connect)`` per
    request (pinned by ``test_litellm_timeout_config.py``); the builder's job is to
    pass both phases through unaltered.
    """
    model = _build_watsonx(watsonx_settings_factory(WATSONX_TRANSPORT="litellm"))

    assert isinstance(model, LiteLLMModel)
    assert model._timeout_connect == 30  # pyright: ignore[reportPrivateUsage]
    assert model._timeout_read == 120  # pyright: ignore[reportPrivateUsage]


def test_litellm_timeouts_honour_env_overrides(
    watsonx_settings_factory: WatsonxSettingsFactory,
) -> None:
    """Non-default ``WATSONX_TIMEOUT_*`` values reach the model (Req 5.2)."""
    model = _build_watsonx(
        watsonx_settings_factory(
            WATSONX_TRANSPORT="litellm",
            WATSONX_TIMEOUT_CONNECT="5",
            WATSONX_TIMEOUT_READ="45",
        ),
    )

    assert isinstance(model, LiteLLMModel)
    assert model._timeout_connect == 5  # pyright: ignore[reportPrivateUsage]
    assert model._timeout_read == 45  # pyright: ignore[reportPrivateUsage]


def test_litellm_project_id_reconciled_into_environ(
    monkeypatch: pytest.MonkeyPatch,
    watsonx_settings_factory: WatsonxSettingsFactory,
) -> None:
    """``WATSONX_PROJECT_ID`` is reconciled into ``os.environ`` by the builder (Req 7.2 / ADR-3).

    LiteLLM's watsonx provider reads the project id from ``os.environ`` directly
    (research.md ADR-3), not from an ``acompletion`` kwarg. A deployment loading
    ``Settings`` from a ``.env`` file would leave it unset in ``os.environ`` even
    though ``settings.watsonx_project_id`` is populated — so the builder writes it.

    The settings are captured first (the factory seats the env var so validation
    passes), then the env var is *deleted* so the assertion proves the **builder**
    — not the fixture — re-populates it from the validated setting. ``monkeypatch``
    restores the var on teardown (it owns the key from the factory's ``setenv``),
    so the process-global write does not leak across tests.
    """
    settings = watsonx_settings_factory(WATSONX_TRANSPORT="litellm")
    monkeypatch.delenv("WATSONX_PROJECT_ID", raising=False)

    _build_litellm(settings)  # pyright: ignore[reportPrivateUsage]

    assert os.environ["WATSONX_PROJECT_ID"] == WATSONX_TEST_PROJECT_ID


def test_litellm_import_guard_raises_valueerror_naming_package(
    monkeypatch: pytest.MonkeyPatch,
    watsonx_settings_factory: WatsonxSettingsFactory,
) -> None:
    """A missing ``litellm`` package fails loud as ``ValueError`` naming it (Req 6.1).

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


def test_litellm_secret_apikey_never_leaks_in_repr(
    watsonx_settings_factory: WatsonxSettingsFactory,
) -> None:
    """The unwrapped apikey never appears in the model's ``repr``/``str`` (Req 7.5).

    The secret is unwrapped at the builder boundary and stored on the model, but
    it must never surface in a debug representation that could reach logs. The
    gitleaks lane (Task 7.3) covers log scanning at the suite level; this pins the
    object-level guard.
    """
    model = _build_watsonx(watsonx_settings_factory(WATSONX_TRANSPORT="litellm"))

    assert WATSONX_TEST_APIKEY not in repr(model)
    assert WATSONX_TEST_APIKEY not in str(model)


def test_litellm_construction_is_io_free(
    monkeypatch: pytest.MonkeyPatch,
    watsonx_settings_factory: WatsonxSettingsFactory,
) -> None:
    """Building the litellm Model performs no network I/O (Req 1.5).

    Detonating both ``httpx`` transport send hooks proves construction issues no
    egress: the first network call is the first :meth:`LiteLLMModel.request`.
    """
    monkeypatch.setattr(httpx.Client, "send", _explode_sync)
    monkeypatch.setattr(httpx.AsyncClient, "send", _explode_async)

    model = _build_watsonx(watsonx_settings_factory(WATSONX_TRANSPORT="litellm"))

    assert isinstance(model, LiteLLMModel)


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
