# 007-2b-cross-platform — PDCA Do Phase

`/sdd-impl` 実装ログ。タスクごとに実施・実測・学びを追記する。

---

## Task 0 — Spike: 配置確定 PoC（2026-06-13）

### TDD 適用について

Task 0 は**測定スパイク（決定ゲート）**であり、production コードを生まない。よって
Red→Green→Refactor の対象ではない。検証エビデンスは「決定基準（research.md ADR-1 /
R-1 / R-2 が固定した合否基準）に対する実測値」そのもの。tdd-enforcement の代替として、
依存解決と `uv sync --locked` の成功・実測ログを VERIFY 証跡とする。

### 実施

- `patterns/rag/pyproject.toml`（`package=false` の PoC）+ `.python-version`(3.13) を作成。
  runtime 閉包 = `patterns-contracts`(path `../contracts`, editable) +
  `docling-core[chunking]>=2.82` + `llama-index-core>=0.14` +
  `llama-index-embeddings-ollama` + `llama-index-llms-ollama` + `pydantic>=2` +
  OpenInference/OTel。
- `uv lock` → `uv sync --locked`（cold/warm）→ `uv tree --package transformers --invert`
  で実測。

### 実測値（uv 0.11.21, CPython 3.13.7）

| 指標 | RAG PoC | llamaindex 基準 | 差分 |
|---|---|---|---|
| 解決パッケージ数 | 119 | 103 | +16 |
| `uv.lock` バイト | 240,878 | 209,045 | +31,833 (+約15%) |
| `torch`/`nvidia-*`/`onnxruntime`/`scipy` | **不在** | 不在 | — |
| `transformers`/`tokenizers`/`safetensors`/`numpy`/`pillow` | PRESENT | — | `docling-core[chunking]` 単独経由 |
| `tiktoken` | PRESENT | (llama-index-core 経由) | R-1 退避策(b)が追加依存ゼロで成立 |

- 解決 2.57s / cold `uv sync --locked` 7.8s wall / warm 再チェック 約2s
  （Resolved 119 in 428ms / Checked 116 in 147ms）。
- 主要版: docling-core 2.82.0 / llama-index-core 0.14.22 /
  llama-index-embeddings-ollama 0.9.0 / llama-index-llms-ollama 0.10.1 /
  transformers 5.8.1。
- invert tree: `transformers → docling-core (extra: chunking) → patterns-rag-poc[chunking]`
  （HF 群の引き込み元は `docling-core[chunking]` 単独と確定）。

### 判断（決定ゲート）

1. **配置 = 独立レーン `patterns/rag/` を確定**（ADR-1 既定維持、同居へ倒さない）。
   torch 不在で同居しても CUDA 級肥大はないが、同居は HF 群（+16 pkg / +約32KB）を
   RAG 非利用の 2 ワークフローパターンが同居する llamaindex レーンへ注入し責務純度を
   汚す。タクソノミー不整合（応用レイヤ vs ワークフロー6パターン）も独立の却下理由。
2. **R11.4 隔離 = unit レベル非発動**（R-2）。オフライン unit CI（contracts 前例の
   `uv sync --locked → pytest`、固定資産ベース）に実用的。結合は既存 gated ジョブに
   embed pull を追加（Task 12.3）、daemon 肥大が実測された場合のみ別ジョブ隔離。
3. **R-1 トークナイザ = tiktoken 注入(b)を主策へ**。rag CI unit は `patterns:setup`
   非経由のため事前取得(a)が走らない。`tiktoken` は既に閉包内 → 追加依存ゼロ。最終確定は
   Task 3、unit は `HF_HUB_OFFLINE=1` 強制。

### 学び（Act 候補）

- `docling`（フル変換器）ではなく `docling-core[chunking]` で HybridChunker 経路は充足し、
  torch を一切引かない。ADR-3 の「変換器を固定資産で経路外へ」は runtime 依存を
  `docling-core` のみに保てる前提で正しい。
- `[chunking]` extra が HF スタック（transformers/tokenizers/huggingface-hub）の単独流入元。
  オフライン hermetic（R6.1）の主戦場はここ → Task 1.1/3 で tiktoken 注入を優先実装する。
