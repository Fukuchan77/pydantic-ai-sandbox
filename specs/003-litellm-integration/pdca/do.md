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

---

## 2026-06-09 — Tasks 2.1–2.2 (C2 `LiteLLMModel` construction + happy-path request)

**Scope**: Create `llm/providers/litellm.py` — the I/O-free `LiteLLMModel`
constructor + `model_name`/`system`/`profile` properties (2.1) and the
non-streaming `request()` happy path routing through `litellm.acompletion()`
and the shared `_openai_mapping.build_response` (2.2). Error-wrapping (2.3) and
streaming-deferral (2.4) are out of scope for this slice.

**Method (TDD)**: Wrote three hermetic test files first (RED — collection
`ModuleNotFoundError`), then implemented to green. `acompletion` is mocked
(monkeypatch on the module attr, reached via the function-local import); response
cases build a real `litellm.ModelResponse` so the load-bearing `.model_dump()`
arg-preservation (Req 2.4) is exercised faithfully, not stubbed.

### Changes

- **2.1** New `litellm.py` with the upstream `pydantic-ai-litellm` MIT
  attribution header (library / version-reconciliation note / repo URL). I/O-free
  keyword-only `__init__`; `model_name` returns the route; `system` is derived
  once in `__init__` as `route.split("/",1)[0]` (→ `"watsonx"`), falling back to
  `"litellm"` for a prefix-less route; `profile` is a `cached_property` returning
  `merge_profile(DEFAULT_PROFILE, ModelProfile(supports_json_schema_output=False))`
  (explicit-false over the package default, preserving all other default fields).
- **2.2** `request()` (3-param V2 ABC): function-local `import litellm` (optional
  dep, Req 6.2), map via shared `_map_messages`/`_map_tools`,
  `acompletion(..., num_retries=0, timeout=httpx.Timeout(read, connect=connect))`,
  then `.model_dump()` → `build_response(raw, model_name=…, provider_name=self.system)`.
  No `try/except` yet (2.3); mapping/response errors surface unwrapped.

### Decisions / learnings

- **`system` is stamped onto the response.** `provider_name=self.system` (not a
  literal `"litellm"`) gives `gen_ai.system == "watsonx"` parity with the SDK path
  for the watsonx route (Req 1.4) — pinned by a mocked-`acompletion` parity test.
- **litellm stubs forced 3 scoped `# pyright: ignore`s.** `acompletion`'s loose
  param stubs (`reportUnknownMemberType`), the narrow `timeout: float|int|None`
  (`reportArgumentType` — it forwards `httpx.Timeout` at runtime per research.md),
  and the `ModelResponse | CustomStreamWrapper` return union (no `model_dump` on
  the stream wrapper → `reportAttributeAccessIssue`). Each carries a rationale.
- **TC002**: the construction test uses `pytest` only in annotations (no
  `pytest.raises`), so `import pytest` moved under `TYPE_CHECKING`.

### Verification gate (evidence)

| Gate | Command | Result |
|------|---------|--------|
| RED | `uv run pytest tests/unit/test_litellm_*` (pre-impl) | 3 collection errors (`No module named …litellm`) |
| New tests | `uv run pytest tests/unit/test_litellm_construction.py …message_mapping.py …response_mapping.py -q` | **14 passed** |
| Full suite | `uv run pytest -q` | **254 passed, 2 skipped** (was 240+2; +14 new) |
| Lint | `uv run ruff check .` | All checks passed |
| Format | `uv run ruff format --check .` | 58 files already formatted |
| Typecheck | `uv run pyright` | 0 errors, 0 warnings, 0 informations |

**Status**: 2.1, 2.2 `[x]`. Remaining in major 2: 2.3 (broad-except →
`ModelAPIError`, scoped to `acompletion` only), 2.4 (`request_stream`
deferral). Test files seeded for 3.1–3.3; 3.4–3.6 await 2.3/2.4.

---

## 2026-06-09 — Tasks 2.3–2.4 (C2 error classification + streaming deferral) — major 2 complete

