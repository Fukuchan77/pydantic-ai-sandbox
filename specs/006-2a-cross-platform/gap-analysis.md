# 実装ギャップ分析 — 006-2a-cross-platform

> `/sdd-validate-gap` 生成。承認済み要件（spec.md R1–R13）と既存コードベース
> （005-cross-platform 完了状態）の差分を design 前に整理する。**意思決定では
> なく情報と選択肢**を提示する。

## 分析サマリ

- **本質は Hybrid**: 005 のレーン足場（フェイク基盤・`configure_tracing`・テスト
  三層・mise/CI・pre-commit ガード）はそのまま**拡張**し、(a) 依存ゼロの
  `patterns/contracts/` パッケージ新設と (b) 4新パターン × 3レーン=12実装を
  **新規構築**する。スコープの大半は 005 の規律のクローン適用で、新規性は
  「契約パッケージ昇格」と「autonomous-agent のツールループ」の2点に集中する。
- **最大の技術リスクは autonomous-agent（R6/R7.2）**。3フレームワークとも
  ネイティブな agent ループ抽象（PydanticAI `Agent`+tools / BeeAI
  `ReActAgent`・`ToolCallingAgent` / LlamaIndex `FunctionAgent`）を持つが、
  契約4ガードレール（max_iterations / allowed_tools / approval_hook / budget）を
  **同一シグネチャで横並びに強制**でき、かつ既存の単発フェイクを「ターン列を返す
  台本フェイク」へ拡張する方式が、3レーンで異なる。design で最優先に解く。
- **shared-contracts のクロス Python バージョン跨ぎは標準セマンティクスで成立**。
  `requires-python >=3.13` のパス依存パッケージは 3.14 レーンにも `>=3.13,<3.14`
  レーンにも install 可能。ただし uv.lock 再生成（全3レーン+契約パッケージ）・
  `mise patterns:setup` のループ拡張・CI の `--locked` 整合が付随作業として発生。
- **R2 の単一点ドリフトテストは既存テストの「置換」**。現行
  `tests/unit/test_patterns_contract_sync.py`（3レーン AST 相互比較）を破棄し、
  「README 正本 == `patterns/contracts/` パッケージ」の1点へ作り替える。読み取り
  方式（AST 解析 vs パッケージ import）とテスト設置場所が design 論点。
- **R10.4 / R12 は実質的に既に充足**。model-id guard の exclude は
  `^(tests/.*|src/.*/config\.py)$` で patterns/ を除外しておらず、CI paths は
  `patterns/**` を含む。**新規追加ではなく不変条件の維持**として扱う。

## 要件別ギャップ表

凡例: ✅ 既存で充足 / 🔧 既存を拡張 / 🆕 新規構築

