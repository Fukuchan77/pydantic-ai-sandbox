# 010-context-engineering — 実装ギャップ分析

> `/sdd-validate-gap` の出力。承認済み要件（`spec.md`、Clarifications 確定済）と既存コードベースの
> 差分を提示し、`/sdd-plan` の設計判断に必要な情報を揃える。**決定ではなく選択肢**を提供する。

## 分析サマリ（要点）

- **compaction アルゴリズムは既に完成・100% テスト済**。ギャップは「アルゴリズム不在」ではなく
  **本線への配線（DI シーム化）と契約昇格**に限定される。`notes.py` の `distill_notes` /
  `compact_digest` はそのまま流用できる。
- **最大の設計判断は 2 点**:(1) `ResearchNote` を dataclass から `patterns_contracts` の
  Pydantic 契約へ昇格させる方式、(2) `notes` ハンドオフを既存 `Finding` に載せるか新規 carrier にするか。
  既存 `Finding` が既に「凝縮サマリ + 引用」のハンドオフ実体なので、**`Finding` 拡張**が最小整合。
- **隠れた correctness リスク**: `researcher.py` の `_results_digest` は reflect ループ（L132）と
  **compression ターン（L150）の 2 箇所**で呼ばれる。Req 1.1 は reflect ループのみを対象とする。
  compression ターンの digest を compaction で縮約すると、citation 選択元が削られ
  `EmptyCitationError`/`DanglingCitationError` を誘発し得る。**seam は reflect ループ限定が安全**。
- **型の整合ナット**: `_results_digest(results: list[SearchResult])` は `list` 引数。seam 型
  `Callable[[Sequence[SearchResult]], str]` の既定値にするには pyright strict（引数反変）で
  `Sequence` への引数型拡幅が必要。`compact_digest` は既に `Sequence` 受け。
- **ドリフト/カバレッジは自動で味方**: `ResearchNote` を BaseModel 化し deep-research README 正本へ
  記載すれば、`test_contract_drift.py` の「1クラス=1README」不変条件が Req 2.3 をそのまま機械検証する。
  カバレッジは `fail_under=98`（実績 100%）— 新シーム分岐と契約に test を足せば維持可能。

## 要件 → 既存コード ギャップ表

