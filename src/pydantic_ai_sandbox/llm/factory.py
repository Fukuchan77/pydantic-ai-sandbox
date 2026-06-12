"""``ModelFactory`` dispatch (plan.md §2.2).

Single window from ``LLM_PROVIDER`` (or an explicit override) to a
``pydantic_ai.models.Model`` instance. The mapping is hard-coded against
the :data:`pydantic_ai_sandbox.config.LLMProvider` Literal alphabet and
guarded by ``tests/unit/test_factory_dispatch.py`` so silent drift between
``Settings`` and the dispatch table fires the suite.

Boundary rules (plan.md §2.2 境界規則):

* ``get_model`` itself does **no** network I/O. The Ollama branch
  delegates to :func:`_build_ollama`, which constructs the OpenAI
  client lazily; the first HTTP call is the eventual ``agent.run(...)``
  invocation. Locked by ``tests/unit/test_factory_ollama_no_io.py``.
* The ``"fallback"`` branch delegates to
  :func:`pydantic_ai_sandbox.llm.fallback._build_fallback` (T5.4). That
  module imports ``_MVP_STUB_PROVIDERS`` and ``get_model`` from here,
  so the dispatch import is performed lazily inside the branch to keep
  the otherwise-circular module graph initialisable.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

# The provider-specific builders below are spec-mandated underscore-prefixed
# names (plan.md §2.3 / §2.4) signalling "package-internal helpers, callable
# only via :func:`get_model`". Each provider module exports the helper through
# ``__all__``; the leading underscore is communicating intent to humans rather
# than module-private semantics, and the pyright suppressions on each line
# acknowledge the cross-module hop without weakening the strict ruleset.
from pydantic_ai_sandbox.config import get_settings
from pydantic_ai_sandbox.llm.providers.anthropic import (
    _build_anthropic,  # pyright: ignore[reportPrivateUsage]
)
from pydantic_ai_sandbox.llm.providers.bedrock import (
    _build_bedrock,  # pyright: ignore[reportPrivateUsage]
)
from pydantic_ai_sandbox.llm.providers.ollama import (
    _build_ollama,  # pyright: ignore[reportPrivateUsage]
)
from pydantic_ai_sandbox.llm.providers.watsonx import (
    _build_watsonx,  # pyright: ignore[reportPrivateUsage]
)

if TYPE_CHECKING:
    from pydantic_ai.models import Model

# Public from the package's perspective even though the leading
# underscore matches the spec wording (plan.md §2.4); listed in
# ``__all__`` so consumers (`_build_fallback` in T5.4, the dispatch
# contract test) can import it without tripping ``reportPrivateUsage``.
__all__ = ["_MVP_STUB_PROVIDERS", "get_model"]

_MVP_STUB_PROVIDERS: frozenset[str] = frozenset({"anthropic", "bedrock"})
"""Provider names whose builder is a NotImplementedError stub in MVP.

watsonx was promoted out of this set in feature ``002-watsonx-provider``
(Task 4.2): it now resolves to a real :func:`_build_watsonx` Model. Only
``anthropic`` and ``bedrock`` remain stubs.

Public so :func:`pydantic_ai_sandbox.llm.fallback._build_fallback` (T5.4)
can detect "every member of FALLBACK_ORDER is a stub" configurations and
fail-fast at startup rather than at first ``/chat`` call. Drift between
this set and the actual stub modules is caught by
``tests/unit/test_factory_dispatch.py::test_mvp_stub_providers_constant_matches_plan``.
"""


def get_model(provider: str | None = None) -> Model:
    """Return a Pydantic AI ``Model`` for the requested (or configured) provider.

    Args:
        provider: Override the provider name. When ``None`` (the
            production path) the value is read from
            :attr:`Settings.llm_provider` via :func:`get_settings`.

    Returns:
        A live ``pydantic_ai.models.Model`` instance. The instance is
        not cached here — repeated calls construct fresh objects so
        tests can rebuild the world without dancing around lru_cache
        invalidation. (``get_settings`` is the lru_cache layer; reusing
        its singleton is enough to keep agent construction cheap.)

    Raises:
        NotImplementedError: When ``provider`` resolves to a name in
            :data:`_MVP_STUB_PROVIDERS` (anthropic / bedrock). watsonx is no
            longer a stub — it routes to :func:`_build_watsonx`.
        RuntimeError: Surfaced from :func:`_build_fallback` when
            ``provider == "fallback"`` and every member of
            ``Settings.fallback_order`` is itself a stub provider
            (Req 4.5 構成段).
        ValueError: When ``provider`` is not a member of the
            :data:`pydantic_ai_sandbox.config.LLMProvider` alphabet.
    """
    settings = get_settings()
    resolved = provider if provider is not None else settings.llm_provider

    if resolved == "ollama":
        return _build_ollama(settings)
    if resolved == "watsonx":
        return _build_watsonx(settings)
    if resolved == "anthropic":
        _build_anthropic(settings)
    if resolved == "bedrock":
        _build_bedrock(settings)
    if resolved == "fallback":
        # T5.4 wiring. Imported lazily to break the circular import:
        # ``llm.fallback`` imports ``_MVP_STUB_PROVIDERS`` and
        # ``get_model`` from this module, so the top-level ``import``
        # would form a cycle. The lazy form keeps the cycle visible only
        # at call time, when both modules are fully initialised.
        from pydantic_ai_sandbox.llm.fallback import (
            _build_fallback,  # pyright: ignore[reportPrivateUsage]
        )

        return _build_fallback(settings)

    msg = f"Unknown LLM_PROVIDER: {resolved!r}"
    raise ValueError(msg)
