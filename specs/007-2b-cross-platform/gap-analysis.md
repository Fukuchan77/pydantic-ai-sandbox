# 007-2b-cross-platform — 実装ギャップ分析

> `/sdd-validate-gap` 生成。承認済み要件（未承認）と既存コードベースの差分を
> 整理し、`/sdd-plan` の意思決定材料を提供する。**決定ではなく情報と選択肢**を
> 並べる（gap-analysis.md フレームワーク準拠）。
>
> 調査日: 2026-06-13 / 一次情報の最終検証は `/sdd-plan` の `research.md` に委譲。

## 1. 分析サマリ

- **基盤は揃っている**: 005/006-2a が確立した規律（独立 uv レーン・`patterns/contracts/`
  パス依存・単一点ドリフト・per-lane テスト三層・OpenInference 計装・mise/CI 二系統）は
  そのまま流用でき、RAG は**初の応用レイヤ**として既存型に積める。最も近い参照実装は
  **llamaindex レーン**（クエリエンジン・`CustomLLM` フェイク・`observability.py` が再利用形）。
- **最大の具体的統合課題は配置に伴う「グロブ不一致」**: 全 `mise run patterns:*` タスクと
  `patterns-ci.yml` マトリクスは `patterns/frameworks/*/` を前提にハードコードされている。
  Clarifications で方向確定した **独立レーン `patterns/rag/`** はこのグロブ外に落ちるため、
  contracts パッケージと同じく**明示配線**が必須（R12.1 / R11.1）。
- **Docling は torch 必須ではない**（PyPI 実測）: `docling-core` の `transformers` は
  `chunking` extra 経由の任意依存、`torch` は直接依存に出てこない。重量の主因は
  HybridChunker のトークナイザ（transformers）と PDF 変換器の layout モデル。**事前変換した
  DoclingDocument を固定資産化**すれば CI から変換器の重量を排除できる（Clarification 2 の退避策）。
- **新規ビルドが要るのは3点**: ①ハッシュベース fake 埋め込み（`BaseEmbedding` 派生）、
  ②引用抽出 + dangling citation loud-fail（R4.3 の契約レベル防御）、③ゴールデンスナップショット
  基盤（固定文書＋スナップショット＋手動再生成フロー）。いずれも既存レーンに前例なし。
- **推奨方向**: 独立レーン `patterns/rag/`（Clarifications 確定）を前提に、mise/CI は
  **contracts ジョブの前例**を踏襲して明示配線。最終確定は `/sdd-plan` の PoC（uv.lock 差分・
  CI 時間実測）に委ねる。

## 2. 要件別ギャップ表

凡例: ✅ 既存で充足 / 🔧 既存を拡張 / 🆕 新規ビルド

