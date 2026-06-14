# 007-2b-cross-platform — Discovery & Research Log

`/sdd-plan` 生成。`gap-analysis.md`（要件 ↔ 既存コードの差分）を起点に、外部依存
（Docling 現行 API・CVE ゲート）の一次検証と設計判断（ADR）を確定する。実測 PoC
（uv.lock 差分・CI 時間・トークナイザ調達）は `/sdd-impl` の最初の Spike タスクに
委譲し、本ログはその判断基準を固定する。

調査日: 2026-06-13 / 一次情報: PyPI メタデータ・docling-core ソース（context7）・
既存レーン実コード（serena/Explore 調査）。

## Discovery type

**Extension（light）**。005/006-2a が確立した patterns/ 規律（独立 uv レーン・
`patterns/contracts/` パス依存・単一点ドリフト・per-lane テスト三層・OpenInference
計装・mise/CI 二系統）に、初の**応用レイヤ（RAG）**を積む。新規ビルドは3点に局所化
（fake 埋め込み・引用健全性 loud-fail・ゴールデンスナップショット基盤）。整合点の確認
が主で、greenfield 探索は不要。

## Investigations

### I-1. Docling `HybridChunker` の現行 API とチャンクメタデータ（R2.x / R4.4）

- **Question**: `source` / `locator` / `chunk_id` を `DocChunk.meta` から決定論的に
  導出する正確な属性パスは何か。PDF 変換器（重量）を CI から排除できるか。
- **Findings**:
  - `DoclingDocument.load_from_json(path)` で**事前変換済みドキュメントを JSON から
    ロード**できる（`docling_core.types.doc.document.DoclingDocument`）。→ PDF→Document
    変換器（layout モデル, 重量）を**固定資産化**してオフラインテスト経路から排除可能
    （Clarification 2 退避策の具体形 / ADR-3）。
  - `HybridChunker(tokenizer=<BaseTokenizer>, max_tokens=<int>)`。`tokenizer` は
    `get_default_tokenizer()` がデフォルト。`merge_peers` / `repeat_table_header` 等
    ブール群あり。`chunker.chunk(doc)` が `DocChunk` を yield、`chunker.contextualize(chunk)`
    が埋め込み用シリアライズ文字列を返す。
  - `DocChunk.meta`（`DocMeta`）から出所を決定論導出:
    - **source** → `meta.origin`（変換元ファイル名）。固定資産では `chunk_document(..., source=...)`
      で明示注入する方が頑健（ADR-4）。
    - **locator** → `meta.doc_items[i].prov[0]`（`ProvenanceItem{page_no:int,
      bbox:BoundingBox, charspan:CharSpan}`）+ `meta.headings`。決定論的優先順位で
      文字列化（下記 locator 規約）。
    - **chunk_id** → API は ID を持たないため、**決定論的順序の序数**から導出する
      （ADR-4）。
  - `locator` 文字列化規約（ドキュメント種別非依存・R4.4）:
    1. `prov[0].page_no` あり → `page={page_no}`（必要に応じ `;char={start}-{end}`）
    2. page なし & `headings` あり → `section={heading-path}`
    3. いずれも無し → `char={charspan.start}-{charspan.end}`
- **Evidence**: context7 `/docling-project/docling-core` —
  `transforms/chunker/hybrid_chunker.py`（HybridChunker フィールド）/
  `types/doc/document.py`（`ProvenanceItem` / `iterate_items(page_no=...)` /
  `load_from_json`）。`gap-analysis.md` §3.3（PyPI 実測: `transformers` は
  `chunking` extra 経由の任意依存、`torch` 直接依存に非出現）。

### I-2. オフライン決定論のためのトークナイザ調達（R6.1 / NFR-2）

- **Question**: `HybridChunker.chunk()` は tokenizer を要する。CI でネットワーク I/O
  （HF ダウンロード）を起こさず決定論的に回せるか。
- **Findings**: 二択。(a) 軽量 HF トークナイザを**ピン**し、`patterns:setup`（ネット
  許可フェーズ）で HF キャッシュに事前取得 → unit 実行時は `HF_HUB_OFFLINE=1` を強制し
  ネットワーク到達を loud-fail させる。(b) `tiktoken` ベースのトークナイザ（オフライン
  動作）を `HybridChunker` に注入し HF 依存を回避。→ **(a) を主、(b) を退避**として
  PoC で確定（ADR-3 / Risk R-1）。いずれも `max_tokens` を明示固定して境界を決定論化。