- PoC `pyproject.toml` は Task 1.1 で正式レーン定義（ruff/pyright/pytest/coverage/dev 群・
  `fail_under`）に上書きされる throwaway。`package=false` は依存閉包の実測専用設定。

---

## Task 1 — RAG レーンの新設と契約パス配線（2026-06-13）

### 実施（TDD: Red→Green→Refactor）

- **1.1** throwaway PoC pyproject を正式レーン定義へ上書き。hatchling build
  (`packages=["src/patterns_rag"]`)、`[tool.uv.sources]` で `../contracts` editable
  パス依存、ruff（llamaindex 等価ルールセット, `known-first-party=["patterns_rag"]`）、
  pyright strict(py3.13)、pytest(asyncio auto)、`[tool.coverage] fail_under=85`(初期フロア)、
  dev 群に **pytest-env** 追加、`[tool.pytest] env=["HF_HUB_OFFLINE=1"]`。`.python-version`
  は PoC 時に uv が生成済みの `3.13` を温存（無変更）。
- **1.2** RED: `tests/unit/test_smoke.py`（import 健全性 + sys.modules ベースの sibling
  レーン非 import 検査）を先行作成し、stale PoC venv で `ModuleNotFoundError:
  patterns_rag` を確認。GREEN: `src/patterns_rag/__init__.py`（scaffold docstring、
  公開再エクスポートは Task 7.3）作成 → `uv sync`（140 pkg, patterns-rag editable build）
  → `uv sync --locked` exit 0（NFR-1 再現性）。

### エラーと根本原因（Refactor 痕跡）

- **pyright strict reportUnusedImport**: 副作用 import の `# noqa: F401` は ruff のみ抑止。
  pyright は別系統で残存。→ 名前束縛を捨てる `importlib.import_module("patterns_rag")` に
  置換して根治（symptom の `# type: ignore` 追加を回避）。
- **ruff format**: 初版の `frozenset({...})` 改行を format 規約が 1 行へ。`ruff format`
  適用で解消。

### VERIFY（検証ゲート証跡）

```
ruff check .          → All checks passed!
ruff format --check . → 2 files already formatted
pyright               → 0 errors, 0 warnings, 0 informations
pytest --cov          → 2 passed / src/patterns_rag/__init__.py 100% /
                        Required 85.0% reached (Total 100.00%)
uv sync --locked      → exit 0
git status            → patterns/rag/** のみ（root 無変更）
```

### 学び（Act 候補）

- patterns/ レーンの「副作用 import を伴う独立性テスト」は `importlib.import_module` が
  pyright strict と両立する正攻法。今後の sibling-isolation テストの定石にする。
- root の `extend-exclude=["patterns"]`（ruff）/ `exclude=["patterns"]`（pyright）により、
  レーン追加は root `mise run check` を構造的に汚さない。R1.4/12.2 は「root ファイル
  無変更 + 除外設定」で機械的に担保でき、毎回 root 全チェックを回す必要はない。

---

## Task 2 — shared-contracts への RAG 契約追加（2026-06-13）

### 実施（Red→Green→Refactor）

- **2.1** RED: `patterns/contracts/tests/unit/test_rag_contracts.py` を先行作成し、
  `ImportError: cannot import name 'Citation' from 'patterns_contracts'` を確認。
  drift テスト（AST/introspection parity）を補完する**振る舞いテスト**として、
  再エクスポート経路・フィールド集合（R4.1）・`RagAnswer`→`Citation` ネスト coercion・
  欠損 `chunk_id`/非数値 `score` の `ValidationError` を検証。GREEN:
  `src/patterns_contracts/rag.py` に `RetrievedChunk{chunk_id,source,locator,text,score}` /
  `Citation{source,locator,chunk_id,score}` / `RagAnswer{answer,citations:list[Citation]}` を
  既存契約と同一スタイル（`from __future__`, `Field(description=...)`, `__all__`）で定義。
- **2.2** `__init__.py` に 3 型 import + `__all__` をアルファベット順維持で追記
  （`Citation`/`RagAnswer`/`RetrievedChunk`）。振る舞いテスト 8/8 green で再エクスポート確認。
