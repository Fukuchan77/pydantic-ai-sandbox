"""Environment-driven configuration for the HITL support agent (Task 4.2).

Follows the same fail-fast ``pydantic_settings.BaseSettings`` pattern as the
root app's ``pydantic_ai_sandbox.config.Settings``: env vars are validated
once at construction time rather than threaded through call sites as bare
strings (Req 12.1 -- no model id is ever hardcoded in source).
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class HitlSettings(BaseSettings):
    """Runtime policy knobs for the HITL lane, loaded from the environment.

    Attributes:
        risk_threshold_usd: Amount above which ``apply_discount`` requires
            human approval (Req 5.4) and above which the output validator
            rejects an unapproved action plan (Req 3.5).
        model_name: Live model identifier for the gated Ollama integration
            lane (Task 8) only; unit tests never read this (Req 12.1).
    """

    model_config = SettingsConfigDict(env_prefix="HITL_")

    risk_threshold_usd: float = 50.0
    model_name: str | None = None