| Req | 必要能力 | 区分 | 根拠・既存資産 |
|---|---|---|---|
| R1.1 独立 uv プロジェクト新設 | 🔧 | `patterns/frameworks/llamaindex/pyproject.toml` を雛形に新レーン。ただし配置は `frameworks/` 外（`patterns/rag/`）で要 PoC 確定 |
| R1.2 contracts をパス依存 import | ✅ | 既存規律: `[tool.uv.sources] patterns-contracts = { path="../../contracts", editable=true }`（llamaindex pyproject）。`patterns/rag/` なら相対パスは `../contracts` |
| R1.3 レーン間 import 禁止 | ✅ | 既存 NFR-3。`observability.py` 等は**複製**で対応（各レーン自前コピーが既存パターン） |
| R1.4 ルートワークフロー無変更 | ✅ | root `pyproject` の `extend-exclude` が `patterns/` を除外済み。`patterns/rag/` も同除外配下 |
| R2.1–2.3 HybridChunker チャンク化 + メタデータ | 🆕 | Docling 未導入。`docling-core` のチャンキング API（`source`/`locator`/`chunk_id` を `DocChunk.meta` から決定論導出） |
| R3.1 ベクトルインデックス + top-k | 🆕 | llama-index-core のインデックス/リトリーバは既存依存だが RAG 用途は未使用。CVE-2025-1793（ベクトルストア統合）が**ゲート条件**として SECURITY-NOTES に記録済み |
| R3.2 埋め込み DI seam | 🆕 | LlamaIndex `BaseEmbedding` 派生のハッシュ fake（オフライン）/ 実埋め込み（結合）。既存 `fake_llm.py` の `CustomLLM` 自作と同型の手法 |
| R3.3 決定論的検索順序（同点 chunk_id 昇順） | 🆕 | タイブレークは自前ポストプロセッサ。既存に前例なし |
| R4.1–4.4 引用付き回答契約 + dangling loud-fail | 🆕 | `RagAnswer`/`Citation`/`RetrievedChunk` を contracts に追加。引用健全性検証は新規。LlamaIndex `CitationQueryEngine` は出発点だが loud-fail は自前 |
| R5.1 contracts に RAG モデル追加 + 再エクスポート | 🔧 | `patterns/contracts/src/patterns_contracts/rag.py` 新設 + `__init__.py` の `__all__` 追記（既存6モジュールと同型） |
| R5.2 README 正本 + ドリフト検証 | 🔧 | `test_contract_drift.py` の `_README_PATHS` に `"rag"` 追加。正本 fenced block 規約は routing README と同型（エントリ signature `retriever/index` は parser スキップ対象） |
| R5.3 既存6パターン非破壊 | ✅ | ドリフトテストは集合比較。新モデル追加は既存集合を壊さない（one-README 不変条件に注意） |
| R6.1–6.5 オフライン hermetic テスト | 🆕 | チャンカー実物 + fake 埋め込み/LLM + ゴールデンスナップショット + 引用健全性/dangling 検出。既存 unit 三層構造に乗るが中身は新規 |
| R7.1–7.3 Ollama 結合（契約レベル） | 🔧 | `tests/integration/test_ollama_e2e.py` の `RUN_INTEGRATION_PATTERNS` ゲート + `OLLAMA_*` env 読取りパターンを流用。埋め込みモデル設定の env 追加が必要 |
| R8.1–8.3 可観測性（span≥1） | 🔧 | llamaindex `observability.py`（OpenInference + `configure_tracing` + `InMemorySpanExporter`）を複製。クエリエンジン経路でスパンが出る |
| R9.1 SECURITY-NOTES に RAG リスク追記 | 🔧 | 既存 SECURITY-NOTES に RAG 行追加（インデックス汚染/引用なりすまし/PII）。CVE-2025-1793 ゲート条件も実体化 |
| R9.2 pip-audit を dev 依存 + mise/CI | ✅→🔧 | 既存 `patterns:audit` パターン。新レーンの明示配線が必要（§3 の課題と同根） |
| R9.3 dangling 禁止＝契約防御 | 🆕 | R4.3 と同実装 |
| R9.4 gitleaks/model-id フックが patterns/ 除外なし | ✅ | `.pre-commit-config.yaml`: 品質フックは `exclude: ^patterns/` だが gitleaks/forbid-hardcoded-model-ids は**リポジトリ全域**。新レーンも自動的に被覆。不変条件を壊さなければ充足 |
| R10.1–10.3 パターン README 4セクション + 索引 + バージョン注記 | 🔧 | routing README の「正本＋必須4セクション」型を流用。`patterns/README.md` に**応用レイヤ別セクション**を新設（ワークフロー6パターン表とは分離） |
| R11.1–11.4 CI 反映 | 🔧 | `patterns-ci.yml` に **dedicated `rag` ジョブ**（`contracts` ジョブが前例）+ paths トリガ追加。`patterns-integration-ollama.yml` は mise 経由のため §3 解決で自動被覆 |
| R12.1–12.2 mise タスク反映 + ルート無変更 | 🔧 | §3 の核心。全 `patterns:*` タスクに RAG レーンを明示追加 |

## 3. 統合課題（最重要）

### 3.1 グロブ不一致 — 配置が `frameworks/` 外であることの帰結

