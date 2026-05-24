# research.md — 001-agentic-platform Discovery Log

> 本ドキュメントは `/sdd-plan` フェーズで実施した技術調査の記録である。`plan.md` の各 Component 節がここの結論を引用する。情報源は **2026-05-24 時点** で確認したもの。`pydantic-ai==2.0.0bN` は API ロックされていないため、**`2.0.0b3` 以降にバージョンが進むたび本ログを再検証**する。

## Discovery Type

**Light Discovery (Greenfield Sandbox + 既知設計書)**
理由: `specs/inputs/idea0.md` が技術選定・トレードオフ・落とし穴をすでに網羅しており、本フェーズの調査は (a) Pydantic AI V2 Beta の API シグネチャ確認、(b) Logfire の fail-soft 動作確認、(c) MVP スコープ (Ollama 単独・/chat のみ) に削った場合の最小構成検証、の 3 点に絞った。

## R-1. Pydantic AI V2 Beta — API 表面の確定

### 確認手段

`/pydantic/pydantic-ai` (Context7 / 公式 docs) に対して V2 (>=2.0.0b3) の Agent 構築・ツール登録・FallbackModel・OllamaProvider・テストモデル・override 動作を問い合わせ。

### 結論 (Requirement 6.4 トレース)

| API 表面                | V2 での形                                                                                             | Import パス                                                                                                         | 出典                                                    |
| ----------------------- | ----------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------- | ---------------- |
| Agent 構築              | `Agent(model, output_type=..., instructions=..., deps_type=..., tools=[...], validation_context=...)` | `from pydantic_ai import Agent`                                                                                     | `docs/agent.md`                                         |
| Tool (Context あり)     | `@agent.tool` で `RunContext[Deps]` を第一引数                                                        | `from pydantic_ai import Agent, RunContext, Tool`                                                                   | `docs/tools.md`                                         |
| Tool (Context なし)     | `@agent.tool_plain`                                                                                   | 同上                                                                                                                | `docs/tools.md`                                         |
| 構造化出力              | `Agent(output_type=Pydantic                                                                           | TypedDict)`、`result.output` で取り出す                                                                             | `from pydantic_ai import Agent`                         | `docs/output.md` |
| FallbackModel           | `FallbackModel(*models)` を `Agent(fallback_model)` に渡す                                            | `from pydantic_ai.models.fallback import FallbackModel`                                                             | `docs/models/overview.md`                               |
| OllamaProvider          | OpenAI 互換ブリッジ + Provider 注入                                                                   | `from pydantic_ai.models.openai import OpenAIChatModel` / `from pydantic_ai.providers.ollama import OllamaProvider` | `docs/models/ollama.md` (要 `pydantic-ai-slim[openai]`) |
| テストモデル (出力固定) | `TestModel()` を `agent.override(model=...)` に渡す                                                   | `from pydantic_ai.models.test import TestModel`                                                                     | `docs/api/models/test.md`                               |
| テストモデル (関数注入) | `FunctionModel(async fn)`、`fn(messages, info: AgentInfo) -> ModelResponse`                           | `from pydantic_ai.models.function import FunctionModel, AgentInfo`                                                  | `docs/api/models/function.md`                           |
| メッセージ型            | `ModelResponse(parts=[TextPart(content='...')])`                                                      | `from pydantic_ai import ModelMessage, ModelResponse, TextPart` (root re-export)                                    | `docs/api/models/function.md`                           |
| 上書き (テスト)         | `with my_agent.override(model=m): ...` コンテキストマネージャ                                         | `Agent.override` メソッド                                                                                           | `docs/api/models/test.md`                               |

### V2 で確認した V1 からの差分 (idea0.md §2 の主張を裏付け)

- `result.output` がエージェント出力の正規アクセサ (V1 の `result.data` は互換目的で残存例があるが新規コードは `.output` を使う)。
- 構造化出力は `output_type` で受け取り、Pydantic / TypedDict の両方を受容。
- FallbackModel は **モデルレベルの抽象**であり、Agent からは単一 Model に見える (member 順失敗時に次へ)。
- OllamaProvider の実体は OpenAI 互換 API クライアントを纏めたもの。`OpenAIChatModel(model_name=..., provider=OllamaProvider(base_url=..., api_key=...))` で構成する。

### 残課題 / 検証ポイント (Implementation 段階で確認)

- `2.0.0b3` 時点で `result.usage` がプロパティ化済みか (idea0.md §2 の予告)。実装時に `dir(result)` で確認しテストに記録。
- `agent.tool` のシグネチャ検証 (型チェッカが `RunContext[None]` を要求するか) は pyright strict 適合確認時に実装。
- `OllamaProvider` の `api_key` が Optional であることは `docs/models/ollama.md` で前提だが、`pydantic-ai-slim[openai]` 依存追加の必要性 (現 `pyproject.toml` は `pydantic-ai>=2.0.0b3` のみ) を `tasks.md` で明記する。

## R-2. Logfire fail-soft 計装パターン

### 結論 (Requirement 5.1 / 5.2 / 5.5 トレース)

