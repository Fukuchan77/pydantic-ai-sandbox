# PDCA — Do Phase: 002-watsonx-provider

Continuous implementation log. Newest entries at the bottom of each task.

---

## Task 1 — Dependencies, lockfile & coverage ratchet

**Date:** 2026-06-08 · **Status:** ✅ Done · **Boundary:** `pyproject.toml`, `.github/dependabot.yml`

### 1.1 — Dependency bump + optional litellm + coverage ratchet

**TDD framing (config task):** the verifiable assertion is the SDK import.

- **RED** — with the locked `ibm-watsonx-ai==1.5.12`:
  ```
  from ibm_watsonx_ai.foundation_models import ModelInference
  TypeError: object.__init__() takes exactly one argument (the instance to initialize)
    at ibm_watsonx_ai/utils/utils.py:1191  (StrEnum member construction, py3.14.5)
  ```
  Reproduces ADR-1 exactly.
- **GREEN** — after bumping to `>=1.5.13` and `uv sync --extra litellm`:
  ```
  version: 1.5.13
  ModelInference import: OK
  python: 3.14.5
  ```
- Edits to `pyproject.toml`: `ibm-watsonx-ai>=1.5.13` (with ADR-1 comment);
  new `[project.optional-dependencies] litellm = ["litellm"]`;
  `[tool.coverage.report] fail_under` 93 → 98.
- `uv.lock` regenerated: `ibm-watsonx-ai 1.5.13`, `litellm 1.89.0rc1` locked.

### 1.2 — Dependabot supply-chain-watch registration

- Added `ibm-watsonx-ai` to `groups.python-minor-and-patch.exclude-patterns`
  (joins `litellm`) so its bumps surface as standalone, never-auto-grouped PRs.
- Documented both packages as the registered watchlist with rationale
  (litellm 2026-03 yank; ibm-watsonx-ai ADR-1 py3.14 break).

### Root-cause note — coverage ratchet vs. task ordering

Raising `fail_under` to 98 in 1.1 precedes the watsonx tests (tasks 5–7), so
measured coverage is **97.40%**. Investigated where the floor is enforced:

- `mise run test` = bare `uv run pytest` (no `--cov`, Constitution V) → **GREEN**;
  canonical `mise run check` gate unaffected.
- CI `ci.yml:85` runs `uv run pytest --cov` → reports **97.40% < 98%** until
  task 11.1. This is the planned Req 9.10 split (1.1 raises, 11.1 confirms),
  not a defect. Self-resolves once SDK/LiteLLM branches are covered.

### Verification evidence

| Gate | Command | Result |
|------|---------|--------|
| Tests | `mise run test` | ✅ 57 passed, 1 skipped |
| Lint | `mise run lint` | ✅ All checks passed |
| Typecheck | `mise run typecheck` | ✅ 0 errors, 0 warnings |
| Import | `python -c "from ibm_watsonx_ai.foundation_models import ModelInference"` | ✅ OK on 3.14.5 |
| Coverage (CI-only) | `uv run pytest --cov` | ⚠️ 97.40% < 98% — expected until task 11.1 |

### Learnings for Act phase

- The coverage ratchet should ideally rise in the *same* wave as the covering
  tests, or the CI `--cov` step stays red across intermediate commits. The
  project's decoupling of coverage from `mise run test` softens this (local
  gate stays green), but PR CI does not.
- Dependabot v2 has no per-dependency label mechanism; the watchlist pattern
  (exclude-patterns + external label-bump workflow) is the project's idiom.

---

## Task 2 — watsonx configuration & fail-fast validation

**Date:** 2026-06-08 · **Status:** ✅ Done · **Boundary:** `src/pydantic_ai_sandbox/config.py`

### TDD cycle

