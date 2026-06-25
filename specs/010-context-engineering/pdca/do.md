# 010-context-engineering — PDCA Do Phase

実装の進捗・試行錯誤・根本原因分析を継続記録する。

---

## Task 1.1 — ResearchNote 契約昇格 + Finding.notes 追加

**日付**: 2026-06-25
**Boundary**: `patterns/contracts/src/patterns_contracts/deep_research.py`,
`patterns/contracts/src/patterns_contracts/__init__.py`,
`patterns/contracts/tests/unit/test_deep_research_contracts.py`
**Requirements**: 2.1, 2.2, 4.1, 4.2, 4.3

### RED

`test_deep_research_contracts.py` に先行で追加:

- `patterns_contracts` から `ResearchNote` を import（未エクスポートで `ImportError`）。
- `_MODELS` に `ResearchNote` を追加（reexport ループで網羅）。
- `test_field_sets`: `ResearchNote == {source, locator, key_point, score}`、
  `Finding` 期待集合へ `notes` 追加。
- `test_research_note_is_frozen`: frozen 変異で `ValidationError`。
- `test_finding_notes_defaults_to_empty_list`: 既定 `[]`。
- `test_finding_carries_research_notes`: notes 充填時に `ResearchNote` インスタンス。

確認: `ImportError: cannot import name 'ResearchNote'` で collection 赤化。

### GREEN

- `deep_research.py` に `class ResearchNote(BaseModel)`（`model_config={"frozen": True}`、
  4 フィールド + docstring に `decision` 系拡張余地を明記）を `SearchResult` 直後へ定義。
- `Finding` に `notes: list[ResearchNote]` 追加。`__all__` 更新。
- `__init__.py` で `ResearchNote` を import + `__all__` 再エクスポート。

結果: `test_deep_research_contracts.py` 10 passed。

### 根本原因対応（pyright strict）

- **症状**: `Field(default_factory=list)` が `reportUnknownVariableType`
  (`Type of "notes" is "list[Unknown]"`) で gate 赤。
- **根本原因**: `list` builtin を factory に渡すと pyright が型引数を推論できず
  field 型が部分 unknown へ後退する（pyright の既知制約）。
- **対応**: `Field(default=[])` を採用。pydantic v2 は mutable default を
  インスタンス毎にコピーするため共有 footgun なし（2 インスタンスで分離を実測）。
  plan の `default_factory=list` からの最小逸脱だが機能等価かつ gate 準拠。

### VERIFY（Task 自身のスコープ）

| Gate | Cmd | 結果 |
|---|---|---|
| test | `uv run pytest tests/unit/test_deep_research_contracts.py --no-cov -q` | 10 passed |
| lint | `uv run ruff check` (boundary files) | All checks passed |
| format | `uv run ruff format --check` (boundary files) | already formatted |
| typecheck | `uv run pyright` (package) | 0 errors |

### 既知の意図的赤（→ Task 1.2 で緑化）

`test_contract_drift.py` の 3 件
(`test_documented_class_set_matches_package` /
`test_documented_field_sets_match_package` /
`test_each_package_model_is_documented_in_exactly_one_readme`) は
README 正本未同期のため赤。tasks.md 1.2（無変更 drift test の緑化）への設計上の
ハンドオフであり回帰ではない。1.1 単体の受入条件（自テスト RED→GREEN）は充足。

### Act 向け学び

- 契約への mutable default 追加時は pyright strict のため `default=[]` を既定形に
  （`default_factory=list` は不可）。pydantic v2 のコピー挙動で安全。
- 契約 field 追加（1.1）と README 正本同期（1.2）の分割は、間に drift test が
  必ず赤になる窓を作る。ペアで連続実行するか、赤を「設計上」と明示記録する。

---

## Task 1.2 — deep-research README 正本同期（drift 緑化）

**日付**: 2026-06-25
**Boundary**: `patterns/deep-research/README.md`
**Depends**: 1.1
**Requirements**: 2.3

### RED（先行赤は 1.1 から継承）

Task 1.1 完了時点で `test_contract_drift.py` の 3 件
(`test_documented_class_set_matches_package` /
`test_documented_field_sets_match_package` /
`test_each_package_model_is_documented_in_exactly_one_readme`) が
README 未同期で赤。これが本タスクの先行 RED。

### GREEN

`## パターン契約（正本）` fence へ:

- `class ResearchNote(BaseModel):` を col-0 で `SearchResult` 直後へ挿入
  （4 フィールド `source`/`locator`/`key_point`/`score` を README idiom の注釈付きで）。