- **Evidence**: HybridChunker `tokenizer: BaseTokenizer = Field(default_factory=
  get_default_tokenizer)`（context7）。gap-analysis §5 研究項目3。

### I-3. ベクトルインデックスと CVE-2025-1793 ゲート（R3.1 / R9.1）

- **Question**: 採用するインデックス実装が CVE-2025-1793（llama-index-core
  <=0.12.21 のベクトルストア統合8種 SQL インジェクション）に該当しないか。
- **Findings**: LlamaIndex 既定の **in-memory `VectorStoreIndex`（`SimpleVectorStore`）**
  は脆弱な「8統合」（外部 DB バックエンド）に**該当しない**。外部ベクトル DB を一切
  導入せず in-memory 既定で構成すれば CVE を回避できる。併せて `llama-index-core` の
  フロアを修正版以上（`>=0.12.28`、実際は llamaindex レーン同様 `>=0.14`）にピン。
  → SECURITY-NOTES の当該行を「ベクトルストア不使用」から「in-memory 既定のみ使用・
  外部統合8種は非依存」へ更新（R9.1）。
- **Evidence**: `patterns/SECURITY-NOTES.md`（CVE-2025-1793 行: 修正済 v0.12.28 /
  RAG イテレーション着手時のゲート条件として記録）。llamaindex レーン pyproject
  `llama-index-core>=0.14`。

### I-4. 埋め込み DI seam（R3.2 / R3.3）

- **Question**: オフライン決定論フェイク埋め込みと結合実埋め込みを切替える seam の形。
- **Findings**: LlamaIndex `BaseEmbedding` 派生で seam を作る。オフライン =
  `HashEmbedding`（チャンク内容→ハッシュ→固定次元ベクトル、`_get_text_embedding` /
  `_get_query_embedding` 実装）。結合 = `OllamaEmbedding`（env で設定）。近傍順序は
  ハッシュベクトルで決定論化し、スコア同点時は `chunk_id` 昇順タイブレーク（R3.3）を
  自前ポストプロセッサで適用。既存 `fake_llm.py` の `CustomLLM` 自作と同型の手法。
- **Evidence**: llamaindex レーン `tests/support/fake_llm.py`（`CustomLLM` 自作前例）。
  gap-analysis §2 R3.2/R3.3。

### I-5. 引用付き回答と dangling citation loud-fail（R4.x / R9.3）

- **Question**: LlamaIndex `CitationQueryEngine` をそのまま使えるか。loud-fail はどこ。
- **Findings**: `CitationQueryEngine` は出発点だが、(a) 引用 0 件禁止（R4.2）、
  (b) dangling citation の例外送出（R4.3）は upstream に無い。→ 自前の
  `citation.validate_citations()` で「各 `Citation.chunk_id` ∈ 検索済みチャンク集合」
  を検証し、違反は `DanglingCitationError`、引用ゼロは `EmptyCitationError` で
  loud-fail。これが「引用なりすまし」緩和の契約レベル防御（R9.3）。
- **Evidence**: gap-analysis §2 R4.1–4.4 / R9.3。spec R4.2/R4.3/R9.3。

### I-6. 配置に伴うグロブ不一致と mise/CI 明示配線（R11.x / R12.x）

- **Question**: 独立レーン `patterns/rag/`（`frameworks/` 外）をどう配線するか。
- **Findings**: 全 `patterns:{setup,lint,format,typecheck,test,audit}` は
  `for d in patterns/frameworks/*/` ループ。`patterns/contracts/` は**ループ前に明示行**
  `(cd patterns/contracts && uv run …)` を持つ（`set -e` で contracts 失敗が lanes 前に
  停止）。`patterns-ci.yml` は3レーンマトリクスとは別に**専用 `contracts` ジョブ**を持つ。
  → RAG レーンは**この contracts 前例を踏襲**: 各 mise タスクに `(cd patterns/rag && …)`
  を1行（contracts 行の後・frameworks ループの前後いずれか。RAG は contracts に依存し
  lanes には依存しないため**ループ後**に置く）、CI は**専用 `rag` ジョブ**を追加、
  paths トリガに `patterns/rag/**`。`patterns:test:integration` は contracts 行を持たない
  （契約パッケージに integration なし）ため、RAG 用に**明示 rag 行を追加**する。
  root の `extend-exclude=["patterns"]` / pyright `exclude` / pre-commit `exclude: ^patterns/`
  は `patterns/rag/` を自動被覆（ルート無変更 R11.3/R12.2 を満たす）。gitleaks /
  forbid-hardcoded-model-ids はリポジトリ全域（R9.4）。
