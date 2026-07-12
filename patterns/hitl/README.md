# HITL 停止・承認・再開ハーネス（pydantic-ai v2 deferred-tools / 応用レイヤ）

pydantic-ai v2 公式の **deferred-tools** 機構（`ApprovalRequired` →
`DeferredToolRequests` → `ToolApproved` / `ToolDenied` → 再開）で、リスクの高い
アクションを人間の承認前で**停止**し、承認判断を受けて**再開**する
Human-in-the-Loop ハーネスの単一レーン（`patterns/hitl/`）。Anthropic の 6 ワークフロー
パターンとは別系の**承認フロー応用レイヤ**で、`sse/` レーンと同格の depth-1 独立 uv
プロジェクト（Python 3.14、独自 lockfile / ゲート）として純加算する。

承認者は**プロセス外**（UI / オペレータ）にいることを前提とし、「1 承認ステップ =
1 HTTP 往復」で `POST /run`（停止 = `DeferredToolRequests`）→ セッション保存 →
`POST /resume`（承認結果で再開）→ 終端 `SupportOutput` か再 defer を**型安全に**返す。
状態（`message_history` + 累積 `RunUsage`）は MVP ではインメモリ/プロセス内の
`SessionStore` が保持する。全ユニットは `TestModel` / `FunctionModel` 駆動で
ネットワーク I/O ゼロ、live 統合のみ dispatch-only の Ollama ワークフローへ隔離する。

## パターン契約（正本）

契約の実体は依存ゼロの [`patterns_contracts`](../contracts/) パッケージ
（[`hitl.py`](../contracts/src/patterns_contracts/hitl.py)）。下記の Python コードブロックが
その**正本**であり、
[`patterns/contracts/tests/unit/test_contract_drift.py`](../contracts/tests/unit/test_contract_drift.py)
が両者（クラス集合・フィールド集合・`Literal` 語彙）の一致を 1 点で検証する
（Req 2.4 / 006-2a NFR-5）。`ActionType` は 011 の drift parser 制約に合わせた
**col-0 名前付きエイリアス**で記述し、`action_type` フィールドはこのエイリアスを参照する
（README 側の alias 解決とパッケージ側の `Literal` 展開が対称に一致する）。HITL レーンは
3 名（`ActionType` / `ResolutionAction` / `SupportOutput`）をここからパス依存で import し、
レーン内で再定義しない（NFR-3 / Req 1.3）。

```python
ActionType = Literal["DISCOUNT", "UPGRADE", "ESCALATE"]   # 是正の閉語彙（col-0 名前付きエイリアス、R2.2）

class ResolutionAction(BaseModel):          # エージェントが提案する単一の是正ステップ
    action_type: ActionType                 # 是正の種類。閉語彙 = ActionType（R2.2）
    target_id: str                          # アクション適用対象エンティティの識別子
    amount_usd: float = Field(ge=0)         # 関与金額（USD）。負値禁止 = ポリシー検査対象（R3.5）

class SupportOutput(BaseModel):             # HITL サポートエージェントの終端構造化出力（R2.1）
    summary_of_issue: str                   # 顧客課題の簡潔な再述
    reasoning: str                          # 提案アクションプランの根拠
    requires_human_approval: bool           # action_plan のいずれかが人間承認を要したか
    action_plan: list[ResolutionAction]     # 是正ステップ列（自動承認 + 人間承認の順序保持）
```

契約が所有するのは**構造化出力の形状**と `action_type` の閉語彙のみ。承認判断そのものの
表現（pydantic-ai の `ToolApproved` / `ToolDenied`）は再モデル化せずそのまま使い、HTTP
リクエスト/レスポンス形状はレーンの [`app.py`](src/patterns_hitl/app.py) が、ポリシー閾値は
レーン設定（`HitlSettings`）が所有する。

## 停止・承認・再開フロー

`output_type=[SupportOutput, DeferredToolRequests]` の Agent を `POST /run` の prompt で実行する。
`requires_approval` 付きツール（`escalate_to_legal`）が呼ばれるか、条件付きツール
（`apply_discount` が閾値超過かつ `not ctx.tool_call_approved`）が `raise ApprovalRequired` すると、
run は `result.output` に `DeferredToolRequests`（`approvals: list[ToolCallPart]`）を載せて**停止**する。
ハーネスは `message_history`（`result.all_messages()`）と累積 `usage`（`RunUsage`）を
`SessionStore` に保存し、pending 一覧（`tool_call_id` / `tool_name` / `args`）と `session_id` を返す。