**Scope**: Close out `LiteLLMModel` — wrap `acompletion` failures as
`ModelAPIError` scoped to the call only (2.3), and override `request_stream` to
defer streaming with a greppable, model-named `NotImplementedError` (2.4).

**Method (TDD)**: Wrote two hermetic test files first (RED), implemented to
GREEN. `acompletion` is mocked via `monkeypatch` on the module attr (reached
through the function-local import). RED run: 8 failed / 2 passed — the 2 passing
are correct regression guards (base ABC already raises `NotImplementedError`; the
empty-choices path already surfaces `UnexpectedModelBehavior` unwrapped, which 2.3
must preserve).

### Changes

- **2.3** `request()` now brackets **only** the `acompletion` call in
  `try/except Exception as exc:` → `raise ModelAPIError(model_name=…, message=…)
  from exc` (Req 4.1). `.model_dump()` + `build_response` deliberately sit below
  the block so a choiceless-completion `UnexpectedModelBehavior` (Req 3.3) is never
  misclassified as `ModelAPIError` (Req 4.3). Runtime import of `ModelAPIError`
  added.
- **2.4** `request_stream` is an `@asynccontextmanager` raising
  `NotImplementedError("LiteLLM streaming support deferred to future work (model:
  {self.model_name})")` before an unreachable `yield` (kept so it types as a
  generator). Added `asynccontextmanager` runtime import + `AsyncGenerator` /
  `RunContext` / `StreamedResponse` `TYPE_CHECKING` imports.
- **Tests** `test_litellm_error_classification.py` (5 cases: wrap+chain,
  `model_name` attr, broad-except over 5 exc types, post-call mapping error
  unwrapped) and `test_litellm_streaming_deferred.py` (2 cases: raises on entry,
  greppable + model-named message).
- **Lint config** `BLE` added to the ruff `select` list (see finding below); the
  swallowing fail-soft catch in `logging_setup.py:154` now carries `# noqa:
  BLE001`.

### Decisions / learnings

- **`ModelAPIError.model_name` is an attribute, not message text.** First RED→GREEN
  attempt asserted `route in str(error)` — wrong; `model_name` rides the dedicated
  attribute (span `error.class` channel) while the message is free text. Fixed the
  test to assert `excinfo.value.model_name == route`, mirroring the SDK transport's
  convention.
- **BLE001 does not flag a *re-raising* blind except (root-cause of a RUF100).**
  The spec mandated `# noqa: BLE001` on the broad except, but ruff's BLE001 lane
  flags only excepts that *swallow* — a `raise … from exc` except is already
  compliant, so the noqa was intrinsically unused (RUF100 fired with **and**
  without `BLE` enabled). Investigated via `ruff check --select BLE <file>` →
  "All checks passed" on litellm.py. Per the user's "enable BLE now
  (spec-faithful)" decision: `BLE` is now in `select` (closing the lane task 7.2
  references), the re-raising litellm except keeps a plain rationale comment (no
  noqa), and the genuinely swallowing `logging_setup.py:154` catch carries the
  noqa. **Act-phase item**: amend the literal "carries a scoped `# noqa: BLE001`"
  wording in tasks 2.3/7.2.

### Verification gate (evidence)

| Gate | Command | Result |
|------|---------|--------|
| RED | `uv run pytest tests/unit/test_litellm_error_classification.py …streaming_deferred.py -q` | 8 failed, 2 passed (pre-impl) |
| New tests | same command (post-impl) | **10 passed** |
| Full unit suite | `uv run pytest tests/unit -q` | **264 passed** (was 254+; +10 new) |
| Lint | `uv run ruff check .` | All checks passed |
| Format | `uv run ruff format --check .` | 60 files already formatted |
| Typecheck | `uv run pyright` | 0 errors, 0 warnings, 0 informations |

**Status**: **Major 2 (C2 `LiteLLMModel`) complete** — 2.1–2.4 all `[x]`. Next
waves: major 3 (remaining hermetic tests 3.4 FallbackModel-recovery / 3.5
timeout) and major 4 (watsonx `_build_litellm` rewrite, C3).
