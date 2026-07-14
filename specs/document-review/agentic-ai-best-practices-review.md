# レビュー: Agentic AI 学習リポジトリの3観点ベストプラクティス準拠評価

対象: 本リポジトリ全体（メインアプリ `src/pydantic_ai_sandbox/`、`patterns/` 全レーン、
`docs/`、正本ドキュメント群 `TOOL-DESIGN-NOTES.md` / `SECURITY-NOTES.md` / `EVAL-GRADERS.md`）

- **検証日**: 2026-07-14
- **対象コミット**: `006b893`（`claude/agentic-ai-pydantic-review-l26hyx` 分岐点）
- **レビュー観点**:
  1. Anthropic 技術ブログのベストプラクティスに従っているか
  2. Pydantic AI のベストプラクティスに従っているか
  3. IBM の定義する AI Agents / Agentic AI の考え方を踏襲できているか
- **検証方法**: リポジトリの実コード・テスト・ドキュメントを下記の公式一次情報と照合。
  Pydantic AI の API 仕様は本リポジトリの lock 版 **pydantic-ai-slim 2.3.0** の
  インストール済みソース（`.venv/lib/python3.13/site-packages/pydantic_ai/`）と直接照合した。
- **結論**: **3観点いずれも高水準で準拠**。指摘は「未準拠」ではなく、
  (a) 全3レーンに共通する**予算計上の終了経路間不整合**（正確性・要修正）、
  (b) IBM 粒度区分の**タクソノミー表の分類が2箇所で定義と緊張関係**にある点（概念・要再構成）、
  (c) Pydantic AI 公式イディオムからの**文書化されていない逸脱2件**（イディオム・要明文化または対比実装）
  の3系統に集約される。詳細は §D 指摘一覧、対応は §E リファクタリング計画を参照。

---

## 出典（公式一次情報）

本レビューの根拠として以下を参照した。本文中では出典 ID（`[A1]` 等）で引用する。
URL は 2026-07-14 時点で Web 検索により到達可能であることを確認済み。

### Anthropic 技術ブログ

| ID | タイトル | URL |
|---|---|---|
| [A1] | Building Effective AI Agents | https://www.anthropic.com/engineering/building-effective-agents |
| [A2] | Writing effective tools for AI agents — using AI agents | https://www.anthropic.com/engineering/writing-tools-for-agents |
| [A3] | Effective context engineering for AI agents | https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents |
| [A4] | How we built our multi-agent research system | https://www.anthropic.com/engineering/multi-agent-research-system |
| [A5] | Demystifying evals for AI agents | https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents |

### Pydantic AI 公式ドキュメント / ソース

| ID | タイトル | URL / 照合先 |
|---|---|---|
| [P1] | Agents（エージェントの再利用設計・実行時モデル上書き） | https://ai.pydantic.dev/agents/ |
| [P2] | Deferred Tools（HITL 承認: `ApprovalRequired` / `DeferredToolRequests` / `ToolApproved` / `ToolDenied`） | https://pydantic.dev/docs/ai/tools-toolsets/deferred-tools/ |
| [P3] | Testing（`TestModel` / `FunctionModel` によるユニットテスト） | https://ai.pydantic.dev/testing/ |
| [P4] | Output（`output_type` / `NativeOutput` / output validator / `ModelRetry`） | https://ai.pydantic.dev/output/ |
| [P5] | Models（`FallbackModel`） | https://ai.pydantic.dev/models/ |
| [P6] | Pydantic Evals（公式評価パッケージ） | https://ai.pydantic.dev/evals/ |
| [P7] | `UsageLimits` 実装（lock 版ソース直接照合） | pydantic-ai-slim 2.3.0 `usage.py:247-265` |

