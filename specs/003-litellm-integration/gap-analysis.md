# 003-litellm-integration — Implementation Gap Analysis

**Feature**: General-purpose `LiteLLMModel` + thin watsonx wrapper, replacing the
broken `_build_litellm()` OpenAI-client transport.
**Date**: 2026-06-09 · **Language**: en · **Status**: requirements-generated (not yet approved)
**Inputs**: `spec.md`, `.sdd/steering/{structure,tech,product}.md`,
`~/.claude/sdd/rules/gap-analysis.md`, the `002-watsonx-provider` PDCA `do.md`
live-verification findings, and empirical probes of the installed
`pydantic-ai 2.0.0b6` / `litellm` packages.

---

## Analysis Summary

- **The mapping layer already exists and is battle-tested.** `WatsonxSDKModel`
  in [watsonx.py](../../src/pydantic_ai_sandbox/llm/providers/watsonx.py) already
  implements the *exact* OpenAI-shaped translation this feature needs
  (`_map_messages`, `_map_request_part`, `_map_user_prompt`,
  `_map_assistant_message`, `_map_tools`, `_map_usage`, `_FINISH_REASON_MAP`,
  `_build_response`) with full hermetic coverage. `litellm.acompletion()` returns
  an OpenAI-shaped object exposing `.model_dump()` / `.to_dict()` — a clean bridge
  into the existing `_build_response(dict)` helper. The dominant design question
  is **reuse vs. re-derive-from-upstream**, not "how to map".
- **Version reconciliation is the real adaptation cost (Req 9.2).** Upstream
  `pydantic-ai-litellm` 0.2.6 targets `pydantic-ai-slim>=1.95.0`; this project
  pins `pydantic-ai==2.0.0b6`. Vendoring (not `pip install`) is therefore the
  right call: the upstream `Model` ABC / `ModelResponse` / `RequestUsage` shapes
  differ from the installed beta and must be hand-reconciled. Confirmed installed
  ABC abstract surface = `{model_name, request, system}` (`request_stream` is
  *not* abstract) — identical to what `WatsonxSDKModel` already satisfies.
- **The replacement target is small and well-bounded.** Only `_build_litellm()`
  (61 lines) and its construction/RESPX test file are being replaced. The SDK
  transport, factory dispatch, fallback, and config are untouched (Req 7.4/10.4).
- **Recommendation: Hybrid (Approach C).** Derive the `LiteLLMModel` *skeleton and
  request shape* from the upstream library's design (honoring Req 9.1/9.3 MIT
  attribution), but implement message/tool/response mapping by **extracting the
  proven watsonx helpers into a shared module** and reusing them — DRY, already
  covered, and already mirrors pydantic-ai's own OpenAI adapter.
- **Three challenges need plan-phase decisions**: (1) `WATSONX_PROJECT_ID` env-var
  routing (litellm reads it from the environment; the model has no constructor
  arg for it), (2) the test grain flips from RESPX (`/chat/completions`) to mocking
  `litellm.acompletion` directly, and (3) confirming `num_retries=0` / `api_base` /
  `custom_llm_provider` pass through litellm's `**kwargs` (not in the explicit
  signature).

---

## Per-Requirement Gap Table

Legend: ✅ satisfied · 🔧 partial (extend) · 🆕 new

