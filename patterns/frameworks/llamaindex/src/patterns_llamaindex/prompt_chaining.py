"""Prompt-chaining pattern — LlamaIndex Workflows implementation (Spec 006-2a Req 3).

Sequential workflow with a program-verification gate between steps (Anthropic
"Building Effective Agents", outline -> check -> document). LlamaIndex Workflows
are event-driven; the steps form a serial chain because each step emits exactly
the event the next step consumes (Req 3.2 — LlamaIndex = ``@step`` serial chain):

1. **outline** step (``StartEvent`` -> ``_DraftEvent``): ``acomplete``
   decomposes ``input_text`` into a short outline.
2. **draft** step (``_DraftEvent`` -> ``_FinalizeEvent | StopEvent``):
   ``acomplete`` expands that outline — its input *is* the outline output, so
   each step's output feeds the next step's input (Req 3.2). The draft step
   then runs the program gate.
3. **gate** is a deterministic program check (not an LLM): the draft must reach
   :data:`GATE_MIN_WORDS` words. A failed gate emits the terminal ``StopEvent``
   directly with ``final_output`` left ``None`` and ``gate.passed=False`` so
   silent continuation is impossible (Req 3.3) — the finalize step never runs.
4. **finalize** step (``_FinalizeEvent`` -> ``StopEvent``): ``acomplete``
   polishes the gated draft into ``final_output``.

``steps`` records the pre-gate steps (outline, draft); ``final_output`` carries
the post-gate answer, mirroring the :class:`~patterns_contracts.ChainResult`
contract whose ``steps`` are "executed before the gate decision".

Observability is OpenInference's process-global ``LlamaIndexInstrumentor``
(plan §9, Req 9.1): callers install it via
:func:`patterns_llamaindex.observability.instrument_llamaindex`. This module
embeds no instrumentation hook, matching the routing / orchestrator-workers lanes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from llama_index.core.prompts import PromptTemplate

# `step` lacks complete stubs upstream; ignore is scoped to that name.
from llama_index.core.workflow import (
    Event,
    StartEvent,
    StopEvent,
    Workflow,
    step,  # pyright: ignore[reportUnknownVariableType]
)
from patterns_contracts import ChainResult, ChainStep, GateOutcome

if TYPE_CHECKING:
    from llama_index.core.llms import LLM

__all__ = ["GATE_MIN_WORDS", "PromptChainWorkflow", "run_prompt_chain"]


GATE_MIN_WORDS = 3
"""Minimum word count the draft must reach to clear the program-verification
gate. A thinner draft is treated as a degenerate intermediate result and the
chain stops before spending the finalize call on it (Req 3.3). Kept identical
to the other lanes so the cross-framework contract behaves the same."""

_OUTLINE_TEMPLATE = PromptTemplate(
    "You are an outliner. Produce a short outline (a few bullet points) that "
    "covers how to answer the user's task. Output only the outline.\n\n"
    "User task: {input_text}"
)

_DRAFT_TEMPLATE = PromptTemplate(
    "You are a drafter. Expand the outline you are given into a coherent draft "
    "answer. Work only from the outline.\n\n"
    "Outline to expand into a draft:\n{outline}"
)

_FINALIZE_TEMPLATE = PromptTemplate(
    "You are an editor. Polish the draft you are given into the final answer, "
    "fixing flow and concision. Return only the finished answer.\n\n"
    "Polish this draft into the final answer:\n{draft}"
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


class _DraftEvent(Event):
    """Carries the outline forward from ``outline`` to ``draft``."""

    steps: list[ChainStep]
    outline: str


class _FinalizeEvent(Event):
    """Carries the gated draft forward from ``draft`` to ``finalize``."""

    steps: list[ChainStep]
    gate: GateOutcome
    draft: str


class PromptChainWorkflow(Workflow):
    """Serial outline -> draft -> gate -> finalize chain over a ``LLM``."""

    def __init__(self, llm: LLM, **kwargs: object) -> None:
        """Store the LLM; remaining kwargs go to ``Workflow`` (e.g. timeout)."""
        # Workflow.__init__ stub types **kwargs narrowly and rejects object.
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._llm = llm

    @step
    async def outline(self, ev: StartEvent) -> _DraftEvent:
        """Stage 1: decompose the task into a short outline."""
        input_text = str(ev.get("input_text"))
        response = await self._llm.acomplete(_OUTLINE_TEMPLATE.format(input_text=input_text))
        outline_text = str(response)
        return _DraftEvent(
            steps=[ChainStep(name="outline", output=outline_text)], outline=outline_text
        )

    @step
    async def draft(self, ev: _DraftEvent) -> _FinalizeEvent | StopEvent:
        """Stage 2: expand the outline, then run the program gate (Req 3.2/3.3)."""
        response = await self._llm.acomplete(_DRAFT_TEMPLATE.format(outline=ev.outline))
        draft_text = str(response)
        steps = [*ev.steps, ChainStep(name="draft", output=draft_text)]
        gate = _gate(draft_text)
        # The program gate decides progress (Req 3.3): a failed gate ends the
        # chain here with final_output left None, so finalize never runs.
        if not gate.passed:
            return StopEvent(result=ChainResult(steps=steps, gate=gate, final_output=None))
        return _FinalizeEvent(steps=steps, gate=gate, draft=draft_text)

    @step
    async def finalize(self, ev: _FinalizeEvent) -> StopEvent:
        """Stage 3: polish the gated draft into the final answer."""
        response = await self._llm.acomplete(_FINALIZE_TEMPLATE.format(draft=ev.draft))
        return StopEvent(
            result=ChainResult(steps=ev.steps, gate=ev.gate, final_output=str(response))
        )


async def run_prompt_chain(input_text: str, *, llm: LLM, timeout: float = 120.0) -> ChainResult:
    """Run the outline -> draft -> gate -> finalize chain over ``input_text``.

    Args:
        input_text: The user task seeding the chain's first step.
        llm: LlamaIndex LLM powering every step (DI seam shared with the other
            patterns). Tests inject the scripted completion fake (network-free);
            the integration lane injects an Ollama-backed model.
        timeout: Workflow timeout in seconds (generous for local models).

    Returns:
        A :class:`~patterns_contracts.ChainResult` whose ``steps`` hold the
        pre-gate outline/draft steps and whose ``final_output`` is the polished
        answer, or ``None`` when the gate failed and the chain stopped early
        (Req 3.3).
    """
    workflow = PromptChainWorkflow(llm=llm, timeout=timeout)
    # workflow.run's return type is partially unknown upstream; the isinstance
    # assert below narrows it for both pyright and runtime.
    result = await workflow.run(input_text=input_text)  # pyright: ignore[reportUnknownVariableType]
    assert isinstance(result, ChainResult)
    return result