- **Evidence**: `mise.toml`（contracts 明示行 + frameworks ループ）/ `patterns-ci.yml`
  （`contracts` 専用ジョブ L92-136, matrix L49-90）/ root `pyproject.toml`
  `extend-exclude`・pyright `exclude` / `.pre-commit-config.yaml`。gap-analysis §3.1。

### I-7. 単一点ドリフトテストの拡張（R5.x）

- **Question**: RAG 契約を `test_contract_drift.py` にどう乗せるか。
- **Findings**: `_README_PATHS` に `"rag": _PATTERNS_DIR / "rag" / "README.md"` を追加。
  parser は `class ` 始まりチャンクのみ `ast.parse` し AnnAssign のフィールド名集合 +
  `Literal` 語彙を比較。RAG 契約は `Literal` を持たず単純フィールド（`score: float`
  含む）のみなので素直に被覆。`async def run_rag(query, *, llm, retriever/index)` は
  非 `class` チャンクのためスキップ（routing の `model/llm` 前例と同じ）。
  `test_each_package_model_is_documented_in_exactly_one_readme`（Counter）の one-README
  不変条件を守るため、3モデルは `patterns/rag/README.md` のみに記載する。
- **Evidence**: `patterns/contracts/tests/unit/test_contract_drift.py`
  （`_PATTERNS_DIR=parents[3]` / `_README_PATHS` / `_top_level_chunks` /
  `_collect_model` / one-README Counter）。gap-analysis §3.2。

## Existing patterns to reuse

