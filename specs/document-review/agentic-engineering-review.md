# Agentic AI 業務適用ベストプラクティス設計 — 8手法レビューとリファクタリング計画

対象: 本リポジトリ全体(メインアプリ `src/pydantic_ai_sandbox/`、`patterns/` 全レーン、
`docs/`、正本ドキュメント群)

- **検証日**: 2026-07-16
- **対象コミット**: `07827ac`(`claude/agentic-ai-best-practices-csth1r` 先端)
- **位置づけ**: 既存レビュー
  [`agentic-ai-best-practices-review.md`](./agentic-ai-best-practices-review.md)
  (3観点: Anthropic / Pydantic AI / IBM、指摘 D-1..D-8、計画 R1..R8)の**姉妹編**。
  本レビューは軸を変え、業務適用設計で参照される 8 つのエンジニアリング手法
  (プロンプト/コンテキスト/ループ/ハーネス/エージェンティック・エンジニアリング、
  AgentOps、MCP、エージェント評価)で同じリポジトリを再評価する。
  既存指摘と重なる箇所は D/R 番号を参照し、**本レビュー固有の新規指摘は N-1..N-4**
  として追加する。R1..R8 の優先順位は本レビューでも変更しない。
- **検証方法**: 出典は Web 検索でタイトル・要旨・到達性を確認(2026-07-16 時点)。
  `anthropic.com` / `ibm.com` は本セッションのネットワークポリシーで本文の直接取得が
  不可のため、内容は検索スニペットと既知の一次情報に基づく。リポジトリ側は実コード・
  テスト・正本ドキュメントを直接照合した。

---

## 出典(一次情報)

既存レビューの [A1]〜[A5] / [I1]〜[I5] に加え、本レビューで追加参照したものを含む。

### Anthropic

| ID | タイトル | URL |
|---|---|---|
| [A1] | Building Effective AI Agents | https://www.anthropic.com/engineering/building-effective-agents |
| [A2] | Writing effective tools for AI agents | https://www.anthropic.com/engineering/writing-tools-for-agents |
| [A3] | Effective context engineering for AI agents | https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents |
| [A4] | How we built our multi-agent research system | https://www.anthropic.com/engineering/multi-agent-research-system |
| [A5] | Demystifying evals for AI agents | https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents |
| [A6] | Effective harnesses for long-running agents | https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents |
| [A7] | Code execution with MCP | https://www.anthropic.com/engineering/code-execution-with-mcp |
| [A8] | Prompt engineering overview(Claude Docs) | https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/overview |
| [A9] | Model Context Protocol(Anthropic 発の公開標準) | https://modelcontextprotocol.io / https://www.anthropic.com/news/model-context-protocol |

### IBM

| ID | タイトル | URL |
|---|---|---|
| [I1] | What Are AI Agents? / What is Agentic AI? | https://www.ibm.com/think/topics/ai-agents / /agentic-ai |
| [I6] | What is AgentOps? | https://www.ibm.com/think/topics/agentops |
| [I7] | What Is Context Engineering? | https://www.ibm.com/think/topics/context-engineering |
| [I8] | Context engineering for trusted agentic AI | https://www.ibm.com/think/insights/context-engineering-foundation-trusted-ai |
| [I9] | What is Model Context Protocol (MCP)? | https://www.ibm.com/think/topics/model-context-protocol |
| [I10] | What is prompt engineering? | https://www.ibm.com/think/topics/prompt-engineering |
| [I11] | AI agent evaluation | https://www.ibm.com/think/topics/ai-agent-evaluation |
| [I12] | How to know if your AI agents are working as intended(IBM Research) | https://research.ibm.com/blog/ibm-agentops-ai-agents-observability |

### 補助出典

| ID | タイトル | URL |
|---|---|---|
| [C1] | Addy Osmani, "Agentic Engineering" / "Loop Engineering"(2026-06) | https://addyosmani.com/blog/agentic-engineering/ |

> 「ループエンジニアリング」「エージェンティックエンジニアリング」は Anthropic / IBM の
> 公刊用語ではない(2026-07 時点)。中身は Anthropic のエージェントループ
> (gather context → take action → verify → repeat)[A1][A3] とガードレール設計 [A1]、
> および人間が設計・品質を所有する開発規律 [A1][A5] に対応するため、
> 本レビューでは両者を一次情報に還元して定義する。

---

## §1 調査 — 8 手法の定義と検証済みベストプラクティス

