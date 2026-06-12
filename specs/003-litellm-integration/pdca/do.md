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

---

## 2026-06-10 — Task 3.1 (C4 construction + observability/output-mode parity tests)

**Scope**: Formalise `test_litellm_construction.py` as the major-3 deliverable
for clause set 3.1 (Req 1.4 / 1.5 / 10.1 / 10.6).

**Method (TDD)**: The 6 cases were already authored as major 2's RED driver
(2.1/2.2) and are GREEN against shipped code. Verified-then-strengthened rather
than re-authored: reviewed each of the task's 5 enumerated clauses for coverage.

### Changes

- **Parity-test strengthening.** `test_response_provider_name_matches_system`
  asserted only `result.provider_name == system`. Added
  `result.model_name == model.model_name == _WATSONX_ROUTE` so the mocked-
  `acompletion` response proves **both** observability span identities
  (`gen_ai.system` *and* `gen_ai.request.model`) match the SDK path — full Req
  1.4 / 10.6 parity, not the provider segment alone. Renamed docstring accordingly.
- No production change; the other 5 clauses (I/O-free `__init__` via detonated
  httpx send hooks, `model_name` route, `system` watsonx/litellm derivation,
  `profile` `supports_json_schema_output` falsy) were already complete.

### Decisions / learnings

- **`build_response` stamps two identities; a parity test must assert both.** The
  call passes `model_name=` and `provider_name=`; asserting only the latter would
  let a regression that drops the route-stamp through. Cheap to close on the same
  mocked response.
- **Toolchain access**: `uv`/`mise` are not on the non-interactive PATH; commands
  must run through `powershell.exe -Command` so the user profile activates the
  mise shims (PowerShell 5.1 emits a harmless chpwd warning; silence with
  `$env:MISE_PWSH_CHPWD_WARNING=0`).

### Verification gate (evidence)

| Gate | Command | Result |
|------|---------|--------|
| Task tests | `uv run pytest tests/unit/test_litellm_construction.py -q` | **6 passed** |
| Full suite | `uv run pytest -q` | **264 passed, 2 skipped** (env-gated integration lanes) |
| Lint | `uv run ruff check tests/unit/test_litellm_construction.py` | All checks passed |
| Format | `uv run ruff format --check …` | 1 file already formatted |
| Typecheck | `uv run pyright tests/unit/test_litellm_construction.py` | 0 errors, 0 warnings, 0 informations |

**Status**: Task 3.1 `[x]`. Remaining in major 3: 3.2, 3.3, 3.4, 3.5, 3.6
(message-mapping, response-mapping, error-classification, timeout, streaming —
test files for several already seeded during major 2).

---

## 2026-06-10 — Task 3.2 (C4 message/tool mapping tests for `request()`)

**Scope**: Formalise `test_litellm_message_mapping.py` as the major-3 deliverable
for clause set 3.2 (Req 10.1): history mapped via `_map_messages`, tools via
`_map_tools`, unsupported part → `NotImplementedError`.

**Method (TDD)**: The 4 cases were already authored as major 2's RED driver and
are GREEN against shipped `request()`. Verified-then-strengthened (same pattern as
3.1), not re-authored.

### Changes

- **Delegation-proof strengthening.** The two mapping cases asserted only literal
  expected dicts — proving *shape*, not that `request()` routes through the shared
  helpers. Added `captured["messages"] == _map_messages(messages)` and
  `captured["tools"] == _map_tools(params)` alongside the literals, so the test
  now pins the **single-implementation reuse** (Req 11): a future inline mapping
  that drifted from the SDK path would fail here, not pass silently. Imported the
  two underscore helpers with the scoped `# pyright: ignore[reportPrivateUsage]`
  cross-module convention.
- No production change. The `None`-tools case and the multimodal →
  `NotImplementedError` case (with `acompletion` detonating via `AssertionError`
  if reached, proving the raise precedes the wrapped call — Req 4.3 fail-loud)
  were already complete.

### Decisions / learnings

- **A "mapped via X" test should assert equivalence to X, not just a literal.** A
  literal-only assertion passes even if the production path re-implements mapping
  inline; the helper-equivalence assertion is what actually proves the delegation
  the task wording ("via `_map_messages`/`_map_tools`") and Req 11 demand.
