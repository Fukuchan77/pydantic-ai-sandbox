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

### 5.3 — `request`: message mapping → `achat` → `ModelResponse` (2026-06-08)

**What landed.** The live (non-streaming) inference path in `watsonx.py`:
`request` maps the `list[ModelMessage]` history + tool definitions to the
OpenAI-shaped payload `ModelInference.achat` expects, awaits it on the lazily
built SDK client (5.2), and `_build_response` rebuilds a `ModelResponse` from the
returned dict — text parts, tool-call parts, `usage`, `finish_reason`, `id`
(Req 2.7 / 9.11). Mapping is factored into pure module helpers (`_map_messages`,
`_map_request_part`, `_map_user_prompt`, `_map_assistant_message`, `_map_tools`,
`_map_usage`, `_FINISH_REASON_MAP`) for testability and to keep `request` lean.

**Scope decision — tool definitions are forwarded.** `WatsonxSDKModel.profile`
reports `supports_json_schema_output: False`, so `build_chat_agent` keeps the
plain `ChatResponse` output tool (tool-mode structured output) rather than
`NativeOutput`. That output tool plus `search_kb` must reach `achat` via `tools=`
(mapped from `function_tools + output_tools`), or tool calling / structured
output silently breaks — the request-side half of "no silent drops" (Req 2.7).

**System prompt source.** The agent uses `instructions=`, landing on
`ModelRequest.instructions` (not a `SystemPromptPart`). The mapper takes the last
non-`None` instructions and inserts one leading `system` message after explicit
system prompts — mirroring pydantic_ai's OpenAI adapter.

### TDD evidence (RED → GREEN)

7 new tests in `test_watsonx_sdk_construction.py` (RED = `request`'s Task-4
`NotImplementedError` placeholder; GREEN = all passing):

- `test_request_maps_text_response` — text→`TextPart`, usage, `finish_reason`
  `stop`, `id`→`provider_response_id`, `model_name`/`provider_name` stamped.
- `test_request_maps_tool_call_response` — `tool_calls`→`ToolCallPart`
  (name/args/id), `finish_reason` `tool_calls`→`tool_call`.
- `test_request_maps_text_and_tool_calls_together` — both parts, in order.
- `test_request_maps_message_history_to_openai_dicts` — instructions→system,
  user, assistant `tool_calls`, tool return — exact payload.
- `test_request_forwards_tool_definitions` — `function_tools`→OpenAI tool specs.
- `test_request_rejects_multimodal_user_content` — `ImageUrl` → `NotImplementedError`.

**Pyright-strict friction → fixes (no blind retry).** Three errors on first
`mise run check`: (1) `ModelInference.achat` is typed as bare `dict` → wrapped in
`cast("dict[str, Any]", ...)` with a line-level
`# pyright: ignore[reportUnknownMemberType]`; (2) `dict.get` widening to
`Any | None` failed the `_FINISH_REASON_MAP` key (`str`) → collapsed via an
`Any`-typed local; (3) `reportUnnecessaryIsInstance` on the trailing
`RetryPromptPart` / `ModelResponse` checks (closed unions) → switched to
union-narrowing so a future part-type addition surfaces as a *type* error rather
than a runtime drop. Also a `C901` complexity hit on `_map_messages` → extracted
`_map_request_part`.

### Verification gate

| Gate | Command | Result |
|------|---------|--------|
| Task tests | `uv run pytest tests/unit/test_watsonx_sdk_construction.py` | ✅ 15 passed |
| Aggregate (canonical) | `mise run check` | ✅ **113 passed / 1 skipped**; ruff lint clean; ruff format clean; pyright **0 errors** |
| Coverage (CI-only) | `pytest --cov` | ⚠️ deferred to Task 11.1 (plan 9.10 split). Standalone `--cov` on this file currently aborts with a pytest-cov ↔ beartype import-hook circular import; the canonical bare-pytest gate is green. Defensive branches (`_build_response` no-choices raise, `ThinkingPart` skip, unsupported-part raises) are owned by Task 7.1. |

### Learnings for Act phase

