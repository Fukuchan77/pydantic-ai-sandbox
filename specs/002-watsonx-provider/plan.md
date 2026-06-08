# Implementation Plan: IBM watsonx.ai Provider Implementation

**Branch**: `002-watsonx-provider` | **Date**: 2026-06-08 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/002-watsonx-provider/spec.md`

## Summary

This feature upgrades the IBM watsonx.ai LLM provider from a `NotImplementedError` stub into a production-ready implementation. It supports two transport modes — direct `ibm-watsonx-ai` SDK integration (the default) and an optional LiteLLM-based routing path — while preserving the platform's established patterns: environment-driven configuration, fail-fast and I/O-free construction, hermetic-by-default tests, and lean observability spans. The implementation removes watsonx from `_MVP_STUB_PROVIDERS`, enables it in the fallback chain, and maintains 98%+ test coverage with zero external API calls in the default suite.

## Technical Context

**Language/Version**: Python 3.14 (per `.python-version`; `pyproject.toml` `requires-python >=3.14`, pyright pinned to 3.14)  
**Primary Dependencies**: 
- `pydantic-ai` (V2 beta) - Agent framework with custom Model support
- `ibm-watsonx-ai` **`>=1.5.13`** - Direct SDK integration (default transport). **The locked `1.5.12` cannot import `foundation_models.ModelInference` on Python 3.14.5** (enum/`StrEnum` incompatibility, `utils/utils.py:1191`); `1.5.13` (`requires_python = "<3.15,>=3.11"`) fixes it and is verified to import on 3.14.5. See research.md C1 / ADR-1. The version bump is the **first foundation task** — the SDK lane cannot compile until it lands.
- `litellm` - Optional routing transport (py3.14 support unverified; import-guarded per Req 2.6)
- `fastapi` - API framework
- `logfire` - Observability and tracing
- `httpx` - HTTP client (for I/O-free construction testing)

**Storage**: N/A (stateless API calls)  
**Testing**: `pytest` with `pytest-cov`, `respx` for HTTP mocking  
**Target Platform**: Linux server (FastAPI application)  
**Project Type**: Single project (Python package with API)  
**Performance Goals**: 
- Startup fail-fast within 2 seconds for missing credentials
- Default timeout: 30s connect, 120s read
- Zero external API calls in default test suite

**Constraints**: 
- I/O-free construction (no network calls during Model instantiation)
- Hermetic default tests (98%+ coverage, no live API calls)
- No provider-level retries (rely on fallback chain)
- Lean observability (standard attributes only: `gen_ai.system`, `gen_ai.request.model`, `error.class`)

**Scale/Scope**: 
- 50+ existing unit tests must continue passing
- Add ~15-20 new unit tests for watsonx provider
- 1 integration test (opt-in via `RUN_INTEGRATION_WATSONX`)
- Raise the coverage ratchet from `fail_under = 93` to `98` (`.sdd/steering/tech.md`: "+5pt per provider-implementation task"); the new branches must be well-covered or the gate regresses

### Steering Alignment (`.sdd/steering/`)

This plan was reconciled against the three steering documents (which exist; the
earlier "steering is empty" note in spec.md was stale and is now corrected):

- **`tech.md`** — Python **3.14**; pyright `strict`; `from __future__ import annotations` in every module; secrets are `SecretStr | None` unwrapped only at the SDK boundary; errors use the `msg = ...; raise` idiom; model IDs never hardcoded in `src/`; all gates via `mise run`. Coverage ratchet currently 93 → 98 for this task.
- **`structure.md`** — provider builders live in `llm/providers/<name>.py` exporting `_build_<name>(settings: Settings) -> Model`, wired into `factory.get_model` and `_MVP_STUB_PROVIDERS`; downward-only imports (routes→deps→agents→llm→config); each module docstring states its **boundary contract** (what it does *not* own).
- **`product.md`** — Config-over-code, Fail-fast/fail-loud, Hermetic-by-default, Intent-documented docstrings citing `Req N.N` / `plan.md §N`.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*
*Constitution source: the project Constitution referenced from [README.md](../../README.md) (per `.sdd/steering/tech.md`); there is no `.sdd/memory/constitution.md` in this repo. Principle names below map to the Product Principles in `.sdd/steering/product.md` (Config-over-code, Fail-fast/fail-loud, Hermetic-by-default, Intent-documented) plus the incremental-delivery convention carried over from `001-agentic-platform`.*

### Principle I: Specification-First Delivery ✅ PASS
- Specification exists at `specs/002-watsonx-provider/spec.md`
- Contains user value (functional watsonx provider), independently testable user stories (12 requirements), measurable success criteria (21 SC items), and explicit edge cases
- Implementation will trace back to spec requirements

### Principle II: Configuration-Driven Provider Behavior ✅ PASS
- All credentials sourced from environment variables: `WATSONX_APIKEY`, `WATSONX_PROJECT_ID`, `WATSONX_URL`, `WATSONX_MODEL_ID`
- Transport mode via `WATSONX_TRANSPORT` (default: `sdk`)
- Timeout configuration via `WATSONX_TIMEOUT_CONNECT`, `WATSONX_TIMEOUT_READ`
- No hardcoded model IDs, secrets, or provider values (Requirement 3.4, SC-008)
- Fail-fast validation for missing/invalid configuration (Requirement 3.2, 3.3)

### Principle III: Hermetic Default Quality Gates ✅ PASS
- Default test suite makes zero external API calls (Requirement 9.10, SC-002)
- Integration tests opt-in via `RUN_INTEGRATION_WATSONX` flag (Requirement 10.1)
- I/O-free construction proven via `httpx.Client.send` patches (Requirement 9.3)
- Maintains 98%+ coverage (Requirement 9.10, SC-010)
- Uses canonical `mise` task runner

### Principle IV: Observable and Fail-Fast Services ✅ PASS
- Fail-fast at construction for missing credentials within 2 seconds (Requirement 3.2, 3.3, SC-004)
- Fail-fast for invalid transport mode (Requirement 2.5)
- Fail-fast for invalid URL format (Requirement 4.2)
- Fail-fast for invalid timeout values (Requirement 5.5)
- Observability spans with standard attributes (Requirement 8.1, 8.2, 8.3)
- No silent degradation; errors surface explicitly (Requirement 6.2)

### Principle V: Incremental, Independently Verifiable Delivery ✅ PASS
- User stories organized by functional capability (provider activation, transport modes, credentials, timeouts, error handling, fallback, observability, testing, CI/CD, migration)
- Each requirement independently testable
- Implementation leaves repository in runnable state after each phase
- Foundational work (SDK/LiteLLM integration) blocks later stories but is justified

**Constitution Compliance**: ✅ ALL PRINCIPLES SATISFIED

## Project Structure

### Documentation (this feature)

```text
specs/002-watsonx-provider/
├── plan.md              # This file (/sdd-plan command output)
├── research.md          # Phase 0 output (/sdd-plan command)
├── data-model.md        # Phase 1 output (design inlined in plan.md §Phase 1)
├── quickstart.md        # Phase 1 output (design inlined in plan.md §Phase 1)
├── contracts/           # Phase 1 output (design inlined in plan.md §Phase 1)
├── tasks.md             # Phase 2 output (/sdd-tasks command - NOT created by /sdd-plan)
├── spec.md              # Feature specification (already exists)
├── gap-analysis.md      # Gap analysis (already exists)
└── checklists/          # Quality checklists (already exists)
    └── requirements.md
