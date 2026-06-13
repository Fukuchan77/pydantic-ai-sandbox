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
