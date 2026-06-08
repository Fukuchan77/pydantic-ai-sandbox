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