| Pattern | Location | Why reuse |
|---|---|---|
| 独立 uv レーン雛形 | `patterns/frameworks/llamaindex/{pyproject.toml,.python-version,uv.lock}` | RAG レーンの最近接形（3.13・llama-index-core・OpenInference）。docling 依存を追加して流用 |
| 契約パス依存 import | `[tool.uv.sources] patterns-contracts = { path="../../contracts", editable=true }` | NFR-3。`patterns/rag/` なら相対は `../contracts`（深さ1差）に調整 |
| `observability.py` | `patterns/frameworks/llamaindex/src/patterns_llamaindex/observability.py` | `configure_tracing` + OpenInference `LlamaIndexInstrumentor`（プロセスグローバル）+ `InMemorySpanExporter`。複製で対応（レーン自前コピーが既存規律 R1.3） |
| `CustomLLM` 台本フェイク | `patterns/frameworks/llamaindex/tests/support/fake_llm.py` | `BaseEmbedding` フェイク・台本 LLM の自作手法の前例 |
| 統合ゲート | `tests/integration/test_ollama_e2e.py`（`RUN_INTEGRATION_PATTERNS` + `OLLAMA_*`） | R7.x の env 読取り・契約レベルアサート・`/v1` 接尾辞剥がしまで踏襲 |
| 契約モジュール型 | `patterns/contracts/src/patterns_contracts/routing.py` + `__init__.py` 再エクスポート | `rag.py` 新設 + `__all__` 追記の型 |
| 単一点ドリフト | `patterns/contracts/tests/unit/test_contract_drift.py` | `_README_PATHS` に `"rag"` 1行追加で被覆 |
| mise/CI contracts 前例 | `mise.toml` contracts 明示行 + `patterns-ci.yml` `contracts` ジョブ | `frameworks/` 外レーンの明示配線の唯一前例（最小ドリフト） |
| パターン README 正本 | `patterns/routing/README.md`（`## パターン契約` + ```` ```python ```` 注釈のみブロック） | 正本 fenced block 規約。Field/description は書かずフィールド名のみ |

## External dependencies

| Dependency | Version（方針） | Purpose | Verified |
|---|---|---|---|
| `patterns-contracts` | path（`../contracts`, editable） | RAG 契約の単一実体を import（NFR-3/5） | ✅ 既存規律 |
| `docling-core` | `>=2.82`（実 PoC でピン） | `HybridChunker` / `DoclingDocument.load_from_json` / `ProvenanceItem` | ✅ PyPI + context7 API 確認 |
| `docling`（任意） | 固定資産生成時のみ（runtime 依存にしない） | PDF→DoclingDocument 事前変換（CI 経路外） | ⚠️ ADR-3 で runtime 非依存を確認 |
| `llama-index-core` | `>=0.14`（≥0.12.28 CVE フロア上） | in-memory `VectorStoreIndex` / リトリーバ / `BaseEmbedding` | ✅ CVE-2025-1793 回避（in-memory 既定） |
| `llama-index-embeddings-ollama` | 結合のみ | 実埋め込み（`OllamaEmbedding`、env 駆動） | ⚠️ integration extra として隔離検討（R11.4） |
| `llama-index-llms-ollama` | 結合のみ | 結合 LLM | ✅ llamaindex レーン前例 |
| `openinference-instrumentation-llama-index` + `opentelemetry-sdk` / `-exporter-otlp-proto-http` | llamaindex レーン同等 | 計装（span≥1） | ✅ 複製 |
| `transformers`（任意・トークナイザ） | `docling-core[chunking]` 経由 or 明示ピン | HybridChunker トークナイザ | ⚠️ オフライン調達 PoC（ADR-3 / R-1） |

dev: `pip-audit` / `pyright` / `pytest` / `pytest-asyncio` / `pytest-cov` / `ruff`
（llamaindex レーンと同一）。各 runtime 依存は pyproject に一行 rationale（Constitution III）。

## Architecture decisions

### ADR-1: 配置は独立レーン `patterns/rag/`（Clarifications 確定方向を採用）

- **Context**: Docling は torch を**任意**で引くがトークナイザ（transformers）+ 変換器
  layout モデルで重量化しうる。llamaindex レーンの lockfile / CI 時間 / 責務純度を汚染
  したくない。RAG はワークフロー6パターンではなく**応用レイヤ**でタクソノミーも別。
- **Decision**: `patterns/rag/`（`frameworks/` 外）に独立 uv プロジェクトを新設。
  パッケージ名 `patterns_rag`。最終確定は impl 冒頭 PoC（uv.lock 差分・CI 時間実測）で
  検証し、軽量と判明すれば同居へ倒す余地を残すが、**既定は独立**。
- **Alternatives**: (B) `patterns/frameworks/rag/` 同居 = 配線ゼロだがタクソノミー不整合
  + Clarifications と矛盾。(C) グロブ汎用化 = 既存安定タスク広範改修で回帰リスク大。
- **Consequences**: mise/CI を contracts 前例で**明示配線**（I-6）。observability 複製
  1ファイル。グロブ外配線漏れリスクは contracts 前例の踏襲で緩和。
- **Spike 実測（Task 0, 2026-06-13 / uv 0.11.21, CPython 3.13.7）**: `patterns/rag/`
  PoC（`package=false`、runtime = `patterns-contracts`(path `../contracts`) +
  `docling-core[chunking]>=2.82` + `llama-index-core>=0.14` +
  `llama-index-embeddings-ollama` + `llama-index-llms-ollama` + OpenInference/OTel）を
  解決。結果:
  - **解決パッケージ数 119**（llamaindex レーン 103 → **+16**）。`uv.lock` **240,878 B**
    （llamaindex 209,045 B → **+31,833 B / +約15%**）。
  - **`torch` / `nvidia-*` / `onnxruntime` / `scipy` は ABSENT**（最重量の懸念は不発。
    gap-analysis §3.3 の PyPI 実測を裏付け）。
  - **`transformers 5.8.1` / `tokenizers 0.22.2` / `safetensors 0.8.0` /
    `huggingface-hub 1.19.0` / `numpy 2.4.6` / `pillow 12.2.0` は PRESENT**。invert tree で
    全て **`docling-core[chunking]` 単独経由**（`transformers → docling-core(extra:chunking)
    → patterns-rag-poc[chunking]`）と確認。
  - 解決時間 **2.57s**、cold `uv sync --locked` **7.8s wall**、warm `uv sync --locked`
    再チェック **約2s**（Resolved 119 in 428ms / Checked 116 in 147ms）。
  - 主要版: `docling-core 2.82.0` / `llama-index-core 0.14.22` /
    `llama-index-embeddings-ollama 0.9.0` / `llama-index-llms-ollama 0.10.1`。
- **判断（配置確定）**: **独立レーン `patterns/rag/` を確定**（既定を維持、同居へは倒さない）。
  torch 不在で同居しても CUDA 級肥大は起きないが、同居は HF トークナイザ群
  （transformers/tokenizers/safetensors/numpy/pillow, +16 pkg / +約32KB）を RAG 非利用の
  2 ワークフローパターンが同居する llamaindex レーンの lockfile/CI に注入し責務純度を汚す。
  タクソノミー不整合（応用レイヤ vs ワークフロー6パターン）は重量と独立した却下理由。
  → ADR-1 既定（独立）を実測が**上書きせず確定**。

### ADR-2: RAG 契約を `patterns/contracts/` に単一実体として追加

- **Context**: 006-2a で契約複製を廃止し単一点ドリフトに統一。RAG も同規律に乗せる。
- **Decision**: `patterns_contracts/rag.py` に `RetrievedChunk` / `Citation` /
  `RagAnswer` を定義し `__init__.py` で再エクスポート。正本は `patterns/rag/README.md`
  の `## パターン契約` ```` ```python ```` ブロック（注釈のみ）。`test_contract_drift.py`
  の `_README_PATHS` に `"rag"` 追加。`Literal` 語彙なし・単純フィールドのみ。
