# Act Phase — 011-eval-graders

PDCA Act: 学びを再利用可能なパターン/予防策へ形式化する。`/sdd-reflect` が生成。

## Check Phase Summary

18/18 受け入れ条件を充足し、3 レーン（contracts / deep-research / pydantic-ai）全テスト緑・
カバレッジ floor 超過・後方互換維持を再実行で実証。設計からの逸脱はゼロで、tasks.md が予告した
sequenced-red（drift 4 本の一時赤 → 登録で緑化）も計画どおりに発生・解消した。

## Outcome

**Success** — 計画完全達成・本番運用可能・残課題なし。

## Success Pattern OR Mistake Record

### Pattern（成功パターン）

- **Problem**: ドリフトテスト + カバレッジ ratchet + pyright strict で**凍結済み**の契約パッケージへ、
  既存 6 パターン契約・parser・他レーンを一切壊さずに**新しい横断契約**を追加したい。素朴に `__all__` を
  広げると drift parser が「package に在るが README 正本に無い」を検知して赤化し、parser を改修すると
  凍結不変条件が揺らぐ。
- **Solution**: **parser-symmetric な契約形状の設計** ×**計画済 sequenced-red の順序付け**。
  (1) 新シンボルを既存 drift parser が両側対称に照合できる構文形へ寄せる（`Rating` は col-0 名前付き
  `Literal` 代入 = `_collect_named_literals` が拾う形、`Judge[SubjectT](Protocol)` は `model_fields` を
  持たず parser が `Tool` 同様スキップ → 型整合は pyright strict の責務へ委譲）。(2) 実装→ scoped test 緑化の
  時点で drift が**意図的に赤**になることを task 分割で予告し、横断 README 正本作成 → `_README_PATHS` へ
  **1 行登録**のみで緑化する（parser 本体は無改修）。
- **Implementation**:
  1. 契約実体を `eval_graders.py` に純加算し、`__init__.py` の `__all__` をアルファベット順に拡張。
  2. ここで drift 4 本が赤 → これを「defect ではなく sequenced state」と do.md/tasks.md に明記。
  3. `## パターン契約` 見出し直後の最初の `python` fence に正本ブロックを置いた横断 README を作成。
     登録前に drift parser の `_normative_block`/`_collect_named_literals`/`_collect_model` を README へ
     直接適用し、package shape との一致を**機械的に事前検証**（緑化を裏付けてから登録）。
  4. `_README_PATHS` に 1 行追加して緑化。
- **Benefits**: 凍結契約の不変条件（1 クラス = 1 README 所有 / parser 無改修 / 後方互換）を保ったまま
  横展開でき、単一ソース化を drift テスト 1 点で機械保証。赤を「想定どおり」と区別することで blind-retry を防ぐ。
- **Evidence**: `patterns/contracts/src/patterns_contracts/eval_graders.py`、
  `patterns/EVAL-GRADERS.md`、`test_contract_drift.py` の `_README_PATHS`（1 行追加）。
  drift 4 passed / contracts 51 passed・cov 100%。
- Saved to: `.sdd/patterns/drift-parser-symmetric-contract-addition.md`

## Learnings → Rules Mapping

| Learning | Candidate rule / steering update |
|----------|----------------------------------|
| 凍結契約への新規追加は parser-symmetric 設計で parser 無改修にできる | steering: 「drift-guarded 契約の追加は parser を改修せず、新シンボルを既存 parser の照合形へ寄せる」を契約追加チェックリストへ |
| `__all__` 拡張 → 正本登録の間に drift が一時赤化するのは設計どおり | tasks-generation rule: drift-guarded 契約タスクは「sequenced-red を明記し closing task を指定する」を必須化 |
| 登録前に drift parser 関数を README へ直接適用して一致を事前検証できる | pattern として記録（緑化を機械的に裏付けてから登録 = 投機的コミット回避） |
| 横断 README は `patterns/` 直下（`<pattern>/README.md` 形式と差異） | EVAL-GRADERS.md を「初の横断 README」として patterns/README.md 索引に明記済（恒久ドキュメント反映済） |
| フェイク judge 判定を被採点 subject（`stop_reason` / `notes`）由来にすると台本焼き込み（同義反復）を回避 | test-strategy: 「決定論フェイクは定数台本でなく subject 連動で導出」を eval テスト指針へ |

## Process Improvements

- drift-guarded パッケージへの契約追加では、`/sdd-tasks` 段階で sequenced-red の発生点と
  closing task を **Implementation Notes に明示**する運用が有効だった（今回 do.md の root-cause 分析が
  blind-retry を未然に防いだ）。次サイクルもこの「赤の所在と解消タスクを事前宣言する」運用を継続。
- doc-only タスク（verification.md）は自動ゲートが無いため、`⚠️ no automated command` と回帰確認
  （契約スイート再実行で無変化）をセットで記録する運用を標準化する。

## Next Actions

- （任意）将来拡張として記録のみ — ランタイム収束ゲート ↔ オフライン `GradeReport` の橋渡し、
  残り 3 パターン（prompt-chaining / routing / parallelization / orchestrator-workers）への横展開、
  ライブ LLM judge の runtime 実装。いずれも本 spec では明示的 Out of Scope。
- `/sdd-validate-impl` 未実行であれば次に実行（本 reflect は再実行で gate 緑を実測済み）。
- PR 化は未着手。ユーザー指示があれば `011-eval-graders` ブランチから main への PR を作成。
