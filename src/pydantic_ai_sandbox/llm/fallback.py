"""``FallbackModel`` builder (plan.md §2.4).

Parses ``Settings.fallback_order`` and composes a Pydantic AI
``FallbackModel`` whose members are constructed by recursively calling
:func:`pydantic_ai_sandbox.llm.factory.get_model`. The function carries
two startup-time guards beyond what ``Settings`` already enforces:

1. **All-stub guard (Req 4.5 構成段)**: when every member sits in
   :data:`pydantic_ai_sandbox.llm.factory._MVP_STUB_PROVIDERS`, raise
   :class:`RuntimeError` so a misconfigured deployment fails at app
   startup rather than at the first ``/chat`` call. plan.md §2.4 names
   this the "all-stub" condition; the lifespan dry-run in T10 calls
   ``_build_fallback`` eagerly to surface it before request traffic.
2. **Stub member skipping (mixed configurations)**: when at least one
   member is real, stub members are filtered out before recursion so
   their ``NotImplementedError`` cannot poison the chain. The user's
   relative ordering of *real* providers is preserved. This lets a team
   stage a 002-multi-provider rollout (e.g. ``FALLBACK_ORDER=
   ollama,watsonx``) without forcing the stub branch to land first.

Construction is pure: no HTTP I/O leaves this function. The recursive
``get_model("ollama")`` call hits :func:`_build_ollama` which is itself
network-free (T4.2 lock).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic_ai.models.fallback import FallbackModel

# Spec-mandated underscore-prefixed name (plan.md §2.4) re-exported via
# ``llm.factory.__all__``; the ignore comment matches the convention
# established by ``llm.factory`` itself.
from pydantic_ai_sandbox.llm.factory import (
    _MVP_STUB_PROVIDERS,  # pyright: ignore[reportPrivateUsage]
    get_model,
)

if TYPE_CHECKING:
    from pydantic_ai.models import Model

    from pydantic_ai_sandbox.config import Settings

__all__ = ["_build_fallback"]


def _build_fallback(settings: Settings) -> Model:
    """Compose a ``FallbackModel`` from ``settings.fallback_order``.

    Args:
        settings: Frozen runtime settings. ``fallback_order`` is the
            comma-separated provider chain; the
            :class:`Settings._check_provider_constraints` validator has
            already rejected empty strings and wholly-unknown member
            lists, so we can assume at least one syntactically valid
            member appears here.

    Returns:
        A ``FallbackModel`` whose ``models`` tuple contains the real
        providers (in the user's specified order) constructed via
        recursive :func:`get_model` calls. Stub providers
        (``watsonx`` / ``anthropic`` / ``bedrock`` in the MVP) are
        filtered out before recursion.

    Raises:
        RuntimeError: When every member of ``fallback_order`` is in
            :data:`_MVP_STUB_PROVIDERS`. This is the "all-stub"
            startup-time guard (Req 4.5 構成段) — without it, the chain
            would silently surface ``NotImplementedError`` at the first
            ``/chat`` call instead of failing fast at startup.
    """
    members = [m.strip() for m in settings.fallback_order.split(",") if m.strip()]
    # Settings already rejects the empty/all-unknown cases; this guard is
    # redundant on the production path but defends against a future
    # refactor that loosens the validator without updating this function.
    # ``raise`` (not ``assert``) is load-bearing — Python's ``-O`` flag
    # strips assertions, which would silently route an empty list to the
    # ``default, *rest = real_models`` unpacking below and surface a
    # confusing ``ValueError`` instead of an explicit boundary error.
    if not members:
        msg = (
            "FALLBACK_ORDER parsed to an empty member list — the Settings "
            "cross-field validator should have rejected this configuration. "
            "If this fires in production, the validator was weakened in a "
            "refactor; restore the empty-string check in "
            "Settings._check_provider_constraints."
        )
        raise RuntimeError(msg)

    if all(member in _MVP_STUB_PROVIDERS for member in members):
        msg = (
            "FALLBACK_ORDER members are all unimplemented stubs in MVP "
            f"({sorted(_MVP_STUB_PROVIDERS)}); configure at least one real "
            "provider (currently only 'ollama' ships an implementation) "
            "or wait for the 002-multi-provider follow-up spec."
        )
        raise RuntimeError(msg)

    # Mixed case: drop stub members before recursing so we do not trip
    # their NotImplementedError. Real-provider ordering is preserved.
    real_models: list[Model] = [
        get_model(member) for member in members if member not in _MVP_STUB_PROVIDERS
    ]

    # ``FallbackModel`` requires at least the default model positionally;
    # the all-stub guard above ensures ``real_models`` has length ≥ 1.
    default, *rest = real_models
    return FallbackModel(default, *rest)