- **Alternatives**: レーン内に契約を置く = 006-2a が廃した複製。却下。
- **Consequences**: contracts レーンの fail_under(85) に被覆（宣言のみで全行 import 被覆）。
  既存6パターンの集合比較・one-README 不変条件を壊さない（R5.3）。

### ADR-3: PDF 変換器を固定資産化し、オフラインは HybridChunker のみ実行

- **Context**: 変換器 layout モデルは重量。R6.1（ネット I/O ゼロ）と R6.2（実物
  チャンカー + ゴールデン一致）を両立する必要。
- **Decision**: 固定ドキュメントを**事前変換した `DoclingDocument` JSON**（`*.docling.json`）
  を `tests/fixtures/` にコミットし、オフラインテストは `load_from_json` →
  `HybridChunker.chunk()`（実物）→ ゴールデン比較。変換器（`docling` 本体）は runtime
  依存にせず、固定資産生成スクリプト/手順のみに留める。トークナイザは ADR で定めた
  オフライン調達（I-2: HF キャッシュ事前取得 + `HF_HUB_OFFLINE=1`、退避 = tiktoken）。
- **Alternatives**: 毎テストで PDF 変換 = CI 重量 + 非決定論リスク + ネット I/O。却下。
- **Consequences**: ゴールデン再生成は Docling バージョン更新時のみ手動（差分レビュー必須・
  CI は比較のみ loud-fail、Clarification 4）。固定資産 + ゴールデンの2ファイルを版管理。

### ADR-4: `chunk_id` は決定論的序数から導出、`locator` は種別非依存文字列

- **Context**: Docling API は安定 chunk ID を持たない。引用が実在チャンクを指す
  （R2.3/R4.3）には決定論的 ID が必須。`locator` はドキュメント種別非依存（Clarification 3）。
- **Decision**: HybridChunker の決定論的反復順序の 0-based 序数で
  `chunk_id = f"{source}::{ordinal:04d}"`（source 名前空間化でレーン内一意 R2.3）。
  `locator` は I-1 の優先順位（page → section → char）で文字列化。両者をゴールデンで固定。
- **Alternatives**: 内容ハッシュ ID = 同一テキスト重複チャンクで衝突しうる。序数併記で回避可
  だが序数単独が単純。`bbox` 含む locator = 種別依存で R4.4 違反。却下。
- **Consequences**: 序数はチャンク境界が変われば変動 → ゴールデン再生成で吸収（ADR-3 と整合）。

### ADR-5: 検索順序は `(-score, chunk_id)` の安定ソートで決定論化

- **Context**: R3.3（同点時 `chunk_id` 昇順タイブレーク）で flakiness ゼロ（NFR-2）。
- **Decision**: リトリーバ結果を `sorted(nodes, key=lambda n: (-score, chunk_id))` で
  再整列するポストプロセッサを `retrieval.py` に置く。fake 埋め込み（ADR I-4）と併せ
  top-k 順序を完全固定。
- **Alternatives**: upstream 既定順序依存 = 同点時に非決定論。却下。
- **Consequences**: 自前ポストプロセッサ1関数。結合でも同経路を通す。

## Risks & open questions

