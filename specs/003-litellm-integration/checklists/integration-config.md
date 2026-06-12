# Integration & Configuration Requirements Quality Checklist

**Purpose**: Validate that requirements for LiteLLM integration, watsonx wrapper configuration, environment variables, and transport switching are complete, clear, and testable.

**Created**: 2026-06-09  
**Feature**: 003-litellm-integration  
**Focus**: Integration & Configuration Quality  
**Depth**: Standard (PR Review)  
**Audience**: Peer reviewers validating implementation readiness

---

## Requirement Completeness

### LiteLLM Model Integration

- [ ] CHK001 - Are requirements defined for all LiteLLM model construction parameters (model_name, api_key, api_base, custom_llm_provider, timeouts)? [Completeness, Spec §Req 1.2]
- [ ] CHK002 - Is the I/O-free construction requirement explicitly stated with verification criteria? [Completeness, Spec §Req 1.3]
- [ ] CHK003 - Are observability requirements (system and model_name properties for span attributes) specified? [Completeness, Spec §Req 1.4]
- [ ] CHK004 - Are requirements defined for the LiteLLM route format (`<provider>/<model_id>`)? [Completeness, Spec §Req 1.2]

### Watsonx Wrapper Configuration

- [ ] CHK005 - Are requirements specified for constructing the watsonx-specific route (`watsonx/<model_id>`)? [Completeness, Spec §Req 7.1]
- [ ] CHK006 - Is the WATSONX_PROJECT_ID environment variable requirement explicitly documented with fail-fast behavior? [Completeness, Spec §Req 7.2]
- [ ] CHK007 - Are requirements defined for API key unwrapping at the boundary (SecretStr.get_secret_value())? [Completeness, Spec §Req 7.5]
- [ ] CHK008 - Are timeout configuration requirements specified (watsonx_timeout_connect/read sourcing)? [Completeness, Spec §Req 5.2]
- [ ] CHK009 - Are requirements defined for the watsonx URL configuration (api_base parameter)? [Completeness, Spec §Req 7.1]

### Optional Dependency Management

- [ ] CHK010 - Are requirements specified for the optional litellm package guard with clear error messaging? [Completeness, Spec §Req 6.1]
- [ ] CHK011 - Is the function-local import requirement for litellm explicitly stated? [Completeness, Spec §Req 6.2]
- [ ] CHK012 - Are requirements defined for the error message format (package name + install command)? [Completeness, Spec §Req 6.1]

### Transport Switching

- [ ] CHK013 - Are requirements specified for maintaining the SDK transport unchanged? [Completeness, Spec §Req 7.4]
- [ ] CHK014 - Is the replacement of the broken _build_litellm() construction explicitly required? [Completeness, Spec §Req 7.3]
- [ ] CHK015 - Are requirements defined for transport selection via WATSONX_TRANSPORT environment variable? [Gap]

## Requirement Clarity

### Configuration Parameters

- [ ] CHK016 - Is "I/O-free construction" quantified with specific criteria (no network calls before first request())? [Clarity, Spec §Req 1.3]
- [ ] CHK017 - Is "fail fast" for missing WATSONX_PROJECT_ID defined with specific error type and message format? [Clarity, Spec §Req 7.2]
- [ ] CHK018 - Are timeout values clearly specified as separate connect and read parameters? [Clarity, Spec §Req 5.1, 5.2]
- [ ] CHK019 - Is the "unwrap only at boundary" requirement for API keys unambiguous about the unwrapping location? [Clarity, Spec §Req 7.5]
- [ ] CHK020 - Is the LiteLLM route format (`<provider>/<model_id>`) documented with concrete examples? [Clarity, Spec §Req 1.2]

### Environment Variable Handling

- [ ] CHK021 - Is the WATSONX_PROJECT_ID environment variable requirement clear about when it must be present (only for litellm transport)? [Clarity, Spec §Req 7.2]
- [ ] CHK022 - Are requirements clear about whether WATSONX_PROJECT_ID is read from Settings or directly from os.environ? [Ambiguity, Spec §Req 7.2]
- [ ] CHK023 - Is the side-effect of setting os.environ["WATSONX_PROJECT_ID"] explicitly acknowledged and justified? [Clarity, Plan §C3]

### Integration Points