- **Mirror pydantic_ai's own OpenAI Chat adapter for OpenAI-shaped providers.**
  `achat` returns OpenAI-shaped dicts, so `models/openai.py`'s `_process_response`
  / `_map_messages` are the authoritative reference for finish-reason mapping
  (`tool_calls`→`tool_call`), tool-call shape and the instructions-as-system-
  message rule — re-deriving them risks subtle drops.
- **The agent's output mode dictates the request contract.** Because the Model's
  profile says `supports_json_schema_output: False`, structured output flows as an
  *output tool*, not `response_format` — so `tools=` wiring (not JSON-schema) is
  the load-bearing path. Verify a provider's profile before deciding what the
  request must carry.
- **Prefer union-narrowing over a redundant final `isinstance` under pyright
  strict.** A trailing `isinstance` on the last union member trips
  `reportUnnecessaryIsInstance`; relying on narrowing keeps exhaustiveness a
  compile-time guarantee (a new member becomes a type error) without a dead branch.

---

## Task 5.4 — SDK/httpx failure wrapping → `ModelAPIError` (no retries) — 2026-06-08

### Plan (Do-phase intent)

Wrap every SDK failure in `WatsonxSDKModel.request` into
`pydantic_ai.exceptions.ModelAPIError` with no provider-level retries, so
`FallbackModel.fallback_on=(ModelAPIError,)` recovers it (plan.md Entity 2 — the
single highest-risk correctness point). Cover the SDK base `WMLClientError` (all
subclasses) and the underlying httpx errors (timeout/connect/HTTPError);
preserve the cause via `raise ... from`. Reqs 4.4/5.6/6.2/6.3/6.4/8.2.

### TDD cycle

**RED** — appended a Task 5.4 section to `test_watsonx_sdk_construction.py`
(7 net-new tests). Initial run: 7 failed (raw SDK/httpx errors propagated
unwrapped), boundary test passed (RuntimeError correctly not caught).

- `test_request_wraps_sdk_failures_in_model_api_error` (parametrized ×5):
  `WMLClientError`, a local `WMLClientError` subclass, `httpx.ReadTimeout`,
  `httpx.ConnectError`, `httpx.HTTPError` base → all become `ModelAPIError`
  with `__cause__` chained, `model_name` = configured id, original class name
  in the message.
- `test_request_wraps_first_call_client_build_failure` — `_build_client` raising
  `httpx.ConnectError` (lazy first-call auth, Req 4.4) is wrapped too.
- `test_request_does_not_retry_on_failure` — counting fake proves `achat` is
  invoked exactly once (Req 6.1/6.3/6.4).
- `test_request_propagates_unexpected_error_unwrapped` — boundary: a
  `RuntimeError` propagates unwrapped (no over-catch; fail loud).

**GREEN** — in `request`, wrapped `_build_client()` + `await achat(...)` in
`try / except (WMLClientError, httpx.HTTPError)` re-raising
`ModelAPIError(model_name=self.model_name, message=...) from exc`. `WMLClientError`
imported function-locally (keep module import cheap for non-watsonx deployments).
Mapping helpers stay outside the try (before/after) so `NotImplementedError` /
`UnexpectedModelBehavior` are not swallowed. Added `ModelAPIError` to the
`pydantic_ai.exceptions` import.

**Design decisions (root-caused, not guessed):**
- Verified empirically that all SDK errors subclass `WMLClientError` and all
  httpx transport errors subclass `httpx.HTTPError`, so two bases are exhaustive
  without enumerating the three named httpx subtypes.
- Guarded block spans `_build_client()` too, because `APIClient` authenticates at
  lazy construction → DNS/connect failures surface there on the first call (Req 4.4).
- `error.class` carries `ModelAPIError`; the underlying cause is chained. Per
  Clarification 2026-06-08, timeouts surface solely via `error.class`, no
  duration attribute (Req 5.6).

### Verification gate

| Gate | Command | Result |
|------|---------|--------|
| Task tests | `uv run pytest tests/unit/test_watsonx_sdk_construction.py` | ✅ 23 passed |
| Aggregate (canonical) | `mise run check` | ✅ **121 passed / 1 skipped**; ruff lint `All checks passed!`; ruff format `2 files already formatted`; pyright **0 errors, 0 warnings** |
| Coverage (CI-only) | `pytest --cov` | ⚠️ deferred to Task 11.1 (plan 9.10 split) — canonical bare-pytest gate is green |

