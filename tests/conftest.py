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
   — seats env so :class:`Settings` validation passes. The actual model is
   replaced via override, so no Ollama HTTP traffic is generated.
2. ``get_settings.cache_clear()`` + ``get_chat_agent.cache_clear()`` — both
   are :func:`functools.lru_cache` singletons; clearing them makes the
   freshly-overridden agent observable to the route handler. Without
   this, a stale agent from a prior test would survive in cache and
   ignore the fixture's override.
3. ``ExitStack.enter_context(agent.override(model=...))`` — the override is
   tracked by a per-test :class:`contextlib.ExitStack` so fixture teardown
   exits all entered overrides in LIFO order. Calling the builder twice
   inside the same test stacks overrides (last call wins), which is the
   intuitive semantics for a "swap the model again" scenario.

The TestClient is built with ``raise_server_exceptions=False`` so the 5xx
path (Req 3.4) is observable as a status code rather than a re-raised
exception. This matches the spec text in T9.2 ("``POST /chat`` が 5xx を
返し partial データが client に届かないこと") which fundamentally requires
the response object to exist for assertion.

The chat router is included on the app explicitly here. T8.2's
``create_app`` skeleton registers only the health router by design; T10.2
will move the chat-router registration into ``create_app`` itself, at
which point the explicit ``app.include_router(chat_router)`` line in this
fixture becomes redundant and SHOULD be removed in the same change set.
Until T10.2 lands, this fixture is the only path that wires the chat
route into a FastAPI app.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Protocol

import pytest
from fastapi.testclient import TestClient

from pydantic_ai_sandbox.api.deps import get_chat_agent
from pydantic_ai_sandbox.api.routes.chat import router as chat_router
from pydantic_ai_sandbox.config import Settings, get_settings
from pydantic_ai_sandbox.main import create_app

if TYPE_CHECKING:
    from collections.abc import Iterator

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


class SettingsFactory(Protocol):
    """Callable returned by the ``settings_factory`` fixture.

    Accepts uppercase env-var names as keyword arguments and returns a
    freshly-built :class:`Settings`. Passing ``None`` for a key leaves it
    unset (after the initial clear), letting callers express "explicitly
    absent" without tripping ``monkeypatch.delenv`` on a missing key.
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
def app_with_overrides(
    settings_factory: SettingsFactory,
) -> Iterator[AppWithOverrides]:
    """Yield a builder that wires the chat route to an overridden agent.

    The builder seats minimal Ollama-only env (so :class:`Settings`
    validates), clears the ``get_settings`` and ``get_chat_agent`` caches,
    enters ``agent.override(model=model)`` on the cached chat-agent
    singleton, and returns a TestClient over a fresh FastAPI app with the
    chat router included.

    Calling the builder more than once in a single test stacks overrides
    on the same agent singleton (the ExitStack tracks each entry); the
    final teardown exits all of them in LIFO order. Each call also
    rebuilds the FastAPI app, which is intentional — different tests may
    want different ``raise_server_exceptions`` semantics in the future,
    and rebuilding keeps that future change cheap.
    """
    stack = contextlib.ExitStack()

    def _build(model: Model) -> TestClient:
        settings_factory(
            LLM_PROVIDER="ollama",
            OLLAMA_MODEL_NAME="dummy-ollama-model",
        )
        # Both caches must be cleared: get_settings so the route's
        # Depends chain reads the per-test env, get_chat_agent so the
        # singleton is rebuilt on top of the new Settings before we
        # enter the override below.
        get_settings.cache_clear()
        get_chat_agent.cache_clear()

        agent = get_chat_agent()
        stack.enter_context(agent.override(model=model))

        app = create_app()
        # T10.2 will fold this registration into create_app() proper.
        # Until then, the fixture is the only place that wires the chat
        # route into an app for testing — keeping it local here means
        # T9.3's boundary (deps.py + chat.py only) stays clean.
        app.include_router(chat_router)
        # raise_server_exceptions=False keeps the 5xx path (Req 3.4)
        # observable as a response status code rather than a re-raised
        # UnexpectedModelBehavior. The 422 path is unaffected — those
        # are client errors and never re-raised regardless of this flag.
        return TestClient(app, raise_server_exceptions=False)

    try:
        yield _build
    finally:
        stack.close()
