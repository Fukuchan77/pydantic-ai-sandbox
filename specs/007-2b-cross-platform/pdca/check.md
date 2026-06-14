# Check Phase — 007-2b-cross-platform

PDCA Check: 実装結果（Do）を計画（Plan）と照合する。`/sdd-reflect` が
`/sdd-validate-impl`（GO 判定）の検証結果を基に生成。

## Expectations vs. Results

| Expectation (from plan) | Result (from do) | Status |
|-------------------------|------------------|--------|
| 独立レーン `patterns/rag/`（frameworks 外）を新設し契約をパス依存 import | 13 タスク完了・`patterns_rag` 7 モジュール着地・`../contracts` パス依存 | ✅ |
| Docling `HybridChunker`（実物）でオフライン決定論チャンク化 + golden 回帰 | `chunk_document` + `golden_chunks.json`、tokenizer のみフェイク注入 | ✅ |
| RAG 契約3型を `patterns/contracts/` に単一実体追加・単一点ドリフトに乗せる | `rag.py` 3型 + 再エクスポート、`_README_PATHS["rag"]` 登録、drift 4 passed | ✅ |
| dangling/empty citation を契約レベルで loud-fail | `validate_citations` + `DanglingCitationError`/`EmptyCitationError` | ✅ |
| 全 unit ネット I/O ゼロ・`fail_under` を兄弟 parity(98) へ ratchet | hermetic ガード装着・gate 98 を実カバレッジ **100%** で充足 | ✅ |
| OpenInference 計装で span≥1・末端 LLM/検索スパン存在を検証 | `observability.py` + InMemorySpanExporter テスト、uninstrument 増分ゼロも実証 | ✅ |
| `RUN_INTEGRATION_PATTERNS=1` ゲートの Ollama 結合（契約レベルアサート） | gated e2e 1件、未設定時 skip・env 専属モデル同定 | ✅ |
| mise/CI 配線・ルート無変更維持（R11.3/12.2） | `patterns:*` 明示行 + rag CI ジョブ、ルート `check` 277 passed 無変更 | ✅ |
| Docling 依存重量の隔離要否を Task 0 spike で実測確定 | torch/onnxruntime 不在を実測 → 独立レーン維持・unit 隔離非発動 | ✅ |

## Test & Quality Outcomes

- RAG レーン: **58 passed / 1 skipped**（gated Ollama が正しく skip）
- カバレッジ: **100.00%**（gate 98 充足、7 モジュール全 100% / 121 stmts・26 branch 全被覆）
- contracts レーン: green（drift 4 + RAG 契約テスト、`patterns:check` 内で通過）
- lint / format / typecheck: 全グリーン（pyright strict 0 errors）
- ルート回帰: **277 passed / 4 skipped**（無変更グリーン、R12.2/R11.3）

## Requirements Coverage

- Covered: **41/41 (100%)** — Coverage Matrix の全 numeric requirement にタスク割当を確認
- Gaps: なし

## Deviations from Design

- **R-1 トークナイザ確定の方針転換**: Task 0 spike は tiktoken 注入(b)を「追加依存ゼロ」で
  主策に傾けたが、Task 3 で空 cache + 不正 proxy 実測により `cl100k_base` が BPE 表を
  ネットワーク DL する（`ProxyError`）と判明 → 根本対処として **tokenizer を DI seam 化**し
  決定論オフライン `WordTokenizer` を注入する方針へ変更（hermetic 主張を実測で確定）。
- **計画済み RED 窓（DAG Wave 分離の帰結）**: Task 2（契約 package 追加）と Task 11（README
  正本記載）が別 Wave のため、その間 `test_contract_drift.py` が意図的に RED。fix-forward せず
  所有タスク（Task 11）で閉鎖 — 単一点ドリフト設計の正しい帰結であり欠陥ではない。
- いずれも plan の意図（hermetic / 単一正本）を強化する方向の確定であり、設計逸脱ではなく
  spike が委ねた最終確定。

## Issues Encountered

| Issue | Root cause | Resolution |
|-------|-----------|------------|
| tiktoken が cold cache で BPE をネット DL | 「オフライン依存」も cache 無効時は DL し得る | tokenizer を DI seam 化・決定論 `WordTokenizer` 注入（R-1 クローズ） |
| `semchunk` が `get_tokenizer()` に callable 要求 | スタブが `None` 返却で分割時 `TypeError` | `get_tokenizer()` が bound counter（callable）を返すよう実装 |
| 既存 hermetic パイプラインにガード追加すると自然に RED にならない | 既にネット非到達のため teeth が出ない | ガード下で実 AF_INET connect が `NetworkReachError` を送出する load-bearing テストを併設 |
| `mise run patterns:test` が contracts で停止（Task 9 時点） | Task 2→11 間の計画済み README ドリフト窓 | Task 11 で正本記載し解消（per-lane 直接起動で RAG green を確認済み） |

## Assessment

実装は計画を完全に満たし、`/sdd-validate-impl` は **GO**（CRITICAL ゼロ）。要件 41/41 トレース・
RAG カバレッジ 100%（gate 98）・ルート無変更グリーン。spike が委ねた2論点（配置・tokenizer）は
いずれも実測で確定し、hermetic 主張は cold-cache + ネット遮断で立証済み。**本番投入可能**
（結合の live-green のみ CI 上の gated env + 実 daemon を要し、これは設計どおりの責務分担）。