`logfire.configure(send_to_logfire='if-token-present')` が **公式の fail-soft API**。

- `LOGFIRE_TOKEN` 未設定/空文字: 送信無効化、`instrument_*` は no-op としても spans を内部生成可能、起動失敗しない。
- トークンあり: 通常モード送信。
- 出典: `docs/how-to-guides/create-write-tokens.md` "Use `send_to_logfire='if-token-present'` to only send logs if a write token is available. This is useful for disabling logging in local development while keeping it enabled for production."

### 採用する FastAPI lifespan の手順

1. `logfire.configure(send_to_logfire='if-token-present', service_name='pydantic_ai_sandbox', environment=settings.app_env, scrubbing=ScrubbingOptions(extra_patterns=['prompt', 'tool_input', 'tool_output']))`
2. `logfire.instrument_pydantic_ai()`
3. `logfire.instrument_fastapi(app)`
4. `logfire.instrument_httpx()`
5. 例外発生時 (例: トークン形式不正) は `logger.warning(...)` で 1 行通知し、アプリは起動継続 (try/except でラップ)。

### Req 5.4 (sensitive payload non-logging by default)

- `ScrubbingOptions(extra_patterns=[...])` で raw prompt / tool 入出力をスクラブ。
- `LOG_SENSITIVE_PAYLOADS=true` (settings.log_sensitive_payloads) で opt-in。実装側で `logfire.span(..., attributes=...)` に `prompt` 系を付けるかをこのフラグで分岐。

### Req 5.5 (transport transient error must not propagate)

- Logfire 内部の OTel BatchSpanProcessor は送信失敗を自身でハンドルしユーザーコードに伝播させない (公式設計)。
- 安全のため、設定段階で発生する例外のみ try/except でフォールバック (上記手順 5)。リクエスト処理経路では追加の例外ハンドルを行わない (要らない)。
- テスト戦略: lifespan で `logfire.configure` をモンキーパッチして `RuntimeError` を上げ、`/healthz` が 200 を返すことを確認するテストを書く。

## R-3. MVP スコープ削減後の構成可能性

### 検証論点

Spec の Q1 (Ollama 単独) / Q2 (/chat のみ) を踏まえ、idea0.md §6 の `ModelFactory` 設計を **抽象は MVP に残し、未実装 provider は `NotImplementedError` で stub する** 形で実現可能か。

### 結論

可能。設計上は次の通り:

- `ModelFactory.get_model("ollama") -> Model` は実体を返す。
- `get_model("watsonx" | "anthropic" | "bedrock") -> Model` は `raise NotImplementedError("provider 'watsonx' is not implemented in MVP; tracked in 002-multi-provider")`。
- `get_model("fallback")` は `FALLBACK_ORDER` を解析し、各 member を `get_model(name)` で再帰的に解決。member が `NotImplementedError` を投げた場合、起動時に **構成エラーとして fail-fast** (Req 4.5)。
- `get_model("unknown")` は `ValueError` (Req 2.5)。
- 単体テストは `MVP では ollama のみ実装、他 3 つは NotImplementedError を出すこと` を assert (Req 2.4)。
- FallbackModel の挙動テストは `FunctionModel(failing_fn)` と `FunctionModel(success_fn)` を直接 `FallbackModel(...)` に詰め、env-var 経由ではなく単体で検証 (Req 4.4)。これにより MVP では物理的に複数 provider 実装が無くても fallback ロジックを green にできる。

## R-4. Hardcoded Model ID 検出 (Req 1.5)

### 検討した選択肢

| 案                                             | 評価                                                                       |
| ---------------------------------------------- | -------------------------------------------------------------------------- |
| ruff カスタムプラグイン                        | ruff 公式はプラグイン非対応 (内部 API)。**不採用**                         |
| `flake8-forbidden-strings` 等の外部 lint       | 追加依存、メンテ不確実。**不採用**                                         |
| pre-commit `pygrep-hooks` 形式の正規表現フック | OSS 標準。`.pre-commit-config.yaml` 1 ブロックで実装可。**採用**           |
| pytest テストとして禁則文字列を grep           | 「lint 段階で fail」要件に微妙にずれる (pytest は別ゲート)。補助として併設 |

### 採用方針

`.pre-commit-config.yaml` に local hook を追加:

```yaml
- repo: local
  hooks:
    - id: forbid-hardcoded-model-ids
      name: forbid hardcoded LLM model identifiers
      entry: '(granite4\.1:|claude-(sonnet|haiku|opus)-\d|ibm/granite-|us\.anthropic\.|jp\.anthropic\.|eu\.anthropic\.|global\.anthropic\.)'
      language: pygrep
      types: [python]
      files: ^src/
      exclude: ^src/.*/config\.py$ # default 値定義のみ許容
```

これにより lint stage (= pre-commit default stage) で grep ヒット時にコミット不可となり Req 1.5 を満たす。CI でも `pre-commit run --all-files` がこの hook を回す。

### 補助 (defense in depth)

