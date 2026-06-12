"""Shared pytest fixtures for the 001-agentic-platform suite.

Hosts cross-cutting test infrastructure declared by tasks.md T3.1:

* ``settings_factory`` — build a :class:`Settings` singleton from explicit
  environment-variable overrides while isolating each test from ambient
  shell state. The factory deletes the canonical env-var set first so a
  developer's local ``.env`` cannot leak into test outcomes.
* ``app_with_overrides`` — builder fixture that yields a callable
  ``(model) -> TestClient``. T3.1 stubbed the fixture as a ``pytest.skip``
  with the explicit note "中身は task 8/9 で拡張するため最小実装に留める";
  T9.1 / T9.2 land the real body here so the chat endpoint can be tested
  end-to-end against a ``TestModel`` / ``FunctionModel`` overlay without
  hitting any real provider.

The ``app_with_overrides`` builder composes three primitives:

1. ``settings_factory(LLM_PROVIDER='ollama', OLLAMA_MODEL_NAME='dummy-...')``
   — seats env so :class:`Settings` validation passes. The actual model
   is replaced via FastAPI's dependency-override mechanism, so no Ollama
   HTTP traffic is generated.
2. ``get_settings.cache_clear()`` + ``get_chat_agent.cache_clear()`` — both
   are :func:`functools.lru_cache` singletons; clearing them makes the
   per-test agent observable to the route handler. Without this, a stale
   agent from a prior test would survive in cache and bypass the override
   path below.
3. ``app.dependency_overrides[get_chat_agent] = lambda: build_chat_agent(
   model=model)`` — FastAPI-native dep override. Each call to the builder
   rebuilds a fresh agent via :func:`build_chat_agent` with the test
   ``model`` injected explicitly. Going through ``build_chat_agent``
   (rather than ``Agent.override`` on a cached singleton) is **load-
   bearing**: ``build_chat_agent``'s production path wraps
   ``output_type`` in :class:`pydantic_ai.NativeOutput` whenever the
   resolved model's profile reports ``supports_json_schema_output: True``
   (i.e. the real :class:`pydantic_ai.models.ollama.OllamaModel`). The
   :class:`pydantic_ai.models.test.TestModel` /
   :class:`pydantic_ai.models.function.FunctionModel` profiles report
   ``False`` for the same flag, so passing them via the explicit-model
   branch deliberately routes the factory to keep plain
   :class:`ChatResponse` and avoid ``UserError`` ("Native structured
   output is not supported by this model.") at run time. ``Agent.override``
   would have kept the production-built NativeOutput agent and only
   swapped the model — that combination is exactly the run-time error
   condition the new branch is designed to skip.

The TestClient is built with ``raise_server_exceptions=False`` so the 5xx
path (Req 3.4) is observable as a status code rather than a re-raised
exception. This matches the spec text in T9.2 ("``POST /chat`` が 5xx を
返し partial データが client に届かないこと") which fundamentally requires
the response object to exist for assertion.

Chat-router registration was previously duplicated here while T8.2's
skeleton ``create_app`` only included the health router. T10.2 folded
``app.include_router(chat_router)`` into ``create_app`` proper, so this
fixture relies on ``create_app()`` to wire the chat route — the explicit
include here was removed in the same change set per the T10.2 task
notes. The fixture deliberately uses ``TestClient`` *without* ``with`` so
the new lifespan (eager fallback dry-run) is bypassed; chat tests stay
focused on the request layer rather than re-testing T10.1's contract.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

import pytest
from fastapi.testclient import TestClient

from pydantic_ai_sandbox.agents.chat_agent import build_chat_agent
from pydantic_ai_sandbox.api.deps import get_chat_agent
from pydantic_ai_sandbox.config import Settings, get_settings
from pydantic_ai_sandbox.main import create_app

if TYPE_CHECKING:
    from pydantic_ai.models import Model


# Canonical env-var contract mirrored from .env.example (T1.3). The factory
# clears every key here before applying caller-supplied overrides so the
# resulting Settings instance is a deterministic function of the overrides
# dict alone, regardless of the developer's shell environment.
_MANAGED_ENV_KEYS: tuple[str, ...] = (
    "APP_ENV",
    "LOG_LEVEL",
    "LLM_PROVIDER",
    "OLLAMA_BASE_URL",
    "OLLAMA_MODEL_NAME",
    "OLLAMA_API_KEY",
    "WATSONX_URL",
    "WATSONX_APIKEY",
    "WATSONX_PROJECT_ID",
    "WATSONX_MODEL_ID",
    "WATSONX_TRANSPORT",
    "WATSONX_TIMEOUT_CONNECT",
    "WATSONX_TIMEOUT_READ",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_MODEL",
    "BEDROCK_REGION",
    "BEDROCK_MODEL_ID",
    "BEDROCK_INFERENCE_PROFILE_ID",
    "FALLBACK_ORDER",
    "LOGFIRE_TOKEN",
    "LOG_SENSITIVE_PAYLOADS",
    "RUN_INTEGRATION_OLLAMA",
)


# Canonical valid watsonx credential set for the unit suite (Task 3.1). Kept
# outside FORBIDDEN_MODEL_ID_LITERALS so consuming tests never regress the
# hardcoded-model-ID guard (mirrors the local constants in test_config.py).
# Exposed as module constants so consumers (Tasks 7.1-7.8) can assert a built
# Model's ``model_name`` / URL against the same source of truth the fixture
# seats, rather than re-typing literals.
WATSONX_TEST_URL = "https://us-south.ml.cloud.ibm.com"
WATSONX_TEST_MODEL_ID = "dummy-watsonx-model"
WATSONX_TEST_APIKEY = "k-watsonx-test-secret"
WATSONX_TEST_PROJECT_ID = "proj-0000"


class SettingsFactory(Protocol):
    """Callable returned by the ``settings_factory`` fixture.

    Accepts uppercase env-var names as keyword arguments and returns a
    freshly-built :class:`Settings`. Passing ``None`` for a key leaves it
    unset (after the initial clear), letting callers express "explicitly
    absent" without tripping ``monkeypatch.delenv`` on a missing key.
    """

    def __call__(self, **overrides: str | None) -> Settings: ...  # pragma: no cover


class WatsonxSettingsFactory(Protocol):
    """Callable returned by the ``watsonx_settings_factory`` fixture.

    Like :class:`SettingsFactory`, but seats a complete, valid watsonx
    credential set (``LLM_PROVIDER=watsonx`` + the four required ``WATSONX_*``
    vars) before applying caller overrides. Pass ``None`` for any seated key to
    express "explicitly absent" — useful for exercising the fail-fast
    credential gate (Task 7.8).
    """

    def __call__(self, **overrides: str | None) -> Settings: ...  # pragma: no cover


class AppWithOverrides(Protocol):
    """Callable returned by the ``app_with_overrides`` fixture.

    Accepts a Pydantic AI :class:`~pydantic_ai.models.Model` instance and
    returns a :class:`fastapi.testclient.TestClient` bound to a fresh
    FastAPI app. The agent's model is overridden to the supplied instance
    for the lifetime of the calling test (the fixture's ExitStack handles
    cleanup on teardown), so route handlers see the overridden model
    transparently via ``Depends(get_chat_agent)``.
    """

    def __call__(self, model: Model) -> TestClient: ...  # pragma: no cover


@pytest.fixture
def settings_factory(monkeypatch: pytest.MonkeyPatch) -> SettingsFactory:
    """Yield a builder that constructs Settings from explicit env overrides.

    The factory:

    1. Deletes every env key in ``_MANAGED_ENV_KEYS`` so ambient shell or
       ``.env`` values cannot influence the test.
    2. Sets each non-``None`` override via ``monkeypatch.setenv`` (string
       values only — pydantic-settings parses them).
    3. Constructs ``Settings()`` and returns the result. Validation errors
       propagate so tests can ``pytest.raises`` on them directly.
    """

    def _build(**overrides: str | None) -> Settings:
        for key in _MANAGED_ENV_KEYS:
            monkeypatch.delenv(key, raising=False)
        for key, value in overrides.items():
            if value is None:
                continue
            monkeypatch.setenv(key, value)
        return Settings()

    return _build


@pytest.fixture
def watsonx_settings_factory(
    settings_factory: SettingsFactory,
) -> WatsonxSettingsFactory:
    """Yield a builder that seats valid watsonx creds, then applies overrides.

    The builder layers caller overrides on top of a complete, valid watsonx
    credential set (``LLM_PROVIDER=watsonx`` + ``WATSONX_APIKEY`` /
    ``WATSONX_PROJECT_ID`` / ``WATSONX_URL`` / ``WATSONX_MODEL_ID``) and
    delegates to :func:`settings_factory`, inheriting its ambient-shell
    isolation (``_MANAGED_ENV_KEYS`` is cleared first).

    Override semantics match ``settings_factory``: a key set to ``None`` is
    left unset, so ``watsonx_settings_factory(WATSONX_APIKEY=None)`` drives the
    fail-fast credential gate. Any non-seated key (e.g. ``WATSONX_TRANSPORT``,
    ``WATSONX_TIMEOUT_CONNECT``) is simply forwarded.
    """

    def _build(**overrides: str | None) -> Settings:
        seated: dict[str, str | None] = {
            "LLM_PROVIDER": "watsonx",
            "WATSONX_APIKEY": WATSONX_TEST_APIKEY,
            "WATSONX_PROJECT_ID": WATSONX_TEST_PROJECT_ID,
            "WATSONX_URL": WATSONX_TEST_URL,
            "WATSONX_MODEL_ID": WATSONX_TEST_MODEL_ID,
        }
        # Caller overrides win (including an explicit ``None`` to drop a cred).
        seated.update(overrides)
        return settings_factory(**seated)

    return _build


@pytest.fixture
def app_with_overrides(
    settings_factory: SettingsFactory,
) -> AppWithOverrides:
    """Yield a builder that wires the chat route to a per-test agent.

    The builder seats minimal Ollama-only env (so :class:`Settings`
    validates), clears the ``get_settings`` and ``get_chat_agent``
    caches, builds a fresh agent via :func:`build_chat_agent` with the
    caller-supplied ``model``, and registers an FastAPI
    ``app.dependency_overrides`` entry so the route handler resolves
    ``Depends(get_chat_agent)`` to the test agent instead of the
    cached production singleton.

    Why ``build_chat_agent(model=...)`` rather than the previous
    ``agent.override(model=...)``: the production path of
    :func:`build_chat_agent` wraps :class:`ChatResponse` in
    :class:`pydantic_ai.NativeOutput` whenever the resolved model's
    profile reports ``supports_json_schema_output: True`` (the real
    :class:`pydantic_ai.models.ollama.OllamaModel`). The test models
    (:class:`pydantic_ai.models.test.TestModel`,
    :class:`pydantic_ai.models.function.FunctionModel`) report ``False``
    for that flag and would raise ``UserError`` at run time if reached
    through a ``NativeOutput``-wrapped agent. Rebuilding via
    :func:`build_chat_agent` with the explicit model arg deliberately
    routes through the factory's "plain ``ChatResponse``" branch so
    each test sees a wiring that matches its model's profile.

    Calling the builder more than once in a single test rebuilds the
    app and replaces the dependency override (last call wins); fixture
    teardown is implicit because ``app.dependency_overrides`` lives on
    the per-test app instance and is garbage-collected with it.
    """

    def _build(model: Model) -> TestClient:
        settings_factory(
            LLM_PROVIDER="ollama",
            OLLAMA_MODEL_NAME="dummy-ollama-model",
        )
        # Both caches must be cleared: get_settings so the route's
        # Depends chain reads the per-test env, get_chat_agent so the
        # singleton does not retain a NativeOutput-wrapped agent from a
        # prior test (which would otherwise leak through to later runs
        # that hit the real dep before the override below registers).
        get_settings.cache_clear()
        get_chat_agent.cache_clear()

        # Fresh per-test agent built directly via the factory's
        # explicit-model branch — this is the branch that keeps plain
        # ``ChatResponse`` output_type and stays compatible with
        # ``TestModel`` / ``FunctionModel`` profiles.
        test_agent = build_chat_agent(model=model)

        # T10.2 folded ``include_router(chat_router)`` into create_app().
        # The chat route is wired automatically; the fixture stays focused
        # on env seating, cache clearing, and dep-override registration.
        app = create_app()
        app.dependency_overrides[get_chat_agent] = lambda: test_agent
        # raise_server_exceptions=False keeps the 5xx path (Req 3.4)
        # observable as a response status code rather than a re-raised
        # UnexpectedModelBehavior. The 422 path is unaffected — those
        # are client errors and never re-raised regardless of this flag.
        return TestClient(app, raise_server_exceptions=False)

    return _build