> [P1] の該当記述（公式ドキュメント逐語）: *"Agents are designed for reuse, like FastAPI Apps"* /
> *"Agents are intended to be instantiated once (frequently as module globals) and reused
> throughout your application, similar to a small FastAPI app or an APIRouter."*
>
> [P7] の該当記述（2.3.0 ソース逐語）: *"The request count is tracked by pydantic_ai, and the
> request limit is checked **before** each request to the model."*（`usage.py:250` — 事前判定）。
> `UsageLimits` は `request_limit` / `tool_calls_limit` / `input_tokens_limit` /
> `output_tokens_limit` / `total_tokens_limit` / `count_tokens_before_request` を提供する。
> また `agent.run(..., model=...)` の実行時モデル上書きは `agent/abstract.py` の
> `run` オーバーロード群（`model: models.Model | KnownModelName | str | None`）で確認。

### IBM Think（定義の正本）

| ID | タイトル | URL |
|---|---|---|
| [I1] | What Are AI Agents? | https://www.ibm.com/think/topics/ai-agents |
| [I2] | What is Agentic AI? | https://www.ibm.com/think/topics/agentic-ai |
| [I3] | Agentic AI vs. Generative AI | https://www.ibm.com/think/topics/agentic-ai-vs-generative-ai |
| [I4] | What are Components of AI Agents? | https://www.ibm.com/think/topics/components-of-ai-agents |
| [I5] | What Is AI Agent Memory? | https://www.ibm.com/think/topics/ai-agent-memory |

> 中核定義（検索スニペットで確認した逐語）:
> - [I1] *"An artificial intelligence (AI) agent refers to a system or program that is capable of
>   autonomously performing tasks on behalf of a user or another system."*
> - [I2] *"Agentic AI describes AI systems that are designed to autonomously make decisions and act,
>   with the ability to pursue complex goals with limited supervision."*
> - [I3] *"Agentic AI is the framework; AI agents are the building blocks within the framework."*
>   （Agentic AI = 枠組み、AI Agent = その構成要素）
> - [I4][I5] AI エージェントの構成モジュール: 知覚・推論・計画・行動・**メモリ（短期/長期）**・
>   通信・学習。メモリは短期（セッション文脈）と長期（知識ベース・ベクトル埋め込み・履歴）に分かれる。

---

## A. 観点1 — Anthropic 技術ブログのベストプラクティス

### A-1. 準拠している点