- **Toolchain access (refines 3.1's note).** `uv`/`mise` shims load only with the
  PowerShell *profile* — the earlier `-NoProfile` attempts failed to find `uv`.
  Ran the gate directly through `.venv\Scripts\python.exe -m {pytest,pyright,ruff}`,
  which is the identical interpreter + deps `uv run` resolves to.

### Verification gate (evidence)

| Gate | Command | Result |
|------|---------|--------|
| Task tests | `.venv\Scripts\python.exe -m pytest tests/unit/test_litellm_message_mapping.py -v` | **4 passed** |
| Full suite | `.venv\Scripts\python.exe -m pytest -q` | **264 passed, 2 skipped** (env-gated integration lanes) |
| Lint | `… -m ruff check tests/unit/test_litellm_message_mapping.py` | All checks passed |
| Format | `… -m ruff format --check …` | 1 file already formatted |
| Typecheck | `… -m pyright tests/unit/test_litellm_message_mapping.py` | 0 errors, 0 warnings, 0 informations |

**Status**: Task 3.2 `[x]`. Remaining in major 3: 3.3, 3.4, 3.5, 3.6
(response-mapping, error-classification, timeout, streaming — files seeded during
major 2, pending formalisation/strengthening).

---

## 2026-06-10 — Task 3.3 (C4 response-mapping tests for `request()`)

**Scope**: Formalise `test_litellm_response_mapping.py` as the major-3 deliverable
for clause set 3.3 (Req 10.1): the `litellm.ModelResponse` → `.model_dump()` →
`build_response` path, finish-reason mapping, empty-choices →
`UnexpectedModelBehavior`, absent-usage → zeroed `RequestUsage`, tool-call args
stay a raw JSON string.

**Method (TDD, verify-then-strengthen)**: The 4 cases were authored as major 2's
RED driver (2.2) and are GREEN against shipped `request()`. Reviewed all 5
enumerated clauses for coverage (same pattern as 3.1/3.2); 4 were complete, the
finish-reason clause was the gap.

### Changes

- **Finish-reason strengthening.** The seeded file only exercised `"stop"`
  (text case) and `"tool_calls"` (tool case) incidentally — the distinctive Req
  3.2 behaviour (absent / unmapped key → `None`) and 3 of 5 map keys were untested
  *through the LiteLLM path*. Added a parametrized `test_finish_reason_mapping`
  covering the full `_FINISH_REASON_MAP` plus three `→ None` branches (absent key,
  explicit `None`, unrecognised key), driven end-to-end through `request()` →
  `.model_dump()` → `build_response` so transport parity with the SDK
  normalisation is pinned, not just the shared helper in isolation.
- No production change. The other 4 clauses (text round-trip via a real
  `litellm.ModelResponse`, Granite double-encoded args surfaced raw, absent-usage
  zeroed, choiceless `UnexpectedModelBehavior` unwrapped) were already complete.

### Decisions / learnings

- **An `_ABSENT` sentinel separates two `None`-yielding branches.** `build_response`
  reaches `None` via *both* a missing `finish_reason` key (`choice.get` → `None`)
  and a falsy/unmapped value (`... if finish_reason_key else None` /
  `_FINISH_REASON_MAP.get(...)`). A sentinel that omits the key entirely vs. an
  explicit `None` param exercises both, so neither branch can regress unnoticed.
- **Coverage already existed on the helper; the value is the *transport* path.**
  `test_openai_mapping_shared.py` (1.5) tests finish-reason on `build_response`
  directly; 3.3's parametrized case re-pins it through `request()` so a
  normalisation drift in the LiteLLM call site (not just the shared helper) would
  be caught — matching the delegation-proof rationale from 3.2.

### Verification gate (evidence)

| Gate | Command | Result |
|------|---------|--------|
| Task tests | `.venv\Scripts\python.exe -m pytest tests/unit/test_litellm_response_mapping.py -v` | **12 passed** (4 seeded + 8 finish-reason params) |
| Full suite | `.venv\Scripts\python.exe -m pytest -q` | **272 passed, 2 skipped** (was 264+2; +8 params; env-gated integration lanes skipped) |
| Lint | `… -m ruff check tests/unit/test_litellm_response_mapping.py` | All checks passed |
| Format | `… -m ruff format --check …` | 1 file already formatted |
| Typecheck | `… -m pyright tests/unit/test_litellm_response_mapping.py` | 0 errors, 0 warnings, 0 informations |

**Status**: Task 3.3 `[x]`. Remaining in major 3: 3.4 (error-classification —
`FallbackModel` recovery), 3.5 (timeout-passthrough), 3.6 (streaming-deferral) —
files seeded during major 2, pending formalisation/strengthening.

---

## 2026-06-10 — Task 3.4 (C4 error-classification tests for `request()`)

**Scope**: Formalise `test_litellm_error_classification.py` as the major-3
deliverable for clause set 3.4 (Req 10.1, 10.2): broad-except wraps all
`acompletion` exceptions as `ModelAPIError`, chaining preserved, **`FallbackModel`
recovers**, and mapping errors are NOT wrapped.

**Method (TDD, verify-then-strengthen)**: The file was seeded as major 2's
RED driver (2.3) with 5 cases. Reviewing against the task's 4 clauses, 3 were
GREEN; the `FallbackModel`-recovery clause (Req 10.2) was the gap flagged in
major 2's Implementation Notes. RED for the new test = the assertion didn't exist.

### Changes

- **Added `test_litellm_failure_recovered_by_fallback_model`** (Req 10.2). The
  unit-level tests prove `acompletion` failures *become* `ModelAPIError`; this
  proves that classification is *actionable* end-to-end. A genuine `LiteLLMModel`
  (not a `FunctionModel` double) with `acompletion` monkeypatched to raise is
  seated first in `FallbackModel(litellm_fail, recovering)` and driven via
  `Agent.run_sync`; the recovering member's output being returned *is* the proof —
  the failure became a `ModelAPIError`, hit the default
  `fallback_on=(ModelAPIError,)`, and never escaped the chain.
- Added a local `_recovering_function_model` helper (parametric `text`), kept out
  of `tests.support.model_fakes` for the same single-caller reasoning recorded in
  `test_watsonx_fallback_integration.py` / `test_fallback_failover.py`.
- No production change. The other 3 clauses (broad-except wraps every exception
  type, `__cause__` chaining + model-name stamping, post-call
  `UnexpectedModelBehavior` unwrapped — Req 4.3) were already GREEN.

### Decisions / learnings

- **The recovery test uses a real `LiteLLMModel`, not a double.** Mirroring
  `test_watsonx_fallback_integration.py`'s shape, but the failing member is the
  actual transport (with only `acompletion` mocked) — so the test exercises
  *this transport's own* broad-except → `ModelAPIError` wrapping, closing the
  unit→integration loop. A `FunctionModel` raising `ModelAPIError` would only
  re-test `FallbackModel`, not the litellm wrapping under test.
- **`run_sync` over an `async` request call.** The wrapping unit tests await
  `request()` directly; the recovery test drives through `Agent.run_sync` because
  `FallbackModel`'s recovery semantics live in the agent run loop, not in a bare
  `request()`. Both halves (mechanism + actionability) are now pinned.

### Verification gate (evidence)

| Gate | Command | Result |
|------|---------|--------|
| Task tests | `mise run test -- tests/unit/test_litellm_error_classification.py -q` | **9 passed** (4 seeded + 5 params + 1 recovery; net +1 file-level vs seed) |
| Full suite | `mise run test` (`uv run pytest`) | **273 passed, 2 skipped** (was 272+2; +1 recovery test; env-gated integration lanes skipped) |
| Lint | `mise run lint` (`uv run ruff check .`) | All checks passed |
| Typecheck | `mise run typecheck` (`uv run pyright`) | 0 errors, 0 warnings, 0 informations |

**Status**: Task 3.4 `[x]`. Remaining in major 3: 3.5 (timeout-passthrough),
3.6 (streaming-deferral) — files seeded during major 2, pending
formalisation/strengthening.

---

## 2026-06-10 — Task 3.5 (C4 timeout-passthrough tests for `request()`)

**Task 3.5 (P)** — Timeout-passthrough tests: both connect and read timeouts reach
`acompletion` as `httpx.Timeout(read, connect=connect)` (Req 10.1, supporting 5.1).

**Method (TDD)**: New file `tests/unit/test_litellm_timeout_config.py` (it did not
exist — RED = no assertion pinned the timeout shaping). The production wiring landed
in Task 2.2 (`litellm.py:235` builds `httpx.Timeout(self._timeout_read,
connect=self._timeout_connect)` and passes it as `timeout=`), so these tests pin
existing behaviour against regression rather than driving new code — the proper
shape for a `(P)` test-only sub-task that depends on a completed major 2.

### Changes

- **`test_timeout_passed_as_httpx_timeout_instance`** — the `timeout` kwarg reaches
  `acompletion` as a structured `httpx.Timeout`, asserting both
  `isinstance(httpx.Timeout)` and `not isinstance(float)`. A bare single float would
  silently collapse the connect and read phases into one budget, dropping the
  distinct connect timeout; this guard fails loud on that regression.
- **`test_both_connect_and_read_phases_reach_acompletion`** (parametrized, 3 cases)
  — `.connect`/`.read` map verbatim from construction values. Distinct custom
  (7/300) catches a single-float collapse and a connect/read swap; the project
  defaults (30/120) and an equal-phase case (15/15) guard the boundaries.
- **`test_timeout_shape_matches_sdk_read_seeds_overall_default`** — parity pin: the
  read value seeds `write`/`pool` (the positional-default semantics of
  `httpx.Timeout(read, connect=connect)`), proving the LiteLLM path matches
  `WatsonxSDKModel._build_client`'s shaping rather than an equivalent
  `Timeout(connect=…, read=…)` spelling that would leave write/pool unset.
- No production change. Reused the sibling files' `_capturing` / `_text_response`
  kwarg-capture pattern (a real `litellm.ModelResponse` success so `request()`'s
  post-call `.model_dump()` → `build_response` path runs unchanged).

### Decisions / learnings

- **Why pin write/pool, not just connect/read.** Req 5.1's literal wording is "both
  phases reach `acompletion`", which `.connect`/`.read` alone satisfy. The
  write/pool assertion is added deliberately: it's the only thing that distinguishes
  the *exact documented shape* (`httpx.Timeout(read, connect=connect)`, where read
  is the positional default) from a functionally-similar but non-parity spelling.
  Both transports must construct timeouts identically (research.md / SDK
  `_build_client`), so the shape — not just the two values — is the contract.
- **`asyncio_mode = "auto"`** — async tests need no decorator (matches all sibling
  `test_litellm_*` files).

### Verification gate (evidence)

| Gate | Command | Result |
|------|---------|--------|
| Task tests | `uv run pytest tests/unit/test_litellm_timeout_config.py -v` | **5 passed** (1 + 3 params + 1) |
| Full suite | `uv run pytest -q` | **278 passed, 2 skipped** (was 273+2 at 3.4; +5 timeout cases; env-gated integration lanes skipped) |
| Lint | `uv run ruff check` (new file) | All checks passed |
| Format | `uv run ruff format --check` (new file) | 1 file already formatted |
| Typecheck | `uv run pyright` (new file) | 0 errors, 0 warnings, 0 informations |

> Note: `uv`/`mise` resolve only in a profile-loaded PowerShell on this host;
> commands were run via `powershell.exe -Command "uv run …"`. The `--cov` ratchet
> remains owned by Task 7.1 (default `pytest` is the clean lane — see Task 1
> Implementation Notes re: the beartype-claw `--cov` circular import).

**Status**: Task 3.5 `[x]`. Remaining in major 3: 3.6 (streaming-deferral) —
file seeded during major 2 (`test_litellm_streaming_deferred.py`, 2 cases),
pending formalisation/strengthening.

---

## 2026-06-10 — Task 3.6 (C4 streaming-deferral tests) — Major 3 complete

**Scope**: Formalise/strengthen `test_litellm_streaming_deferred.py` so it fully
covers the task's four enumerated clauses. The `request_stream` override (Task
2.4) was already complete; this is a test-only `(P)` task, so the behaviour was
driven RED-first during major 2 — the work here is closing the one clause the
seeded cases covered only implicitly.

