# 012-agentic-ai-design — Implementation Tasks

plan.md(design 承認済み)をタスクへ分解する。TDD(赤 → 緑)を各境界で徹底する。

Conventions:
- `- [ ]` pending, `- [x]` done, `- [ ]*` optional/deferrable test.
- `(P)` = safe to run in parallel (no dependency, disjoint boundary).
- Every task (major and sub) declares `_Boundary:_` and `_Depends:_`.
- Requirement coverage lists numeric IDs only, comma-separated.

---

## 1. HITL 契約の実体定義(`patterns_contracts/hitl.py` + 契約テスト)

_Boundary:_ `patterns/contracts/src/patterns_contracts/hitl.py`, `patterns/contracts/src/patterns_contracts/__init__.py`, `patterns/contracts/tests/unit/test_hitl_contract.py`
_Depends:_ none
_Requirements:_ 2.1, 2.2, 2.3

`ActionType` / `ResolutionAction` / `SupportOutput` を依存ゼロの `patterns_contracts` に
新規契約モジュールとして純加算し(既存契約は無改変)、root からフラット再エクスポートする。

- [x] 1.1 契約形状の失敗テストを先行作成する(hermetic)。`ActionType` 閉語彙(`"DISCOUNT" | "UPGRADE" | "ESCALATE"` 受理、語彙外は ValidationError)、`ResolutionAction.amount_usd` の `ge=0` 拒否、`SupportOutput` 必須 4 フィールド(`summary_of_issue` / `reasoning` / `requires_human_approval` / `action_plan`)を検証する。**赤を確認する。**
  _Boundary:_ `patterns/contracts/tests/unit/test_hitl_contract.py`
  _Depends:_ none
  _Requirements:_ 2.2, 2.3
- [x] 1.2 `hitl.py` に契約実体を実装しテストを緑化する。`ActionType = Literal["DISCOUNT", "UPGRADE", "ESCALATE"]`(col-0 名前付きエイリアス — drift parser 対称、research.md I-3)、`ResolutionAction`(`action_type: ActionType` / `target_id: str` / `amount_usd: float = Field(ge=0)`)、`SupportOutput`。`__init__.py` の `__all__` へ 3 名を追加する。
  _Boundary:_ `patterns/contracts/src/patterns_contracts/hitl.py`, `patterns/contracts/src/patterns_contracts/__init__.py`
  _Depends:_ 1.1
  _Requirements:_ 2.1, 2.2, 2.3

### Implementation Notes

- 011 と同型の sequenced-red: `__all__` 追加時点で drift テストが「package 側に存在・README
  未登録」で赤化する。Task 2 が緑化するまでが設計どおりの中間状態。

---

## 2. レーン README 正本化とドリフト登録

_Boundary:_ `patterns/hitl/README.md`, `patterns/contracts/tests/unit/test_contract_drift.py`
_Depends:_ 1
_Requirements:_ 2.1, 2.4, 13.1, 13.2, 13.3

- [x] 2.1 `patterns/hitl/README.md` を作成する。`## パターン契約` 直後の python fence に正本ブロック(Task 1.2 と同一)を記載し、別節に: 停止・承認・再開フローの解説、Durable Execution ノート(公式統合 = Temporal / DBOS / Prefect、Restate は Restate 側 SDK)、セキュリティノート(v1 併用時 `>=1.99.0` フロア、信頼できない `message_history`/URL の SSRF リスク、`safe_download` 経路 — 実装はしない)、検証基準版(pydantic-ai-slim 2.9.0 / 2026-07-11)を記す。
  _Boundary:_ `patterns/hitl/README.md`
  _Depends:_ 1.2
  _Requirements:_ 2.1, 13.1, 13.2, 13.3
- [x] 2.2 `test_contract_drift.py` の `_README_PATHS` に `"hitl": patterns/hitl/README.md` を 1 行追加し(parser 無改修)、drift テストと既存契約テスト全体を緑に保つ。
  _Boundary:_ `patterns/contracts/tests/unit/test_contract_drift.py`
  _Depends:_ 2.1
  _Requirements:_ 2.4

---