| 原則（出典） | 本リポジトリの実装根拠 | 判定 |
|---|---|---|
| 「最も成功した実装は複雑なフレームワークではなく **simple, composable patterns** で構築されていた」[A1] | `patterns/README.md:23-27` が当該文を逐語引用し、6パターン全てを各フレームワークの最小プリミティブ（`Agent` + `asyncio.gather` + 型付き出力）で実装。重厚な抽象レイヤに依存しない | ✅ |
| **workflow と agent の区別**（コードが制御フローを定めるのが workflow、LLM が自律的に process を方向づけるのが agent）[A1] | prompt-chaining / routing / parallelization / orchestrator-workers / evaluator-optimizer を「ワークフロー」、autonomous-agent を「ツールループ＋ガードレール」として分離実装（`patterns/frameworks/*/src/`） | ✅（ただし IBM 軸との整合は §C-2 参照） |
| **エージェントにはガードレールと人間のチェックポイント**（コスト・エラー複利化への対処）[A1] | `patterns/frameworks/pydantic-ai/src/patterns_pydantic_ai/autonomous_agent.py:100-228` の4ガードレール: `max_iterations`（反復上限）/ `allowed_tools`（最小権限 allow-list）/ `approval_hook`（人間承認）/ `budget`（トークン予算）。閉じた `stop_reason` 語彙で停止理由を監査可能化し、OWASP Agentic AI Top 10 へのマッピング（`patterns/SECURITY-NOTES.md`）まで整備 | ✅（計上不整合1件 → §D-1） |
| **ツール設計**: namespacing / token 効率（pagination・truncation・妥当な既定値）/ `response_format`（concise/detailed）/ 実行前入力検証 [A2] | `patterns/TOOL-DESIGN-NOTES.md` が原則を規約化し準拠状況表で管理。実演 `tool_design.py`: `directory_` プレフィックス、既定 `limit=5`/上限25クランプ、`next_offset` カーソル、80字 truncation、`concise`/`detailed` 切替 | ✅ |
| **コンテキストエンジニアリング**: compaction / structured note-taking / sub-agent 隔離、「desired outcome の確率を最大化する最小の高信号トークン集合」[A3] | `docs/context-engineering.md` が3技法を deep-research レーンへ実装。reflect ループの「全結果毎ターン再注入」アンチパターンを自ら特定し `digest_fn` DI シーム + `compact_digest`（dedup / cap / truncation）で解消。sub-researcher → lead のハンドオフを「凝縮サマリ + ノート」に限定（生トランスクリプト非伝播） | ✅（上限トリガ再初期化は未実装・明記済み → §D-7） |
| **マルチエージェントリサーチ**: lead が計画し並列 sub-agent が独立コンテキストで探索、引用グラウンディング [A4] | `patterns/deep-research/`: lead（brief→plan、`out_of_scope` による重複防止）→ `max_researchers` cap の並列 researcher（`asyncio.gather`）→ 有界 search→read→reflect ループ → dangling/empty citation の loud-fail（`compression.py`）→ report 合成 | ✅ |
| **エージェント評価**: 実タスク由来の評価を早期に、outcome だけでなく振る舞いも [A5] | `patterns/EVAL-GRADERS.md` + `patterns_contracts/eval_graders.py`: outcome / behavior 分離の多軸採点 `GradeReport`、離散 Rating（1–5 + `unknown`）、空 rationale の構築拒否、独立 judge 注入シームで self-eval バイアス回避 | ✅ |

### A-2. 改善候補

1. **予算計上の終了経路間不整合**（→ §D-1、全3レーン共通）。[A1] が強調するエージェントの
   コスト可視性の観点で、`completed` 終了時だけ最終ターンのトークンが `total_budget_spent` から
   漏れるのは監査証跡の欠落である。
2. **budget ガードが事後判定**である点が docstring に明記されていない（→ §D-4）。
   Pydantic AI ネイティブの `UsageLimits` は `request_limit` を**事前判定**する [P7] ため、
   セマンティクス差は学習上むしろ好教材であり、明文化する価値がある。
3. **compaction の中核（トークン上限トリガの文脈再初期化）が未実装**（→ §D-7）。
   `docs/context-engineering.md` の「拡張点」に明記されており誠実だが、[A3] の compaction の
   本丸はここであり、既存の token-budget seam への接続が次の自然な一歩。

---

## B. 観点2 — Pydantic AI のベストプラクティス

### B-1. 準拠している点

