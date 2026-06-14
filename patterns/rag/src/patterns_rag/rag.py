"""The ``run_rag`` orchestration entry for the RAG lane (Spec 007-2b Req 4.1, 4.2, 4.3).

This is the lane's single public entry. It composes the modules that own each step --
deterministic retrieval (:mod:`patterns_rag.retrieval`), the injected LLM, and citation
validation (:mod:`patterns_rag.citation`) -- into one control flow:

1. retrieve the top-k chunks for the query in deterministic order;
2. build a prompt that labels every chunk with its ``chunk_id`` / ``source`` / ``locator`` /
   ``score`` so the model can cite by copying those fields back;
3. ask the LLM for a structured :class:`RagAnswer` via ``astructured_predict`` (a
   function-calling model uses tool-call structured output; the offline completion fake goes
   through the text-completion program's JSON parser -- both land on the same contract);
4. validate the answer's citations against the retrieved set, loud-failing an empty answer
   (``EmptyCitationError``) or a citation that names no retrieved chunk
   (``DanglingCitationError``) rather than returning unverified grounding.

An empty index falls out of this flow without a special case: zero retrieved chunks means an
empty prompt context, the model cites nothing, and ``validate_citations`` raises
``EmptyCitationError`` (plan §Error Handling). ``top_k < 1`` is rejected by ``retrieve``.

This module owns only the orchestration; it does not own chunking, indexing/embedding,
retrieval ordering, citation rules, or tracing wiring -- those live in their own modules.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from llama_index.core.prompts import PromptTemplate
from patterns_contracts import RagAnswer

from patterns_rag.citation import validate_citations
from patterns_rag.retrieval import retrieve

if TYPE_CHECKING:
    from collections.abc import Sequence

    from llama_index.core.llms import LLM
    from llama_index.core.retrievers import BaseRetriever
    from patterns_contracts import RetrievedChunk

__all__ = ["run_rag"]


_RAG_TEMPLATE = PromptTemplate(
    "You are a question-answering assistant. Answer the question using ONLY the sources "
    "below. For every source you rely on, add a citation by copying that source's chunk_id, "
    "source, locator, and score verbatim. Do not invent sources or cite anything absent "
    "from the list.\n\n"
    "Sources:\n{context}\n\n"
    "Question: {query}"
)


def _format_context(chunks: Sequence[RetrievedChunk]) -> str:
    """Render retrieved chunks as ``chunk_id=… | source=… | locator=… | score=…`` blocks.

    Each chunk occupies a labelled header line followed by its indented text. The header is
    the citation contract surface the model copies back; an empty sequence yields an empty
    string, so the model has nothing to cite and the answer loud-fails as empty downstream.

    A chunk's ``text`` is untrusted input (it originates from the indexed corpus): citation
    grounding (:func:`patterns_rag.citation.validate_citations`) defends the cited *ids*, not
    the answer prose, so content manipulation via a poisoned chunk is out of this surface's
    scope and is mitigated upstream by fixed fixtures + golden regression (Spec 007 §Security
    / OWASP LLM08).
    """
    return "\n".join(
        f"- chunk_id={chunk.chunk_id} | source={chunk.source} | "
        f"locator={chunk.locator} | score={chunk.score}\n  {chunk.text}"
        for chunk in chunks
    )


async def run_rag(query: str, *, llm: LLM, retriever: BaseRetriever, top_k: int = 4) -> RagAnswer:
    """Answer ``query`` with citations grounded in the top-k retrieved chunks.

    Args:
        query: The natural-language question to answer.
        llm: A LlamaIndex LLM. Unit runs inject the scripted offline fake (network-free);
            the gated integration lane injects ``llama_index.llms.ollama.Ollama``.
        retriever: Any LlamaIndex retriever (e.g. ``index.as_retriever(...)``).
        top_k: Maximum number of chunks to retrieve and expose to the model. Must be >= 1.

    Returns:
        A :class:`RagAnswer` whose citations are non-empty and all point at retrieved chunks.

    Raises:
        ValueError: If ``top_k`` is less than 1 (raised by :func:`patterns_rag.retrieval.retrieve`).
        EmptyCitationError: If the answer carries no citations (e.g. an empty index, Req 4.2).
        DanglingCitationError: If a citation names a chunk that was not retrieved (Req 4.3 / R9.3).
    """
    retrieved = retrieve(retriever, query, top_k=top_k)
    context = _format_context(retrieved)
    answer = await llm.astructured_predict(RagAnswer, _RAG_TEMPLATE, context=context, query=query)
    validate_citations(answer, retrieved)
    return answer