- **RED** — added 34 config tests to `tests/unit/test_config.py` covering: timeout
  defaults (30/120) + env overrides, non-positive/non-numeric timeout rejection,
  transport default→`sdk` + case-insensitivity + unknown-value error, URL
  accept/reject + no-network proof, and the credential gate on both direct and
  fallback-membership selection. First run: **26 failed, 8 passed** (the 8 were
  the accept/gate-dormant cases that need no new rejection logic).
- **GREEN** — implemented in `config.py`:
  - 2.1: `watsonx_timeout_connect=30` / `watsonx_timeout_read=120` fields.
  - 2.3: `_normalize_watsonx_transport` (`mode="before"`) — None/blank→`sdk`,
    lower-case, else `ValueError` listing `("sdk","litellm")`. Field changed to
    non-optional `Literal[...] = "sdk"`.
  - 2.5: `_validate_watsonx_timeout` (`mode="before"`, shared by both fields) —
    `int()` coercion guard + `<= 0` check, message keyed off `info.field_name.upper()`.
  - 2.4: `_validate_watsonx_url` (`mode="after"`) — `urlparse` scheme∈{http,https}
    + non-empty netloc; pure string parse, no I/O.
  - 2.2: credential gate appended to `_check_provider_constraints` — fires on
    `LLM_PROVIDER=watsonx` OR (`fallback` AND `watsonx ∈ FALLBACK_ORDER`); names
    the first missing var.
  - Result: **34 passed**.

### Root-cause investigation — 4 pre-existing tests regressed

Full-suite run after GREEN: **4 failed**. Investigated rather than retried.

- **Cause:** the credential gate (spec-mandated to fire on `watsonx ∈ FALLBACK_ORDER`,
  plan Entity 1 / Req 3.3) is incompatible with 001-era tests that used `watsonx`
  as an *uncredentialled stub* in `FALLBACK_ORDER`:
  `test_factory_fallback.py` (×2), `test_app_lifespan_fallback_dryrun.py`,
  `test_factory_dispatch.py`. The plan's File Structure Plan marked two of these
  `[NO CHANGE]` — an oversight given the gate.
- **Decision:** narrowing the gate to direct-only would violate Task 2.2, so the
  gate stays. Migrated the stub scenarios to `anthropic`/`bedrock` (still stubs);
  gave the direct-watsonx dispatch test valid creds (watsonx is still in
  `_MVP_STUB_PROVIDERS` until 4.2, so it still raises `NotImplementedError`).

### Verification evidence

| Gate | Command | Result |
|------|---------|--------|
| Watsonx tests | `mise run test tests/unit/test_config.py -k watsonx` | ✅ 34 passed, 11 deselected |
| Tests (full) | `mise run test` | ✅ 91 passed, 1 skipped |
| Lint | `mise run lint` | ✅ All checks passed |
| Typecheck | `mise run typecheck` | ✅ 0 errors, 0 warnings |
| Aggregate | `mise run check` (lint+format+typecheck+test) | ✅ green |

### Learnings for Act phase

- **Plan gap to feed back:** a fail-fast gate that fires on fallback membership
  must be sequenced against — or paired with the migration of — tests that use
  the soon-promoted provider as a stub. The wave plan put Task 2 before Task 4's
  test migration without flagging the collision; the `[NO CHANGE]` annotations on
  `test_factory_fallback.py` / `test_app_lifespan_fallback_dryrun.py` were wrong.
- Stub-scenario tests should reference providers that are *actually* stubs
  (`anthropic`/`bedrock`), never a provider under active promotion.
- Adding the two timeout keys to `_MANAGED_ENV_KEYS` (residual of Task 3.1) was
  required for the default-timeout test to be hermetic; pulled forward here.

---

## Task 3 — Test infrastructure (fixtures & doubles) — 2026-06-08

**Scope:** 3.1 (`tests/conftest.py`) + 3.2 (`tests/support/model_fakes.py`).

### What landed

