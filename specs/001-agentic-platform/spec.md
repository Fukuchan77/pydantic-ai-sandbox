# 001-agentic-platform Requirements Specification

## Overview

Pydantic AI V2 (Beta) × FastAPI × マルチプロバイダ Agentic AI 基盤。本番想定では安定版を採用しつつ、Pydantic AI V2 のローカル検証構築を前提とする。ruff/pyright によるリント・フォーマット・型チェック、pytest による品質確保、pre-commit による自動実行、定期セキュリティスキャンを含む。詳細設計は [specs/inputs/idea0.md](../inputs/idea0.md) を参照。

## Project Description

本サンドボックスは、複数 LLM プロバイダ (Ollama / IBM watsonx.ai / Anthropic 直接 / AWS Bedrock) を `ModelFactory` で切替可能な FastAPI ベースの Agentic AI 基盤を構築する。Pydantic AI V2 Beta のローカル検証を主目的に置きつつ、運用知見の蓄積として品質ゲート (ruff / pyright / pytest / pre-commit / 定期セキュリティスキャン) を最初から組み込む。アーキテクチャ・構成・落とし穴は `specs/inputs/idea0.md` に詳細記述あり。

主要要素 (idea0.md 由来):

- **ランタイム**: Python 3.14.5、可能な限り最新ライブラリ
- **フレームワーク**: FastAPI (`fastapi[standard]`)、Pydantic AI V2 Beta (`pydantic-ai>=2.0.0b3`)
- **LLM プロバイダ**: Ollama (granite4.1:8b 主力)、watsonx.ai (granite-4-h-small)、Anthropic 直接 (claude-sonnet-4-6 / claude-haiku-4-5)、AWS Bedrock (Cross-Region Inference Profile 必須)
- **抽象化**: `ModelFactory` + `FallbackModel`、全モデル ID を環境変数化
- **マルチモーダル**: `BinaryContent` で画像入力を Vision 対応モデルへ
- **可観測性**: Logfire (`instrument_pydantic_ai` / `instrument_fastapi` / `instrument_httpx`)
- **テスト**: `TestModel` / `FunctionModel` + `agent.override` パターン
- **品質ゲート**: ruff (lint+format)、pyright (strict)、pytest (asyncio auto)、pre-commit
- **セキュリティ**: 定期スキャン (pip-audit / Safety / 等は要決定)、LiteLLM サプライチェーン警戒

## Clarifications

### Session 2026-05-24

- Q1: MVP として含める LLM プロバイダの範囲は？ → A: **Ollama 単独で V2 beta 検証**。`granite4.1:8b` を主軸に Agent/Tool/構造化出力/Fallback を Pydantic AI V2 beta で動作確認する。残り3プロバイダ (watsonx.ai / Anthropic / Bedrock) は後続スプリントで段階追加。`ModelFactory` の抽象化は MVP から導入し、後の追加コストを下げる。
- Q2: Vision (マルチモーダル) エンドポイントを MVP に含めるか？ → A: **/chat のみ、Vision は後続**。MVP は `/chat`（テキスト）に集中し、Pydantic AI V2 beta の Agent/Tool/構造化出力/Fallback/可観測性を確実に動かす。Vision (BinaryContent + llama3.2-vision など) は後続フェーズで追加。
- Q3: 定期セキュリティスキャンのツールセットは？ → A: **pip-audit + bandit + gitleaks**。pip-audit=依存 CVE（PyPI Advisory DB）、bandit=Python コード脆弱性、gitleaks=シークレット漏洩、の三層を OSS で構成。CI (GitHub Actions など) で週次実行 + pre-commit に軽量チェックを組み込み、LiteLLM 系サプライチェーン事故にも備える。
- Q4: pre-commit で自動実行する品質ゲート範囲は？ → A: **lint+format+型チェック+軽量セキュリティ**。`ruff check` / `ruff format --check` / `pyright` / `gitleaks` を pre-commit で実行し、`pytest` / `pip-audit` / `bandit` は CI 側に寄せる。コミット速度を維持しつつ重要ゲートは確保。`pre-commit run --hook-stage manual` で全件実行も可能にする。
- Q5: 可観測性 (Logfire) と Pydantic Evals の MVP 範囲は？ → A: **Logfire は計装のみ、Evals は後続**。`instrument_pydantic_ai` / `instrument_fastapi` / `instrument_httpx` を FastAPI lifespan に組み込む。`LOGFIRE_TOKEN` 未設定時は送信スキップで起動継続 (fail-soft)。Pydantic Evals はゴールデンセット設計とともに後続スプリントで導入。

