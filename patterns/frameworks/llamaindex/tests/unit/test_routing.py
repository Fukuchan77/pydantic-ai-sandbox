"""Routing pattern unit tests (Spec 005 Req 2 / 4.3)."""

from __future__ import annotations

import pytest
from patterns_contracts import RouteDecision
from pydantic import ValidationError

from patterns_llamaindex.routing import ROUTE_INSTRUCTIONS, run_routing
from tests.support.fake_llm import ScriptedLLM


async def test_routing_dispatches_to_scripted_route() -> None:
    llm = ScriptedLLM(
        route_payload={"route": "technical", "reasoning": "mentions an error"},
        text="restart the daemon",
    )
    result = await run_routing("The daemon crashes on boot", llm=llm)
    assert result.route == "technical"
    assert result.answer == "restart the daemon"


@pytest.mark.parametrize("route", sorted(ROUTE_INSTRUCTIONS))
async def test_routing_supports_every_vocabulary_route(route: str) -> None:
    llm = ScriptedLLM(
        route_payload={"route": route, "reasoning": "scripted"},
        text=f"answer-for-{route}",
    )
    result = await run_routing("any query", llm=llm)
    assert result.route == route
    assert result.answer == f"answer-for-{route}"


async def test_routing_rejects_out_of_vocabulary_route() -> None:
    # Req 2.3: an out-of-vocabulary classification must fail the run, not
    # silently fall back. The JSON output parser validates against the
    # RouteDecision Literal and raises.
    llm = ScriptedLLM(
        route_payload={"route": "sales", "reasoning": "not in vocabulary"},
        text="unused",
    )
    with pytest.raises((ValidationError, ValueError)):
        await run_routing("any query", llm=llm)


def test_route_vocabulary_rejects_unknown_route() -> None:
    with pytest.raises(ValidationError):
        RouteDecision(route="sales", reasoning="nope")  # type: ignore[arg-type]
