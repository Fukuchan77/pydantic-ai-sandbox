# 012-agentic-ai-design — Discovery & Research Log

要件(spec.md)を設計へ翻訳する前の調査記録。API 事実はレビュー
[specs/document-review/agentic-ai-design-v2-review.md](../document-review/agentic-ai-design-v2-review.md)
の実行検証(pydantic-ai-slim 2.9.0 venv)を一次ソースとする。

## Discovery type

既存レーン規約への「新レーン純加算」+ pydantic-ai v2 固有機構(deferred tools)の初採用。
ランタイム本線・既存レーン・凍結契約は無改変。

## Investigations

### I-1: pydantic-ai 2.9.0 の HITL API は実行検証済み(最重要)

レビュー付録の検証スクリプトで以下を**実行確認**済み。設計はこの事実に直接立脚する:

- `Agent(instrument=True)` は `TypeError`(v2 に kwarg なし)→ 計装は
  `logfire.instrument_pydantic_ai()` 一本(R3.2 / R9.1)。
- 停止・再開フロー: 条件付き `raise ApprovalRequired` → `result.output` が
  `DeferredToolRequests`(`approvals: list[ToolCallPart]`)→
  `run(deps=..., message_history=result.all_messages(), deferred_tool_results=DeferredToolResults(approvals={id: ToolApproved()}))`
  で `user_prompt` なし再開 → `SupportOutput` 終端。
- `output_type=[SupportOutput, DeferredToolRequests]` ではテキスト終端が
  「Please call a tool.」リトライ→枯渇エラー。`FunctionModel` の終端応答は
  `ToolCallPart("final_result", {...})` 必須(R10.2)。
- `UsageLimits(request_limit, tool_calls_limit, total_tokens_limit)` 実在。`run()` は
  `usage=` を受け、渡せば予算が run 間で累積する(R7.2)。
- `TestModel(call_tools=...)` 実在(`models/test.py:77`)— 既定 `'all'` は
  `requires_approval` ツールも呼ぶため、承認フロー以外のテストでは絞り必須(R10.3)。
- `ctx.tool_call_approved`(`_run_context.py:92`)が条件付き承認の権威(R5.4)。

### I-2: FastAPI アプリレーンの直近前例は sse レーン

`patterns/sse/` が depth-1 アプリレーンのテンプレート:

- `pyproject.toml`: `requires-python = ">=3.14"`、`patterns-contracts` を
  `[tool.uv.sources] path = "../contracts", editable = true`(depth-1 なので 1 段)、
  ruff ルールセット・pyright strict(`pythonVersion = "3.14"`)・
  `asyncio_mode = "auto"`・`fail_under = 98` まで完備 — **そのまま雛形にする**。
- `app.py:125 create_app(...)` の app-factory + テストは `with TestClient(app):`(R8.6)。
- レーン src は自レーン所有、兄弟レーン import 禁止(NFR-3 規約)。

### I-3: 契約所有則とドリフト検知

- 契約実体はレーンごとに `patterns_contracts/<lane>.py` 1 モジュール
  (`sse.py` / `rag.py` / `deep_research.py` ...)+ `__init__.py` フラット再エクスポート。
- 正本はレーン README の `## パターン契約` 直後の python fence。
  `patterns/contracts/tests/unit/test_contract_drift.py:49 _README_PATHS` に登録すると
  単一点で「正本 == パッケージ実体」を機械検証(R2.4)。
- `Literal` は col-0 名前付きエイリアス(011 AD-1 の drift parser 制約)→
  `ActionType = Literal["DISCOUNT", "UPGRADE", "ESCALATE"]` はこの形式で書く(R2.2)。

### I-4: レーン列挙面は 4 箇所(mise / patterns-ci / security.yml / dependabot)

- `mise.toml` `patterns:{setup,lint,format,typecheck,test,audit}`: contracts →
  `frameworks/*/` glob ループ → rag / sse / deep-research の**明示行**。hitl も明示行(R1.4)。
- `.github/workflows/patterns-ci.yml`: frameworks 3 レーンは `matrix.lane`
  (working-directory が `patterns/frameworks/` 前提)、rag/sse/deep-research は専用ジョブ。
  depth-1 の hitl は**専用ジョブ**が対称(R1.6)。`on.push.paths` への `patterns/hitl/**` 追記も必要。
- `security.yml` `patterns-pip-audit` matrix: `{ lane: hitl, dir: patterns/hitl }` 行を追加
  (R1.6 — 2026-07 nltk 事案の教訓: 未登録レーンは daily CVE cron の死角)。
- `dependabot.yml`: pip エコシステムの `directories` は現状 frameworks 3 レーンのみ。
  pydantic-ai 依存レーンとして `/patterns/hitl` を追加(R1.6)。
