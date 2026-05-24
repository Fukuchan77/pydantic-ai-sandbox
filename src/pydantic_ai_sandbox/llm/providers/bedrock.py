"""AWS Bedrock provider builder — MVP stub (plan.md §2.4 / Req 2.4).

See :mod:`pydantic_ai_sandbox.llm.providers.watsonx` for the rationale of
shipping a typed stub before the real implementation lands in
``002-multi-provider``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Never

if TYPE_CHECKING:
    from pydantic_ai_sandbox.config import Settings

# Spec-mandated underscore-prefixed name (plan.md §2.4); exported via
# ``__all__`` so pyright treats it as the module's public surface.
__all__ = ["_build_bedrock"]


def _build_bedrock(settings: Settings) -> Never:
    """Reject construction with a follow-up-spec hint.

    Args:
        settings: Unused in MVP; retained for signature parity.

    Raises:
        NotImplementedError: Always. Message names the provider and the
            follow-up spec ID so the failure is self-documenting.
    """
    del settings
    msg = "Provider 'bedrock' is not implemented in MVP; tracked in 002-multi-provider"
    raise NotImplementedError(msg)
