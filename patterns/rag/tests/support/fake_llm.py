"""Scripted ``CustomLLM`` fake for the RAG lane's offline unit suite (Req 6.3).

``run_rag`` asks its LLM for a structured ``RagAnswer`` via
``LLM.astructured_predict``; for a non-function-calling model that flows through the
text-completion program, whose JSON output parser validates the model's text against
the contract (the same idiom the sibling ``llamaindex`` lane documents). ``ScriptedLLM``
is that offline model: it never reaches a network and returns a deterministic, *grounded*
answer.

Grounded means the fake does not invent sources -- it echoes back exactly the chunks
``run_rag`` placed in the prompt. ``run_rag`` labels each retrieved chunk on one line as
``chunk_id=… | source=… | locator=… | score=…``; the fake parses those labels and emits
one citation per chunk, so its ``RagAnswer`` cites real retrieved chunks and
``validate_citations`` passes. With no chunks in the prompt (an empty index) it cites
nothing, which ``run_rag`` turns into an ``EmptyCitationError`` -- exercising the full
control flow rather than a special case.

``dangling_chunk_id`` is the deliberate-misbehaviour seam: setting it appends one citation
to a ``chunk_id`` that was never retrieved, simulating a hallucinating model so a test can
prove ``run_rag``'s ``validate_citations`` call actually loud-fails (``DanglingCitationError``)
rather than passing fabricated grounding downstream.
"""

from __future__ import annotations

import json
import re
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

# Matches one chunk label line emitted by ``run_rag._format_context``:
# ``chunk_id=<id> | source=<source> | locator=<locator> | score=<score>``. The ``[^|\n]``
# classes keep each field on its own label line, and ``score`` stops at whitespace so the
# trailing float is captured cleanly. The output schema embedded in the structured-predict
# prompt uses quoted ``"chunk_id":`` keys, never ``chunk_id=``, so it cannot match here.
_CHUNK_LABEL_RE = re.compile(
    r"chunk_id=(?P<chunk_id>[^|\n]+?) \| "
    r"source=(?P<source>[^|\n]+?) \| "
    r"locator=(?P<locator>[^|\n]+?) \| "
    r"score=(?P<score>[^\s|]+)"
)


class ScriptedLLM(CustomLLM):
    """A deterministic, offline ``CustomLLM`` returning a grounded ``RagAnswer`` payload.

    Attributes:
        answer: The canned answer text returned for every query.
        dangling_chunk_id: When set, appends a citation to this (un-retrieved) ``chunk_id``
            to simulate a hallucinating model, so ``run_rag``'s citation validation can be
            shown to loud-fail.
    """

    model_name: str = "scripted-rag-fake"
    answer: str = "scripted-answer"
    dangling_chunk_id: str | None = None

    @property
    def metadata(self) -> LLMMetadata:
        """Advertise a plain (non-function-calling) completion model (text-program path)."""
        return LLMMetadata(model_name=self.model_name, is_function_calling_model=False)

    def _grounded_citations(self, prompt: str) -> list[dict[str, Any]]:
        """Build one citation per chunk label found in ``prompt`` (grounded, in prompt order)."""
        citations: list[dict[str, Any]] = [
            {
                "source": match["source"].strip(),
                "locator": match["locator"].strip(),
                "chunk_id": match["chunk_id"].strip(),
                "score": float(match["score"]),
            }
            for match in _CHUNK_LABEL_RE.finditer(prompt)
        ]
        if self.dangling_chunk_id is not None:
            citations.append(
                {
                    "source": "ghost",
                    "locator": "page=0",
                    "chunk_id": self.dangling_chunk_id,
                    "score": 0.0,
                }
            )
        return citations

    @llm_completion_callback()  # pyright: ignore[reportUntypedFunctionDecorator]
    def complete(self, prompt: str, formatted: bool = False, **kwargs: Any) -> CompletionResponse:
        """Return a ``RagAnswer`` JSON payload citing the chunks present in ``prompt``."""
        del formatted, kwargs
        payload = {"answer": self.answer, "citations": self._grounded_citations(prompt)}
        return CompletionResponse(text=json.dumps(payload))

    @llm_completion_callback()  # pyright: ignore[reportUntypedFunctionDecorator]
    def stream_complete(
        self, prompt: str, formatted: bool = False, **kwargs: Any
    ) -> CompletionResponseGen:
        """Stream the single canned completion as one chunk (delegates to ``complete``)."""
        del formatted, kwargs

        def _gen() -> CompletionResponseGen:
            yield self.complete(prompt)

        return _gen()