```

### Source Code (repository root)

```text
src/pydantic_ai_sandbox/
├── __init__.py
├── config.py                    # [MODIFY] Add watsonx config fields
├── logging_setup.py             # [NO CHANGE] Existing observability setup
├── main.py                      # [NO CHANGE] FastAPI app entry point
├── agents/
│   ├── __init__.py
│   └── chat_agent.py            # [NO CHANGE] Agent using factory
├── api/
│   ├── __init__.py
│   ├── deps.py                  # [NO CHANGE] Dependency injection
│   └── routes/
│       ├── __init__.py
│       ├── chat.py              # [NO CHANGE] Chat endpoint
│       └── health.py            # [NO CHANGE] Health endpoint
├── llm/
│   ├── __init__.py
│   ├── factory.py               # [MODIFY] Remove watsonx from _MVP_STUB_PROVIDERS
│   ├── fallback.py              # [NO CHANGE] Fallback chain logic
│   └── providers/
│       ├── __init__.py
│       ├── anthropic.py         # [NO CHANGE] Remains stub
│       ├── bedrock.py           # [NO CHANGE] Remains stub
│       ├── ollama.py            # [NO CHANGE] Reference implementation
│       └── watsonx.py           # [IMPLEMENT] New watsonx provider with SDK/LiteLLM modes
└── schemas/
    ├── __init__.py
    └── chat.py                  # [NO CHANGE] Request/response schemas

tests/
├── conftest.py                  # [MODIFY] Add watsonx fixtures + WATSONX_APIKEY/PROJECT_ID/URL/MODEL_ID/TRANSPORT/TIMEOUT_* to _MANAGED_ENV_KEYS
├── integration/
│   ├── __init__.py
│   ├── test_ollama_chat_e2e.py  # [NO CHANGE] Reference pattern
│   └── test_watsonx_chat_e2e.py # [NEW] Opt-in watsonx integration test
├── support/
│   ├── __init__.py
│   └── model_fakes.py           # [MODIFY] Add watsonx test doubles
└── unit/
    ├── test_app_lifespan_fallback_dryrun.py  # [NO CHANGE]
    ├── test_chat_agent_output_native.py      # [NO CHANGE]
    ├── test_chat_agent_tool.py               # [NO CHANGE]
    ├── test_chat_agent_v2_surface.py         # [NO CHANGE]
    ├── test_chat_endpoint_validation_errors.py # [NO CHANGE]
    ├── test_chat_endpoint_with_testmodel.py  # [NO CHANGE]
    ├── test_config.py                        # [MODIFY] Add watsonx config tests
    ├── test_factory_dispatch.py              # [MODIFY] Update watsonx case
    ├── test_factory_fallback.py              # [NO CHANGE]
    ├── test_factory_ollama_no_io.py          # [NO CHANGE]
    ├── test_fallback_failover.py             # [NO CHANGE]
    ├── test_health.py                        # [NO CHANGE]
    ├── test_logging_resilience.py            # [NO CHANGE]
    ├── test_logging_setup.py                 # [NO CHANGE]
    ├── test_logging_span_attributes.py       # [NO CHANGE]
    ├── test_no_hardcoded_model_ids.py        # [NO CHANGE]
    ├── test_watsonx_sdk_construction.py      # [NEW] SDK mode I/O-free tests
    ├── test_watsonx_litellm_construction.py  # [NEW] LiteLLM mode tests
    ├── test_watsonx_timeout_config.py        # [NEW] Timeout configuration tests
    ├── test_watsonx_url_validation.py        # [NEW] URL format validation tests
    ├── test_watsonx_no_retry.py              # [NEW] No-retry behavior tests
    ├── test_watsonx_fallback_integration.py  # [NEW] Fallback chain tests
    └── test_watsonx_observability.py         # [NEW] Span attribute tests

.github/workflows/
├── integration-ollama.yml       # [NO CHANGE] Existing Ollama workflow
└── integration-watsonx.yml      # [NEW] Manual-dispatch watsonx workflow

