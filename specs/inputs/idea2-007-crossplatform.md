# Idea: Spec 007 — Cross-Platform Pattern Collection 2b（Docling RAG）

- 起票日: 2026-06-13
- 前提:
  - `005-cross-platform` 完了（patterns/ 基盤 + routing / orchestrator-workers の
    3フレームワーク実装、レーン毎 unit GREEN、CI 2本）。
  - `006-2a-cross-platform` で **shared-contracts パッケージ
    `patterns/contracts/`**（依存ゼロ・`requires-python >=3.13`・PEP 561 `py.typed`）
    を昇格済み。契約ドリフト検知を「README 正本 == パッケージ」の単一点
    （`patterns/contracts/tests/unit/test_contract_drift.py`、4テスト GREEN）へ縮約済み。
  - 注: 006-2a の残り4パターン（prompt-chaining / parallelization /
    evaluator-optimizer / autonomous-agent）×3レーンの**実装（tasks 3〜12）は
    未完**。本イテレーションは契約パッケージ基盤の上に積むが、4パターン実装の
    完了を硬い前提とはしない（独立に着手可能）。
- ねらい: idea2-006 §2b を実体化する。Docling `HybridChunker` でドキュメントを
  チャンク化し、**引用（ソースアンカー）付き回答**を返す RAG パイプラインを
  LlamaIndex で構築する。torch 系の重量依存を引き込むため、配置（既存
  llamaindex レーン拡張 or 独立レーン）は実測で判断する。

---

## 1. 入力ドキュメントと検証前提

- 起票元: `specs/inputs/idea2-006-crossplatform.md` §2b / §4 論点3
- 原典調査: `specs/005-cross-platform/research.md`（Docling HybridChunker /
  Production Architectures for Agentic AI の RAG 節）
- Docling / llama-index-readers-docling / HybridChunker の現行 API・依存ツリー
  （torch / transformers 等の有無とサイズ）は**実装時に Web + 実測で再検証**し、
  `specs/007-*/research.md` に記録する（005/006 の検証規律を踏襲）。

## 2. スコープ（2b = Docling RAG）

### 2a. RAG パイプライン（引用付き回答）

- Docling `HybridChunker` でドキュメント（PDF / Markdown 等）をチャンク化し、
  ベクトルインデックス化 → クエリ → **引用付き回答**（回答テキスト + 各主張の
  ソースアンカー: ドキュメント名 / ページ or セクション / チャンク ID）。
- LlamaIndex のクエリエンジン + ノードポストプロセッサ（引用抽出）で構成。
  プランナー LLM は使わず、決定論性とテスト容易性を優先する。
- 契約は `patterns/contracts/` に追加する（`RagAnswer{answer: str,
  citations: list[Citation]}`、`Citation{source: str, locator: str,
  chunk_id: str, score: float}` 等）。正本は新設パターン README、ドリフトは
  既存単一点テストが検知（006-2a の規律をそのまま拡張）。

### 2b. 配置の実測判断（idea2-006 §4 論点3）

- 候補: ① llamaindex レーン同居 / ② `patterns/rag/` 独立レーン。
- 判断材料: Docling 導入による **uv.lock 差分サイズ**（torch/transformers の
  引き込み有無）、`mise run patterns:setup` / CI 実行時間への影響、既存
  llamaindex レーンの責務純度。/sdd で PoC 実測の上、独立レーンを既定候補とする
  （重量依存を既存レーンの lockfile/CI から隔離する観点）。

### 2c. オフラインテスト戦略

- **チャンカーは実物**（HybridChunker は決定論的）で小さな固定ドキュメントを
  チャンク化し、**ゴールデンチャンク・スナップショット**で回帰検知。
- **LLM・埋め込みはフェイク**（005/006 のフェイク規律を踏襲。埋め込みは
  決定論的なスタブベクトル、LLM は引用を含む台本応答）。ネットワーク I/O ゼロ。
- 引用の健全性テスト: 回答中の各 citation が実在チャンクを指し、locator が
  ソース範囲内であること（dangling citation を loud-fail）。

### 2d. 結合テスト / 可観測性 / セキュリティ

- `RUN_INTEGRATION_PATTERNS=1` ゲートの Ollama 結合テスト（契約レベルアサート:
  citations が1件以上、各 citation が既知ソースを指す）。
- `configure_tracing()` 適用 + span≥1 検証（005/006 と同手段）。
- SECURITY-NOTES に RAG 固有リスク（インデックス汚染 / 引用なりすまし /
  PII を含むチャンクの露出）を OWASP LLM Top 10（過度の依存 / データ漏洩）へ
  マッピング。`pip-audit` を新レーン dev 依存に含む。

## 3. スコープ外（後続イテレーション）

- マルチモーダル（画像・表）チャンク化と引用
- 複数ドキュメント横断・再ランキング・ハイブリッド検索のチューニング
- PydanticAI / BeeAI レーンへの RAG 移植（本イテレーションは LlamaIndex のみ。
  Docling+LlamaIndex の役割分担が原典調査の主眼のため）
- idea2-006 §2c–2e（FastAPI SSE = spec 008 / A2A・ACP / Evals CI）

## 4. /sdd 起動時に解決すべき論点

1. **配置**（§2b）: llamaindex レーン同居 vs `patterns/rag/` 独立レーン。
   PoC で uv.lock 差分・CI 時間を実測してから確定。
2. **Docling 依存の重量**: torch を引き込むか、CPU-only / 軽量バックエンドで
   回避できるか。CI のキャッシュ戦略（`cache-dependency-glob`）への影響。
3. **引用契約の粒度**: locator をページ番号 / セクションパス / 文字オフセットの
   どれで表すか（ドキュメント種別非依存にできる形を優先）。
4. **ゴールデンスナップショットの安定性**: HybridChunker のバージョン更新で
   チャンク境界が変わった際の更新運用（スナップショット再生成の承認フロー）。
5. **埋め込みフェイクの決定論化**: ハッシュベースのスタブ埋め込みで近傍検索の
   順序を固定できるか（検索結果順序がテストの flakiness 源にならないこと）。

## 5. 参考

- `specs/inputs/idea2-006-crossplatform.md` — 第2イテレーション全体の起票文書
- `specs/006-2a-cross-platform/` — shared-contracts 昇格・単一点ドリフトの設計
- `specs/005-cross-platform/research.md` — Docling / RAG 節の一次情報
- `patterns/README.md` — 二軸タクソノミーとフレームワーク実測比較表
- `patterns/contracts/` — 契約パッケージ（本イテレーションの RAG 契約の追加先）
- OWASP LLM Top 10 2025 / OWASP Agentic AI Top 10 (2025-12)
