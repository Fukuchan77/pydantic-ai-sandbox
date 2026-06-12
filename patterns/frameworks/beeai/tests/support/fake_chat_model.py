"""Scripted ``ChatModel`` fake for deterministic offline tests (Spec 005 Req 4.1).

beeai-framework ships no official mock (upstream issue #750); its own test
suite subclasses ``ChatModel`` directly (e.g. ``ReverseWordsDummyModel``),
so this fake follows the same approach (research.md R-4). It implements
the abstract surface of beeai-framework 0.1.39 — ``_create``,
``_create_stream``, ``_create_structure``, ``model_id``, ``provider_id``.
Because that surface is internal, the lane pins beeai-framework EXACT
(``==``) and the smoke test guards drift (plan §8 R-1).

Structured dispatch keys off the requested schema type: ``RouteDecision``-
shaped schemas (a ``route`` field) get ``route_payload``, ``TaskPlan``-
shaped schemas (a ``subtasks`` field) get ``plan_payload``; plain chat
gets ``text``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from beeai_framework.backend.chat import ChatModel
from beeai_framework.backend.message import AssistantMessage
from beeai_framework.backend.types import ChatModelOutput, ChatModelStructureOutput

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from beeai_framework.backend.constants import ProviderName
    from beeai_framework.backend.types import ChatModelInput, ChatModelStructureInput
    from beeai_framework.context import RunContext

__all__ = ["ScriptedChatModel"]


class ScriptedChatModel(ChatModel):
    """Network-free ``ChatModel`` returning canned structured/text responses."""

    def __init__(
        self,
        *,
        route_payload: dict[str, Any] | None = None,
        plan_payload: dict[str, Any] | None = None,
        text: str = "scripted-text",
    ) -> None:
        """Store the canned payloads; no I/O happens at any point."""
        super().__init__()
        self._route_payload = route_payload
        self._plan_payload = plan_payload
        self._text = text

    @property
    def model_id(self) -> str:
        """Fake model identifier (surfaced in emitter metadata)."""
        return "scripted-fake"

    @property
    def provider_id(self) -> ProviderName:
        """Provider identifier; constrained upstream to the ProviderName Literal.

        "ollama" is borrowed purely to satisfy the closed vocabulary — no
        Ollama daemon is ever contacted (``_create*`` are all canned).
        """
        return "ollama"

    async def _create(self, input: ChatModelInput, run: RunContext) -> ChatModelOutput:  # noqa: A002 - upstream signature
        del input, run
        return ChatModelOutput(messages=[AssistantMessage(self._text)])

    def _create_stream(
        self,
        input: ChatModelInput,  # noqa: A002 - upstream signature
        run: RunContext,
    ) -> AsyncGenerator[ChatModelOutput]:
        async def _gen() -> AsyncGenerator[ChatModelOutput]:
            yield ChatModelOutput(messages=[AssistantMessage(self._text)])

        del input, run
        return _gen()

    async def _create_structure(
        self,
        input: ChatModelStructureInput[Any],  # noqa: A002 - upstream signature
        run: RunContext,
    ) -> ChatModelStructureOutput:
        del run
        schema = input.input_schema
        field_names = set(getattr(schema, "model_fields", {}))
        if "route" in field_names and self._route_payload is not None:
            return ChatModelStructureOutput(object=self._route_payload)
        if "subtasks" in field_names and self._plan_payload is not None:
            return ChatModelStructureOutput(object=self._plan_payload)
        msg = f"ScriptedChatModel has no payload for schema fields: {sorted(field_names)}"
        raise AssertionError(msg)