### Learnings for Act phase

- **Catch by base class after verifying the hierarchy.** Enumerating named
  exception subtypes is fragile; one `python -c "issubclass(...)"` probe confirmed
  two bases (`WMLClientError`, `httpx.HTTPError`) catch the whole matrix.
- **Wrap the lazy client build, not just the call.** When client construction is
  deferred and authenticates over the network, the *first* failure surfaces from
  the builder — the error guard must enclose it or Req 4.4 leaks an unwrapped error.
- **Scope the catch; test the boundary.** A boundary test asserting a non-API
  error propagates unwrapped documents that we don't mask programming bugs as
  recoverable model errors — over-catching would silently trigger failover on bugs.

---

## Task 5.5 — `request_stream` deliberate out-of-scope fail-loud — 2026-06-08

### Plan (Do-phase intent)

Override `WatsonxSDKModel.request_stream` to raise `NotImplementedError` with a
watsonx-specific *out-of-scope* message (streaming is out of scope — spec.md
"Out of Scope"; `/chat` issues a single non-streaming `request`). Req 2.1.

### What changed

- `src/.../watsonx.py`: added the `request_stream` override
  (`@asynccontextmanager`, base-mirroring signature incl. `run_context`), raising
  `NotImplementedError` before the unreachable generator `yield`. Added
  `contextlib.asynccontextmanager` (runtime) + TYPE_CHECKING
  `AsyncGenerator` / `RunContext` / `StreamedResponse` imports.
- `tests/unit/test_watsonx_sdk_construction.py`: +1 test
  (`test_request_stream_raises_out_of_scope`) entering the async CM and asserting
  `NotImplementedError` matching `"out of scope"`.

### Design decisions (root-caused, not guessed)

- **Genuine RED despite the ABC already raising.** `Model.request_stream`'s
  default raises a *generic* `NotImplementedError` ("Streamed requests not
  supported by this WatsonxSDKModel"). Matching on `"out of scope"` (absent from
  the base message, present in ours) makes the RED real — it fails against the
  inherited default and passes only once the deliberate override lands.
- **`AsyncGenerator`, not `AsyncIterator`, return annotation.** The base ABC
  annotates `-> AsyncIterator[StreamedResponse]`, but pyright-strict flags that
  combined with `@asynccontextmanager` as `reportDeprecated` (use
  `AsyncGenerator`). `AsyncGenerator` is a subtype of `AsyncIterator`, so the
  override stays Liskov-covariant while clearing the type gate.
- **Signature mirrors the base exactly** (incl. `run_context=None`) for LSP
  compatibility; `del` of all params documents intentional non-use; the trailing
  `yield` (unreachable, `# pragma: no cover`) keeps it a generator for the
  `@asynccontextmanager` contract.

### Verification gate

| Gate | Command | Result |
|------|---------|--------|
| Task test | `uv run pytest ...::test_request_stream_raises_out_of_scope` | ✅ RED→GREEN (1 passed) |
| Aggregate (canonical) | `mise run check` | ✅ **122 passed / 1 skipped**; ruff lint `All checks passed!`; ruff format `44 files already formatted`; pyright **0 errors, 0 warnings** |

### Learnings for Act phase

- **Override an ABC default only with a distinguishing message** — otherwise the
  RED is hollow (the base already raises). Assert on text unique to the override.
- **`@asynccontextmanager` + return annotation is a pyright-strict trap**: prefer
  `AsyncGenerator[T]` over `AsyncIterator[T]` to avoid `reportDeprecated`, even
  when mirroring an upstream ABC that still uses `AsyncIterator`.

---

## Task 5.6 — `_build_watsonx` transport dispatch (SDK branch) — 2026-06-08

### What changed

