"""Smoke test (Spec 005 Req 4.2): import + one fake-model turn + typed result."""

from __future__ import annotations

from pydantic_ai.models.test import TestModel

from patterns_pydantic_ai import RoutedAnswer, run_routing


async def test_smoke_routing_with_testmodel() -> None:
    result = await run_routing("Why was I charged twice?", model=TestModel())
    assert isinstance(result, RoutedAnswer)
    assert result.route in {"billing", "technical", "general"}
    assert isinstance(result.answer, str)
