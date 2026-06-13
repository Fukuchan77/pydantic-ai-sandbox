"""Routing pattern — PydanticAI implementation (Spec 005 Req 2).

Two-stage flow (Anthropic "Building Effective Agents" routing workflow):

1. A classifier ``Agent`` with ``output_type=RouteDecision`` assigns the
   query to one of the closed ``Route`` vocabulary values. Anything
   outside the ``Literal`` fails Pydantic validation — PydanticAI then
   retries and ultimately raises instead of silently falling back
   (Req 2.3).
2. A per-route specialist ``Agent`` (plain ``str`` output) answers the
   query under route-specific instructions.

Both agents are built per call from the caller-supplied ``model`` so
tests inject ``TestModel``/``FunctionModel`` and the integration lane
injects an Ollama-backed model — the construction path is identical
(mirrors ``build_chat_agent``'s DI seam in the root app).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, get_args

from patterns_contracts import Route, RoutedAnswer, RouteDecision
from pydantic_ai import Agent
from pydantic_ai.models.instrumented import instrument_model

if TYPE_CHECKING:
    from pydantic_ai.models import Model
    from pydantic_ai.models.instrumented import InstrumentationSettings

__all__ = ["ROUTE_INSTRUCTIONS", "run_routing"]


_CLASSIFIER_INSTRUCTIONS = (
    "You are a triage classifier for a customer-support desk. "
    "Assign the user query to exactly one route: "
    "'billing' (payments, invoices, refunds), "
    "'technical' (errors, outages, integration problems), or "
    "'general' (anything else). "
    "Return the route plus a one-sentence reasoning."
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
"""Specialist instructions per route. Keys are asserted against the
``Route`` vocabulary at import time so the dispatch table can never drift
from the contract."""

# Import-time guard: a missing/extra key would otherwise only surface when
# that route is first classified at runtime.
assert set(ROUTE_INSTRUCTIONS) == set(get_args(Route))


def _build_classifier(model: Model) -> Agent[None, RouteDecision]:
    """Construct the stage-1 classifier agent."""
    return Agent[None, RouteDecision](
        model=model,
        output_type=RouteDecision,
        instructions=_CLASSIFIER_INSTRUCTIONS,
        deps_type=type(None),
    )


def _build_specialist(model: Model, route: Route) -> Agent[None, str]:
    """Construct the stage-2 specialist agent for ``route``."""
    return Agent[None, str](
        model=model,
        output_type=str,
        instructions=ROUTE_INSTRUCTIONS[route],
        deps_type=type(None),
    )


async def run_routing(
    query: str,
    *,
    model: Model,
    instrumentation: InstrumentationSettings | None = None,
) -> RoutedAnswer:
    """Classify ``query`` and answer it with the matching specialist.

    Args:
        query: End-user question to triage and answer.
        model: PydanticAI model powering both stages. Tests pass
            ``TestModel``/``FunctionModel`` (network-free, Req 4.1); the
            integration lane passes an Ollama-backed model (Req 5.3).
        instrumentation: Optional ``InstrumentationSettings`` built from
            :func:`patterns_pydantic_ai.observability.configure_tracing`.
            When set, the model is wrapped via ``instrument_model`` (the
            V2 replacement for V1's ``Agent(instrument=...)`` kwarg) so
            ``gen_ai.*`` spans flow to the configured provider. ``None``
            keeps the run uninstrumented.

    Returns:
        The contract-level :class:`RoutedAnswer`.
    """
    resolved = instrument_model(model, instrumentation) if instrumentation else model
    decision = (await _build_classifier(resolved).run(query)).output
    answer = (await _build_specialist(resolved, decision.route).run(query)).output
    return RoutedAnswer(route=decision.route, answer=answer)