8 手法は階層として整理できる: プロンプト ⊂ コンテキスト ⊂ ループ ⊂ ハーネス ⊂
エージェンティックエンジニアリング(内側から外側へスコープが広がる)。
AgentOps は運用横断、MCP は接続標準、評価は品質保証としてこの階層を貫く。

### 1.1 プロンプトエンジニアリング (PE)

1回のモデル呼び出しに与える指示文の設計 [A8][I10]。エージェント時代の位置づけは
「コンテキストエンジニアリングの部分集合」[A3]。

- **PE-1** 明確・直接的な指示。役割は system プロンプトで与える [A8]。
- **PE-2** 明示的デリミタで指示・データ・例を分離し、信頼できないデータは
  「指示ではない」と明示する [A8][I8]。
- **PE-3** 適切な「高度」: if-else 的ハードコードは脆く、曖昧すぎはシグナル不足。
  ヒューリスティックを与える高度が最適 [A3]。
- **PE-4** プロンプトはコードとして扱う: バージョン管理・単一ソース・テスト [A5]。
- **PE-5** ツール description もプロンプト。「いつ呼ぶか」を規範的に書く [A2]。

### 1.2 コンテキストエンジニアリング (CE)

推論時にモデルが見るトークン全体の構成最適化 [A3][I7]。有限の attention budget と
context rot を前提に「望む結果の尤度を最大化する最小の高信号トークン集合」を維持する。

- **CE-1** Just-in-time 検索(事前注入でなくツールによる実行時取得)[A3]。
- **CE-2** Compaction(上限接近時の要約・再初期化)[A3]。
- **CE-3** Structured note-taking(コンテキスト外の永続メモ)[A3]。
- **CE-4** サブエージェント分離(深い探索は独立コンテキストで、凝縮要約だけ返す)[A3][A4]。
- **CE-5** 信頼境界: 出所を管理し、信頼できないコンテンツを権威と混ぜない [I8]。

### 1.3 ループエンジニアリング (LE)

エージェントループの制御系(トリガ・検証器・リトライ・停止規則)の設計 [A1][C1]。

- **LE-1** 停止条件は多重に(ステップ数+トークン/コスト予算+時間)[A1]。
- **LE-2** 停止理由を閉じた語彙で監査可能に [A1][I6]。
- **LE-3** 検証器をループに組み込む(ルール → コード → LLM 判定の順に安価に)[A1]。
- **LE-4** ガードレール: 最小権限 allow-list、破壊的操作の HITL [A1]。
- **LE-5** 予測可能でよいならワークフロー、エージェントは必要な所だけ [A1]。

### 1.4 ハーネスエンジニアリング (HE)

モデル周囲の足場(ツール実行・状態管理・環境・復旧)の設計 [A6]。

- **HE-1** 初期化と実行の二相分離(initializer / coder)[A6]。
- **HE-2** 構造化した作業リスト(feature list 等)を「正」とする [A6]。
- **HE-3** 進捗ノート・チェックポイントで巻き戻し・再開可能に [A6]。
- **HE-4** 完了宣言の前に検証を強制する [A6]。
- **HE-5** suspend/resume はハーネス側の永続機構が所有し、モデルは型付き契約で関与 [A6]。
- **HE-6** 破壊的操作は専用ツール化し、型付き引数でゲート・監査できる形に [A2]。

### 1.5 エージェンティックエンジニアリング (AE)

エージェントと共に/の上に構築する開発規律 [C1]。「AI が実装し、人間が
アーキテクチャ・品質・正しさを所有する」(vibe coding との対比)。

- **AE-1** 合成可能な最小プリミティブで組む(重い抽象を避ける)[A1]。
- **AE-2** 仕様・ADR・受け入れ条件を先行(spec-driven)。コンテキストファイルを
  実態と乖離させない [C1]。
- **AE-3** 機械的ゲート(lint・型・テスト・ドリフトテスト・フック)[C1]。
- **AE-4** ACI(Agent-Computer Interface)を一級の設計対象に [A1][A2]。

### 1.6 AgentOps (AO)

自律エージェントのライフサイクル管理。**可観測性・評価・最適化**の 3 本柱 [I6][I12]。

