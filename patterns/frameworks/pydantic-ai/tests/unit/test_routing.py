"""Routing pattern unit tests (Spec 005 Req 2 / 4.3)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from patterns_pydantic_ai.contracts import RouteDecision
from patterns_pydantic_ai.routing import ROUTE_INSTRUCTIONS, run_routing
from tests.support.model_fakes import scripted_model


async def test_routing_dispatches_to_scripted_route() -> None:
    model = scripted_model(
        route_payload={"route": "technical", "reasoning": "mentions an error"},
        text="restart the daemon",
    )
    result = await run_routing("The daemon crashes on boot", model=model)
    assert result.route == "technical"
    assert result.answer == "restart the daemon"


@pytest.mark.parametrize("route", sorted(ROUTE_INSTRUCTIONS))
async def test_routing_supports_every_vocabulary_route(route: str) -> None:
    model = scripted_model(
        route_payload={"route": route, "reasoning": "scripted"},
        text=f"answer-for-{route}",
    )
    result = await run_routing("any query", model=model)
    assert result.route == route
    assert result.answer == f"answer-for-{route}"


def test_route_vocabulary_rejects_unknown_route() -> None:
    # Req 2.3: values outside the Literal vocabulary must fail validation,
    # not silently fall back to a default route.
    with pytest.raises(ValidationError):
        RouteDecision(route="sales", reasoning="not in vocabulary")  # type: ignore[arg-type]