- **契約レベル方針**: `RagAnswer.citations` は plain `list[Citation]`。≥1 不変条件（R4.2）・
  dangling loud-fail（R4.3）は依存ゼロ契約ではなく RAG パイプライン（`rag.citation`,
  Task 6/7）の責務として設計どおり分離（plan Components の所有境界に準拠）。

### エラーと根本原因

- **ruff format**: `Field(description=...)` の長文が 100 桁超過 → format が
  `locator`/`chunk_id`/`citations` を複数行へ折返し。`ruff format` 適用で解消（symptom 無視せず）。

### VERIFY（検証ゲート証跡）

```
ruff check .          → All checks passed!
ruff format --check . → 10 files already formatted
pyright               → 0 errors, 0 warnings, 0 informations
pytest tests/unit/test_rag_contracts.py → 8 passed
pytest --cov (lane 全体) → 3 failed, 9 passed / rag.py 100% (17/17) /
                          Required 85.0% reached (Total 100.00%)
```

**3 failed の根本原因（既知の Task 11 結合・修正forward しない）**: `test_contract_drift.py`
は「README 正本 == `patterns_contracts` 実体」の単一点パリティを検証する。RAG 3 型を
パッケージへ追加・再エクスポートした時点で package 側に出現するが、README 正本側
（`patterns/rag/README.md` の正本 fenced block + `_README_PATHS["rag"]` 登録）は **Task 11.1/
11.2**（depends: 2, 7）の所有物。失敗メッセージは `Extra items in the right set:
RetrievedChunk, Citation, RagAnswer` で、package にのみ存在＝README 未記載を正確に示す。
これは DAG の Wave1→Wave5 間に構造的に存在する計画済み RED ウィンドウであり、Task 2 の
成果物欠陥ではない。Task 11 が README 正本を記載・登録した時点で 3 テストは green に閉じる。
Task 2 のスコープ（`rag.py` + `__init__.py`）を越えて README を先行作成すること
（fix-forward）は行わない。

### 学び（Act 候補）

- 契約パッケージへのモデル追加は drift テストを必ず一時 RED にする（README 正本は別タスク
  所有）。タスク順序上、contracts 追加（Wave1）とパターン README/drift 登録（Wave5）の間は
  lane suite が RED であることを前提に、タスク単位ゲートは「当該タスク固有テスト green +
  lint/format/typecheck green + 既知結合の明示」で評価する。
- drift テストの `test_each_package_model_is_documented_in_exactly_one_readme` は
  package→README 方向の網羅を検出するため、再エクスポートを追加した瞬間に発火する。
  これは設計意図どおりの早期検出であり、Task 11 完了で解消する。

---

## Task 3 — Docling HybridChunker によるチャンク化（2026-06-13）

**スコープ**: 3.1 `sample.docling.json` 固定資産 / 3.2 `chunk_document` + `ChunkRecord` +
`derive_locator` / 3.3 `golden_chunks.json`。boundary 4 ファイルのみ（ルート・他レーン無変更）。

### TDD 証跡（Red→Green）

1. **RED**: `tests/unit/test_chunking_golden.py` を先行作成 → `uv run pytest --no-cov` で
   `ModuleNotFoundError: No module named 'patterns_rag.chunking'`（収集エラー）を確認。
2. **GREEN(部分)**: `chunking.py` 実装後、振る舞い 11 テスト green / golden 一致のみ
   `FileNotFoundError: golden_chunks.json`（未生成）で 1 failed。設計どおりの段階。
3. **GREEN(完)**: `chunk_document` 実出力から `golden_chunks.json`（4 チャンク）を生成・
   目視確定（page1 merge / page2 単 / page3 split×2）→ 12 passed。

### 根本原因対応した不具合（blind retry なし）

- **tiktoken 非 hermetic（R-1 確定）**: 当初 Task 0 ノートは tiktoken 注入(b)を主策に傾けて
  いたが、空 cache + 不正 proxy 実測で `cl100k_base` が `openaipublic.blob.core.windows.net`
  へ BPE 表を DL（`ProxyError`）= オフライン CI で不可と判明。→ 根本対処として tokenizer を
  DI seam 化し、unit は資産ゼロの決定論 `WordTokenizer` を注入（HF_HUB_OFFLINE 強制と整合）。
