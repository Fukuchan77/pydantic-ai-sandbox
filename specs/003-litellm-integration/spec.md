# 003-litellm-integration — Requirements

**Feature Branch**: `003-litellm-integration`
**Created**: 2026-06-09
**Status**: Draft
**Input**: Create a LiteLLM-backed `Model` for Pydantic AI (provider-agnostic),
customizing the existing `pydantic-ai-litellm` library as the base, and wrap it
for watsonx where needed. Supersedes the broken `_build_litellm()` transport
discovered during `002-watsonx-provider` live verification.

## Overview

`002-watsonx-provider` shipped a dual-transport watsonx provider. Its `litellm`
transport reuses Pydantic AI's `OpenAIChatModel` over `LiteLLMProvider`, but live
verification proved that path non-functional: `LiteLLMProvider` is a thin
`AsyncOpenAI` wrapper that POSTs to `/chat/completions`, an endpoint watsonx.ai
does not expose — every request 404s. The fix is to route through the **LiteLLM
SDK itself** (`litellm.acompletion()`), which owns the per-provider request and
response translation that the bare OpenAI client cannot perform.

This feature delivers a **general-purpose `LiteLLMModel`** — a Pydantic AI
`Model` subclass that wraps `litellm.acompletion()` for *any* LiteLLM-supported
backend — and a **thin watsonx wrapper** that configures it with the
`watsonx/<model_id>` route and watsonx credentials. The implementation is
**based on and customized from** the open-source `pydantic-ai-litellm` library
(`mochow13/pydantic-ai-litellm`), adapted to this project's Pydantic AI V2 (Beta)
`Model` ABC, Python 3.14 baseline, strict typing, and `ModelAPIError`/fallback
conventions. The value: operators gain a working `WATSONX_TRANSPORT=litellm`
path and a reusable LiteLLM model surface that future providers can route
through without bespoke SDK adapters.

## Clarifications

### Session 2026-06-09

