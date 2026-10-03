"""Guardrail tests for ``POST /chat`` (best-practices review follow-up).

Before this, the route called ``agent.run(req.message)`` with no
``usage_limits`` and no timeout at all — a runaway tool loop or a hung
provider call had no bound — and returned ``result.output`` unmodified, so a
model-invented ``ChatResponse.sources`` entry (a citation id ``search_kb``
never actually returned) reached the caller unchecked. These tests cover the
three guardrails added to ``app/api/routes/chat.py``:

1. a request that exceeds ``chat_request_timeout`` returns HTTP 504;
2. a run that exceeds ``chat_usage_request_limit`` returns HTTP 429;
3. ``ChatResponse.sources`` is re-grounded against what ``search_kb``
   actually returned this run, dropping anything the model invented, and
   forced empty when ``search_kb`` was never called.

Uses ``app_with_overrides``'s ``**env_overrides`` (tests/conftest.py) to seat
the per-test ``CHAT_*`` env vars alongside the fixture's own
``LLM_PROVIDER``/``OLLAMA_MODEL_NAME`` seating.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from pydantic_ai.messages import ModelRequest, ModelResponse, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from pydantic_ai_sandbox.schemas.chat import ChatResponse

if TYPE_CHECKING:
    from pydantic_ai.messages import ModelMessage

    from tests.conftest import AppWithOverrides

_SEARCH_KB_QUERY = "widgets"
_REAL_SOURCE_ID = f"kb-stub:{_SEARCH_KB_QUERY}"


def _already_called_search_kb(messages: list[ModelMessage]) -> bool:
    return any(
        isinstance(part, ToolReturnPart) and part.tool_name == "search_kb"
        for message in messages
        if isinstance(message, ModelRequest)
        for part in message.parts
    )


def _final_output_response(info: AgentInfo, output: dict[str, Any]) -> ModelResponse:
    output_tool = info.output_tools[0]
    return ModelResponse(parts=[ToolCallPart(output_tool.name, output)])


class TestRequestTimeout:
    """``CHAT_REQUEST_TIMEOUT`` bounds how long ``POST /chat`` waits (Req: OWASP
    unbounded consumption -- a hung provider call previously blocked forever)."""

    def test_a_run_slower_than_the_timeout_returns_504(
        self, app_with_overrides: AppWithOverrides
    ) -> None:
        async def _hang(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
            await asyncio.sleep(5)
            return ModelResponse(parts=[])  # pragma: no cover - never reached

        client = app_with_overrides(FunctionModel(_hang), CHAT_REQUEST_TIMEOUT="1")

        response = client.post("/chat", json={"message": "hello"})

        assert response.status_code == 504, response.text


class TestUsageLimit:
    """``CHAT_USAGE_REQUEST_LIMIT``/``CHAT_USAGE_TOTAL_TOKENS_LIMIT`` bound
    per-run model-request/token spend (Req: OWASP unbounded consumption)."""

    def test_a_run_needing_more_requests_than_the_limit_returns_429(
        self, app_with_overrides: AppWithOverrides
    ) -> None:
        # This model always calls search_kb first, forcing a second model
        # request to produce the final answer - request_limit=1 must trip
        # before that second request is sent.
        def _always_search_first(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            if not _already_called_search_kb(messages):
                return ModelResponse(parts=[ToolCallPart("search_kb", {"query": _SEARCH_KB_QUERY})])
            return _final_output_response(
                info, {"answer": "here", "sources": [_REAL_SOURCE_ID]}
            )  # pragma: no cover - request_limit=1 stops the run first

        client = app_with_overrides(
            FunctionModel(_always_search_first), CHAT_USAGE_REQUEST_LIMIT="1"
        )

        response = client.post("/chat", json={"message": "hello"})

        assert response.status_code == 429, response.text


class TestSourcesGrounding:
    """``ChatResponse.sources`` only ever names ids ``search_kb`` actually
    returned this run (Req: never a silently ungrounded answer)."""

    def test_invented_sources_are_dropped(self, app_with_overrides: AppWithOverrides) -> None:
        def _search_then_invent(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            if not _already_called_search_kb(messages):
                return ModelResponse(parts=[ToolCallPart("search_kb", {"query": _SEARCH_KB_QUERY})])
            return _final_output_response(
                info,
                {
                    "answer": "here",
                    "sources": [_REAL_SOURCE_ID, "totally-invented-source"],
                },
            )

        client = app_with_overrides(FunctionModel(_search_then_invent))

        response = client.post("/chat", json={"message": "hello"})

        assert response.status_code == 200, response.text
        parsed = ChatResponse.model_validate(response.json())
        assert parsed.sources == [_REAL_SOURCE_ID]

    def test_sources_are_forced_empty_when_search_kb_was_never_called(
        self, app_with_overrides: AppWithOverrides
    ) -> None:
        def _skip_search(_messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            return _final_output_response(
                info, {"answer": "here", "sources": ["invented-without-any-search"]}
            )

        client = app_with_overrides(FunctionModel(_skip_search))

        response = client.post("/chat", json={"message": "hello"})

        assert response.status_code == 200, response.text
        parsed = ChatResponse.model_validate(response.json())
        assert parsed.sources == []

    def test_a_genuinely_returned_source_survives_grounding(
        self, app_with_overrides: AppWithOverrides
    ) -> None:
        def _search_then_cite(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            if not _already_called_search_kb(messages):
                return ModelResponse(parts=[ToolCallPart("search_kb", {"query": _SEARCH_KB_QUERY})])
            return _final_output_response(info, {"answer": "here", "sources": [_REAL_SOURCE_ID]})

        client = app_with_overrides(FunctionModel(_search_then_cite))

        response = client.post("/chat", json={"message": "hello"})

        assert response.status_code == 200, response.text
        parsed = ChatResponse.model_validate(response.json())
        assert parsed.sources == [_REAL_SOURCE_ID]
