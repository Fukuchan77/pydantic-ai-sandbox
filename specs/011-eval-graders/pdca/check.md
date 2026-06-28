# Check Phase — 011-eval-graders

PDCA Check: 実装結果（Do）を計画（Plan/Spec/Tasks）の期待と照合する。
`/sdd-reflect` が `pdca/check.md` 不在のため生成（証拠は再実行で再現確認済み）。

## Expectations vs. Results

| 期待（plan/tasks 由来） | 結果（do + 再実行検証） | 状態 |
|-------------------------|------------------------|------|
| 共有グレーダ契約 `Rating` / `AxisScore` / `GradeReport` / `Judge[SubjectT]` を依存ゼロ `patterns_contracts` へ純加算し root からフラット再エクスポート（R1.1–1.3, 1.5, 2.1, 3.1, 3.3） | `eval_graders.py` 実装 + `__init__.py` 再エクスポート。`test_eval_graders.py` 17 passed。 | ✅ |
| 横断 README `patterns/EVAL-GRADERS.md` を正本化し `_README_PATHS` 登録、parser 無改修でドリフト緑（R1.4, 1.6, 4.3, 5.1） | 初の横断 README 作成。`_README_PATHS` 1 行追加のみ。drift 4 passed。 | ✅ |
| deep-research が同一契約を import・構築、`Finding.notes` を採点対象に含め空/低信号 `key_point`→`Unknown`（R2.3, 2.4, 4.2） | 純粋ヘルパ `faithfulness_rating_for` + フェイク `Judge[ResearchReport]`。9 passed、レーン全体 62 passed。 | ✅ |
| pydantic-ai の evaluator-optimizer / autonomous-agent が同一契約を参照、ガードレールは behavior 軸（R2.1, 4.2） | フェイク 2 種（判定を `stop_reason` 由来）。6 passed、レーン全体 56 passed。 | ✅ |
| 既存ランタイム契約（`OptimizationResult`/`ResearchReport`/`AgentRunResult`）後方互換維持（R2.2） | 既存契約テスト無改変のまま 51 passed に含まれ緑維持。 | ✅ |
| ドキュメント同期：索引・import 面・各パターン評価節参照・verification.md 観点6（R5.1, 5.2） | README ×5 + verification.md 更新。one-README 不変条件遵守（正本ブロック無改変）。観点6 を ✅準拠→✅一致 へ格上げ。 | ✅ |

## Test & Quality Outcomes

再実行（2026-06-28）で全レーン緑を確認：

- **contracts**: `51 passed`、Total coverage **100.00%**（floor 85）。
- **deep-research**: `62 passed, 1 skipped`、Total coverage **100.00%**（floor 98）。
- **pydantic-ai**: `56 passed, 6 skipped`、Total coverage **99.15%**（floor 98）。
- Lint（ruff）/ Format（ruff format --check）/ Typecheck（pyright strict）: 各レーン do.md 記録時点で全緑。
- ネットワーク I/O: 全グレーディングテストが決定論フェイク judge のみ（hermetic, R4.1 充足）。

## Requirements Coverage

- Covered: **18/18 受け入れ条件 (100%)** — R1(1.1–1.6) / R2(2.1–2.4) / R3(3.1–3.3) / R4(4.1–4.3) / R5(5.1–5.2)。
- Gaps: なし。
- 全タスク（1.1–5.2）が `[x]` 完了、各タスクが requirement ID へトレース。

## Deviations from Design

- 設計からの逸脱なし。tasks.md の Implementation Notes が予告した **sequenced-red**（Task 1.2 で
  `__all__` 拡張 → drift 4 本が一時赤 → Task 2.2 で緑化）が計画どおり発生・解消。defect ではなく
  task 分割の中間状態であり fix-forward 不要だった。
- pydantic-ai レーンのフェイク判定を `subject.stop_reason` 由来にしたのは tasks.md「台本焼き込み回避」
  方針の範囲内（定数台本ではなく被採点サブジェクト連動の決定論フェイク）。

## Issues Encountered

| Issue | Root cause | Resolution |
|-------|-----------|------------|
| Task 1.2 後に drift 4 本が赤化 | drift parser が `__all__` introspect ↔ README 正本の双方向照合。export 面拡張に正本が追従していない中間状態。 | 計画済 sequenced-red。Task 2.1（正本作成）→ 2.2（`_README_PATHS` 登録）で緑化。 |
| Serena `replace_content` が language server 不在で失敗 | 契約レーンに LSP 未起動。 | Edit ツールへフォールバック（既読ファイルゆえ可）。 |
| `verification.md` に自動ゲートが無い | `specs/` 配下でどのテストも parse しない doc。 | 回帰確認として契約スイート 51 passed を再実行し無変化を担保（⚠️ no automated command を明示記録）。 |

## Assessment

実装は計画を完全に満たした。18/18 受け入れ条件を充足し、3 レーン全テスト緑・カバレッジ floor 超過・
後方互換維持を再実行で実証。横断契約の単一ソース化（`GradeReport`）をドリフトテスト 1 点で機械保証する
構造が確立され、本番運用可能。残課題は無く、将来拡張（ランタイムゲート↔オフライン採点の橋渡し、
6 パターン全展開、ライブ judge）は明示的に Out of Scope。
