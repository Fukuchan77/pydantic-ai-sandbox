"""Routing pattern — BeeAI Framework implementation (Spec 005 Req 2).

BeeAI Workflows are state machines: each step receives the shared
Pydantic state, mutates it, and returns the next step name (or
``Workflow.END``). The two-step routing flow is::

    classify --(state.decision set)--> answer --> END

Structured output goes through ``ChatModel.create_structure``; the result
dict is then explicitly re-validated with ``RouteDecision.model_validate``
in *our* code, so an out-of-vocabulary route raises ``ValidationError``
regardless of how a given backend implements structure generation
(Req 2.3 — no silent fallback).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, get_args

from beeai_framework.backend.message import SystemMessage, UserMessage
from beeai_framework.workflows.workflow import Workflow
from patterns_contracts import Route, RoutedAnswer, RouteDecision
from pydantic import BaseModel

if TYPE_CHECKING:
    from beeai_framework.backend.chat import ChatModel

__all__ = ["ROUTE_INSTRUCTIONS", "run_routing"]


_CLASSIFY_PROMPT = (
    "You are a triage classifier for a customer-support desk. "
    "Assign the user query to exactly one route: "
    "'billing' (payments, invoices, refunds), "
    "'technical' (errors, outages, integration problems), or "
    "'general' (anything else). "
    "Return the route plus a one-sentence reasoning.\n\n"
    "User query: {query}"
)

ROUTE_INSTRUCTIONS: dict[Route, str] = {
    "billing": (
        "You are a billing specialist. Answer the user's payment/invoice "
        "question precisely and mention any next step they must take."
    ),
    "technical": (
        "You are a technical-support engineer. Diagnose the user's issue "
        "and give concrete, actionable steps."
    ),
    "general": ("You are a friendly generalist assistant. Answer the user's question concisely."),
}
"""Specialist instructions per route; keys are import-time-guarded against
the ``Route`` vocabulary so the dispatch table cannot drift."""

assert set(ROUTE_INSTRUCTIONS) == set(get_args(Route))


class _RoutingState(BaseModel):
    """Shared workflow state (BeeAI's Pydantic-state convention)."""

    query: str
    decision: RouteDecision | None = None
    answer: str | None = None


def _build_workflow(llm: ChatModel) -> Workflow[_RoutingState, str]:
    """Assemble the two-step routing workflow over ``llm`` (closure-injected)."""
    workflow: Workflow[_RoutingState, str] = Workflow(schema=_RoutingState, name="routing")

    async def classify(state: _RoutingState) -> str:
        output = await llm.create_structure(
            schema=RouteDecision,
            messages=[UserMessage(_CLASSIFY_PROMPT.format(query=state.query))],
        )
        # Explicit contract validation in lane code (Req 2.3): backends may
        # or may not validate internally; this line is the guarantee.
        state.decision = RouteDecision.model_validate(output.object)
        return "answer"

    async def answer(state: _RoutingState) -> str:
        assert state.decision is not None  # set by classify
        output = await llm.create(
            messages=[
                SystemMessage(ROUTE_INSTRUCTIONS[state.decision.route]),
                UserMessage(state.query),
            ]
        )
        state.answer = output.get_text_content()
        return Workflow.END

    workflow.add_step("classify", classify)
    workflow.add_step("answer", answer)
    return workflow


async def run_routing(query: str, *, llm: ChatModel) -> RoutedAnswer:
    """Classify ``query`` and answer it with the matching specialist.

    Args:
        query: End-user question to triage and answer.
        llm: BeeAI ``ChatModel``. Tests pass the scripted fake
            (network-free, Req 4.1); the integration lane passes
            ``OllamaChatModel`` (Req 5.3).

    Returns:
        The contract-level :class:`RoutedAnswer`.
    """
    run = await _build_workflow(llm).run(_RoutingState(query=query))
    state = run.state
    assert state.decision is not None and state.answer is not None
    return RoutedAnswer(route=state.decision.route, answer=state.answer)