| 公式イディオム（出典） | 本リポジトリの実装根拠 | 判定 |
|---|---|---|
| 構造化出力は `output_type`、モデル能力に応じた `NativeOutput` [P4] | `src/pydantic_ai_sandbox/agents/chat_agent.py:139-143`: モデルプロファイルの `supports_json_schema_output` を見て `NativeOutput(ChatResponse)` を条件付きラップ。`TestModel`/`FunctionModel` が `NativeOutput` で `UserError` になる v2 仕様を正確に回避 | ✅ |
| オフラインテストは `TestModel` / `FunctionModel` で実 LLM 呼び出しを排除 [P3] | 全レーンで採用。autouse `block_network` フィクスチャ + 決定論フェイク（`turn_sequenced_model` / `verdict_sequenced_model` 等）でネットワーク I/O ゼロのユニットレーンを維持 | ✅ |
| HITL は deferred tools 公式機構（`ApprovalRequired` → `DeferredToolRequests` → `ToolApproved`/`ToolDenied`、`requires_approval=True`）[P2] | `patterns/hitl/src/patterns_hitl/agent.py:133-160`: `output_type=[SupportOutput, DeferredToolRequests]`、静的 `Tool(requires_approval=True)`、動的 `ctx.tool_call_approved` + `ApprovalRequired` の3形態を実演。`output_validator` + `ModelRetry` でポリシー強制まで上乗せ | ✅ |
| メインアプリでの Agent 再利用（モジュール/プロセス単位で1回構築）[P1] | `src/pydantic_ai_sandbox/api/deps.py`: `get_chat_agent` がプロセス全体のシングルトンを返し、テストは `agent.override(model=...)` で差し替え | ✅（ただしパターンレーンは逸脱 → §D-3） |
| プロバイダ切替・фallback [P5] | `FallbackModel` を env 駆動で構成（`llm/fallback.py`、`FALLBACK_ORDER`）。`pydantic-settings` で起動時 fail-fast 検証、モデル ID 非ハードコードを pre-commit フックで強制 | ✅ |
| 可観測性は Logfire / OTel 計装 | `instrument_model`（V2 API）+ `logfire.instrument_pydantic_ai()` で `gen_ai.*` スパン。`Agent(instrument=True)` が v2 で `TypeError` になる点も把握済み（`patterns/hitl/agent.py:8-11`） | ✅ |

### B-2. 改善候補（イディオム逸脱）

1. **パターンレーンでの呼び出し毎 Agent 構築**（→ §D-3）。[P1] は「Agent は FastAPI アプリ同様、
   1回構築してアプリ全体で再利用する」ことを明示する。`orchestrator_workers.py:51-58, 94-99`・
   `evaluator_optimizer.py:63-80`・`researcher.py`・`orchestrator.py:74-88` は関数呼び出しの度に
   `Agent` を構築している。モデル DI シームが動機だが、`agent.run(..., model=...)` の実行時
   上書き（[P7] 照合先と同じ `agent/abstract.py` で確認）で同じシームをモジュールレベル Agent の
   まま実現できる。
2. **`UsageLimits` を使わない手動ツールループ**（→ §D-4）。`autonomous_agent.py` は
   `Model.request` 直叩きで `max_iterations`/`budget` を自前実装している。docstring の理由
   （3レーンでガードレールを同型に所有する）は正当だが、「Pydantic AI のベストプラクティス学習」
   という目的に対しては、`Agent` + `@agent.tool` + `UsageLimits(request_limit=...,
   total_tokens_limit=...)` [P7] のイディオマティック対比実装が欠けている。
3. **`pydantic-evals` との関係が未記録**（→ §D-6）。`GradeReport`/`Judge` は自前契約だが、
   エコシステムには同目的の公式パッケージ pydantic-evals（`Dataset`/`Evaluator`/`LLMJudge`）[P6]
   が存在する。`EVAL-GRADERS.md` の出典欄（Anthropic/Google/AWS/IBM を列挙）に比較根拠として
   欠けており、採用しない判断の ADR 化が望ましい。
4. **`/chat` が単発ターンのみ**（→ §D-5）。`api/routes/chat.py` は `message_history` を扱わない。
   MVP スコープとして明記済みだが、HITL レーンの `SessionStore`（`store.py`）で履歴持ち回りを
   既に実装しているため、本線への還流が自然な次ステップ。

---

## C. 観点3 — IBM の AI Agents / Agentic AI の考え方

### C-1. 踏襲できている点

