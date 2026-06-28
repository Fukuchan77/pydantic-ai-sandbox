# 011-eval-graders — 実装ギャップ分析

> `/sdd-validate-gap` 出力。承認済み要件（EARS, `requirements-generated`）と既存コードベースの差分を
> design 前に整理する。**意思決定ではなく情報と選択肢**を提示する。出力言語 `ja`（spec.json）。

## 分析サマリ

- **本質は「新規契約モジュール（既存契約は無改変） + 初の横断 README」**。`patterns_contracts` に `GradeReport`
  系モデルを追加し、`patterns/EVAL-GRADERS.md` を `_README_PATHS` へ登録する作業は、既存の
  「契約実体＝パッケージ / 正本＝README / 単一点ドリフト」規律にそのまま乗る。ランタイム本線
  （`OptimizationResult` / `ResearchReport` / `AgentRunResult`）には触れない純加算なので後方互換リスクは低い。
- **最大の技術的ギャップは「1–5 rating の型表現」とドリフト parser の整合**。既存 `Literal` は
  **全て文字列値**で、`test_contract_drift.py` の parser は **文字列 Literal しか拾わない**
  （README 側は `isinstance(element.value, str)` で int を捨て、パッケージ側は全 arg を `str()` 化）。
  `Literal[1,2,3,4,5]` を素朴に使うと**両側不一致でドリフトテストが赤化する**（R4.3 と衝突）。要 design 決定。
- **R1.5（rationale 空で構築拒否・loud-fail）は契約規律の方針と緊張関係**。既存契約は「不変条件は
  pipeline 側、契約は plain shape」（Citation ≥1・dangling は pipeline で loud-fail）。一方 1.5 は
  「`GradeReport` の構築を拒否」と明記 → pydantic validator（in-contract）か pipeline かの二択を design で確定する。
- **judge シーム（R3.1/3.2）の所在が未定**。`Tool` Protocol が契約パッケージに居る前例があるため
  `Judge` Protocol を契約へ置く案と、判定ハーネス＋決定論フェイクを各レーン `tests/support/` に置く案がある。
  ADR-3「契約は純データ + judge 最小メタ」とのバランスで決める。
- **推奨は Hybrid**：契約データ型は `patterns_contracts/eval_graders.py`、判定シームは最小の Protocol、
  フェイク judge と 3 パターン参照テストは各レーン test 層。スコープ（3 パターン・eval 限定・永続化なし）に最も整合。

## 要件別ギャップ表

