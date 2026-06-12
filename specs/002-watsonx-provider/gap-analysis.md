# Implementation Gap Analysis: 002-watsonx-provider

**Feature**: IBM watsonx.ai Provider Implementation
**Date**: 2026-06-08
**Status**: Gap analysis (pre-design); requirements generated, not yet approved
**Inputs**: `spec.md` (12 requirements / 11 NFRs), `.sdd/steering/{product,tech,structure}.md`,
existing `001-agentic-platform` codebase, installed dependency surface.

---

## 1. Analysis Summary

- **Scope is "promote one stub to real", but the bulk of the work is net-new**: SDK
  transport requires a **hand-rolled `pydantic_ai.models.Model` subclass** over
  `ibm-watsonx-ai` (no native watsonx Model ships in pydantic-ai V2 Beta). LiteLLM
  transport can largely reuse existing pydantic-ai building blocks. Config, factory,
  tests, and CI are **extend-existing** with strong pattern matches.
- **De-risked**: `ibm-watsonx-ai==1.5.12` is already installed and is **httpx-based**
  (25 httpx-importing modules vs 1 requests). The spec's no-I/O test strategy
  (patch `httpx.Client.send` / `AsyncClient.send`) and RESPX mocking are therefore
  viable for **both** transports — this was the single biggest open risk and it clears.
- **Three correctness traps to design around**: (a) the custom SDK Model must raise
  `pydantic_ai.exceptions.ModelAPIError` on failure or `FallbackModel` will **not**
  recover it (Req 7.1/7.2 silently break); (b) `WATSONX_TRANSPORT` is already a strict
  pydantic `Literal` that rejects unknown values with a `ValidationError` at *Settings*
  time, which is **not** case-insensitive (Req 2.4) and emits a generic message rather
  than one "listing valid values" (Req 2.5); (c) a **field-name mismatch** —
  spec says `WATSONX_API_KEY`, the codebase already uses `WATSONX_APIKEY`
  (`Settings.watsonx_apikey`, `conftest._MANAGED_ENV_KEYS`).
- **Config is partially present**: `watsonx_url/apikey/project_id/model_id/transport`
  fields exist, but **timeout fields, URL-format validation, and the watsonx
  credential cross-field validator are all missing**, and `watsonx_url` is `str | None`
  (not validated).
- **Recommendation**: Hybrid build — extend Settings/factory/tests/CI in place, build
  the custom SDK Model and the LiteLLM wiring as the two new units. Resolve the three
  traps and the field-name mismatch in the design phase (`/sdd-plan`) before any code.

---

## 2. Existing Codebase Map (integration points)

| Capability | Where it lives today | Touch type |
|------------|---------------------|------------|
| Provider dispatch | `llm/factory.py` `get_model` + `_MVP_STUB_PROVIDERS` | extend |
| watsonx builder | `llm/providers/watsonx.py` `_build_watsonx` (`Never` stub) | replace |
| Config / env | `config.py` `Settings` (+ `watsonx_*` fields, validator) | extend |
| Fallback composition | `llm/fallback.py` `_build_fallback` (stub-skip logic) | extend (data only) |
| Agent shape | `agents/chat_agent.py` `build_chat_agent` (NativeOutput gating) | likely none |
| Observability | `instrument_pydantic_ai` (auto), `logging_setup.py` scrubbing | reuse |
| Dispatch test | `tests/unit/test_factory_dispatch.py` (locks stub set) | update |
| No-I/O test pattern | `tests/unit/test_factory_ollama_no_io.py` | mirror |
| Span attr test | `tests/unit/test_logging_span_attributes.py` | mirror |
| Failover test | `tests/unit/test_fallback_failover.py` + `tests/support/model_fakes.py` | mirror |
| Integration lane | `tests/integration/test_ollama_chat_e2e.py` | mirror |
| Test fixtures | `tests/conftest.py` `settings_factory` / `_MANAGED_ENV_KEYS` | extend |
| CI | `.github/workflows/integration-ollama.yml`, `dependabot.yml` | mirror / extend |
| Deps | `pyproject.toml` (`ibm-watsonx-ai` present; no optional-deps section) | extend |

Confirmed available in the installed environment:
- `ibm_watsonx_ai` 1.5.12 (required dep, **httpx-based**).
- `pydantic_ai.providers.litellm.LiteLLMProvider` (signature: `api_key`,
  `api_base`, `http_client`, or `openai_client`). **No** `pydantic_ai.models.watsonx`.
- `litellm` package is **not installed** (must be optional, gated per Req 2.6).
- `pydantic_ai.models.Model` ABC: abstract `request(...)`, `model_name`, `system`
  (the last two drive `gen_ai.request.model` / `gen_ai.system` — Req 8.6).

---

## 3. Per-Requirement Gap Table