| IBM の考え方（出典） | 本リポジトリの実装根拠 | 判定 |
|---|---|---|
| AI Agent = 構成要素、Agentic AI = それらを束ねる枠組み [I3] | `patterns/README.md:7-21` の二軸タクソノミー（縦軸 Anthropic 分類 × 横軸 IBM 粒度）として明文化。粒度区分をリポジトリ構造（単一エージェント = ルートアプリ、マルチエージェント = deep-research）に対応づけ | ✅（分類2箇所に論点 → §C-2） |
| Agentic AI は「限定的な監督下で複雑な目標を追求」[I2] | deep-research レーン: lead の動的計画 → 並列 sub-researcher → 統合という限定監督下のゴール追求を、fan-out cap・反復上限・引用検証のガバナンス付きで実装 | ✅ |
| エージェント構成モジュール: 知覚・推論・計画・行動・メモリ・学習 [I4] | 知覚（検索ツール/`SearchProvider`）、推論・計画（planner / brief→plan）、行動（ツールループ）、リフレクション（evaluator-optimizer、reflect ループ）、短期メモリ（`message_history` 持ち回り、`ResearchNote`）を網羅 | ✅（長期メモリのみ未着手 → §C-3） |
| ガバナンス・責任ある運用（IBM が一貫して強調） | HITL 承認フロー + 監査ログ（`patterns_hitl/audit.py`）、OWASP Agentic AI Top 10 マッピング、CVE runbook（`SECURITY-NOTES.md`）、watsonx プロバイダ統合と watsonx agentic eval の参照（`EVAL-GRADERS.md`） | ✅ |

### C-2. 論点1: タクソノミー表の「Agentic AI」分類が IBM 定義に対して過大

`patterns/README.md:13-21` は6パターン全行を「Agentic AI」に分類しているが、
[I2] の Agentic AI は「**自律的に意思決定し行動**し、限定的な監督下で複雑な目標を追求する」
システムであり、決定論的なワークフロー自動化とは対比される概念である。

- **Prompt Chaining / Parallelization / Routing**: コード（ゲート・固定順序・固定 fan-out）が
  制御フローを決め、LLM は各ステップの変換器にすぎない。Anthropic 自身もこれらを
  "workflows"（"agents" と対比）と呼ぶ [A1]。IBM 定義では「LLM を構成要素とする
  ワークフロー自動化」に相当し、「Agentic AI（複数エージェントのオーケストレーション）」と
  呼ぶのは軸が潰れている。
- **Autonomous Agent**: 表は「Agentic AI」に置くが、実体（`autonomous_agent.py`）は
  **単一エージェントのツールループ**である。[I3] の粒度区分（AI Agent = 構成要素 /
  Agentic AI = マルチエージェントの枠組み）では、これは典型的な「AI Agent」側であり、
  同表が「単一エージェント = AI Agent」と定義していることと自己矛盾気味である。
  マルチエージェント性の正当な代表は deep-research レーンである。

**提案**（→ §D-2）: 表に第3の軸「**制御フローの決定者**（コード = workflow / LLM = agentic）」を
追加し、prompt-chaining・parallelization・routing を「ワークフロー（AI Agent の合成）」、
autonomous-agent を「AI Agent（単一・ツールループ）」、orchestrator-workers・deep-research を
「Agentic AI（LLM が分解・協調を決定）」へ再配置する。これで [A1] と [I2][I3] の両定義に
同時整合する。

### C-3. 論点2: 長期メモリの不在

[I4][I5] は AI エージェントのメモリを短期（セッション文脈）と長期（知識ベース・ベクトル
埋め込み・履歴）に区分する。本リポジトリは短期メモリ（HITL の `SessionStore`、deep-research の
`ResearchNote`）を備えるが、**セッション横断の長期メモリ**（notebook 永続化・checkpoint/resume）は
`docs/context-engineering.md:150` で「将来イテレーション」とされたまま具体計画がない。
RAG レーン（`patterns/rag/`）が長期メモリの器（ベクトルインデックス）を既に持つため、
「エージェントが自分のノートを RAG へ書き戻し後続セッションで検索する」構成が最小の実装径路になる
（→ §D-8）。

---

## D. 指摘一覧（重要度順）