- `src/.../watsonx.py`: `_build_watsonx` now dispatches on the validated
  `settings.watsonx_transport` selector instead of unconditionally returning
  `WatsonxSDKModel`. `"sdk"` (the default) → `WatsonxSDKModel(settings)`;
  `"litellm"` raises a greppable `NotImplementedError` (Task 6's branch).
  Docstring updated with the dispatch contract and a `Raises:` section.
- `tests/unit/test_watsonx_sdk_construction.py`: +4 tests (Task 5.6 section) and
  added `_build_watsonx` to the module import. Covers SDK selector → subtype,
  unset → SDK default, I/O-free dispatch (detonated httpx hooks), and the
  litellm fail-loud.

### Design decisions (root-caused, not guessed)

- **Litellm must fail loud, not fall through.** Before 5.6 the builder ignored
  the selector and always returned the SDK model, so a `litellm` selector would
  have silently shipped the SDK transport. The only meaningful RED was therefore
  the litellm test (the three SDK guards passed pre-change). Raising
  `NotImplementedError` matches the codebase's fail-loud idiom (cf. `request`'s
  Task-4 stub and `request_stream`); Task 6 replaces the raise with the real
  branch.
- **No `else`/exhaustiveness ceremony.** `watsonx_transport` is a validated
  `Literal["sdk", "litellm"]` (config Task 2.3), so the post-`if` path is
  provably the litellm case — a guard-clause `if "sdk"` + trailing raise reads
  cleaner than an `elif` and needs no `assert_never`.

### Verification gate

| Gate | Command | Result |
|------|---------|--------|
| Task test | `uv run pytest ...test_watsonx_sdk_construction.py -k build_watsonx` | ✅ RED→GREEN (4 passed: litellm RED→GREEN, 3 SDK guards) |
| Aggregate (canonical) | `mise run check` | ✅ **126 passed / 1 skipped**; ruff lint + format clean; pyright 0 errors |

### Learnings for Act phase

- **A guard task can have only one real RED.** When the pre-existing code already
  satisfies most of a new contract (here: SDK branch already returned the right
  type), pin the *behavioural delta* (litellm fail-loud) as the RED and keep the
  rest as regression guards — don't fabricate REDs that were never red.

---

## Task 6 — LiteLLM transport — 2026-06-09

### Plan (intent)

Wire the `WATSONX_TRANSPORT=litellm` branch of `_build_watsonx`: 6.1 an
optional-dependency import guard (`ImportError → ValueError` naming `litellm`,
Req 2.6), 6.2 a `LiteLLMProvider(api_key, api_base, http_client)` wrapped in
`OpenAIChatModel(model_name="watsonx/<id>", provider=...)`, routing `apikey →
api_key` / `url → api_base` with timeouts via `http_client` (Req 2.3/5.4).
`project_id` reaches litellm via the `WATSONX_PROJECT_ID` env var, not a
constructor arg (R4/ADR-3).

### Do (TDD cycle)

- **RED**: new `tests/unit/test_watsonx_litellm_construction.py` (7 tests) — all
  failed on the Task 5.6 `NotImplementedError` placeholder. Coverage: builds
  `OpenAIChatModel`; `model_name == "watsonx/<id>"`; credential routing
  (`client.api_key`/`base_url`); timeout wiring (defaults 30/120 + env override);
  import-guard `ValueError`; I/O-free construction.
- **GREEN**: extracted `_build_litellm(settings)`; `_build_watsonx` now dispatches
  to it for the non-SDK branch. Removed the obsolete 5.6 fail-loud test from
  `test_watsonx_sdk_construction.py` atomically.

### Design decisions (root-caused, not guessed)

- **Verified surfaces empirically before coding.** Built a `LiteLLMProvider` +
  `OpenAIChatModel` in a throwaway interpreter: confirmed `.client.api_key`,
  `.client.base_url`, `.client.timeout` (an `httpx.Timeout` with the wired
  connect/read phases) and `.model_name == "watsonx/<id>"`. Tests assert these
  public surfaces, not internals — no guessing at attribute names.
- **Three heavy imports kept function-local.** `litellm`, `OpenAIChatModel`,
  `LiteLLMProvider` all import *inside* `_build_litellm` — `factory.py` imports
  this module unconditionally, so module-scope imports would tax SDK-only and
  ollama-only deployments. Same rule as 5.2's SDK import.
- **Import guard tested without uninstalling.** litellm is installed in the env;
  `monkeypatch.setitem(sys.modules, "litellm", None)` forces `import litellm` to
  raise `ImportError`, which the guard re-raises as `ValueError` (cause chained,
  asserted via `__cause__`). RESPX request-path tests stay Task 7.2.
