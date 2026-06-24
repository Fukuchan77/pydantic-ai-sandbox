# フレームワーク比較・ハイブリッド活用検証（Deep Research を題材に）

Deep Research（Multi-Agent System）を題材に、Pydantic AI と主要エージェントフレームワーク
（**LangGraph / CrewAI / Microsoft Agent Framework / LlamaIndex / BeeAI / Langflow / Dify**）の
**メリット・デメリット**を整理し、各フレームの**優れたロジックを安全に取り込む**方針と、
**Pydantic AI をラップ／応用するハイブリッド**の指針をまとめる。実装比較の実測（PydanticAI / BeeAI /
LlamaIndex の3レーン横断）は [../README.md](../README.md#フレームワーク比較本イテレーションで実測した差異) を参照。

## 設計の出発点：なぜ Pydantic AI を「core」に置くか

本リポジトリの一貫した観察（Anthropic「Building Effective Agents」逐語）:
> "the most successful implementations weren't using complex frameworks … they were building with
> simple, composable patterns."

Pydantic AI の強みは **型付き構造化出力（検証失敗で自動リトライ）＋最小プリミティブ（`Agent` /
ツール / `Model` DI）＋ネイティブ可観測性（`instrument_model` の `gen_ai.*`）** にある。Deep Research の
ような Agentic AI は「契約（`ResearchBrief`/`SubQuestion`/`Finding`/`ResearchReport`）を core に据え、
オーケストレーション層を薄く保つ」と堅牢になる。本レーンはこの方針で、orchestrator-workers /
parallelization / autonomous-agent / RAG / SSE の既存プリミティブを**合成**した（再実装しない）。

各フレームは「Pydantic AI に無い／弱い能力」を補う。以下はその**取り込みどころ**と
**ラップの向き**（Pydantic AI を包むか、フレームを包むか）の検証。

## 比較サマリ（メリット・デメリットと取り込みどころ）

| フレームワーク | 主なメリット | デメリット / 注意 | Deep Research に取り込む良所 | ラップの向き（推奨） |
|---|---|---|---|---|
| **LangGraph** (LangChain) | 明示的グラフ state、**checkpoint/durable execution**、interrupt（HITL）、再開可能性 | 学習コスト・抽象が厚い。LangChain 依存の重さ | state を契約オブジェクトで受け渡し、ステージ境界に **checkpoint/resume seam** を置く設計 | 永続化が要るなら **LangGraph で Pydantic AI ステージを包む** |
| **CrewAI** | **role/task/crew** の直感的メンタルモデル、role ベースの協調が書きやすい | 細粒度制御が弱い、暗黙挙動が多い | lead（orchestrator）vs focused researcher の**役割分割＋非重複タスク記述**（既に `ResearchPlan`/`SubQuestion`） | 役割設計は思想として取り込み、**実行は Pydantic AI**（包まない） |
| **Microsoft Agent Framework** | **middleware** パイプライン、thread/会話状態、エンタープライズ統合（Azure） | 比較的新しくエコシステム発展途上、.NET 寄りの歴史 | `instrument_model`＋`on_event` を **middleware 類似**（横断トレース/ガードレール）、researcher 毎の独立 context を「thread」として明示 | middleware 思想を seam で再現、**Pydantic AI を core に** |
| **LlamaIndex** (Workflows) | **event 駆動 step**、`ctx.send_event`/`collect_events`、RAG/インデックスが強い | structured output は `astructured_predict` 経由で挙動分岐、順序復元が必要 | `ProgressEvent` 判別共用体を**イベント語彙**に。RAG レーンは LlamaIndex 実装（検索基盤として併用可） | RAG は **LlamaIndex 実装をそのまま応用**、調査制御は Pydantic AI |
| **BeeAI Framework** | Pydantic-state ステートマシン、明示再検証、ProviderName Literal 等の良質な型 | 公式モック無し（テストフェイク自作）、structured は明示再検証が必要 | **契約モデル＝state** の発想。Pydantic AI は自動再検証が効く点が優位（実測比較表参照） | 思想取り込み、**Pydantic AI を core に** |
| **Langflow** | **ビジュアル**ノードグラフ、ノーコードでフロー試作、共有しやすい | 大規模・厳密制御や CI 連携は不向き、生成物の保守性 | 厳格契約境界（`ResearchBrief`…）が**ノードのシリアライズ単位**そのもの。`run_deep_research` を単一合成ノード化 | **Langflow で Pydantic AI ノードを包む**（試作/共有用） |
| **Dify** | **LLMOps プラットフォーム**（GUI、プロンプト管理、RAG、API 公開、運用監視） | プラットフォーム結合度が高い、深いカスタムはコード側に逃がす | 運用面（プロンプト/評価/公開 API）を Dify、**深い Agentic ロジックを Pydantic AI で実装し API 連携** | **Dify から Pydantic AI サービスを呼ぶ**ハイブリッド |

## 取り込みの詳細（安全な再現方法）

### LangGraph — durability / checkpoint
- **取り込む**: 研究 state を**不変の契約オブジェクト**（`ResearchPlan`→`Finding[]`→`ResearchReport`）で
  ステージ間に明示受け渡しする本レーンの設計は、LangGraph の「明示 state」と同型。長時間の調査を
  中断・再開可能にするには、`on_event`/各ステージ境界に **checkpoint/resume seam**（plan・各 finding を
  外部ストアへ退避）を attach すればよい。本レーンは seam を用意し、永続化実体は範囲外（拡張点）。
- **ハイブリッド**: durability/HITL interrupt が要件なら、**LangGraph のノードとして `build_brief_and_plan` /
  `run_subquestion` / `write_report` を呼ぶ**（Pydantic AI を core、LangGraph を耐久層に）。逆向き
  （Pydantic AI で LangGraph を包む）は利得が薄い。

### CrewAI — roles / tasks / crews
- **取り込む**: 「lead（計画）」と「focused researcher（単一 subquestion）」の役割分割、**非重複・自己完結の
  タスク記述**は CrewAI の task 設計の良所そのもの。Anthropic も「サブエージェントへ明示的で重複しない
  タスク記述を与えること」を重視。本レーンの `_PLANNER_INSTRUCTIONS`（"answerable on its own … must not
  overlap"）と `SubQuestion` がこれを契約化している。
- **ハイブリッド**: CrewAI を実行層に被せる利得は小さい（細粒度制御・型安全・テスト容易性で Pydantic AI が優位）。
  **役割設計の思想のみ取り込み、実行は Pydantic AI** を推奨。

### Microsoft Agent Framework — middleware / threads
- **取り込む**: MAF の middleware（リクエスト/ツール呼び出しに横断処理を差し込む）は、本レーンの
  `instrument_model`（横断トレース）と `on_event`（横断進捗）seam で再現できる。researcher 毎の**独立
  context window**は MAF の thread に対応し、Anthropic の「サブエージェントは独立コンテキスト」原則を満たす。
- **ハイブリッド**: ガードレール/監査を middleware 的に増やしたい場合も、Pydantic AI の DI seam に
  関数を挿す形で実現でき、**core を置き換える必要はない**。

### LlamaIndex — event 駆動 Workflows + RAG
- **取り込む**: `ProgressEvent` 判別共用体は LlamaIndex Workflows のイベント語彙に対応。LlamaIndex の
  順序復元課題（`collect_events`）は、本レーンでは `asyncio.gather`（入力順保持）＋ plan-index で解消済み。
- **ハイブリッド**: **検索バックエンドとして LlamaIndex の `VectorStoreIndex` を `SearchProvider` 実装に
  差し込める**（local-deep-research 風のローカル文書調査）。RAG レーン（`patterns/rag/`）が既に
  LlamaIndex 実装を持つため、その retriever を Deep Research の検索 seam に橋渡しするのが自然な応用。

### BeeAI — Pydantic-state / 明示再検証
- **取り込む**: 「契約モデルを state にする」発想。ただし BeeAI は structured 出力に**明示再検証**が要る
  のに対し、Pydantic AI は `output_type=Model` で検証失敗時に**自動リトライ**する（実測比較表）。Deep Research の
  `ResearchPlan`/`Finding` 生成はこの自動再検証の恩恵を受ける。

### Langflow / Dify — 低コード / 可視化 / LLMOps
- **取り込む**: 厳格な契約境界（`ResearchBrief`/`SubQuestion`/`Finding`/`ResearchReport`）は、ビジュアル
  ビルダーがノード間で受け渡す**シリアライズ可能なスキーマ**そのもの。`run_deep_research` を**単一の合成
  可能ノード/サービス**として公開すれば、Langflow の試作・共有や Dify の運用（プロンプト管理・評価・API 公開・
  監視）に載せられる。
- **ハイブリッド**: **Langflow/Dify から Pydantic AI の Deep Research サービスを呼ぶ**（低コード層＝オーケスト
  レーション UI/運用、コード層＝型安全な Agentic ロジック）。深いロジックを低コード側に作り込むと保守性が
  落ちるため、**境界をスキーマで切る**のが安全。

## 「ラップして応用」の総合指針

- **既定**: Pydantic AI を**型付き core**に据え、フレームは「durability（LangGraph）」「可視化/試作（Langflow）」
  「運用/公開（Dify）」「検索基盤（LlamaIndex）」など**不足能力を補う層**としてのみ採用する。
- **フレームを包む向き**が有効なのは、そのフレーム固有の強み（永続グラフ実行・ビジュアル・LLMOps）が
  要件のとき。**Pydantic AI でフレームを包む向き**は、既存資産を型安全に呼び出すアダプタ程度に留める。
- いずれの場合も**契約（Pydantic モデル）を境界**にすることで、フレーム差し替え時の影響を局所化できる
  （本リポジトリの contracts ＋ドリフトテスト規律と同じ思想）。

## コストの現実：Multi-Agent の ~15x トークン

Anthropic の計測では、マルチエージェント調査は単一エージェントの**約15倍のトークン**を消費し得る。
価値が高いのは「並列化で時間短縮できる広域・分岐的な調査」に限られる。本レーンはこのコストを
**上限設計**で抑制する:

- `max_researchers`（ファンアウト上限、`truncated` で可視化）
- `max_iterations`（researcher 毎の反復上限、`Finding.truncated`/`iterations`）
- `top_k`（検索出力量の上限）
- 検索 seam の**最小権限**（任意 URL/ツール不可）

さらに **token-budget seam**（autonomous-agent の `_budget_spent` 相当＝`ModelResponse.usage` 合算）を
ファンアウトに被せれば、明示予算で打ち切れる（v1 は cap で抑制、予算ガードは拡張点）。安全性の OWASP
マッピングは [../SECURITY-NOTES.md](../SECURITY-NOTES.md#deep-research-応用レイヤ--owasp-マッピングspec-009-req-13)。

## 参照アーキテクチャ

- Anthropic, *How we built our multi-agent research system* — lead→並列 subagent→citation、~15x トークン
- LangChain, *open_deep_research* — supervisor/researcher＋scoping→brief→report、MCP/検索 API 設定
- Hugging Face, *open-deep-research* — コード駆動エージェントループ、GAIA ベンチ
- LearningCircuit, *local-deep-research* — 反復検索・適応的エンジン選択・ローカル文書蓄積