| # | 重要度 | 指摘 | 根拠出典 | 場所 |
|---|---|---|---|---|
| D-1 | **高（正確性）** | autonomous-agent の `completed` 終了時、最終ターンのトークンが `total_budget_spent` に未計上。`disallowed_tool`/`denied` は `total + tokens` を返すため終了経路間で計上規則が揺れる。最終応答ターンは `steps` にも残らない。**全3レーン共通**（pydantic-ai `autonomous_agent.py:163-168` / beeai `:139-144` / llamaindex `:191-196`） | [A1]（コスト可視性・ガードレール） | `patterns/frameworks/*/src/*/autonomous_agent.py` |
| D-2 | **高（概念）** | Prompt Chaining / Parallelization / Routing の「Agentic AI」分類が IBM 定義に対して過大。Autonomous Agent（単一エージェント）の「Agentic AI」分類が同表の「単一エージェント = AI Agent」と自己矛盾 | [I2][I3][A1] | `patterns/README.md:13-21` |
| D-3 | 中（イディオム） | パターンレーンが呼び出し毎に `Agent` を構築。公式は「1回構築・再利用（module globals）」を明示。`agent.run(model=...)` で DI シームは維持可能 | [P1] | `orchestrator_workers.py` / `evaluator_optimizer.py` / `researcher.py` / `orchestrator.py` ほか |
| D-4 | 中（教材価値） | `UsageLimits`（事前判定の公式ガードレール）を使うイディオマティック版 autonomous agent が不在。手動ループの事後判定セマンティクスも未明文化 | [P7][P1] | `autonomous_agent.py` |
| D-5 | 低 | `/chat` が単発ターンのみ（`message_history` 未対応）。IBM の短期メモリ要件の本線適用が HITL レーン止まり | [I4][I5] | `src/pydantic_ai_sandbox/api/routes/chat.py` |
| D-6 | 低 | `pydantic-evals` 不採用判断が ADR 化されていない | [P6] | `patterns/EVAL-GRADERS.md` |
| D-7 | 低 | compaction の上限トリガ文脈再初期化が未実装（拡張点として明記済み） | [A3] | `docs/context-engineering.md:113-122` |
| D-8 | 低 | 長期メモリ（セッション横断永続化）が将来項目のまま無計画 | [I4][I5] | `docs/context-engineering.md:150` |

---

## E. リファクタリング計画（優先度順）

各項は独立に着地可能。R1 と R2 以外は既存の凍結契約（`patterns_contracts`）・ドリフトテスト・
他レーンの byte 互換テストを壊さないことを受け入れ条件に含める。工数は S（半日以下）/
M（1–2日）/ L（3日以上）の目安。

### P0 — R1: 予算計上の終了経路統一（D-1、工数 S、3レーン同型修正）

- **変更**: 各レーンの `run_autonomous_agent` で、`completed` 分岐の戻り値を
  `total_budget_spent=total + tokens` に統一する（最終応答ターンの消費を計上）。
  併せて docstring に「budget 判定はツール実行後の事後判定であり、最大1ターン分の
  超過があり得る」ことを明記する（[P7] の `UsageLimits` 事前判定との対比として）。
- **対象**: `patterns/frameworks/pydantic-ai/src/patterns_pydantic_ai/autonomous_agent.py`、
  `patterns/frameworks/beeai/src/patterns_beeai/autonomous_agent.py`、
  `patterns/frameworks/llamaindex/src/patterns_llamaindex/autonomous_agent.py`
- **受け入れ条件**:
  1. 5つの `stop_reason` すべてで「`total_budget_spent` = 全モデルターンのトークン総和」を
     検証するユニットテストを3レーンに追加（既存 `turn_sequenced_model` 系フェイクを再利用）。
  2. `AgentRunResult` 契約（フィールド・`stop_reason` 語彙）は不変 — 契約ドリフトテスト green。
  3. 3レーンの `mise run patterns:check` green。
- **リスク**: 既存テストが `completed` 時の旧値を固定している場合はテスト側を更新する
  （契約は変わらないため正当な期待値修正）。