pyproject.toml                   # [MODIFY] ibm-watsonx-ai already present; add [project.optional-dependencies] litellm; raise [tool.coverage] fail_under 93 → 98 (+5pt/provider, tech.md)
.github/dependabot.yml           # [MODIFY] Add ibm-watsonx-ai (litellm grouping already present) with supply-chain-watch labels
```

**Structure Decision**: Single project structure (Option 1) is appropriate. This is a Python package with FastAPI API, following the existing pattern established by feature `001-agentic-platform`. The `src/pydantic_ai_sandbox/` layout with `llm/providers/` subdirectory cleanly separates provider implementations. Tests are organized by type (unit/integration) with hermetic defaults.

### File Structure Plan (responsibility + boundary per file)

Each row is the contract a `/sdd-tasks` task can pin via `_Boundary:_`. "Owns"
is the one-sentence responsibility; "Does NOT own" is the boundary.

| File | Owns (one sentence) | Does NOT own |
|------|---------------------|--------------|
| `llm/providers/watsonx.py` | `_build_watsonx(settings)` transport dispatch + `WatsonxSDKModel` (message mapping, `ModelAPIError` wrapping, lazy httpx client, `system`/`model_name`). | Env parsing/validation (Settings' job); fallback composition; the litellm package install. |
| `config.py` | New `watsonx_timeout_connect/read` fields + watsonx credential gate, transport normalization/default, URL-format and timeout validators. | HTTP I/O; transport dispatch; how the Model uses the values. |
| `llm/factory.py` | Drop `"watsonx"` from `_MVP_STUB_PROVIDERS`; route `"watsonx"` → `return _build_watsonx(settings)`. | Provider internals; fallback logic. |
| `llm/fallback.py` | (data-only) watsonx now flows through unchanged once de-stubbed. | Any code change — none required. |
| `tests/conftest.py` | watsonx fixtures + `_MANAGED_ENV_KEYS` additions. | Provider logic. |
| `tests/support/model_fakes.py` | watsonx `FunctionModel` doubles raising `ModelAPIError` for failover tests. | Live SDK calls. |
| `tests/unit/test_watsonx_*.py` (7 files) | One concern each: SDK construction (no-I/O), litellm construction, timeout config, URL validation, no-retry, fallback integration, observability. | Cross-concern assertions; live API. |
| `tests/unit/test_factory_dispatch.py` | Move watsonx case to success; keep anthropic/bedrock asserting `NotImplementedError`; update `_MVP_STUB_PROVIDERS` lock — **atomic with the factory edit**. | New provider behavior. |
| `tests/integration/test_watsonx_chat_e2e.py` | Opt-in (`RUN_INTEGRATION_WATSONX`) stateless `/healthz`+`/chat` check mirroring the Ollama lane. | Resource cleanup (stateless). |
| `.github/workflows/integration-watsonx.yml` | `workflow_dispatch`-only run + concurrency + explicit fail-on-missing-secret. | push/PR/cron triggers. |
| `pyproject.toml` | **Bump `ibm-watsonx-ai` 1.5.12 → `>=1.5.13`** (py3.14 import fix, ADR-1 — first foundation task); `[project.optional-dependencies] litellm`; `fail_under` 93 → 98. | Source logic. |
| `.github/dependabot.yml` | `ibm-watsonx-ai` watch entry with supply-chain labels. | Version pins. |

## Requirements Traceability

Numeric acceptance-criteria IDs (spec.md) → owning component. Drives
`/sdd-tasks` boundaries.

| Req IDs | Component / File |
|---------|------------------|
| 1.1 | `config.py` `LLMProvider` Literal (already satisfied) |
| 1.2, 1.4, 9.1, 9.2, 12.1 | `llm/factory.py` `_MVP_STUB_PROVIDERS` + `tests/unit/test_factory_dispatch.py` |
| 1.3, 1.5, 2.1–2.3, 2.7 | `llm/providers/watsonx.py` `_build_watsonx` + `WatsonxSDKModel` (2.7: `request` message/tool-call mapping) |
| 2.4, 2.5 | `config.py` transport `field_validator` (lower-case + valid-value message) |
| 2.6 | `llm/providers/watsonx.py` litellm import guard |
| 3.1, 3.2, 3.3 | `config.py` watsonx credential gate (`WATSONX_APIKEY` et al.) |
| 3.4 | enforced by existing `test_no_hardcoded_model_ids.py` + pre-commit hook |
| 4.1, 4.2, 4.3 | `config.py` URL-format validator (`urlparse`, no network) |
| 4.4, 6.2 | `WatsonxSDKModel.request` error wrapping → `ModelAPIError` |
| 5.1–5.5 | `config.py` timeout fields/validator + `watsonx.py` httpx timeout wiring |
| 5.6 | `WatsonxSDKModel` — `error.class` only, no duration attr |
| 6.1, 6.3, 6.4 | `WatsonxSDKModel` (no retry; Ollama-consistent) |
| 7.1–7.4 | `llm/fallback.py` (data-only) + `WatsonxSDKModel` `ModelAPIError` |
| 8.1–8.6 | `WatsonxSDKModel` `system`/`model_name`; litellm path via OpenAI adapter |
| 9.3–9.11 | `tests/unit/test_watsonx_*.py` + coverage ratchet in `pyproject.toml` (9.11: response-mapping test in `test_watsonx_sdk_construction.py`) |
| 10.1–10.3 | `tests/integration/test_watsonx_chat_e2e.py` |
| 11.1–11.3 | `.github/workflows/integration-watsonx.yml` |
| 11.4 | `.github/dependabot.yml` |
| 11.5 | `pyproject.toml` deps |
| 12.2 | `tasks.md` wording (and stale `002-multi-provider` stub messages) |

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

No violations detected. All constitutional principles are satisfied by the design.

## Phase 0: Research & Clarification Resolution

### Research Tasks

All [NEEDS CLARIFICATION] markers from Technical Context have been resolved through the specification's Clarifications section (Session 2026-06-08). The following research consolidates the technical decisions and their rationale.

### Research Findings

#### 1. IBM watsonx.ai SDK Integration

**Research Question**: How to integrate `ibm-watsonx-ai` SDK with pydantic_ai's Model abstraction?

**Findings**:
- pydantic_ai has no native watsonx Model (unlike Ollama, Anthropic, etc.)
- Requires custom `pydantic_ai.models.Model` subclass
- SDK provides `generate_text()` and `chat()` methods for non-streaming inference
- SDK handles authentication via API key and project ID
- SDK supports custom endpoint URLs for different watsonx deployments

**Decision**: Implement custom `WatsonxSDKModel(Model)` subclass wrapping `ibm-watsonx-ai` SDK
**Rationale**: Provides maximum control over observability attributes, minimizes dependencies, aligns with Constitution Principle II
**Alternatives Considered**:
- Use LiteLLM exclusively (rejected: adds dependency, less control)
- Wait for pydantic_ai native support (rejected: timeline uncertain)

#### 2. LiteLLM Integration Strategy

**Research Question**: How to support LiteLLM as optional transport while maintaining SDK as default?

**Findings**:
- LiteLLM supports watsonx via `watsonx/model-id` format
- pydantic_ai provides `LiteLLMProvider` for routing
- LiteLLM handles authentication and endpoint configuration
- Adds supply-chain dependency but simplifies implementation

**Decision**: Support both transports via `WATSONX_TRANSPORT` env var (default: `sdk`)
**Rationale**: Flexibility for different deployment contexts, SDK default minimizes dependencies
**Alternatives Considered**:
- SDK only (rejected: less flexibility)
- LiteLLM only (rejected: adds unnecessary dependency for default case)

#### 3. I/O-Free Construction Pattern

**Research Question**: How to validate configuration without network calls during construction?

**Findings**:
- Ollama provider uses `httpx.Client.send` patch for I/O-free testing
- URL validation can be done with `urllib.parse.urlparse` (no network)
- Credential presence can be checked without API calls
- Endpoint reachability requires network call (defer to runtime)

**Decision**: Validate URL format and credential presence only; defer reachability to runtime
**Rationale**: Preserves I/O-free construction (Constitution Principle III), fail-fast for obvious errors
**Alternatives Considered**:
- Full endpoint validation (rejected: violates I/O-free construction)
- No validation (rejected: violates fail-fast principle)

#### 4. Timeout Configuration Best Practices

**Research Question**: What are reasonable timeout defaults for LLM API calls?

**Findings**:
- LLM inference can take 30-120 seconds for complex prompts
- Network connect timeouts typically 10-30 seconds
- Read timeouts should account for model processing time
- Both SDK and LiteLLM support custom timeout configuration

**Decision**: 30s connect, 120s read defaults with env overrides
**Rationale**: Reasonable for LLM workloads, overridable for different contexts
**Alternatives Considered**:
- Shorter timeouts (rejected: LLM calls can be legitimately slow)
- No timeouts (rejected: can hang indefinitely)
- Different defaults per transport (rejected: adds complexity)

#### 5. Error Handling and Retry Strategy

**Research Question**: Should the provider implement retry logic for transient failures?

**Findings**:
- Ollama provider has no retry logic
- Fallback chain provides resilience at higher level
- Provider-level retries add complexity and latency
- Most errors (auth, invalid config) are not transient

**Decision**: No provider-level retries; rely on fallback chain
**Rationale**: Matches Ollama pattern, simpler implementation, fallback provides resilience
**Alternatives Considered**:
- Exponential backoff retries (rejected: adds complexity, fallback sufficient)
- Retry only for specific errors (rejected: hard to classify transient vs permanent)

#### 6. Observability Attribute Selection

**Research Question**: What observability attributes should watsonx spans include?

**Findings**:
- Ollama provider emits `gen_ai.system`, `gen_ai.request.model`, `error.class`
- pydantic_ai instrumentation derives attributes from Model properties
- Custom Model must set `system` and `model_name` properties
- Extended attributes (tokens, latency) add overhead

**Decision**: Standard attributes only (`gen_ai.system`, `gen_ai.request.model`, `error.class`)
**Rationale**: Lean spans matching Ollama, sufficient for debugging, minimal overhead
**Alternatives Considered**:
- Extended attributes (rejected: adds overhead, not needed for MVP)
- No observability (rejected: violates Constitution Principle IV)

#### 7. Integration Test Strategy

**Research Question**: How to test watsonx integration without breaking hermetic defaults?

**Findings**:
- Ollama uses `RUN_INTEGRATION_OLLAMA` opt-in flag
- Integration tests follow stateless single-request pattern
- No resource cleanup needed for stateless API calls
- CI workflow uses manual dispatch for cost control

**Decision**: Opt-in via `RUN_INTEGRATION_WATSONX`, stateless pattern, manual CI dispatch
**Rationale**: Hermetic defaults (Constitution Principle III), cost control, matches Ollama
**Alternatives Considered**:
- Always-on integration tests (rejected: violates hermetic defaults)
- Complex multi-request tests (rejected: adds complexity, not needed)

### Key Technical Decisions

1. **SDK vs LiteLLM Default**
   - **Decision**: SDK mode (`ibm-watsonx-ai`) is the default transport
   - **Rationale**: Minimizes supply-chain footprint, maximizes control, aligns with Constitution Principle II (configuration-driven)
   - **Alternatives Considered**: LiteLLM as default (rejected: adds dependency, less control over observability attributes)
   - **Implementation Note**: Requires custom `pydantic_ai.models.Model` subclass since pydantic_ai has no native watsonx Model

2. **I/O-Free Construction Strategy**
   - **Decision**: Validate URL format only (protocol, structure) without network calls
   - **Rationale**: Preserves I/O-free construction (Constitution Principle III), fail-fast for obvious errors, defer reachability to runtime
   - **Alternatives Considered**: Endpoint reachability check (rejected: violates I/O-free construction, adds startup latency)
   - **Implementation Note**: Use `urllib.parse.urlparse` for structure validation

3. **Timeout Configuration**
   - **Decision**: 30s connect, 120s read defaults with env overrides
   - **Rationale**: Reasonable for LLM API calls, overridable for different deployment contexts
   - **Alternatives Considered**: No timeouts (rejected: can hang indefinitely), shorter defaults (rejected: LLM calls can be slow)
   - **Implementation Note**: Apply to both SDK and LiteLLM transports

4. **Error Handling Without Retries**
   - **Decision**: No provider-level retry logic; fail immediately
   - **Rationale**: Matches Ollama provider pattern, relies on fallback chain for resilience (Constitution Principle IV)
   - **Alternatives Considered**: Provider-level retries (rejected: adds complexity, fallback chain provides resilience)
   - **Implementation Note**: Errors surface with observability spans, trigger fallback

5. **Observability Attributes**
   - **Decision**: Standard attributes only (`gen_ai.system`, `gen_ai.request.model`, `error.class`)
   - **Rationale**: Lean spans matching Ollama provider, sufficient for debugging
   - **Alternatives Considered**: Extended attributes (rejected: adds overhead, not needed for MVP)
   - **Implementation Note**: Custom SDK Model must set `system` and `model_name` properties for pydantic_ai instrumentation

6. **Integration Test Strategy**
   - **Decision**: Opt-in via `RUN_INTEGRATION_WATSONX`, stateless single-request pattern
   - **Rationale**: Hermetic defaults (Constitution Principle III), cost control, matches Ollama pattern
   - **Alternatives Considered**: Always-on integration tests (rejected: violates hermetic defaults), complex multi-request tests (rejected: adds complexity)
   - **Implementation Note**: Follow `test_ollama_chat_e2e.py` pattern

### Dependencies Analysis

**Required Dependencies**:
- `ibm-watsonx-ai` - Direct SDK integration (default transport)
  - Version: Latest stable (to be pinned in pyproject.toml)
  - Supply-chain risk: Mitigated via dependabot monitoring
  - API stability: Assumed stable for production use

**Optional Dependencies**:
- `litellm` - Optional routing transport
  - Version: Latest stable (to be pinned in pyproject.toml)
  - Supply-chain risk: Mitigated via dependabot monitoring
  - API stability: Assumed stable for watsonx.ai use

**Existing Dependencies** (no changes):
- `pydantic-ai` - Agent framework with custom Model support
- `fastapi` - API framework
- `logfire` - Observability
- `httpx` - HTTP client (for testing)
- `pytest`, `pytest-cov`, `respx` - Testing framework

### Integration Points

1. **Factory Integration** (`src/pydantic_ai_sandbox/llm/factory.py`)
   - Remove `"watsonx"` from `_MVP_STUB_PROVIDERS`
   - Add watsonx case to `build_model` function
   - Dispatch to `watsonx.py` provider

2. **Configuration Integration** (`src/pydantic_ai_sandbox/config.py`)
   - Add watsonx-specific config fields
   - Validate required credentials at startup
   - Support transport mode selection

3. **Fallback Chain Integration** (`src/pydantic_ai_sandbox/llm/fallback.py`)
   - No code changes needed
   - watsonx automatically participates once removed from stub list
   - Preserve silent-drop logic for remaining stubs

4. **Observability Integration** (`src/pydantic_ai_sandbox/logging_setup.py`)
   - No code changes needed
   - Existing Logfire setup captures spans
   - Custom SDK Model must populate standard attributes

5. **Testing Integration** (`tests/conftest.py`, `tests/support/model_fakes.py`)
   - Add watsonx fixtures for unit tests
   - Add watsonx test doubles (FunctionModel substitutes)
   - Follow Ollama testing patterns

## Phase 1: Design Artifacts

### Data Model

**Note**: Phase 1 design artifacts (data model, contracts, quickstart) are documented inline in this section by choice; the canonical traceability matrix and File Structure Plan below drive `/sdd-tasks`.

#### Entity 1: `Settings` watsonx extensions (env source of truth)

The env source of truth is the existing frozen `Settings(BaseSettings)` in
`config.py` — **not** a separate config object. This mirrors the Ollama
precedent (`_build_ollama(settings)` reads `settings.ollama_*` directly) and
the `structure.md` rule that builders take `Settings`. Some fields already
exist; this feature **adds** timeout fields and the cross-field validators.

**Existing fields (reused, names are authoritative):**
- `watsonx_url: str | None` — endpoint URL (env `WATSONX_URL`)
- `watsonx_apikey: SecretStr | None` — API key (env **`WATSONX_APIKEY`**, per Clarification 2026-06-08 — matches the existing field, `conftest._MANAGED_ENV_KEYS`, and the IBM SDK's own env var; **not** `WATSONX_API_KEY`)
- `watsonx_project_id: str | None` — project ID (env `WATSONX_PROJECT_ID`)
- `watsonx_model_id: str | None` — model identifier (env `WATSONX_MODEL_ID`)
- `watsonx_transport: Literal["sdk", "litellm"] | None` — transport (env `WATSONX_TRANSPORT`)

**New fields:**
- `watsonx_timeout_connect: int = 30` — connect timeout, seconds (env `WATSONX_TIMEOUT_CONNECT`)
- `watsonx_timeout_read: int = 120` — read timeout, seconds (env `WATSONX_TIMEOUT_READ`)

**Validation rules (in `Settings._check_provider_constraints` / dedicated validators):**
- **Credential gate (Req 3.1/3.2):** the gate fires when watsonx is selected **either directly (`LLM_PROVIDER=watsonx`) OR as a member of `FALLBACK_ORDER`** (decision confirmed at plan-validation 2026-06-08). All of `watsonx_url` / `watsonx_apikey` / `watsonx_project_id` / `watsonx_model_id` must then be present; a missing one raises `ValueError` **naming the specific env var** (e.g. `"WATSONX_PROJECT_ID is required when ..."`). **Asymmetry note:** the existing Ollama gate (`config.py` `_check_provider_constraints`) only validates on *direct* selection, not on fallback membership. watsonx is intentionally stricter so that a `FALLBACK_ORDER=ollama,watsonx` deployment with partial watsonx creds fails fast at boot (SC-004/SC-005) rather than surfacing at the first failover. **Interaction with `fallback.py`:** once watsonx leaves `_MVP_STUB_PROVIDERS` it is no longer filtered out of the chain (fallback.py:102), so a creds-less watsonx in `FALLBACK_ORDER` *will* be constructed — the boot-time gate is what keeps that from deferring the failure to runtime. A unit test must pin "watsonx in `FALLBACK_ORDER` + missing cred → boot-time `ValueError` naming the var". Currently only Ollama is gated — this validator is net-new.
- **Transport normalization (Req 2.4/2.5):** `WATSONX_TRANSPORT` is lower-cased before the `Literal` check via a `field_validator(mode="before")`, so `SDK`/`LiteLLM` are accepted (the `Literal` alone is case-sensitive). Unset → defaults to `"sdk"` (Req 2.2). An out-of-set value raises `ValueError` whose message **lists the valid values** `("sdk", "litellm")` (Req 2.5), replacing pydantic's generic `Literal` error.
- **URL format (Req 4.1/4.2):** `watsonx_url` is validated for protocol + netloc via `urllib.parse.urlparse` (no network); invalid format raises `ValueError` with a detailed message. No reachability probe (Req 4.3).
- **Timeouts (Req 5.5):** `watsonx_timeout_connect` / `watsonx_timeout_read` must be positive integers; non-positive / non-numeric raises `ValueError`.
- **litellm availability (Req 2.6):** enforced lazily in the builder's litellm branch (import guard), not in `Settings`, so `sdk`-only deployments never need litellm installed.

**Relationships:**
- Consumed by `_build_watsonx(settings)` (the factory builder).
- An optional internal frozen `_WatsonxRuntimeConfig` dataclass MAY bundle the
  validated values handed to `WatsonxSDKModel`, but it carries no env logic —
  `Settings` remains the single source.

#### Entity 2: WatsonxSDKModel

Custom `pydantic_ai.models.Model` subclass for direct SDK integration (the
genuine net-new unit; pydantic_ai ships no native watsonx Model).

**Terminology Note**: This class is referred to as "Custom watsonx Model" in spec.md glossary and requirements, but the actual implementation class name is `WatsonxSDKModel` for clarity and consistency with the codebase naming conventions.

**Abstract surface to implement (pydantic_ai V2 `Model` ABC):**
- `model_name` (`@property` decorator) → returns `settings.watsonx_model_id` → drives `gen_ai.request.model` (Req 8.6)
- `system` (`@property` decorator) → returns `"watsonx"` → drives `gen_ai.system` (Req 8.6)
- `async def request(self, messages, model_settings, model_request_parameters) -> ModelResponse` — note the **third positional `model_request_parameters: ModelRequestParameters`** argument, which the earlier draft omitted; it is required by the ABC.
- `request_stream(...)` — verified at plan-validation against the pinned `pydantic-ai 2.0.0b6`: **only `request` is abstract; `request_stream` is NOT** (`request_stream.__isabstractmethod__ == False`). It is still overridden here to `raise NotImplementedError` defensively — not to make the class instantiable (it already is), but so that any accidental streaming path fails loud with a clear message instead of hitting the base default and producing a confusing error. Streaming is out of scope.

**Message mapping (Req R2 — RESOLVED in research.md R2 against `ibm-watsonx-ai 1.5.13`):**
- Use the **async** **`ModelInference.achat(messages: list[dict], params=None, tools=None, tool_choice=None, tool_choice_option=None) -> dict`** (OpenAI-shaped), **not** the synchronous `chat()` and **not** `generate_text()`. `Model.request` is `async`; the sync `chat()` would block the event loop, so the verified async coroutine `achat()` (identical signature, returns the same dict) is the correct call. It pairs with the `async_httpx_client` timeout wiring below. `achat` supports tool-calls.
- Translate pydantic_ai `list[ModelMessage]` (system / user / tool parts) → OpenAI-style `list[{"role","content"}]` dicts; non-streaming only.
- Build `ModelResponse` from the returned dict: `resp["choices"][0]["message"]` → `parts` (text + any `tool_calls`), `resp["usage"]` → usage, `resp["choices"][0]["finish_reason"]` → finish_reason, `resp["id"]` → `provider_response_id`. Exhaustive part handling, no silent drops (`models/CLAUDE.md`).

**Internal state:**
- `_settings: Settings` (or the optional `_WatsonxRuntimeConfig`) — validated values; no env access at request time.
- `_client: ModelInference` — `ibm-watsonx-ai` client, **lazily** constructed on first `request` so `__init__` stays I/O-free (Req 1.5). Construction wiring (research.md R3):
  - Timeouts inject via the **httpx client on `APIClient`**, not `Credentials` (which has no timeout arg): build `APIClient(credentials=Credentials(url, apikey), project_id=..., async_httpx_client=httpx.AsyncClient(timeout=httpx.Timeout(connect=watsonx_timeout_connect, read=watsonx_timeout_read)))`, then `ModelInference(model_id=..., api_client=that_client, max_retries=0, validate=False)`.
  - **`max_retries=0` is mandatory** (Req 6.1 / ADR-2): the SDK retries by default. A unit test (Req 9.7) pins this.
  - **`validate=False` is mandatory**: the SDK validates over the network at construction (default `validate=True`). Lazy construction keeps our `__init__` I/O-free, and `validate=False` avoids an extra validation round-trip (and second failure surface) on the first call.

**Error handling — CRITICAL (Req 6.x / 7.x / 4.4):**
- **`request` MUST translate every SDK failure into `pydantic_ai.exceptions.ModelAPIError` (or a subclass).** Error-classification matrix (research.md R5): catch the SDK base **`ibm_watsonx_ai.wml_client_error.WMLClientError`** (covers `ApiRequestFailure`, `AuthenticationError`, `InvalidCredentialsError`, `ExceededLimitOfAPICalls` [rate limit], `ReadingDataTimeoutError`, …) **plus the underlying httpx errors** (`httpx.TimeoutException`, `httpx.ConnectError`, `httpx.HTTPError`) since the SDK is httpx-based. `FallbackModel`'s default `fallback_on` is `(ModelAPIError,)` (verified, pydantic_ai 2.0.0b6) — if the Model raises a raw `TimeoutError` / SDK exception, **failover silently does not happen** and Req 7.1/7.2/9.8 break in the real chain even while passing in isolation.
- **No retries** of any kind (Req 6.1); do not enable SDK-internal retry config. Fail on the first error.
- Surface the error so pydantic_ai instrumentation stamps `error.class` (Req 8.2); timeouts carry **only** `error.class` — no duration attribute (Req 5.6, resolved against 8.3/8.4).

**Observability:**
- `system="watsonx"` → `gen_ai.system`; `model_name=watsonx_model_id` → `gen_ai.request.model`; `error.class` on failure. Exactly the standard three (Req 8.3); reuses the existing `extra_patterns` scrubbing unchanged (Req 8.5).

#### Entity 3: `_build_watsonx` builder

The builder follows the established `_build_ollama(settings) -> Model` shape
(`structure.md`): exported as `_build_watsonx` from `llm/providers/watsonx.py`,
called by `factory.get_model`, I/O-free.

**Signature:**
```python
def _build_watsonx(settings: Settings) -> Model:
    """Build a watsonx-backed Model per WATSONX_TRANSPORT. I/O-free."""
