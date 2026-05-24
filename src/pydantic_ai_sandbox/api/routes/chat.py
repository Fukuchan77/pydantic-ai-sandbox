"""``POST /chat`` route (plan.md §2.7 / §3.1 / Req 3.1-3.6).

Wires the FastAPI request layer to :class:`build_chat_agent`'s output:

1. The request body is validated against :class:`ChatRequest` by FastAPI's
   default Pydantic v2 integration. Bodies that miss ``message``, supply
   the wrong type, or violate ``min_length=1`` raise the framework's
   built-in 422 path (Req 3.6) without ever reaching the handler.
2. Inside the handler, ``await agent.run(req.message)`` invokes the
   Pydantic AI V2 agent in async mode. ``result.output`` is the validated
   :class:`ChatResponse` (V1's ``result.data`` is intentionally unsupported
   — research.md R-1 records the migration).
3. Output validation is delegated to Pydantic AI: when the model emits a
   structurally invalid payload, the framework raises
   :class:`pydantic_ai.exceptions.UnexpectedModelBehavior` after exhausting
   its retry budget. The handler does *not* catch the exception, so it
   propagates to FastAPI's default 500 handler (Req 3.4) — the spec text
   explicitly cedes exception handling to the framework default here.

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

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends

from pydantic_ai_sandbox.api.deps import get_chat_agent
from pydantic_ai_sandbox.schemas.chat import ChatRequest, ChatResponse

if TYPE_CHECKING:
    from pydantic_ai import Agent

router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
async def post_chat(
    req: ChatRequest,
    agent: Agent[None, ChatResponse] = Depends(get_chat_agent),  # noqa: B008 — FastAPI Depends idiom.
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

    Returns:
        The :class:`ChatResponse` extracted from ``result.output``. If the
        model produces a payload that fails ``ChatResponse`` validation,
        Pydantic AI raises :class:`UnexpectedModelBehavior` which
        propagates to FastAPI's default 500 handler (Req 3.4).
    """
    result = await agent.run(req.message)
    return result.output
