"""Scripted ``FunctionModel`` for deterministic pattern tests (Spec 005 Req 4.1).

``TestModel`` (used by the smoke test) generates schema-valid but
arbitrary data; the pattern tests instead need *chosen* routes and plans.
``scripted_model`` builds a ``FunctionModel`` that:

* answers a structured-output request (``info.output_tools`` non-empty)
  with a tool call whose args come from the payload matching the output
  schema — the schema is recognised by its property names (``route`` →
  RouteDecision, ``subtasks`` → TaskPlan), because every PydanticAI output
  tool is named ``final_result`` regardless of the agent; and
* answers a plain-text request with ``text``.

This mirrors the root repo's ``tests/support/model_fakes.py`` philosophy
(fakes are tiny, explicit, and network-free) extended to structured
output via ``ToolCallPart``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import FunctionModel

if TYPE_CHECKING:
    from pydantic_ai.messages import ModelMessage
    from pydantic_ai.models.function import AgentInfo

__all__ = ["scripted_model"]


def scripted_model(
    *,
    route_payload: dict[str, Any] | None = None,
    plan_payload: dict[str, Any] | None = None,
    text: str = "scripted-text",
    model_name: str = "fake-scripted",
) -> FunctionModel:
    """Build a ``FunctionModel`` returning canned structured/text responses.

    Args:
        route_payload: Args for a ``RouteDecision``-shaped output tool
            (its schema exposes a ``route`` property).
        plan_payload: Args for a ``TaskPlan``-shaped output tool (its
            schema exposes a ``subtasks`` property).
        text: Response for plain-text (``output_type=str``) requests.
        model_name: Identifier surfaced in instrumentation spans.

    Returns:
        A ``FunctionModel`` usable anywhere the patterns accept ``model``.

    Raises:
        AssertionError: At call time, when the agent requests a structured
            output the script has no payload for — a test-authoring error
            that should fail loudly.
    """

    def _respond(_messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if info.output_tools:
            tool = info.output_tools[0]
            properties: dict[str, Any] = tool.parameters_json_schema.get("properties", {})
            if "route" in properties and route_payload is not None:
                return ModelResponse(parts=[ToolCallPart(tool.name, route_payload)])
            if "subtasks" in properties and plan_payload is not None:
                return ModelResponse(parts=[ToolCallPart(tool.name, plan_payload)])
            msg = f"scripted_model has no payload for output schema: {sorted(properties)}"
            raise AssertionError(msg)
        return ModelResponse(parts=[TextPart(text)])

    return FunctionModel(_respond, model_name=model_name)
