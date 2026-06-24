# 009-deep-research — Tasks（Red-Green-Refactor）

各タスクは要件 ID にトレースし、テスト先行（Red）→実装（Green）→整理（Refactor）で進める。
品質ゲートは mise/uv 経由（bare 実行なし）。

## Task 1 — 契約と単一ドリフト（Req 2）
- [x] 1.1 `patterns_contracts/deep_research.py` 追加（brief/plan/finding/report＋`ProgressEvent`、`Citation` 再利用）。
- [x] 1.2 `patterns_contracts/__init__.py` 再export（`__all__` アルファベット順）。
- [x] 1.3 `patterns/deep-research/README.md` の `## パターン契約` 正本 fence を記述。
- [x] 1.4 `test_contract_drift.py` の `_README_PATHS` に `deep-research` 登録。
- [x] 1.5 `test_deep_research_contracts.py` 追加 → contracts ドリフト green。

## Task 2 — レーン scaffold（Req 1, 9）
- [x] 2.1 `pyproject.toml`/`.python-version`(3.13)/`__init__.py`/`observability.py`。
- [x] 2.2 `search.py`（`SearchProvider` Protocol＋`load_search_provider`）。
- [x] 2.3 `tests/support/{fake_search,model_fakes,hermetic}.py`＋`fixtures/corpus.json`。
- [x] 2.4 `tests/unit/conftest.py`（autouse `block_network`）＋`test_smoke.py`/`test_search_seam.py`。

## Task 3 — lead（Req 3）
- [x] 3.1 `orchestrator.build_brief_and_plan`（planner＋任意 clarify）＋`test_brief_and_plan.py`。

## Task 4 — researcher・引用 grounding（Req 4, 5）
- [x] 4.1 `compression.py`（`map_citations`/`dedup_citations`＋empty/dangling loud-fail）。
- [x] 4.2 `researcher.run_subquestion`（有界 search→read→reflect＋compress）。
- [x] 4.3 `test_bounded_iterations.py`/`test_citation_mapping.py`。

## Task 5 — fan-out・report・可観測性（Req 4.1, 6, 7, 9）
- [x] 5.1 `research.run_deep_research`（cap 検証→plan→fan-out cap→gather→report）。
- [x] 5.2 `report.write_report`（synthesizer＋dedup＋truncated 伝播）。
- [x] 5.3 `test_fanout_cap.py`/`test_report_synthesis.py`/`test_observability.py`。

## Task 6 — 進捗ストリーミング seam（Req 10）
- [x] 6.1 `run_deep_research(on_event=...)` で `ProgressEvent` 発行（順序検証）。

## Task 7 — 結合・ゲート（Req 8.3）
- [x] 7.1 `tests/integration/{conftest,test_ollama_e2e}.py`（gated＋`EXPECT_LIVE_TESTS`、既定 fake 検索／`RUN_INTEGRATION_SEARCH=1` でライブ）。

## Task 8 — ドキュメント（Req 11, 13）
- [x] 8.1 lane README 4セクション＋COMPARISON.md（7フレーム比較・ハイブリッド）。
- [x] 8.2 `patterns/README.md` 応用レイヤー索引＋`SECURITY-NOTES.md` OWASP マッピング。

## Task 9 — 配線（Req 12）
- [x] 9.1 `mise.toml`（`patterns:*`＋per-lane 結合タスク）。
- [x] 9.2 `patterns-ci.yml` 専用ジョブ＋`patterns-integration-ollama.yml` マトリクス。
- [x] 9.3 `.env.example` 追記、`uv.lock` 生成・コミット。

## Task 10 — 検証
- [x] 10.1 contracts ドリフト green / lane unit 100% / pyright strict / ruff clean。