**Method (TDD, strengthening)**: Captured GREEN baseline (2 cases pass) against
the existing 2.4 override, then added a third case for the uncovered clause and
re-ran. No production change.

### Changes

- The 2 seeded cases covered three clauses: raises `NotImplementedError`,
  greppable `"streaming support deferred"` message, model route named in the
  message. The fourth — **"before any yield"** — was only implicit (a
  `pragma: no cover` on the `async with` body).
- Added `test_request_stream_raises_before_any_yield_without_downgrading`,
  pinning it two ways:
  - **(a) Raise precedes the yield.** A `body_ran` sentinel asserted `False`
    proves `@asynccontextmanager` raises on `__aenter__` (the generator raises
    before reaching its `yield`), not from inside the managed block.
  - **(b) No silent downgrade (Req 8.2).** `litellm.acompletion` monkeypatched
    to detonate (`AssertionError`); reaching it fails the test, proving the
    override refuses streaming outright rather than quietly servicing it via the
    non-streaming transport path — the regression a future "just call
    `request()`" shortcut would introduce.

### Decisions / learnings

- **Detonating `acompletion` is the load-bearing guard.** `request_stream` does
  not even import `litellm` today (it raises first), so the monkeypatch can only
  ever be hit by a future regression — which is exactly the point: it converts
  "never silently downgrades" (Req 8.2) from prose into an enforced invariant.
