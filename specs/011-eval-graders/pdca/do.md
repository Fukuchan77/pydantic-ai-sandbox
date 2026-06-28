# 011-eval-graders — PDCA Do Phase Log

## Task 1.1 — 契約形状の失敗テストを先行作成（RED）

- **State**: RED 確認済 ✅（Task 1.2 で緑化予定）
- **成果物**: `patterns/contracts/tests/unit/test_eval_graders.py`（新規・hermetic・ネットワーク I/O ゼロ）
- **被覆観点**: `Rating` 語彙（`"1"`–`"5"` + `"unknown"`）受理／語彙外拒否、outcome・behavior 軸分離 +
  `aggregate: float` partial credit（outcome に `unknown`・behavior に数値混在で構築可）、`rationale`
  空/空白の loud-fail（`ValidationError`）、`judge_id` 任意（既定 None）、inline 決定論フェイクによる
  `Judge[str]` Protocol 準拠（`await grade()→GradeReport`）、フラット再エクスポート面。
- **RED 証拠**: `uv run pytest --no-cov tests/unit/test_eval_graders.py`
  → `ImportError: cannot import name 'AxisScore' from 'patterns_contracts'`（契約未実装ゆえの想定赤）。
- **回帰確認**: 既存契約スイート（新規ファイル除外）は `34 passed` で無改変・緑維持。

### Learnings

- 契約パッケージは `asyncio_mode = "auto"`。async な `Judge.grade` テストは `async def test_...` を直接書け、
  `@pytest.mark.asyncio` 不要。
- `Judge` Protocol の構造的準拠は runtime `isinstance` ではなく、`Judge[str]` 引数で受ける
  ヘルパ経由（pyright が構造検証・runtime で await 実行）で固定する設計とした。
- Task 1.2 で `eval_graders.py` 実装 + `__init__.py` フラット再エクスポートにより緑化する。

## Task 1.2 — 契約実体実装 + フラット再エクスポート（GREEN）

- **State**: scoped test 緑化済 ✅（`test_eval_graders.py` 17 passed）
- **成果物**:
  - 新規 `eval_graders.py` — `Rating`（col-0 名前付き Literal）/ `AxisScore`（`rationale` 非空 `field_validator`）
    / `GradeReport`（outcome・behavior 分離 + `aggregate: float` + `judge_id: str | None`）/ `Judge[SubjectT]`
    （PEP 695 ジェネリック Protocol、`async def grade`）。
  - `__init__.py` — 4 シンボルを import + `__all__` へ alphabetical 追加（フラット再エクスポート面）。
- **GREEN 証拠**: `uv run pytest --no-cov tests/unit/test_eval_graders.py` → `17 passed`。
- **検証ゲート**: lint `All checks passed!` / format `19 files already formatted` / pyright `0 errors`。
- **既知の sequenced-red（非デグレ）**: 全体 suite は `47 passed, 4 failed`。失敗 4 本はすべて
  `test_contract_drift.py`。原因は package に `AxisScore`/`GradeReport`/`Rating` が出現したが
  `EVAL-GRADERS.md` 未作成・`_README_PATHS` 未登録のため（正本欠落）。**Task 2.1/2.2 が緑化する**
  設計どおりの中間状態（tasks.md Task 2.2 完了条件 = drift 緑維持）。

### Root cause analysis（drift 4 本の赤）

- 直接原因: drift テストは `__all__` を introspect し README 正本と双方向照合する。1.2 で export 面を増やすと
  対応する正本（EVAL-GRADERS.md）が必要になる。
- これは defect ではなく task 分割による sequenced state。1.2 のスコープは「契約実体 + 再エクスポートで
  `test_eval_graders.py` を緑化」であり満たしている。fix-forward は不要（Task 2 が正規の closing task）。

### Learnings

- PEP 695 `class Judge[SubjectT](Protocol)` は py313 / pyright strict で問題なし。`from __future__ import
  annotations` 併用でも Protocol メソッド注釈は文字列化され整合。
- parametrize の rating 引数は `rating: Rating` と注釈しないと pyright strict が `str → Literal` 不可で赤化。
- 契約モジュールの初期 ruff format は col-width で `Field(...)` を複数行化する。`ruff format`（--check でなく）で
  自動整形してからゲートに掛けると齟齬がない。

## Task 2.1 — 横断正本 README `patterns/EVAL-GRADERS.md` 作成

- **State**: 正本作成済 + parser-match 事前検証済 ✅（drift 緑化は Task 2.2 で確定）
- **成果物**: `patterns/EVAL-GRADERS.md`（初の横断 README）。`## パターン契約（正本）` 直後の最初の `python` fence に
  正本ブロック（col-0 `Rating = Literal[...]` + `class AxisScore` / `class GradeReport` / `class Judge[SubjectT](Protocol)`）。
  別節に Rating 1–5 + `"unknown"` rubric（Vertex 方式）、outcome/behavior criterion 例、独立 judge 規律、
  ランタイムゲート併存（後方互換 / ADR-4）を散文化。
- **事前検証（parser-match）**: drift parser の `_normative_block`/`_collect_named_literals`/`_collect_model` を
  本 README へ直接適用し package shape と照合 →
  `Rating` 語彙一致 / `AxisScore`・`GradeReport` フィールド集合一致 / `(AxisScore,rating)` literal 一致 /
  `Judge` Protocol スキップ を確認。**Task 2.2 登録で drift 4 本が緑化する**ことを機械的に裏付け。
- **検証ゲート**: 本タスクは markdown のみ（`.py` 無改変）ゆえ lint/format/typecheck 不影響。全体 suite は
  `47 passed, 4 failed`（drift、未登録のため不変）。drift 検証は Task 2.2 のスコープ。

