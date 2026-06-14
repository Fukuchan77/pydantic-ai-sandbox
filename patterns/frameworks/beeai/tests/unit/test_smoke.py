"""Smoke test (Spec 005 Req 4.2): import + one fake-model turn + typed result.

Also the drift guard for plan §8 R-1: if a beeai-framework bump changes
the internal ``ChatModel`` surface the fake implements, this test fails
first and loudest.
"""

from __future__ import annotations

from patterns_beeai import RoutedAnswer, run_routing
from tests.support.fake_chat_model import ScriptedChatModel


async def test_smoke_routing_with_scripted_chat_model() -> None:
    llm = ScriptedChatModel(
        route_payload={"route": "general", "reasoning": "smoke"},
        text="hello from the fake",
    )
    result = await run_routing("ping", llm=llm)
    assert isinstance(result, RoutedAnswer)
    assert result.route == "general"
    assert result.answer == "hello from the fake"
