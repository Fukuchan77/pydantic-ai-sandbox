"""Evaluator-optimizer pattern — LlamaIndex implementation (Spec 006-2a Req 5).

Generator→evaluator loop (Anthropic "Building Effective Agents"): a generator
produces a candidate, an evaluator judges it as ``pass`` or ``revise``, and the
loop repeats — feeding each ``revise`` feedback back into the next generator
input — until the evaluator passes or ``max_iterations`` is reached.

* The generator is a plain-text ``llm.acomplete`` call.
* The evaluator is a structured ``llm.astructured_predict`` call over the
  lane-internal :class:`_Evaluation` schema. ``astructured_predict`` adapts to the
  LLM's capability (tool-call structured output for function-calling models, the
  text-completion + JSON-parser program for the plain completion fake); both
  paths land on a Pydantic-validated :class:`_Evaluation`, so an out-of-vocabulary
  verdict raises instead of silently passing (mirrors routing's Req 2.3
  guarantee). The schema embeds a ``verdict`` property, which is the seam the
  offline ``VerdictSequencedLLM`` fake (Task 4.3) keys off — the quoted
  ``"verdict"`` token in a structured-predict prompt selects its verdict cursor,
  so a ``revise → … → pass`` transition replays deterministically (Req 5.3/5.4).

Unlike the routing / prompt-chaining / parallelization lanes this pattern is a
plain ``for`` loop rather than a LlamaIndex ``Workflow``: the loop is inherently
sequential with no fan-out, so the event machinery would add no contract value
(matching the beeai lane's 7.2 decision and parallelization's judgement that a
Workflow is not mandatory here).

``iterations`` records every generate/evaluate round; ``final_output`` carries
the accepted candidate on ``passed`` or the last candidate on
``max_iterations``; ``stop_reason`` is fixed to the
:class:`~patterns_contracts.OptimizationResult` vocabulary (Req 5.4).

Observability is OpenInference's process-global ``LlamaIndexInstrumentor``
(plan §9, Req 9.1): callers install it via
:func:`patterns_llamaindex.observability.instrument_llamaindex`, which captures
the leaf ``acomplete`` / ``astructured_predict`` spans. This module embeds no
instrumentation hook, matching the other LlamaIndex lanes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from llama_index.core.prompts import PromptTemplate
from patterns_contracts import Iteration, OptimizationResult
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from llama_index.core.llms import LLM

__all__ = ["run_evaluator_optimizer"]


_GENERATOR_INSTRUCTIONS = (
    "You are a generator. Produce your best complete answer to the task. When "
    "you are given prior-attempt feedback, revise your previous answer to "
    "address it. Output only the answer."
)

_EVALUATOR_INSTRUCTIONS = (
    "You are a strict evaluator. Judge whether the candidate answer fully and "
    "correctly addresses the task. Return verdict='pass' only when it does; "
    "otherwise return verdict='revise' with concrete, actionable feedback."
)

_EVALUATOR_TEMPLATE = PromptTemplate(
    _EVALUATOR_INSTRUCTIONS + "\n\nTask:\n{task}\n\nCandidate answer to evaluate:\n{candidate}"
)


class _Evaluation(BaseModel):
    """Evaluator's structured judgement of a candidate (lane-internal).

    Distinct from the :class:`~patterns_contracts.Iteration` contract: the
    evaluator only decides the ``verdict``/``feedback`` pair, while the loop
    stamps the ``index`` and pairs it with the generator's ``candidate``. Its
    JSON schema exposes a ``verdict`` property, which is the seam the offline
    fake uses to tell evaluator calls apart from generator calls.
    """

    verdict: Literal["pass", "revise"] = Field(description="Evaluator decision for the candidate.")
    feedback: str = Field(description="Actionable critique fed into the next generator attempt.")


def _generator_prompt(task: str, previous_candidate: str, feedback: str) -> str:
    """Build the generator input, folding in prior feedback on a revise (Req 5.3).

    Args:
        task: The original user task seeding every iteration.
        previous_candidate: The candidate produced in the prior iteration.
        feedback: The evaluator's ``revise`` feedback; empty on the first
            iteration, in which case the task alone seeds the prompt.

    Returns:
        The generator instructions plus the task by itself on the first
        iteration, otherwise plus the previous attempt and the feedback to
        address.
    """
    if not feedback:
        body = f"Task:\n{task}"
    else:
        body = (
            f"Task:\n{task}\n\n"
            f"Your previous attempt:\n{previous_candidate}\n\n"
            f"Evaluator feedback to address:\n{feedback}"
        )
    return f"{_GENERATOR_INSTRUCTIONS}\n\n{body}"


async def run_evaluator_optimizer(
    task: str,
    *,
    llm: LLM,
    max_iterations: int = 3,
) -> OptimizationResult:
    """Run the generate→evaluate loop over ``task`` until pass or cap.

    Args:
        task: The user task to optimize an answer for.
        llm: LlamaIndex LLM powering both the generator (``acomplete``) and
            evaluator (``astructured_predict``) — the DI seam shared with the
            other patterns. Tests inject ``VerdictSequencedLLM``; the integration
            lane injects an Ollama-backed model.
        max_iterations: Maximum generate/evaluate rounds before stopping with
            ``stop_reason="max_iterations"``. Must be >= 1.

    Returns:
        An :class:`~patterns_contracts.OptimizationResult` whose ``iterations``
        record every round, whose ``final_output`` is the accepted candidate
        (``passed``) or the last candidate (``max_iterations``), and whose
        ``stop_reason`` is fixed to that two-value vocabulary (Req 5.4).

    Raises:
        ValueError: If ``max_iterations`` is not positive — a zero/negative cap
            would silently produce an empty optimization run.
    """
    if max_iterations < 1:
        msg = f"max_iterations must be >= 1, got {max_iterations}"
        raise ValueError(msg)

    iterations: list[Iteration] = []
    candidate = ""
    feedback = ""
    for index in range(max_iterations):
        response = await llm.acomplete(_generator_prompt(task, candidate, feedback))
        candidate = str(response)
        evaluation = await llm.astructured_predict(
            _Evaluation, _EVALUATOR_TEMPLATE, task=task, candidate=candidate
        )
        iterations.append(
            Iteration(
                index=index,
                candidate=candidate,
                verdict=evaluation.verdict,
                feedback=evaluation.feedback,
            )
        )
        if evaluation.verdict == "pass":
            return OptimizationResult(
                iterations=iterations,
                final_output=candidate,
                stop_reason="passed",
            )
        feedback = evaluation.feedback

    return OptimizationResult(
        iterations=iterations,
        final_output=candidate,
        stop_reason="max_iterations",
    )