- **semchunk が `get_tokenizer()` を callable 要求**: 初期スタブが `None` 返却で分割時
  `TypeError: first argument must be callable`。→ `get_tokenizer()` が bound counter
  (`self.count_tokens`) を返すよう修正（症状でなく分割経路の契約を満たす）。
- **pyright `reportPrivateImportUsage`**: `DocMeta` を `hierarchical_chunker` から import
  でエラー。→ 正本 `docling_core.transforms.chunker.doc_chunk` へ変更。
- **ruff D301 / UP035 / TCH**: docstring の `\\ ` 擬似 RST・`typing.Callable`・実行時不要
  import を是正（`collections.abc` + `TYPE_CHECKING`）。

### Verification Gate（証跡）

- `uv run pytest --cov` → **14 passed**、`Required test coverage of 85.0% reached.
  Total coverage: 94.83%`（chunking.py 95% / 未被覆は無 prov 退避分岐のみ）。
- `uv run ruff check .` → `All checks passed!` / `ruff format --check .` → 全整形済。
- `uv run pyright` → `0 errors, 0 warnings`。

### 学び（Act 候補）

- 「オフライン動作」と評された依存（tiktoken）も cold cache では DL する場合がある。hermetic
  主張は cache 無効化 + ネットワーク遮断で実測検証してから確定する。DI seam を tokenizer にも
  広げたことで embed/llm と一貫した「実物アルゴリズム + 注入フェイク」の規律が揃った。
- golden テストは「凍結入力(fixture) → 被テストコード → 凍結出力(golden)」の三点で回帰を捉える。
  golden は実装出力から生成しても目視確定 + 差分レビュー必須で循環を断つ。

---

## Task 4 — インデックス化と埋め込み DI seam（2026-06-13）

### TDD 証跡（Red→Green）

- RED: `tests/unit/test_indexing.py` を先行作成 → `ModuleNotFoundError: No module named
  'patterns_rag.indexing'`（被テスト未実装を確認）。
- GREEN: `tests/support/fake_embedding.py`（`HashEmbedding`）と
  `src/patterns_rag/indexing.py`（`build_index`）を実装 → 9 新規テスト green。
- 被覆: HashEmbedding 決定論（インスタンス間一致）/ 固定次元 / 設定次元尊重 / 異テキスト相違、
  build_index のノード生成（id=chunk_id）/ メタ保存（source,locator）/ in-memory
  SimpleVectorStore / 注入モデルでの埋め込み（次元一致）/ 空コーパス。

### 設計判断

- **sha256 採用**: builtin `hash()` は `PYTHONHASHSEED` でプロセス間に揺れ、index 再現性
  （ひいては Task 5 検索順序の決定論）を壊す。content→`hashlib.sha256`→counter ブロック展開で
  machine/run 不変の固定次元ベクトルを生成。資産ゼロ・ネットワークゼロ。
- **in-memory store を能動所有**: 上流既定に委ねず `StorageContext.from_defaults(
  vector_store=SimpleVectorStore())` で明示構築（CVE-2025-1793＝外部ベクタ DB SQLi を範囲外
  に固定, R9.1）。isinstance ピン留めテストで上流既定変化を回帰検知。

### エラーと根本原因（blind retry なし）

- **pyright strict: `BasePydanticVectorStore` に `.data` 無**: `index.vector_store` の静的型は
  基底で、`.data.embedding_dict` 直アクセスが 8 error。→ 症状抑止（ignore）でなく
  `assert isinstance(vs, SimpleVectorStore)` で narrow し、`embedding_dict`
  （`dict[str,list[float]]`）へ型安全到達（Task 3 の DocMeta narrow と同型の正攻法）。
- **ruff format**: `build_index` シグネチャ整形差分 1 件 → `ruff format` で吸収。

### Verification Gate（証跡）

- `uv run pytest --cov`（lane, HF_HUB_OFFLINE=1）→ **23 passed**、`Required test coverage of
  85.0% reached. Total coverage: 95.59%`（indexing.py 100%）。