```

**Logic (transport dispatch):**
- `transport == "sdk"` (default) → `return WatsonxSDKModel(settings)`.
- `transport == "litellm"` →
  - **Import guard first:** `try: import litellm except ImportError: raise <ValueError naming 'litellm'>` (Req 2.6).
  - Build an httpx client carrying the connect/read timeouts (Req 5.4), then:
    ```python
    return OpenAIChatModel(
        model_name=f"watsonx/{settings.watsonx_model_id}",
        provider=LiteLLMProvider(api_key=..., api_base=..., http_client=...),
    )
    ```
  - **`LiteLLMProvider` is a *Provider*, not a *Model*** — returning it directly would not satisfy `Agent`'s `Model` contract. Wrap in `OpenAIChatModel(model_name=f"watsonx/{model_id}", provider=LiteLLMProvider(...))` (the litellm path reuses pydantic_ai's OpenAI adapter, which auto-stamps `gen_ai.system`/`gen_ai.request.model`).
  - **Credential routing (RESOLVED, research.md R4):** `LiteLLMProvider(*, api_key, api_base, openai_client, http_client)` has **no `project_id` param**. Route `apikey → api_key`, `url → api_base`; **`project_id` reaches litellm via the `WATSONX_PROJECT_ID` env var** (already set by the deployment), not a constructor arg. Timeouts inject via `http_client` (a custom async HTTP client). The litellm RESPX test (Req 9.4) must set `WATSONX_PROJECT_ID` in its env fixture.

**Integration:**
- `factory.get_model("watsonx")` calls `return _build_watsonx(settings)` (today it calls the `Never` stub).
- `"watsonx"` is removed from `_MVP_STUB_PROVIDERS` **in the same atomic edit** as updating `test_factory_dispatch.py` (the frozenset is dual-locked by that test — Req 1.2 / 12.1).
- Once out of the stub set, `_build_fallback` includes watsonx with no code change (Req 7.3); failover correctness depends entirely on `WatsonxSDKModel` raising `ModelAPIError` (see Entity 2).

### API Contracts

#### Contract 1: WatsonxSDKModel Interface

**Purpose**: Define the contract for the custom SDK Model implementation.

**Interface**:
```python
from pydantic_ai.exceptions import ModelAPIError
from pydantic_ai.models import Model, ModelRequestParameters
from pydantic_ai.messages import ModelMessage, ModelResponse
from pydantic_ai.settings import ModelSettings