- ⚠️ **R-1 トークナイザのオフライン調達**（R6.1）— HF ダウンロードが CI でネット I/O を
  起こすと hermetic 違反。**制約**: rag CI ジョブは contracts ジョブ複製（`uv sync --locked`
  → `pytest`）で `patterns:setup` を経由しないため、「`patterns:setup` で HF 事前取得」は
  CI 経路に適用されない。よって CI のオフライン unit は**ネット事前取得を要さない調達**で
  確定する必要がある。**Spike 合否基準（impl 冒頭で確定）**: (1) `tiktoken` ベースの
  トークナイザ（オフライン同梱）を `HybridChunker` に注入してゴールデンが安定再生成できる
  なら**これを主策に採用**。(2) HF トークナイザしか選べない場合は `uv sync --locked` 後に
  オフラインで解決される形（パッケージ同梱資産）でのみ可とし、それも不可なら rag CI ジョブ
  にのみ明示の事前取得ステップを追加する。いずれの場合も unit は `HF_HUB_OFFLINE=1` を強制し
  実ネット到達を loud-fail させ、`max_tokens` を明示固定して境界を決定論化する。
  - **Spike 実測（Task 0, 2026-06-13）**: 解決閉包に HF トークナイザ群
    （`transformers`/`tokenizers`/`huggingface-hub`）が `docling-core[chunking]` 経由で入る
    一方、**`tiktoken` も llama-index-core 経由で既に PRESENT**。rag CI unit ジョブは
    contracts 前例の `uv sync --locked → pytest` で **`patterns:setup` を経由しない**ため
    退避策(a)の事前取得は当該ジョブで走らない。→ **主策を (b) tiktoken ベースのトークナイザを
    `HybridChunker` に注入する方針へ傾ける**（追加依存ゼロでオフライン同梱）。最終確定は
    ゴールデン安定再生成の可否で Task 3 にて行い、unit は `HF_HUB_OFFLINE=1` を強制する。
- ⚠️ **R-2 Docling 依存重量の CI 実用性**（R11.4 / NFR-6）— uv.lock 肥大・CI 時間増。
  mitigation: 固定資産化（ADR-3）で変換器を経路外に。実埋め込み（OllamaEmbedding）は
  結合専用 extra に隔離し、必要なら RAG 結合を別ジョブ/別ゲートへ（R11.4 が明示許容）。
  impl 冒頭 PoC で uv.lock 差分・`patterns:setup`/CI 時間を実測。
  **結合 CI 供給**: `patterns-integration-ollama.yml` は生成 LLM（`OLLAMA_MODEL_NAME`）に
  加えて埋め込みモデル（`OLLAMA_EMBED_MODEL_NAME`）を env 供給 + pull する必要がある
  （現状 env は生成 LLM 1モデルのみ）。埋め込みモデルの追加 pull が daemon ウォームアップ
  時間を著しく増やす場合は、R11.4 隔離（RAG 専用結合ジョブ）へ倒す判断を PoC で確定。
  - **Spike 判断（Task 0, 2026-06-13）— R11.4 隔離は unit レベルでは非発動**: 実測で
    `torch`/`nvidia-*`/`onnxruntime`/`scipy` 不在、`uv.lock` +約32KB（+16 pkg）、cold sync
    7.8s / warm `--locked` 再チェック 約2s。**オフライン unit CI ジョブ**（contracts 前例の
    `uv sync --locked → pytest`、固定資産ベース、埋め込みモデル不要）には実用的であり、
    **RAG 専用ジョブへの隔離は不要**。**結合**は既存の gated 結合ジョブに RAG を載せ、
    `OLLAMA_EMBED_MODEL_NAME` env + 埋め込みモデル pull を追加（Task 12.3）。埋め込み pull が
    daemon ウォームアップを著しく増やすと**実測された場合のみ** R11.4 の別ジョブ/別ゲートへ
    隔離（Task 12.3 の CI 実測に委譲）。現時点では先取り隔離せず、隔離はドキュメント化済みの
    退避策として保持。
- ⚠️ **R-3 ゴールデン安定性**（R6.2）— Docling/トークナイザ更新でチャンク境界が変動。
  mitigation: バージョンピン + 手動再生成フロー（差分レビュー必須・CI 比較のみ、
  Clarification 4）。固定資産とゴールデンを同時更新。
- ⚠️ **R-4 カバレッジフロア**（R6.5 / NFR-4）— 新規レーンは防御分岐（dangling/empty
  citation, locator 3分岐）が多く初回から 98 が厳しい可能性。mitigation: 兄弟レーン
  parity（98）を目標に設定、PoC で被覆困難な変換器グルーが残れば 85→ratchet で着地し
  rationale を spec/commit に明示。
- ❓ **Q-1 既定 top-k 値** — 実装で定義（R3.1）。固定資産の規模に合わせ impl で確定
  （初期案 k=4、llamaindex レーンの worker 既定と無関係）。
- ❓ **Q-2 OllamaEmbedding モデル名 env** — `OLLAMA_EMBED_MODEL_NAME`（新規 env）。
  `.env.example` 更新要否は結合専用のため要検討（resolve in: impl 結合タスク）。