Legend: ✅ satisfied · 🔧 partial (extend) · 🆕 missing (build)

| Req | Capability | Status | Evidence / Gap |
|-----|-----------|--------|----------------|
| 1.1 | Preserve `LLMProvider` literal | ✅ | `config.py:25` already includes `"watsonx"` |
| 1.2 | Drop watsonx from `_MVP_STUB_PROVIDERS` | 🔧 | `factory.py:55` frozenset + **locked** by `test_factory_dispatch.py:145` (`expected = {"watsonx","anthropic","bedrock"}`) — both must change in lockstep |
| 1.3 | `build_model("watsonx")` returns a Model | 🆕 | `factory.py:97` currently calls the `Never` stub; needs `return _build_watsonx(...)` + real builder |
| 1.4 | anthropic/bedrock stay stubs | ✅ | `anthropic.py` / `bedrock.py` unchanged |
| 1.5 | I/O-free construction | 🆕 | new builder must defer all HTTP; pattern from `_build_ollama` |
| 2.1–2.3 | Transport: sdk default / litellm route | 🔧 | `watsonx_transport: Literal["sdk","litellm"] \| None = None` exists but **does not default to `sdk`** and has no builder dispatch |
| 2.4 | Case-insensitive transport | 🆕 | pydantic `Literal` is **case-sensitive**; `SettingsConfigDict(case_sensitive=False)` affects env-*key* matching, not the *value* — needs a normalizing validator or builder-side `.lower()` |
| 2.5 | Invalid transport → fail-fast listing valid values | 🔧 | `Literal` already fails fast, but message does not "list valid values"; decide Settings-validator vs builder guard |
| 2.6 | litellm-missing → fail-fast naming dep | 🆕 | needs an import guard in the litellm branch (`litellm` not installed) |
| 3.1 | Require `WATSONX_API_KEY`/`PROJECT_ID`/`URL`/`MODEL_ID` | 🔧 | fields exist but **named `watsonx_apikey` (env `WATSONX_APIKEY`)** — spec says `WATSONX_API_KEY`. **Naming decision required.** |
| 3.2 | Missing credential → `ValueError` naming the var | 🆕 | **no** watsonx cross-field validator in `Settings._check_provider_constraints` (only ollama is gated) |
| 3.3 | Fail within 2s | ✅ | construction is in-memory; trivially met if no network probe |
| 3.4 | No hardcoded IDs/keys/URLs | ✅ | enforced by `test_no_hardcoded_model_ids.py` + pre-commit hook |
| 4.1–4.2 | URL-format validation (I/O-free) | 🆕 | `watsonx_url: str \| None` is unvalidated; ollama uses `HttpUrl` — could reuse, or add explicit format check with detailed message |
| 4.3 | No reachability check | ✅ | matches existing no-I/O discipline |
| 4.4 | Network error surfaced at runtime w/ classification | 🆕 | depends on custom Model raising classifiable errors |
| 5.1–5.5 | Timeout config (defaults 30/120, env overrides, both transports, validation) | 🆕 | **no** `WATSONX_TIMEOUT_CONNECT/READ` fields exist; no validator; wiring into SDK + LiteLLM `http_client` is net-new |
| 5.6 | Timeout error in span w/ duration attrs | 🆕 | "timeout-duration attributes" appears to **exceed** the "standard three attributes" cap in 8.3 — **internal tension to resolve** (see §6) |
| 6.1–6.4 | No retries; immediate fail w/ observability; Ollama-consistent | 🆕/✅ | no-retry is a non-action for litellm path; for SDK Model, must avoid SDK-internal retry config |
| 7.1–7.4 | Fallback participation + immediate failover | 🔧 | `_build_fallback` already includes watsonx once it leaves the stub set; **failover only works if the Model raises `ModelAPIError`** (FallbackModel default `fallback_on`) |
| 8.1–8.5 | Lean standard span attrs + scrubbing | ✅/🆕 | scrubbing reused as-is; litellm path auto-stamps via OpenAI adapter; SDK path needs 8.6 |
| 8.6 | Custom Model sets `system`/`model_name` | 🆕 | both are **abstract** on `Model`; must return `"watsonx"` and the model id |
| 9.1 | Update dispatch test (watsonx asserts success) | 🔧 | `test_factory_dispatch.py` parametrizes over `_MVP_STUB_PROVIDERS`; watsonx case moves to a success assertion |
| 9.2 | anthropic/bedrock still assert `NotImplementedError` | ✅ | keep existing cases |
| 9.3 | No-I/O proof via httpx send patches | 🆕→viable | SDK is httpx-based → patch strategy works for both transports |
| 9.4 | SDK + LiteLLM unit tests; RESPX for litellm | 🆕 | RESPX viable; SDK path can also be RESPX'd since httpx-based |
| 9.5 | Timeout tests (default/custom/invalid/simulated) | 🆕 | new |
| 9.6 | URL-format tests | 🆕 | new |
| 9.7 | No-retry tests | 🆕 | new |
| 9.8 | Immediate-failover test | 🔧 | mirror `test_fallback_failover.py` + `function_model_raising(ModelAPIError(...))` |
| 9.9 | Span-attr test for SDK Model run | 🆕 | mirror `test_logging_span_attributes.py`; requires faking the SDK call (httpx/RESPX) to run `Agent.run` |
| 9.10 | Zero external calls; ≥98% coverage | 🔧 | `pyproject.toml:127` `fail_under = 93` — ratchet up per the +5/provider rule in `tech.md` |
| 10.1–10.3 | Opt-in integration tests, stateless | 🆕 | mirror `test_ollama_chat_e2e.py`; gate on `RUN_INTEGRATION_WATSONX`; add key to `conftest._MANAGED_ENV_KEYS` |
| 11.1–11.3 | Secrets + manual `integration-watsonx.yml` + fail-on-missing-secret | 🆕 | mirror `integration-ollama.yml` but **`workflow_dispatch` only** (no push/PR/cron) + concurrency + explicit secret check |
| 11.4 | dependabot: `ibm-watsonx-ai` + `litellm` watch labels | 🔧 | `dependabot.yml` already excludes `litellm` from grouping; **`ibm-watsonx-ai` not yet listed** |
| 11.5 | `ibm-watsonx-ai` required + `litellm` optional in pyproject | 🔧 | `ibm-watsonx-ai` present (`pyproject.toml:9`); **no `[project.optional-dependencies]` section** for `litellm` |
| 12.1 | Update/remove `test_mvp_stub_providers_lock` | 🔧 | the lock test is `test_mvp_stub_providers_constant_matches_plan` (`test_factory_dispatch.py:137`) |
| 12.2 | Remove "stub" terminology for watsonx in tasks.md | 🆕 | doc edit; also stub messages cite the old `002-multi-provider` id (see §6) |