class WatsonxSDKModel(Model):
    """Custom pydantic_ai Model for IBM watsonx.ai SDK integration."""

    def __init__(self, settings: Settings) -> None:
        """I/O-free construction. Validation already done by Settings.

        Raises:
            ValueError: surfaced via Settings if URL/timeout/credentials invalid.
        """

    @property
    def system(self) -> str:
        """Return 'watsonx' → gen_ai.system (Req 8.6).
        
        This property decorator enables pydantic_ai instrumentation to derive
        the gen_ai.system span attribute automatically.
        """
        return "watsonx"

    @property
    def model_name(self) -> str:
        """Return the configured model id → gen_ai.request.model (Req 8.6).
        
        This property decorator enables pydantic_ai instrumentation to derive
        the gen_ai.request.model span attribute automatically.
        """
        return self._settings.watsonx_model_id

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,  # required by the ABC
    ) -> ModelResponse:
        """Execute one non-streaming inference via ibm-watsonx-ai.

        Maps messages → ModelInference.achat(...) [async] → ModelResponse.

        Raises:
            ModelAPIError: for EVERY failure (timeout, auth, 4xx/5xx, network).
                Raw SDK exceptions (WMLClientError, httpx.TimeoutException, ...)
                MUST be wrapped — FallbackModel.fallback_on defaults to
                (ModelAPIError,), so an unwrapped error breaks failover.
        """

    async def request_stream(self, *args, **kwargs):  # abstract — must exist
        """Streaming is out of scope (Req 'Out of Scope')."""
        msg = "watsonx SDK transport does not support streaming"
        raise NotImplementedError(msg)