- `Finding` へ `notes: list[ResearchNote] = []` 行を追記。

drift parser は field 名のみ比較（default/型は非対象）のため注釈表記で十分。
package 側 `default=[]` と表記も整合させた。

### VERIFY

| Gate | Cmd | 結果 |
|---|---|---|
| drift | `uv run pytest tests/unit/test_contract_drift.py --no-cov -q` | 4 passed |
| contracts 全体 | `uv run pytest --no-cov -q` (patterns/contracts) | 34 passed（旧 31+3赤 → 全緑） |
| deep-research lane | `uv run pytest --no-cov -q` (patterns/deep-research) | 40 passed, 1 skipped（回帰なし） |

### 結果

major task 1（契約昇格）完了。`ResearchNote` 契約と `Finding.notes` が package＝README
で機械検証され一致。Req 2.1/2.2/2.3 充足。次は major task 2（notes.py の契約 import 移行）。

---

## Task 2.1 — test_notes.py に契約移行テストを先行追加（RED 半）

**日付**: 2026-06-25
**Boundary**: `patterns/deep-research/tests/unit/test_notes.py`（テストのみ）
**Requirements**: 3.1, 3.2, 3.3, 4.1, 4.2

### RED

`test_notes.py` に 4 件追加（注入用 import: `ResearchNote as ContractResearchNote`,
`pydantic.ValidationError`）:

- `test_research_note_is_the_promoted_contract_single_entity`: `id(notes.ResearchNote)
  == id(ContractResearchNote)`。移行前は local dataclass のため **赤**。
- `test_research_note_is_a_frozen_basemodel`: 変数経由 `setattr` で frozen 変異 →
  `ValidationError` を要求。移行前は `FrozenInstanceError` のため **赤**。
- `test_research_note_keyword_construction_and_value_equality`: kwargs 構築 + 値等価
  （dataclass/BaseModel 両対応の保存ロック、緑）。
- `test_distill_notes_returns_empty_for_empty_input`: `distill_notes([]) == []`（緑）。

### 検証

- 型/lint ゲートを**緑**に保つ設計判断（do.md の learnings 参照）:
  - 単一実体は `is` ではなく `id() ==`（pyright `reportUnnecessaryComparison` 回避）。
  - frozen は変数経由 `setattr`（直接代入=pyright frozen-dataclass 赤／リテラル
    `setattr`=ruff B010 を同時回避）。
- 実測（`uv run`、lane venv）:
  - `ruff check tests/unit/test_notes.py` → All checks passed
  - `ruff format --check` → already formatted
  - `pyright` → 0 errors, 0 warnings
  - `pytest tests/unit --no-cov` → **2 failed, 42 passed**
    （failed = 単一実体・frozen の 2 件のみ、いずれも移行前 dataclass を正しく検知）

### 結果（ハンドオフ）

新規 2 件は **意図的に赤**（`notes.ResearchNote` がまだ local dataclass）。lint/format/
pyright は緑のため、Task 2.2 の import 移行は純粋な挙動フリップで両件を緑化する設計上の
ハンドオフ（Task 1.1→1.2 と同型）。coverage ratchet（`fail_under=98`）は major task 2
完了（2.2 後）に確認する。

---

## Task 2.2 — notes.py を契約 import へ移行（GREEN 半）

**日付**: 2026-06-25
**Boundary**: `patterns/deep-research/src/patterns_deep_research/notes.py`
**Requirements**: 1.2, 3.1, 3.2, 3.3, 4.3

### GREEN（純挙動フリップ）

- `@dataclass(frozen=True, slots=True) ResearchNote` と `from dataclasses import dataclass`
  を削除。
- `from patterns_contracts import ResearchNote` を追加。**runtime import**（`distill_notes`
  が instantiate するため TYPE_CHECKING 不可）。コメントで「昇格済み単一実体・再定義ではない」を明記。
- `SearchResult` は注釈専用のため TYPE_CHECKING ブロック据え置き。
- `distill_notes` / `compact_digest` / `render_notebook` / `_key_point` の本体は **byte 不変**
  （dedup / score 降順 + tiebreak / `max_notes` cap / 可視 truncate / 非正 `ValueError`）。
- `__all__` は import した `ResearchNote` を再エクスポート（消費側 import 不変）。

### 検証（lane gate, `uv run`）