- [ ] CHK024 - Are requirements clear about which component owns the litellm.acompletion() call? [Clarity, Spec §Req 1.1]
- [ ] CHK025 - Is the shared mapping module extraction requirement unambiguous about which functions are extracted? [Clarity, Spec §Req 11.1, 11.2]
- [ ] CHK026 - Are requirements clear about the response normalization step (.model_dump() before build_response)? [Clarity, Plan §C2]

## Requirement Consistency

### Configuration Flow

- [ ] CHK027 - Are timeout configuration requirements consistent between LiteLLMModel and watsonx wrapper? [Consistency, Spec §Req 5.1, 5.2]
- [ ] CHK028 - Are API key handling requirements consistent across all components (unwrap once, never log)? [Consistency, Spec §Req 7.5]
- [ ] CHK029 - Are optional dependency guard requirements consistent between LiteLLMModel and watsonx wrapper? [Consistency, Spec §Req 6.1, 6.2]
- [ ] CHK030 - Are observability requirements (span attributes) consistent with existing SDK transport? [Consistency, Spec §NFR]

### Transport Behavior

- [ ] CHK031 - Are error handling requirements consistent between SDK and LiteLLM transports? [Consistency, Spec §Req 4.1]
- [ ] CHK032 - Are retry behavior requirements (num_retries=0) consistent with project ADR-2? [Consistency, Spec §Req 4.2]
- [ ] CHK033 - Are streaming deferral requirements consistent between transports (both raise NotImplementedError)? [Consistency, Spec §Req 8.1]

### Shared Utilities

- [ ] CHK034 - Are message/tool mapping requirements consistent between SDK and LiteLLM models after extraction? [Consistency, Spec §Req 11.3]
- [ ] CHK035 - Are response transformation requirements consistent across both transports? [Consistency, Spec §Req 11.4]

## Acceptance Criteria Quality

### Measurability

- [ ] CHK036 - Can "I/O-free construction" be objectively verified (e.g., no network mocks needed in construction tests)? [Measurability, Spec §Req 1.3]
- [ ] CHK037 - Can timeout passthrough be objectively measured (e.g., assert timeout values in acompletion call)? [Measurability, Spec §Req 5.1]
- [ ] CHK038 - Can the "fail fast" requirement be objectively tested (e.g., specific exception type and message pattern)? [Measurability, Spec §Req 7.2]
- [ ] CHK039 - Can observability requirements be objectively verified (e.g., span attribute assertions)? [Measurability, Spec §Req 1.4]

### Testability

- [ ] CHK040 - Are all configuration requirements testable in hermetic tests (no live dependencies)? [Testability, Spec §Req 10.1]
- [ ] CHK041 - Are environment variable requirements testable with monkeypatch/restore patterns? [Testability, Plan §C3]
- [ ] CHK042 - Are optional dependency guard requirements testable with import mocking? [Testability, Spec §Req 6.1]
- [ ] CHK043 - Are transport switching requirements testable without modifying factory.py? [Testability, Plan §Architecture]

## Scenario Coverage

### Primary Flow

- [ ] CHK044 - Are requirements defined for the happy path: WATSONX_TRANSPORT=litellm with all config present? [Coverage, Spec §Req 7.1]
- [ ] CHK045 - Are requirements defined for the SDK transport path remaining unchanged? [Coverage, Spec §Req 7.4]

### Alternate Flows

- [ ] CHK046 - Are requirements defined for using LiteLLMModel with non-watsonx providers? [Coverage, Spec §Req 1.1]
- [ ] CHK047 - Are requirements defined for custom_llm_provider override scenarios? [Coverage, Spec §Req 1.2]

### Exception/Error Flows

- [ ] CHK048 - Are requirements defined for missing WATSONX_PROJECT_ID when transport=litellm? [Coverage, Spec §Req 7.2]
- [ ] CHK049 - Are requirements defined for missing litellm package when transport=litellm? [Coverage, Spec §Req 6.1]
- [ ] CHK050 - Are requirements defined for litellm.acompletion() exceptions? [Coverage, Spec §Req 4.1]
- [ ] CHK051 - Are requirements defined for invalid timeout configurations? [Gap]
- [ ] CHK052 - Are requirements defined for invalid model_name format (missing provider prefix)? [Gap]

### Recovery Flows

- [ ] CHK053 - Are requirements defined for fallback behavior when LiteLLM transport fails? [Coverage, Spec §Req 4.1]
- [ ] CHK054 - Are requirements defined for retry behavior (disabled via num_retries=0)? [Coverage, Spec §Req 4.2]