## 3. (P) レーン足場(独立 uv プロジェクト + ゲート設定)

_Boundary:_ `patterns/hitl/pyproject.toml`, `patterns/hitl/uv.lock`, `patterns/hitl/.python-version`, `patterns/hitl/src/patterns_hitl/__init__.py`, `patterns/hitl/tests/unit/conftest.py`
_Depends:_ 1
_Requirements:_ 1.1, 1.2, 1.3, 1.5, 10.1

sse レーンの pyproject を雛形に(research.md I-2)独立 uv プロジェクトを起こす。

- [x] 3.1 `pyproject.toml` / `.python-version`(3.14)/ `src/patterns_hitl/__init__.py` + `py.typed` を作成する。依存: `patterns-contracts`(`[tool.uv.sources] path = "../contracts", editable = true`)、`pydantic-ai-slim[openai]>=2.9.0`、`fastapi>=0.136`、`logfire`。dev: `pytest` / `pytest-asyncio` / `pytest-cov` / `pyright` / `ruff` / `pip-audit` / `httpx`。ゲート: ruff 同一セット、pyright strict(3.14)、`asyncio_mode = "auto"`、`fail_under = 98`。`beeai-framework` / `llamaindex` は宣言しない。`uv lock` で lockfile を生成する。
  _Boundary:_ `patterns/hitl/pyproject.toml`, `patterns/hitl/uv.lock`, `patterns/hitl/.python-version`
  _Depends:_ 1.2
  _Requirements:_ 1.1, 1.2, 1.3, 1.5, 10.1
- [x] 3.2 `tests/unit/conftest.py` で `pydantic_ai.models.ALLOW_MODEL_REQUESTS = False` を強制し、スモークテスト(`import patterns_hitl` + 契約 import)で足場の緑を確認する。**赤→緑の証跡(M-2)**: ローカルで 3.14 が実行不能な場合、赤・緑それぞれの確認を patterns-ci(hitl ジョブ)で行い、CI run URL をコミットメッセージまたはタスク完了記録(PDCA ログ)へ残す — sse / frameworks/pydantic-ai の既存 3.14 レーンと同じ運用。以降の全タスク(T4〜T6)の赤確認にも同手順を適用する。
  _Boundary:_ `patterns/hitl/tests/unit/conftest.py`, `patterns/hitl/tests/unit/test_smoke.py`
  _Depends:_ 3.1
  _Requirements:_ 10.1

### Implementation Notes

- この開発コンテナは Python 3.14 を uv ダウンロードできない(research.md I-5)。`uv lock` は
  3.13 インタープリタでも解決可能(`requires-python` メタデータ駆動)。テスト実行が 3.14 必須で
  ローカル不能な場合は CI(GitHub runner)で緑を確認し、その旨をタスク完了記録に残す。

---

## 4. エージェント構築(`agent.py` + ポリシーセンサー)

_Boundary:_ `patterns/hitl/src/patterns_hitl/agent.py`, `patterns/hitl/src/patterns_hitl/settings.py`, `patterns/hitl/tests/unit/test_agent_tools.py`, `patterns/hitl/tests/unit/test_output_validator.py`, `patterns/hitl/pyproject.toml`, `patterns/hitl/uv.lock`
_Depends:_ 3
_Requirements:_ 3.1, 3.2, 3.3, 3.4, 3.5, 4.1, 5.4, 10.3, 12.1

- [x] 4.1 失敗テストを先行作成する。(a) `test_output_validator.py`: `FunctionModel` 台本で閾値超過額 + `requires_human_approval=False` の終端 → `ModelRetry` フィードバック後に修正版終端で成功、リトライ枯渇 path も検証。(b) `test_agent_tools.py`: `TestModel(call_tools=["search_customer_context"])` で承認不要経路が `SupportOutput` 終端すること、`apply_discount` の閾値以下は承認なしで実行されること。**赤を確認する。**
  _Boundary:_ `patterns/hitl/tests/unit/test_output_validator.py`, `patterns/hitl/tests/unit/test_agent_tools.py`
  _Depends:_ 3.2
  _Requirements:_ 3.5, 10.3
