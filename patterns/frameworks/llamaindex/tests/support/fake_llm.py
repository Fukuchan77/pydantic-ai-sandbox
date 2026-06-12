"""Scripted completion LLM for deterministic offline tests (Spec 005 Req 4.1).

``llama_index.core.llms.MockLLM`` echoes prompts / emits filler tokens and
cannot produce schema-valid JSON, so structured-output steps need a
scripted fake (research.md R-4). ``ScriptedLLM`` is a ``CustomLLM`` (a
plain completion model, NOT function-calling): ``astructured_predict``
therefore exercises the text-completion program path, whose JSON output
parser validates the canned response against the contract model — the
same validation surface the live function-calling path lands on.

Prompt dispatch heuristic: the structured-predict prompt embeds the output
schema, so the schema's distinctive property name (``"route"`` /
``"subtasks"``) appearing in the prompt selects the structured payload;
everything else gets the plain ``text`` response. Test inputs must avoid
those two quoted tokens.
"""

from __future__ import annotations

import json
from typing import Any

from llama_index.core.llms import (
    CompletionResponse,
    CompletionResponseGen,
    CustomLLM,
    LLMMetadata,
)

# Untyped upstream decorator factory; ignore is scoped to the imported name.
from llama_index.core.llms.callbacks import (
    llm_completion_callback,  # pyright: ignore[reportUnknownVariableType]
)

__all__ = ["ScriptedLLM"]


class ScriptedLLM(CustomLLM):
    """Completion-only LLM returning canned structured/text responses."""

    route_payload: dict[str, Any] | None = None
    plan_payload: dict[str, Any] | None = None
    text: str = "scripted-text"

    @property
    def metadata(self) -> LLMMetadata:
        """Advertise a plain (non-function-calling) completion model."""
        return LLMMetadata(model_name="scripted-fake", is_function_calling_model=False)

    def _dispatch(self, prompt: str) -> str:
        if '"route"' in prompt and self.route_payload is not None:
            return json.dumps(self.route_payload)
        if '"subtasks"' in prompt and self.plan_payload is not None:
            return json.dumps(self.plan_payload)
        return self.text

    @llm_completion_callback()  # pyright: ignore[reportUntypedFunctionDecorator]
    def complete(self, prompt: str, formatted: bool = False, **kwargs: Any) -> CompletionResponse:
        """Return the scripted response for ``prompt``."""
        del formatted, kwargs
        return CompletionResponse(text=self._dispatch(prompt))

    @llm_completion_callback()  # pyright: ignore[reportUntypedFunctionDecorator]
    def stream_complete(
        self, prompt: str, formatted: bool = False, **kwargs: Any
    ) -> CompletionResponseGen:
        """Stream the scripted response as a single chunk."""
        del formatted, kwargs

        def _gen() -> CompletionResponseGen:
            yield CompletionResponse(text=self._dispatch(prompt))

        return _gen()