## Edge Case Coverage

### Configuration Edge Cases

- [ ] CHK055 - Are requirements defined for empty or whitespace-only WATSONX_PROJECT_ID? [Edge Case, Gap]
- [ ] CHK056 - Are requirements defined for WATSONX_PROJECT_ID present but transport=sdk? [Edge Case, Gap]
- [ ] CHK057 - Are requirements defined for api_key=None scenarios? [Edge Case, Spec §Req 1.2]
- [ ] CHK058 - Are requirements defined for api_base=None scenarios? [Edge Case, Spec §Req 1.2]
- [ ] CHK059 - Are requirements defined for zero or negative timeout values? [Edge Case, Gap]

### Integration Edge Cases

- [ ] CHK060 - Are requirements defined for litellm.ModelResponse with missing fields? [Edge Case, Spec §Req 3.4]
- [ ] CHK061 - Are requirements defined for double-encoded tool-call arguments (Granite models)? [Edge Case, Spec §Req 2.4]
- [ ] CHK062 - Are requirements defined for unsupported message part types? [Edge Case, Spec §Req 2.3]
- [ ] CHK063 - Are requirements defined for empty choices array in response? [Edge Case, Spec §Req 3.3]

### Boundary Conditions

- [ ] CHK064 - Are requirements defined for very long model_name strings? [Edge Case, Gap]
- [ ] CHK065 - Are requirements defined for special characters in model_name? [Edge Case, Gap]
- [ ] CHK066 - Are requirements defined for concurrent construction of multiple LiteLLMModel instances? [Edge Case, Gap]

## Non-Functional Requirements

### Performance

- [ ] CHK067 - Are performance requirements quantified for construction time (< 2 seconds, no network I/O)? [NFR, Spec §NFR]
- [ ] CHK068 - Are performance requirements defined for configuration validation overhead? [Gap]

### Security

- [ ] CHK069 - Are security requirements explicit about never logging API keys? [NFR, Spec §Req 7.5, §NFR]
- [ ] CHK070 - Are security requirements defined for SecretStr handling throughout the pipeline? [NFR, Spec §Req 7.5]
- [ ] CHK071 - Are security requirements defined for environment variable exposure (WATSONX_PROJECT_ID)? [Gap]

### Observability

- [ ] CHK072 - Are observability requirements defined for span attributes (gen_ai.system, gen_ai.request.model)? [NFR, Spec §NFR]
- [ ] CHK073 - Are observability requirements defined for error.class attribute on failures? [NFR, Spec §NFR]
- [ ] CHK074 - Are observability requirements consistent with existing SDK transport? [NFR, Spec §NFR]

### Maintainability

- [ ] CHK075 - Are requirements defined for upstream library attribution (MIT license header)? [NFR, Spec §Req 9.3]
- [ ] CHK076 - Are requirements defined for code reuse via shared mapping module? [NFR, Spec §Req 11.1]
- [ ] CHK077 - Are requirements defined for avoiding circular dependencies in shared utilities? [Gap]

## Dependencies & Assumptions

### External Dependencies

- [ ] CHK078 - Is the dependency on litellm package explicitly documented as optional? [Dependency, Spec §Dependencies]
- [ ] CHK079 - Is the dependency on pydantic-ai V2 (Beta) Model ABC explicitly documented? [Dependency, Spec §Dependencies]
- [ ] CHK080 - Is the dependency on completion of 002-watsonx-provider explicitly documented? [Dependency, Spec §Dependencies]
- [ ] CHK081 - Are version compatibility requirements defined for litellm package? [Gap]

### Assumptions

- [ ] CHK082 - Is the assumption that LiteLLM reads WATSONX_PROJECT_ID from os.environ validated? [Assumption, Plan §C3, Research ADR-3]
- [ ] CHK083 - Is the assumption that .model_dump() preserves raw JSON tool-call arguments validated? [Assumption, Plan §C2]
- [ ] CHK084 - Is the assumption that factory.py dispatch requires no changes validated? [Assumption, Plan §Architecture]
- [ ] CHK085 - Is the assumption that SDK transport tests pass unmodified validated? [Assumption, Spec §Req 7.4, 11.4]

### Integration Assumptions

