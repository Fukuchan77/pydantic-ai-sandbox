# 相互取り込み backlog（pydantic-ai-sandbox）

Agentic AI 系 5 リポジトリを横断で突き合わせた検証の、本 repo 向け抜粋。
**根拠・実測値・全 16 項目の本文は `vaz-agentic-ai-next/docs/cross-repo-adoption-review.md` が正本**。
本文書は重複させず、項目 ID（X-n）で参照する。

- 検証日: 2026-09-06
- 兄弟 repo: `beeai-agentic-ai-sandbox` / `fastapi-pydantic-ai-agent` / `vaz-ai-next` / `vaz-agentic-ai-next`

---

## 1. この repo が出す資産

| 資産 | 場所 | 何が独自か |
|---|---|---|
| フレームワーク非依存の型契約 | `patterns/contracts/src/patterns_contracts/`（依存は `pydantic>=2` のみ） | 同じ 6 パターンを 3 フレームワークで実装しても**契約は 1 つ**という構造。5 repo 中ここだけ |
| 正本 README ↔ ランタイムの AST ドリフト検証 | `patterns/contracts/tests/unit/test_contract_drift.py`（287 行） | 11 個の README の `## パターン契約` フェンスを AST パースし、クラス集合・フィールド集合・`Literal` 語彙を runtime introspection と照合。**doc→code 方向のドリフト検知は 5 repo 中ここだけ** |
| 空振り検知プラグイン | `patterns/contracts/src/patterns_contracts/pytest_live_guard.py`（62 行） | `EXPECT_LIVE_TESTS=n` 未満を hard fail、未設定時は完全に不活性。**パッケージ化済みで 1 行の再エクスポートで各レーンに配れる**（他 repo は内製 or shell） |
| 評価グレーダ契約 | `patterns/contracts/src/patterns_contracts/eval_graders.py`（93 行） | `Rating` に `"unknown"`（証拠不足を数値化しない）／outcome・behavior 軸分離／`Judge[SubjectT]` Protocol による DI シーム＝**決定論フェイク judge でネットワーク不要のユニットテストが書ける** |
| ツール設計の実装 | `patterns/frameworks/pydantic-ai/src/patterns_pydantic_ai/tool_design.py`（215 行） | `_DEFAULT_LIMIT=5` / `_MAX_LIMIT=25` / `_DETAIL_NOTE_CHARS=80`、最終ページで `next_offset=None`、`_coerce_format()` の寛容パース。**規約文書だけの repo に対して実物**（X-6） |
| HITL の履歴封鎖 | `patterns/hitl/src/patterns_hitl/app.py:92,157` | リクエストモデルが `extra="forbid"` で `message_history` フィールドを持たない ＝ クライアントは履歴を注入できず、サーバ側 `record.history` が正（spec 013 R4、CVE-2026-25580 の経路を構造的に封鎖）。consume-once ステートマシン付き |
| Agentic AI Top 10 対応表 | `patterns/SECURITY-NOTES.md` | **Agentic AI Top 10 (2025-12)** をレイヤ別に。CVE floor 表 ＋ no-fix advisory ランブック（R8.2: 日付付きレビュー期限と追跡参照が無い抑止を禁止） |
| フレームワーク比較 | `patterns/deep-research/COMPARISON.md` | LangGraph / CrewAI / MS Agent Framework / LlamaIndex / BeeAI / Langflow / Dify ＋ 多エージェントのトークンコスト |
| CI 戦略の失敗記録 | `specs/ci-strategy-review/retrospective.md` | live-Ollama CI の連続失敗（mise 404 → litellm 600s → anyio → httpx → OOM → job budget）の事後分析と P1-P5 是正 |

## 2. この repo が取り込む項目