- **Defensive `None` guard for apikey AND model_id.** `f"watsonx/{None}"` would be
  a silent bug; guarded with the same fail-loud `TypeError` invariant the SDK
  builder uses (unreachable when the credential gate has run).

### Verification gate

| Gate | Command | Result |
|------|---------|--------|
| Task tests | `uv run pytest test_watsonx_litellm_construction.py test_watsonx_sdk_construction.py` | ✅ 34 passed |
| Aggregate (canonical) | `mise run check` | ✅ **132 passed / 1 skipped**; ruff lint + format clean; pyright 0 errors |

### Learnings for Act phase

- **Confirm provider/adapter surfaces by construction, not docs.** Wrapping a
  third-party `Provider` in `OpenAIChatModel` exposes a specific attribute graph
  (`.client.timeout` etc.); a 30-second build-and-introspect turned the test
  assertions from speculative to grounded — cheaper than a RED that fails on a
  wrong attribute name.

---

## Task 7.1 — Hermetic SDK construction/mapping tests (2026-06-09)

**Scope:** Exhaustive unit tests for the SDK transport (Req 9.3, 9.11) in
`tests/unit/test_watsonx_sdk_construction.py`.

### What was done

The literal 9.3 (I/O-free construction via both `httpx.Client.send` /
`httpx.AsyncClient.send` patches) and 9.11 (representative `achat` response →
`ModelResponse` with text/tool-call parts, `usage`, `finish_reason`) test
categories already existed from Task 5's incremental TDD. Task 7.1's net-new
work was the **defensive-branch backfill** the Task 5.3/5.5 notes explicitly
assigned to it — pinning every remaining branch of the OpenAI↔pydantic_ai
translation so the ≥98% ratchet (Task 11.1) has no source gaps:

| New test | Branch pinned |
|----------|---------------|
| `test_request_raises_unexpected_behavior_on_no_choices` | `_build_response` no-`choices` → `UnexpectedModelBehavior` |
| `test_request_maps_absent_usage_to_zeroed_usage` | `_map_usage` absent block → `RequestUsage()` zeroed |
| `test_request_maps_unknown_finish_reason_to_none` ×3 | absent / empty / unmapped `finish_reason` → `None` |
| `test_request_maps_empty_message_to_no_parts` | empty assistant message → empty `parts` (rule 433) |
| `test_request_maps_system_prompt_part` | `_map_request_part` `SystemPromptPart` → `system` |
| `test_request_maps_assistant_text_part` | `_map_assistant_message` `TextPart` replay |
| `test_request_skips_thinking_part_in_assistant_message` | `ThinkingPart` documented omission |
| `test_request_raises_on_unsupported_assistant_part` | unsupported part (`FilePart`) → `NotImplementedError` |
| `test_request_maps_retry_prompt_without_tool_to_user` | `RetryPromptPart` (no tool) → `user` |
| `test_request_maps_retry_prompt_with_tool_to_tool` | `RetryPromptPart` (tool) → `tool` |

+12 cases (10 functions, one parametrized ×3). Written after the source (Task 5
did happy-path RED→GREEN); passed on first run → characterization tests
confirming the deferred defensive contracts.

### Trial / decisions

- **`FilePart` chosen as the unsupported-part probe** — a real `ModelResponsePart`
  the mapper doesn't handle, so no synthetic stub needed. Verified it constructs
  (`BinaryContent(media_type="image/png")`) before writing the test.
- **`NotImplementedError` / `UnexpectedModelBehavior` assert raw types, not
  `ModelAPIError`** — both fire outside the SDK-error guard (mapping before /
  `_build_response` after the `try`), so they propagate unwrapped (boundary
  contract from Task 5.4).
- **Retry feedback asserted via `retry.model_response()`** (dynamic), not a
  hardcoded string — robust against upstream wording drift.

### Verification gate

| Gate | Command | Result |
|------|---------|--------|
| Task file | `uv run pytest tests/unit/test_watsonx_sdk_construction.py` | ✅ 39 passed (27 → 39) |
| Aggregate (canonical) | `mise run check` (lint+format+pyright+pytest) | ✅ **144 passed / 1 skipped**; ruff clean; pyright 0 errors |