- `uv run ruff check .` → `All checks passed!` / `ruff format --check .` → 全整形済。
- `uv run pyright` → `0 errors, 0 warnings`。
- ※ mise `patterns:*` は `patterns/frameworks/*` のみ走査（rag レーン配線は Task 12）。
  本タスクはレーン自身のゲートを `uv run` で直接実行（Task 1〜3 と同手順）。

### テスト配置の補足（boundary 整合）

- 主タスク boundary は `indexing.py` / `fake_embedding.py` の2点だが、`/sdd-impl` の TDD 必須
  と 4.2「テストを先行作成」に従い `tests/unit/test_indexing.py` を新設。boundary の欠落は
  計画の取りこぼし（4.2 が明示的にテスト先行を要求）であり、最小・正当な追加と判断。

### 学び（Act 候補）

- フェイクの決定論は「アルゴリズムの決定論」だけでなく「ハッシュ源の決定論」も要件。builtin
  `hash()` の塩は再現性の隠れた破壊要因で、フェイク実装では hashlib 系で固定するのが定石。
- 「既定が安全」でも能動的に所有して回帰テストで固定すると、上流の既定変更で安全性が静かに
  失われる事故（CVE 回避の無効化）を防げる。

---

## Task 5 — 検索と決定論順序（2026-06-14）

### TDD 証跡（Red→Green）

- RED: `tests/unit/test_retrieval_determinism.py` を先行作成 → `ModuleNotFoundError: No
  module named 'patterns_rag.retrieval'`（被テスト未実装を確認）。
- GREEN: `src/patterns_rag/retrieval.py`（`retrieve` + 純ヘルパ `_score_of` /
  `_to_retrieved_chunk`）を実装 → 9 新規テスト green。
- 被覆: 降順スコア順序 / 同点 `chunk_id` 昇順タイブレーク（ADR-5 中核）/ 入力順非依存
  （forward==reversed）/ `top_k` 切詰 / 件数超過時の全件返却 / `top_k<1` ValueError（0・負を
  parametrize）/ node metadata→`RetrievedChunk` 復元 / score=None の 0.0 既定化。

### 設計判断

- **全順序キー `(-score, chunk_id)`**: `chunk_id` がレーン一意なので同点は完全決定論。
  Python の安定ソートに依存せず入力順非依存を保証（forward/reversed 二経路テストで固定）。
  upstream 既定順序依存（同点非決定論）は ADR-5 が却下済み。
- **score=None の 0.0 既定化**: 実リトリーバは `None` を返し得る。`-None` は `TypeError` で
  sort を壊すため `_score_of` で防御。無スコアは正スコア群の下に着地し、契約 `score`（必須
  float）にも同値を充当。範囲外（locator 意味検証など）は抱えず、metadata 欠落は自然
  `KeyError`=loud-fail。
- **契約はパス依存 import**: `RetrievedChunk` を `patterns_contracts` から import（レーン内
  再定義しない, NFR-3）。indexing.py の `BaseEmbedding` seam と同じ規律。

### エラーと根本原因（blind retry なし）

- **pyright strict: `super().__init__()` reportUnknownMemberType**（テスト stub
  `_StubRetriever`）: 上流 `BaseRetriever.__init__` が untyped（`Dict` 型引数なし）のため strict
  が型を解決不能。→ runtime では `callback_manager` 初期化に必須（`retrieve()` が依存）のため
  呼出は残し、原因を明記した局所 `# pyright: ignore[reportUnknownMemberType]` で解消。症状抑止
  でなく上流の型欠落を明示する正攻法（Task 4 の isinstance narrow と同じ「ignore を撒かず原因に
  当てる」規律）。
- **ruff I001（import 未整序）**: `patterns_contracts`（path dep=third-party 扱い）と
  `patterns_rag`（first-party）の群分け差分 → `ruff check --fix` で吸収。

### Verification Gate（証跡）

- `uv run --active ruff check .` → `All checks passed!`
- `uv run --active ruff format --check .` → `9 files already formatted`
- `uv run --active pyright` → `0 errors, 0 warnings, 0 informations`
- `HF_HUB_OFFLINE=1 uv run --active pytest --cov`（lane）→ **32 passed**、
  `Required test coverage of 85.0% reached. Total coverage: 96.47%`（retrieval.py 100%）。
