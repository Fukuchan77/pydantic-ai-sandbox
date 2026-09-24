"""``POST /chat`` route (plan.md §2.7 / §3.1 / Req 3.1-3.6).

Wires the FastAPI request layer to :class:`build_chat_agent`'s output:

1. The request body is validated against :class:`ChatRequest` by FastAPI's
   default Pydantic v2 integration. Bodies that miss ``message``, supply
   the wrong type, or violate ``min_length=1`` raise the framework's
   built-in 422 path (Req 3.6) without ever reaching the handler.
2. Inside the handler, ``await agent.run(req.message, usage_limits=...)``
   invokes the Pydantic AI V2 agent in async mode, under a request timeout
   and the ``chat_usage_*`` caps from :class:`Settings` (OWASP Agentic AI
   "unbounded consumption" — a runaway tool loop or a hung provider call
   previously had no request/token cap and no timeout at all).
   ``result.output`` is the validated :class:`ChatResponse` (V1's
   ``result.data`` is intentionally unsupported — research.md R-1 records
   the migration).
3. Output validation is delegated to Pydantic AI: when the model emits a
   structurally invalid payload, the framework raises
   :class:`pydantic_ai.exceptions.UnexpectedModelBehavior` after exhausting
   its retry budget. The handler does *not* catch that exception, so it
   propagates to FastAPI's default 500 handler (Req 3.4) — the spec text
   explicitly cedes exception handling to the framework default there. A
   timeout (504) and a usage-limit overrun (429) *are* caught, since those
   are resource guardrails this route owns, not a model-output-shape
   concern research.md R-1 ceded.
4. ``result.output.sources`` is re-grounded against what ``search_kb``
   actually returned this run before the response is built — the model is
   free to invent citation ids in a structured-output field just as easily
   as in prose, and nothing upstream of this handler checks that (see
   :func:`_grounded_sources`).

Boundary rules from plan.md §2.7:

* the handler has no model-specific knowledge — provider selection lives
  in :mod:`pydantic_ai_sandbox.llm.factory`, agent shape lives in
  :mod:`pydantic_ai_sandbox.agents.chat_agent`, and this file is purely
  the HTTP-to-agent adapter;
* ``response_model=ChatResponse`` is declared on the route so the wire
  contract is enforced at serialisation time even if the agent's output
  type drifts (a defensive double-check on top of Pydantic AI's own
  ``output_type`` coercion).

T10.2 will register this router on ``create_app()`` proper; until then
the chat route is wired into a TestClient app via the
``app_with_overrides`` fixture in ``tests/conftest.py``.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException
from pydantic_ai import UsageLimitExceeded, UsageLimits
from pydantic_ai.messages import ModelRequest, ToolReturnPart

from pydantic_ai_sandbox.api.deps import get_chat_agent, get_settings_dep
from pydantic_ai_sandbox.schemas.chat import ChatRequest, ChatResponse

if TYPE_CHECKING:
    from pydantic_ai import Agent
    from pydantic_ai.agent import AgentRunResult

    from pydantic_ai_sandbox.config import Settings

router = APIRouter()

_SEARCH_KB_TOOL_NAME = "search_kb"
"""Matches the ``@agent.tool`` name registered in ``agents/chat_agent.py``."""


def _grounded_sources(result: AgentRunResult[ChatResponse]) -> list[str]:
    """Filter ``result.output.sources`` down to ids ``search_kb`` actually returned.

    Nothing upstream of this handler checks that a model-generated
    ``ChatResponse.sources`` entry corresponds to a real tool result —
    ``ChatResponse`` is a plain ``list[str]`` field, so a model can name any
    string it likes just as easily as it could invent an unfounded claim in
    free text. This walks the run's own message history for every
    ``search_kb`` :class:`ToolReturnPart` and keeps only the ``sources``
    entries that were genuinely returned, dropping the rest — the same
    "never a silently ungrounded answer" principle the sibling
    ``fastapi-pydantic-ai-agent`` repo's RAG citation validation applies,
    scaled down to this MVP's single stub tool.

    Args:
        result: The completed agent run, whose ``all_messages()`` carries
            every tool call/return made along the way.

    Returns:
        The subset of ``result.output.sources`` that ``search_kb`` actually
        returned this run, in their original order. Empty when
        ``search_kb`` was never called — an answer cannot legitimately cite
        a knowledge-base lookup that didn't happen.
    """
    returned_ids: set[str] = set()
    for message in result.all_messages():
        if not isinstance(message, ModelRequest):
            continue
        for part in message.parts:
            if isinstance(part, ToolReturnPart) and part.tool_name == _SEARCH_KB_TOOL_NAME:
                content: object = part.content
                if isinstance(content, list):
                    returned_ids.update(str(item) for item in content)  # pyright: ignore[reportUnknownVariableType,reportUnknownArgumentType]
                elif content is not None:
                    returned_ids.add(str(content))

    if not returned_ids:
        return []
    return [source for source in result.output.sources if source in returned_ids]


@router.post("/chat", response_model=ChatResponse)
async def post_chat(
    req: ChatRequest,
    agent: Agent[None, ChatResponse] = Depends(get_chat_agent),  # noqa: B008 — FastAPI Depends idiom.
    settings: Settings = Depends(get_settings_dep),  # noqa: B008 — FastAPI Depends idiom.
) -> ChatResponse:
    """Run the chat agent for ``req.message`` and return the structured output.

    Args:
        req: Validated :class:`ChatRequest` body — FastAPI handles 422 for
            invalid payloads before this handler is reached.
        agent: Cached :class:`Agent` singleton injected via
            :func:`get_chat_agent`. Tests override the agent's model with
            :class:`agent.override` so this dependency stays unaware of the
            backing provider; production traffic flows through the model
            selected by :class:`Settings`.
        settings: Cached :class:`Settings` singleton, read for the
            ``chat_usage_*`` caps and ``chat_request_timeout``.

    Returns:
        The :class:`ChatResponse` extracted from ``result.output``, with
        ``sources`` re-grounded against what ``search_kb`` actually
        returned (see :func:`_grounded_sources`). If the model produces a
        payload that fails ``ChatResponse`` validation, Pydantic AI raises
        :class:`UnexpectedModelBehavior` which propagates to FastAPI's
        default 500 handler (Req 3.4).

    Raises:
        HTTPException: 504 if the run exceeds ``chat_request_timeout``; 429
            if it exceeds ``chat_usage_request_limit`` /
            ``chat_usage_total_tokens_limit``.
    """
    limits = UsageLimits(
        request_limit=settings.chat_usage_request_limit,
        total_tokens_limit=settings.chat_usage_total_tokens_limit,
    )
    try:
        result = await asyncio.wait_for(
            agent.run(req.message, usage_limits=limits),
            timeout=settings.chat_request_timeout,
        )
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail="Chat request timed out") from exc
    except UsageLimitExceeded as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc

    return result.output.model_copy(update={"sources": _grounded_sources(result)})