### Learnings

- drift parser は `## パターン契約` を `index()` 部分一致で探すので見出しは `（正本）` 付きでも可。最初の `python`
  fence を正本ブロックにする配置が必須。
- README 正本に PEP 695 `class Judge[SubjectT](Protocol)` を書いても `ast.parse`（3.13）は通り、`_is_protocol` が
  Protocol 基底を検出してスキップする。既存 README の無効 signature（`model/llm`）と違い構文有効で安全。

## Task 2.2 — `_README_PATHS` へ eval-graders 登録（drift 緑化）

- **State**: 緑化完了 ✅。sequenced-red（Task 1.2 以降の drift 4本）を解消。
- **成果物**: `test_contract_drift.py` の `_README_PATHS` に `"eval-graders": _PATTERNS_DIR / "EVAL-GRADERS.md"`
  を 1 行追加（parser 本体は無改修）。
- **GREEN 証拠**:
  - drift: `uv run pytest tests/unit/test_contract_drift.py` → `4 passed`
  - lint `All checks passed!` / format `19 files already formatted` / pyright `0 errors`
  - 全体 + coverage: `51 passed`、`Total coverage: 100.00%`（floor 85 超過）
- **R2.2 後方互換**: 既存ランタイム契約テスト無改変のまま 51 passed に含まれ緑維持を確認。

### Learnings

- 横断 README は `patterns/` 直下なので `_PATTERNS_DIR / "EVAL-GRADERS.md"`（サブディレクトリ無し）。既存 6+3 件は
  `<pattern>/README.md` 形式だった点と差異。
- Serena `replace_content` は language server 不在で失敗。コード編集は Edit へフォールバック（既読ファイルゆえ可）。

## Task 3.1 — deep-research レーン失敗 eval テストを先行作成（RED）

- **State**: RED 確認済 ✅（Task 3.2 で緑化予定・sequenced-red）
- **成果物**: `patterns/deep-research/tests/unit/test_eval_graders_deep_research.py`（新規・hermetic・I/O ゼロ）
- **被覆観点**: 共有 `GradeReport`/`Judge` を `patterns_contracts` から import し、レーン自身の
  `ResearchReport`（`Finding.notes` 含む = R2.3）を決定論フェイク `Judge[ResearchReport]` で採点して
  `GradeReport` 形状（outcome/behavior 軸分離・`judge_id` provenance）を検証。純粋ヘルパ
  `faithfulness_rating_for(notes)` へ空/空白/非空 `key_point` と空 notes を直接与え、R2.4 の
  `Unknown` 分岐（空・低信号→`"unknown"`／grounded→数値 Rating）を tested 化。フェイクはヘルパを呼ぶ
  end-to-end 1 本で台本焼き込み（同義反復）を回避。`Judge[ResearchReport]` Protocol シーム準拠も検証。
- **RED 証拠**: `uv run pytest --no-cov tests/unit/test_eval_graders_deep_research.py`
  → `ImportError: cannot import name 'FakeResearchReportJudge' from 'tests.support.model_fakes'`
  （フェイク judge・ヘルパ未実装ゆえの想定赤＝Task 1.1 と同型の import-error red）。
- **無回帰**: 残レーン unit `53 passed`（新ファイル除外）。新ファイル lint `All checks passed!` / format 済。

### Learnings

- coverage source は `src/patterns_deep_research` のみ。Task 3.2 の fake judge + ヘルパは `tests/support/`
  に置くため 98 ratchet に算入されず、契約参照テスト追加が coverage を割らない設計。
- isort: `tests.support.*` は first-party 群（`patterns_deep_research` と同群）に並ぶ。既存 `test_research.py`
  の import 並びに準拠。

## Task 3.2 — deep-research フェイク judge + 純粋ヘルパ実装（GREEN）

- **State**: 緑化完了 ✅（Task 3.1 の sequenced-red を解消）
- **成果物**: `patterns/deep-research/tests/support/model_fakes.py` に
  `faithfulness_rating_for(notes) -> Rating`（純関数）+ `FakeResearchReportJudge`（`Judge[ResearchReport]` 準拠）を純加算。
- **設計**: ヘルパは grounded share で `unknown`（grounded 0）/`3`（partial）/`5`（full）を返す。フェイク `grade()` は
  `Finding.notes` をフラット化しヘルパを呼んで faithfulness behavior 軸を導出（R2.4 をテスト直接ピンと同一経路へ通し
  台本焼き込み＝同義反復を回避）。outcome 軸（completeness）は台本化、`judge_id` で provenance を刻む（R3.3）。
- **GREEN 証拠**:
  - 対象: `uv run pytest --no-cov tests/unit/test_eval_graders_deep_research.py` → `9 passed`
  - 全体 + coverage: `62 passed, 1 skipped`、`Total coverage: 100.00%`（floor 98 超過）
  - lint `All checks passed!` / format `27 files already formatted` / pyright `0 errors, 0 warnings`
- **無回帰**: 既存 `plan_payload`/`scripted_model` 利用テスト（`test_research.py` 等）は無改変のまま緑維持。

### Learnings

- `AxisScore`/`GradeReport` は runtime 構築ゆえ通常 import、`Rating`/`ResearchNote`/`ResearchReport` は注釈専用で
  `TYPE_CHECKING` 下（ruff `TCH` 準拠）。`async def grade(self, subject, /)` の positional-only 一致で
  `Judge[SubjectT]` Protocol への構造的準拠を pyright strict が検証（RUF029 は preview 非選択ゆえ no-await でも緑）。
- `tests/support/` は coverage source 外。フェイク + ヘルパ追加が 98 ratchet を割らない設計を実測で確認（100% 維持）。