- **3.1 fixture:** `watsonx_settings_factory` + `WATSONX_TEST_{URL,MODEL_ID,APIKEY,PROJECT_ID}`
  constants + `WatsonxSettingsFactory` Protocol in `conftest.py`. Seats a valid
  watsonx cred set + `LLM_PROVIDER=watsonx`, applies caller overrides (incl.
  `None` → unset), delegates to `settings_factory` for ambient-env isolation.
  The `_MANAGED_ENV_KEYS` half was already done in Task 2 (timeout keys pulled
  forward there) — no change needed.
- **3.2 double:** `watsonx_function_model_failing(*, message, model_name="watsonx")`
  in `model_fakes.py`, a thin wrapper over `function_model_raising` pre-built
  with `ModelAPIError(model_name="watsonx")` so `FallbackModel` recovers it.

### TDD evidence (RED → GREEN)

- RED: `tests/unit/test_watsonx_test_infrastructure.py` failed at collection
  (`ImportError: cannot import name 'WATSONX_TEST_APIKEY'`) — symbols absent.
- GREEN: 6 tests pass after implementing fixture + double.

### Verification gate

| Gate | Command | Result |
|------|---------|--------|
| New infra tests | `uv run pytest tests/unit/test_watsonx_test_infrastructure.py -q` | ✅ 6 passed |
| Aggregate | `mise run check` (lint+format+typecheck+test) | ✅ 97 passed / 1 skipped; ruff clean; pyright 0 errors |

### Learnings for Act phase

- Test infrastructure is TDD-able: assert the fixture/double's *behaviour*
  (valid Settings built; `ModelAPIError` recovered by `FallbackModel`) in a
  dedicated test that fails at import before the support code exists.
- Reuse-over-duplicate: 3.2 specialises `function_model_raising` rather than
  reimplementing a raising `FunctionModel`, keeping the "raise `ModelAPIError`
  → recover; else → propagate" failover contract in one place.

---

## Task 4 — Provider activation & factory dispatch (2026-06-08)

Subtasks 4.1 → 4.2 → 4.3 (a chain; 4.2 ⇄ 4.3 atomic).

### What landed

- **4.1** `llm/providers/watsonx.py` rewritten: module docstring now states the
  boundary contract (does NOT own env parsing/validation, fallback composition,
  or litellm install). Added a minimal `WatsonxSDKModel(Model)` activation
  skeleton — I/O-free `__init__` storing `Settings` under `_app_settings`,
  `system` → `"watsonx"`, `model_name` → `watsonx_model_id` (None-guard).
- **4.2** `llm/factory.py`: dropped `"watsonx"` from `_MVP_STUB_PROVIDERS`
  (now `{"anthropic", "bedrock"}`); watsonx branch changed from a `Never` call
  to `return _build_watsonx(settings)`; stale stub docstrings corrected.
- **4.3** `tests/unit/test_factory_dispatch.py`: watsonx case now asserts a
  `Model` instance; anthropic/bedrock still assert `NotImplementedError`;
  constant-lock test updated to `{"anthropic", "bedrock"}`; added
  `test_llm_provider_vocabulary_unchanged` (all five providers still valid).

### Decisions / root-cause notes

- **Skeleton was mandatory, not scope creep.** 4.3 requires a real `Model` from
  `_build_watsonx`. Confirmed against `pydantic-ai 2.0.0b6`: abstract members =
  `{model_name, system, request}` (`request_stream` NOT abstract). The skeleton
  implements exactly those; `request` raises `NotImplementedError` until Task 5.
- **`_app_settings`, not `_settings`.** `Model.__init__` reserves `self._settings`
  for `ModelSettings`; storing the app `Settings` there would corrupt settings
  merging. Deviated from the plan contract (which used `_settings`) deliberately.

### TDD evidence (RED → GREEN)

- RED: `uv run pytest tests/unit/test_factory_dispatch.py -q` → 3 failed, 6 passed
  (watsonx → `NotImplementedError`; stub constant still held `watsonx`).