### P1 — R2: タクソノミー表の三軸再構成（D-2、工数 S、ドキュメントのみ）

- **変更**: `patterns/README.md` の二軸表に「制御フローの決定者」列を追加し再分類する:
  | パターン | 制御フロー | IBM 粒度 |
  |---|---|---|
  | prompt-chaining / routing / parallelization | コード（workflow） | AI Agent の合成（ワークフロー自動化） |
  | evaluator-optimizer | コード（ループはコード、判定は LLM） | AI Agent の合成 |
  | orchestrator-workers | LLM が分解を決定（agentic） | Agentic AI への入口 |
  | autonomous-agent | LLM がツール選択を決定（agentic） | **AI Agent**（単一・ツールループ） |
  | deep-research | LLM が計画・協調を決定 | **Agentic AI**（Multi-Agent System の代表） |
  出典として [A1]（workflow/agent の区別）と [I2][I3]（粒度区分）を脚注に明記する。
- **受け入れ条件**: 契約・コード変更なし。README のみ。ドリフトテストの `_README_PATHS`
  対象パターン README は不変のため影響なし。
- **リスク**: なし（分類の解釈変更であり、既存パターン実装・spec 文書への遡及修正は不要。
  旧分類の経緯は本レビューが記録する）。

### P2 — R3: Agent 構築イディオムの整合（D-3、工数 M）

- **方針**: 2段階。(a) まず `TOOL-DESIGN-NOTES.md` と同型の「受容した非適用」節を
  `patterns/README.md` に追加し、「呼び出し毎構築は DI シームとテスト決定論のための意図的
  逸脱」であることを [P1] への参照付きで明文化する（工数 S、即着地可）。
  (b) 次いで pydantic-ai レーンのみ、モジュールレベル Agent + `agent.run(..., model=...)` の
  実行時上書きへ移行するリファクタリングを試行する（instrumentation は
  `instrument_model` 済みモデルを run 時に渡せば従来と等価）。
- **受け入れ条件**:
  1. (a) は文書のみ。(b) はプロンプト文字列・呼び出し順序が byte 互換
     （`test_researcher.py` 等の捕捉プロンプト完全一致テストが無変更で green）。
  2. レーンの `check` green、カバレッジゲート維持。
- **リスク**: (b) は `Agent` がモジュールグローバル化することでテスト間の状態共有が
  生じ得る（`override` の入れ子等）。テストが1つでも不安定化するなら (a) 止まりとし、
  逸脱の明文化をもって完了とする。

### P2 — R4: `UsageLimits` 対比実装の追加（D-4、工数 M）

- **変更**: pydantic-ai レーンに `autonomous_agent_idiomatic.py`（仮称）を新設し、
  `Agent` + `tools=[...]` + `UsageLimits(request_limit=max_iterations,
  total_tokens_limit=budget)` [P7] で同じ4ガードレール意味論を公式機構だけで組む。
  `UsageLimitExceeded` を `stop_reason` 語彙へ写像するアダプタで既存
  `AgentRunResult` 契約に載せ、手動ループ版との**事前判定/事後判定の差**を
  docstring と `docs/tool-design.md` に対比表で記録する。
- **受け入れ条件**:
  1. 既存 `autonomous_agent.py`・凍結契約・他レーンは無変更（新規ファイル追加のみ）。
  2. `TestModel`/`FunctionModel` による決定論テストで `request_limit` 発火・
     `total_tokens_limit` 発火・承認拒否の3経路を検証。
  3. 対比ドキュメント（手動ループ vs `UsageLimits`）が README から辿れる。
- **リスク**: 低。追加のみで既存面を触らない。

### P3 — R5: `/chat` の多ターン化（D-5、工数 M）

