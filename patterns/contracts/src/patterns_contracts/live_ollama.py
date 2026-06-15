"""Single source of truth for the gated live-Ollama integration knobs (P5).

Live 8B inference on the CPU-only CI runner is slow, memory-bound, and shared
across concurrent fan-out, so every lane's live test must bound the same three
things. Before this module each lane carried its own literals, and the rag lane
re-introduced the llamaindex OOM (a ~20 GB KV cache) because it simply forgot to
set ``context_window`` — the exact "same rut" this module exists to prevent.
Centralising the values means a new lane wires constants, not magic numbers, and
the rationale travels with them.

Values
------
``LIVE_CONTEXT_WINDOW``
    Bounds the Ollama ``num_ctx``. **Critical for OOM avoidance** on clients that
    forward a context window to Ollama as ``num_ctx`` — the llama-index ``Ollama``
    LLM (and the native ``ollama`` client) default to the model's *full* context
    (granite4.1 = 131072), whose KV cache is ~20 GB and OOMs ``llama-server`` with
    a 500. 8192 tokens is ample for the short contract-level prompts and keeps the
    KV cache within the runner's memory.

    NOTE: lanes that reach Ollama through its OpenAI-compatible ``/v1`` endpoint
    (pydantic-ai's ``OllamaProvider``, beeai's litellm adapter) do **not** send
    ``num_ctx`` and instead get the server's default context, so they neither need
    nor accept this knob. Apply ``LIVE_CONTEXT_WINDOW`` on the llama-index / native
    Ollama path; it is the one that defaults to the model maximum.

``LIVE_MAX_TOKENS``
    Caps generation per request so each call returns promptly under CPU
    contention. Framework-specific spelling: ``max_tokens`` (beeai / OpenAI params)
    or ``num_predict`` (llama-index / Ollama options). Contract-level assertions
    only require non-empty output, so the cap is safe.

``LIVE_REQUEST_TIMEOUT_SECONDS``
    Per-request timeout, well above litellm's 600s default, so a slow concurrent
    branch finishes instead of being cut off mid-generation.

``LIVE_WORKFLOW_TIMEOUT_SECONDS``
    LlamaIndex ``Workflow`` per-run timeout (default 120s), a layer above the
    request timeout. A multi-step workflow over the 8B model on CPU exceeds 120s,
    so workflow-based lanes pass this via their exposed ``timeout`` knob.
"""

from __future__ import annotations

LIVE_CONTEXT_WINDOW = 8192
LIVE_MAX_TOKENS = 512
LIVE_REQUEST_TIMEOUT_SECONDS = 1200.0
LIVE_WORKFLOW_TIMEOUT_SECONDS = 1200.0
