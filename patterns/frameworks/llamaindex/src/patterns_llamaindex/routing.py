"""Routing pattern — LlamaIndex Workflows implementation (Spec 005 Req 2).

Event-driven two-step flow: ``StartEvent`` → ``classify`` (structured
output via ``LLM.astructured_predict``) → ``_RouteEvent`` → ``answer`` →
``StopEvent``. The classifier's output is validated against the closed
``Route`` Literal by Pydantic — out-of-vocabulary routes raise instead of
silently falling back (Req 2.3).

``astructured_predict`` adapts to the LLM's capability: function-calling
LLMs (e.g. Ollama-backed) use tool-call structured output, plain
completion LLMs (the test fake) go through the text-completion program
with a JSON output parser. Both paths land in the same ``RouteDecision``
model — this is the lane's documented answer to offline structured-output
faking (plan §8 R-2).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, get_args

from llama_index.core.prompts import PromptTemplate

# `step` lacks complete stubs upstream; ignore is scoped to that name.
from llama_index.core.workflow import (
    Context,
    Event,
    StartEvent,
    StopEvent,
    Workflow,
    step,  # pyright: ignore[reportUnknownVariableType]
)

from patterns_llamaindex.contracts import Route, RoutedAnswer, RouteDecision

if TYPE_CHECKING:
    from llama_index.core.llms import LLM

__all__ = ["ROUTE_INSTRUCTIONS", "RoutingWorkflow", "run_routing"]


_CLASSIFY_TEMPLATE = PromptTemplate(
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


class _RouteEvent(Event):
    """Carries the classification decision from ``classify`` to ``answer``."""

    decision: RouteDecision
    query: str


class RoutingWorkflow(Workflow):
    """Two-step routing workflow over a caller-supplied ``LLM``."""

    def __init__(self, llm: LLM, **kwargs: object) -> None:
        """Store the LLM; remaining kwargs go to ``Workflow`` (e.g. timeout)."""
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._llm = llm

    @step
    async def classify(self, ev: StartEvent) -> _RouteEvent:
        """Stage 1: structured classification into the closed vocabulary."""
        query = str(ev.get("query"))
        decision = await self._llm.astructured_predict(
            RouteDecision, _CLASSIFY_TEMPLATE, query=query
        )
        return _RouteEvent(decision=decision, query=query)

    @step
    async def answer(self, ev: _RouteEvent, ctx: Context) -> StopEvent:
        """Stage 2: specialist completion under route-specific instructions."""
        del ctx  # present to exercise the Context-injection signature shape
        prompt = f"{ROUTE_INSTRUCTIONS[ev.decision.route]}\n\nUser query: {ev.query}"
        response = await self._llm.acomplete(prompt)
        return StopEvent(result=RoutedAnswer(route=ev.decision.route, answer=str(response)))


async def run_routing(query: str, *, llm: LLM, timeout: float = 120.0) -> RoutedAnswer:
    """Classify ``query`` and answer it with the matching specialist.

    Args:
        query: End-user question to triage and answer.
        llm: LlamaIndex LLM. Tests pass the scripted completion fake
            (network-free, Req 4.1); the integration lane passes
            ``llama_index.llms.ollama.Ollama`` (Req 5.3).
        timeout: Workflow timeout in seconds (generous for local models).

    Returns:
        The contract-level :class:`RoutedAnswer`.
    """
    workflow = RoutingWorkflow(llm=llm, timeout=timeout)
    # workflow.run's return type is partially unknown upstream; the isinstance
    # assert below narrows it for both pyright and runtime.
    result = await workflow.run(query=query)  # pyright: ignore[reportUnknownVariableType]
    assert isinstance(result, RoutedAnswer)
    return result
