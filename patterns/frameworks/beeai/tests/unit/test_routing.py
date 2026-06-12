"""Routing pattern unit tests (Spec 005 Req 2 / 4.3)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from patterns_beeai.contracts import RouteDecision
from patterns_beeai.routing import ROUTE_INSTRUCTIONS, run_routing
from tests.support.fake_chat_model import ScriptedChatModel


async def test_routing_dispatches_to_scripted_route() -> None:
    llm = ScriptedChatModel(
        route_payload={"route": "technical", "reasoning": "mentions an error"},
        text="restart the daemon",
    )
    result = await run_routing("The daemon crashes on boot", llm=llm)
    assert result.route == "technical"
    assert result.answer == "restart the daemon"


@pytest.mark.parametrize("route", sorted(ROUTE_INSTRUCTIONS))
async def test_routing_supports_every_vocabulary_route(route: str) -> None:
    llm = ScriptedChatModel(
        route_payload={"route": route, "reasoning": "scripted"},
        text=f"answer-for-{route}",
    )
    result = await run_routing("any query", llm=llm)
    assert result.route == route
    assert result.answer == f"answer-for-{route}"


async def test_routing_rejects_out_of_vocabulary_route() -> None:
    # Req 2.3: the lane re-validates the structure output with
    # RouteDecision.model_validate; the workflow runner wraps the
    # ValidationError into FrameworkError, preserving it as __cause__.
    from beeai_framework.errors import FrameworkError

    llm = ScriptedChatModel(
        route_payload={"route": "sales", "reasoning": "not in vocabulary"},
        text="unused",
    )
    with pytest.raises(FrameworkError) as exc_info:
        await run_routing("any query", llm=llm)
    assert isinstance(exc_info.value.__cause__, ValidationError)


def test_route_vocabulary_rejects_unknown_route() -> None:
    with pytest.raises(ValidationError):
        RouteDecision(route="sales", reasoning="nope")  # type: ignore[arg-type]
