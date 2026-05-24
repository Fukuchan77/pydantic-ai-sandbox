"""Shared pytest fixtures for the 001-agentic-platform suite.

Hosts cross-cutting test infrastructure declared by tasks.md T3.1:

* ``settings_factory`` — build a :class:`Settings` singleton from explicit
  environment-variable overrides while isolating each test from ambient
  shell state. The factory deletes the canonical env-var set first so a
  developer's local ``.env`` cannot leak into test outcomes.
* ``app_with_overrides`` — skeleton hook reserved for T8.2 / T9.1 / T9.2
  where ``create_app()`` and ``agent.override(model=TestModel())`` will be
  composed. Kept inert in the MVP bootstrap so importing ``conftest`` from
  early TDD phases does not accidentally exercise unimplemented surfaces.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

import pytest

from pydantic_ai_sandbox.config import Settings

if TYPE_CHECKING:
    from collections.abc import Iterator


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
def app_with_overrides() -> Iterator[None]:
    """Reserved fixture name for T8.2 / T9.1 / T9.2.

    The concrete body — building a FastAPI ``TestClient`` with
    ``agent.override(model=TestModel())`` applied — lands once
    ``create_app`` and ``build_chat_agent`` exist. Until then the fixture
    is a guarded skip so any premature consumer fails loudly with a
    pointer to the implementing task instead of importing a half-shaped
    object.
    """
    pytest.skip("app_with_overrides skeleton: concrete body lands in T8.2 / T9.1 / T9.2")
    yield None  # pragma: no cover  -- unreachable; satisfies the generator contract.