| 要件 | 区分 | 根拠・既存資産 | 必要作業 |
|---|---|---|---|
| **R1** shared-contracts 昇格 | 🆕 | 現状は各レーン `src/patterns_<fw>/contracts.py` に約25行を意図的複製（[structure.md §8 原則1]） | `patterns/contracts/`（pydantic のみ・`requires-python >=3.13`・hatchling）新設。6パターン契約を集約。各レーン pyproject に `[tool.uv.sources]` パス依存追加、`contracts.py` 削除、import 差し替え |
| **R2** ドリフト単一点化 | 🔧（実質置換） | `tests/unit/test_patterns_contract_sync.py:38-77`（AST で3レーン相互比較 + Route 語彙文字列マッチ） | 同テストを破棄/作り替え。「README fenced block の正本 == パッケージ定義」の1点比較へ。読取方式と設置場所が論点（後述） |
| **R3** prompt-chaining | 🆕 | 既存実装なし。逐次連結の参考は routing の2段フロー | 契約 `ChainStep/GateOutcome/ChainResult` + `run_prompt_chain`。PydanticAI=複数 `agent.run` 直列 / LlamaIndex=`@step` 直列 / BeeAI=Workflow 逐次。ゲート不合格で早期終了・`final_output=None` |
| **R4** parallelization | 🆕 | fan-out 機構は orchestrator-workers が実証済み（PydanticAI/BeeAI=`asyncio.gather`、LlamaIndex=`send_event`/`collect_events`+順序復元 [orchestrator_workers.py:107-122]） | 契約 `ParallelResult/Branch` + `run_parallelization(variant: Literal["sectioning","voting"], n=3)`。fan-out は既存パターンを流用、変種分岐とブランチ順序の決定論復元が新規 |
| **R5** evaluator-optimizer | 🆕 | 既存実装なし | 契約 `OptimizationResult/Iteration` + `run_evaluator_optimizer(max_iterations=3)`。生成→評価ループ、`verdict: Literal["pass","revise"]`、`stop_reason: Literal["passed","max_iterations"]` |
| **R6** autonomous-agent | 🆕（高リスク） | 各レーン venv にネイティブ agent あり（pydantic_ai `agent`/`usage.py`/`toolsets`、beeai `agents/react`・`tool_calling`、llama_index `agent/workflow`・`react`） | 契約 `AgentRunResult/AgentStep` + 4ガードレール引数を同一シグネチャで公開。`stop_reason: Literal["completed","max_iterations","budget_exceeded","denied"]`。許可リスト違反拒否・承認フック・予算超過停止を全レーンで実装 |
| **R7** オフラインテスト | 🔧 | 既存フェイク3種（[model_fakes.py](../../patterns/frameworks/pydantic-ai/tests/support/model_fakes.py) `scripted_model` / [fake_chat_model.py](../../patterns/frameworks/beeai/tests/support/fake_chat_model.py) `ScriptedChatModel` / [fake_llm.py](../../patterns/frameworks/llamaindex/tests/support/fake_llm.py) `ScriptedLLM`）はいずれも**単発・スキーマ別分岐**型 | 「ツール呼出→環境FB→最終回答のターン列」を返すよう各フェイクを拡張（呼出回数/履歴で台本進行）。正常系+契約違反系（ゲート不合格/許可リスト違反/予算超過/承認拒否/max_iterations 打切）を各レーンに追加 |
| **R8** Ollama 結合 | 🔧 | 各レーン `tests/integration/test_ollama_e2e.py` + `RUN_INTEGRATION_PATTERNS=1` ゲート | 新4パターンの結合ケース追加。アサートは契約レベルのみ（branches=n / stop_reason 語彙内 等） |
| **R9** 可観測性 | 🔧 | `configure_tracing()` 3レーン実装済み（pydantic-ai=`instrument_model`、beeai=`traced()` 手動スパン、llamaindex=OpenInference）。`InMemorySpanExporter` 注入パターン確立 | 新4パターンにも適用し span≥1 を検証。末端 LLM スパン存在確認に留める（二重計上回避） |
| **R10** セキュリティ | 🔧 | [SECURITY-NOTES.md](../../patterns/SECURITY-NOTES.md) 存在、pip-audit は各レーン dev 依存済み。model-id guard exclude は patterns/ 非除外（[.pre-commit-config.yaml:74]） | SECURITY-NOTES に autonomous-agent 4ガードレール→OWASP Agentic AI マッピング追記。R10.4 は**不変条件維持**（patterns/contracts/ を除外しない）。R10.2 は契約パッケージにも pip-audit 必要か要確認（依存ゼロなので限定的） |
| **R11** README/索引 | 🔧 | [patterns/README.md:13-21] タクソノミー表（4パターンが「将来イテレーション」）、[routing/README.md] が必須4セクションの雛形 | 表の4行を「✅実装済み」へ更新+リンク。新4パターンの `patterns/<pattern>/README.md` を routing 形式で作成（差異比較含む） |
| **R12** CI | 🔧（実質充足） | [patterns-ci.yml] paths に `patterns/**` 含む、3レーンマトリクス。`patterns-integration-ollama.yml` 存在 | paths は既に契約パッケージを内包。`cache-dependency-glob` がパス依存変更を取りこぼす可能性のみ要確認。既存 ci/integration/security.yml は無変更（R12.3） |
| **R13** 開発体験 | 🔧 | mise `patterns:*` タスクは `patterns/frameworks/*/` をループ（[mise.toml:64-130]） | `patterns/contracts/` は glob 外 → setup/lint/typecheck/test に契約パッケージ手順を追加。`mise run check`（ルート）は patterns/ 除外で無変更グリーンを維持 |

## 統合上の課題

1. **契約パッケージのレーンへの配線（R1.4）**: `[tool.uv.sources]` の
   `patterns-contracts = { path = "../../contracts", editable = true }` 形式で各レーン
   pyproject に追加。`uv sync` がパス依存を editable install するため、`patterns:setup`
   のフレームワーク・ループとは別に契約パッケージ自身のセットアップ（lint/typecheck/
   ドリフトテスト）の置き場を決める必要がある。
2. **uv.lock の連鎖再生成（NFR-1）**: 3レーンすべての uv.lock がパス依存を含む形に
   更新され、契約パッケージにも lock が要る。CI は `uv sync --locked` なのでロック不整合は
   検出されるが、`cache-dependency-glob: …/uv.lock` だけでは契約パッケージ本体の変更で
   キャッシュが bust しない（実害は `--locked` が拾う／キャッシュ鮮度のみの問題）。
