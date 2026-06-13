"""Evaluator-optimizer pattern — PydanticAI implementation (Spec 006-2a Req 5).

Generator→evaluator loop (Anthropic "Building Effective Agents"): a generator
produces a candidate, an evaluator judges it as ``pass`` or ``revise``, and the
loop repeats — feeding each ``revise`` feedback back into the next generator
input — until the evaluator passes or ``max_iterations`` is reached.

* The generator is a plain-text ``agent.run`` (``output_type=str``).
* The evaluator is a structured ``agent.run`` whose output exposes a ``verdict``
  property, so the offline ``verdict_sequenced_model`` fake can dispatch
  generator vs. evaluator calls by schema and replay a ``revise → … → pass``
  transition deterministically (Task 4.1 seam, Req 5.3/5.4).

``iterations`` records every generate/evaluate round; ``final_output`` carries
the accepted candidate on ``passed`` or the last candidate on
``max_iterations``; ``stop_reason`` is fixed to the
:class:`~patterns_contracts.OptimizationResult` vocabulary (Req 5.4).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from patterns_contracts import Iteration, OptimizationResult
from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.models.instrumented import instrument_model

if TYPE_CHECKING:
    from pydantic_ai.models import Model
    from pydantic_ai.models.instrumented import InstrumentationSettings

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
    stamps the ``index`` and pairs it with the generator's ``candidate``. Its
    JSON schema exposes a ``verdict`` property, which is the seam the offline
    fake uses to tell evaluator calls apart from generator calls.
    """

    verdict: Literal["pass", "revise"] = Field(description="Evaluator decision for the candidate.")
    feedback: str = Field(description="Actionable critique fed into the next generator attempt.")


def _generator_agent(model: Model) -> Agent[None, str]:
    """Construct the plain-text generator agent."""
    return Agent[None, str](
        model=model,
        output_type=str,
        instructions=_GENERATOR_INSTRUCTIONS,
        deps_type=type(None),
    )


def _evaluator_agent(model: Model) -> Agent[None, _Evaluation]:
    """Construct the structured evaluator agent (emits verdict + feedback)."""
    return Agent[None, _Evaluation](
        model=model,
        output_type=_Evaluation,
        instructions=_EVALUATOR_INSTRUCTIONS,
        deps_type=type(None),
    )


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
    model: Model,
    max_iterations: int = 3,
    instrumentation: InstrumentationSettings | None = None,
) -> OptimizationResult:
    """Run the generate→evaluate loop over ``task`` until pass or cap.

    Args:
        task: The user task to optimize an answer for.
        model: PydanticAI model powering both the generator and evaluator (DI
            seam shared with the other patterns). Tests inject
            ``verdict_sequenced_model``; the integration lane injects an
            Ollama-backed model.
        max_iterations: Maximum generate/evaluate rounds before stopping with
            ``stop_reason="max_iterations"``. Must be >= 1.
        instrumentation: Optional ``InstrumentationSettings`` built from
            :func:`patterns_pydantic_ai.observability.configure_tracing`. When
            set the model is wrapped via ``instrument_model`` (V2 API) so
            ``gen_ai.*`` spans flow to the provider. ``None`` runs uninstrumented.

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

    resolved = instrument_model(model, instrumentation) if instrumentation else model
    generator = _generator_agent(resolved)
    evaluator = _evaluator_agent(resolved)

    iterations: list[Iteration] = []
    candidate = ""
    feedback = ""
    for index in range(max_iterations):
        candidate = (await generator.run(_generator_prompt(task, candidate, feedback))).output
        evaluation = (await evaluator.run(_evaluator_prompt(task, candidate))).output
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
