"""Docling + LlamaIndex RAG application lane of the cross-framework patterns.

This package implements a retrieval-augmented generation pipeline that returns
answers with citations anchored to real chunks (Spec 007-2b). The public
surface — ``run_rag``, the contract types, exceptions, and tracing helpers — is
re-exported here by Task 7.3 once the pipeline modules land; at scaffold time
this module only marks the package and anchors the import smoke test (Req 1.1).
"""

from __future__ import annotations
