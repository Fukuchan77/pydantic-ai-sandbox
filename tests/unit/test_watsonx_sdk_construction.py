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
from pydantic_ai.models import Model

from pydantic_ai_sandbox.config import Settings
from pydantic_ai_sandbox.llm.providers.watsonx import WatsonxSDKModel
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