- GREEN: same command → 8 passed after 4.1 + 4.2.

### Verification gate

| Gate | Command | Result |
|------|---------|--------|
| Dispatch tests | `uv run pytest tests/unit/test_factory_dispatch.py -q` | ✅ 8 passed |
| Aggregate | `mise run check` (lint+format+typecheck+test) | ✅ 98 passed / 1 skipped; ruff clean; pyright 0 errors |

### Learnings for Act phase

- When an "activation" task asserts a real `Model`, the minimal ABC skeleton is
  part of that task even if a later task "owns" the full Model — pin the abstract
  surface against the installed lib version, not the plan prose.
- Plan contracts can collide with library internals (`_settings`); verify base
  `__init__` attributes before copying a contract verbatim.

---

## Task 5 — SDK transport: WatsonxSDKModel

**Date:** 2026-06-08 · **Status:** 🔄 In progress (5.1, 5.2 ✅) · **Boundary:** `src/pydantic_ai_sandbox/llm/providers/watsonx.py`

### 5.1 — Activation skeleton (`__init__` + `system`/`model_name`)

**Verify-not-create.** Task 4 already landed the skeleton so `_build_watsonx`
could return a real `Model` for the dispatch test. Reread against the 5.1
contract (Req 1.5/3.4/8.1/8.3/8.4/8.6) — it matches exactly, so **no `src/`
edit was required**. 5.1's contribution is the dedicated test coverage.

**TDD framing.** The dispatch test (`test_factory_dispatch.py`) only asserts
`isinstance(model, Model)`; `system`, `model_name`, and the defensive
`None`-guard had **zero direct coverage**. New
`tests/unit/test_watsonx_sdk_construction.py` (4 tests) closes that gap and is
the file Task 7.1 extends with request/response-mapping once 5.2/5.3 land.

- RED: `test_watsonx_sdk_construction.py` absent → skeleton properties +
  `model_name` `None`-branch uncovered.
- GREEN: `uv run pytest tests/unit/test_watsonx_sdk_construction.py -v` → 4 passed.
  - `test_system_property_returns_watsonx` — `system == "watsonx"` (Req 8.6).
  - `test_model_name_is_sourced_from_settings` — `model_name == WATSONX_TEST_MODEL_ID` (Req 3.4/8.6).
  - `test_construction_is_io_free` — detonated `httpx.{Client,AsyncClient}.send`; ctor still returns (Req 1.5).
  - `test_model_name_none_guard_raises_typeerror` — `Settings.model_construct(watsonx_model_id=None)` → `TypeError`.

### Verification gate

| Gate | Command | Result |
|------|---------|--------|
| Skeleton tests | `uv run pytest tests/unit/test_watsonx_sdk_construction.py -v` | ✅ 4 passed |
| Aggregate (canonical) | `mise run check` | ✅ 102 passed / 1 skipped; ruff clean; pyright 0 errors |
| Coverage (CI-only) | `pytest --cov` | ⚠️ 95.26% < 98% — `watsonx.py:126-128` (`request` `NotImplementedError`) owned by 5.3/5.4; confirmed at Task 11.1 per plan 9.10 split |

### Learnings for Act phase

- A "skeleton" subtask that a prior activation task already satisfied becomes a
  **coverage task**: the deliverable is the direct unit tests proving the
  contract, not a source rewrite. Verify the source against the requirement IDs
  before assuming work remains.
- `Settings.model_construct` is the project's established way to cover defensive
  guards whose production path the validator makes unreachable (mirrors
  `test_factory_fallback.py`).

### 5.2 — Lazy `_build_client` (SDK client construction)

**Scope:** a `_build_client` method that builds and memoises the
`ibm-watsonx-ai` `ModelInference` client on first request (never in `__init__`),
wiring the configured timeouts (Req 5.4), `max_retries=0` (Req 6.1 / ADR-2), and
`validate=False` (plan §Entity 2). `request` still raises `NotImplementedError`
(owned by 5.3/5.4) — `_build_client` is exercised directly by the tests.