## Requirements

> 本要件は `specs/inputs/idea0.md` の設計と `.sdd/memory/constitution.md` 原則 I–V、および当 spec の Clarifications Q1–Q5 に基づく。各 Acceptance Criteria は EARS 形式 (Ubiquitous / Event-driven / State-driven / Optional / Unwanted-behavior) を採用し、テスト可能であることを必須とする。`<system>` の主体は本サンドボックス・アプリケーション (`pydantic_ai_sandbox`) を指す。
>
> EARS パターン凡例:
>
> - U: `The <system> SHALL <response>`
> - E: `WHEN <trigger> the <system> SHALL <response>`
> - S: `WHILE <state> the <system> SHALL <response>`
> - O: `WHERE <feature> the <system> SHALL <response>`
> - X: `IF <condition> THEN the <system> SHALL <response>`

### Requirement 1: アプリケーション基盤と設定ロード

**User Story**: 開発者として、環境変数で全ての挙動を切替可能な FastAPI 基盤を起動したい。理由: Constitution V (品質ゲート) と Clarification Q1 (`ModelFactory` 抽象化) の前提が成立するため。

**Acceptance Criteria**:

- 1.1 [U] The system SHALL load all runtime configuration via `pydantic-settings` before the FastAPI lifespan begins.
- 1.2 [E] WHEN a required environment variable for the active `LLM_PROVIDER` is missing the system SHALL fail fast at startup, raising an error that names the missing variable.
- 1.3 [U] The system SHALL expose `GET /healthz` returning HTTP 200 with at minimum `{"status": "ok", "provider": <active provider>}`.
- 1.4 [U] The system SHALL run on Python `>=3.14` and SHALL NOT introduce dependencies that lack Python 3.14 wheels at the pinned version.
- 1.5 [X] IF source code under `src/` contains a hardcoded LLM model identifier (e.g., the literal `granite4.1:8b`) THEN the lint stage SHALL fail; all model IDs SHALL be sourced from environment variables.

### Requirement 2: LLM プロバイダ抽象化 (ModelFactory)

**User Story**: 基盤利用者として、`LLM_PROVIDER` を変更するだけで使用モデルを切り替えたい。理由: Clarification Q1 で MVP は Ollama 単独だが、後続で watsonx/Anthropic/Bedrock を追加する拡張パスを最初から確保するため。

**Acceptance Criteria**:

- 2.1 [U] The system SHALL provide a `ModelFactory` (function or class) that returns a `pydantic_ai.models.Model` instance based on `LLM_PROVIDER`.
- 2.2 [O] WHERE `LLM_PROVIDER=ollama` the factory SHALL return an Ollama-backed `Model` configured with `OLLAMA_BASE_URL` and `OLLAMA_MODEL_NAME`.
- 2.3 [U] The factory SHALL accept the public string contract `{"ollama", "watsonx", "anthropic", "bedrock", "fallback"}`.
- 2.4 [O] WHERE `LLM_PROVIDER ∈ {"watsonx","anthropic","bedrock"}` is selected in the MVP the factory MAY raise `NotImplementedError` with a message naming the provider; the contract SHALL nonetheless be covered by a unit test that asserts the raised type and message.
- 2.5 [X] IF `LLM_PROVIDER` is not in the documented set THEN the factory SHALL raise a configuration error (e.g., `ValueError`) at first invocation.
- 2.6 [U] The factory SHALL be unit-testable without a running Ollama instance (no real network I/O required for the constructor path).

### Requirement 3: チャットエージェントエンドポイント (/chat)

**User Story**: API クライアントとして、`POST /chat` に自然文を送ると構造化された JSON 回答が得られたい。理由: Clarification Q2 により MVP の機能スコープは `/chat` のみであり、構造化出力とツール呼び出しの V2 Beta 動作確認が本サンドボックスの主目的だから。

**Acceptance Criteria**:

