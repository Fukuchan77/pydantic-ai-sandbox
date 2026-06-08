# 002-watsonx-provider — Discovery & Research Log

Created during `/sdd-plan` (2026-06-08; revised same day under "fix
recommended"). Records investigations, decisions, and risks that inform the
design. Entries are evidence-backed against the *installed* packages on the
project's pinned interpreter (Python **3.14.5**), not documentation alone.

## Discovery type

**Extension (light)** — adds one provider to the established
`llm/providers/<name>.py` + `factory.get_model` pattern from
`001-agentic-platform`. The only genuinely net-new unit is the hand-rolled
`WatsonxSDKModel` (pydantic_ai ships no native watsonx Model), so discovery
focused on the `ibm-watsonx-ai` SDK surface and the pydantic_ai V2 `Model` /
`LiteLLMProvider` contracts.

## Investigations

### C1 (CRITICAL): `ibm-watsonx-ai 1.5.12` does not import on Python 3.14

- **Question**: Can the pinned SDK (`uv.lock` → `ibm-watsonx-ai 1.5.12`)
  provide `ModelInference.chat()` on the project's Python 3.14.5?
- **Findings**: **No.** Importing the SDK *core* (`from
  ibm_watsonx_ai.foundation_models import ModelInference`, and even
  `from ibm_watsonx_ai import APIClient`) raises
  `TypeError: object.__init__() takes exactly one argument` while building
  `class TextGenDecodingMethod(StrEnum)`. Root cause: the SDK's custom
  `StrEnum.__init__(self, *args, **kwargs)` (`utils/utils.py:1190`) forwards
  member-construction args to `object.__init__`, which Python 3.14's stricter
  enum machinery rejects. This blocks the **entire SDK default transport**.
- **Resolution**: `ibm-watsonx-ai 1.5.13` (latest; `requires_python =
  "<3.15,>=3.11"`, ships a `Programming Language :: Python :: 3.14`
  classifier) imports `foundation_models.ModelInference` cleanly on 3.14.5.
  Fix = bump the pin `1.5.12 → 1.5.13`.
- **Evidence**:
  - `uv run python -c "from ibm_watsonx_ai.foundation_models import ModelInference"`
    → `TypeError ... object.__init__()` at
    `ibm_watsonx_ai/utils/utils.py:1191` (under py 3.14.5).
  - `uv run --with 'ibm-watsonx-ai==1.5.13' python -c "from ibm_watsonx_ai.foundation_models import ModelInference; print('IMPORT OK 1.5.13')"`
    → `py (3, 14, 5)` / `IMPORT OK 1.5.13` (ephemeral overlay, lock untouched).
  - PyPI `requires_python` for 1.5.13 = `"<3.15,>=3.11"`.

### R2: SDK message mapping (`ModelInference.chat`) — RESOLVED

- **Question**: How to map pydantic_ai `list[ModelMessage]` → watsonx and
  build a `ModelResponse`? `chat()` vs `generate_text()`? tool-call support?
- **Findings**: Use the **async `achat()`** (OpenAI-shaped), not the sync
  `chat()` and not `generate_text()`. `Model.request` is `async`, and the
  sync `chat()` would block the event loop; `achat()` is a verified coroutine
  with an identical signature and return type.
  - `ModelInference.achat(messages: list[dict], params: dict |
    TextChatParameters | None = None, tools: list | None = None,
    tool_choice: dict | None = None, tool_choice_option:
    Literal["none","auto","required"] | None = None, context, crypto) ->
    dict`. (`chat()` is the sync twin; `achat_stream`/`agenerate` also exist
    but are out of scope.)
  - `messages` are OpenAI-style `{"role": ..., "content": ...}` dicts;
    return value is an OpenAI chat-completion-shaped `dict` (`choices[].message`,
    `usage`, `id`, per-choice `finish_reason`). **Tool calls are supported**
    via `tools` / `tool_choice`.
  - Mapping for `WatsonxSDKModel.request`: pydantic_ai system/user/tool parts
    → `list[dict]`; call `chat()`; parse `resp["choices"][0]["message"]`
    (text + any `tool_calls`) into `ModelResponse.parts`, `resp["usage"]` →
    usage, `resp["choices"][0]["finish_reason"]` → finish_reason,
    `resp["id"]` → `provider_response_id`. Exhaustive part handling, no
    silent drops (`models/CLAUDE.md`).
- **Evidence**: `inspect.iscoroutinefunction(ModelInference.chat) == False`
  but `inspect.iscoroutinefunction(ModelInference.achat) == True`;
  `inspect.signature(ModelInference.achat)` identical to `chat` with
  `-> dict`; docstring `:rtype: dict`. Under `ibm-watsonx-ai==1.5.13`.

### R3: SDK timeout wiring + no-retry — RESOLVED

- **Question**: How do connect/read timeouts (Req 5.x) reach the SDK while
  keeping construction I/O-free? Does the SDK retry by default (Req 6.1)?
- **Findings**:
  - `Credentials(...)` has **no** timeout parameter. Timeouts live on the
    **httpx client** handed to `APIClient`:
    `APIClient(credentials, project_id, ..., httpx_client: httpx.Client |
    HttpClientConfig = HttpClientConfig(timeout=Timeout(connect=10,
    read=1800, ...)), async_httpx_client: httpx.AsyncClient | HttpClientConfig
    = ...)`. → Inject `httpx.Timeout(connect=WATSONX_TIMEOUT_CONNECT,
    read=WATSONX_TIMEOUT_READ)` via the (async) httpx client (Req 5.1–5.4).
  - `ModelInference(..., api_client: APIClient | None = None, max_retries:
    int | None = None, delay_time, retry_status_codes)`. The SDK **retries by
    default** → to honour Req 6.1 the Model MUST construct the client with
    `max_retries=0` (no provider-level retry; rely on the fallback chain).
  - **I/O-free construction (Req 1.5)**: `APIClient`/`ModelInference` perform
    auth/validation network calls at construction (default `validate=True`),
    so the SDK client MUST be built **lazily on first `request`**, never in
    `WatsonxSDKModel.__init__`. Consider `validate=False` to avoid an extra
    validation round-trip on the first call.
- **Evidence**: `inspect.signature(APIClient.__init__)` (default
  `HttpClientConfig(timeout=Timeout(connect=10, read=1800, write=1800,
  pool=1800), ...)`) and `inspect.signature(ModelInference.__init__)` showing
  `max_retries`/`delay_time`/`retry_status_codes`, under `==1.5.13`.

### R4: LiteLLM credential routing — RESOLVED

- **Question**: How do `apikey` / `url` / `project_id` reach litellm, and
  how do timeouts apply on the litellm path?
- **Findings**: `LiteLLMProvider(*, api_key, api_base, openai_client,
  http_client)` — **no `project_id` parameter**. Route:
  `apikey → api_key`, `url → api_base`; **`project_id` reaches litellm via
  the environment** (`WATSONX_PROJECT_ID`, which the deployment already sets),
  not a constructor arg. Timeouts (Req 5.4) inject via the `http_client`
  (a custom async HTTP client). Wrap in
  `OpenAIChatModel(model_name=f"watsonx/{model_id}", provider=LiteLLMProvider(
  ...))` — `OpenAIChatModel` accepts a `Provider`, and its OpenAI adapter
  auto-stamps `gen_ai.system` / `gen_ai.request.model` (Req 8.1).
- **Evidence**: `inspect.signature(LiteLLMProvider.__init__)` →
  `(*, api_key, api_base, openai_client, http_client)`;
  `inspect.signature(OpenAIChatModel.__init__)` → `provider:
  OpenAIChatCompatibleProvider | ... | Provider[AsyncOpenAI]`.

### R5: Error-classification matrix — RESOLVED

- **Question**: Which SDK/transport exceptions must be wrapped in
  `ModelAPIError` so `FallbackModel` recovers them (Req 6.2/7.1/7.2)?
- **Findings**: Catch the SDK base `WMLClientError` (covers
  `ApiRequestFailure`, `AuthenticationError`, `InvalidCredentialsError`,
  `ExceededLimitOfAPICalls` [rate limit], `ReadingDataTimeoutError`, …) **plus
  the underlying httpx errors** (`httpx.TimeoutException`,
  `httpx.ConnectError`, `httpx.HTTPError`) since the SDK is httpx-based, and
  wrap every one in `pydantic_ai.exceptions.ModelAPIError`. `FallbackModel`'s
  default `fallback_on = (ModelAPIError,)` (verified) — an unwrapped raw
  exception silently breaks failover. No retries (Req 6.1): first failure
  propagates immediately.
- **Evidence**: `dir(ibm_watsonx_ai.wml_client_error)` →
  `WMLClientError, ApiRequestFailure, AuthenticationError,
  InvalidCredentialsError, ExceededLimitOfAPICalls, ReadingDataTimeoutError,
  …`; `FallbackModel.__init__` default `fallback_on=(ModelAPIError,)`
  (pydantic_ai 2.0.0b6).

### V1: pydantic_ai V2 `Model` ABC surface — RESOLVED

- **Question**: Exact abstract surface a custom Model must implement.
- **Findings**: Only `request(self, messages: list[ModelMessage],
  model_settings: ModelSettings | None, model_request_parameters:
  ModelRequestParameters) -> ModelResponse` is abstract. `request_stream` is
  **not** abstract (still overridden to `raise NotImplementedError`
  defensively; streaming is out of scope). `model_name` / `system` properties
  drive `gen_ai.request.model` / `gen_ai.system` (Req 8.6).
- **Evidence**: `Model.request.__isabstractmethod__ == True`;
  `Model.request_stream.__isabstractmethod__ == False` (pydantic_ai 2.0.0b6).

## Existing patterns to reuse

| Pattern | Location | Why reuse |
|---------|----------|-----------|
| `_build_<name>(settings: Settings) -> Model`, I/O-free | `llm/providers/ollama.py` | Builder shape mandated by `structure.md`; factory calls every builder uniformly |
| Lazy client construction (no HTTP at build time) | `ollama.py` (`OllamaProvider` deferred) | Satisfies Req 1.5 / the "no HTTP I/O at construction" constraint |
| `SecretStr` unwrapped only at SDK boundary | `ollama.py` `get_secret_value()` | `tech.md` secrets convention |
| Cross-field provider gate in `Settings` | `config.py` `_check_provider_constraints` | Fail-fast credential validation (Req 3.2) |
| Opt-in integration lane + `_MANAGED_ENV_KEYS` | `tests/integration/test_ollama_chat_e2e.py`, `conftest.py` | Hermetic defaults (Req 9.10/10.1) |

## External dependencies

| Dependency | Version | Purpose | Verified |
|------------|---------|---------|----------|
| `ibm-watsonx-ai` | **`>=1.5.13`** (was 1.5.12) | SDK default transport (`ModelInference.chat`) | ✅ imports on py3.14.5; 1.5.12 ❌ blocked |
| `litellm` | latest (optional extra) | LiteLLM transport via `LiteLLMProvider` | ⚠️ not installed by default; import-guarded (Req 2.6); py3.14 support to confirm at install |
| `pydantic-ai` | `2.0.0b6` (existing) | `Model` ABC, `FallbackModel`, `LiteLLMProvider`, `OpenAIChatModel` | ✅ surfaces verified |
| `httpx` | existing | timeout injection (`APIClient(httpx_client=...)`) + I/O-free test patches | ✅ |

## Architecture decisions

### ADR-1: Bump `ibm-watsonx-ai` to `>=1.5.13` (unblock Python 3.14)

- **Context**: The locked `1.5.12` cannot import its `foundation_models` core
  on the project's Python 3.14.5 (enum/`StrEnum` incompatibility), making the
  SDK default transport impossible to build or test.
- **Decision**: Pin `ibm-watsonx-ai >= 1.5.13` in `pyproject.toml` and refresh
  `uv.lock`. This is the **first foundation task** — nothing else in the SDK
  lane can compile or run until it lands.
- **Alternatives**: (a) Monkeypatch the SDK's `StrEnum` — rejected: fragile,
  touches vendor internals. (b) Make litellm the default to sidestep the SDK —
  rejected: contradicts the supply-chain-minimization decision and Req 2.2.
  (c) Pin Python ≤3.13 — rejected: violates `tech.md` (Python 3.14 mandated).
- **Consequences**: Trivial version bump; keeps SDK-as-default intact. Adds a
  hard lower bound that dependabot (Req 11.4) will track upward.

### ADR-2: No-retry via explicit `ModelInference(max_retries=0)`

- **Context**: Req 6.1 forbids provider-level retries; the SDK retries by
  default (`max_retries`/`delay_time`/`retry_status_codes` params).
- **Decision**: Construct the SDK client with `max_retries=0`; wrap all
  failures in `ModelAPIError` and let the fallback chain provide resilience.
- **Alternatives**: Leave SDK defaults — rejected: silently violates Req 6.1
  and inflates latency before failover.
- **Consequences**: A dedicated unit test (Req 9.7) must assert the client is
  built with `max_retries=0` and that no retry occurs on error.

### ADR-3: litellm `project_id` via environment, not constructor

- **Context**: `LiteLLMProvider` exposes `api_key`/`api_base` but no
  `project_id`; watsonx requires a project/space id.
- **Decision**: Pass `apikey → api_key`, `url → api_base` explicitly; rely on
  the already-present `WATSONX_PROJECT_ID` env var for litellm to pick up.
  Inject timeouts via `http_client`.
- **Alternatives**: Embed project_id in the model string — rejected: not
  supported by the `watsonx/<model_id>` convention.
- **Consequences**: The litellm path's RESPX unit test (Req 9.4) must set
  `WATSONX_PROJECT_ID` in the env fixture.

## Risks & open questions

- ⚠️ **Resolved blocker**: SDK import on py3.14 — mitigated by ADR-1
  (`>=1.5.13`). Until the pin lands, the SDK lane is non-functional.
- ⚠️ **litellm on py3.14**: the optional extra's 3.14 compatibility is
  unverified (not installed). Mitigation: import-guard already required
  (Req 2.6); confirm at the point litellm is added to the optional extra.
- ⚠️ **SDK construction does network I/O** (`validate=True` default) →
  mitigation: build `APIClient`/`ModelInference` lazily on first `request`,
  never in `__init__`; `validate=False` to avoid the extra round-trip.
- ❓ **Exact `chat()` response dict keys across model classes** (finish_reason
  presence, tool_call shape) — to confirm against a live response in the
  integration lane (Req 10.x); unit tests use a captured fixture shape.