```

**Observability Contract**:
- MUST emit `gen_ai.system="watsonx"` and `gen_ai.request.model=<watsonx_model_id>` on all requests (via the `system`/`model_name` properties).
- MUST surface failures so pydantic_ai stamps `error.class` — exactly the standard three attributes, no extras (Req 8.3/8.4).

**Error Contract**:
- MUST wrap all SDK failures in `ModelAPIError` (or subclass) so `FallbackModel` recovers them (Req 7.1/7.2). **This is the single highest-risk correctness point in the feature.**
- MUST NOT retry on any error (Req 6.1); first failure propagates immediately.
- Timeout failures expose `error.class` only — no timeout-duration attribute (Req 5.6, resolved against 8.3/8.4).

#### Contract 2: Configuration Schema

**Purpose**: Define the configuration schema for watsonx provider.

**Schema**:
```yaml
watsonx_config:
  type: object
  required:
    - api_key
    - project_id
    - url
    - model_id
  properties:
    apikey:
      type: string
      description: IBM watsonx.ai API key (SecretStr)
      env_var: WATSONX_APIKEY
    project_id:
      type: string
      description: IBM watsonx.ai project ID
      env_var: WATSONX_PROJECT_ID
    url:
      type: string
      format: uri
      description: IBM watsonx.ai endpoint URL
      env_var: WATSONX_URL
    model_id:
      type: string
      description: Model identifier
      env_var: WATSONX_MODEL_ID
    transport:
      type: string
      enum: [sdk, litellm]
      default: sdk
      description: Transport mode
      env_var: WATSONX_TRANSPORT
    timeout_connect:
      type: integer
      minimum: 1
      default: 30
      description: Connect timeout in seconds
      env_var: WATSONX_TIMEOUT_CONNECT
    timeout_read:
      type: integer
      minimum: 1
      default: 120
      description: Read timeout in seconds
      env_var: WATSONX_TIMEOUT_READ