- [x] 4.2 `settings.py`(`HitlSettings`: `risk_threshold_usd` 既定 50.0、live 用モデル名は env のみ)と `agent.py` の `build_agent(model)` を実装しテストを緑化する。`output_type=[SupportOutput, DeferredToolRequests]`、`instructions=...`(`system_prompt` 不使用)、`instrument=True` は渡さない。ツール: `search_customer_context`(承認不要・フェイク deps 検索)、`apply_discount`(閾値超過かつ `not ctx.tool_call_approved` で `raise ApprovalRequired`)、`escalate_to_legal`(`requires_approval=True`)。`@output_validator` でポリシー検査(`ModelRetry`)。モデル文字列はソースに置かない。
  _Boundary:_ `patterns/hitl/src/patterns_hitl/agent.py`, `patterns/hitl/src/patterns_hitl/settings.py`, `patterns/hitl/pyproject.toml`, `patterns/hitl/uv.lock`
  _Depends:_ 4.1
  _Requirements:_ 3.1, 3.2, 3.3, 3.4, 3.5, 4.1, 5.4, 12.1

---

## 5. ハーネス + セッションストア(停止・承認・再開・予算通算)

_Boundary:_ `patterns/hitl/src/patterns_hitl/harness.py`, `patterns/hitl/src/patterns_hitl/store.py`, `patterns/hitl/tests/unit/test_stop_approve_resume.py`, `patterns/hitl/tests/unit/test_store.py`, `patterns/hitl/tests/support/function_model_scripts.py`
_Depends:_ 4
_Requirements:_ 4.1, 4.2, 5.1, 5.2, 5.3, 6.1, 7.1, 7.2, 7.3, 8.4, 10.2, 10.4

- [x] 5.1 失敗テスト `test_stop_approve_resume.py` を先行作成する(`tests/support/function_model_scripts.py` の FunctionModel 台本駆動 — 具体形は research.md I-1 の実行確認済み 2 フェーズ台本(`len(messages)==1` → 承認必須ツール呼び出し、以降 → `ToolCallPart("final_result", ...)`)を転用。終端応答は必ず `ToolCallPart("final_result", ...)`)。ケース: (a) 停止 → `PendingResult`(`tool_name`/`args`/`tool_call_id` 露出)、(b) `ToolApproved` 再開 → ツール実行 → `SupportOutput` 終端、(c) `ToolApproved(override_args=...)` → 上書き引数で実行、(d) `ToolDenied(message=...)` → ツール未実行 + モデルが拒否理由を受けて代替終端、(e) 再開後の再 defer → 2 度目の `PendingResult`(型ガード)、(f) usage 通算 — resume に前 run の `usage` が渡り、低い `total_tokens_limit` で 2 run 目に `UsageLimitExceeded` 由来の専用例外。**赤を確認する。**
  _Boundary:_ `patterns/hitl/tests/unit/test_stop_approve_resume.py`, `patterns/hitl/tests/support/function_model_scripts.py`
  _Depends:_ 4.2
  _Requirements:_ 10.2, 10.4
- [x] 5.2 `store.py`(`SessionStore`: uuid4 生成 / `SessionRecord(history, usage)` の create・get・update)と `harness.py`(`start(prompt)` / `resume(session_id, decisions)` — `usage_limits=LIMITS`、resume は `message_history` + `deferred_tool_results` + `usage=stored.usage`、戻り値は `isinstance` 分岐で `TerminalResult | PendingResult`、`UsageLimitExceeded` は `HitlBudgetExceededError` へ変換)を実装しテストを緑化する。
  _Boundary:_ `patterns/hitl/src/patterns_hitl/harness.py`, `patterns/hitl/src/patterns_hitl/store.py`, `patterns/hitl/tests/unit/test_store.py`
  _Depends:_ 5.1
  _Requirements:_ 4.1, 4.2, 5.1, 5.2, 5.3, 6.1, 7.1, 7.2, 7.3, 8.4

### Implementation Notes

- FunctionModel 台本はレビュー付録の検証スクリプト(document-review)で動作確認済みの形を
  転用する: 1 メッセージ目 → ツール呼び出し、以降 → `final_result` 出力ツール呼び出し。
