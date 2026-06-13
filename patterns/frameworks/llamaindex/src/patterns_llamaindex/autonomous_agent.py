"""Autonomous-agent pattern — LlamaIndex implementation (Spec 006-2a Req 6).

A manual tool loop on the LlamaIndex completion primitive (Anthropic "Building
Effective Agents"): the model is driven directly via ``llm.acomplete`` rather
than through a framework agent, so this lane — not the framework — owns the four
contract-level guardrails and the closed ``stop_reason`` vocabulary, making the
agentic defense-in-depth posture (Req 10.3, OWASP "excessive agency" / "unbounded
consumption") identical across all three lanes.

The four guardrails:

* **max_iterations** (Req 6.3) — the loop stops after at most ``max_iterations``
  model turns with ``stop_reason="max_iterations"``.
* **allowed_tools** (Req 6.4, least privilege) — a requested tool absent from
  ``allowed_tools`` is *refused*: it is never executed, the refused attempt is
  recorded as a step, and the loop stops with ``stop_reason="disallowed_tool"``
  and ``final_output=None``. A disallowed tool call is a hard stop (OWASP
  "excessive agency"), distinct from the ``denied`` approval rejection.
* **approval_hook** (Req 6.5) — a tool flagged ``dangerous`` must clear
  ``approval_hook`` first; a rejection stops the loop with
  ``stop_reason="denied"`` and ``final_output=None``.
* **budget** (Req 6.6) — each step's token spend is read through the
  lane-specific ``_budget_spent`` seam and accumulated; once the cumulative spend
  exceeds ``budget`` the loop stops with ``stop_reason="budget_exceeded"``.

LlamaIndex's ``CustomLLM`` is completion-only with no native tool-call parts, so
the tool-call channel is a JSON convention (Task 4.3): a model turn that parses
to an object carrying a ``"tool"`` key is a tool call (with a string ``args``),
and anything else is the final answer. Budget accounting is closed in the single
:func:`_budget_spent` seam (``CompletionResponse.raw["usage"]["total_tokens"]``)
so the offline ``TurnSequencedLLM`` fake can supply a fixed per-turn token count
and fire the budget guardrail deterministically (Req 7.3). Every attempted
iteration — executed, refused, or denied — is recorded in ``steps`` so the audit
trail is never silently empty.

Observability is OpenInference's process-global ``LlamaIndexInstrumentor``
(plan §9, Req 9.1): callers install it via
:func:`patterns_llamaindex.observability.instrument_llamaindex`, which captures
the leaf ``acomplete`` spans. This module embeds no instrumentation hook,
matching the other LlamaIndex lanes.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, cast

from patterns_contracts import AgentRunResult, AgentStep

if TYPE_CHECKING:
    from collections.abc import Sequence

    from llama_index.core.llms import LLM, CompletionResponse
    from patterns_contracts import ApprovalHook, Tool

__all__ = ["run_autonomous_agent"]


_LOOP_INSTRUCTIONS = (
    "You are an autonomous agent. To use a tool, respond with a single JSON "
    'object {"tool": "<name>", "args": "<string>"} and nothing else. To finish, '
    "respond with your final answer as plain text (not JSON)."
)


def _as_mapping(value: object) -> dict[str, object] | None:
    """Narrow an opaque JSON value to a string-keyed mapping, or None.

    The single narrowing point for the two boundaries that ingest untyped JSON
    (``CompletionResponse.raw`` and a parsed completion): both arrive as ``Any``
    from loose upstream stubs / ``json.loads``, so they are coerced to a typed
    ``dict[str, object]`` here before flowing inward (constitution II: ``Any`` is
    narrowed at the I/O boundary, never carried).
    """
    if isinstance(value, dict):
        return cast("dict[str, object]", value)
    return None


def _budget_spent(response: CompletionResponse) -> int:
    """Lane budget seam: tokens consumed by one model response (Req 6.6).

    Closes the budget accounting in a single function so the offline fake can
    script a deterministic per-turn token count. LlamaIndex's ``CustomLLM``
    surfaces usage on ``CompletionResponse.raw`` (an opaque provider payload);
    this seam reads ``raw["usage"]["total_tokens"]`` defensively, contributing
    zero whenever the provider omits a usage record.
    """
    raw = _as_mapping(response.raw)
    if raw is None:
        return 0
    usage = _as_mapping(raw.get("usage"))
    if usage is None:
        return 0
    total = usage.get("total_tokens")
    return total if isinstance(total, int) else 0


def _parse_action(text: str) -> tuple[str, str] | None:
    """Parse a completion as a ``(tool, args)`` call, or None for a final answer.

    The LlamaIndex tool-call convention (Task 4.3): a completion that parses to a
    JSON object carrying a ``"tool"`` key is a tool call, with ``args`` taken as a
    string (defaulting to ``""``); anything else — non-JSON, a JSON scalar, or an
    object without ``"tool"`` — is the model's final answer.
    """
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    obj = _as_mapping(parsed)
    if obj is None or "tool" not in obj:
        return None
    return str(obj["tool"]), str(obj.get("args", ""))


def _refused_observation(tool: str) -> str:
    """Synthetic observation recorded when a tool is not in allowed_tools (Req 6.4)."""
    return f"refused: tool {tool!r} is not in allowed_tools"


def _denied_observation(tool: str) -> str:
    """Synthetic observation recorded when approval_hook rejects a tool (Req 6.5)."""
    return f"denied: approval_hook rejected dangerous tool {tool!r}"


def _initial_prompt(goal: str) -> str:
    """Seed the transcript with the loop instructions and the user goal."""
    return f"{_LOOP_INSTRUCTIONS}\n\nGoal:\n{goal}"


def _extend_transcript(transcript: str, tool: str, args: str, observation: str) -> str:
    """Append a tool call and its observation so the next turn conditions on them."""
    action = json.dumps({"tool": tool, "args": args})
    return f"{transcript}\nAction: {action}\nObservation: {observation}"


async def run_autonomous_agent(
    goal: str,
    *,
    llm: LLM,
    max_iterations: int = 5,
    allowed_tools: Sequence[Tool],
    approval_hook: ApprovalHook,
    budget: int,
) -> AgentRunResult:
    """Run the manual guardrail tool loop toward ``goal`` (Req 6.1-6.6).

    Args:
        goal: The user goal seeding the loop's first model request.
        llm: LlamaIndex LLM driven directly via ``llm.acomplete`` (DI seam shared
            with the other patterns). Tests inject ``TurnSequencedLLM``; the
            integration lane injects an Ollama-backed model.
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
        five-value guardrail vocabulary (Req 6.2).

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
    transcript = _initial_prompt(goal)
    steps: list[AgentStep] = []
    total = 0

    for index in range(max_iterations):
        response = await llm.acomplete(transcript)
        tokens = _budget_spent(response)

        action = _parse_action(response.text)
        if action is None:
            return AgentRunResult(
                steps=steps,
                final_output=response.text,
                stop_reason="completed",
                total_budget_spent=total,
            )

        name, args = action
        tool = registry.get(name)

        if tool is None:
            steps.append(
                AgentStep(
                    index=index,
                    tool=name,
                    observation=_refused_observation(name),
                    budget_spent=tokens,
                )
            )
            return AgentRunResult(
                steps=steps,
                final_output=None,
                stop_reason="disallowed_tool",
                total_budget_spent=total + tokens,
            )
        if tool.dangerous and not approval_hook(name, args):
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
        transcript = _extend_transcript(transcript, name, args, observation)

    return AgentRunResult(
        steps=steps,
        final_output=None,
        stop_reason="max_iterations",
        total_budget_spent=total,
    )