- **変更**: HITL レーンの `SessionStore` 設計を本線へ還流し、`ChatRequest` に
  `session_id`（任意）を追加、`agent.run(message_history=store.history(session_id))` で
  短期メモリを持ち回る。クライアント供給の `message_history` は受け付けない
  （HITL レーンが Spec 013 R4 で閉じた SSRF/履歴注入経路 — `SECURITY-NOTES.md` — を
  本線でも踏襲）。
- **受け入れ条件**: 既存の単発ターン API は後方互換（`session_id` 省略時は現挙動）。
  `TestModel` による履歴持ち回りのユニットテスト追加。ルートの `mise run check` green。
- **リスク**: 中。スキーマ拡張のため spec（新規または 001 の追補）を先行させる
  （本リポジトリの SDD パイプライン規約に従う）。

### P3 — R6: pydantic-evals 比較 ADR（D-6、工数 S、ドキュメントのみ）

- **変更**: `EVAL-GRADERS.md` の ADR 群に「pydantic-evals [P6] を採用せず自前
  `GradeReport` 契約とした理由（依存ゼロ契約・3レーン横断・ドリフトテスト一元化）と
  再検討条件（pydantic-evals が cross-framework 契約を提供した時点）」を追記する。
- **受け入れ条件**: 文書のみ。契約ドリフトテスト green。

### P4 — R7: compaction 上限トリガの実装（D-7、工数 L）

- **変更**: `docs/context-engineering.md:113-122` が既に設計した径路の実装:
  deep-research の fan-out に token-budget ガード（autonomous-agent の `_budget_spent` 同型の
  `ModelResponse.usage` 合算）を被せ、閾値近傍で `digest_fn` を `compact_digest` へ
  エスカレートする段階化。[A3] の「最も軽量・安全な compaction からの段階導入」に従う。
- **受け入れ条件**: 既定（未注入）挙動の byte 互換維持。閾値発火の決定論テスト。

### P4 — R8: 長期メモリの最小実装検討（D-8、工数 L、spec 先行）

- **変更**: `ResearchNote` の永続化（checkpoint/resume）を最小スコープで spec 化する。
  実装径路は RAG レーンの in-memory `VectorStoreIndex` を器にした
  「ノート書き戻し → 後続セッションで検索」構成（[I5] の長期メモリ = ベクトル埋め込み・
  履歴の定義に対応）。
- **受け入れ条件**: まず spec/research のみ（SDD パイプライン）。実装は別イテレーション。

### 依存関係と着地順

```
R1（P0・独立）─┐
R2（P1・独立）─┼─ 即着地可能（互いに依存なし）
R6（P3・文書）─┘
R3(a) → R3(b)（(a) の明文化が (b) 断念時のフォールバック）
R4 → R7（R4 の UsageLimits 知見が R7 の budget ガードの参照実装になる）
R5 → R8（本線セッション管理が長期メモリの前提になる）
```

---

## 付録: 検証ログ（抜粋）

- pydantic-ai-slim **2.3.0**（`uv sync` 後の `.venv`）にて確認:
  - `usage.py:247-265` — `UsageLimits` の定義とフィールド群、`request_limit` の事前判定コメント。
  - `agent/abstract.py` — `run()` オーバーロードの `model: Model | KnownModelName | str | None`
    パラメータ（実行時モデル上書き）。
- 予算計上不整合（D-1）の3レーン照合:
  - pydantic-ai レーン `autonomous_agent.py`: `completed` 163-168行（`total` のみ）、
    `disallowed_tool` 183-188行 / `denied` 198-203行（`total + tokens`）。
  - beeai レーン: 139-144行 / 160-165行 / 175-180行（同型）。
  - llamaindex レーン: 191-196行 / 210-215行 / 225-230行（同型）。
- Anthropic / IBM / Pydantic AI の各 URL は 2026-07-14 に Web 検索で到達性とタイトルを確認。
  `ai.pydantic.dev` は本セッションのネットワークポリシーで直接取得不可のため、[P1] の逐語は
  検索結果スニペット、[P7] はローカル lock 版ソースで裏取りした。