| Req | 必要ケイパビリティ | 分類 | 根拠（file:line） |
|---|---|---|---|
| 1.1 | reflect digest を `digest_fn` シームとして公開 | 🆕 新規 | [researcher.py:76-122](../../patterns/deep-research/src/patterns_deep_research/researcher.py#L76-L122) に `run_subquestion` シグネチャあり。digest seam パラメータは未存在。`_results_digest` は L132 でハードコード呼出 |
| 1.2 | `compact_digest` 注入時にノートベース縮約 digest を供給 | ✅ アルゴ済 / 🆕 配線 | [notes.py:133-155](../../patterns/deep-research/src/patterns_deep_research/notes.py#L133-L155) `compact_digest` 実装済・テスト済。reflect への注入経路が未配線 |
| 1.3 | 未注入時 `_results_digest` と byte 一致（後方互換） | 🔧 既存維持 | [researcher.py:67-73](../../patterns/deep-research/src/patterns_deep_research/researcher.py#L67-L73)。既定値に同一関数オブジェクトを据えれば byte 一致。byte 同一性をロックする test が未存在 |
| 1.4 | v1 は digest 縮約限定（tool result clearing / 上限再初期化を提供しない）| ✅ 設計境界 | 既存に余計な実装なし。docs に「非対象」明記が必要（Req 3.4/5.1 と連動）|
| 2.1 | `ResearchNote`（source/locator/key_point/score）を `patterns_contracts` の単一実体に | 🔧 昇格 | [notes.py:53-60](../../patterns/deep-research/src/patterns_deep_research/notes.py#L53-L60) に **frozen dataclass** として存在。`patterns_contracts.deep_research` には未定義（[deep_research.py](../../patterns/contracts/src/patterns_contracts/deep_research.py)）。BaseModel 化 + 再エクスポートが必要 |
| 2.2 | sub-researcher→lead ハンドオフを「凝縮サマリ + ノート」に限定 | 🔧 部分済 + 🆕 | [researcher.py:155-161](../../patterns/deep-research/src/patterns_deep_research/researcher.py#L155-L161) `Finding` は既に summary+citations のみ（生 transcript 非伝播）。`notes` フィールドが Finding 契約に無い（[deep_research.py:109-123](../../patterns/contracts/src/patterns_contracts/deep_research.py#L109-L123)）|
| 2.3 | `ResearchNote` 正本を deep-research README が所有、ドリフトで検証 | 🆕 + ✅ 機構済 | README 正本ブロック（[README.md:34-92](../../patterns/deep-research/README.md#L34-L92)）に `ResearchNote` 未記載。`test_contract_drift.py` の one-README 不変条件は追加だけで自動適用 |
| 3.1-3.2 | dedup（最高score優先）/ score降順 +(source,locator) tiebreak / `max_notes` cap / 可視 truncate | ✅ 実装済 | [notes.py:76-123](../../patterns/deep-research/src/patterns_deep_research/notes.py#L76-L123)、test [test_notes.py:26-67](../../patterns/deep-research/tests/unit/test_notes.py#L26-L67) で網羅 |
| 3.3 | `max_notes`/`key_point_chars` 非正で `ValueError` loud-fail | ✅ 実装済 | [notes.py:98-103](../../patterns/deep-research/src/patterns_deep_research/notes.py#L98-L103)、test [test_notes.py:70-74](../../patterns/deep-research/tests/unit/test_notes.py#L70-L74) |
| 3.4 | 上限再初期化を v1 非対象とし token-budget seam 接続を拡張点として文書化 | 🆕 文書 | [README.md:148-149](../../patterns/deep-research/README.md#L148-L149) に token-budget seam 言及あり。明示の拡張点記述を追記 |
| 4.1 | 全 unit がネットワーク I/O ゼロ | ✅ 機構済 | `block_network` + 決定論フェイク（[README.md:122-124](../../patterns/deep-research/README.md#L122-L124)）。新規 test も同方針で書く |
| 4.2 | compaction（cap/dedup/trunc/順序）+ ノート受け渡しを契約レベル検証 | 🔧 一部済 + 🆕 | compaction 側は [test_notes.py](../../patterns/deep-research/tests/unit/test_notes.py) で済。ハンドオフ（Finding.notes）と seam 注入の test が未存在 |
| 4.3 | カバレッジ `fail_under`（実績 100%）維持 | 🔧 維持 | [pyproject.toml:125](../../patterns/deep-research/pyproject.toml#L125) `fail_under = 98` |
| 5.1 | `docs/context-engineering.md` を本線配線手順へ更新 + README 準拠追記 | 🔧 更新 | [context-engineering.md:72-94](../../docs/context-engineering.md#L72-L94) は現在「配線していない（diff 提示のみ）」と明記。本線昇格後に書換 |
| 5.2 | `verification.md` 観点5 を実装済へ反映 | 🔧 更新 | [verification.md:33](../../specs/best-practices-review/verification.md#L33) が「compaction/note-taking 未実装 ✅/△ 部分的」。実装済へ更新 |

凡例: ✅ 既存で満たす / 🔧 部分的（要拡張）/ 🆕 新規構築

## 統合上の課題（plan で要対処）

1. **digest seam の適用範囲（correctness 直結）**: `_results_digest` は reflect（L132）と
   compression（L150）の 2 箇所で使用。compression ターンの digest を compaction で縮約すると
   citation 選択元の source が脱落し `map_citations` が dangling/empty で loud-fail し得る。
   → **seam は reflect ループのみに適用**し compression は full digest を維持する案を推奨。
   spec Req 1.1 の文言（「reflect ループの digest 生成」）とも一致。
2. **既定値の型反変**: seam 型 `Callable[[Sequence[SearchResult]], str]` の既定に `_results_digest`
   を据えるには、その引数型を `list` → `Sequence[SearchResult]` へ拡幅する（pyright strict）。
   挙動は不変。`Sequence` の遅延 import は既存 `TYPE_CHECKING` ブロックに追加。
3. **`run_deep_research` への seam スルーパス**: 最上位エントリから opt-in 注入できるよう
   `run_deep_research` にも `digest_fn` を通すか、`run_subquestion` 限定にするか。
   end-to-end で compaction を有効化するなら前者が必要（[research.py:122-130](../../patterns/deep-research/src/patterns_deep_research/research.py#L122-L130) で `run_subquestion` 呼出）。
4. **`ResearchNote` dataclass→BaseModel 移設の波及**: `notes.py` は契約から import する形へ変更。
   既存 test [test_notes.py:39](../../patterns/deep-research/tests/unit/test_notes.py#L39) は等値比較に依存
   （Pydantic は `==` 対応）、kwargs 構築のみ（位置引数なし）で BaseModel 化に耐える。
   `frozen=True` を維持しハッシュ可能性・不変性を保つ。
5. **契約 test の追従**: [test_deep_research_contracts.py:65-71](../../patterns/contracts/tests/unit/test_deep_research_contracts.py#L65-L71) の
   `Finding.model_fields` 期待集合に `notes` を追加、`ResearchNote` の reexport/field-set ケースを新設。
6. **`decision` 拡張余地（ADR-2）**: v1 は 4 フィールド固定。将来の採用/棄却判断（`decision` 系）は
   **追加しない**が、契約 docstring/README に拡張点として明記（Anthropic「将来の推論を制約し続ける情報のみ」）。
7. **README ベータ版数・凍結6パターン非干渉**: 変更は deep-research README 正本ブロックと
   `patterns_contracts.deep_research` / `__init__` のみ。凍結済み 6 ワークフロー契約・他レーンには触れない（NFR）。

## アプローチ選択肢（トレードオフ）

| 案 | 内容 | コスト | リスク | 適合 |
|---|---|---|---|---|
| **A. 昇格 + Finding 拡張（Hybrid, 推奨）** | `ResearchNote` を契約へ昇格 → `notes.py` は import 利用。`digest_fn` を `run_subquestion`(+`run_deep_research`)へ。`Finding.notes` を追加し `distill_notes(collected)` で充填 | 中 | 統合（契約 test/drift/README/docs を同時更新）。既存パターン（`SearchProvider`/`on_event` の DI 規律、`Citation` 所有則）に正対 | Req 1〜5 を全充足。spec ADR-1〜3 と一致 |
| **B. seam のみ（契約昇格を見送り）** | `digest_fn` シームだけ追加、`ResearchNote` は dataclass のまま local 保持、Finding 不変 | 低 | **Req 2.1/2.3 未充足**（契約所有・ドリフト検証が成立しない）。note ハンドオフ（Req 2.2）も不成立 | 不可（縮退フォールバックとしてのみ言及）|
| **C. 新規ハンドオフ carrier 新設** | `Finding` を拡張せず `SubResearchHandoff` 等の新契約に summary+notes を載せる | 高 | summary/citation の二重定義・契約数増・drift/README 追記が倍増。`Finding` が既にハンドオフ実体なので重複 | 過剰。非推奨 |

**推奨**: **案 A**。compaction アルゴリズムと DI 規律（`SearchProvider`/`on_event`/`instrument_model`）、
契約所有則（`Citation` を RAG が所有する判断と同型に `ResearchNote` を deep-research が所有）が
既存パターンに完全に乗る。最小チャーンで Req 全充足。

## plan フェーズで深掘りすべき論点

1. **digest seam の適用範囲確定**: reflect 限定 vs reflect+compression。推奨は reflect 限定
   （compression の citation-grounding を壊さない）。要設計確認・受入条件化。
2. **`run_deep_research` への seam 露出有無**: end-to-end opt-in を実現するか、`run_subquestion` 局所に留めるか。
3. **`Finding.notes` の必須/任意・既定**: 既定 `[]`（後方互換）か必須か。既存 `Finding` 利用箇所
   （report writer / 既存 test / fixtures）への波及を確認。
4. **byte 同一性テストの粒度**: Req 1.3 を「同一プロンプト文字列」でロックする具体的アサーション設計。
5. **README 正本ブロックへの `ResearchNote` 挿入位置**: `SearchResult` の直後など、ドリフト parser が
   col-0 class として拾える形か確認。

## 次のステップ

- 本ギャップ分析をレビュー後、`/sdd-plan 010-context-engineering` で技術プラン（plan.md）を作成する。
- 要件は `approved: false`（[spec.json:12](spec.json#L12)）。`/sdd-plan ... -y` で承認と設計を一括するか、
  先に要件承認を行うかは運用判断。Clarifications は確定済（ADR-1〜3）なので設計の前提は固まっている。