- `LIMITS = UsageLimits(request_limit=8, tool_calls_limit=10, total_tokens_limit=20_000)` を
  レーン定数とし、テストは低い limit を注入して超過 path を決定論化する。

---

## 6. FastAPI アプリ + 観測性(app-factory / `/run` / `/resume` / fail-soft 計装)

_Boundary:_ `patterns/hitl/src/patterns_hitl/app.py`, `patterns/hitl/src/patterns_hitl/observability.py`, `patterns/hitl/tests/unit/test_api.py`, `patterns/hitl/tests/unit/test_observability.py`
_Depends:_ 5
_Requirements:_ 5.2, 5.3, 8.1, 8.2, 8.3, 8.5, 8.6, 9.1

- [ ] 6.1 失敗テストを先行作成する。(a) `test_api.py`: `with TestClient(app):` で — `/run` 承認不要 prompt → `{status: "completed", output}` / `/run` 承認要 → `{status: "pending_approval", session_id, approvals}` / `/resume` 承認 → completed / `/resume` 拒否 → completed(代替案)/ 未知 session → 404 / `Decision` の相互排他違反(approved=True + message)→ 422。(b) `test_observability.py`: exporter/logfire 未設定環境で `create_app()` 起動が失敗しない(戻り値 False 許容)。**赤を確認する。**
  _Boundary:_ `patterns/hitl/tests/unit/test_api.py`, `patterns/hitl/tests/unit/test_observability.py`
  _Depends:_ 5.2
  _Requirements:_ 8.6, 9.1
- [ ] 6.2 `app.py`(**DI シーム `create_app(*, agent, store=None, instrument=True)`** — sse の keyword-only 注入署名を鏡映(plan.md HitlApp / research.md AD-8)。harness は app 内部で `(agent, store)` から組み立てる。`RunRequest` / `CompletedResponse` / `PendingResponse` / `ResumeRequest` / `Decision`(model_validator で相互排他)、`Decision` → `ToolApproved`/`ToolDenied` 写像、lifespan で `instrument=True` のとき `enable_observability(app)`)と `observability.py`(`enable_observability`: `logfire.configure` + `instrument_pydantic_ai` + `instrument_fastapi` を try/except、失敗は False 返却で続行)を実装しテストを緑化する。6.1 のテストは FunctionModel 製 agent + 素の `SessionStore()` を注入し `instrument=False` で駆動する(観測性テストのみ True)。
  _Boundary:_ `patterns/hitl/src/patterns_hitl/app.py`, `patterns/hitl/src/patterns_hitl/observability.py`
  _Depends:_ 6.1
  _Requirements:_ 5.2, 5.3, 8.1, 8.2, 8.3, 8.5, 8.6, 9.1

---

## 7. (P) リポジトリ列挙面への登録(mise / patterns-ci / security.yml / dependabot)

_Boundary:_ `mise.toml`, `.github/workflows/patterns-ci.yml`, `.github/workflows/security.yml`, `.github/dependabot.yml`
_Depends:_ 3
_Requirements:_ 1.4, 1.6, 11.1, 11.2

- [ ] 7.1 `mise.toml` の `patterns:{setup,lint,format,typecheck,test,audit}` に `patterns/hitl` の明示行を(contracts → frameworks glob → rag/sse/deep-research の後に)追加し、`patterns:test:integration:hitl`(`RUN_INTEGRATION_PATTERNS=1 EXPECT_LIVE_TESTS=2`)を新設する。`EXPECT_LIVE_TESTS=2` は T8.1 の live 本数(e2e 承認経路 1 本 + 拒否経路 1 本)と一致させ、空振り緑を決定論的に赤化する。
  _Boundary:_ `mise.toml`
  _Depends:_ 3.1
  _Requirements:_ 1.4, 11.1, 11.2