- 3.1 [U] The system SHALL expose `POST /chat` accepting a JSON body matching a Pydantic `ChatRequest` model.
- 3.2 [U] The endpoint SHALL return a JSON response matching a Pydantic `ChatResponse` model containing at least one structured field beyond a free-text answer (e.g., a list of sources or citations).
- 3.3 [U] The agent backing `/chat` SHALL register at least one tool via the Pydantic AI tool registration API and SHALL be reachable from within the agent run loop.
- 3.4 [E] WHEN the LLM produces output that fails `ChatResponse` validation the endpoint SHALL respond with HTTP 5xx and SHALL NOT return partially valid data to the client.
- 3.5 [U] The endpoint SHALL be exercisable end-to-end against a local Ollama running `granite4.1:8b` with no code changes (provider selection by env var only).
- 3.6 [X] IF the request body fails Pydantic validation THEN the endpoint SHALL return HTTP 422 with FastAPI's standard validation error structure.

### Requirement 4: フォールバック耐性 (FallbackModel)

**User Story**: 運用者として、プライマリ LLM プロバイダが落ちても順送りで別プロバイダに切替えられる構成を持ちたい。理由: idea0.md §6/§13 と Clarification Q1 が抽象化を MVP から要求しているため、`FallbackModel` 経路を MVP で配線可能にしておく。

**Acceptance Criteria**:

- 4.1 [O] WHERE `LLM_PROVIDER=fallback` is selected the system SHALL compose a `FallbackModel` whose member ordering comes from the `FALLBACK_ORDER` environment variable.
- 4.2 [U] The system SHALL parse `FALLBACK_ORDER` as a comma-separated list of provider names from the Requirement 2.3 contract.
- 4.3 [X] IF a provider in the fallback chain raises a non-retriable error THEN the system SHALL attempt the next provider in order and SHALL emit at least one log/span attribute capturing the failover (provider name + error class).
- 4.4 [U] The fallback path SHALL be exercisable in unit tests using `FunctionModel` substitutes that simulate provider failure without network calls.
- 4.5 [X] IF `FALLBACK_ORDER` is empty or contains only undefined providers THEN selecting `LLM_PROVIDER=fallback` SHALL fail at startup (Requirement 1.2 applies).

### Requirement 5: 可観測性 (Logfire 計装、fail-soft)

**User Story**: 開発者として、エージェント実行・FastAPI リクエスト・httpx 呼び出しのトレースを Logfire で確認したい。理由: Clarification Q5 により計装は MVP に含めるが、トークン未設定でも開発が止まらないことが重要。

**Acceptance Criteria**:

- 5.1 [U] The system SHALL invoke `logfire.instrument_pydantic_ai()`, `logfire.instrument_fastapi(app)`, and `logfire.instrument_httpx()` during the FastAPI lifespan startup.
- 5.2 [X] IF `LOGFIRE_TOKEN` is unset or empty THEN the system SHALL still start successfully, with Logfire transport disabled (fail-soft) and a one-line warning emitted via the configured logger.
- 5.3 [E] WHEN an LLM call is dispatched through any provider the system SHALL emit at least one trace span attributed to the agent run; span attributes SHALL include the active provider name and model ID.
- 5.4 [U] The system SHALL NOT log raw user prompts, full tool inputs, or tool outputs at INFO level by default; sensitive payload logging SHALL be opt-in via a configuration flag.
- 5.5 [X] IF Logfire transport raises a transient error during request processing THEN the request SHALL still complete; observability failures SHALL NOT propagate to the API response.

### Requirement 6: Pydantic AI V2 Beta 検証

**User Story**: 検証者として、本サンドボックスで Pydantic AI V2 Beta の主要 API を実際に動かして、安定版 GA 移行時の影響範囲を予見したい。理由: 本プロジェクトの主目的 (Clarification Q1 と CLAUDE.md) が V2 Beta のローカル検証であるため。

**Acceptance Criteria**:

- 6.1 [U] The system SHALL declare `pydantic-ai>=2.0.0b3,<3` in `pyproject.toml` (already present) and SHALL NOT pin a stable V1 release.
- 6.2 [U] The system SHALL exercise the V2 `Agent(model=..., output_type=...)` construction path and structured-output coercion against a real Ollama backend in at least one integration test.
- 6.3 [U] The system SHALL exercise V2 tool registration and tool invocation in at least one test (unit or integration).
- 6.4 [U] The design phase SHALL enumerate every V2 API surface used (Agent constructor parameters, tool decorator name, history processor mechanism, usage accessor pattern) so V2 GA migration impact is reviewable.
- 6.5 [X] IF a V2 Beta API surface used by the system is removed or renamed in a subsequent `2.0.0bN` release THEN the dependency upgrade PR SHALL be blocked by failing tests rather than silently merged.

