# RAG パターン（応用レイヤー / LlamaIndex 役割分担）

検索拡張生成（Retrieval-Augmented Generation）を**唯一の応用レイヤー契約**として
実装する単一レーン（`patterns/rag/`）。Anthropic の6ワークフローパターンとは別系で、
LlamaIndex を「チャンク化（Docling）→ インデックス化 → 検索 → 引用付き生成」の役割分担に
用いる。生成された各 `Citation` が検索済みチャンクの実在 `chunk_id` を指すこと（接地）と、
引用が1件以上あることを**パイプラインが loud-fail で強制**する（捏造・無接地回答を出さない）。

## パターン契約（正本）

契約の実体は依存ゼロの [`patterns_contracts`](../contracts/) パッケージ
（[`rag.py`](../contracts/src/patterns_contracts/rag.py)）。下記の Python コードブロックが
その**正本**であり、
[`patterns/contracts/tests/unit/test_contract_drift.py`](../contracts/tests/unit/test_contract_drift.py)
が両者（クラス集合・フィールド集合）の一致を1点で検証する（Req 5.2, 5.3 / 006-2a NFR-5）。
RAG 契約は閉じた `Literal` 語彙を持たない（ワークフローパターンの `stop_reason`/`Route` 等とは
異なる）。エントリ signature `run_rag` はドキュメント目的で、ドリフト parser はスキップする
（正本一致は pyright strict が担保）。RAG レーンは3型をここからパス依存で import し、
レーン内で再定義しない（NFR-3 / Req 1.3）。

```python
class RetrievedChunk(BaseModel):       # top-k 検索が返す1チャンク（出所アンカー + スコア）
    chunk_id: str       # レーン一意の決定論キー（f"{source}::{ordinal:04d}"）— 引用の接地キー
    source: str         # チャンクの導出元ドキュメント識別子
    locator: str        # 文書種別非依存アンカー（page=3 / section=2.1 / char=120-240、ADR-4）
    text: str           # 回答を接地させる本文
    score: float        # 検索スコア。同点は chunk_id 昇順タイブレーク（R3.3）

class Citation(BaseModel):             # 回答の各主張を裏付ける出所アンカー（実在チャンク必須）
    source: str         # 引用したチャンクのドキュメント識別子
    locator: str        # 引用が参照するソース内アンカー（R4.4）
    chunk_id: str       # 検索済みチャンクの chunk_id。dangling 値は loud-fail（R4.3）
    score: float        # 裏付けチャンクの検索スコア

class RagAnswer(BaseModel):            # RAG 最終出力: 回答 + それを接地する引用（>=1、R4.2）
    answer: str                 # 検索済みチャンクから生成した回答テキスト
    citations: list[Citation]   # 回答を裏付ける引用（>=1 はパイプラインが強制）

async def run_rag(query: str, *, llm, retriever, top_k: int = 4) -> RagAnswer: ...
```

不変条件はフィールド制約ではなく**パイプライン責務**（`patterns_rag.citation` /
`patterns_rag.rag`）で強制する — 契約は依存ゼロの素な形状を保つ:

- **>=1 引用**（Req 4.2）: 引用ゼロの `RagAnswer` は `EmptyCitationError` で loud-fail。
- **dangling 引用**（Req 4.3）: 検索済みチャンクに存在しない `chunk_id` を指す引用は
  `DanglingCitationError` で loud-fail（全違反 id を既知集合と併記して送出）。
- **空インデックス**（plan §Error Handling）: 分岐レスに retrieved=[] → context="" →
  引用ゼロ → `EmptyCitationError` へ自然収束（特別扱いを置かない）。

## パイプライン（単一レーン・LlamaIndex 役割分担）

| 段 | 実装 | 決定論シーム |
|---|---|---|
| チャンク化 | 実物 Docling `HybridChunker`（[`chunking.py`](src/patterns_rag/chunking.py)） | `tokenizer` を DI（unit はオフライン `WordTokenizer`）。`locator` は page→section→char 規約（ADR-4）、`chunk_id=f"{source}::{ordinal:04d}"` |
| インデックス化 | in-memory `VectorStoreIndex`（[`indexing.py`](src/patterns_rag/indexing.py)） | `embed_model` を DI（unit は `HashEmbedding`）。`SimpleVectorStore` を**能動的に明示構築** |
| 検索 | top-k retriever（[`retrieval.py`](src/patterns_rag/retrieval.py)） | `(-score, chunk_id)` 全順序ソートで入力順非依存に決定論化、`top_k<1` は `ValueError` |
| 引用検証 | 集合メンバシップ検証（[`citation.py`](src/patterns_rag/citation.py)） | `chunk_id` のレーン一意性を接地キーに dangling/empty を loud-fail |
| オーケストレーション | `run_rag`（[`rag.py`](src/patterns_rag/rag.py)） | 検索 → プロンプト構築（chunk_id ラベル付与）→ `astructured_predict(RagAnswer)` → `validate_citations` |

## 必須4セクション

### 型安全

- 契約 `RetrievedChunk`/`Citation`/`RagAnswer` は `patterns_contracts` の単一実体。レーンは
  パス依存で import し再定義しない（NFR-3）。pyright **strict**（Python 3.13）で全レーンを検査。