- [ ] 7.2 `.github/workflows/patterns-ci.yml` に `patterns/hitl/**` の paths トリガーと専用ジョブ(rag/sse と同型: lock --check → sync --locked → ruff → pyright → pytest → pip-audit)を追加し、`.github/workflows/security.yml` の `patterns-pip-audit` matrix に `{ lane: hitl, dir: patterns/hitl }` を、`.github/dependabot.yml` の pip `directories` に `/patterns/hitl` を追加する(**方針 = AD-9**: dependabot は pydantic-ai 依存レーンを個別監視。応用兄弟レーン未監視は既知ギャップとしてスコープ外)。既存の workflow ガードテスト(`tests/unit/test_ollama_ci_workflows.py` 等)が緑のままであることを確認する。
  _Boundary:_ `.github/workflows/patterns-ci.yml`, `.github/workflows/security.yml`, `.github/dependabot.yml`
  _Depends:_ 3.1
  _Requirements:_ 1.6
- [ ] 7.3 モデル ID 二層ガードの**第2層**を新レーンへ到達させる(gap-analysis H-1 / research.md AD-10)。`tests/unit/test_no_hardcoded_model_ids.py` の `_iter_scanned_py_files()` の走査対象へ `patterns/*/src` を追加する(禁止リテラル集合は無改変)。TDD: まず走査拡張だけを入れた状態で `patterns/hitl/src` に一時ファイルで禁止リテラルを植え込み**赤を確認**(コミットしない)→ 撤去して緑を恒久化。既存レーン src が現状クリーンであることを事前 grep で確認してから拡張する。
  _Boundary:_ `tests/unit/test_no_hardcoded_model_ids.py`
  _Depends:_ 3.1
  _Requirements:_ 12.2

---

## 8. Live 統合レーン(dispatch-only Ollama e2e)

_Boundary:_ `patterns/hitl/tests/integration/`, `.github/workflows/patterns-integration-ollama.yml`
_Depends:_ 6, 7
_Requirements:_ 11.1, 11.2, 11.3, 12.1

- [ ] 8.1 `tests/integration/test_ollama_hitl_e2e.py` を作成する。`RUN_INTEGRATION_PATTERNS=1` ゲート、`OLLAMA_MODEL_NAME` env 経由でモデル解決(ハードコードなし)、live モデルで 停止 → 承認 → 再開 → `SupportOutput` の e2e を最小 1 本 + 拒否 path 1 本。conftest は既存レーンの live ガード(`pytest_live_guard`)方式を踏襲し、`EXPECT_LIVE_TESTS` と本数を一致させる。
  _Boundary:_ `patterns/hitl/tests/integration/`
  _Depends:_ 6.2
  _Requirements:_ 11.1, 11.2, 12.1
- [ ] 8.2 `patterns-integration-ollama.yml` に hitl ジョブを追加する(`workflow_dispatch` のみ — `pull_request:` トリガーを付けない)。workflow ガードテストの緑を確認する。
  _Boundary:_ `.github/workflows/patterns-integration-ollama.yml`
  _Depends:_ 7.2, 8.1
  _Requirements:_ 11.3

---

## 9. (P) ドキュメント同期

_Boundary:_ `patterns/README.md`, `docs/README.md`
_Depends:_ 2, 6
_Requirements:_ 13.1, 13.2

- [ ] 9.1 `patterns/README.md` の索引へ hitl レーンを追加し(one-README 不変条件: 契約の再宣言はしない、参照のみ)、必要に応じ `docs/README.md` のガイド一覧から HITL 実装への参照を張る。
  _Boundary:_ `patterns/README.md`, `docs/README.md`
  _Depends:_ 2.2, 6.2
  _Requirements:_ 13.1, 13.2

---

## 完了ゲート(全タスク後)

- `mise run patterns:check`(lint / format / typecheck / test)緑 — hitl レーン含む。
- `mise run patterns:audit` 緑(hitl lockfile 含む)。
- R12.2 二層とも通過: 第1層 pre-commit `forbid-hardcoded-model-ids` + 第2層
  `tests/unit/test_no_hardcoded_model_ids.py`(T7.3 で patterns/*/src 走査に拡張済み)。
- カバレッジ `fail_under = 98`(hitl レーン)。
- 013(セキュリティ強化)が本レーンの上に積める状態 — `store.py` / `app.py` の
  拡張点(plan.md の「013 が拡張」注記)を壊していない。