- ※ mise `patterns:*` は rag レーン未配線（Task 12）。本タスクはレーン自身のゲートを
  `uv run --active` で直接実行（Task 1〜4 と同手順）。

### 学び（Act 候補）

- 「決定論順序」はソートキーだけでなくキー構成要素の一意性で担保される。`chunk_id` を第2キーに
  据えたことで安定ソート非依存の全順序になり、入力順を意図的に攪乱したテスト（forward/reversed）
  で初めてその性質を証跡化できる。順序テストは「正解列の一致」だけでなく「攪乱入力でも不変」で
  二重に締める。
- 上流フェイク基底の `__init__` が untyped な場合、strict pyright は call 側を partial-unknown
  と判定する。narrowing で潰せない種類のため、原因明記の局所 ignore が正当な落とし所（ignore
  禁止ではなく「無根拠 ignore 禁止」が規律）。

---

## Task 6 — 引用検証と loud-fail（2026-06-14）

### TDD 証跡（Red→Green）

- **RED**: `test_dangling_citation.py`（7 件）/ `test_citation_soundness.py`（4 件）を先行作成。
  `uv run pytest tests/unit/test_dangling_citation.py tests/unit/test_citation_soundness.py`
  → `ModuleNotFoundError: No module named 'patterns_rag.citation'`（collection error 2 件）。
- **GREEN**: `citation.py` 実装後、対象 2 ファイル **11 passed**。lane 全体 **43 passed**。
- **REFACTOR**: 実装は純検証で追加整理不要。`ruff format` が soundness テストの 1 行を整形
  （RetrievedChunk 引数の多行化）。

### 設計判断

- **健全性キー = `chunk_id` 集合メンバシップ**: `chunk_id` がレーン一意（`f"{source}::{ordinal:04d}"`）
  のため、grounded 判定は `known = {c.chunk_id for c in retrieved}` への所属で必要十分。契約
  （`RetrievedChunk`/`Citation`/`RagAnswer`）は依存ゼロのまま、不変条件はパイプライン責務という
  Task 2 の所有境界を踏襲。
- **例外階層 `CitationError` 基底 + 2 サブクラス**: Task 7 オーケストレータが `except CitationError`
  で empty/dangling を一括捕捉できる seam。plan §rag.citation の「例外型定義を owns」に対応。
- **チェック順序（empty→dangling）**: 空回答 ∩ 空 retrieved の交差で EmptyCitationError を優先。
  plan §Error Handling「空インデックス→引用不能→EmptyCitationError」と整合。順序をテストで固定。
- **loud-fail の情報量**: dangling は最初の 1 件で打ち切らず `sorted({...})` で全違反 id と既知集合を
  併記送出（なりすまし調査の足場）。R9.3「引用なりすまし緩和」の運用価値を実装に反映。

### エラーと根本原因（blind retry なし）

- **ruff format diff（症状）**: soundness テストの `RetrievedChunk(...)` 単行が 100 桁超。
  根本原因＝行長規約（line-length=100）。`ruff format` で多行化し吸収（lint/pyright は当初から green、
  format のみの差分）。型エラー・テスト失敗はゼロで、blind retry の対象事象なし。

### Verification Gate（証跡）

- `uv run ruff check .` → `All checks passed!`
- `uv run ruff format --check .` → `12 files already formatted`
- `uv run pyright` → `0 errors, 0 warnings, 0 informations`
- `uv run pytest --cov`（lane, `HF_HUB_OFFLINE=1`）→ **43 passed**、
  `Required test coverage of 85.0% reached. Total coverage: 97.06%`（citation.py 100%）。
- ※ mise `patterns:*` は rag レーン未配線（Task 12）。レーン自身のゲートを `uv run` で直接実行
  （Task 1〜5 と同手順）。boundary 3 ファイルのみ、ルート・他レーン無変更。

### 学び（Act 候補）