`tests/unit/test_no_hardcoded_model_ids.py` で同様の正規表現を pathlib で走査し、引っかかれば fail。pre-commit 未インストール環境への保険。

## R-5. 品質ゲートの mise タスク化 (Req 7.5)

### 現状

`mise.toml` は `python = "3.14"`, `uv = "latest"` の 2 行のみ。タスク未定義。

### 提案 (plan.md File Structure Plan に反映)

```toml
[tools]
python = "3.14"
uv = "latest"

[tasks.lint]
run = "uv run ruff check ."

[tasks.format]
run = "uv run ruff format --check ."

[tasks."format:fix"]
run = "uv run ruff format ."

[tasks.typecheck]
run = "uv run pyright"

[tasks.test]
run = "uv run pytest"

[tasks."test:cov"]
run = "uv run pytest --cov=pydantic_ai_sandbox --cov-report=term-missing --cov-report=xml"

[tasks."test:integration"]
# Ollama が起動済み + RUN_INTEGRATION_OLLAMA=1 が前提 (CI: integration-ollama.yml / local: developer 任意)
run = "uv run pytest tests/integration -v"

[tasks.check]
depends = ["lint", "format", "typecheck", "test"]

[tasks."pre-commit:install"]
run = "uv run pre-commit install"

[tasks."pre-commit:manual"]
run = "uv run pre-commit run --all-files --hook-stage manual"

[tasks.setup]
depends = ["pre-commit:install"]
```

`mise run check` が Constitution Principle V の四ゲートを 1 コマンドで回す。

## R-6. CI 戦略 (Req 8.4 / 9.1-9.3)

### 想定 GitHub Actions ジョブ構成

| Workflow       | トリガ                                                 | 内容                                                                          |
| -------------- | ------------------------------------------------------ | ----------------------------------------------------------------------------- |
| `ci.yml`       | push, PR                                               | `mise run check` + `mise run pre-commit:manual` (pytest を含む全 hook を回す) |
| `security.yml` | push, PR, weekly cron (`schedule: cron: '17 2 * * 1'`) | `uv run pip-audit`, `uv run bandit -r src`, `gitleaks detect --redact`        |

`pip-audit` / `bandit` / `gitleaks` は dev 依存に追加 (現状 `pyproject.toml` にはない)。`gitleaks` バイナリは GitHub Actions の公式 action `gitleaks/gitleaks-action@v2` を採用。

### CI 上の優先順位

`pre-commit:manual` を CI で回す (Req 8.4) ことで pre-commit 設定そのものの破損を即検出する。これは local の pre-commit インストール忘れに対する防御線。

## R-7. 落とし穴・リスク継承 (idea0.md §14 から MVP 関連のみ抽出)

| リスク                                                        | MVP での扱い                                                                                                                                                                                                                     |
| ------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Ollama `:latest` エイリアス                                   | `.env.example` で `granite4.1:8b` (明示タグ) を指定し、`OLLAMA_MODEL_NAME` を env 必須化                                                                                                                                         |
| Pydantic AI V2 Beta 不安定性 (b1→b3 で API 変更継続)          | dependency upgrade PR が test を fail させて検出 (Req 6.5)。CI に `pydantic-ai==2.0.0b3` を pin (>= で許容しているため上限を将来追加検討)                                                                                        |
| LiteLLM サプライチェーン (2026-03 yank 事案)                  | MVP は LiteLLM 未使用 (watsonx 後続スプリント)。先回りして dev 依存にも入れない                                                                                                                                                  |
| Bedrock Inference Profile 必須                                | MVP は Bedrock 未実装 ⇒ ドキュメント注記のみ。`.env.example` の `BEDROCK_MODEL_ID` 既定値を `us.anthropic.claude-sonnet-4-6` (Cross-Region Inference Profile 形式) として明示し、後続スプリント実装者が誤って base ID を入れない |
| structured output ばらつき (Ollama Cloud は json_schema 無視) | MVP は self-host Ollama 前提なので問題化しない。`.env.example` の `OLLAMA_BASE_URL` 既定 `http://localhost:11434/v1` で固定                                                                                                      |

## R-8. Out-of-scope の確認

Spec §Out of Scope と一致。本研究で新たに out-of-scope 化したものはなし。

---

## 引用したソース

- Pydantic AI 公式 docs (Context7 経由 `/pydantic/pydantic-ai`):
  - `docs/agent.md`, `docs/tools.md`, `docs/output.md`
  - `docs/models/overview.md`, `docs/models/ollama.md`
  - `docs/api/models/test.md`, `docs/api/models/function.md`
- Pydantic Logfire 公式 docs (Context7 経由 `/pydantic/logfire`):
  - `docs/how-to-guides/create-write-tokens.md`
  - `docs/integrations/index.md`, `docs/integrations/http-clients/httpx.md`
- 本リポジトリ:
  - `specs/inputs/idea0.md` (設計母体)
  - `.sdd/memory/constitution.md` v1.0.0
  - `pyproject.toml` (lint/format/type/test 設定)

**確認日**: 2026-05-24