| Req | Capability | Status | Evidence / Notes |
|-----|-----------|--------|------------------|
| **1.1** | `LiteLLMModel(Model)` over `litellm.acompletion` | 🆕 | No `LiteLLMModel` exists. ABC surface `{model_name, request, system}` confirmed in `2.0.0b6`; `WatsonxSDKModel` is the structural template. |
| **1.2** | Accept `<provider>/<model_id>`, `api_key`, `api_base`, `custom_llm_provider` | 🆕 / 🔧 | `litellm.acompletion` takes `model`, `api_key` explicitly; `api_base` + `custom_llm_provider` flow via `**kwargs` (confirmed *absent* from the explicit signature — must be passed through, documented in litellm). |
| **1.3** | I/O-free construction | ✅(pattern) | Established invariant; `WatsonxSDKModel.__init__` + `test_litellm_construction_is_io_free` show the proven shape. `litellm` import is function-local (Req 6.2). |
| **1.4** | `model_name` / `system` properties | ✅(pattern) | `WatsonxSDKModel.system`/`model_name` are the exact template; `system` likely derived from the route prefix's provider segment. |
| **2.1** | Map full `ModelMessage` history | 🔧(reuse) | `_map_messages` / `_map_request_part` / `_map_user_prompt` / `_map_assistant_message` already do this in [watsonx.py:90-219](../../src/pydantic_ai_sandbox/llm/providers/watsonx.py#L90-L219). Extract & reuse. |
| **2.2** | Map tools; `None` when empty | 🔧(reuse) | `_map_tools` ([watsonx.py:222-249](../../src/pydantic_ai_sandbox/llm/providers/watsonx.py#L222-L249)) already returns this exact shape. |
| **2.3** | `NotImplementedError` on unsupported parts | 🔧(reuse) | `_map_user_prompt` / `_map_assistant_message` already raise naming the type; covered by `test_request_rejects_multimodal_user_content`. |
| **2.4** | Surface double-encoded tool args faithfully | 🆕 (verify) | Granite double-encoding was a *live* finding (do.md). `_build_response` currently passes `function.get("arguments")` through raw — likely already faithful, but must be re-verified through the litellm response object (litellm may normalize differently). |
| **3.1** | Build `ModelResponse` (text/tool/usage/finish/id) | 🔧(reuse) | `_build_response` ([watsonx.py:490-546](../../src/pydantic_ai_sandbox/llm/providers/watsonx.py#L490-L546)) does this from an OpenAI-shaped dict. Bridge via `acompletion(...).model_dump()`. `provider_name` becomes the route provider, not hardcoded `"watsonx"`. |
| **3.2** | Finish-reason mapping, `None` for unmapped | 🔧(reuse) | `_FINISH_REASON_MAP` + the `get`-with-None-default already implements this. |
| **3.3** | No choices → `UnexpectedModelBehavior` | 🔧(reuse) | `_build_response` already raises; `test_request_raises_unexpected_behavior_on_no_choices`. |
| **3.4** | Absent usage → zeroed `RequestUsage` | 🔧(reuse) | `_map_usage` ([watsonx.py:252-264](../../src/pydantic_ai_sandbox/llm/providers/watsonx.py#L252-L264)) already returns `RequestUsage()`. |
| **4.1** | Wrap litellm exceptions as `ModelAPIError` (chained) | 🆕 (pattern) | `WatsonxSDKModel.request`'s `try/except … raise ModelAPIError(...) from exc` is the template; the catch base changes from `(WMLClientError, httpx.HTTPError)` to litellm's exception hierarchy (`litellm.exceptions.*`, base likely `litellm.APIError` / `openai.OpenAIError`). **Plan-phase: confirm the exhaustive base classes.** |
| **4.2** | `num_retries=0` | 🆕 (verify) | litellm honors `num_retries`; it is **not** in the explicit `acompletion` signature (passes via `**kwargs`). Must verify it reaches the request and is respected. |
| **4.3** | Don't wrap mapping errors | ✅(pattern) | Same boundary discipline as SDK transport: mapping runs *outside* the try block so `NotImplementedError`/`UnexpectedModelBehavior` propagate. |
| **5.1** | Pass connect/read timeouts to `acompletion` | 🔧 | `acompletion` takes `timeout`. SDK/old-litellm used `httpx.Timeout(read, connect=connect)`; litellm's `timeout` is typically a float/`httpx.Timeout`. **Plan-phase: confirm accepted timeout type.** |
| **5.2** | Source timeouts from `watsonx_timeout_*` | ✅ | `Settings.watsonx_timeout_connect/read` exist and are validated. |
| **6.1** | Missing `litellm` → `ValueError` naming package | ✅(reuse) | The exact guard exists in `_build_litellm` ([watsonx.py:627-635](../../src/pydantic_ai_sandbox/llm/providers/watsonx.py#L627-L635)); `test_litellm_import_guard_raises_valueerror_naming_package` covers it. Retain/relocate. |
| **6.2** | Function-local `litellm` import | ✅(pattern) | Current builder already imports function-locally. |
| **7.1** | watsonx builder → `LiteLLMModel("watsonx/<id>", …)` | 🔧(rewrite) | `_build_litellm` is rewritten to construct the new model instead of `OpenAIChatModel`+`LiteLLMProvider`. |
| **7.2** | Route `project_id` via `WATSONX_PROJECT_ID` env | 🔧 (decide) | Today the test fixture *seats* the env var; nothing in `src/` sets it. **Plan-phase decision:** model/builder sets `os.environ` (side-effect) vs. documented deployment contract. See Challenge #1. |
| **7.3** | Replace the broken `_build_litellm()` | 🆕 | The whole point: the OpenAI-client path 404s against watsonx (do.md live finding). Replaced wholesale. |
| **7.4** | SDK path unchanged + tests green | ✅ | `WatsonxSDKModel` and `_build_watsonx`'s SDK branch are untouched. |
| **7.5** | Unwrap secret only at boundary; never log | ✅(pattern) | `.get_secret_value()` at the litellm call boundary, as both existing builders do. |
| **8.1/8.2** | `request_stream` routes-or-fails-loud, no silent downgrade | 🔧(pattern) | `WatsonxSDKModel.request_stream` ([watsonx.py:548-578](../../src/pydantic_ai_sandbox/llm/providers/watsonx.py#L548-L578)) is the fail-loud template (`@asynccontextmanager`, distinguishing message, unreachable `yield`). litellm streaming exists (`acompletion(stream=True)`) if routing is chosen instead. |
| **9.1/9.3** | Derived from upstream + MIT attribution | 🆕 | Upstream is MIT (confirmed via PyPI). Vendor with a license/attribution header. See Approaches. |
| **9.2** | V2-Beta ABC + py3.14 reconciliation | 🆕 | Upstream targets `pydantic-ai-slim>=1.95.0`; project pins `2.0.0b6`. The core adaptation work — reconcile types against the installed beta. |
| **9.4** | Strict typing + `msg`-then-`raise` idioms | ✅(pattern) | Whole codebase follows this; pyright strict, `from __future__ import annotations`. |
| **10.1/10.2** | Hermetic tests, litellm mocked, fallback recovery | 🆕 | **Grain change**: mock `litellm.acompletion` directly (monkeypatch), not RESPX `/chat/completions`. The old RESPX request-path tests target the *removed* transport and will be rewritten. |
| **10.3** | Extend `RUN_INTEGRATION_WATSONX=1` lane | 🔧 | [test_watsonx_chat_e2e.py](../../tests/integration/test_watsonx_chat_e2e.py) exists; add a litellm-transport variant (the do.md "deferred to next phase" item). |
| **10.4** | SDK / dispatch / fallback suites unchanged | ✅ / ⚠️ | True for those three suites. **Caveat:** `test_watsonx_litellm_construction.py` tests the *old* transport and is **not** in the "unchanged" set — it must be rewritten. |
| **NFR** | 98% coverage, hermetic default, span parity, security | 🔧 | Ratchet already at 98 ([pyproject.toml:135](../../pyproject.toml#L135)). New model needs full branch coverage; `litellm` already in both the `litellm` extra and the dev group ([pyproject.toml:26,30-31](../../pyproject.toml#L26)). |

---

## Integration Challenges

1. **`WATSONX_PROJECT_ID` env-var routing (Req 7.2).** litellm's watsonx provider
   reads the project id from the *environment*, and `LiteLLMModel` has no
   constructor argument for it. Today only the test fixture seats the var; nothing
   in `src/` does. Options: (a) the watsonx wrapper sets `os.environ[...]` at build
   time (a process-global side-effect — surprising, and survives across providers),
   (b) the model sets it transiently around each `acompletion` call, or (c) keep it
   a documented *deployment contract* (the operator sets it, as the SDK path
   already requires four env vars). The boundary contract in `structure.md`
   ("this module never re-validates settings") favors (c), but live routing must be
   proven in the integration lane regardless.

2. **Test-mock grain flips.** The old litellm transport delegated HTTP to an
   `AsyncOpenAI` client, so RESPX at `/chat/completions` was the correct mock. The
   new path calls `litellm.acompletion()` which owns the HTTP internally — so the
   hermetic tests must **patch `litellm.acompletion`** (return a canned
   `litellm.ModelResponse`) and assert the kwargs passed (`model`, `messages`,
   `tools`, `timeout`, `num_retries`, `api_key`). `respx` may no longer be needed
   for this file. Re-verify `assert_all_called`-style egress guards translate.

3. **litellm exception hierarchy (Req 4.1).** The SDK path caught
   `(WMLClientError, httpx.HTTPError)`. The litellm path must catch litellm's
   bases exhaustively (e.g. `litellm.exceptions.APIError` and friends, which often
   subclass `openai.OpenAIError`). Mirror the SDK's "verify the hierarchy with a
   `issubclass` probe before catching by base" discipline (do.md Task 5.4 learning).

4. **`acompletion` kwargs that bypass the explicit signature.** Empirically,
   `num_retries`, `api_base`, and `custom_llm_provider` are **not** in
   `inspect.signature(litellm.acompletion)` — they ride `**kwargs`. The plan must
   verify each is actually honored (a passthrough that's silently dropped would
   break Req 4.2's no-retry guarantee, the cornerstone of ADR-2 failover).

5. **Double-encoded Granite tool args (Req 2.4).** A live do.md finding: granite
   models double-encode tool-call args. The existing `_build_response` passes raw
   `arguments` through, but litellm's response object may normalize or re-encode
   differently than the raw watsonx dict did. Verify the faithful-passthrough
   contract holds through `litellm.ModelResponse.model_dump()`.

6. **Placement & the "provider-agnostic" boundary.** `structure.md` routes *new
   providers* to `llm/providers/<name>.py`, but `LiteLLMModel` is provider-agnostic
   — structurally closer to `llm/fallback.py` (a cross-cutting `Model`). Natural
   home: `llm/litellm_model.py`, with the watsonx wrapper staying in
   `providers/watsonx.py`. Confirm the `LLMProvider` Literal / factory dispatch
   stay **unchanged** (this is not a new provider name — watsonx still dispatches
   to `_build_watsonx`, which internally picks the litellm transport).

7. **`profile` for output-mode gating.** `build_chat_agent` wraps `NativeOutput`
   only when `model.profile.supports_json_schema_output` is True *and* `model is
   None` (resolver path). `LiteLLMModel`'s default `Model.profile` must not
   accidentally report `True` for watsonx (which would force `response_format` the
   way the SDK path deliberately avoids). Confirm the default profile keeps the
   watsonx-via-litellm path in tool-mode, matching the SDK transport.

---

## Approach Options

| # | Approach | When it fits | Cost | Risk |
|---|----------|-------------|------|------|
| **A** | **Vendor & adapt upstream `model.py`** verbatim, reconcile to `2.0.0b6` | Strict reading of Req 9.1 ("derived from the library") | High | Duplicates the watsonx mapping; upstream's `>=1.95` types diverge from beta → heavy line-by-line reconciliation; two parallel mapping implementations to keep in sync |
| **B** | **Build new `LiteLLMModel` reusing watsonx mapping helpers** (extract to shared module), ignore upstream code | DRY purist; fastest to green | Low–Med | Weakest fit to Req 9.1/9.3 (no demonstrable upstream lineage / attribution) |
| **C** ✅ | **Hybrid**: skeleton + request shape + `LiteLLMModelSettings` *derived from upstream's design* (MIT header), mapping *reused* from extracted watsonx helpers | Honors Req 9.1/9.3 lineage **and** DRY; reuses tested code that already mirrors pydantic-ai's OpenAI adapter | Medium | The extraction refactor touches `watsonx.py` (must keep SDK tests green); requires citing upstream design provenance without copying its incompatible mapping |

**Recommended: Approach C (Hybrid).** It is the only option that satisfies both
Req 9.1 (upstream-derived design, MIT attribution) and the project's DRY / reuse
ethic (do.md's repeated "reuse-over-duplicate" learning). Concretely:

- Extract the OpenAI-shaped mapping helpers from `watsonx.py` into a shared module
  (e.g. `llm/_openai_mapping.py`): `_map_messages`, `_map_request_part`,
  `_map_user_prompt`, `_map_assistant_message`, `_map_tools`, `_map_usage`,
  `_FINISH_REASON_MAP`, and a parameterized `build_response(dict, *, system,
  provider_name, model_name)`. `WatsonxSDKModel` then imports them (its tests stay
  green — same behavior, new location).
- Author `LiteLLMModel` in `llm/litellm_model.py` with an MIT-attribution header
  citing `mochow13/pydantic-ai-litellm`, its `__init__`/`request`/`request_stream`
  shape following the upstream design, calling `litellm.acompletion(...)` and
  bridging its response via `.model_dump()` into `build_response(...)`.
- Rewrite `_build_litellm()` in `providers/watsonx.py` to construct
  `LiteLLMModel(model_name="watsonx/<id>", api_key=…, api_base=…, timeout=…,
  num_retries=0)` and rewrite `test_watsonx_litellm_construction.py` to mock
  `litellm.acompletion`.

---

## Flagged for Plan-Phase Research

- **R1 — litellm exception taxonomy**: enumerate the exhaustive base class(es) to
  catch for Req 4.1 (probe `issubclass`); confirm the chained-cause idiom.
- **R2 — `acompletion` kwargs passthrough**: verify `num_retries=0`, `api_base`,
  `custom_llm_provider`, and the accepted `timeout` type are honored, not silently
  dropped (critical for ADR-2 / Req 4.2 / 5.1).
- **R3 — `WATSONX_PROJECT_ID` routing decision**: pick (a) build-time env set,
  (b) per-call transient env, or (c) deployment contract; document the trade-off
  against the `structure.md` boundary rule.
- **R4 — upstream license & provenance**: capture the exact MIT text and the
  upstream commit/version to cite in the vendored file header (Req 9.3).
- **R5 — `request_stream` v1 decision**: route through `acompletion(stream=True)`
  vs. fail-loud `NotImplementedError`. Spec defers but demands no silent downgrade
  (Req 8.1/8.2); recommend fail-loud for v1 parity with the SDK transport.
- **R6 — `profile` behavior**: confirm `LiteLLMModel`'s default profile keeps the
  watsonx path in tool-mode (no accidental `NativeOutput`/`response_format`).
- **R7 — live routing proof**: the integration-lane variant that closes the do.md
  "litellm live routing deferred to next phase" gap (404 root cause now addressed
  by routing through the litellm SDK rather than the OpenAI client).

---

## Next Steps

1. Review this analysis (note requirements are **generated, not yet approved** —
   gap insights may feed requirement revisions).
2. Run `/sdd-plan 003-litellm-integration` to produce the technical plan
   (resolving R1–R7), or `/sdd-plan 003-litellm-integration -y` to auto-approve
   requirements and proceed directly.