| Req | 必要能力 | 既存コードの状態 | 分類 | 根拠 / 注記 |
|---|---|---|---|---|
| 1.1 | `GradeReport` 単一契約を `patterns_contracts` 実体として提供 | 6+応用パターンの契約モジュール構成が確立（`evaluator_optimizer.py` 等） | 🆕 | 新規 `eval_graders.py` + `__init__.py` フラット再エクスポート（[__init__.py](../../patterns/contracts/src/patterns_contracts/__init__.py)） |
| 1.2 | outcome/behavior 軸分離・各軸 1–5 rating + `Unknown` + rationale | 軸スコア型は不在。`score: float` の素フィールド前例あり（[rag.py:39](../../patterns/contracts/src/patterns_contracts/rag.py#L39)） | 🆕 | **rating の型表現が design 争点**（後述・調査要）。軸別 `AxisScore` を outcome[]/behavior[] に分けて保持する形が素直 |
| 1.3 | 集約スコアを partial credit float | `float` フィールドは多数前例 | ✅ | `aggregate: float` は既存 idiom と一致、追加実装容易 |
| 1.4 | 各 rating 段階（1–5）の rubric 文言定義（Vertex 方式） | rubric を保持する型は不在 | 🆕 | **rubric の所在が design 争点**：型内モデル（`RubricLevel`）に持つか README 正本の散文に置くか |
| 1.5 | rationale 空なら `GradeReport` 構築拒否・loud-fail | pipeline loud-fail 前例（`EmptyCitationError` / `DanglingCitationError`） | 🔧 | **方針緊張**：in-contract `field_validator`（純 pydantic・依存ゼロ維持可）vs pipeline 強制。design 決定 |
| 1.6 | `patterns/EVAL-GRADERS.md` 正本所有 + `_README_PATHS` 登録 + ドリフト一致 | `_README_PATHS` は `<pattern>/README.md` のみ登録（[test_contract_drift.py:49](../../patterns/contracts/tests/unit/test_contract_drift.py#L49)） | 🆕 | **初の横断（非単一パターン）README**。`## パターン契約` 見出し + python fence が必須形式。one-README 不変条件上、`GradeReport` 系は EVAL-GRADERS.md のみで documentに |
| 2.1 | 3 パターンから同一 `GradeReport` を import | 各レーンは `patterns-contracts` パス依存で既に契約 import 済み | 🔧 | 配線は既存。eval/test 側に import 面を足すだけ |
| 2.2 | 既存ランタイム契約を置換せず後方互換・別レイヤ併存 | `OptimizationResult` / `ResearchReport` / `AgentRunResult` は無改変で良い | ✅ | 純加算。ADR-4 と一致、後方互換リスクなし |
| 2.3 | deep-research 採点に `Finding.notes`（distill 済 `ResearchNote`）を含める | `Finding.notes` は spec 010 で追加済（[deep_research.py:148](../../patterns/contracts/src/patterns_contracts/deep_research.py#L148)） | 🆕 | レーン eval テストの採点ロジック（契約形状の変更ではない） |
| 2.4 | 空/低信号 `key_point` を behavior/faithfulness で `Unknown` へマップ | distill は空 snippet→空 key_point を生成しうる（[notes 記述](../../patterns/contracts/src/patterns_contracts/deep_research.py#L110)） | 🆕 | レーン eval テストの判定規律。`Unknown` 表現（1.2）に依存 |
| 3.1 | 被評価系と分離した judge シーム（注入）で self-eval 回避 | `Tool` Protocol / `SearchProvider` / `digest_fn` の DI seam 前例 | 🆕 | **judge シームの所在が design 争点**（契約 Protocol vs レーン局所） |
| 3.2 | 決定論フェイク judge で I/O ゼロ hermetic 検証 | `TestModel`/`FunctionModel`・`ScriptedChatModel`・`CustomLLM` 等フェイク前例（fw 毎に手段差） | 🆕 | フェイク judge を各レーン `tests/support/` に追加。手段はレーン差あり（structure.md §8.4） |
| 3.3 | 純データ + `judge_id` 等の最小メタに限定、self-eval 禁止フラグを型に入れない | — | 🆕/✅ | 契約設計制約。`judge_id: str | None` 等の任意フィールドのみ |
| 4.1 | 全グレーディング unit を I/O ゼロ | unit/integration 境界規律が確立、`pytest_live_guard` あり | ✅ | 既存規律踏襲 |
| 4.2 | 3 パターン eval からの参照を検証 | — | 🆕 | **検証粒度が要検討**：import-site テストをどこに置くか（contracts か各レーンか） |
| 4.3 | 契約ドリフトテストを緑維持 | 単一点ドリフト健在 | 🔧 | **1.2 の rating 表現次第で赤化リスク**（最重要・調査要） |
| 5.1 | EVAL-GRADERS.md 正本 + 各パターン README 評価節に参照追記 | パターン README に「必須4セクション」構造あり | 🆕 | ドキュメント作業 |
| 5.2 | `verification.md` 観点6 へ単一ソース化反映 | [specs/best-practices-review/verification.md](../../specs/best-practices-review/verification.md) | 🆕 | ドキュメント作業 |

凡例: ✅ 既存で充足 / 🔧 部分的（拡張要） / 🆕 新規構築

## 実装アプローチ選択肢

| アプローチ | 適合条件 | コスト | リスク |
|---|---|---|---|
| **A. Extend（既存契約規律へ素直に乗せる）** | 契約 = `eval_graders.py`、正本 = EVAL-GRADERS.md、ドリフト infra 再利用 | 低 | rating の int-Literal でドリフト parser 赤化；横断 README が one-README 不変条件で初ケース |
| **B. Build new（独立グレーディングハーネス / 新レーン）** | judge シーム + フェイク + 採点ロジックを 1 箇所に集約 | 高 | スコープ超過（「3 パターン・eval 限定・永続化なし」に対し過剰）；契約複製の誘惑 |
| **C. Hybrid（推奨）** | 契約データ型は `patterns_contracts`；判定 `Judge` Protocol は最小；フェイク judge と 3 パターン参照テストは各レーン test 層 | 中 | 契約 / シーム / テストの責務境界を明示する設計が必要 |

**推奨 = C（Hybrid）**。根拠：(1) 契約データは単一実体＝`patterns_contracts` でなければ ADR-1/単一ソース化が崩れる、
(2) judge の独立性は ADR-3 どおり**実装規律**（別モデル注入・物理分離）であり、契約は純データに留める、
(3) フェイク judge の手段はフレームワーク毎に異なる（structure.md §8.4）ため、レーン `tests/support/` 局所が自然。
A との差は「judge Protocol を契約に置くか否か」のみで、ここは design で `Tool` 前例（契約に Protocol あり）と
ADR-3（純データ志向）を天秤にかけて確定する。

## plan フェーズで深掘りすべき調査項目（フラグ）

1. **【最重要】1–5 rating の型表現とドリフト parser の整合**。候補：
   - (a) 文字列 Literal `Literal["1","2","3","4","5","unknown"]` → 両側一致・parser 無改修。意味的に rating が文字列になる難点。
   - (b) `rating: int = Field(ge=1, le=5)` + `Unknown` を別表現（`int | None` で None=Unknown、または `Literal["unknown"]` との union）→ rating は Field 制約で 1–5、`int|None` は parser スキップ対象（`score: float` と同じ扱い）。
   - (c) `Literal[1..5]` を使い **drift parser を int Literal 対応に拡張** → 凍結済み共有テスト infra への変更（要慎重・他契約に影響しないか確認）。
   - → **(b) が「parser 無改修 × 整数 rating 維持 × Unknown 明示」で最有力候補**だが、`Unknown` の型表現（sentinel か union か）を確定すること。drift テスト（R4.3）を最優先制約として design する。
2. **rubric 文言の所在（R1.4）**。型内に `RubricLevel`(level:int, descriptor:str) を持つ案 vs EVAL-GRADERS.md 散文に置き型は rating のみ持つ案。Vertex の rating_rubric は**メトリクス定義側**であり**スコア出力側ではない**点を踏まえると、rubric は契約（per-report インスタンス）に毎回載せるより README 正本＋（任意で）定義用の軽量型が自然か。要確定。
3. **R1.5 loud-fail の実装層**。in-contract `field_validator`（純 pydantic・依存ゼロを壊さない・「構築拒否」の文言に最も忠実）vs pipeline loud-fail（Citation 前例と一貫）。`GradeReport の構築を拒否` の文言は validator 寄りだが、契約 plain shape 規律とどう両立させるか design で言語化する。
4. **judge シームの所在（R3.1）**。`Judge` Protocol を `patterns_contracts` に置く（`Tool` 前例）か、レーン局所にするか。置く場合 drift parser は Protocol をスキップ（`model_fields` 無し）するため整合は pyright strict 担保 ＝ `Tool` と同じ扱いで安全。
5. **「3 パターン参照」検証の粒度（R4.2）**。import-site テストを contracts パッケージに置く（3 レーンは別 venv で import 不可な点に注意）か、各レーン unit に 1 本ずつ置くか。レーンが別 Python/venv で resolve される制約（structure.md §8）から、**各レーン側テスト**が現実的。
6. **criterion 名の語彙性**。outcome=`correctness`/`completeness`、behavior=`tool_use_discipline`/`guardrail_adherence`/`faithfulness` は spec 上「例」。閉じた `Literal` 語彙にするか自由 `str` にするか（自由 str なら drift Literal 問題は criterion には波及しない）。
7. **EVAL-GRADERS.md の最小構成**。drift parser は `## パターン契約` 見出し直後の最初の `python` fence を読む。横断 README でもこの形式を厳守し、one-README 不変条件（`GradeReport` 系は他 README に再掲しない）を満たすこと。`patterns/README.md` 索引・`contracts/README.md` の import 面追記も忘れない。

## 次のステップ

- 本ギャップ分析を踏まえ `/sdd-plan 011-eval-graders` で技術プラン（特に上記 1–4 の design 決定）を作成する。
- 要件未承認（`approvals.requirements.approved=false`）。ギャップ分析は要件改訂の入力にもなり得る — 例えば 1.2 の rating 表現は drift 制約から型を逆算する必要があり、要件の「離散 1–5」を型でどう満たすかを plan で確定する。
- `/sdd-plan 011-eval-graders -y` で要件を自動承認しつつ plan へ直行も可。