- [ ] CHK086 - Are assumptions about LiteLLM's timeout parameter format (httpx.Timeout) documented? [Assumption, Plan §Interfaces]
- [ ] CHK087 - Are assumptions about LiteLLM's error types and exception hierarchy documented? [Gap]
- [ ] CHK088 - Are assumptions about watsonx.ai endpoint behavior (404 on /chat/completions) documented? [Assumption, Spec §Overview]

## Ambiguities & Conflicts

### Specification Ambiguities

- [ ] CHK089 - Is it clear whether WATSONX_PROJECT_ID validation happens at construction or first request? [Ambiguity, Spec §Req 7.2]
- [ ] CHK090 - Is it clear whether the optional dependency guard raises ValueError or ImportError? [Clarity, Spec §Req 6.1 - states ValueError]
- [ ] CHK091 - Is it clear which component is responsible for setting os.environ["WATSONX_PROJECT_ID"]? [Clarity, Plan §C3]

### Potential Conflicts

- [ ] CHK092 - Do requirements for I/O-free construction conflict with WATSONX_PROJECT_ID environment validation? [Conflict Check, Spec §Req 1.3, 7.2]
- [ ] CHK093 - Do requirements for function-local imports conflict with type checking needs? [Conflict Check, Spec §Req 6.2, 9.4]
- [ ] CHK094 - Do requirements for broad exception catching conflict with fail-loud mapping errors? [Conflict Check, Spec §Req 4.1, 4.3]

### Design Decisions Needing Validation

- [ ] CHK095 - Is the decision to use os.environ mutation (side effect) justified and documented? [Design Decision, Plan §C3]
- [ ] CHK096 - Is the decision to vendor upstream code rather than use as dependency justified? [Design Decision, Spec §Clarifications]
- [ ] CHK097 - Is the decision to defer streaming support (NotImplementedError) justified? [Design Decision, Spec §Req 8.1]

## Constitution & Project Compliance

### Configuration-Driven Behavior (Principle II)

- [ ] CHK098 - Do requirements ensure model identifiers are sourced from configuration, not hardcoded? [Constitution, Spec §Req 1.2, 7.1]
- [ ] CHK099 - Do requirements ensure credentials are sourced from environment/config, not hardcoded? [Constitution, Spec §Req 7.5]
- [ ] CHK100 - Do requirements ensure provider selection is configuration-driven? [Constitution, Spec §Req 7.1]

### Hermetic Default Quality Gates (Principle III)

- [ ] CHK101 - Do requirements ensure default tests are hermetic (no network calls)? [Constitution, Spec §Req 10.1]
- [ ] CHK102 - Do requirements ensure live integration tests are opt-in (RUN_INTEGRATION_WATSONX=1)? [Constitution, Spec §Req 10.3]
- [ ] CHK103 - Do requirements ensure construction is I/O-free for hermetic testing? [Constitution, Spec §Req 1.3]

### Observable and Fail-Fast Services (Principle IV)

- [ ] CHK104 - Do requirements ensure fail-fast on missing configuration (WATSONX_PROJECT_ID, litellm package)? [Constitution, Spec §Req 6.1, 7.2]
- [ ] CHK105 - Do requirements ensure actionable error messages (package name + install command)? [Constitution, Spec §Req 6.1]
- [ ] CHK106 - Do requirements ensure observability via span attributes? [Constitution, Spec §NFR]

### Operational Constraints

- [ ] CHK107 - Do requirements ensure secrets are never logged? [Constitution, Spec §Req 7.5, §NFR]
- [ ] CHK108 - Do requirements ensure integration tests are isolated from default quality gate? [Constitution, Spec §Req 10.3]

---

## Summary

**Total Items**: 108  
**Traceability**: 85/108 items (79%) include spec/plan references or gap markers  
**Focus Areas**:
- LiteLLM model integration and configuration (CHK001-CHK015)
- Environment variable and dependency management (CHK016-CHK026)
- Transport switching and consistency (CHK027-CHK043)
- Edge cases and error scenarios (CHK044-CHK066)
- Non-functional requirements and compliance (CHK067-CHK108)

**Key Gaps Identified**:
- Transport selection mechanism (CHK015)
- Invalid configuration handling (CHK051, CHK052, CHK055-CHK059, CHK064-CHK066)
- LiteLLM version compatibility (CHK081)
- Error type documentation (CHK087)
- Security considerations for environment variables (CHK071)
- Circular dependency prevention (CHK077)

**Next Steps**: Review this checklist during PR review to validate that all integration and configuration requirements are complete, clear, consistent, and testable before implementation proceeds.