- 「契約レベル防御」は契約モデルにフィールド制約を盛るのではなく、依存ゼロ契約 ＋ 別モジュールの
  検証関数で表現するのが本リポジトリの分業。Task 2 で「不変条件は契約でなくパイプライン責務」と
  分離した設計が Task 6 でそのまま `validate_citations` に着地し、所有境界の事前宣言が後続実装の
  迷いを消すことを再確認。
- loud-fail は「最初の違反で止める」より「全違反を集約報告」する方が、セキュリティ系（なりすまし）
  では調査コストを下げる。例外メッセージの情報設計もテストで固定対象に含める。

---

## Task 7 — run_rag エントリのオーケストレーション（2026-06-14）

### TDD 証跡（Red→Green）

- 先行作成: `tests/support/fake_llm.py`（`ScriptedLLM`, 7.1）+ `tests/unit/test_rag_answer_contract.py`（7 テスト, 7.2）。
- RED: `uv run pytest --no-cov tests/unit/test_rag_answer_contract.py`
  → `ModuleNotFoundError: No module named 'patterns_rag.rag'`（collection error, 想定どおり）。
- GREEN: `src/patterns_rag/rag.py`（`run_rag` + `_format_context` + `_RAG_TEMPLATE`）実装
  → 7 passed。`__init__.py`（7.3）フラット再エクスポート後も lane 50 passed。

### 設計判断

- **構造化出力 seam**: 兄弟 `llamaindex` レーンと同一の `astructured_predict(RagAnswer, template, **args)`
  慣用句を採用（NFR-3 レーン規律）。非 function-calling フェイクは text-completion program の JSON
  パーサ経路、実 Ollama は tool-call 経路 — 双方が同一 `RagAnswer` 契約に着地。実装前に spike で
  `list[Citation]` ネスト解析・空 context・ゼロネットワークを実証（無駄な RED→GREEN サイクル回避）。
- **空インデックスを分岐レスに**: `run_rag` に `if not retrieved` の特別扱いを置かず、retrieved=[]
  → context="" → 引用ゼロ → `validate_citations` が `EmptyCitationError`。plan §Error Handling の
  「空インデックス→引用不能→EmptyCitationError」と構造的に一致し、検証点を1つに集約。
- **`top_k<1` の重複防御を置かない**: `retrieve` 既に `ValueError` を送出するため `run_rag` は継承。
  境界防御の単一所有（retrieval）を維持。
- **`ScriptedLLM` は接地のみ生成**: プロンプトのチャンクラベルを正規表現解析して引用を構築し、捏造
  しない。`dangling_chunk_id` seam で未検索 id を注入でき、`run_rag` の `validate_citations` が
  飾りでなく実効的に loud-fail することをテストで立証。

### エラーと根本原因（blind retry なし）

- **ruff isort + format diff（症状）**: `rag.py` の import 並び（`__all__` 直前ブロック）と
  `rag.py`/test の行整形が規約差分。根本原因＝import 整序規約と line-length=100。`ruff check --fix`
  + `ruff format` で吸収（pyright は当初から 0 errors、lint/format のみの機械的差分）。型・テスト
  失敗はゼロで blind retry 対象事象なし。

### Verification Gate（証跡）

- `uv run ruff check .` → `All checks passed!`
- `uv run ruff format --check .` → `15 files already formatted`
- `uv run pyright` → `0 errors, 0 warnings, 0 informations`
- `uv run pytest --cov`（lane, `HF_HUB_OFFLINE=1`）→ **50 passed**、
  `Required test coverage of 85.0% reached. Total coverage: 97.54%`（rag.py 100% / __init__.py 100%）。
- ※ mise `patterns:*` は rag レーン未配線（Task 12.1 所有）。レーン自身のゲートを `uv run` 直接実行。
  boundary 4 ファイルのみ、ルート・他レーン無変更。

### 学び（Act 候補）

- 構造化出力フェイクは「事前 spike で end-to-end を 1 回確認」してから TDD に入ると、program パーサ
  経路の不確実性（ネスト解析・出力スキーマ混入による誤マッチ）を RED 前に潰せる。spike は本体の
  設計判断（プロンプトラベル形式 ＝ フェイクの解析契約）も同時に確定させる。
