"""Smoke test (Spec 005 Req 4.2): import + one fake-LLM turn + typed result."""

from __future__ import annotations

from patterns_llamaindex import RoutedAnswer, run_routing
from tests.support.fake_llm import ScriptedLLM


async def test_smoke_routing_with_scripted_llm() -> None:
    llm = ScriptedLLM(
        route_payload={"route": "general", "reasoning": "smoke"},
        text="hello from the fake",
    )
    result = await run_routing("ping", llm=llm)
    assert isinstance(result, RoutedAnswer)
    assert result.route == "general"
    assert result.answer == "hello from the fake"