- **Function-local `import litellm`** in the test mirrors the production
  transport's own function-local import (no `PLC0415` lane enabled), keeping the
  detonation target consistent with how `request()` resolves the module.

### Verification gate (evidence)

| Gate | Command | Result |
|------|---------|--------|
| Task tests | `uv run pytest tests/unit/test_litellm_streaming_deferred.py -q` | **3 passed** (2 seeded + 1 strengthening) |
| Regression | `uv run pytest tests/unit -k litellm -q` | **54 passed, 225 deselected** |
| Lint | `uv run ruff check` (changed file) | All checks passed |
| Format | `uv run ruff format --check` (changed file) | 1 file already formatted |
| Typecheck | `uv run pyright` (changed file) | 0 errors, 0 warnings, 0 informations |

> Commands run via `pwsh -Command "uv run …"` (uv/mise resolve only in a
> profile-loaded PowerShell on this host). Full-suite `--cov` ratchet remains
> owned by Task 7.1.

**Status**: Task 3.6 `[x]`. **Major 3 complete** (3.1–3.6 all `[x]`). Next wave:
major 4 (rewrite watsonx `_build_litellm` wrapper) — already unblocked (depends
only on major 2).

---

## 2026-06-10 — Tasks 4.1–4.3 + 5.1–5.2 (C3 `_build_litellm` rewrite + wrapper tests) — majors 4 & 5 complete

**Scope**: Rewrite the watsonx `_build_litellm` builder to construct the new
`LiteLLMModel` (4.1), preserving the optional-`litellm` import guard (4.2) and
reconciling `WATSONX_PROJECT_ID` into `os.environ` for LiteLLM's watsonx path
(4.3); rewrite `test_watsonx_litellm_construction.py` to assert the new
construction (5.1) and verify the unchanged-behavior suites stay green (5.2).

**Scope decision (user-approved)**: invocation was `/sdd-impl … Task4.1`. The
production rewrite breaks the existing construction test (it asserts the removed
`OpenAIChatModel` path), and that test's faithful replacement (5.1) asserts the
4.3 env reconciliation and the 4.2 guard alongside 4.1 — so the green
verification gate is **inseparable** from the whole `_build_litellm` rewrite +
test rewrite. Asked the user; chosen scope = "4.1 + 5.1 together (keep suite
green)". Implemented the full coupled unit (4.1+4.2+4.3+5.1+5.2) and marked all
five, since each is genuinely complete and verified.

**Method (TDD)**: Rewrote the test file first → RED (7 failed / 4 passed against
the `OpenAIChatModel`-returning production: the 4 passes were the unchanged
import-guard, route-prefix, secret-leak and `None`-cred-guard cases). Rewrote
`_build_litellm` → GREEN (11 passed).

### Changes

- **4.1** `_build_litellm` body fully replaced: removed
  `OpenAIChatModel`/`LiteLLMProvider` + the custom `http_client`; now returns
  `LiteLLMModel(model_name=f"watsonx/{model_id}", api_key=apikey.get_secret_value(),
  api_base=watsonx_url, timeout_connect=…, timeout_read=…)`. Timeout *shaping*
  lives in `LiteLLMModel.request` (Task 2.2), so the builder passes the two `int`
  phases through unaltered. `LiteLLMModel` imported function-locally (after the
  guard). Added module-level `import os`.
- **4.2** Import guard preserved verbatim (`try: import litellm / except
  ImportError: raise ValueError` naming the package + install command).
- **4.3** Added `os.environ["WATSONX_PROJECT_ID"] = settings.watsonx_project_id`
  (ADR-3). `None` → `TypeError` + `# pragma: no cover` (defensive; boot
  credential gate already rejects a missing project id). Kept the env write —
  the live lane (Task 6) has not yet validated an `acompletion(project_id=...)`
  kwarg alternative.
- **5.1** Retargeted `test_watsonx_litellm_construction.py` to `LiteLLMModel`
  construction (11 cases). The 5 old RESPX request-path tests were **removed**,
  not ported — they drove the OpenAI adapter's `httpx` POST to
  `/chat/completions`, a path that no longer exists; the litellm request path is
  covered hermetically by the `test_litellm_*` (mocked-`acompletion`) suite.
- **5.2** SDK / factory-dispatch / fallback suites pass unmodified.

### Decisions / learnings

- **The project-ID env test must prove the *builder* writes it, not the
  fixture.** `watsonx_settings_factory` seats `WATSONX_PROJECT_ID` via
  `monkeypatch.setenv` (that is how `Settings` reads it). A naive
  `assert os.environ["WATSONX_PROJECT_ID"] == …` would pass even without 4.3,
  masked by the fixture. The test captures `settings` first, then
  `monkeypatch.delenv`s the var, then builds — so only the builder's reconciliation
  can satisfy the assertion. `monkeypatch` still owns the key (from the factory's
  `setenv`), so its teardown restores it and the process-global write does not leak.
