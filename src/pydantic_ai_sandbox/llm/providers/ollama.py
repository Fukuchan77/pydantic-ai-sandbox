"""Ollama provider builder (plan.md §2.3).

Wraps Pydantic AI's ``OllamaModel`` over an ``OllamaProvider`` so the
local Ollama daemon can be addressed through the OpenAI-compatible
chat-completions surface (research.md R-1). Construction is pure: no
HTTP call leaves this function — the Ollama HTTP round-trip is deferred
until ``agent.run(...)`` so a stopped daemon cannot break process start
(Req 2.6).

``OllamaModel`` (vs the underlying ``OpenAIChatModel`` it subclasses) is
load-bearing: its profile sets ``supports_json_schema_output: True``,
which the agent factory keys off to wrap the output type in
:class:`pydantic_ai.NativeOutput`. Self-hosted Ollama v0.5.0+ honours
``response_format`` with ``json_schema`` via ``llama.cpp``'s
grammar-constrained decoder, so the JSON-schema mode produces
schema-valid output at generation time — without it, weaker local
Granite-class models under-perform at the V2 default tool-mode
structured output and the integration lane (T11.1) flakes.

The model-ID literal is **not** spelled here; it lives in
``OLLAMA_MODEL_NAME`` and reaches us through :class:`Settings`. Hardcoded
strings would be caught by both the unit guard
(``tests/unit/test_no_hardcoded_model_ids.py``) and the pre-commit
``forbid-hardcoded-model-ids`` hook.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic_ai.models.ollama import OllamaModel
from pydantic_ai.providers.ollama import OllamaProvider

if TYPE_CHECKING:
    from pydantic_ai.models import Model

    from pydantic_ai_sandbox.config import Settings

# Spec-mandated underscore-prefixed name (plan.md §2.3); exported via
# ``__all__`` so pyright treats it as the module's public surface and
# does not flag the cross-module import in ``llm.factory`` as unused.
__all__ = ["_build_ollama"]


def _build_ollama(settings: Settings) -> Model:
    """Construct an Ollama-backed ``Model`` from typed settings.

    Args:
        settings: Frozen runtime settings; ``ollama_model_name`` is
            non-optional at this point because Settings' validator
            already rejected the missing-name case (Req 1.2).

    Returns:
        A ``pydantic_ai.models.Model`` instance ready to be passed to
        :class:`pydantic_ai.Agent`.

    Raises:
        TypeError: If ``ollama_model_name`` is unexpectedly ``None`` —
            this should be unreachable because Settings enforces the
            invariant; the explicit check is defensive against future
            refactors that loosen the validator.
    """
    if settings.ollama_model_name is None:
        msg = (
            "ollama_model_name is None at _build_ollama time — "
            "Settings should have rejected this configuration; "
            "did the cross-field validator change?"
        )
        raise TypeError(msg)

    # Unwrap the ``SecretStr`` only at the SDK boundary — the wrapper
    # keeps the value redacted in repr/str everywhere else. ``None``
    # propagates unchanged so hosted-Ollama auth stays optional.
    api_key = (
        settings.ollama_api_key.get_secret_value() if settings.ollama_api_key is not None else None
    )
    provider = OllamaProvider(
        # ``HttpUrl`` carries a trailing slash; OllamaProvider expects a
        # plain string and tolerates either form, so we hand it the
        # canonical str() rendering.
        base_url=str(settings.ollama_base_url),
        api_key=api_key,
    )
    return OllamaModel(model_name=settings.ollama_model_name, provider=provider)
