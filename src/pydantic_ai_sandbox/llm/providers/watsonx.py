"""watsonx.ai provider builder — MVP stub (plan.md §2.4 / Req 2.4).

Real construction lands in spec ``002-multi-provider``; the file exists
in MVP so the dispatch table in :mod:`pydantic_ai_sandbox.llm.factory`
has a stable, type-checked import target and the contract test
``tests/unit/test_factory_dispatch.py`` can pin the
``NotImplementedError`` wording without later imports churning.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Never

if TYPE_CHECKING:
    from pydantic_ai_sandbox.config import Settings

# Spec-mandated underscore-prefixed name (plan.md §2.4); exported via
# ``__all__`` so pyright treats it as the module's public surface.
__all__ = ["_build_watsonx"]


def _build_watsonx(settings: Settings) -> Never:
    """Reject construction with a follow-up-spec hint.

    The signature mirrors :func:`_build_ollama` so the factory can call
    every builder uniformly. ``settings`` is intentionally unused in the
    stub; we ``del`` it to make that intent explicit and to satisfy
    static analyzers without tagging the parameter with an underscore
    prefix (which would change the public-looking call site).

    Args:
        settings: Unused in MVP; retained for signature parity.

    Raises:
        NotImplementedError: Always. Message names the provider and the
            follow-up spec ID so an operator hitting this in production
            knows exactly where the work is tracked.
    """
    del settings
    msg = "Provider 'watsonx' is not implemented in MVP; tracked in 002-multi-provider"
    raise NotImplementedError(msg)
