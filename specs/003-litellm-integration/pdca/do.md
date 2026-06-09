# 003-litellm-integration — PDCA Do Phase

Implementation log. Continuously updated by `/sdd-impl`.

---

## 2026-06-09 — Tasks 1.1–1.3 (C1 shared mapping extraction)

**Scope**: Extract the OpenAI-shaped mapping helpers from
`llm/providers/watsonx.py` into the new shared `llm/_openai_mapping.py`
(ADR-1) so `WatsonxSDKModel` and the forthcoming `LiteLLMModel` consume one
implementation.

**Method (refactor TDD)**: A pure extraction has no new behaviour to drive
RED-first; the existing watsonx SDK suites are the characterization safety net.
Captured a green baseline (64 passed) **before** touching code, then kept it
green through the move.

### Changes

- **1.1** Created `_openai_mapping.py`; moved `_map_messages`,
  `_map_request_part`, `_map_user_prompt`, `_map_assistant_message` verbatim
  (signatures + bodies + docstrings unchanged).
- **1.2** Moved `_map_tools` (the `model_request_parameters` signature),
  `_map_usage`, and `_FINISH_REASON_MAP` into the same module.
- **1.3** Generalised `WatsonxSDKModel._build_response` into the free
  `build_response(raw, *, model_name, provider_name)`; the two hard-coded
  identity fields (`self.model_name`, `provider_name="watsonx"`) are now
  keyword parameters. `WatsonxSDKModel._build_response` is retained as a thin
  delegator that stamps `provider_name="watsonx"` — `request()` is untouched.
- **Wiring (within the shared 1.1–1.3 boundary)**: `watsonx.py` now imports
  `_map_messages` / `_map_tools` / `build_response` from `_openai_mapping`
  (the two `_map_*` carry scoped `# pyright: ignore[reportPrivateUsage]` per
  the cross-module underscore convention). Removed the now-unused runtime
  imports (`UnexpectedModelBehavior`, `RequestUsage`, the message-part classes,
  `ModelRequest`) and the dead `TYPE_CHECKING` names (`FinishReason`,
  `ModelRequestPart`, `ModelResponsePart`); moved `ModelResponse` to
  `TYPE_CHECKING` (now annotation-only).

### Decisions / learnings

- **Verbatim move, including watsonx-flavoured wording.** Error messages and
  Req-2.7 docstrings were copied byte-for-byte (Req 11.4). One deliberate
  exception: the no-`choices` message dropped its `"watsonx "` prefix
  (`"watsonx achat response contained no choices."` → `"achat response
  contained no choices."`) since the function is now shared. Verified the
  regression test asserts only `match="no choices"`, so behaviour is preserved.
- **`build_response` is public (no underscore)** per the plan; only the
  `_map_*` helpers stay underscore-prefixed and need the pyright suppression.
- **No re-export needed (defers part of 1.4).** No test imports the helpers
  from `watsonx.py` (grep confirmed only doc/comment references), so
  `watsonx.__all__` stays `["_build_watsonx"]`. The formal `__all__`
  re-export decision and the byte-for-byte audit remain task 1.4's deliverable.

### Verification gate (evidence)

| Gate | Command | Result |
|------|---------|--------|
| Baseline | `uv run pytest` (watsonx suites) | 64 passed (pre-refactor) |
| Tests | `uv run pytest tests/unit -q` | **211 passed** |
| Lint | `uv run ruff check .` | All checks passed |
| Format | `uv run ruff format --check .` | 53 files already formatted |
| Typecheck | `uv run pyright` | 0 errors, 0 warnings |

**Status**: 1.1, 1.2, 1.3 complete. Remaining in major 1: 1.4 (formal
import/re-export + byte-for-byte audit), 1.5 (dedicated shared-utility tests),
1.6 (confirm watsonx SDK suites unmodified).

---

## 2026-06-09 — Tasks 1.4–1.6 (C1 wiring, shared-utility tests, SDK audit) — major 1 complete

**Scope**: Close out major 1 — formalise the `watsonx.py` re-export deferred by
1.1–1.3, add dedicated transport-agnostic tests for `_openai_mapping`, and prove
the watsonx SDK suites pass unmodified.

### Changes

- **1.4** Re-exported `_map_messages`, `_map_tools`, `build_response` via
  `watsonx.__all__` (the production deliverable deferred from 1.1–1.3). These
  were part of `watsonx.py`'s public surface in feature `002` before the C1
  extraction; listing them in `__all__` preserves that surface (Req 11.3/11.4)
  and marks the cross-module imports as intentional re-exports for ruff/pyright.
  The `build_response(model_name=self.model_name, provider_name="watsonx")`
  wiring was already in place (1.1–1.3), verified byte-for-byte.
- **1.5** Created `tests/unit/test_openai_mapping_shared.py` — 29 hermetic,
  transport-agnostic cases hitting `_openai_mapping` directly: user/request/
  assistant part maps, full-history role+order, instructions-after-system,
  tool maps (incl. `None` when empty, output-tool `description=""`), usage
  (present + absent→zeroed), full `_FINISH_REASON_MAP` coverage, multimodal
  `NotImplementedError`, empty/missing `choices`→`UnexpectedModelBehavior`,
  absent/unmapped/absent finish-reason→`None`, empty-message→no-parts, and the
  Granite double-encoded tool-arg string surfaced raw (Req 2.4).
- **1.6** Confirmed the watsonx SDK suites pass **unmodified** —
  `git diff --stat tests/` shows zero changes to existing test files.

### Decisions / learnings

- **Re-export resolves the 1.1–1.3 deferral.** The prior log left
  `watsonx.__all__` as `["_build_watsonx"]` pending 1.4's formal decision; 1.4's
  text explicitly mandates "re-export via `__all__`", so the surface is now
  restored. No current consumer imports the helpers from `watsonx.py`, but the
  re-export is a documented backward-compat preservation, not dead surface.
- **Transport-agnostic identity proof.** The 1.5 tests stamp `some-provider`
  (not `watsonx`) through `build_response` to prove the identity generalisation
  is real — the same path `LiteLLMModel` will use for the watsonx route's
  `gen_ai.system` parity (Req 1.4).
- **`pytest --cov` ↔ beartype-claw circular import.** Adding `--cov` trips a
  circular import in `beartype.claw._clawstate` via conftest's FastAPI
  `TestClient` import; the default `uv run pytest` (no `--cov` in addopts) is
  clean. Coverage ratchet is Task 7.1's gate — its invocation must avoid/repair
  this interaction.

### Verification gate (evidence)

| Gate | Command | Result |
|------|---------|--------|
| Baseline | `uv run pytest` (watsonx SDK suites) | 64 passed (pre-change) |
| New tests | `uv run pytest tests/unit/test_openai_mapping_shared.py -q` | **29 passed** |
| SDK audit (1.6) | `uv run pytest` (5 watsonx suites) + `git diff --stat tests/` | **67 passed**, 0 test-file changes |
| Full suite | `uv run pytest -q` | **240 passed, 2 skipped** (integration lanes gated) |
| Lint | `uv run ruff check …` (touched files) | All checks passed |
| Format | `uv run ruff format --check …` | already formatted |
| Typecheck | `uv run pyright` | 0 errors, 0 warnings, 0 informations |

**Status**: **Major 1 (C1 shared mapping) complete** — 1.1–1.6 all `[x]`.
Next wave: major 2 (`LiteLLMModel`, C2), which depends on this module.