`pytest --cov` still aborts on the pytest-cov ↔ beartype circular import (known,
deferred to Task 11.1); uncovered branches were targeted by source analysis.

### Learnings for Act phase

- **The "task already done by an earlier task" pattern recurs.** Tasks 4→5→7.1
  all landed tests/skeletons ahead in a shared boundary file. The honest move is
  to treat the later task as "prove exhaustively + backfill deferred branches"
  rather than re-deriving work — the per-task notes are the contract for what's
  net-new, and they held precisely here.

---

## Task 7.2 — LiteLLM RESPX request-path tests (2026-06-09)

**Scope:** Req 9.4 — RESPX-based tests for the LiteLLM transport's live request
path. Net-new = 5 request-path tests in `test_watsonx_litellm_construction.py`
(the import-guard clause was already satisfied by Task 6 in the same file).

### What landed

- `test_litellm_request_maps_text_response_over_respx` — text completion →
  `TextPart`, usage/finish_reason/provider_response_id/model_name mapping.
- `test_litellm_request_routes_model_prefix_and_apikey_on_the_wire` — intercepted
  request body `model == watsonx/<id>` (Req 2.3 prefix end-to-end) + mapped user
  message + `Authorization: Bearer <apikey>` header.
- `test_litellm_request_maps_tool_call_response_over_respx` — `tool_calls` →
  `ToolCallPart`, finish_reason `tool_calls` → `tool_call`.
- `test_litellm_project_id_reaches_litellm_via_env` — the `WATSONX_PROJECT_ID`
  env fixture (R4: `LiteLLMProvider` has no `project_id` arg; carried via env).
- `test_litellm_request_http_error_surfaces_as_model_api_error` — 503 →
  `ModelHTTPError` (a `ModelAPIError` subclass) → failover-recoverable.

### Errors / root cause (investigated, not blind-retried)

- **`litellm` not importable in the canonical test env.** Root cause: it was
  declared ONLY as a `[project.optional-dependencies]` extra; `uv sync` and CI's
  `uv sync --all-groups` install dependency-*groups* but NOT *extras*. Verified
  Task 6's six litellm construction tests fail-collect in that env (only the
  import-guard test, which forces `ImportError`, passed). **Fix:** add `litellm`
  to the dev group (prod stays lean via the extra; test env always has it).
- **`respx` absent entirely** despite Req 9.4 / spec Testing naming it. **Fix:**
  added to the dev group.

### Trial / decisions

- **Confirmed the request path empirically before writing tests** — the litellm
  transport is a plain `AsyncOpenAI` POST to `{WATSONX_URL}/chat/completions`
  (not a `litellm.completion` call), so RESPX intercepts that exact endpoint.
- **Drive `model.request` directly (no Agent)** to pin the transport's own
  request/response contract rather than agent behaviour — matching the SDK
  construction-test grain.
- **Match the endpoint URL exactly** (`_CHAT_COMPLETIONS_URL`) so the mock
  doubles as a "hit the configured watsonx endpoint" assertion.

### Verification gate

| Gate | Command | Result |
|------|---------|--------|
| Task file | `uv run pytest tests/unit/test_watsonx_litellm_construction.py` | ✅ 12 passed (7 → 12) |
| Aggregate (canonical) | `mise run check` (lint+format+pyright+pytest) | ✅ **149 passed / 1 skipped**; ruff lint+format clean; pyright 0 errors |

`pytest --cov` still aborts on the pytest-cov ↔ beartype circular import (known,
deferred to Task 11.1).

### Learnings for Act phase

- **An optional *production* extra is the wrong place for a dependency the test
  suite hard-requires.** Task 6 put `litellm` only in extras and its tests
  silently relied on a manual install — green locally, red in CI. When a feature
  is opt-in for prod but mandatory for tests, it belongs in **both** the extra
  (prod) and the dev group (test/CI). Worth a steering note.
- **"RESPX-based tests" implies an HTTP-level transport.** The grain follows the
  transport: SDK → send-patch/fake `achat`; litellm-via-OpenAI-adapter → RESPX at
  `/chat/completions`. Verifying the actual wire path first avoided mocking the
  wrong layer.