**Pre-coding empirical checks** (avoid the "tasks.md literal compiles" trap):
- `inspect.signature` confirmed `Credentials(*, url, api_key, …)`,
  `APIClient(credentials, project_id, …, async_httpx_client)`,
  `ModelInference(*, model_id, api_client, validate=True, max_retries=None, …)`.
- `httpx.Timeout(connect=30, read=120)` **raises** `ValueError` — partial spec
  rejected. Used `httpx.Timeout(read, connect=connect)` (read seeds
  read/write/pool; connect overrides).
- SDK ships `py.typed` → pyright strict type-checks the usage.

- **RED**: 5 new tests → `AttributeError: no attribute '_build_client'`
  (after fixing an initial test-harness ordering bug, below).
- **GREEN**: `uv run pytest tests/unit/test_watsonx_sdk_construction.py` → 9 passed
  (4 from 5.1 + 5 new):
  - `test_build_client_wires_credentials_no_retry_and_no_validate` — full wiring
    chain incl. `max_retries=0` / `validate=False` / unwrapped apikey.
  - `test_build_client_applies_default_timeouts` — connect=30 / read=120 (Req 5.4).
  - `test_build_client_applies_overridden_timeouts` — env overrides 15/200 (Req 5.4).
  - `test_build_client_is_lazily_cached` — built once, reused (Req 1.5).
  - `test_build_client_missing_apikey_raises_typeerror` — `SecretStr` unwrap guard.

**Error encountered → root cause → fix (no blind retry):** the first RED run
failed with `TypeError: function() argument 'code' must be code, not str` at
`ibm_watsonx_ai/_wrappers/httpx_wrapper.py:344` (`class HTTPXAsyncClient(httpx.AsyncClient)`),
**not** the expected missing-attribute error. Root cause: the spy patched
`httpx.AsyncClient` to a *function* before the SDK's `httpx_wrapper` was imported,
so the subclass statement received a non-class base. Fix: import
`ibm_watsonx_ai.foundation_models` at the test module's top (binds the subclass to
the real `httpx.AsyncClient`) and patch `httpx.AsyncClient` last in the spy
installer. Re-run → clean RED (missing `_build_client`).

### Verification gate

| Gate | Command | Result |
|------|---------|--------|
| Task tests | `uv run pytest tests/unit/test_watsonx_sdk_construction.py` | ✅ 9 passed |
| Aggregate (canonical) | `mise run check` | ✅ 107 passed / 1 skipped; ruff clean; pyright 0 errors |
| Coverage (CI-only) | `pytest --cov` | ⚠️ deferred to Task 11.1 (plan 9.10 split); only `watsonx.py` `request` `NotImplementedError` body (5.3/5.4) remains uncovered. `_build_client` is fully exercised (happy/cache/guard). Note: standalone `--cov` currently hits an unrelated beartype claw circular-import; canonical bare-pytest gate is green. |

### Learnings for Act phase

- **Import the heavy SDK function-locally, not at module scope.** `factory.py`
  imports every provider module unconditionally, so a top-level
  `import ibm_watsonx_ai` taxes ollama-only deployments. Defer it into
  `_build_client` (first-request only) to keep module import + `__init__` cheap.
- **A network-authenticating constructor can still be unit-tested hermetically**
  by substituting all of `Credentials`/`APIClient`/`ModelInference`/`AsyncClient`
  with recording spies and asserting the wiring — but watch import-time base-class
  binding (the `httpx_wrapper` subclass gotcha above).
- **Restricted ruff `--select X --fix` deletes valid `# noqa` for other rules.**
  `--select RUF100 --fix` stripped a legitimate `# noqa: F401` because F401 was
  disabled in that run. Re-add suppressions after a narrow autofix and re-run the
  full lint.
