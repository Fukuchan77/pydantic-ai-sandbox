"""Autonomous-agent pattern — PydanticAI implementation (Spec 006-2a Req 6).

A manual tool loop on chat primitives (Anthropic "Building Effective Agents"):
the model is driven directly via ``Model.request`` rather than through an
``Agent``, so this lane — not the framework — owns the four contract-level
guardrails and the closed ``stop_reason`` vocabulary, making the agentic
defense-in-depth posture (Req 10.3, OWASP "excessive agency" / "unbounded
consumption") identical across all three lanes.

The four guardrails:

* **max_iterations** (Req 6.3) — the loop stops after at most ``max_iterations``
  model turns with ``stop_reason="max_iterations"``.
* **allowed_tools** (Req 6.4, least privilege) — a requested tool absent from
  ``allowed_tools`` is *refused*: it is never executed, a refusal observation is
  fed back, and the loop continues. This is a per-call refusal, not a
  loop-terminating guardrail, which is why ``stop_reason`` has no "forbidden"
  member.
* **approval_hook** (Req 6.5) — a tool flagged ``dangerous`` must clear
  ``approval_hook`` first; a rejection stops the loop with
  ``stop_reason="denied"`` and ``final_output=None``.
* **budget** (Req 6.6) — each step's token spend is read through the
  lane-specific ``_budget_spent`` seam and accumulated; once the cumulative spend
  exceeds ``budget`` the loop stops with ``stop_reason="budget_exceeded"``.

Budget accounting is closed in the single :func:`_budget_spent` seam
(``ModelResponse.usage`` token sum) so the offline ``turn_sequenced_model`` fake
can supply a fixed per-turn token count and fire the budget guardrail
deterministically (Req 7.3). Every attempted iteration — executed, refused, or
denied — is recorded in ``steps`` so the audit trail is never silently empty.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from patterns_contracts import AgentRunResult, AgentStep
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.models.instrumented import instrument_model

if TYPE_CHECKING:
    from collections.abc import Sequence

    from patterns_contracts import ApprovalHook, Tool
    from pydantic_ai.messages import ModelMessage
    from pydantic_ai.models import Model
    from pydantic_ai.models.instrumented import InstrumentationSettings

__all__ = ["run_autonomous_agent"]


def _budget_spent(response: ModelResponse) -> int:
    """Lane budget seam: tokens consumed by one model response (Req 6.6).

    Closes the budget accounting in a single function so the offline fake can
    script a deterministic per-turn token count. PydanticAI exposes usage as
    ``ModelResponse.usage``; ``total_tokens`` is the input+output sum.
    """
    return response.usage.total_tokens


def _first_tool_call(response: ModelResponse) -> ToolCallPart | None:
    """Return the first tool-call part in a response, or None for a final answer."""
    return next((part for part in response.parts if isinstance(part, ToolCallPart)), None)


def _final_text(response: ModelResponse) -> str:
    """Concatenate the text parts of a final (no-tool-call) response."""
    return "".join(part.content for part in response.parts if isinstance(part, TextPart))


def _args_text(args: str | dict[str, Any] | None) -> str:
    """Normalize a tool call's args to the string a ``Tool.run`` expects."""
    if args is None:
        return ""
    if isinstance(args, str):
        return args
    return json.dumps(args, sort_keys=True)


def _refused_observation(tool: str) -> str:
    """Synthetic observation recorded when a tool is not in allowed_tools (Req 6.4)."""
    return f"refused: tool {tool!r} is not in allowed_tools"


def _denied_observation(tool: str) -> str:
    """Synthetic observation recorded when approval_hook rejects a tool (Req 6.5)."""
    return f"denied: approval_hook rejected dangerous tool {tool!r}"


async def run_autonomous_agent(
    goal: str,
    *,
    model: Model,
    max_iterations: int = 5,
    allowed_tools: Sequence[Tool],
    approval_hook: ApprovalHook,
    budget: int,
    instrumentation: InstrumentationSettings | None = None,
) -> AgentRunResult:
    """Run the manual guardrail tool loop toward ``goal`` (Req 6.1-6.6).

    Args:
        goal: The user goal seeding the loop's first model request.
        model: PydanticAI model driven directly via ``Model.request`` (DI seam
            shared with the other patterns). Tests inject ``turn_sequenced_model``;
            the integration lane injects an Ollama-backed model.
        max_iterations: Maximum model turns before stopping with
            ``stop_reason="max_iterations"`` (Req 6.3). Must be >= 1.
        allowed_tools: The least-privilege tool allow-list (Req 6.4); a requested
            tool outside it is refused, never executed.
        approval_hook: Human-approval seam ``(tool, args) -> approved`` consulted
            before any ``dangerous`` tool runs (Req 6.5).
        budget: Non-negative cumulative token cap; the loop stops with
            ``stop_reason="budget_exceeded"`` once spend exceeds it (Req 6.6).
        instrumentation: Optional ``InstrumentationSettings`` built from
            :func:`patterns_pydantic_ai.observability.configure_tracing`. When set
            the model is wrapped via ``instrument_model`` (V2 API) so ``gen_ai.*``
            spans flow to the provider. ``None`` runs uninstrumented.

    Returns:
        An :class:`~patterns_contracts.AgentRunResult` whose ``steps`` record
        every attempted iteration, whose ``final_output`` is the answer on
        ``completed`` (else ``None``), and whose ``stop_reason`` is fixed to the
        four-value guardrail vocabulary (Req 6.2).

    Raises:
        ValueError: If ``max_iterations`` is not positive or ``budget`` is
            negative — either would make the run meaningless rather than fail
            loudly.
    """
    if max_iterations < 1:
        msg = f"max_iterations must be >= 1, got {max_iterations}"
        raise ValueError(msg)
    if budget < 0:
        msg = f"budget must be >= 0, got {budget}"
        raise ValueError(msg)

    resolved = instrument_model(model, instrumentation) if instrumentation else model
    registry = {tool.name: tool for tool in allowed_tools}
    params = ModelRequestParameters()

    messages: list[ModelMessage] = [ModelRequest(parts=[UserPromptPart(goal)])]
    steps: list[AgentStep] = []
    total = 0

    for index in range(max_iterations):
        response = await resolved.request(messages, None, params)
        messages.append(response)
        tokens = _budget_spent(response)

        tool_call = _first_tool_call(response)
        if tool_call is None:
            return AgentRunResult(
                steps=steps,
                final_output=_final_text(response),
                stop_reason="completed",
                total_budget_spent=total,
            )

        name = tool_call.tool_name
        args = _args_text(tool_call.args)
        tool = registry.get(name)

        if tool is None:
            observation = _refused_observation(name)
        elif tool.dangerous and not approval_hook(name, args):
            steps.append(
                AgentStep(
                    index=index,
                    tool=name,
                    observation=_denied_observation(name),
                    budget_spent=tokens,
                )
            )
            return AgentRunResult(
                steps=steps,
                final_output=None,
                stop_reason="denied",
                total_budget_spent=total + tokens,
            )
        else:
            observation = tool.run(args)

        steps.append(
            AgentStep(index=index, tool=name, observation=observation, budget_spent=tokens)
        )
        total += tokens
        if total > budget:
            return AgentRunResult(
                steps=steps,
                final_output=None,
                stop_reason="budget_exceeded",
                total_budget_spent=total,
            )
        messages.append(
            ModelRequest(
                parts=[ToolReturnPart(name, observation, tool_call_id=tool_call.tool_call_id)]
            )
        )

    return AgentRunResult(
        steps=steps,
        final_output=None,
        stop_reason="max_iterations",
        total_budget_spent=total,
    )