- **AO-1** セッション/トレース/スパン 3 層の計装(OTel GenAI 準拠)[I6][I12]。
- **AO-2** コスト・レイテンシ・ループ段数・失敗率のメトリクス化とドリフト監視 [I6][A5]。
- **AO-3** 監査証跡とガバナンス(HITL、KPI)をライフサイクル全体に [I6]。
- **AO-4** 本番/実行の障害を評価セットへ還流する [I6][A5]。
- **AO-5** デプロイ前サンドボックス評価と継続評価を両方持つ [I6]。

### 1.7 Model Context Protocol (MCP)

エージェントと外部ツール/データ源を繋ぐオープン標準(Anthropic 発)[A9]。
IBM は「AI アプリの USB-C」と形容し、フレームワークではなく標準化された
統合レイヤと位置づける [I9]。

- **MCP-1** 採用判断: 統合を複数ホスト/エージェントで再利用するとき、
  サードパーティツール群を取り込むときに価値。単一アプリ内少数ツールなら
  in-process で足りる [I9][A2]。
- **MCP-2** ツールセット肥大に注意(名前空間・厳選・遅延ロード)[A2]。
- **MCP-3** tool annotations(readOnlyHint / destructiveHint 等)で破壊性を宣言し、
  ホストの承認ポリシーに接続する [A9]。
- **MCP-4** 大規模ツールセットではコード実行経由の MCP 呼び出しでトークン節約 [A7]。
- **MCP-5** MCP サーバは供給網として審査。ツール結果は信頼できない入力として
  インジェクション対策の対象 [I9][I8]。

### 1.8 エージェント評価 (EV)

- **EV-1** 実タスク・実障害由来の 20〜50 件から始める [A5]。
- **EV-2** 採点器 3 系統(コード採点 / LLM judge / 人間)の使い分け [A5][I11]。
- **EV-3** アウトカムとビヘイビアを別軸で採点 [A5]。
- **EV-4** judge の独立性とコスト計上 [A5]。
- **EV-5** 自動評価・本番監視・A/B・トランスクリプトレビューの補完 [A5][I11]。
- **EV-6** セッション/トレース/スパン各レベルの評価 [I6][I11]。

---

## §2 本リポジトリの評価

### 2.1 準拠している点(強み)

| 手法 | 実装根拠 | 対応 BP |
|---|---|---|
| PE | プロンプトはコードとして所有され、捕捉プロンプトの byte 互換テストで固定(`test_researcher.py` 等)。ツール設計規約 `TOOL-DESIGN-NOTES.md` は「いつ呼ぶか」を含む description 規約と準拠状況表を持つ | PE-4, PE-5 |
| CE | `docs/context-engineering.md` が [A3] の 3 技法を deep-research レーンへ適用済み: structured note-taking(`ResearchNote`)、compaction(`compact_digest` の dedup/cap/truncation)、sub-agent 分離(sub-researcher → lead は凝縮サマリのみ)。既存レビュー A-1 表の通り | CE-1, CE-3, CE-4 |
| LE | autonomous-agent の 4 ガードレール(`max_iterations` / `allowed_tools` / `approval_hook` / `budget`)+閉じた `stop_reason` 語彙は LE-1/2/4 の教科書的実装。6 パターンの workflow/agent 区別は LE-5 に一致 | LE-1, LE-2, LE-4, LE-5 |
| HE | `patterns/hitl/harness.py` の stop/approve/resume ハーネス: 1 往復 = 1 承認ステップ、`SessionStore` による予算の累積執行、消費状態機械(R2.x)。suspend/resume をハーネス側が所有する HE-5 の実装。hermetic テストハーネス(`block_network` + 決定論フェイク)も HE の一部として高水準 | HE-4, HE-5, HE-6 |
| AE | SDD パイプライン(spec 先行)、凍結契約 `patterns_contracts` + ドリフトテスト、pre-commit のモデル ID 非ハードコード強制、3 フレームワーク比較で「最小プリミティブ」方針を実証 | AE-1〜AE-4 |
| AO(部分) | 各レーンの `observability.py` + logfire/OTel `gen_ai.*` スパン(AO-1)、HITL レーンの監査ログ `audit.py`(AO-3)、CI レーン(unit / integration-ollama / watsonx / security)による継続ゲート | AO-1, AO-3 |
| EV | `EVAL-GRADERS.md` + `patterns_contracts/eval_graders.py`: outcome/behavior 分離(EV-3)、離散 Rating + `unknown`、独立 judge 注入シーム(EV-4)、tier 構成(unit グレーダ + Ollama E2E) | EV-2, EV-3, EV-4 |

### 2.2 既存レビューへの写像

