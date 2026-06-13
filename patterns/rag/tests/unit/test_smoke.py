"""Smoke test (Spec 007-2b Req 1.1/1.3/1.4): the lane package imports cleanly
and pulls in no sibling lane."""

from __future__ import annotations

import importlib
import sys

# Sibling lanes the RAG lane must never import (NFR-3 / Req 1.3). Contract
# sharing is allowed and flows only through the `patterns_contracts` path
# dependency, which is intentionally absent from this set.
SIBLING_LANES = frozenset({"patterns_pydantic_ai", "patterns_beeai", "patterns_llamaindex"})


def test_patterns_rag_imports() -> None:
    import patterns_rag

    assert patterns_rag.__name__ == "patterns_rag"


def test_no_sibling_lane_imports() -> None:
    # Import for its side effect: populate sys.modules without binding a name
    # (keeps pyright strict's reportUnusedImport quiet).
    importlib.import_module("patterns_rag")

    leaked = SIBLING_LANES & set(sys.modules)
    assert not leaked, f"RAG lane must not import sibling lanes: {sorted(leaked)}"
