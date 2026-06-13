"""Prompt-chaining pattern — BeeAI Framework implementation (Spec 006-2a Req 3).

Sequential workflow with a program-verification gate between steps (Anthropic
"Building Effective Agents", outline -> check -> document). BeeAI Workflows are
state machines whose steps run sequentially by design (Req 3.2 — BeeAI =
Workflow with Pydantic state); the chain is ``outline -> draft -> finalize``,
where the draft step's gate either advances to finalize or jumps to
``Workflow.END`` early (leaving ``final_output=None``):

1. **outline** ``llm.create`` decomposes ``input_text`` into a short outline.
2. **draft** ``llm.create`` expands that outline — its input *is* the outline
   output, so each step's output feeds the next step's input (Req 3.2). The
   draft step then runs the program gate.
3. **gate** is a deterministic program check (not an LLM): the draft must reach
   :data:`GATE_MIN_WORDS` words. A failed gate transitions straight to
   ``Workflow.END`` with ``final_output`` left ``None`` and ``gate.passed=False``
   so silent continuation is impossible (Req 3.3) — the finalize step never runs.
4. **finalize** ``llm.create`` polishes the gated draft into ``final_output``.

``steps`` records the pre-gate steps (outline, draft); ``final_output`` carries
the post-gate answer, mirroring the :class:`~patterns_contracts.ChainResult`
contract whose ``steps`` are "executed before the gate decision".

Observability is the BeeAI manual-span fallback (plan §9, Req 9.1): callers wrap
the run with :func:`patterns_beeai.observability.traced`. This module embeds no
instrumentation hook, matching the routing / orchestrator-workers lanes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from beeai_framework.backend.message import SystemMessage, UserMessage
from beeai_framework.workflows.workflow import Workflow
from patterns_contracts import ChainResult, ChainStep, GateOutcome
from pydantic import BaseModel

if TYPE_CHECKING:
    from beeai_framework.backend.chat import ChatModel

__all__ = ["GATE_MIN_WORDS", "run_prompt_chain"]


GATE_MIN_WORDS = 3
"""Minimum word count the draft must reach to clear the program-verification
gate. A thinner draft is treated as a degenerate intermediate result and the
chain stops before spending the finalize call on it (Req 3.3). Kept identical
to the other lanes so the cross-framework contract behaves the same."""

_OUTLINE_INSTRUCTIONS = (
    "You are an outliner. Produce a short outline (a few bullet points) that "
    "covers how to answer the user's task. Output only the outline."
)

_DRAFT_INSTRUCTIONS = (
    "You are a drafter. Expand the outline you are given into a coherent draft "
    "answer. Work only from the outline."
)

_FINALIZE_INSTRUCTIONS = (
    "You are an editor. Polish the draft you are given into the final answer, "
    "fixing flow and concision. Return only the finished answer."
)


def _gate(draft: str) -> GateOutcome:
    """Program-verify the draft before the chain commits to a final answer.

    Args:
        draft: The draft step's output.

    Returns:
        A :class:`GateOutcome` that passes only when the draft reaches
        :data:`GATE_MIN_WORDS` words.
    """
    word_count = len(draft.split())
    if word_count >= GATE_MIN_WORDS:
        return GateOutcome(
            passed=True,
            detail=f"draft reached {word_count} words (>= {GATE_MIN_WORDS})",
        )
    return GateOutcome(
        passed=False,
        detail=f"draft too thin: {word_count} words (< {GATE_MIN_WORDS})",
    )


class _ChainState(BaseModel):
    """Shared workflow state across the outline/draft/finalize steps."""

    input_text: str
    steps: list[ChainStep] = []
    gate: GateOutcome | None = None
    final_output: str | None = None


def _build_workflow(llm: ChatModel) -> Workflow[_ChainState, str]:
    """Assemble the outline -> draft -> finalize chain over ``llm``."""
    workflow: Workflow[_ChainState, str] = Workflow(schema=_ChainState, name="prompt-chaining")

    async def outline(state: _ChainState) -> str:
        output = await llm.create(
            messages=[SystemMessage(_OUTLINE_INSTRUCTIONS), UserMessage(state.input_text)]
        )
        state.steps.append(ChainStep(name="outline", output=output.get_text_content()))
        return "draft"

    async def draft(state: _ChainState) -> str:
        outline_output = state.steps[-1].output  # outline appended by the prior step
        output = await llm.create(
            messages=[
                SystemMessage(_DRAFT_INSTRUCTIONS),
                UserMessage(f"Outline to expand into a draft:\n{outline_output}"),
            ]
        )
        draft_text = output.get_text_content()
        state.steps.append(ChainStep(name="draft", output=draft_text))
        state.gate = _gate(draft_text)
        # The program gate decides progress (Req 3.3): a failed gate ends the
        # chain here with final_output left None, so finalize never runs.
        if not state.gate.passed:
            return Workflow.END
        return "finalize"

    async def finalize(state: _ChainState) -> str:
        draft_text = state.steps[-1].output  # draft appended by the prior step
        output = await llm.create(
            messages=[
                SystemMessage(_FINALIZE_INSTRUCTIONS),
                UserMessage(f"Polish this draft into the final answer:\n{draft_text}"),
            ]
        )
        state.final_output = output.get_text_content()
        return Workflow.END

    workflow.add_step("outline", outline)
    workflow.add_step("draft", draft)
    workflow.add_step("finalize", finalize)
    return workflow


async def run_prompt_chain(input_text: str, *, llm: ChatModel) -> ChainResult:
    """Run the outline -> draft -> gate -> finalize chain over ``input_text``.

    Args:
        input_text: The user task seeding the chain's first step.
        llm: BeeAI ``ChatModel`` powering every step (DI seam shared with the
            other patterns). Tests inject a scripted fake; the integration lane
            injects an Ollama-backed model.

    Returns:
        A :class:`~patterns_contracts.ChainResult` whose ``steps`` hold the
        pre-gate outline/draft steps and whose ``final_output`` is the polished
        answer, or ``None`` when the gate failed and the chain stopped early
        (Req 3.3).
    """
    run = await _build_workflow(llm).run(_ChainState(input_text=input_text))
    state = run.state
    assert state.gate is not None  # set by the draft step
    return ChainResult(steps=state.steps, gate=state.gate, final_output=state.final_output)