---

## 4. Approach Options

The feature decomposes into a fixed **extend-in-place** layer (config, factory wiring,
tests, CI, deps) plus one genuine architectural choice: **how to realize the two
transports**. The spec has already committed to "SDK default, LiteLLM optional"
(Clarifications 2026-06-08), so the options below frame *sequencing and structure*,
not whether to build SDK at all.

| Approach | Description | Cost | Risk |
|----------|-------------|------|------|
| **A. SDK-first, single custom Model** | Build the `WatsonxModel(Model)` subclass over `ModelInference` first; add LiteLLM branch second. | High | All eggs in the hand-rolled adapter; message-mapping + error-classification correctness is the long pole. |
| **B. LiteLLM-first, SDK second** | Wire `OpenAIChatModel(provider=LiteLLMProvider(...))` with `watsonx/<id>` first (cheap, reuses proven adapters + error classes), then build the custom SDK Model. | Medium | LiteLLM is optional/not-installed → dev-loop friction; risks treating litellm as the de-facto default contrary to spec intent. |
| **C. Hybrid parallel (recommended)** | Land the shared scaffold (Settings fields + validators, factory transport dispatch, deps, CI, test fixtures) first; then build SDK Model and LiteLLM branch as two independent units behind the already-tested dispatch. | Medium | Slightly more upfront scaffold design, but isolates the two risky units and lets failover/observability tests be written against the dispatch seam early. |

**Recommendation**: **C (Hybrid)** — it matches the codebase's layered, single-window
(`get_model`) discipline, lets the transport dispatch + Settings validation + failover
behavior be locked by tests before either transport adapter is finalized, and keeps the
SDK Model (the genuine unknown) as a swappable unit. Within C, build the **SDK Model
adapter first** (it is the spec default and the only path with no upstream safety net),
using RESPX/httpx fakes that the httpx-based SDK makes possible.

Sub-decision — **custom SDK Model base class**: subclass `Model` directly (implement
`request`, `model_name`, `system`) vs. subclass/wrap `OpenAIChatModel`. Direct `Model`
subclassing is cleaner given watsonx's non-OpenAI wire format; flag for `/sdd-plan`.

---

## 5. Integration Challenges

1. **`_MVP_STUB_PROVIDERS` drift guard is dual-locked.** Changing the frozenset in
   `factory.py:55` without updating `test_factory_dispatch.py:145` (and the parametrized
   stub-raises test) will break the suite — intentional, but must be a single atomic edit.
2. **Fallback failover depends on error type.** `FallbackModel` recovers only
   `ModelAPIError` by default. The SDK Model's `request` must translate
   `ibm-watsonx-ai` exceptions (`WMLClientError`, auth, timeout, network) into
   `ModelAPIError` (or a subclass) — otherwise Req 7.1/7.2/9.8 pass in isolation but the
   real chain propagates an unrecoverable error.
