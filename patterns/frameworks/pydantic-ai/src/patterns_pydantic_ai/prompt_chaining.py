"""Prompt-chaining pattern — PydanticAI implementation (Spec 006-2a Req 3).

Sequential workflow with a program-verification gate between steps (Anthropic
"Building Effective Agents", outline -> check -> document):

1. **outline** ``agent.run`` decomposes ``input_text`` into a short outline.
2. **draft** ``agent.run`` expands that outline — its input *is* the outline
   output, so each step's output feeds the next step's input (Req 3.2).
3. **gate** is a deterministic program check (not an LLM): the draft must reach
   :data:`GATE_MIN_WORDS` words. A failed gate ends the chain early with
   ``final_output=None`` and ``gate.passed=False`` so silent continuation is
   impossible (Req 3.3) — the finalize step below never runs.
4. **finalize** ``agent.run`` polishes the gated draft into ``final_output``.

``steps`` records the pre-gate steps (outline, draft); ``final_output`` carries
the post-gate answer, mirroring the :class:`~patterns_contracts.ChainResult`
contract whose ``steps`` are "executed before the gate decision".
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from patterns_contracts import ChainResult, ChainStep, GateOutcome
from pydantic_ai import Agent
from pydantic_ai.models.instrumented import instrument_model

if TYPE_CHECKING:
    from pydantic_ai.models import Model
    from pydantic_ai.models.instrumented import InstrumentationSettings

__all__ = ["GATE_MIN_WORDS", "run_prompt_chain"]


GATE_MIN_WORDS = 3
"""Minimum word count the draft must reach to clear the program-verification
gate. A thinner draft is treated as a degenerate intermediate result and the
chain stops before spending the finalize call on it (Req 3.3)."""

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


def _agent(model: Model, instructions: str) -> Agent[None, str]:
    """Construct a plain-text agent with shared settings."""
    return Agent[None, str](
        model=model,
        output_type=str,
        instructions=instructions,
        deps_type=type(None),
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


async def run_prompt_chain(
    input_text: str,
    *,
    model: Model,
    instrumentation: InstrumentationSettings | None = None,
) -> ChainResult:
    """Run the outline -> draft -> gate -> finalize chain over ``input_text``.

    Args:
        input_text: The user task seeding the chain's first step.
        model: PydanticAI model powering every step (DI seam shared with the
            other patterns). Tests inject ``FunctionModel``; the integration
            lane injects an Ollama-backed model.
        instrumentation: Optional ``InstrumentationSettings`` built from
            :func:`patterns_pydantic_ai.observability.configure_tracing`. When
            set the model is wrapped via ``instrument_model`` (V2 API) so
            ``gen_ai.*`` spans flow to the provider. ``None`` runs uninstrumented.

    Returns:
        A :class:`~patterns_contracts.ChainResult` whose ``steps`` hold the
        pre-gate outline/draft steps and whose ``final_output`` is the polished
        answer, or ``None`` when the gate failed and the chain stopped early
        (Req 3.3).
    """
    resolved = instrument_model(model, instrumentation) if instrumentation else model

    outline = (await _agent(resolved, _OUTLINE_INSTRUCTIONS).run(input_text)).output
    draft = (
        await _agent(resolved, _DRAFT_INSTRUCTIONS).run(
            f"Outline to expand into a draft:\n{outline}"
        )
    ).output
    steps = [
        ChainStep(name="outline", output=outline),
        ChainStep(name="draft", output=draft),
    ]

    gate = _gate(draft)
    if not gate.passed:
        return ChainResult(steps=steps, gate=gate, final_output=None)

    final_output = (
        await _agent(resolved, _FINALIZE_INSTRUCTIONS).run(
            f"Polish this draft into the final answer:\n{draft}"
        )
    ).output
    return ChainResult(steps=steps, gate=gate, final_output=final_output)