- **Factory dispatch needed no edit.** `test_factory_dispatch.py` asserts only the
  `Model` ABC for the litellm branch (by design, so the concrete Pydantic AI class
  can evolve), so the `OpenAIChatModel → LiteLLMModel` swap was transparent to it —
  only `test_watsonx_litellm_construction.py` (5.1's boundary) referenced the
  concrete removed class.
- **Construction asserts read private attrs.** `LiteLLMModel` exposes no public
  accessors for `api_key`/`api_base`/timeouts, so the construction-level assertions
  use `model._api_key` etc. with the per-line `# pyright:
  ignore[reportPrivateUsage]` cross-module convention.

### Verification gate (evidence)

| Gate | Command | Result |
|------|---------|--------|
| RED | `mise run test -- tests/unit/test_watsonx_litellm_construction.py -q` (pre-impl) | 7 failed, 4 passed |
| Task tests | same command (post-impl) | **11 passed** |
| 5.2 named suites | `mise run test -- …sdk_construction …factory_dispatch …fallback_integration …fallback_failover -q` | **53 passed** |
| Full suite | `mise run test` (`uv run pytest`) | **277 passed, 2 skipped** (env-gated integration lanes) |
| Lint | `mise run lint` (`uv run ruff check .`) | All checks passed |
| Format | `mise run format` (`uv run ruff format --check .`) | 61 files already formatted |
| Typecheck | `mise run typecheck` (`uv run pyright`) | 0 errors, 0 warnings, 0 informations |

> `uv`/`mise` resolve only in a profile-loaded PowerShell on this host; commands
> ran via `powershell.exe … '. $PROFILE; mise run …'`. The PS5.1 chpwd warning and
> mise's stderr task-echo are harmless. The `--cov` ratchet remains owned by Task
> 7.1 (default `pytest` is the clean lane — beartype-claw `--cov` interaction).

**Status**: **Majors 4 & 5 complete** — 4.1–4.3, 5.1–5.2 all `[x]`. Remaining:
major 6 (opt-in live `litellm` lane) and major 7 (quality gates: coverage ratchet,
security lane, integration). Act item carried from major 2 still open: amend the
literal "carries a scoped `# noqa: BLE001`" wording in tasks 2.3/7.2.

---

## Task 6 — Opt-in live integration lane for the litellm transport (C4)

**Boundary**: `tests/integration/test_watsonx_chat_e2e.py` (single file, test-only).
**Depends**: 4 (builder rewrite, done). No production code touched — the litellm
transport (majors 2–4) is already implemented; major 6 is pure test authoring.

### What changed

- **Parametrized the existing `/chat` E2E test over `["sdk", "litellm"]`**,
  forcing `WATSONX_TRANSPORT` per param so one `RUN_INTEGRATION_WATSONX=1` run
  exercises both transports end-to-end through the FastAPI route (Task 7.4).
- **Added `test_litellm_lane_parity_env_routing_and_single_upstream_attempt`** —
  drives the agent directly (preserving an in-memory `TestExporter`) and asserts
  the litellm-only contracts: `WATSONX_PROJECT_ID` env routing (ADR-3),
  `gen_ai.system == "watsonx"` + `gen_ai.request.model == "watsonx/<id>"` parity
  (Req 1.4/10.6), response transformation, and `num_retries=0` honored.

### Design decisions (trial reasoning)

- **`num_retries=0` proof via per-request POST equality.** The pydantic-ai `chat`
  span is created once per `request()` regardless of LiteLLM internal retries, so
  it cannot prove retry-suppression. Counting upstream httpx POSTs (via
  `instrument_httpx`) to the inference host and asserting
  `inference_posts == len(chat_spans)` is the robust signal: it holds across
  multi-turn tool-calling runs and catches both a silent retry (count > spans) and
  an instrumentation miss (count 0). Filtered to the `WATSONX_URL` host to exclude
  the IAM token POST.
- **WATSONX_PROJECT_ID env routing** asserted by `delenv` → build → assert
  `os.environ` set by the builder — directly exercises the `.env`-loaded-but-not-
  exported silent-404 class ADR-3 exists to kill.

### Verification gate (evidence)

| Gate | Command | Result |
|------|---------|--------|
| Collect + skip | `uv run pytest tests/integration/test_watsonx_chat_e2e.py -v` | **3 skipped** (gate off — hermetic) |
| Full suite | `uv run pytest` | **277 passed, 4 skipped** |
| Lint | `uv run ruff check tests/integration/test_watsonx_chat_e2e.py` | All checks passed |
| Format | `uv run ruff format --check …` | already formatted |
| Typecheck | `uv run pyright tests/integration/test_watsonx_chat_e2e.py` | 0 errors, 0 warnings |

> The **live** assertions (Req 10.3 — real watsonx round-trip) cannot run in the
> hermetic gate without operator creds; they are validated under Task 7.4
> (`[ ]*`, optional) with `RUN_INTEGRATION_WATSONX=1`. The lane is authored and
> collection-clean; green-against-live is the operator's remaining step.

**Status**: **Major 6 complete.** Remaining: major 7 (7.1 coverage ratchet, 7.2
pyright/ruff S+BLE lanes, 7.3 security lane, 7.4 optional live integration run).
Carried act item: amend the literal "carries a scoped `# noqa: BLE001`" wording
in tasks 2.3/7.2 (re-raising except is BLE-compliant).

---

## 2026-06-10 — Task 7.1 (C4 coverage ratchet gate)

**Scope**: Run the full hermetic suite under coverage and confirm the LiteLLM
path meets/exceeds the 98% `fail_under` ratchet (Req 10.4). This is a
verification gate — no RED→GREEN; the coverage run *is* the test.

### Result

Full hermetic suite with `--cov` (no network): **277 passed / 4 skipped**, total
**98.83% ≥ 98%** → "Required test coverage of 98.0% reached." The LiteLLM path is
**fully covered**: `litellm.py` 100% (46 stmts), `_openai_mapping.py` 100% (85
stmts / 44 branches). Residual misses sit only in out-of-boundary provider stubs
(`ollama.py` 64-69, `factory.py` 113-117, `deps.py` 76) — already above ratchet.

### Decisions / learnings

- **The beartype-claw `--cov` circular import (flagged in the major-1 notes) no
  longer reproduces.** Both `.venv/Scripts/python -m pytest --cov` and the
  canonical `uv run pytest --cov` run clean through conftest's FastAPI
  `TestClient` import. The interaction was resolved by an env/dependency update
  since 2026-06-09; the "avoid/repair" action item is closed by observation — no
  conftest surgery required.
- **Canonical invocation established (the deliverable 7.1 owns).** Added
  `[tasks.cov]` to `mise.toml` (`uv run pytest --cov --cov-report=term-missing`).
  Bare `--cov` measures the `[tool.coverage.run] source` declared in
  pyproject.toml, so the ratchet stays single-sourced and the gate flows through
  `mise.toml` per the steering "all quality gates flow through mise.toml" rule.
- **Why no separate `--cov` in `addopts`.** Keeping `--cov` off the default
  `pytest` addopts preserves the fast hermetic `mise run test` lane; the
  coverage gate is the explicit `mise run cov` lane. This also sidesteps any
  future re-emergence of the import-hook interaction, which the major-1 notes
  attributed specifically to forcing coverage instrumentation at startup.

### Verification gate (evidence)

| Gate | Command | Result |
|------|---------|--------|
| Coverage gate | `mise run cov` (`uv run pytest --cov --cov-report=term-missing`) | **277 passed, 4 skipped**; total **98.83%**; `litellm.py` 100%, `_openai_mapping.py` 100%; "Required test coverage of 98.0% reached" |
| Cross-check | `.venv\Scripts\python.exe -m pytest --cov --cov-report=term-missing` | identical — 98.83%, no beartype-claw error |

**Status**: Task 7.1 `[x]`. Remaining in major 7: 7.2 (pyright strict + ruff
`S`/`BLE`), 7.3 (security lane: gitleaks/pip-audit + `test_no_hardcoded_model_ids`),
7.4 (`[ ]*` optional live integration). Carried act item still open: amend the
literal "carries a scoped `# noqa: BLE001`" wording in tasks 2.3/7.2.

---

## 2026-06-10 — Task 7.2 (C4 pyright strict + ruff S/BLE quality gate)

**Scope**: Run pyright `strict` and ruff (incl. the `S`/`BLE` lanes) across the
three boundary files (`_openai_mapping.py`, `litellm.py`, `watsonx.py`) and the
whole project, fix any issue, and resolve the carried major-2 action item on the
broad-except `# noqa: BLE001` wording (Req 10.4). Verification gate — no
RED→GREEN; the gate run *is* the test.

### Result

All gates clean, no production code change needed:

- **ruff (full, incl. `S`/`BLE`)** — `All checks passed!`
- **pyright strict** — `0 errors, 0 warnings, 0 informations`
- **ruff format --check** — `61 files already formatted`
- **`S`/`BLE` lanes on the 3 boundary files** (`ruff check --select S,BLE`) —
  `All checks passed!`

### Changes (spec-doc only)

- **Closed the carried act item.** Amended the literal "carries a scoped
  `# noqa: BLE001`" wording in **task 2.3** and **task 7.2** to state the
  user-approved finding: the litellm broad-except **re-raises** (`raise ... from
  exc`), so it is already BLE-compliant and needs **no** noqa — ruff's BLE001
  flags only *swallowing* excepts, and a noqa there would be unused (`RUF100`).
  The breadth rationale rides a plain block comment ([litellm.py:236-246](../../../src/pydantic_ai_sandbox/llm/providers/litellm.py#L236)).
- No source edit: the `BLE` lane was already in the ruff `select` (added in major
  2), the swallowing fail-soft catch in `logging_setup.py:154` already carries its
  `# noqa: BLE001`, and the litellm except already carries the plain rationale
  comment with no noqa.

### Decisions / learnings

- **The spec premise was the only thing left to fix, not the code.** Major 2 had
  already corrected the implementation (enable `BLE`, no noqa on the re-raising
  except, noqa on the genuinely-swallowing `logging_setup` catch). 7.2's residual
  work was therefore purely reconciling the task wording with the shipped reality
  so the spec no longer mandates a noqa that ruff would reject.

### Verification gate (evidence)

| Gate | Command | Result |
|------|---------|--------|
| Lint (S/BLE incl.) | `mise run lint` (`uv run ruff check .`) | **All checks passed!** |
| Typecheck | `mise run typecheck` (`uv run pyright`) | **0 errors, 0 warnings, 0 informations** |
| Format | `mise run format` (`uv run ruff format --check .`) | **61 files already formatted** |
| S/BLE targeted | `uv run ruff check --select S,BLE` (3 boundary files) | **All checks passed!** |
| Full suite | `mise run test` (`uv run pytest`) | **277 passed, 4 skipped** (env-gated integration lanes) |

> `uv`/`mise` resolve only in a profile-loaded PowerShell on this host; commands
> ran via `powershell.exe -Command ". $PROFILE; mise run …"`.

**Status**: Task 7.2 `[x]`. **Carried act item closed** (2.3/7.2 noqa wording
amended). Remaining in major 7: 7.3 (security lane: gitleaks/pip-audit +
`test_no_hardcoded_model_ids`), 7.4 (`[ ]*` optional live integration run).

---

## 2026-06-10 — Task 7.3 (C4 security lane gate)

**Scope**: Run the security lane — gitleaks (secret scan, Req 9.3), pip-audit
(dependency CVE scan), and `test_no_hardcoded_model_ids.py` — confirming no
credentials in logs (Req 7.5) and no model-ID literals in `src/` (Req 1.5,
Req 10.4). Verification gate — no RED→GREEN; the gate run *is* the test, and no
production code was touched.

### Result

All three gates clean:

- **`test_no_hardcoded_model_ids.py`** — **2 passed**
  (`test_no_hardcoded_model_ids_in_src`: no banned literal across `src/**/*.py`;
  `test_gitignore_excludes_dotenv`: `.env` present in `.gitignore`, Req 9.6).
- **gitleaks** (`pre-commit run gitleaks --all-files`) — **Passed**
  ("Detect hardcoded secrets … Passed"). This is the suite-level "no credentials
  in logs" scan (Req 7.5) that complements task 5.1's per-construction
  secret-leak assertion (unwrapped key absent from `LiteLLMModel` `repr`/`str`).
- **pip-audit** (`uv run pip-audit`) — **No known vulnerabilities found**. The
  only entry is a *skip* for the local `pydantic-ai-sandbox` (0.1.0) package —
  "Dependency not found on PyPI" — which is expected (the project under test is
  unpublished) and benign, not a vulnerability.

### Decisions / learnings

- **gitleaks IS the "no credentials in logs" gate.** Task 5.1's note explicitly
  scopes the per-model secret-leak check (key not in `repr`/`str`) to the unit
  level and defers suite-level log scanning to "the gitleaks lane in task 7.3" —
  so 7.3's gitleaks pass closes the Req 7.5 log-credential clause. The litellm
  transport's `_api_key`/`api_base` never surface in the constructed model's
  string forms (5.1) and no secret-shaped string was committed (gitleaks).
- **pip-audit's lone "skip" is not a failure.** The unpublished local package
  cannot be resolved on PyPI; pip-audit reports it as a skip, not a finding, and
  every resolvable dependency audited clean. Treating the skip as a pass is
  correct — there is no advisory to action.
- **Two model-ID guards, one source of truth.** The runtime test's
  `FORBIDDEN_MODEL_ID_LITERALS` is canonical; the `forbid-hardcoded-model-ids`
  pygrep pre-commit hook is a re-serialised mirror (kept in lockstep by the
  inline comment). The litellm work added no model-ID literal to `src/` — routes
  are env-derived (`watsonx/{settings.watsonx_model_id}`), so the guard stays
  green for the new transport.

### Verification gate (evidence)

| Gate | Command | Result |
|------|---------|--------|
| Model-ID guard | `uv run pytest tests/unit/test_no_hardcoded_model_ids.py -v` | **2 passed** |
| Secret scan | `uv run pre-commit run gitleaks --all-files` | **Passed** ("Detect hardcoded secrets … Passed") |
| CVE scan | `uv run pip-audit` | **No known vulnerabilities found** (lone skip: unpublished local pkg, benign) |

> `uv`/`mise` resolve only in a profile-loaded PowerShell on this host; commands
> ran via `powershell.exe -Command ". $PROFILE; uv run …"`.

**Status**: Task 7.3 `[x]`. Remaining in major 7: **7.4 only** (`[ ]*` optional
live integration run — `RUN_INTEGRATION_WATSONX=1`, operator-gated with creds).
All hermetic quality gates (7.1 coverage, 7.2 pyright/ruff S+BLE, 7.3 security)
are now complete; the feature's non-optional task set is closed.

---

## 2026-06-10 — Task 7.4 (`[ ]*` opt-in live integration run) — BLOCKED on watsonx provisioning

**Scope**: Run the opt-in integration lane (`RUN_INTEGRATION_WATSONX=1`) and
confirm both `sdk` and `litellm` transports work end-to-end against a live
watsonx.ai backend (Req 10.3). Verification-only task — no RED→GREEN; the live
run *is* the test. The lane itself was authored and collection-clean in major 6.

### Result — environment not provisioned for the watsonx live lane

The hermetic baseline is clean, but the live lane cannot be exercised in this
environment: it lacks watsonx credentials. `.env` here targets the local **ollama**
dev provider (`LLM_PROVIDER=ollama`), not watsonx, and carries no `WATSONX_*` /
`LLM_PROVIDER=watsonx`. With the gate on, `get_settings()` raised a
`ValidationError` *before* any network call:

```
Value error, OLLAMA_MODEL_NAME is required when LLM_PROVIDER=ollama;
set the env var or switch LLM_PROVIDER.
```

This is **not a defect in the LiteLLM transport** (majors 1–6, all hermetic gates
green) — it is a credential-provisioning gap. Crucially, the lane behaved exactly
as its fail-not-skip contract specifies: a gated run with unusable creds **FAILS
(errors), it does not skip** — so a broken or unprovisioned live lane can never
masquerade as green. This is the designed safety posture, observed working.

### Decisions / learnings

- **7.4 stays `[ ]*` unchecked.** Marking it `[x]` would require live-green
  evidence (a real watsonx round-trip on both transports); none can be produced
  here, and a green claim without the captured passing result is forbidden. The
  task is optional and operator-gated by design — the do.md / tasks.md notes from
  majors 6/7 already frame it as "the operator's remaining step".
- **The fail-not-skip posture is verified, not just asserted.** The lane's
  docstring promises "missing creds surface as a test ERROR, not a skip"; this run
  is the live demonstration of that — the `ValidationError` propagated as 3 FAILED,
  not 3 SKIPPED.
- **Operator runbook to close 7.4.** On a host with real watsonx access, set
  `LLM_PROVIDER=watsonx` + `WATSONX_URL` / `WATSONX_APIKEY` / `WATSONX_PROJECT_ID`
  / `WATSONX_MODEL_ID` (and optionally `WATSONX_TRANSPORT` — the lane forces both
  values per-param regardless), then run `RUN_INTEGRATION_WATSONX=1 uv run pytest
  tests/integration/test_watsonx_chat_e2e.py -v`. Expect 3 passed. Watch the
  litellm lane specifically against the **known prior 404** (the `api_base`/route
  bug feature 003 exists to fix — see project memory) and the `num_retries=0`
  single-upstream-POST assertion.

### Verification gate (evidence)

| Gate | Command | Result |
|------|---------|--------|
| Hermetic baseline | `.venv\Scripts\python.exe -m pytest tests/integration/test_watsonx_chat_e2e.py -v` | **3 skipped** (gate off — network-free) |
| Live lane (gated) | `RUN_INTEGRATION_WATSONX=1 .venv\Scripts\python.exe -m pytest tests/integration/test_watsonx_chat_e2e.py -v` | **3 failed** — `ValidationError`: env is `LLM_PROVIDER=ollama`, no watsonx creds (fail-not-skip working as designed; **not** a transport defect) |

**Status**: Task 7.4 **remains `[ ]*` (unchecked) — BLOCKED on watsonx
credentials in this environment.** No production code changed. The lane is
authored, collection-clean, and its fail-not-skip safety posture is verified
live. Closing 7.4 requires an operator run on a watsonx-provisioned host (runbook
above). All non-optional tasks (1–7.3) remain complete.

> **SUPERSEDED below (same day).** The operator confirmed a watsonx-provisioned
> `.env` was in place; the block above was a *loading* gap, not a provisioning
> one — see the next entry, which executes the live run and closes 7.4.

---

## 2026-06-10 — Task 7.4 (live run executed) — `[x]*` CLOSED

**Resolution of the block above**: `Settings` sets `env_file=None`
([config.py:83](../../../src/pydantic_ai_sandbox/config.py#L83)) — it reads only
the *process* environment, never auto-loading `.env` (the app loads `.env` via
uvicorn `--env-file`; pytest does not). The earlier gated run saw
`LLM_PROVIDER=ollama` (the field default) because the watsonx `.env` was never
exported into the env. Sourcing it first — `set -a; source <(tr -d '\r' < .env);
set +a` (the `tr` strips Windows CRLF) — then running the gate is the operator
recipe the project memory already records.

### Live result — both transports work E2E; 404 is fixed

With real `us-south` creds + `WATSONX_MODEL_ID=meta-llama/llama-4-maverick-17b-128e-instruct-fp8`
(the structured-output-capable model; granite-4 double-encodes — project memory):

- **`...returns_structured_chat_response[sdk]` → PASS.** SDK `/chat` E2E, 200 +
  valid `ChatResponse`, `search_kb` tool round-trip.
- **`...returns_structured_chat_response[litellm]` → PASS.** ***The headline:***
  the LiteLLM transport routes through the full FastAPI `/chat` chain to live
  watsonx and returns a valid `ChatResponse`. **Feature 002's `litellm` 404
  (`OpenAIChatModel`/`LiteLLMProvider` POSTing to `/chat/completions`) is fixed**
  by the `LiteLLMModel`/`acompletion` rewrite — confirmed against the real
  backend, not just hermetically.
- **`test_litellm_lane_parity_env_routing_and_observability` → PASS** (renamed,
  see below). `WATSONX_PROJECT_ID` env routing (ADR-3), `gen_ai.system ==
  "watsonx"` + `gen_ai.request.model == "watsonx/<id>"` parity, and a coercible
  non-empty `ChatResponse` all hold live.

### The `num_retries=0` assertion — a real Task 7.4 finding (down-scoped, user-approved)

The original litellm-only test ended with
`assert inference_posts == len(chat_spans)` (one upstream POST per chat span).
The live run exposed it as **doubly flawed**:

1. **The inference POST is invisible to `instrument_httpx`.** A span diagnostic
   showed LiteLLM issues the watsonx chat completion over its own *aiohttp*
   transport; only the auxiliary **IAM-token** POST (`iam.cloud.ibm.com`) rides
   the `httpx` client `instrument_httpx` patches. The inference attempt to
   `us-south.ml.cloud.ibm.com` never surfaces as an httpx span → count `0`.
2. **A successful request cannot reveal a retry budget anyway.** Retries fire
   only on a *retryable failure*; on the happy path there is exactly one attempt
   whether `num_retries` is `0` or `N`. So even with perfect instrumentation, the
   happy-path count proves nothing about suppression.

**Decision (user-approved: "正直にダウンスコープ").** Removed the unprovable
happy-path POST-count assertion (and its `_inference_post_count` helper +
`urlsplit` import); kept the env-routing / observability-parity / response
assertions (all PASS live). Renamed the test
`..._single_upstream_attempt` → `..._env_routing_and_observability` to match the
honest scope. `num_retries=0` stays pinned **hermetically** by the
kwarg-passthrough unit test (`test_litellm_timeout_config` / error-classification
suite assert `acompletion` receives `num_retries=0`). **Future work**: a genuine
suppression proof needs a forced-failure lane — inject a retryable error and
assert exactly one LiteLLM attempt via a LiteLLM callback (transport-agnostic,
immune to the aiohttp/httpx split). Documented in the module + test docstrings.

### Verification gate (evidence)

| Gate | Command | Result |
|------|---------|--------|
| Live lane (gated) | `set -a; source <(tr -d '\r' < .env); set +a; RUN_INTEGRATION_WATSONX=1 .venv\Scripts\python.exe -m pytest tests/integration/test_watsonx_chat_e2e.py -v` | **3 passed** (sdk E2E, litellm E2E, litellm parity) |
| Full hermetic suite | `.venv\Scripts\python.exe -m pytest -q` | **277 passed, 4 skipped** (integration lanes skip without the gate) |
| Lint | `ruff check .` | All checks passed |
| Format | `ruff format --check .` | 61 files already formatted |
| Typecheck | `pyright` | 0 errors, 0 warnings, 0 informations |

**Status**: Task 7.4 **`[x]*` CLOSED.** Both transports verified live; the
litellm 404 is fixed against the real backend. The only production-relevant
finding (the unprovable `num_retries=0` happy-path assertion) was down-scoped
honestly with the suppression proof deferred to a forced-failure lane. **All
of feature 003's tasks (majors 1–7) are now complete.** No production code
changed in 7.4 — test-file boundary only (`test_watsonx_chat_e2e.py`).