3. **Field-name mismatch (`WATSONX_API_KEY` vs `WATSONX_APIKEY`).** The existing field
   is `watsonx_apikey`; `conftest._MANAGED_ENV_KEYS` and (likely) `.env.example` use
   `WATSONX_APIKEY`. The spec text (3.1 / FR-010) says `WATSONX_API_KEY`. Pick one and
   align spec + Settings + conftest + docs; note `WATSONX_APIKEY` is also the env name
   the IBM SDK itself recognizes, which argues for keeping it.
4. **Transport value normalization.** `case_sensitive=False` in `SettingsConfigDict`
   normalizes env *keys*, not *values*; a `Literal` won't accept `"SDK"`. Req 2.4
   needs an explicit lowercasing validator (and then the default-to-`sdk` behavior).
5. **Coverage ratchet.** `fail_under=93` must rise toward ≥98 (tech.md's "+5pt per
   provider-impl task"); the new branches must be well-covered or the gate regresses.
6. **Optional-dependency packaging.** No `[project.optional-dependencies]` exists yet;
   introducing `litellm` as an extra (name TBD, e.g. `watsonx-litellm`) plus the runtime
   import guard (Req 2.6) is a new packaging pattern for this repo.

---

## 6. Flagged for Plan-Phase Research / Resolution

- **R1 — Spec-internal tension (5.6 vs 8.3/8.4):** 5.6 asks for "timeout-duration
  attributes" on the span, but 8.3/8.4/SC-018 cap attributes to exactly
  `system`/`model`/`error.class` and forbid extras. Resolve which wins (likely: keep
  the lean cap; surface timeout via `error.class` only). **Needs a clarification.**
- **R2 — SDK message mapping:** map pydantic-ai `list[ModelMessage]` ↔
  `ModelInference.chat`/`generate_text`, and build a valid `ModelResponse`
  (parts, usage, finish_reason, provider_response_id) per the `models/CLAUDE.md`
  guidance (exhaustive part handling, no silent drops). Determine non-streaming method
  and tool-call support surface for the configured model class.
- **R3 — SDK timeout wiring:** how to inject connect/read timeouts into
  `ibm-watsonx-ai` (`APIClient`/`Credentials`/`httpx` client) without a network probe at
  construction. Confirm the SDK exposes an httpx client/timeout hook (it is httpx-based).
- **R4 — LiteLLM construction details:** exact model object (likely
  `OpenAIChatModel(model_name="watsonx/<id>", provider=LiteLLMProvider(...))`), and how
  watsonx `project_id`/`url`/apikey reach litellm (params vs env), plus the
  `http_client` timeout injection for Req 5.4.
- **R5 — Error classification matrix:** which `ibm-watsonx-ai` exceptions map to
  `ModelAPIError` (recoverable) vs. should propagate; ensure auth/4xx vs transient
  network both fail immediately (Req 6.2) yet trigger failover (Req 7.2).
- **R6 — `Model` subclass base choice:** direct `Model` ABC vs `OpenAIChatModel`
  wrapper (see §4 sub-decision).
- **R7 — Stale spec-id references:** `_build_watsonx`/`_build_anthropic`/`_build_bedrock`
  and `test_factory_dispatch.py` cite `002-multi-provider`; this feature is
  `002-watsonx-provider`. Decide scope of the rename (watsonx-only vs. all three stub
  messages) — affects the dispatch test's `"002-multi-provider" in msg` assertion.
- **R8 — Empty steering note is now stale:** spec.md:284 claims `.sdd/steering/` is
  empty, but `product.md`/`tech.md`/`structure.md` are present and were used for this
  analysis. Update the spec note in the design phase.

---

## 7. Document Status & Next Steps

- **Analysis approach**: full framework per `rules/gap-analysis.md` — requirements
  mapped to capabilities, codebase surveyed via Grep/Read, installed dependency surface
  verified (ibm-watsonx-ai httpx-based; LiteLLMProvider present; litellm not installed;
  `Model` ABC surface confirmed). Output language `en` per `spec.json`.
- **Requirements approval**: `spec.json` shows `requirements.approved = false`. Per
  skill policy this analysis proceeds anyway and **feeds back** issues R1, R3-naming, and
  the 5.6/8.3 tension into requirement revision.
- **Next**: run `/sdd-plan 002-watsonx-provider` to produce the technical plan
  (resolve R1-R8, settle the field-name and transport-base decisions, finalize the
  custom Model design), or `/sdd-plan 002-watsonx-provider -y` to auto-approve
  requirements first. Recommend resolving **R1** (the 5.6/8.3 contradiction) and the
  **`WATSONX_API_KEY` naming** before planning, since both ripple through Settings,
  tests, and docs.
</content>
</invoke>