```

**Validation Rules**:
- URL must match pattern: `^https?://[^/]+`
- Transport must be case-insensitive match for "sdk" or "litellm"
- Timeouts must be positive integers
- If transport="litellm", litellm package must be available

### Quickstart Guide

#### Prerequisites

1. **IBM watsonx.ai Account**
   - Active IBM Cloud account
   - watsonx.ai service provisioned
   - API key generated
   - Project ID obtained

2. **Environment Setup**
   - Python 3.14+
   - Repository cloned and dependencies installed via `mise install`

#### Configuration

Create `.env` file in repository root:

```bash
# Required: watsonx credentials
WATSONX_APIKEY=your_api_key_here
WATSONX_PROJECT_ID=your_project_id_here
WATSONX_URL=https://us-south.ml.cloud.ibm.com
WATSONX_MODEL_ID=<your-model-id>  # never hardcoded in src/; supplied via env

# Optional: Transport mode (default: sdk)
WATSONX_TRANSPORT=sdk  # or "litellm"

# Optional: Timeout configuration (defaults: 30s connect, 120s read)
WATSONX_TIMEOUT_CONNECT=30
WATSONX_TIMEOUT_READ=120

# Provider selection
LLM_PROVIDER=watsonx  # or "fallback" with FALLBACK_ORDER=ollama,watsonx
```

#### Usage Examples

**Example 1: Direct watsonx Provider**

```bash
# Set provider to watsonx
export LLM_PROVIDER=watsonx

# Start application
mise run dev

# Test chat endpoint
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello, watsonx!"}'
```

**Example 2: Fallback Chain with watsonx**

```bash
# Set fallback chain
export LLM_PROVIDER=fallback
export FALLBACK_ORDER=ollama,watsonx

# Start application (will try Ollama first, then watsonx)
mise run dev
```

**Example 3: LiteLLM Transport Mode**

```bash
# Use LiteLLM transport
export WATSONX_TRANSPORT=litellm

# litellm is an optional extra (not installed by default); install via uv
uv sync --extra litellm   # or: uv pip install litellm

# Start application
mise run dev
```

