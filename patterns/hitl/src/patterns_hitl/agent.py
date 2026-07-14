"""HITL support agent construction (Req 3.1-3.5, 4.1, 5.4, 12.1).

Builds a pydantic-ai ``Agent`` whose terminal output is either a structured
``SupportOutput`` or, when a ``requires_approval`` tool is pending, the
framework's ``DeferredToolRequests`` sentinel (Req 3.1). Guidance is
expressed via ``instructions`` rather than ``system_prompt`` so prompt text
does not leak into carried-over ``message_history`` across a stop/resume
boundary (Req 3.4). ``instrument=True`` is deliberately never passed to
``Agent(...)`` -- unsupported in pydantic-ai v2 (raises ``TypeError``);
instrumentation is enabled solely through ``logfire.instrument_pydantic_ai()``
(Req 3.2, wired in ``observability.py``).

Tools and the output validator are defined at module level (or returned from
a small factory) rather than as decorator-registered closures inside
``build_agent``, mirroring ``pydantic_ai_sandbox.agents.chat_agent``: a name
that is only ever *decorated*, never read afterward, reads as dead code to
pyright strict (``reportUnusedFunction``); a name that is passed into
``tools=[...]`` or returned from a factory is unambiguously used.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Annotated

from patterns_contracts import SupportOutput
from pydantic import Field
from pydantic_ai import (
    Agent,
    ApprovalRequired,
    DeferredToolRequests,
    ModelRetry,
    RunContext,
    Tool,
)

from .settings import HitlSettings

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from pydantic_ai.models import Model

__all__ = ["HitlDeps", "build_agent"]

_INSTRUCTIONS = (
    "You are a customer support agent. Look up the customer's context, "
    "propose a concrete action plan, and escalate to legal when a matter "
    "carries legal risk. Always finish with a structured SupportOutput."
)


@dataclass
class HitlDeps:
    """Fake, in-process dependencies injected into agent tool calls.

    Attributes:
        customer_directory: A fake customer lookup table keyed by customer
            id; ``search_customer_context`` reads from this instead of a
            real CRM -- the lane performs zero external I/O in tests.
    """

    customer_directory: Mapping[str, str] = field(default_factory=dict[str, str])


def search_customer_context(ctx: RunContext[HitlDeps], customer_id: str) -> str:
    """Look up a customer's account context. Never requires approval."""
    return ctx.deps.customer_directory.get(customer_id, "no record on file")


def escalate_to_legal(ctx: RunContext[HitlDeps], target_id: str, reason: str) -> str:
    """Escalate a matter to legal. Always requires human approval."""
    return f"escalated {target_id} to legal: {reason}"


def _make_apply_discount(
    risk_threshold_usd: float,
) -> Callable[[RunContext[HitlDeps], str, float], str]:
    """Build ``apply_discount``, gated by ``risk_threshold_usd`` at construction time.

    Kept as a factory (rather than a closure defined inline in
    :func:`build_agent`) so the returned function is unambiguously *used*
    (via the ``return``), not merely decorated.
    """

    def apply_discount(
        ctx: RunContext[HitlDeps],
        target_id: str,
        amount_usd: Annotated[float, Field(ge=0)],
    ) -> str:
        """Apply a discount; amounts above the risk threshold need manual approval."""
        if amount_usd > risk_threshold_usd and not ctx.tool_call_approved:
            raise ApprovalRequired
        return f"applied ${amount_usd:.2f} discount to {target_id}"

    return apply_discount


def _make_approval_policy_validator(
    risk_threshold_usd: float,
) -> Callable[[SupportOutput | DeferredToolRequests], SupportOutput | DeferredToolRequests]:
    """Build the Req 3.5 output validator, closed over ``risk_threshold_usd``.

    The framework strips ``DeferredToolRequests`` from validated outputs
    before invoking any ``@output_validator`` (it is a control-flow sentinel,
    never a model-produced structured answer), so the ``isinstance`` branch
    below is unreachable at runtime. It exists to satisfy the validator's
    static signature, which is keyed to the agent's full ``output_type``
    union rather than to what actually reaches it.
    """

    def enforce_approval_policy(
        output: SupportOutput | DeferredToolRequests,
    ) -> SupportOutput | DeferredToolRequests:
        """Reject a terminal answer that under-reports its own approval need."""
        if isinstance(output, DeferredToolRequests):  # pragma: no cover -- see factory docstring
            return output
        exceeds_threshold = any(
            action.amount_usd > risk_threshold_usd for action in output.action_plan
        )
        if exceeds_threshold and not output.requires_human_approval:
            raise ModelRetry(
                "action_plan contains an amount above the risk threshold of "
                f"${risk_threshold_usd:.2f} but requires_human_approval is "
                "False. Set requires_human_approval to True for any plan containing "
                "such an action."
            )
        return output

    return enforce_approval_policy


def build_agent(model: Model | str) -> Agent[HitlDeps, SupportOutput | DeferredToolRequests]:
    """Construct the HITL support agent bound to ``model``.

    Args:
        model: A pydantic-ai ``Model`` instance (e.g. ``TestModel``,
            ``FunctionModel``) or a live model identifier string. The lane
            never hardcodes a model string in source (Req 12.1) -- callers
            resolve it from the environment or inject a test double.

    Returns:
        An ``Agent`` whose ``output_type`` is ``[SupportOutput,
        DeferredToolRequests]`` (Req 3.1) and which declares one
        statically ``requires_approval`` tool (Req 3.3).
    """
    settings = HitlSettings()
    agent: Agent[HitlDeps, SupportOutput | DeferredToolRequests] = Agent(
        model,
        deps_type=HitlDeps,
        output_type=[SupportOutput, DeferredToolRequests],
        instructions=_INSTRUCTIONS,
        tools=[
            search_customer_context,
            _make_apply_discount(settings.risk_threshold_usd),
            Tool(escalate_to_legal, requires_approval=True),
        ],
    )
    agent.output_validator(_make_approval_policy_validator(settings.risk_threshold_usd))
    return agent