- 統合: `patterns:test:integration:<lane>` タスク(`RUN_INTEGRATION_PATTERNS=1` +
  `EXPECT_LIVE_TESTS=<n>`)+ dispatch-only の Ollama live ワークフロー(R11)。

### I-5: Python 3.14 はこの開発コンテナでローカル実行不可

コンテナは 3.13 まで(uv の 3.14 ダウンロードは proxy 403)。sse / frameworks/pydantic-ai
と同じ制約であり、レーンのローカル検証は CI(GitHub runner)前提。設計への影響:
コードは 3.13 でも動く書き方を保ちつつ(検証容易性)、ゲート宣言は 3.14 を維持。

### I-6: 観測性の既存シームは OTel `configure_tracing`、Req 9.1 は logfire

既存レーンは `observability.py` の `configure_tracing`(injected exporter > OTLP env >
no-op)。R9.1 は `logfire.instrument_pydantic_ai()` を明示要求する。logfire は OTel 上に
構築されるため矛盾しない — hitl レーンは logfire ベースの fail-soft ブートストラップを
自レーン所有で持つ(AD-5)。

## Existing patterns to reuse

- `patterns/sse/pyproject.toml` — レーンゲート一式の雛形(ruff/pyright/pytest/coverage)。
- `patterns/sse/src/patterns_sse/app.py` — `create_app` app-factory + lifespan。
- `patterns/contracts/tests/unit/test_contract_drift.py` — `_README_PATHS` 登録だけで
  正本検証が効く。
- `mise.toml` の rag/sse/deep-research 明示行、`security.yml` matrix 行、
  `patterns-integration-ollama.yml` の `EXPECT_LIVE_TESTS` ゲート。
- レビュー付録の検証スクリプト(FunctionModel 台本・HITL 停止再開)— そのまま
  ユニットテストの骨格に転用できる。

## External dependencies

- `pydantic-ai-slim[openai]>=2.9.0`(検証基準版。OllamaProvider 用に openai extra)
- `fastapi>=0.136` / `pydantic>=2,<2.14`(sse レーンと同床)
- `logfire`(R9.1。`logfire[fastapi]` 相当の instrument を fail-soft で)
- dev: `pytest` / `pytest-asyncio` / `pytest-cov` / `pyright` / `ruff` / `pip-audit` / `httpx`

## Architecture decisions

### AD-1: レーンは depth-1 `patterns/hitl/`、sse をミラー

frameworks 配下ではなくアプリケーションレーン(rag/sse/deep-research)と同格。
contracts へのパスは `../contracts`。CI は専用ジョブ。

### AD-2: 契約は `patterns_contracts/hitl.py` に新設、README 正本

`ActionType`(col-0 Literal エイリアス)/ `ResolutionAction` / `SupportOutput` を所有。
`amount_usd: float = Field(ge=0)` を含む(R3.5 のポリシー検査対象)。既存契約は無改変。

### AD-3: ハーネスは「1 ステップ = 1 HTTP 往復」、ループは呼び出し側

`/resume` が再 defer を返すのは正常応答(R8.3)— API 文脈での R6.1 は
「`isinstance` で 2 分岐を型安全に返す」ことで満たす。プロセス内で terminal まで回す
`run_until_terminal` ヘルパーは提供しない(承認者はプロセス外、が本 spec の前提)。

### AD-4: 予算通算は SessionStore が `RunUsage` を保持し `usage=` で再注入

`UsageLimits` はレーン定数(env 上書き可)。超過は `UsageLimitExceeded` を捕捉して
loud にエラー化(HTTP マッピングは 013 R2.4 の責務)。

### AD-5: 観測性は logfire fail-soft ブートストラップを自レーン所有

`observability.py` の `enable_observability()` が `logfire.configure(...)` +
`instrument_pydantic_ai()` + `instrument_fastapi(app)` を try/except で包む(R9.1)。
exporter 未設定・失敗は起動を止めない。テストは未設定環境で create_app が成功することを検証。

### AD-6: モデル ID は env ルーティング、既定はテストダブル

ソースにモデル文字列を置かない(R12)。live 統合のみ `OLLAMA_MODEL_NAME` 系 env を
読む。unit は `Agent.override(model=TestModel(...)/FunctionModel(...))` で駆動し、
`models.ALLOW_MODEL_REQUESTS = False` を conftest で強制。

### AD-7: 統合は dispatch-only Ollama ワークフローへ追加

`patterns:test:integration:hitl`(`EXPECT_LIVE_TESTS` 宣言)を新設し、
`patterns-integration-ollama.yml` に組み込む。`pull_request:` トリガーは付けない(R11.3)。