### Requirement 7: 品質ゲート (Constitution Principle V)

**User Story**: メンテナとして、すべてのコミット候補が lint・format・型・テストの 4 ゲートをローカルで通過したことを保証したい。理由: Constitution Principle V が MUST であり、緩和は禁止されているため。

**Acceptance Criteria**:

- 7.1 [U] `uv run ruff check .` SHALL exit 0 on the canonical `main` branch state.
- 7.2 [U] `uv run ruff format --check .` SHALL exit 0 on the canonical state.
- 7.3 [U] `uv run pyright` SHALL exit 0 in strict mode targeting Python 3.14.
- 7.4 [U] `uv run pytest` SHALL exit 0 with `asyncio_mode = "auto"`.
- 7.5 [U] All four gates SHALL be discoverable as `mise run` tasks (e.g., `mise run lint`, `mise run format`, `mise run typecheck`, `mise run test`, plus a composite `mise run check`).
- 7.6 [X] IF a contributor introduces local rule weakening (new per-file ignores beyond those already in `pyproject.toml`, ungrounded `# noqa` / `# type: ignore` without a justification comment, or `pyright` mode downgrade) THEN review SHALL block merge.
- 7.7 [U] The system SHALL track test coverage via `pytest-cov`; coverage of touched modules SHALL NOT regress relative to `main` (Constitution V).

### Requirement 8: pre-commit による品質ゲート自動実行

**User Story**: 開発者として、コミット時点で軽量品質ゲートが自動実行され、コミット履歴を汚さずに済む構成にしたい。理由: Clarification Q4 が高頻度の重い処理を pre-commit に置かない方針を採るため。

**Acceptance Criteria**:

- 8.1 [U] The repository SHALL provide a `.pre-commit-config.yaml` running `ruff check`, `ruff format --check`, `pyright`, and `gitleaks` on the default commit stage.
- 8.2 [X] IF any default-stage hook fails THEN the commit SHALL be blocked (pre-commit's standard behavior, not bypassed by configuration).
- 8.3 [U] The default stage SHALL NOT include `pytest`, `pip-audit`, or `bandit`; those SHALL be configured under `--hook-stage manual` for opt-in full sweeps.
- 8.4 [U] CI SHALL execute `pre-commit run --all-files --hook-stage manual` as one job to validate the configuration end-to-end on every push.
- 8.5 [U] The repository SHALL document the developer onboarding step `pre-commit install` in `README.md` (or equivalent), and the same step SHALL be runnable via `mise run setup` (or equivalent) when introduced.

### Requirement 9: 定期セキュリティスキャン

**User Story**: メンテナとして、依存・コード・シークレットの三層を継続的にスキャンし、LiteLLM 型のサプライチェーン事故と認証情報漏洩を未然に検出したい。理由: Clarification Q3 と Constitution Quality & Tooling Standards (S ルール強制) を満たすため。

**Acceptance Criteria**:

- 9.1 [U] CI SHALL run `pip-audit` against the resolved dependency set on every push and on a weekly schedule (e.g., GitHub Actions `schedule:` cron).
- 9.2 [U] CI SHALL run `bandit` against `src/` on every push.
- 9.3 [U] CI SHALL run `gitleaks` against the full repository (commits + working tree) on every push.
- 9.4 [X] IF any scanner reports a HIGH or CRITICAL finding THEN the CI job SHALL fail and the PR SHALL NOT be auto-mergeable.
- 9.5 [U] Dependencies that have a documented supply-chain incident history (e.g., `litellm` per idea0.md §14) SHALL be added with explicit version pins and SHALL be subject to dependency review (Renovate/Dependabot) before upgrade.
- 9.6 [U] The system SHALL NOT commit any secret material; `.env` SHALL remain in `.gitignore` (already present) and `.env.example` SHALL serve as the canonical contract for required variables.

### Requirement 10: テスト基盤 (TestModel / FunctionModel)

**User Story**: 開発者として、LLM プロバイダに到達せずにエージェントの振る舞いを検証したい。理由: idea0.md §11 と Constitution Principle I (Test-First) が、ネットワーク非依存の単体テスト基盤を要求するため。

**Acceptance Criteria**:

- 10.1 [U] The system SHALL configure pytest with `asyncio_mode = "auto"` (already encoded in `pyproject.toml`).
- 10.2 [U] The unit test suite SHALL exercise agents via `agent.override(model=TestModel())` or `FunctionModel(...)` substitutes; unit tests SHALL NOT require network access to any LLM provider.
- 10.3 [O] WHERE an integration test is provided that targets a real Ollama backend, the test SHALL be gated by an environment variable (e.g., `RUN_INTEGRATION_OLLAMA=1`) and SHALL be skipped by default in environments where the variable is not set.
- 10.4 [U] Test coverage SHALL be reported via `pytest-cov` and SHALL be visible in CI output.
- 10.5 [E] WHEN a new `tasks.md` task introduces production code under `src/`, a corresponding failing test SHALL be authored first and SHALL appear as a red state in the PDCA log or commit sequence (Constitution Principle I).

## Acceptance Criteria

> 個別の機能 Acceptance Criteria は §Requirements 内に EARS 形式で埋め込み済み。本セクションは横断 (Cross-Cutting) 受入条件と非機能要件 (NFR)、およびトレーサビリティを定義する。

### Cross-Cutting / Non-Functional

- **NFR-1 (Constitution 一貫性)**: 全 Requirement 1–10 は `.sdd/memory/constitution.md` 原則 I–V と矛盾しない。矛盾が検出された場合は本 spec ではなく Constitution 改定で解決する。
- **NFR-2 (再現性)**: 任意の開発機で `git clone` → `uv sync` → `pre-commit install` → `mise run check` の手順により全ゲートが通過する。
- **NFR-3 (環境変数中心主義)**: モデル ID・プロバイダ選択・トークンは全て環境変数で表現され、ソースコードに直書きしない (Requirement 1.5)。
- **NFR-4 (起動レジリエンス)**: `LOGFIRE_TOKEN` 未設定でも起動・稼働する (Requirement 5.2)。Ollama 未起動でもアプリは起動可能で、`/chat` 呼び出し時にのみエラー化する。
- **NFR-5 (V2 Beta 不安定性受容)**: `pydantic-ai==2.0.0b*` は API 変動を継続中であり、上書きは依存更新 PR で検出する (Requirement 6.5)。本番採用は V2 GA 後に再評価する。
- **NFR-6 (秘密情報非ログ)**: 既定で生プロンプト・ツール入出力を INFO レベルに出さない (Requirement 5.4)。
- **NFR-7 (CI 実行時間目標)**: pre-commit 既定ステージは開発機で目標 10 秒未満 (lint+format+pyright+gitleaks 合算)。これを超える場合は manual ステージへ移動を検討する。

### Traceability Matrix (要件 → 出典)

| Req              | 主要出典                                         |
| ---------------- | ------------------------------------------------ |
| R1 アプリ基盤    | Constitution II/V, idea0.md §10, pyproject.toml  |
| R2 ModelFactory  | Clarification Q1, idea0.md §6                    |
| R3 /chat         | Clarification Q2, idea0.md §10                   |
| R4 FallbackModel | idea0.md §6/§13                                  |
| R5 Logfire       | Clarification Q5, idea0.md §10                   |
| R6 V2 Beta 検証  | CLAUDE.md, Clarification Q1, pyproject.toml      |
| R7 品質ゲート    | Constitution V, pyproject.toml §ruff/§pyright    |
| R8 pre-commit    | Clarification Q4                                 |
| R9 セキュリティ  | Clarification Q3, Constitution Quality Standards |
| R10 テスト基盤   | Constitution I, idea0.md §11                     |

### Out of Scope (MVP 範囲外、別 spec で扱う)

- watsonx.ai / Anthropic / AWS Bedrock の実プロバイダ実装 (`Requirement 2.4` の `NotImplementedError` で MVP は受容)
- `/vision/describe` および BinaryContent によるマルチモーダル入力 (Q2)
- Pydantic Evals ゴールデンセット運用 (Q5)
- Pydantic AI V1 (`1.102.0`) との二系運用 — 本サンドボックスは V2 Beta 専用
- 本番運用向けの Provisioned Throughput / 課金最適化 / 監査ログ要件
- AWS Bedrock の Cross-Region Inference Profile 配置検証