既存レビューの指摘は本レビューの軸では次に対応する(重複計上しない):

| 既存指摘 | 8 手法軸での位置づけ | 計画 |
|---|---|---|
| D-1 予算計上の終了経路間不整合 | LE-1/LE-2(予算の監査可能性)+ AO-2(コスト可視性) | R1(P0) |
| D-2 タクソノミー表の分類 | AE-2(概念の正確さ) | R2(P1) |
| D-3 Agent 毎回構築 | AE-1(イディオム) | R3(P2) |
| D-4 `UsageLimits` 対比実装 | LE-1(事前判定型ガードレールの教材) | R4(P2) |
| D-5 `/chat` 単発ターン | CE(短期メモリの本線適用) | R5(P3) |
| D-6 pydantic-evals ADR | EV(エコシステム比較の記録) | R6(P3) |
| D-7 compaction 上限トリガ未実装 | CE-2 | R7(P4) |
| D-8 長期メモリ無計画 | CE-3(セッション横断) | R8(P4) |

### 2.3 本レビュー固有の新規指摘(N-1..N-4、重要度順)

| # | 重要度 | 手法 | 指摘 | 根拠 |
|---|---|---|---|---|
| N-1 | **高** | MCP | **MCP がリポジトリ全体に不在**。「エージェント実装ベストプラクティス・パターン集」を掲げる本リポジトリで、Anthropic 発のオープン標準 [A9] かつ IBM が標準統合レイヤと位置づける [I9] MCP のレーンが無く、不採用の判断も記録されていない。Pydantic AI は MCP クライアント(`MCPServerStdio` / `MCPServerStreamableHTTP`)・サーバ双方を公式サポートしており、`patterns/tool_design` の実演ツール群は MCP サーバ化の理想的な素材。tool annotations(MCP-3)と HITL レーンの `requires_approval` の対応も、本リポジトリだけが示せる教材になる | MCP-1..5 |
| N-2 | 中 | AO | **AgentOps 3 本柱のうち「最適化」柱が体系化されていない**。observability モジュールと評価契約はあるが、(a) `total_budget_spent` / `stop_reason` が OTel スパン属性として出力されず(トレースからコストが読めない)、(b) セッション/トレース/スパン 3 層 [I6] と本リポジトリの計装の対応が文書化されていない。R1(計上統一)の成果をテレメトリへ載せる出口が無い | AO-1, AO-2 |
| N-3 | 中 | HE | **長時間実行ハーネスの要素(HE-1..3)が deep-research レーンに無い**。[A6] の initializer/実行の二相分離・作業リストの成果物化・チェックポイント/再開に相当する構成が無く、研究 run は中断すると全損する。既存 D-8(長期メモリ)と同根であり、`ResearchNote` の永続化(R8)を「checkpoint/resume ハーネス」として仕様化すると両方を一度に満たせる | HE-1, HE-2, HE-3 |
| N-4 | 低 | PE | **プロンプトの「高度」規約が未文書化**。プロンプト本文はテストで固定されている(PE-4)が、`TOOL-DESIGN-NOTES.md` に相当する「プロンプト設計規約」(PE-3 の高度、system への権威配置、デリミタ規約)が無く、レーン間でスタイルが暗黙知になっている | PE-1..3 |

---

## §3 リファクタリング計画

R1..R8(既存)に N-1..N-4 由来の新規項 **NR-1..NR-3** を挿入する。
既存計画の優先順位・受け入れ条件は変更しない。工数: S(半日以下)/ M(1–2日)/
L(3日以上)。共通受け入れ条件: 凍結契約・ドリフトテスト・他レーン byte 互換を
壊さないこと。

### P1 — NR-1: MCP パターンレーンの新設(N-1、工数 L、spec 先行)

- **変更**: `patterns/mcp/` レーン(独立 uv レーン、他レーンと同型)を新設する。
  スコープは 3 点:
  1. **サーバ**: `tool_design.py` の directory ツール群(`directory_` 名前空間、
     pagination、`concise/detailed`)を MCP サーバとして公開(公式 `mcp` SDK /
     FastMCP)。tool annotations で `readOnlyHint` を宣言する(MCP-3)。
  2. **クライアント**: pydantic-ai の `MCPServerStdio` で同サーバに接続する
     エージェントを実装し、in-process ツール版との等価性をテストで示す
     (MCP-1 の採用判断の教材化)。
  3. **セキュリティ**: `SECURITY-NOTES.md` に MCP 節を追加 — サーバの供給網審査、
     ツール結果へのインジェクション対策(既存の egress policy / allow-list との
     接続)、annotations と `requires_approval` の写像表(MCP-5)。