`mise.toml` の全 `patterns:{setup,lint,format,typecheck,test,audit,test:integration}` は
`for d in patterns/frameworks/*/` でループする（[mise.toml:75](../../mise.toml#L75) 他）。
`patterns-ci.yml` のマトリクスも `lane: [pydantic-ai, beeai, llamaindex]` と
`working-directory: patterns/frameworks/${{ matrix.lane }}` をハードコード。

→ **独立レーン `patterns/rag/` はこのグロブ・マトリクス外に落ち、何も実行されない。**
ただし前例は既にある: `patterns/contracts/` も `frameworks/` 外で、各 mise タスクは
ループの**前に明示行**（`(cd patterns/contracts && …)`）を持ち、CI は専用 `contracts`
ジョブを持つ。RAG レーンは**この contracts 前例を踏襲**するのが最小ドリフト。

| 選択肢 | mise/CI コスト | 整合性 |
|---|---|---|
| A. `patterns/rag/` 独立 + contracts 流の明示配線 | 各タスクに1行 + CI 1ジョブ追加 | Clarifications 確定方向と一致。重量隔離 |
| B. `patterns/frameworks/rag/` に置く | グロブ・マトリクスに自動的に乗る（配線ゼロ） | RAG は「フレームワーク」ではなく**応用レイヤ**でありタクソノミー不整合。Clarifications の `patterns/rag/` と矛盾 |
| C. グロブ汎用化（`patterns/*/` へ拡大） | 全タスク改修 + contracts 二重実行回避が要 | 既存安定タスクへの広範な変更。回帰リスク大 |

### 3.2 ドリフトテストの拡張点

`test_contract_drift.py` の `_README_PATHS`（[L49-56](../../patterns/contracts/tests/unit/test_contract_drift.py#L49)）は
6パターンのハードコード dict。`_PATTERNS_DIR = parents[3]`（= `patterns/`）なので
`"rag": _PATTERNS_DIR / "rag" / "README.md"` を追加すれば `patterns/rag/README.md` に解決する。
RAG 契約は `Literal` 語彙を持たず単純フィールドのみ（`score: float` 含む）なので、
AnnAssign フィールド集合比較でそのまま被覆される。エントリ `run_rag(query, *, llm, retriever/index)`
は `async def` かつ非 Python の `retriever/index` を含むが、parser は class/assignment チャンクのみ
ast.parse し `async def` をスキップするため routing の `model/llm` と同様に問題ない。

### 3.3 Docling 依存重量（PoC 実測対象）

PyPI 実測（2026-06-13）:
- `docling` 2.102.x は `docling-slim[standard]` へ再編。`requires-python <4.0,>=3.10`（3.13 レーンと両立）。
- `docling-core` 2.82.0: コア依存は pydantic/pandas/pillow 等。**`transformers` は `chunking` extra 経由の任意依存、`torch` は直接依存に非出現**。

→ 重量の主因は (a) HybridChunker のトークナイザ（transformers、torch を**任意**で引く）、
(b) PDF→DoclingDocument 変換器の layout モデル（重量）。**事前変換済み DoclingDocument JSON を
固定資産としてコミット**し、オフラインテストは HybridChunker のみ実行すれば変換器の重量を
CI から排除できる（Clarification 2 の退避策の具体形）。uv.lock 差分・CI 時間の最終実測は
`/sdd-plan` の PoC へ。

## 4. アプローチ選択肢（フィーチャ全体）

| アプローチ | 適合条件 | コスト | リスク |
|---|---|---|---|
| **独立レーン `patterns/rag/`（推奨方向）** | Docling 依存が重量 / llamaindex レーンの責務純度を保つ | 中（mise/CI 明示配線・observability 複製） | 配線漏れ（グロブ外）。contracts 前例で緩和 |
| llamaindex レーン同居 | PoC で Docling が軽量と判明した場合のみ | 低（配線ゼロ） | lockfile/CI 汚染・責務混在。Clarifications 方向と逆行 |
| ハイブリッド（独立レーン + 重量依存は結合ジョブのみ） | 変換器が CI 非実用と実測された場合 | 中〜高（フィクスチャ二系統） | テスト経路の分岐複雑化。R11.4 が明示的に許容 |

依存重量・テスト経路（チャンカー実物の置き場）は**独立レーン採用後**も残る判断であり、
配置の二択とは直交する点に注意。

## 5. `/sdd-plan` で深掘りすべき研究項目（research.md）

1. **Docling 現行 API**: `docling-core` の `HybridChunker` / `DocChunk.meta` から
   `source`/`locator`/`chunk_id` を決定論導出する正確な属性パス（page/section/char の
   locator 文字列化規約）。バージョンピン。
2. **依存ツリー実測**: `patterns/rag/` で `uv add docling llama-index-core …` した後の
   uv.lock 差分サイズ・torch 引き込み有無・`mise run patterns:setup` / CI 実行時間。
   → 配置の最終確定（R1.1）と R11.4 隔離判断の根拠。
3. **HybridChunker のトークナイザ調達**: オフライン決定論のためトークナイザを事前同梱/
   ピンできるか（HF ダウンロードが CI でネットワーク I/O を起こさないこと、R6.1）。
4. **ゴールデンスナップショット安定性**: Docling バージョン更新でチャンク境界が変わる
   際の手動再生成フロー（差分レビュー必須・CI 比較のみ）の具体ファイル設計。
5. **fake 埋め込みの近傍順序固定**: ハッシュベクトルで top-k 順序が決定論化し、
   同点時 `chunk_id` 昇順タイブレーク（R3.3）が flakiness を排除することの検証。
6. **CVE-2025-1793 ゲート**: 採用するベクトルインデックス実装が脆弱な8統合に該当しないこと
   （in-memory `VectorStoreIndex` 既定なら回避可）の確認 + SECURITY-NOTES 更新。

## 6. 文書ステータス

gap-analysis.md フレームワーク（要件マッピング → 既存コード調査 → 区分 → 統合課題 →
アプローチ比較 → 研究フラグ）に沿って完了。Docling は PyPI 一次メタデータまで確認、
深掘りは `research.md` へ委譲（spec 冒頭注記と整合）。

## 7. 次ステップ

- `/sdd-plan 007-2b-cross-platform` で技術プラン + `research.md`（上記6項目の一次検証）を生成。
  PoC で配置（R1.1）と依存重量（R11.4）を実測確定する。
- または `/sdd-plan 007-2b-cross-platform -y` で要件を自動承認して直行。