`POST /resume` は承認判断を `DeferredToolResults(approvals={tool_call_id: ToolApproved() | ToolDenied()})`
へ写像し、保存済み履歴 + 累積 usage を再注入して `user_prompt` なしで**再開**する。承認された
ツールは実行され（`override_args` で引数上書き可）、拒否は `ToolDenied(message=...)` の理由を
モデルへ返して代替終端を促す。再開後は終端 `SupportOutput`（`TerminalResult`）か、さらに承認が
必要な場合の再 defer（`PendingResult`）のいずれかを返す — この 2 分岐を
`isinstance(result.output, DeferredToolRequests)` の明示分岐で型安全に確定する（R6.1）。

| 段 | 実装 | 決定論シーム / 不変条件 |
|---|---|---|
| DI seam | `create_app(*, agent, store=None, instrument=True)`（[`app.py`](src/patterns_hitl/app.py)） | sse の keyword-only 注入を鏡映。テストは `FunctionModel` / `TestModel` 製 agent と素の `SessionStore()` を注入し実 I/O ゼロで全経路駆動（R8.6 / R10.4） |
| エージェント | `build_agent(model)`（[`agent.py`](src/patterns_hitl/agent.py)） | `output_type=[SupportOutput, DeferredToolRequests]`、`instructions=...`（`system_prompt` 不使用）、`instrument=True` は渡さない（v2 で `TypeError`、R3.2） |
| 停止・再開 | `start` / `resume`（[`harness.py`](src/patterns_hitl/harness.py)） | `usage_limits=LIMITS`、resume は `message_history` + `deferred_tool_results` + `usage=stored.usage` を再注入し予算を run 間通算（R7.1/7.2）。`UsageLimitExceeded` は専用例外へ変換（R7.3） |
| 状態保持 | `SessionStore`（[`store.py`](src/patterns_hitl/store.py)） | `session_id → (message_history, RunUsage)` のインメモリ正本（R8.4）。Protocol が 013 / Durable 差し替え点 |
| ポリシー検査 | `@output_validator`（[`agent.py`](src/patterns_hitl/agent.py)） | `action_plan` 内に閾値超過額 + `requires_human_approval=False` があれば `ModelRetry`（R3.5） |

## 型安全

- 契約 `ActionType` / `ResolutionAction` / `SupportOutput` は `patterns_contracts` の単一実体。
  レーンはパス依存で import し再定義しない（NFR-3）。pyright **strict**（Python 3.14）で検査。
- 承認判断は pydantic-ai の `ToolApproved` / `ToolDenied` をそのまま用い、API スキーマ
  （`Decision`）→ これらへの写像は `app.py` が所有する。`Any` は API 境界（`args` 写像）に留め、
  内側へは Pydantic モデルへ narrow してから流す。
- 再開後も `DeferredToolRequests` が返り得る点を `isinstance` 分岐で型分割し、
  `TerminalResult | PendingResult` として呼び出し側へ返す（R6.1）。

## テスト

- **オフライン hermetic**（NFR）: 全 unit がネットワーク I/O ゼロで完走。conftest で
  `pydantic_ai.models.ALLOW_MODEL_REQUESTS = False` を強制する。
- **FunctionModel 台本**: 終端応答は `ToolCallPart("final_result", ...)`（出力ツール呼び出し）
  必須（テキスト終端は出力リトライ枯渇で失敗、R10.2）。1 メッセージ目 → 承認必須ツール呼び出し、
  以降 → `final_result` 終端の 2 フェーズ台本で 停止 → 承認 → 再開 → `SupportOutput` を検証する。
- **TestModel(call_tools=[...])**: 既定 `'all'` は `requires_approval` ツールも呼ぶため、
  承認不要経路の検証では対象を絞る（R10.3）。
- **カバレッジゲート**: 兄弟レーン parity で `fail_under = 98`（NFR）。追加した `patterns_contracts`
  形状は contracts パッケージのゲートで別途カバーする。

## 可観測性

- [`observability.py`](src/patterns_hitl/observability.py) の `enable_observability(app)` が
  `logfire.configure()` + `logfire.instrument_pydantic_ai()` + `instrument_fastapi(app)` を
  try/except で包む **fail-soft ブートストラップ**（R9.1）。exporter 未設定・失敗時は `False` を
  返して起動を継続する（テストは未設定環境で `create_app()` が成功することを検証）。