- `ruff check .` → All checks passed
- `ruff format --check .` → 24 files already formatted
- `pyright` → 0 errors, 0 warnings, 0 informations
- `pytest --cov` → **44 passed, 1 skipped**、`notes.py` 100%、TOTAL 100.00%
  （`fail_under=98` 到達）。2.1 の赤 2 件（単一実体・frozen）が緑化。

### 根本原因メモ

エラーゼロ。2.1 で型/lint ゲートを緑に保つ設計（`id()` 比較・変数経由 `setattr`）に
したため、2.2 は import 置換のみで赤 2 件が緑化し、副作用回帰なし（他 42 件不変）。

### 結果

major task 2（notes.py の契約 import 移行）完了。`ResearchNote` は契約の単一実体に一本化され、
縮約アルゴリズムは不変。Req 1.2 / 3.1 / 3.2 / 3.3 / 4.x 充足。次は major task 3
（compaction DI シームの本線配線）。

---

## Task 3.1 — reflect ループ digest seam（`digest_fn` 注入 + byte 互換ロック）

### RED

- 新規 `tests/unit/test_researcher.py` を作成（boundary 通り）。プロンプト捕捉モデル
  `_PromptCapture`（`__call__` で reflect/compression プロンプトを stage 別記録、output schema の
  `enough`/`cited_sources` で分岐）を用意。
- 3 ケース: (a) `compact_digest` 注入で reflect プロンプトがノート縮約 digest、(b) 既定で reflect
  プロンプト ＝ `_results_digest(collected)` から独立構築した期待文字列と `==` 完全一致、
  (c) compression ターンは full `_results_digest` 維持。
- `FunctionModel` が `function.__name__` を参照するため callable クラスへ `__name__` 明示が必要
  （初回 `AttributeError` で判明、blind retry せず根因対処）。
- 確認: (a)(c) が `TypeError: unexpected keyword 'digest_fn'` で赤、(b) は変更前から緑（回帰ガード）。
  → **2 failed / 1 passed**（設計どおりの赤）。

### GREEN

- `run_subquestion` へ `digest_fn: Callable[[Sequence[SearchResult]], str] = _results_digest` を追加
  （reflect ループ限定で `digest_fn(collected)`）。compression は `_results_digest(collected)` full 維持（ADR-A）。
- `_results_digest` 引数型を `list[SearchResult]` → `Sequence[SearchResult]` へ拡幅。
- `Callable` / `Sequence` を TYPE_CHECKING ブロックへ追加。docstring に `digest_fn` を追記。

### 根本原因メモ

- pyright `reportPrivateUsage`（`_results_digest` の white-box import）は **診断行 = symbol 行**に
  ignore を付ける必要があり、多行 import の `(` 開き括弧行では抑止されない。`_results_digest,` 行へ
  移動して解消（magic trailing comma で多行形を維持）。
- ruff I001: 説明コメント＋空行が first-party import を分断 → `ruff check --fix` で括弧形に整理。

### 検証（lane gate, `uv run`）

- `ruff check .` → All checks passed
- `ruff format --check .` → 25 files already formatted
- `pyright` → 0 errors, 0 warnings, 0 informations
- `pytest --cov` → **47 passed, 1 skipped**、`researcher.py` 100%、TOTAL 100.00%（`fail_under=98` 到達）。

### 結果

Task 3.1 完了。reflect digest が注入可能シーム化され、既定は byte 互換（関数同一性に非依拠の
プロンプト一致ロックで固定）、compression は grounding 保全のため full digest 維持。
Req 1.1 / 1.2 / 1.3 / 1.4 / 4.1 / 4.2 / 4.3 を充足。次は 3.2（`Finding.notes` 充填）・3.3（`run_deep_research` 透過、(P)）。

---

## Task 3.2 — `Finding.notes` 充填（凝縮ハンドオフ）

### RED

- `test_researcher.py` に 3 ケース追加。`_run` ヘルパを `-> Finding` 化し戻り値を検査可能に。
- (1) 既定 digest で `finding.notes == distill_notes(collected)`（populated）、(2) `compact_digest`
  注入でも notes 同一（reflect シーム非依存）、(3) 空 collected の loud-fail（`EmptyCitationError`）＋
  `distill_notes([]) == []`。
- 確認: (1)(2) が赤（`finding.notes` は契約既定 `[]` ↔ distilled 非空）、(3) と 3.1 の 3 件は緑
  → **2 failed / 4 passed**（設計どおりの赤）。

### GREEN