- DAG の計画済みギャップは「未配線 ＋ 後続所有者を明記」で前進（fix-forward しない）。Task 7.3 の
  tracing 再エクスポートは observability（Task 8）未着地のため意図的に欠落 — Task 2 の README ドリフト
  窓と同型。所有境界を Implementation Notes に明記して後続合流点を残す。

---

## Task 8 — 可観測性の配線（2026-06-14）

### 実装サマリ

- **boundary 2 ファイル**: `src/patterns_rag/observability.py`（新規）/
  `tests/unit/test_observability.py`（新規）。ルート・他レーン・`__init__.py` 無変更。
- **RED→GREEN**: `ModuleNotFoundError: patterns_rag.observability`（5 テスト collection error）
  → observability.py 実装で 5/5 green。

### 設計判断

- **NFR-3 レーン自前コピー**: 兄弟 `llamaindex` レーンの observability を vendoring せず同一契約を
  自前実装（Constitution III「vendoring 禁止」と整合）。`configure_tracing(exporter=None)` /
  `instrument_llamaindex` / `uninstrument_llamaindex` の3公開関数。RAG は LlamaIndex 上で走るため
  OpenInference `LlamaIndexInstrumentor`（プロセスグローバル）が検索/LLM スパンを捕捉する。
- **優先チェーン3段を独立テストで全被覆（R8.1）**: no-op（env 未設定で OTLP 非構築）/ 注入>env
  （endpoint 設定下でも注入 exporter 着地・OTLP 短絡）/ env>no-op（endpoint のみで OTLP 構築）。
  env 分岐は実 `OTLPSpanExporter` を記録スパイ `_RecordingOTLPExporter(SpanExporter)` へ monkeypatch
  し、`from … import` の呼出時解決を利用してネットワークゼロで発火のみ立証。`provider.shutdown()` で
  BatchSpanProcessor ワーカーを join。
- **末端スパン存在のみ（R8.2/8.3）**: instrument→実 `run_rag`→span≥1、名前に "llm"/"complete"
  （末端 LLM）と "retriev"（末端検索）の存在を確認。属性集計は非アサート（バックエンド責務・二重計上
  回避、兄弟レーンと同一判定形状）。着脱の実効性は「uninstrument 後の再 run で同 exporter 増分ゼロ」で立証。
- **`__init__` tracing 再エクスポートは boundary 外**: Task 8 の `_Boundary:_` は observability.py /
  test の2点のみ。Task 7.3 が予告した「合流」は __init__.py（Task 7.3 所有）の再開を要し、本タスク境界に
  含まれず、トップレベル import を要求するテストも無いため未変更とした（境界規律を優先）。

### エラーと根本原因（blind retry なし）

- **ruff format 行折返し（症状）**: `_chunks()` の `ChunkRecord(...)` 行が line-length=100 超過。
  根本原因＝整形規約。`ruff format` で吸収（pyright は当初から 0 errors、機械的差分のみ）。型・テスト
  失敗ゼロ、blind retry 対象事象なし。

### Verification Gate（証跡）

- `uv run ruff check .` → `All checks passed!`
- `uv run ruff format --check .` → `17 files already formatted`
- `uv run pyright` → `0 errors, 0 warnings, 0 informations`
- `uv run pytest`（lane, `HF_HUB_OFFLINE=1`）→ **55 passed**、coverage **98%**
  （observability.py 100% = 21 stmts・4 branch 全被覆 / rag.py 100%, gate 85）。
- ※ mise `patterns:*` は rag レーン未配線（Task 12.1 所有）。レーン自身のゲートを `uv run` 直接実行。

### 学び（Act 候補）

- スパン名アサートは「TDD 前に instrumentor を inline 配線した throwaway スパイクで実測」してから固定
  すると、上流の命名（`VectorIndexRetriever.retrieve` / `ScriptedLLM.complete`）に対する推測 RED を
  回避できる。Task 7 の構造化出力スパイクと同型の de-risk。
- 着脱（attach/detach）テストは「detach 後に別 provider/exporter で空を確認」では弱い（instrumentor は
  元 provider に紐付くため失敗を捕捉できない）。「同一 exporter のスパン増分ゼロ」で計測すると
  uninstrument の実効性を真に立証できる。
