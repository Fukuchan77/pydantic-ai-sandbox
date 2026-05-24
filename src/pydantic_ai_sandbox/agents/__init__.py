"""Agent factory namespace.

Re-exports :func:`build_chat_agent` so consumers (the ``/chat`` route
in T9.3 and the integration test in T11.1) can write
``from pydantic_ai_sandbox.agents import build_chat_agent``. plan.md
§4.1 marks this package as "namespace のみ"; keep it import-only.
"""

from __future__ import annotations

from pydantic_ai_sandbox.agents.chat_agent import build_chat_agent

__all__ = ["build_chat_agent"]