- Q: Build a watsonx-only `LiteLLMWatsonxModel` (Bob's original framing), or a
  general LiteLLM model plus a watsonx wrapper? → A: **General-purpose
  `LiteLLMModel` + thin watsonx wrapper.** The user's direction is "create a
  LiteLLM model for Pydantic AI, and a watsonx wrapper only if needed"; a
  provider-agnostic model is reusable and keeps watsonx-specifics at the
  configuration boundary.
- Q: Write the model from scratch or reuse `pydantic-ai-litellm`? → A: **Base it
  on `pydantic-ai-litellm` and customize.** That library already maps Pydantic
  AI messages/tools to `litellm.completion()`; this feature adapts its design to
  our V2 (Beta) `Model` ABC and project conventions rather than reinventing it.
- Q: Why does the existing `_build_litellm()` fail at runtime? → A: It builds an
  `OpenAIChatModel` over `LiteLLMProvider`, which is an `AsyncOpenAI` wrapper
  POSTing to `/chat/completions`; watsonx.ai does not expose that endpoint, so
  requests 404. Routing through `litellm.acompletion()` (which knows the watsonx
  request shape) is the corrective design.
- Q: Is streaming in scope for v1? → A: **Deferred but explicit.** `request_stream`
  may either route through LiteLLM streaming or fail loud with a clear message;
  it MUST NOT silently fall back to a non-streaming response.
- Q: How should the watsonx project ID be passed to LiteLLM? → A: **Use `WATSONX_PROJECT_ID` environment variable exclusively; fail fast if missing when transport is `litellm`.** This aligns with configuration-driven principles and prevents silent misconfiguration.
- Q: Which exception types should be caught and wrapped as `ModelAPIError`? → A: **Catch all exceptions from `litellm.acompletion()` using a broad except clause and wrap as `ModelAPIError`.** This ensures the fallback chain can recover from any LiteLLM or transport failure, maintaining resilience.
- Q: Should the upstream code be vendored or used as a dependency? → A: **Derive the implementation from the upstream design and carry an MIT attribution header — not a dependency, and not a copied source tree.** Upstream `pydantic-ai-litellm` targets `pydantic-ai-slim>=1.95.0` while this project uses `pydantic-ai==2.0.0b6`; the ABC shapes differ so much that copying the source would carry V1-isms to unwind. Instead, `LiteLLMModel` reuses this project's already-V2-correct OpenAI-shaped mapping (extracted to `_openai_mapping.py`) and authors the thin SDK wrapper fresh, attributing the upstream library (name, version, repo URL) in a header comment. This is faithful to "derived from, not authored from scratch" (Req 9.1) while avoiding a V1→V2 hand-port.
- Q: Where should shared OpenAI-shaped mapping utilities be placed? → A: **Extract to a new shared module `llm/_openai_mapping.py` that both watsonx and LiteLLM models import from.** This maintains clean separation of concerns, avoids circular dependencies, and makes the shared utilities discoverable and reusable.
- Q: Should streaming be implemented or deferred in v1? → A: **Raise `NotImplementedError` with a clear message for v1, deferring streaming to future work.** This maintains parity with the SDK transport's fail-loud approach and allows focused delivery of the core non-streaming functionality.

## Scope

- **In scope**:
  - A provider-agnostic `LiteLLMModel(Model)` wrapping `litellm.acompletion()`.
  - A watsonx wrapper/builder that configures `LiteLLMModel` for watsonx and
    replaces the broken `_build_litellm()`.
  - Extraction of OpenAI-shaped mapping helpers into a shared module.
  - Bidirectional message/tool mapping and response transformation.
  - `ModelAPIError` classification, timeout wiring, optional-dependency guard.
  - Hermetic test coverage + an opt-in live integration lane.
  - Adaptation of `pydantic-ai-litellm` to the project's V2 (Beta) ABC.
  - Explicit `NotImplementedError` for streaming requests in v1.
- **Out of scope**:
  - Streaming support via `litellm.acompletion(stream=True)` (deferred to future work).
  - Changes to the watsonx **SDK** transport (verified working in `002`).
  - Other providers (`ollama`, `anthropic`, `bedrock`).
  - LiteLLM **proxy** deployment/configuration.
  - LiteLLM features beyond chat completion (embeddings, fine-tuning, batching).
  - Migrating existing SDK-transport users to LiteLLM.
  - Caching / performance optimization layers.

## Glossary

| Term | Definition |
|------|------------|
| LiteLLM Model | The new `LiteLLMModel(pydantic_ai.models.Model)` wrapping `litellm.acompletion()`. |
| watsonx wrapper | The builder (`_build_litellm` replacement) that configures `LiteLLMModel` with the `watsonx/<id>` route and watsonx credentials. |
| Route prefix | LiteLLM's `<provider>/<model_id>` selector (e.g. `watsonx/<id>`) that picks the backend. |
| `pydantic-ai-litellm` | Upstream MIT library (`mochow13`) providing a `LiteLLMModel`; the base this feature customizes. |
| SDK transport | The existing `WatsonxSDKModel` over `ibm-watsonx-ai` (out of scope to change). |
| Attribution-based reuse | Deriving `LiteLLMModel` from the upstream library's design and citing it in an MIT attribution header, while reusing this project's own V2 mapping — not copying the upstream source tree and not taking it as a dependency. |
| OpenAI-shaped mapping | Message, tool, and response transformation utilities that convert between Pydantic AI types and OpenAI/LiteLLM formats. |

## Requirements

### Requirement 1: General-purpose LiteLLM Model

A reusable Pydantic AI `Model` that routes any LiteLLM-supported backend through
the LiteLLM SDK, replacing the unusable OpenAI-client transport.

**Acceptance Criteria**

1.1 THE system SHALL provide a `LiteLLMModel` class that subclasses
`pydantic_ai.models.Model` and routes chat requests through `litellm`'s async
completion API (`litellm.acompletion`).

1.2 THE LiteLLMModel SHALL accept a model name in LiteLLM's `<provider>/<model_id>`
route form, plus optional `api_key`, `api_base`, and `custom_llm_provider`
configuration.

1.3 WHEN a LiteLLMModel is constructed, THE LiteLLMModel SHALL perform no network
I/O — the first network call SHALL be the first `request()`.

1.4 THE LiteLLMModel SHALL expose a `model_name` property and a `system` property
so Pydantic AI instrumentation can derive the `gen_ai.request.model` and
`gen_ai.system` span attributes. THE `system` property SHALL be derived from the
provider segment of the `<provider>/<model_id>` route (e.g. `watsonx/<id>` →
`"watsonx"`), falling back to `"litellm"` only when the route carries no provider
prefix. This SHALL be the same value the model stamps as `provider_name` on the
returned `ModelResponse`, so that — for the watsonx route — `gen_ai.system` and
the response provider match the SDK transport (`"watsonx"`) and observability
parity is preserved (see Non-Functional Requirements → Observability).

1.5 THE LiteLLMModel SHALL expose a `profile` that keeps the watsonx-via-LiteLLM
path in tool-mode parity with the SDK transport: it SHALL NOT report
`supports_json_schema_output=True` in a way that causes `build_chat_agent` to
wrap `NativeOutput`/force `response_format`, since the SDK transport
deliberately avoids that for watsonx.

### Requirement 2: Request message and tool mapping

The model must translate the full Pydantic AI message history and tool catalog
into LiteLLM's expected input without losing information.

**Acceptance Criteria**

2.1 WHEN `request()` is called, THE LiteLLMModel SHALL map the `ModelMessage`
history (system prompts, rendered instructions, user prompts, prior assistant
turns, tool returns, retry prompts) to LiteLLM/OpenAI-shaped messages.

2.2 THE LiteLLMModel SHALL map registered function tools and output tools to
LiteLLM tool specifications, passing `None` when no tools are registered.

2.3 IF a message or content part type is unsupported (e.g. multimodal items),
THEN THE LiteLLMModel SHALL raise `NotImplementedError` naming the offending
type rather than silently dropping it.

2.4 IF a backend returns tool-call arguments that are double-encoded JSON (as
observed with some watsonx Granite models), THEN THE LiteLLMModel SHALL surface
the raw arguments faithfully without compounding the encoding.

### Requirement 3: Response transformation

**Acceptance Criteria**

3.1 WHEN `litellm.acompletion()` returns a completion, THE LiteLLMModel SHALL
build a `ModelResponse` containing text parts, tool-call parts, usage,
`finish_reason`, and `provider_response_id`.

3.2 THE LiteLLMModel SHALL map LiteLLM/OpenAI finish-reason keys to Pydantic AI's
normalised `FinishReason`, yielding `None` for absent or unmapped keys.

3.3 IF a completion response carries no choices, THEN THE LiteLLMModel SHALL
raise `UnexpectedModelBehavior`.

3.4 IF a usage block is absent, THEN THE LiteLLMModel SHALL return a zeroed
`RequestUsage` rather than failing.

### Requirement 4: Error classification and fallback

**Acceptance Criteria**

4.1 THE LiteLLMModel SHALL catch all exceptions raised by `litellm.acompletion()` using a broad except clause and wrap them as `pydantic_ai.exceptions.ModelAPIError` (chaining the original via `raise ... from`) so `FallbackModel.fallback_on` can recover from any LiteLLM or transport failure.

4.2 THE LiteLLMModel SHALL disable LiteLLM's own retry loop (`num_retries=0`) so
the fallback chain remains the sole resilience layer (ADR-2).

4.3 THE LiteLLMModel SHALL NOT wrap mapping errors (unsupported parts, malformed
responses) as `ModelAPIError` — these SHALL surface as `NotImplementedError` /
`UnexpectedModelBehavior` and fail loud.

### Requirement 5: Timeout configuration

**Acceptance Criteria**

5.1 THE LiteLLMModel SHALL pass the configured connect and read timeouts through
to `litellm.acompletion()`.

5.2 WHEN used for watsonx, THE timeout values SHALL be sourced from
`watsonx_timeout_connect` / `watsonx_timeout_read` in `Settings`.

### Requirement 6: Optional-dependency guard

**Acceptance Criteria**

6.1 IF the optional `litellm` package is not installed WHEN the LiteLLM transport
is selected, THEN THE builder SHALL fail fast with a `ValueError` naming the
`litellm` package and the install command — never a bare `ImportError`.

6.2 THE `litellm` import SHALL be function-local so importing the provider module
stays cheap for deployments that never select the LiteLLM transport.

### Requirement 7: watsonx wrapper and transport integration

The watsonx provider must route `WATSONX_TRANSPORT=litellm` through the new
`LiteLLMModel`, replacing the broken construction.

**Acceptance Criteria**

7.1 WHERE `WATSONX_TRANSPORT=litellm` is configured, THE watsonx builder SHALL
construct a `LiteLLMModel` configured with the `watsonx/<model_id>` route, the
watsonx API key, and the watsonx URL.

7.2 THE watsonx wrapper SHALL route the watsonx project ID to LiteLLM exclusively via the `WATSONX_PROJECT_ID` environment variable and SHALL fail fast with a clear error message if the variable is missing when `WATSONX_TRANSPORT=litellm` is selected.

7.3 THE watsonx builder SHALL replace the existing `_build_litellm()` that
constructs `OpenAIChatModel` over `LiteLLMProvider`, since that path POSTs to
`/chat/completions` and 404s against watsonx.ai.

7.4 THE `WATSONX_TRANSPORT=sdk` path (`WatsonxSDKModel`) SHALL remain unchanged
and continue to pass all existing tests.

7.5 THE secret API key SHALL be unwrapped only at the LiteLLM boundary
(`.get_secret_value()`) and SHALL never be logged.

### Requirement 8: Streaming behavior

**Acceptance Criteria**

8.1 THE LiteLLMModel SHALL implement `request_stream` as an async context manager that raises `NotImplementedError` with a clear, greppable message stating "LiteLLM streaming support deferred to future work" before yielding any content.

8.2 THE LiteLLMModel SHALL NOT silently downgrade a streaming request to a
non-streaming response.

8.3 THE `NotImplementedError` message SHALL be greppable and SHALL include the model name to aid debugging.

### Requirement 9: Basis on `pydantic-ai-litellm` and V2 compatibility

**Acceptance Criteria**

9.1 THE LiteLLMModel SHALL be derived from the design of the `pydantic-ai-litellm`
library (`mochow13/pydantic-ai-litellm`) rather than authored from scratch.

9.2 THE LiteLLMModel SHALL be compatible with this project's Pydantic AI V2 (Beta)
`Model` ABC (`request`, `request_stream`, `ModelRequestParameters`,
`RequestUsage`) and Python 3.14, reconciling the upstream library's
`pydantic-ai-slim>=1.95.0` / Python 3.13 baseline by reusing this project's
V2-correct mapping rather than copying the upstream source, hand-reconciling type differences at the wrapper boundary.

9.3 THE `LiteLLMModel` module SHALL carry an MIT attribution header citing the
upstream `pydantic-ai-litellm` library (name, version, and repository URL) as
the design basis, even though no upstream source tree is copied.

9.4 THE LiteLLMModel SHALL satisfy the project's strict typing
(`from __future__ import annotations`, pyright `strict`) and error idioms
(`msg` variable then `raise`).

### Requirement 10: Test coverage

**Acceptance Criteria**

10.1 THE hermetic test suite SHALL exercise construction, message
transformation, response transformation, error classification, and timeout
wiring with `litellm.acompletion()` mocked and zero external network calls.

10.2 THE feature SHALL add hermetic tests proving LiteLLM exceptions are
classified as `ModelAPIError` and recovered by `FallbackModel`.

10.3 THE feature SHALL extend the opt-in integration lane (gated by
`RUN_INTEGRATION_WATSONX=1`) to exercise live LiteLLM routing to watsonx.

10.4 THE existing test suites (SDK transport, factory dispatch, fallback) SHALL
continue to pass without modification.

10.5 THE hermetic test suite SHALL verify that `request_stream` raises `NotImplementedError` with the expected message format.

10.6 THE hermetic test suite SHALL verify observability parity and output-mode
gating without network I/O: that `system` resolves to the route provider segment
(`"watsonx"` for a `watsonx/<id>` route), that `provider_name` on the resulting
`ModelResponse` matches it, and that the model's `profile` does not force
`NativeOutput`/`response_format` for the watsonx route (Req 1.4, 1.5).

### Requirement 11: Shared mapping utilities

OpenAI-shaped mapping helpers must be extracted from the watsonx implementation
into a reusable module to avoid duplication.

**Acceptance Criteria**

11.1 THE system SHALL provide a shared module `llm/_openai_mapping.py` containing OpenAI-shaped message, tool, and response transformation utilities extracted from the watsonx implementation.

11.2 THE shared module SHALL export functions for mapping messages (`_map_messages`, `_map_request_part`, `_map_user_prompt`, `_map_assistant_message`), tools (`_map_tools`), usage (`_map_usage`), finish reasons (`_FINISH_REASON_MAP`), and building responses (`build_response`).

11.3 BOTH `WatsonxSDKModel` and `LiteLLMModel` SHALL import and use these shared utilities, eliminating code duplication.

11.4 THE extraction refactor SHALL NOT change the behavior of `WatsonxSDKModel` — all existing SDK transport tests SHALL continue to pass without modification.

## Non-Functional Requirements

- **Performance**: LiteLLMModel construction and configuration validation SHALL
  complete within 2 seconds with no network I/O.
- **Coverage**: The LiteLLM path SHALL meet or exceed the project's 98% coverage
  ratchet (`fail_under`).
- **Hermetic default**: The standard `pytest` run SHALL make no network calls;
  live exercise is opt-in behind `RUN_INTEGRATION_WATSONX=1`.
- **Observability**: The LiteLLM path SHALL emit the same span attributes as the
  SDK path (`gen_ai.system`, `gen_ai.request.model`, `error.class`). For the
  watsonx route this means `gen_ai.system` SHALL resolve to `"watsonx"` (via the
  route-segment derivation in Req 1.4), not `"litellm"`, so an operator filtering
  on `gen_ai.system="watsonx"` observes both transports identically.
- **Security**: No credentials in logs; `litellm` is an import-guarded optional
  extra; the security lane (gitleaks, pip-audit, ruff `S`) SHALL stay green.

## Out of Scope / Future Work

- Streaming support via `litellm.acompletion(stream=True)` (explicitly deferred; v1 raises `NotImplementedError`).
- Routing other providers (`ollama`, `anthropic`, `bedrock`) through LiteLLM,
  even though `LiteLLMModel` is provider-agnostic by design.
- LiteLLM proxy deployment and non-completion LiteLLM features.
- Multi-turn session state and response caching.

## Dependencies

- Completion of `002-watsonx-provider` (SDK transport, optional-dependency
  scaffolding, hermetic test infrastructure).
- `litellm` available as an optional extra in `pyproject.toml`.
- `pydantic-ai` V2 (Beta) `Model` ABC and `ModelResponse` types.
- Existing observability (Logfire + OpenTelemetry) and fallback infrastructure.

## References

- **Upstream library**: https://github.com/mochow13/pydantic-ai-litellm ·
  https://pypi.org/project/pydantic-ai-litellm/
- **Existing SDK adapter (V2 ABC reference)**:
  `src/pydantic_ai_sandbox/llm/providers/watsonx.py` (`WatsonxSDKModel`).
- **Broken transport to replace**: `_build_litellm()` in the same module.
- **Live 404 root cause & Granite tool-arg double-encoding**:
  `002-watsonx-provider` PDCA `do.md` verification findings.