- `researcher.py`: `from patterns_deep_research.notes import distill_notes`（runtime、compression import 直後、循環なし）。
- Finding コンストラクタへ `notes=distill_notes(collected)` を追加（生トランスクリプト非伝播、Req 2.2）。

### 根本原因メモ（仕様内テンション）

- plan の edge「空 collected → `Finding.notes=[]`（安全既定）」は `run_subquestion` happy path では
  **到達不能**。`map_citations` が空 collected で `EmptyCitationError`（cited 空）/`DanglingCitationError`
  （cited 非空）を先に loud-fail し Finding を返さないため。STOP→根因調査の結果、誠実な固定として
  「populated で notes==distill_notes(collected) を赤→緑」＋「空入力は loud-fail＋distill_notes([])==[]」
  を採用（観測不能な空 Finding を捏造しない）。安全既定 [] は契約 default として保持。

### 検証（lane gate, `uv run`）

- `ruff check .` → All checks passed
- `ruff format --check .` → 25 files already formatted
- `pyright` → 0 errors, 0 warnings, 0 informations
- `pytest --cov` → **50 passed, 1 skipped**、`researcher.py` 100%、TOTAL 100.00%（`fail_under=98` 到達）。

### 結果

Task 3.2 完了。ハンドオフが「凝縮サマリ + distill ノート」に固定され生トランスクリプト非伝播（Req 2.2）。
Req 2.2 / 4.1 / 4.2 / 4.3 充足。残り major task 3 は 3.3（`run_deep_research` への `digest_fn` 透過、(P)）。

---

## Task 3.3 — `run_deep_research` への `digest_fn` 透過（end-to-end opt-in）

### RED

- 新規 `tests/unit/test_research.py`。`_PipelineCapture`（full pipeline 用、plan/reflect/compression/
  report を schema 分岐し reflect プロンプトを記録）で sub-researcher の reflect digest を捕捉。
- (1) 既定で `_results_digest` が end-to-end 維持（変更前から緑＝回帰ロック）、(2) `digest_fn=compact_digest`
  注入が sub-researcher の reflect プロンプトへ伝播（赤）。
- 確認: (2) が `TypeError: unexpected keyword 'digest_fn'` で赤、(1) は緑 → **1 failed / 1 passed**。

### GREEN（plan 逸脱を含む設計判断）

- `run_deep_research` に `digest_fn: Callable[[Sequence[SearchResult]], str] | None = None` を追加。
- `_research` で注入時のみ `run_subquestion(..., digest_fn=digest_fn)` へ透過、未注入（None）は
  researcher 側の `_results_digest` 既定に委譲（明示 if/else 分岐）。
- TYPE_CHECKING へ `Sequence` / `SearchResult` 追加、docstring に `digest_fn` 追記。

### 根本原因メモ（2 つの設計判断）

1. **plan 逸脱（意図的）**: plan は `digest_fn = _results_digest` を指定するが、それには研究者の
   private `_results_digest` を research.py へ import する必要があり、**src へ
   `# pyright: ignore[reportPrivateUsage]` を強いる**。`| None = None` センチネルにすれば private
   import 不要・suppression ゼロ・レイヤリング改善（reflect-digest 既定は researcher が所有）。
   挙動は既定＝`_results_digest` で plan と等価のため Req 1.1/1.2 を満たす。
2. **`**dict` splat 不採用**: `**({"digest_fn": ...} if ... else {})` は pyright strict が残余 kwarg
   （`instrumentation: InstrumentationSettings | None`）へ `Callable` を割当不可と判定し reject。
   明示 if/else 分岐で型安全＋両分岐 100% 被覆（既定は既存テスト群、else は注入テスト）。

### 検証（lane gate, `uv run`）

- `ruff check .` → All checks passed
- `ruff format --check .` → 26 files already formatted
- `pyright` → 0 errors, 0 warnings, 0 informations
- `pytest --cov` → **52 passed, 1 skipped**、`research.py` / `researcher.py` 100%、TOTAL 100.00%。

### 結果

Task 3.3 完了。`run_deep_research` が `digest_fn` を公開し全 sub-researcher の reflect ループへ透過、
end-to-end opt-in が成立（既定は現挙動互換）。Req 1.1 / 1.2 / 4.1 / 4.3 充足。
**major task 3（compaction DI シーム本線配線）完了**：reflect 注入（3.1）+ Finding.notes 充填（3.2）+
end-to-end 透過（3.3）。残りは major task 4（ドキュメント反映、4.1 / 4.2 / 4.3）。
