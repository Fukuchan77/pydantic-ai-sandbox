"""Autonomous-agent pattern — BeeAI Framework implementation (Spec 006-2a Req 6).

A manual tool loop on chat primitives (Anthropic "Building Effective Agents"):
the model is driven directly via ``ChatModel.create`` rather than through a
framework agent, so this lane — not the framework — owns the four contract-level
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
(``ChatModelOutput.usage`` token sum) so the offline ``TurnSequencedChatModel``
fake can supply a fixed per-turn token count and fire the budget guardrail
deterministically (Req 7.3). Unlike the pydantic-ai lane — whose
``ToolCallPart.args`` may arrive as a dict or ``None`` — BeeAI surfaces
``MessageToolCallContent.args`` as a plain string, so the args reach ``Tool.run``
without normalization. Every attempted iteration — executed, refused, or denied —
is recorded in ``steps`` so the audit trail is never silently empty.

Observability is the BeeAI manual-span fallback (plan §9, Req 9.1): callers wrap
the run with :func:`patterns_beeai.observability.traced`. This module embeds no
instrumentation hook, matching the routing / orchestrator-workers / prompt-
chaining / parallelization / evaluator-optimizer lanes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from beeai_framework.backend.message import (
    MessageToolResultContent,
    ToolMessage,
    UserMessage,
)
from patterns_contracts import AgentRunResult, AgentStep

if TYPE_CHECKING:
    from collections.abc import Sequence

    from beeai_framework.backend.chat import ChatModel
    from beeai_framework.backend.message import AnyMessage
    from beeai_framework.backend.types import ChatModelOutput
    from patterns_contracts import ApprovalHook, Tool

__all__ = ["run_autonomous_agent"]


def _budget_spent(output: ChatModelOutput) -> int:
    """Lane budget seam: tokens consumed by one model response (Req 6.6).

    Closes the budget accounting in a single function so the offline fake can
    script a deterministic per-turn token count. BeeAI exposes usage as
    ``ChatModelOutput.usage`` (optional); ``total_tokens`` is the input+output
    sum, and a missing usage record contributes zero.
    """
    return output.usage.total_tokens if output.usage else 0


def _refused_observation(tool: str) -> str:
    """Synthetic observation recorded when a tool is not in allowed_tools (Req 6.4)."""
    return f"refused: tool {tool!r} is not in allowed_tools"


def _denied_observation(tool: str) -> str:
    """Synthetic observation recorded when approval_hook rejects a tool (Req 6.5)."""
    return f"denied: approval_hook rejected dangerous tool {tool!r}"


async def run_autonomous_agent(
    goal: str,
    *,
    llm: ChatModel,
    max_iterations: int = 5,
    allowed_tools: Sequence[Tool],
    approval_hook: ApprovalHook,
    budget: int,
) -> AgentRunResult:
    """Run the manual guardrail tool loop toward ``goal`` (Req 6.1-6.6).

    Args:
        goal: The user goal seeding the loop's first model request.
        llm: BeeAI ``ChatModel`` driven directly via ``ChatModel.create`` (DI seam
            shared with the other patterns). Tests inject
            ``TurnSequencedChatModel``; the integration lane injects an
            Ollama-backed model.
        max_iterations: Maximum model turns before stopping with
            ``stop_reason="max_iterations"`` (Req 6.3). Must be >= 1.
        allowed_tools: The least-privilege tool allow-list (Req 6.4); a requested
            tool outside it is refused, never executed.
        approval_hook: Human-approval seam ``(tool, args) -> approved`` consulted
            before any ``dangerous`` tool runs (Req 6.5).
        budget: Non-negative cumulative token cap; the loop stops with
            ``stop_reason="budget_exceeded"`` once spend exceeds it (Req 6.6).

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

    registry = {tool.name: tool for tool in allowed_tools}
    messages: list[AnyMessage] = [UserMessage(goal)]
    steps: list[AgentStep] = []
    total = 0

    for index in range(max_iterations):
        output = await llm.create(messages=messages)
        messages.extend(output.messages)
        tokens = _budget_spent(output)

        tool_calls = output.get_tool_calls()
        if not tool_calls:
            return AgentRunResult(
                steps=steps,
                final_output=output.get_text_content(),
                stop_reason="completed",
                total_budget_spent=total,
            )

        call = tool_calls[0]
        name = call.tool_name
        args = call.args
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
            ToolMessage(
                MessageToolResultContent(result=observation, tool_name=name, tool_call_id=call.id)
            )
        )

    return AgentRunResult(
        steps=steps,
        final_output=None,
        stop_reason="max_iterations",
        total_budget_spent=total,
    )
