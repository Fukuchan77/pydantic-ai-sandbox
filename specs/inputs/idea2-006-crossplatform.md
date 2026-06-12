# Idea: Spec 006 — Cross-Platform Pattern Collection 第2イテレーション

- 起票日: 2026-06-12
- 前提: `005-cross-platform` 完了（ブランチ `claude/happy-noether-939dgs` =
  005-cross-platform ブランチ。patterns/ 基盤 + routing / orchestrator-workers
  の3フレームワーク実装、レーン毎 unit GREEN、coverage 97.8–98.0%、
  patterns-ci.yml / patterns-integration-ollama.yml 構成済み）
- ねらい: 005 で意図的にスコープ外とした残課題（idea2-005 §3）を完遂し、
  パターン集を **Anthropic タクソノミー全網羅 + 応用レイヤ（RAG / SSE /
  A2A / Evals CI）** まで拡張する。

---

## 1. 繰越前提・残課題（005 pdca/check.md より）

1. **結合テストの実機確認が未**: patterns-integration-ollama.yml の
   workflow_dispatch 起動による green 確認を 006 着手前または序盤に行う。
2. BeeAI の LLM 呼び出し粒度スパンは上流計装 API 待ち（Accepted Risk 継続）。
3. 契約複製は `tests/unit/test_patterns_contract_sync.py` がドリフト検知中。
   パターンが 2→6 に増えると複製コストが跳ねるため、**shared-contracts 昇格
   判断を本イテレーションの論点に含める**（§4）。

## 2. スコープ（8項目）

### 2a. 残り4パターン × 3フレームワーク（計12実装）

005 と同じ規律を適用する: パターン契約（Pydantic モデル + エントリポイント）
の正本はパターン README、必須4セクション（型安全 / テスト / 可観測性 /
セキュリティ）、オフラインユニットテスト + Ollama ゲート付き結合テスト、
configure_tracing スパン存在テスト。

1. **prompt-chaining** — 逐次ステップ + ステップ間ゲート（プログラム検証で
   不合格なら早期終了）。契約: 型付き中間成果のチェーンとゲート判定の記録。
2. **parallelization** — sectioning（独立サブタスク分割）と voting（同一タスク
   多数決）の2変種を1契約で表現。fan-out は各フレームワークの流儀
   （asyncio.gather / ステップ内 gather / send_event+collect_events）を比較。
3. **evaluator-optimizer** — 生成器と評価器のループ。契約: 評価スコア・
   フィードバック・最大反復数・打ち切り理由を構造化。評価器の判定は
   `Literal`（pass / revise）で語彙固定。
4. **autonomous-agent** — ツールループ + 環境フィードバック + 停止条件。
   唯一の「Agent」型パターンであり OWASP Agentic AI Top 10 の主戦場。
   ガードレール必須: 最大反復数、ツール許可リスト、危険操作のヒューマン
   承認フック、ループ毎の予算消費記録。

### 2b. Docling + LlamaIndex RAG レーン

- Docling `HybridChunker` でドキュメントをチャンク化し、引用（ソース
  アンカー）付き回答を返す RAG パイプライン。
- 配置は llamaindex レーン拡張か独立レーンかを /sdd で決定（§4）。
  Docling は torch 系の重量依存を引き込むため、既存レーンの lockfile /
  CI 時間への影響を実測して判断する。
- オフラインテスト: チャンカーは実物（決定論的）、LLM・埋め込みは
  フェイク。ゴールデンチャンク・スナップショットで回帰検知。

### 2c. FastAPI EventSourceResponse SSE デモ

- エージェント実行のイベント（ステップ開始 / ツール呼び出し / トークン /
  完了）を SSE でストリーム配信する最小デモアプリ。
- sse-starlette の `EventSourceResponse` を使用。イベントスキーマは
  Pydantic モデルで型付けし、パターン契約と同じ複製+同期検知の規律に乗せる。
- テスト: httpx `ASGITransport` + フェイクモデルでストリーム全体を
  オフライン検証（切断・キャンセル経路を含む）。

### 2d. BeeAI A2A/ACP 相互運用サーバ

- BeeAI レーンに A2A（Agent2Agent）プロトコルのサーバ/クライアント往復
  デモを追加し、フレームワーク間相互運用を実証する。
- 注意: ACP は A2A プロジェクトへの合流が進行しており、BeeAI 側 API の
  現行サポート状況（acp- 系か a2a- 系か）は**実装時に Web 検証**して
  research.md に記録する（005 と同じ検証規律）。
- テスト: インプロセスでサーバを起動しループバックで契約検証
  （ネットワーク外部依存なし）。

### 2e. Pydantic Evals の CI 組込

- pydantic-evals の `Dataset` / `Evaluator` で routing・orchestrator-workers
  （および 2a の新パターン）の品質回帰を検知。SpanTree によるスパンベース
  評価（「分類器スパンが正しい経路語彙を記録したか」等）を含める。
- 2層構成: ① オフライン evals（フェイクモデル、PR 必須ゲート）
  ② 実モデル evals（Ollama、workflow_dispatch / nightly、非ブロッキング
  レポート）。閾値とレポート形式は /sdd で確定。

## 3. スコープ外（将来イテレーション）

- LlamaAgents の実測評価（005 research で公式 docs 403 のまま）
- マルチプロバイダ（watsonx / LiteLLM）でのパターン横断ベンチマーク
- SSE デモのフロントエンド（curl / httpx クライアントでの確認まで）

## 4. /sdd 起動時に解決すべき論点

1. **イテレーション分割**: 8項目を 1 スペックで進めるか、
   「006a = 残り4パターン（コア）」「006b = 応用レイヤ（RAG / SSE / A2A /
   Evals CI）」に分けるか。推奨は単一スペック内のフェーズ分割
   （タスク依存: 2a → 2e、2b/2c/2d は独立並行可）。
2. **shared-contracts 昇格**: パターン6種 × 3レーン複製の同期コストと、
   `tool.uv.sources` パス依存パッケージ化のトレードオフ。昇格するなら
   requires-python 交差（>=3.13,<3.14 と >=3.14）を跨げる契約専用
   パッケージ（依存ゼロ、`requires-python >=3.13`）として設計する。
3. **Docling の配置**: llamaindex レーン同居 or `patterns/rag/` 独立レーン。
   判断材料 = lockfile 差分サイズ・CI 時間・既存レーンの責務純度。
4. **SSE デモの配置**: ルートアプリ拡張 or patterns/ 配下の独立プロジェクト。
   ルート CI（279 passed / 98.83%）無変更の原則を維持できる方を選ぶ。
5. **autonomous-agent のオフライン決定論化**: FunctionModel（PydanticAI）/
   自作フェイク（BeeAI・LlamaIndex）でツールループを台本化する方式の統一。
6. **Evals の必須ゲート閾値**: オフライン evals を fail 条件にする基準
   （全ケース pass か、スコア下限か）。

## 5. 参考

- `specs/inputs/idea2-005-cross-platform.md` — 第1イテレーションの決定事項
- `specs/005-cross-platform/research.md` — 検証済み一次情報・CVE 表
- `specs/005-cross-platform/pdca/check.md` — 残課題（§1 の繰越元）
- `patterns/README.md` — 二軸タクソノミーとフレームワーク実測比較表
- Anthropic "Building Effective Agents" (2024-12-19)
- OWASP Agentic AI Top 10 (2025-12) / OWASP LLM Top 10 2025