#### Testing

**Run Unit Tests (Hermetic, No External Calls)**

```bash
# Run all unit tests
mise run test

# Run watsonx-specific tests
pytest tests/unit/test_watsonx_*.py -v

# Check coverage
mise run coverage
```

**Run Integration Tests (Requires Live Credentials)**

```bash
# Opt-in flag; without it the watsonx integration tests skip
export RUN_INTEGRATION_WATSONX=1

# Routed through mise → uv (never bare pytest)
mise run test:integration
```

#### Troubleshooting

**Issue: "ValueError: WATSONX_APIKEY is required when LLM_PROVIDER=watsonx"**
- Solution: Ensure all required environment variables are set in `.env`
  (`WATSONX_APIKEY`, `WATSONX_PROJECT_ID`, `WATSONX_URL`, `WATSONX_MODEL_ID`)

**Issue: "ValueError: Invalid WATSONX_URL format"**
- Solution: URL must include protocol (https://) and valid domain

**Issue: "ImportError: litellm package not found"**
- Solution: Install litellm (`pip install litellm`) or use SDK transport (default)

**Issue: "TimeoutError: Request exceeded configured timeout"**
- Solution: Increase timeout values via `WATSONX_TIMEOUT_CONNECT` / `WATSONX_TIMEOUT_READ`

**Issue: "AuthenticationError: Invalid API key or project ID"**
- Solution: Verify credentials in IBM Cloud console

#### Next Steps

1. Review [spec.md](./spec.md) for detailed requirements
2. Review [plan.md](./plan.md) for implementation design
3. Run `/sdd-tasks 002-watsonx-provider` to generate actionable task breakdown
4. Follow task list for incremental implementation

## Phase 2: Implementation Phases

*Note: Detailed task breakdown will be generated by `/sdd-tasks` command.*

### Phase 2.1: Foundation (Blocking Prerequisites)
- Configuration schema and validation
- Factory integration (remove from stub list)
- Test infrastructure (fixtures, test doubles)

### Phase 2.2: SDK Transport Implementation
- Custom `WatsonxSDKModel` class
- I/O-free construction with URL validation
- Timeout configuration
- Observability attribute population
- Unit tests for SDK mode

### Phase 2.3: LiteLLM Transport Implementation
- LiteLLM routing integration
- Transport mode selection logic
- Dependency validation
- Unit tests for LiteLLM mode

### Phase 2.4: Error Handling & Fallback
- No-retry error handling
- Fallback chain integration
- Error observability
- Unit tests for error scenarios

### Phase 2.5: Integration Testing & CI
- Opt-in integration test
- CI workflow configuration
- Secret management
- Dependabot configuration

### Phase 2.6: Migration & Cleanup
- Update stub-related tests
- Remove stub terminology from documentation
- Final validation and coverage check

## Post-Phase 1 Constitution Re-Check

*GATE: Must pass before implementation begins.*

### Principle I: Specification-First Delivery ✅ PASS
- Design artifacts trace back to spec requirements
- Data model extracted from functional requirements
- API contracts generated from user actions
- Implementation phases organized by user story

### Principle II: Configuration-Driven Provider Behavior ✅ PASS
- All configuration sourced from environment variables
- No hardcoded values in design artifacts
- Fail-fast validation for missing/invalid configuration

### Principle III: Hermetic Default Quality Gates ✅ PASS
- Default tests remain I/O-free
- Integration tests explicitly opt-in
- Test doubles and fixtures support hermetic testing

### Principle IV: Observable and Fail-Fast Services ✅ PASS
- Fail-fast validation at construction
- Observability spans with standard attributes
- Errors surface explicitly without silent degradation

### Principle V: Incremental, Independently Verifiable Delivery ✅ PASS
- Implementation phases organized by functional capability
- Each phase leaves repository in runnable state
- User stories independently testable

**Post-Design Constitution Compliance**: ✅ ALL PRINCIPLES SATISFIED

## Next Steps

1. ✅ **Phase 0 Complete** - Research findings persisted in [research.md](./research.md), evidence-backed against the *installed* `ibm-watsonx-ai 1.5.13` / `pydantic-ai 2.0.0b6` on Python 3.14.5. **R2–R5 are now RESOLVED** (R2 message mapping via async `achat()`; R3 timeout via `APIClient(httpx_client=...)` + mandatory `max_retries=0`; R4 litellm `project_id` via env; R5 `WMLClientError`+httpx → `ModelAPIError` matrix). A **CRITICAL compatibility blocker** was discovered and resolved during this revision: `ibm-watsonx-ai 1.5.12` does not import on Python 3.14.5 — fixed by bumping to `>=1.5.13` (ADR-1), which is the first foundation task.
2. ✅ **Phase 1 Complete** - Design artifacts inline (data model, contracts, quickstart), plus the Requirements Traceability matrix and File Structure Plan below.
3. **Next Command**: Run `/sdd-tasks 002-watsonx-provider` to generate the task breakdown.

**Planning Phase Complete**: Constitution check passed pre- and post-design (source: README-referenced Constitution + steering). The four original CRITICAL design risks (ModelAPIError wrapping, LiteLLM-via-OpenAIChatModel, `WATSONX_APIKEY` naming, 5.6/8.3 attribute cap) are resolved, and the "fix recommended" revision additionally (a) resolved the open research items R2–R5 against the installed SDK ([research.md](./research.md)), (b) discovered and remediated a CRITICAL Python-3.14 import blocker in `ibm-watsonx-ai 1.5.12` (→ `>=1.5.13`, ADR-1), (c) confirmed the watsonx credential gate fires on direct **and** fallback selection, and (d) corrected the `request_stream` abstractness note.

## Notes

- Feature `001-agentic-platform` provides the patterns to follow: environment-driven configuration, fail-fast validation, hermetic testing, lean observability
- SDK transport is the default despite larger implementation surface: pydantic_ai has no native watsonx Model, so SDK mode requires a custom `Model` subclass
- Acceptance criteria 8.6 and 9.9 ensure observability attributes are not silently lost in the custom Model
- `_MVP_STUB_PROVIDERS` was a temporary MVP constraint; removing watsonx from it is a primary goal
- Anthropic and Bedrock remain stubs and continue to raise `NotImplementedError`
- The specification is comprehensive with 12 requirements, 21 success criteria, and explicit clarifications for all technical decisions
