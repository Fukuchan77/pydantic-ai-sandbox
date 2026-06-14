"""Deterministic offline embedding fake for the RAG unit lane (Req 3.2, 6.3).

``HashEmbedding`` is the offline half of the embedding dependency-injection seam that
``build_index`` exposes: it derives a fixed-dimension vector from the content's SHA-256
digest, so the same text always embeds to the same vector on every machine with zero
network I/O and zero cached assets. The gated Ollama integration lane injects the real
embedding model through the same seam (Req 7); unit runs inject this fake instead.

The digest (not Python's salted ``hash``) is what makes it reproducible across processes:
``PYTHONHASHSEED`` would otherwise perturb a builtin hash run-to-run and break the index's
determinism guarantee.
"""

from __future__ import annotations

import hashlib

from llama_index.core.base.embeddings.base import BaseEmbedding

_BYTES_PER_FLOAT = 4
_UINT32_MAX = 0xFFFFFFFF


class HashEmbedding(BaseEmbedding):
    """A deterministic ``BaseEmbedding`` mapping content -> sha256 -> fixed-dimension vector."""

    model_name: str = "hash-embedding-fake"
    dim: int = 64

    def _embed(self, text: str) -> list[float]:
        """Expand the content digest into ``dim`` floats in ``[0, 1]`` deterministically."""
        seed = hashlib.sha256(text.encode("utf-8")).digest()
        vector: list[float] = []
        counter = 0
        while len(vector) < self.dim:
            block = hashlib.sha256(counter.to_bytes(4, "big") + seed).digest()
            for offset in range(0, len(block), _BYTES_PER_FLOAT):
                if len(vector) >= self.dim:
                    break
                word = int.from_bytes(block[offset : offset + _BYTES_PER_FLOAT], "big")
                vector.append(word / _UINT32_MAX)
            counter += 1
        return vector

    def _get_query_embedding(self, query: str) -> list[float]:
        return self._embed(query)

    def _get_text_embedding(self, text: str) -> list[float]:
        return self._embed(text)

    async def _aget_query_embedding(self, query: str) -> list[float]:
        return self._embed(query)
