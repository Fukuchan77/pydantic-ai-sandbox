"""Evaluator-optimizer pattern — BeeAI Framework implementation (Spec 006-2a Req 5).

Generator→evaluator loop (Anthropic "Building Effective Agents"): a generator
produces a candidate, an evaluator judges it as ``pass`` or ``revise``, and the
loop repeats — feeding each ``revise`` feedback back into the next generator
input — until the evaluator passes or ``max_iterations`` is reached.

* The generator is a plain-text ``llm.create`` call.
* The evaluator is a structured ``llm.create_structure`` call over the
  lane-internal :class:`_Evaluation` schema; its result dict is re-validated
  with ``_Evaluation.model_validate`` in *our* code so an out-of-vocabulary
  verdict raises ``ValidationError`` regardless of how a backend implements
  structure generation (mirrors the routing lane's Req 2.3 guarantee).

Dispatch is by *method* — generator via ``create``, evaluator via
``create_structure`` — which is exactly the seam the offline
``VerdictSequencedChatModel`` fake (Task 4.2) keys off to replay a
``revise → … → pass`` transition deterministically (Req 5.3/5.4).

``iterations`` records every generate/evaluate round; ``final_output`` carries
the accepted candidate on ``passed`` or the last candidate on
``max_iterations``; ``stop_reason`` is fixed to the
:class:`~patterns_contracts.OptimizationResult` vocabulary (Req 5.4).

Observability is the BeeAI manual-span fallback (plan §9, Req 9.1): callers wrap
the run with :func:`patterns_beeai.observability.traced`. This module embeds no
instrumentation hook, matching the routing / orchestrator-workers / prompt-
chaining / parallelization lanes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from beeai_framework.backend.message import SystemMessage, UserMessage
from patterns_contracts import Iteration, OptimizationResult
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from beeai_framework.backend.chat import ChatModel

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


class _Evaluation(BaseModel):
    """Evaluator's structured judgement of a candidate (lane-internal).

    Distinct from the :class:`~patterns_contracts.Iteration` contract: the
    evaluator only decides the ``verdict``/``feedback`` pair, while the loop
    stamps the ``index`` and pairs it with the generator's ``candidate``.
    """

    verdict: Literal["pass", "revise"] = Field(description="Evaluator decision for the candidate.")
    feedback: str = Field(description="Actionable critique fed into the next generator attempt.")


def _generator_prompt(task: str, previous_candidate: str, feedback: str) -> str:
    """Build the generator input, folding in prior feedback on a revise (Req 5.3).

    Args:
        task: The original user task seeding every iteration.
        previous_candidate: The candidate produced in the prior iteration.
        feedback: The evaluator's ``revise`` feedback; empty on the first
            iteration, in which case the task alone is the prompt.

    Returns:
        The task by itself on the first iteration, otherwise the task plus the
        previous attempt and the feedback to address.
    """
    if not feedback:
        return task
    return (
        f"Task:\n{task}\n\n"
        f"Your previous attempt:\n{previous_candidate}\n\n"
        f"Evaluator feedback to address:\n{feedback}"
    )


def _evaluator_prompt(task: str, candidate: str) -> str:
    """Build the evaluator input pairing the task with the candidate to judge."""
    return f"Task:\n{task}\n\nCandidate answer to evaluate:\n{candidate}"


async def run_evaluator_optimizer(
    task: str,
    *,
    llm: ChatModel,
    max_iterations: int = 3,
) -> OptimizationResult:
    """Run the generate→evaluate loop over ``task`` until pass or cap.

    Args:
        task: The user task to optimize an answer for.
        llm: BeeAI ``ChatModel`` powering both the generator (``create``) and
            evaluator (``create_structure``) — the DI seam shared with the other
            patterns. Tests inject ``VerdictSequencedChatModel``; the integration
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
        generated = await llm.create(
            messages=[
                SystemMessage(_GENERATOR_INSTRUCTIONS),
                UserMessage(_generator_prompt(task, candidate, feedback)),
            ]
        )
        candidate = generated.get_text_content()
        evaluated = await llm.create_structure(
            schema=_Evaluation,
            messages=[
                SystemMessage(_EVALUATOR_INSTRUCTIONS),
                UserMessage(_evaluator_prompt(task, candidate)),
            ],
        )
        # Explicit contract validation in lane code (mirrors routing Req 2.3):
        # an out-of-vocabulary verdict raises here rather than silently passing.
        evaluation = _Evaluation.model_validate(evaluated.object)
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