3. **autonomous-agent の決定論化（R7.2）**: 既存フェイクは「スキーマのプロパティ名で
   1回だけ分岐」する設計。ツールループは**同一フェイクが複数回呼ばれ、各回で異なる
   ターン（ツール呼出→観測→最終回答）を返す**必要があり、フェイクに呼出カウンタ/
   メッセージ履歴依存の台本進行を導入する拡張が要る。3フレームワークで agent ループの
   駆動方法（ネイティブ駆動か手動ループか）が異なる点が波及する。
4. **ガードレールの責務配置（R6.4-6.6 / R10.3）**: 4ガードレールをフレームワーク
   ネイティブ機能に委ねるか（例: PydanticAI `UsageLimits` で budget、toolset で
   allowed_tools）、レーンコードで一様に巻くか。同一契約シグネチャ保証のため、最低限
   レーンコード側で停止経路（`stop_reason`）を確定させる層が必要。
5. **ドリフトテストの読取面（R2.1-2.3）**: README の fenced ```python ブロックを正本と
   して、(a) AST 解析で両者比較（import 不要・現行 root テスト流儀の踏襲）か、
   (b) パッケージを import して Pydantic `model_fields` を intro省するか。後者は root
   venv（3.14）に契約パッケージ（>=3.13）の install が要る。

## 実装アプローチの選択肢

| アプローチ | 適合条件 | コスト | リスク |
|---|---|---|---|
| **A. Hybrid（推奨）**: 005 足場を拡張 + 契約パッケージと4パターンを新設 | spec のクリア決定（shared-contracts 昇格・単一契約+variant・契約レベル4ガードレール）に最も整合 | 中 | 統合（パス依存配線・lock 連鎖・CI キャッシュ） |
| **B. 全面新規**: パターン横断の共通ランタイム層を新たに導入 | 4パターンに強い共通骨格が見いだせる場合 | 高 | 005 の「最小プリミティブで組む」方針（[patterns/README.md] Anthropic 逐語引用）からの逸脱・重複 |
| **C. 純拡張**: 契約をレーン複製のまま 4パターン追加 | 昇格を見送る場合 | 低 | spec の R1/R2（昇格は確定済み clarification）と矛盾 — 不採用 |

design 論点として残る subdecision（A 前提）:

- **A1 契約パッケージ構造**: フラット単一 `contracts.py` か、パターン別サブモジュール
  （`contracts/routing.py` 等）か。6パターン分なら後者が責務純度高いが、ドリフト
  テストの走査対象が増える。
- **A2 ドリフトテスト方式・設置**: 上記課題5の (a) AST / (b) import。設置は root
  `tests/unit/` か `patterns/contracts/tests/` か。
- **A3 autonomous-agent ループ**: 各 fw ネイティブ agent 駆動か、chat プリミティブ上の
  手動一様ループか。フェイク台本化の容易さと型安全（pyright strict）で評価。

## plan フェーズで深掘りすべき研究項目

1. **autonomous-agent × 3フレームワークのループ実装と4ガードレール強制方式**
   （最優先）: PydanticAI `Agent`+`UsageLimits`+toolset、BeeAI `ReActAgent`/
   `ToolCallingAgent`/`RequirementAgent`、LlamaIndex `FunctionAgent`/`AgentWorkflow` の
   どれを使い、allowed_tools 拒否・approval_hook・budget 超過・max_iterations を
   どこで確定するか。台本フェイクのターン列駆動が3レーンで実現可能かを PoC で確認。
2. **parallelization の variant 表現と順序復元**: voting の多数決集約ロジック、
   sectioning の分割主体（プランナー有無）、LlamaIndex `collect_events` での
   ブランチ index 復元（orchestrator-workers の既存手法を流用可能か）。
3. **契約パッケージのパス依存とロック/CI 整合**: `editable` 要否、`uv sync --locked`
   とパス依存の相性、`cache-dependency-glob` への契約 lock 追加要否。
4. **ドリフトテストの正本パース戦略**: README fenced block の機械可読フォーマット
   （クラス名・フィールド名・Literal 値の抽出）と、6パターン分への一般化。
5. **evaluator-optimizer のフィードバック反映**: `revise` フィードバックを次反復
   入力へ織り込む際の各 fw のメッセージ/state 表現差。

## 次のステップ

ギャップ分析は完了。**Hybrid（アプローチ A）** を起点に、design では特に
autonomous-agent のループ実装（研究項目1）と契約パッケージ昇格の配線（同3）を
先行して解くことを推奨する。

- `/sdd-plan 006-2a-cross-platform` で技術プラン（plan.md / research.md）を作成
- 要件は承認済み（spec.json `approvals.requirements.approved=true`）のため `-y` は不要
