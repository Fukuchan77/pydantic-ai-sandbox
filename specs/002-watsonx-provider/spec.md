# Feature Specification: IBM watsonx.ai Provider Implementation

**Feature Branch**: `002-watsonx-provider`  
**Created**: 2026-06-08  
**Status**: Requirements Generated  
**Input**: User description: "002-multi-provider を IBM watsonx.ai のみに修正して仕様設計からやり直してください"

## Overview

This feature upgrades the IBM watsonx.ai LLM provider from a `NotImplementedError`
stub into a production-ready implementation. It supports two transport modes —
direct `ibm-watsonx-ai` SDK integration (the default, to minimize supply-chain
footprint) and an optional LiteLLM-based routing path — while leaving the
existing `LLMProvider` vocabulary unchanged. The provider preserves the
platform's established patterns: environment-driven configuration, fail-fast and
I/O-free construction, hermetic-by-default tests, and lean observability spans.
Anthropic and Bedrock remain stubs and are out of scope.

**Prerequisites**: Feature `001-agentic-platform` is complete (50 unit tests +
1 integration test passing, 98% coverage, Constitution principles I–V satisfied).

## Clarifications

### Session 2026-06-08

- Q: Expected timeout behavior for watsonx.ai API calls in both transport modes? → A: Explicit defaults (30s connect, 120s read) with env overrides (`WATSONX_TIMEOUT_CONNECT`, `WATSONX_TIMEOUT_READ`).
- Q: How to handle SDK initialization errors (invalid URL, unreachable endpoint) during construction? → A: Fail fast at construction by validating URL format only (no network calls), preserving I/O-free construction.
- Q: Observability detail beyond `gen_ai.system` and `gen_ai.request.model`? → A: Standard attributes only (`system`, `model`, `error.class`), matching the Ollama provider; keep spans lean.
- Q: Retry logic for transient failures? → A: No retry logic; fail immediately and rely on the fallback chain for resilience.
- Q: Integration-test resource cleanup? → A: No cleanup; watsonx API calls in scope are stateless.
- Q: pydantic_ai has no native watsonx Model, so SDK mode requires a hand-rolled `Model` subclass. Keep SDK as default? → A: Yes, keep SDK as default (supply-chain minimization); LiteLLM remains the optional alternative. Acceptance criteria 8.6 / 9.9 make observability-attribute population explicit for the custom Model.
- Q: Env var name for the API key — spec draft said `WATSONX_API_KEY`, but the existing `Settings.watsonx_apikey` field, `conftest._MANAGED_ENV_KEYS`, and the IBM SDK itself all use `WATSONX_APIKEY`. Which wins? → A: Standardize on `WATSONX_APIKEY` (lowest churn; aligns with both the existing codebase and the SDK's native env var). Requirement 3.1 and all downstream artifacts use `WATSONX_APIKEY`.
- Q: Requirement 5.6 asked for "timeout-duration attributes" on the span, but 8.3/8.4/SC-018 cap span attributes to exactly `gen_ai.system`, `gen_ai.request.model`, `error.class` and forbid extras — which wins? → A: The lean cap wins. Timeout surfaces solely via `error.class` (the timeout exception class); no timeout-duration attribute is added. Logfire records span wall-clock duration intrinsically, so no information is lost. Requirement 5.6 revised accordingly.

## Scope

- **In scope**:
  - Functional watsonx.ai provider via `build_model("watsonx")` with `sdk` (default) and `litellm` transports.
  - Environment-driven credentials, transport selection, timeout configuration, and URL-format validation.
  - Lean, Ollama-consistent observability and no-retry error handling.
  - watsonx participation in the existing fallback chain.
  - Hermetic unit tests, gated live integration tests, and manual-dispatch CI workflow.
  - Migration away from the watsonx stub (`_MVP_STUB_PROVIDERS`).
- **Out of scope**: Anthropic/Bedrock implementations (remain stubs), streaming, vision/multimodal, provider-level retries, rate-limit backoff, multi-region, stateful conversation, extended observability, endpoint reachability checks.

## Glossary

| Term | Definition |
|------|------------|
| Transport mode | The watsonx integration path selected by `WATSONX_TRANSPORT`: `sdk` (direct `ibm-watsonx-ai` SDK, default) or `litellm` (routing via `LiteLLMProvider`). |
| I/O-free construction | Model instantiation that performs no network calls; only in-memory validation (e.g., URL format). |
| Fallback chain | The `LLM_PROVIDER=fallback` mechanism that tries providers in `FALLBACK_ORDER` until one succeeds. |
| Stub provider | A provider listed in `_MVP_STUB_PROVIDERS` whose `build_model` raises `NotImplementedError`. |
| Integration test gate | The `RUN_INTEGRATION_WATSONX` flag that opts into live-API integration tests; unset → tests skip. |
| Custom watsonx Model | The hand-rolled `pydantic_ai.models.Model` subclass over `ibm-watsonx-ai` used by SDK transport. |

## Requirements

<!-- EARS format (rules/ears-format.md). Numeric requirement IDs; hierarchical
acceptance-criteria IDs are the traceability keys for plan.md / tasks.md.
Parenthetical (FR-xxx / SC-xxx) tags preserve continuity with prior numbering. -->

### Requirement 1: Provider Activation and Vocabulary Preservation

watsonx is promoted from a stub to a real provider without changing the provider
vocabulary; Anthropic and Bedrock stay stubs.

**Acceptance Criteria**

1.1 THE system SHALL preserve the `LLMProvider` vocabulary `Literal["ollama","watsonx","anthropic","bedrock","fallback"]` unchanged. (FR-001)
1.2 THE system SHALL exclude `"watsonx"` from `_MVP_STUB_PROVIDERS` so watsonx is treated as a real provider. (FR-002)
1.3 WHEN `build_model("watsonx")` is invoked with valid configuration, THE system SHALL return a functional Model instance without raising `NotImplementedError`. (FR-003, SC-001)
1.4 WHEN `build_model("anthropic")` or `build_model("bedrock")` is invoked, THE system SHALL raise `NotImplementedError`, preserving their stub status. (FR-006)
1.5 WHEN the watsonx provider Model is constructed, THE system SHALL complete construction without making any network call. (FR-004)

### Requirement 2: watsonx Transport Mode Selection

The transport mode is configuration-driven, defaults to `sdk`, and is validated
at construction time.

**Acceptance Criteria**

2.1 WHERE `WATSONX_TRANSPORT=sdk`, THE system SHALL use direct `ibm-watsonx-ai` SDK integration via a `pydantic_ai.models.Model` subclass. (FR-007)
2.2 WHERE `WATSONX_TRANSPORT` is unset, THE system SHALL default to `sdk` transport mode. (FR-008)
2.3 WHERE `WATSONX_TRANSPORT=litellm`, THE system SHALL route requests through `LiteLLMProvider` using a `watsonx/...` model string. (FR-009)
2.4 THE system SHALL accept `WATSONX_TRANSPORT` values `sdk` and `litellm` case-insensitively. (FR-011)
2.5 IF `WATSONX_TRANSPORT` is set to any value other than `sdk` or `litellm`, THEN THE system SHALL fail fast at construction with an error message listing the valid values. (FR-011)
2.6 IF `WATSONX_TRANSPORT=litellm` and the `litellm` dependency is not installed, THEN THE system SHALL fail fast at construction with an error message naming the missing dependency. (FR-013)
2.7 WHERE `WATSONX_TRANSPORT=sdk`, THE system SHALL map pydantic_ai messages (system / user / tool parts) to and from `ModelInference.achat`, preserving text and tool-call parts in both the request payload and the resulting `ModelResponse` with no silent drops. (FR-057)

### Requirement 3: Credential Requirements and Fail-Fast Validation

Required credentials are validated at construction time, failing fast and naming
the offending variable.

**Acceptance Criteria**

3.1 THE system SHALL require `WATSONX_APIKEY`, `WATSONX_PROJECT_ID`, `WATSONX_URL`, and `WATSONX_MODEL_ID` for the watsonx provider. (FR-010)
3.2 IF any required watsonx credential is missing when the provider is constructed, THEN THE system SHALL fail fast with a `ValueError` naming the specific missing variable. (FR-005)
3.3 WHEN required watsonx credentials are missing at application startup, THE system SHALL fail within 2 seconds. (SC-004)
3.4 THE system SHALL source all watsonx model IDs and credentials from environment variables, with no hardcoded model IDs, API keys, or endpoint values in source code. (SC-008)

### Requirement 4: URL Format Validation (I/O-free)

`WATSONX_URL` is validated for structure only; reachability is deferred to
runtime to preserve I/O-free construction.

**Acceptance Criteria**

4.1 WHEN the watsonx provider is constructed, THE system SHALL validate `WATSONX_URL` for valid structure (protocol and domain) without making network calls. (FR-039, SC-016)
4.2 IF `WATSONX_URL` has an invalid format, THEN THE system SHALL fail fast at construction with a detailed message describing the validation failure. (FR-040)
4.3 THE system SHALL NOT perform endpoint reachability or connectivity checks during construction. (FR-041)
4.4 WHEN an unreachable endpoint or DNS failure occurs during the first API call, THE system SHALL surface the network error at runtime with error classification in observability spans. (FR-042, SC-017)

### Requirement 5: Timeout Configuration

Connect and read timeouts have sensible defaults, are overridable by environment,
and apply to both transports.

**Acceptance Criteria**

5.1 THE system SHALL apply a default connect timeout of 30 seconds and a default read timeout of 120 seconds for watsonx API calls. (FR-032, FR-033, SC-014)
5.2 WHERE `WATSONX_TIMEOUT_CONNECT` is set, THE system SHALL use it as the connect timeout in seconds. (FR-032)
5.3 WHERE `WATSONX_TIMEOUT_READ` is set, THE system SHALL use it as the read timeout in seconds. (FR-033)
5.4 THE system SHALL apply the configured timeout values to both `sdk` and `litellm` transport modes. (FR-035)
5.5 IF a timeout value is not a positive integer (negative, zero, or non-numeric), THEN THE system SHALL fail fast at construction with a clear error message. (FR-034)
5.6 WHEN a timeout expires during an API call, THE system SHALL surface the timeout solely through the span's `error.class` attribute (the timeout exception class), adding NO timeout-duration attribute, to stay within the lean attribute cap of 8.3/8.4. Span wall-clock duration is recorded intrinsically by Logfire. (FR-036, SC-015)

### Requirement 6: Error Handling Without Retries

The provider never retries; resilience comes from the fallback chain, matching
Ollama behavior.

**Acceptance Criteria**

6.1 THE system SHALL NOT implement retry logic in the watsonx provider for any error type. (FR-047)
6.2 WHEN the watsonx provider encounters any error (network, timeout, authentication, or rate limit), THE system SHALL fail immediately and surface it with observability. (FR-048, SC-019)
6.3 THE system SHALL rely on the existing fallback chain for resilience rather than provider-level retries. (FR-049)
6.4 THE system SHALL maintain error-handling consistency with the existing Ollama provider (no retries). (FR-050)

### Requirement 7: Fallback Chain Integration

watsonx participates in the fallback chain and is no longer silently dropped.

**Acceptance Criteria**

7.1 WHILE `LLM_PROVIDER=fallback` with `FALLBACK_ORDER=ollama,watsonx`, WHEN Ollama fails, THE system SHALL attempt watsonx and log the failover. (SC-005)
7.2 WHEN the watsonx provider fails within a fallback chain, THE system SHALL fail over immediately to the next provider without retry attempts. (FR-052, SC-020)
7.3 THE system SHALL preserve `_build_fallback` silent-drop logic while no longer dropping watsonx from the chain. (FR-031)
7.4 WHEN the fallback chain is exercised with FunctionModel substitutes, THE system SHALL exhibit failover behavior matching existing fallback test patterns.

### Requirement 8: Observability Attributes

Spans carry the standard lean attribute set; the custom SDK Model must populate
identity attributes explicitly.

**Acceptance Criteria**

8.1 WHEN an Agent.run completes against the watsonx provider, THE system SHALL emit `gen_ai.system` (or `gen_ai.provider.name`) and `gen_ai.request.model` attributes on the span. (FR-022, SC-006)
8.2 WHEN the watsonx provider encounters an error during Agent.run, THE system SHALL include an `error.class` attribute on the span. (FR-023)
8.3 THE system SHALL limit watsonx span attributes to the standard set (`gen_ai.system`, `gen_ai.request.model`, `error.class`). (FR-045, SC-018)
8.4 THE system SHALL NOT capture extended attributes (token counts, latency breakdown, prompt/completion content, or model parameters). (FR-046)
8.5 THE system SHALL scrub sensitive information using the existing `extra_patterns=["prompt","tool_input","tool_output"]` configuration without adding provider-specific patterns. (FR-024)
8.6 THE custom watsonx SDK Model subclass SHALL set its `system` (e.g. `"watsonx"`) and `model_name` properties so pydantic_ai instrumentation derives `gen_ai.system` and `gen_ai.request.model`. (FR-055)

### Requirement 9: Hermetic Unit Testing

The default suite makes no external calls, proves I/O-free construction, and
guards the new behaviors.

**Acceptance Criteria**

9.1 THE system SHALL update `tests/unit/test_factory_dispatch.py` so the watsonx case asserts success instead of `NotImplementedError`. (FR-015)
9.2 THE system SHALL keep the Anthropic and Bedrock dispatch test cases asserting `NotImplementedError`. (FR-016)
9.3 THE system SHALL include unit tests proving I/O-free construction using `httpx.Client.send` and `httpx.AsyncClient.send` patches. (FR-017, FR-044)
9.4 THE system SHALL include unit tests for both SDK and LiteLLM transport modes, with RESPX-based tests for the LiteLLM path. (FR-020, FR-021)
9.5 THE system SHALL include unit tests for timeout configuration covering default, custom, and invalid values, plus simulated timeout scenarios. (FR-037, FR-038)
9.6 THE system SHALL include unit tests for URL format validation, asserting valid formats pass and invalid formats fail fast with detailed messages. (FR-043)
9.7 THE system SHALL include unit tests confirming no retry attempts occur for any error type. (FR-051)
9.8 THE system SHALL include unit tests verifying immediate failover in fallback chains when watsonx fails. (FR-052)
9.9 THE system SHALL include a unit test asserting an Agent.run against the watsonx SDK Model produces non-empty `gen_ai.system` and `gen_ai.request.model` span attributes. (FR-056)
9.10 THE default unit test suite SHALL make zero external API calls and maintain at least 98% coverage. (SC-002, SC-010)
9.11 THE system SHALL include a unit test asserting that a successful SDK request maps a representative `achat` response into a `ModelResponse` with correct text parts, tool-call parts, `usage`, and `finish_reason`. (FR-058)

### Requirement 10: Integration Testing

Live tests are opt-in, minimal-contract, and stateless.

**Acceptance Criteria**

10.1 WHERE `RUN_INTEGRATION_WATSONX` is set, THE system SHALL run the watsonx integration tests; WHERE it is unset, THE system SHALL skip them. (FR-018)
10.2 WHEN the watsonx integration tests run, THE system SHALL verify that `/healthz` returns 200, `/chat` returns 200, and the ChatResponse structure is valid. (FR-019, SC-003)
10.3 THE watsonx integration tests SHALL follow the stateless single-request pattern of `tests/integration/test_ollama_chat_e2e.py` without resource-cleanup logic. (FR-053, FR-054, SC-021)

### Requirement 11: CI/CD and Security

Integration runs are manual and cost-controlled; dependencies are tracked.

**Acceptance Criteria**

11.1 THE system SHALL store watsonx API credentials in CI secrets for integration testing. (FR-025)
11.2 THE system SHALL provide an `integration-watsonx.yml` workflow triggered exclusively by manual `workflow_dispatch`, with concurrency controls. (FR-026, FR-027, SC-007)
11.3 IF required secrets are missing in the CI environment, THEN the integration-test workflow SHALL fail explicitly rather than skip. (FR-028)
11.4 THE system SHALL register `ibm-watsonx-ai` and `litellm` in `dependabot.yml` with supply-chain-watch labels. (FR-014)
11.5 THE system SHALL require `ibm-watsonx-ai` (bumped to the Python-3.14-compatible `>=1.5.13`, per ADR-1) as a dependency and `litellm` as an optional dependency in `pyproject.toml`. (FR-012, FR-013)

### Requirement 12: Migration and Cleanup

Stub-era artifacts are updated to reflect watsonx's new real status.

**Acceptance Criteria**

12.1 THE system SHALL update or remove `test_mvp_stub_providers_lock` to reflect that watsonx is no longer a stub. (FR-029)
12.2 THE system SHALL update `tasks.md` descriptions to remove "stub" terminology for watsonx-related tasks. (FR-030)

## Non-Functional Requirements

- **Startup latency (fail-fast)**: Application startup SHALL fail within 2 seconds when required watsonx credentials are missing or invalid. (SC-004)
- **Test coverage**: Code coverage SHALL remain at or above 98%, with all 50+ existing unit tests passing and no regressions. (SC-002, SC-009, SC-010)
- **Hermetic defaults**: The default test suite SHALL make zero external API calls. (SC-002)
- **Quality gates**: All ruff, pyright, and pre-commit checks SHALL pass. (SC-011)
- **Security**: Security scans (pip-audit, ruff `S` rules, gitleaks) SHALL show no new vulnerabilities, and no secrets or hardcoded model IDs SHALL appear in source. (SC-008, SC-012)
- **Constitution compliance**: Principles I–V (specification-first, configuration-driven, hermetic defaults, observable/fail-fast, incremental delivery) SHALL remain fully satisfied. (SC-013)
- **Observability overhead**: watsonx spans SHALL carry only the standard three attributes, matching the Ollama provider. (SC-018)

## Success Criteria (Measurable Outcomes)

- **SC-001**: watsonx handles chat requests and returns valid responses in both SDK and LiteLLM modes when configured.
- **SC-002**: Unit suite maintains ≥98% coverage with zero external API calls by default.
- **SC-003**: Integration tests pass when credentials are provided, validating end-to-end functionality.
- **SC-004**: Startup fails within 2 seconds with a clear message when required credentials are missing.
- **SC-005**: Fallback chains including watsonx fail over to watsonx with proper observability.
- **SC-006**: All watsonx spans include `gen_ai.system` and `gen_ai.request.model`.
- **SC-007**: CI runs watsonx integration tests on manual trigger with proper secret management.
- **SC-008**: No hardcoded model IDs, API keys, or watsonx-specific values exist in source.
- **SC-014**: Timeout configuration works with defaults (30s/120s) and env overrides.
- **SC-015**: Timeout errors are captured in spans via `error.class` (no extra duration attribute) and trigger failover in fallback chains.
- **SC-016**: URL format validation catches invalid URLs at construction with detailed messages, no network calls.
- **SC-017**: Network errors surface at runtime with observability, not during construction.
- **SC-018**: Spans contain only standard attributes (system, model, error.class).
- **SC-019**: Provider fails immediately on all errors without retries.
- **SC-020**: Fallback chains handle watsonx failures with immediate failover.
- **SC-021**: Integration tests execute without resource cleanup, confirming stateless interaction.

## Assumptions

1. `ibm-watsonx-ai` SDK is stable for production with proper version pinning.
2. LiteLLM is stable for watsonx.ai use, with supply-chain risk mitigated via dependabot.
3. Operators have valid watsonx.ai credentials (API key, project ID, URL, model ID).
4. Integration environments have network access to watsonx.ai endpoints.
5. Configured watsonx model IDs are available in the target project.
6. Pydantic AI V2 beta maintains stable APIs for custom Model implementations and `LiteLLMProvider`.
7. CI supports secure secret storage for watsonx credentials.
8. Direct SDK integration is preferred over LiteLLM to minimize dependencies and maximize control.
9. Anthropic and Bedrock remain stubs for this feature scope.
10. Default timeouts (30s connect, 120s read) are reasonable and overridable.
11. URL format validation (protocol, structure) is sufficient for fail-fast without network checks.
12. Standard observability attributes are sufficient without extended attributes.
13. The existing fallback chain provides adequate resilience without provider-level retries.
14. Transient failures are rare enough that immediate failover is acceptable.
15. watsonx.ai API calls in scope are stateless and require no cleanup.

## Dependencies

- **Upstream**: Feature `001-agentic-platform` complete and merged.
- **Required library**: `ibm-watsonx-ai` (SDK transport, default).
- **Optional library**: `litellm` (LiteLLM transport).
- **CI infrastructure**: Secret storage and workflow configuration.
- **Provider account**: Active IBM watsonx.ai account with valid credentials.

## Out of Scope / Future Work

- Anthropic and Bedrock real implementations (remain stubs).
- Streaming responses; vision/multimodal support.
- Provider-specific advanced features (custom parameters, fine-tuned models).
- Cost tracking/optimization; sophisticated rate-limit backoff.
- Provider health monitoring and circuit breakers.
- watsonx pagination control; multi-region watsonx.
- Adaptive timeout strategies; endpoint reachability checks during construction.
- Extended observability (token counts, latency breakdown, prompt/completion content, model parameters).
- Provider-level retry logic; stateful conversation management; integration-test resource cleanup.

## Notes

- `001-agentic-platform` provides the patterns for environment-driven configuration, fail-fast validation, and hermetic testing to follow.
- SDK transport is the default despite a larger implementation surface: pydantic_ai ships no native watsonx `Model`, so SDK mode entails authoring a custom `Model` subclass over `ibm-watsonx-ai` (non-streaming `generate_text`/`chat`). Acceptance criteria 8.6 and 9.9 ensure observability attributes are not silently lost.
- `_MVP_STUB_PROVIDERS` was a temporary MVP constraint; removing watsonx from it is a primary goal. Anthropic and Bedrock remain in it and continue to raise `NotImplementedError`.
- **Steering context note**: `.sdd/steering/` contains `product.md`, `tech.md`, and `structure.md`; requirements and the downstream plan were aligned against them (Python 3.14, coverage ratchet "+5pt per provider-impl task", downward-only layering, secrets as `SecretStr`, `mise`-routed quality gates).