- `Agent(instrument=True)` は v2 に存在しない（`TypeError`）ため計装は
  `logfire.instrument_pydantic_ai()` に統一する（レビュー修正 ①、R3.2）。

## セキュリティ

- **モデル ID ハードコード禁止**: live モデルは env 専属（`OLLAMA_MODEL_NAME` 等）。ソースに
  モデル文字列を置かず、repo 全域の `forbid-hardcoded-model-ids`（第1層 pre-commit + 第2層
  backing test）が `patterns/hitl/src/` を走査する（R12）。
- **v1 併用時の下限（記述のみ）**: pydantic-ai v1 を併用する場合、SSRF/XSS 系アドバイザリの
  修正を含む **`>=1.99.0`** をフロアとする。本 HITL レーンは既知アドバイザリのない v2 ライン
  （`pydantic-ai-slim>=2.9.0`）上に構築するため、この下限は v1 相互運用時の要件（R13.2）。
- **信頼できない入力の SSRF リスク（記述のみ）**: 外部から渡る `message_history` や URL は
  信頼できない入力として扱う。ツールがそれらの URL を fetch する経路は SSRF ベクタになり得るため、
  egress は許可リスト経由の **`safe_download` 経路**へ集約すべき — ただし本 spec では
  **egress 強化は実装しない**（設計ノートのみ、実装は 013 のスコープ）。
- **認証・レート制限・消費セマンティクス**: 本 MVP のスコープ外。未知 session は `404`、
  予算超過は loud にエラー化するにとどめ、セッション ID 衛生 / 承認監査証跡 /
  `/resume` の消費セマンティクスは [013-agentic-ai-security](../../specs/013-agentic-ai-security/) が担う。
- OWASP（LLM Top 10 / Agentic AI）への詳細マッピングは
  [SECURITY-NOTES.md](../SECURITY-NOTES.md) を参照。

## Durable Execution（将来フェーズ / 記述のみ）

MVP の `SessionStore` はインメモリ/プロセス内であり、プロセス再起動を跨いだ永続化や
long-lived な承認待ちには耐えない。恒久運用では **Durable Execution** への差し替えが対象になる。
pydantic-ai が**公式に統合をドキュメント化**している先は次の 3 つ:

- **Temporal**
- **DBOS**
- **Prefect**

（**Restate** は pydantic-ai 側ではなく **Restate 自身の SDK** が pydantic-ai 連携を提供する。）

これらは本 spec では**実装しない**（将来フェーズ）。`SessionStore` を細い Protocol として
設計してあるため、Durable / 永続 DB バックエンドはこの Protocol の差し替え点で接続できる。

## 使用ライブラリと検証基準版

| ライブラリ | バージョン | 役割 / 注記 |
|---|---|---|
| `pydantic-ai-slim[openai]` | `>=2.9.0` | deferred-tools（`ApprovalRequired` / `DeferredToolRequests` / `ToolApproved` / `ToolDenied`）と `UsageLimits`。`openai` extra は Ollama 結合用 |
| `fastapi` | `>=0.136` | `POST /run` / `POST /resume` app-factory（`requires-python>=3.14`、sse レーンと同床） |
| `pydantic` | `>=2,<2.14` | 契約モデル基底。runtime 閉包を stable に固定 |
| `logfire` | 最新 | `instrument_pydantic_ai` / `instrument_fastapi` の fail-soft 計装（R9.1） |
| `pytest` / `pytest-asyncio` / `pytest-cov` / `pyright` / `ruff` / `pip-audit` / `httpx` | dev | `asyncio_mode = "auto"`、`fail_under = 98`、pyright strict、レーン lockfile の pip-audit |

> **検証基準版（R13.3）**: 本レーンの pydantic-ai v2 HITL API 使用（停止・再開フロー、
> `output_type=[SupportOutput, DeferredToolRequests]`、`UsageLimits` の run 間通算、
> `TestModel(call_tools=...)`）は **pydantic-ai-slim 2.9.0 / 2026-07-11** の実行検証を基準とする。
> pyproject のフロア `>=2.9.0` はこの基準に固定する。モデル ID は版に追従して 3〜6 か月で
> 変わるため、コードにハードコードせず env 経由で解決する。