- **受け入れ条件**:
  1. SDD パイプラインに従い spec/plan を先行させる。
  2. ユニットレーンはネットワーク I/O ゼロ(stdio 内 in-process 接続)。
  3. 既存レーン・凍結契約は無変更(追加のみ)。README のタクソノミーには
     「応用レイヤー」(RAG と同格)として索引する — ワークフロー 6 分類とは別軸。
- **リスク**: 中。`mcp` SDK の追加依存はロック版更新+`minimumReleaseAge` 同等の
  審査(dependabot 管理)に載せる。

### P2 — NR-2: 予算・停止理由のテレメトリ出力と AgentOps 文書(N-2、工数 S+S、R1 後)

- **変更**: (a) R1 完了後、autonomous-agent / deep-research の run 結果
  (`total_budget_spent`、`stop_reason`)を各レーン `observability.py` の
  スパン属性(`gen_ai.usage.*` 系)として出力する。
  (b) `docs/agentops.md` を新設し、IBM 3 本柱 [I6] × 本リポジトリの対応表を記録:
  可観測性(observability モジュール/logfire)、評価(EVAL-GRADERS 契約 + CI レーン)、
  最適化((a) のメトリクスと R4 `UsageLimits` の事前判定)。セッション/トレース/
  スパン 3 層と HITL `SessionStore` / run / ツール呼び出しの対応も明記する。
- **受け入れ条件**: (a) は既存スパンのスキーマ追加のみ(名称は OTel GenAI 準拠)。
  観測テスト(`test_observability.py` 系)に属性検証を追加。(b) は文書のみ。
- **依存**: R1(計上統一が先。不整合な値をテレメトリに載せない)。

### P3 — NR-3: deep-research の checkpoint/resume を R8 と統合仕様化(N-3、工数 L、spec 先行)

- **変更**: R8(長期メモリ)の spec を「長時間ハーネス」まで広げて 1 本の spec に
  する: `ResearchNote` + 研究計画(brief/plan)を run 開始時に成果物として永続化し
  (HE-1/HE-2)、sub-researcher 完了毎にチェックポイント(HE-3)、再開時は
  ノートから文脈を再構築する(CE-3 と同じ器 = RAG レーンの `VectorStoreIndex` か
  ファイル永続)。
- **受け入れ条件**: まず spec/research のみ(SDD)。実装は別イテレーション。
  R7(compaction 上限トリガ)との整合(再初期化時に compact_digest を使う)を
  spec 内で扱う。
- **依存**: R8 を置換(統合)。R7 と相互参照。

### P3 — NR-4: プロンプト設計規約の明文化(N-4、工数 S、文書のみ)

- **変更**: `patterns/PROMPT-NOTES.md`(`TOOL-DESIGN-NOTES.md` と同型)を新設:
  (a) PE-3 の高度規約(ハードコード列挙でなくヒューリスティック)、
  (b) 権威の配置(方針は system、データはデリミタ付き user)、
  (c) byte 互換テストによる固定の運用(変更時は spec 追補が先)、
  (d) 各レーンの準拠状況表。
- **受け入れ条件**: 文書のみ。README から辿れること。

### 統合後の依存関係と着地順

```
R1(P0)──→ NR-2(a)(計上統一 → テレメトリ出力)
R2 / R6 / NR-4(文書系・独立)── 即着地可能
NR-1(P1・独立、spec 先行)
R3(a)→R3(b)、R4 → R7(既存のまま)
R5 → R8+NR-3(統合 spec)
```

---

## §4 まとめ

本リポジトリは 8 手法のうち **LE(ガードレール+停止語彙)・CE(3 技法の適用)・
AE(SDD+凍結契約)・EV(多軸グレーダ契約)が既に模範的**で、既存レビューの
R1..R8 が残る改善を正しく捕捉している。本レビューで追加された最大のギャップは
**MCP の完全な不在(N-1)**であり、パターン集という性格上、単なる機能追加でなく
「採用判断・annotations と HITL の接続・供給網審査」まで含む教材レーンとして
埋める価値が高い。次いで AgentOps の「最適化」柱(N-2)は R1 の成果を
テレメトリに接続する小さな追加で成立し、長時間ハーネス(N-3)は既存 R8 と
統合することで計画の重複なく着地できる。