| ID | 内容 | 出所 | 工数 | 受け入れ条件 |
|---|---|---|---|---|
| **X-1** | Actions の SHA 固定を全体へ（現状 **5/31**。`jdx/mise-action` のみ固定＝404 事件への対処で、他は全てタグ） | `fastapi-pydantic-ai-agent/tests/unit/test_ci_workflows.py`（224 行、`_FULL_SHA_PIN_RE` で 40 桁検証） | S | 6 ワークフロー全ての `uses:` が SHA。既存の `test_ollama_ci_workflows.py` / `test_watsonx_ci_workflow.py` と同じ流儀で repo ガード化し、「走査ファイル数 > 0」アサートを含めること |
| **X-4** | エージェント契約ファイルの追跡下配置。`.gitignore:222-228` が `CLAUDE.md` と `.sdd/` を除外しているため、**クローン直後のツリーに契約が存在しない** | 解法の前例は `vaz-agentic-ai-next`（`.sdd/` は ignore のまま憲章だけ `specs/memory/constitution.md` へ移した） | S | **規約のテスト化という既存の設計判断は維持する**。テストが表現できない "なぜ"（Principle III 無ベンダリング / Principle V 単一ゲート / 8 レーン分割の理由）だけを載せた最小の `AGENTS.md` を追跡下に置く |
| **X-8** | eval の**運用**（契約はあるが回帰比較の仕組みが無い） | `vaz-ai-next/packages/evals/src/pr-gate.ts` — ベースライン差分、over-under-trigger balance、case あたりトークン・所要時間、20 件未満は `reportOnly` | M | ベースラインの運搬手段（Actions cache 等）を決める。実モデル課金を伴うため opt-in ラベル方式を踏襲 |
| **X-9** | HITL の防御を 2 方向で補強 | `vaz-ai-next` — (a) 承認ゲートと受信者 allow-list の**独立 2 ゲート**（どちらも他方の代替にならない）、(b) sticky taint（外部由来コンテンツ注入後は run 終端まで latch し、デリミタがコンテキストから消えても承認が緩まない） | M | **ゲートを増やす方向ではなく、既存ゲートを迂回不能にする方向**であること（承認ダイアログを増やすと読まずに承認される）。`store.py` の TTL/永続化スコープ外という判断は `vaz-ai-next` の durable engine 設計を参照先に持つ |
| **X-10** | SSE ライフサイクルの 3 罠を `patterns/sse` レーンに記録・対処 | `fastapi-pydantic-ai-agent`: (1) `Agent.iter()` の anyio cancel scope はタスク跨ぎ不可 → 単一の永続駆動タスク＋`asyncio.Queue`（`fastapi-pydantic-ai-agent/app/api/v1/_stream.py:237-304`）、(2) ハートビートは `asyncio.wait()`（`wait_for()` は進行中イベントをキャンセル、`fastapi-pydantic-ai-agent/app/api/v1/agent.py:159,175`）、(3) `str.splitlines()` は U+2028/2029 を行境界扱いする → 実 SSE 終端子のみで分割（`fastapi-pydantic-ai-agent/app/patterns/sse.py:6,103`） | S | 3 点それぞれに回帰テスト。`patterns/sse` は同じ 5 イベント判別共用体を持つが、この 3 点の記録が無い |
| X-2 | ネットワーク遮断の**適用範囲拡大** | 自 repo の `patterns/deep-research/tests/unit/conftest.py`（`connect` ＋ `connect_ex` ＋ `getaddrinfo`）が最も厳格。他レーンは `ALLOW_MODEL_REQUESTS=False` のみ | S | 全レーンで同じ強度に揃える。socket 遮断が空振りでないことを証明するテスト（`test_smoke.py` の既存パターン）を各レーンに |
| X-6 | ツール設計規約の記述を補強 | `fastapi-pydantic-ai-agent/docs/tool-design-conventions.md` の「寛容なパース」節の**具体的な許容範囲リスト**（大文字小文字・前後空白・数値文字列・単一要素とリストの相互） | S | `docs/tool-design.md` に追記。実装（`tool_design.py`）との整合を確認 |
| X-6b | 「1 エージェント ≤ 20 ツール」の機械チェック（`tool-count-check`） | どの repo も未実装。原則のみ `vaz-agentic-ai-next/specs/memory/constitution.md` | S | 超過時は subagent 分割か Tool RAG。上限の引き上げは選択肢にしない |
| X-12 | セキュリティ抑止方針の階段を明示 | `beeai-agentic-ai-sandbox/SECURITY-NOTES.md`（`--ignore-vuln` を使わない最厳格）と自 repo（期限付き抑止）と `fastapi-pydantic-ai-agent`（理由付き抑止）の 3 段 | S | 本 repo がどの段を採るかを `patterns/SECURITY-NOTES.md` に明記（現在は暗黙） |

## 3. この repo 固有の注意

- **`.gitignore` の `CLAUDE.md` 除外は設計判断であり、単純に外さない**（X-4）。
  「強制可能な規約はテストへ実体化する」という判断は優れており、
  `test_ci_usage_policy.py` / `test_no_hardcoded_model_ids.py` / `test_security_workflow_lanes.py` /
  `test_contract_drift.py` がその成果。追加するのは**テストが伝えられない部分だけ**。
- **8 レーンの独立性を壊さない**: `beeai-framework` が `<3.14` を要求するため単一 uv workspace で
  解決できない、という記録（`specs/005-cross-platform/research.md` R-3）が分割の根拠。
  取り込み時に共通化のためレーンを統合しない。
- **既存のラベルドリフト**: `.github/workflows/patterns-ci.yml` のフレームワークレーン matrix と contracts ジョブの
  ステップ名がどちらも "coverage floor 85" と書いているが、3 フレームワークレーンの
  `pyproject.toml` は `fail_under = 98`（85 は `patterns/contracts` のみ）。
  ステップ名が陳腐化しているだけでゲート自体は正しい。X-1 で CI を触る際に直す。
  同様に `.pre-commit-config.yaml` のヘッダと `pyright` フックの名前が "py3.14" だが
  ルートの pyright 設定は 3.13 を対象にしている。
- **Dependabot の空白は文書化済み**: `rag` / `sse` / `deep-research` レーンは
  `dependabot.yml` の `directories` に無く、日次 pip-audit で覆っている。
  この「覆えていない範囲を宣言する」書き方は X-12 で他 repo へ出す資産でもある。
