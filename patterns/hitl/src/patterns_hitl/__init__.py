"""Human-in-the-Loop stop/approve/resume harness lane (Spec 012-agentic-ai-design).

This package implements the pydantic-ai-v2-only deferred-tools flow
(``ApprovalRequired`` -> ``DeferredToolRequests`` -> ``ToolApproved``/
``ToolDenied`` -> resume) behind a FastAPI ``POST /run`` / ``POST /resume``
harness. The I/O contract (``ActionType`` / ``ResolutionAction`` /
``SupportOutput``) is owned by ``patterns_contracts.hitl``; this lane never
duplicates it.
"""

from __future__ import annotations