- 構造化出力は LlamaIndex `llm.astructured_predict(RagAnswer, ...)` で `RagAnswer` 契約へ着地。
  非 function-calling フェイクは text-completion program の JSON パーサ経路、実 Ollama は
  tool-call 経路 — 同一契約に収束する。
- 埋め込み・LLM・トークナイザは型付き DI seam。`index.vector_store` 等の上流広域型は
  I/O 境界で `isinstance` narrow してから内側へ流す（`Any` を素通しさせない）。

### テスト

- **オフライン hermetic**（Req 6.1）: 全 unit がネットワーク I/O ゼロで完走。`HF_HUB_OFFLINE=1`
  を pytest env で全 run 強制（tiktoken/HF の DL を回避）。`block_network` フィクスチャが
  AF_INET/AF_INET6 の reach を monkeypatch で loud-fail（飾りでない load-bearing テスト併設）。
- **決定論フェイク**: `WordTokenizer`（語数=トークン数・資産ゼロ）/ `HashEmbedding`
  （sha256→固定次元ベクトル、`PYTHONHASHSEED` 非依存）/ `ScriptedLLM`（プロンプト内ラベルを
  解析し接地引用のみ生成、`dangling_chunk_id` seam で検証の実効性を立証）。
- **ゴールデン回帰**: 事前変換 `sample.docling.json` 固定資産（変換器を CI 経路外へ、ADR-3）を
  チャンク化した `golden_chunks.json` でチャンク境界・`chunk_id`・`locator` を固定（更新は差分
  レビュー必須）。
- **カバレッジゲート**: 兄弟レーン parity で `fail_under=98`（Req 6.5 / NFR-4）。実 Ollama 結合は
  `RUN_INTEGRATION_PATTERNS=1` でゲートし、契約レベル（citations>=1 / 各 citation が既知ソース
  /chunk_id を指す）のみアサート、正確なテキスト一致は禁止（Req 7.2）。

### 可観測性

- 兄弟 llamaindex レーンと揃えた OpenInference `LlamaIndexInstrumentor` をプロセスグローバルに
  着脱（[`observability.py`](src/patterns_rag/observability.py)）。RAG は `VectorStoreIndex`
  リトリーバと LLM が LlamaIndex dispatcher 経由で走るため、検索/LLM スパンを捕捉する。
- exporter 優先チェーン: **注入 > `OTEL_EXPORTER_OTLP_ENDPOINT` > no-op**（Req 8.1）。
  `InMemorySpanExporter` 注入で RAG 実行時に span>=1 と末端 LLM/検索スパンの**存在**を検証する
  （属性集計はバックエンド責務でアサートしない、Req 8.2/8.3）。uninstrument 後の再 run で
  スパン増分ゼロを確認し着脱の実効性を立証。

### セキュリティ

- **ベクタストア**（Req 9.1）: 上流既定に委ねず in-memory `SimpleVectorStore` を能動的に明示
  構築し **CVE-2025-1793 を回避**（外部ベクタ DB を混入させない）。isinstance 固定で上流既定の
  変化を回帰検知する。
- **引用なりすまし / 過度の依存**（OWASP LLM Top 10）: dangling/empty 引用を loud-fail で遮断し、
  無接地・捏造回答の流出を防ぐ（Req 4.2/4.3/9.3）。
- **モデル ID ハードコード禁止**: Ollama の接続/モデルは env 専属（`OLLAMA_BASE_URL` /
  `OLLAMA_MODEL_NAME` / `OLLAMA_EMBED_MODEL_NAME`）。gitleaks / forbid-hardcoded-model-ids は
  `patterns/` 全域を除外しない。
- RAG 固有リスク（インデックス汚染 / 引用なりすまし / PII チャンク露出）→ OWASP LLM Top 10
  の詳細マッピングは [SECURITY-NOTES.md](../SECURITY-NOTES.md)（Task 13.2 で追記）。

## 使用ライブラリとバージョン

| ライブラリ | バージョン | 役割 / 注記 |
|---|---|---|
| `docling-core[chunking]` | 2.82 系 | `HybridChunker` / `DoclingDocument.load_from_json`（ADR-3）。`[chunking]` extra がトークナイザ群を引き込む |
| `llama-index-core` | 0.14 系（**1.0 前のベータ系**） | `VectorStoreIndex` / `SimpleVectorStore` / リトリーバ / `astructured_predict`。API は安定化前のため版を固定追従 |
| `llama-index-embeddings-ollama` | 0.9 系 | 実 Ollama 埋め込み（結合テストのみ） |
| `llama-index-llms-ollama` | 0.10 系 | 実 Ollama 生成（結合テストのみ） |
| `openinference-instrumentation-llama-index` | 4.4 系 | プロセスグローバル instrumentor（OpenTelemetry SDK 連携） |
| `pydantic` | >=2 | 契約モデル基底 |

> **ベータ注記**: `llama-index-core` 0.14.x は 1.0 前の系列で、`astructured_predict` や
> リトリーバ既定の挙動が版間で変わり得る。`uv.lock` で固定し、版更新時はゴールデン
> （`golden_chunks.json`）と in-memory ストア isinstance 固定で回帰を検知する。モデル ID は
> 版に追従して 3〜6か月で変わるため、コードにハードコードせず env 経由で解決する。
