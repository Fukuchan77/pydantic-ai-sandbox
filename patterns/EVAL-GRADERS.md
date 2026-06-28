# Eval Graders（評価グレーダ）— outcome+behavior 多軸採点の横断契約

outcome（最終成果物）と behavior（過程・振る舞い）を**分離**して多軸採点する
共有グレーダ契約。evaluator-optimizer / deep-research / autonomous-agent の
3 パターンが同一の `GradeReport` を参照し、ランタイム収束ゲートと eval グレーダの
定義ドリフトを 1 点で防ぐ（Spec 011 / 出典: Anthropic「Demystifying evals」、
Google Vertex rubric metrics、AWS Bedrock evals、IBM watsonx agentic eval）。

これは個別パターン固有でない**真に横断的**な契約なので、6 パターン README とは別に
本横断 README が正本を所有する（ADR-1）。

## パターン契約（正本）

契約の実体は依存ゼロの [`patterns_contracts`](contracts/) パッケージ
（[`eval_graders.py`](contracts/src/patterns_contracts/eval_graders.py)）。下記の
Python コードブロックがその**正本**であり、
[`patterns/contracts/tests/unit/test_contract_drift.py`](contracts/tests/unit/test_contract_drift.py)
が両者（クラス集合・フィールド集合・`Literal` 語彙）の一致を 1 点で検証する
（Req 1.6 / 4.3）。`Judge` Protocol は `model_fields` を持たないため、`Tool` 同様に
ドリフト parser はスキップする（横断整合は pyright strict の責務）。

```python
Rating = Literal["1", "2", "3", "4", "5", "unknown"]

class AxisScore(BaseModel):
    criterion: str          # 採点軸名（例 correctness / tool_use_discipline）
    rating: Rating          # 離散 1–5、証拠不足は "unknown"
    rationale: str          # 根拠（空は構築拒否・loud-fail / R1.5）

class GradeReport(BaseModel):
    outcome_scores: list[AxisScore]    # 最終成果物の軸（R1.2 分離保持）
    behavior_scores: list[AxisScore]   # 過程・振る舞いの軸
    aggregate: float                   # partial credit 集約（R1.3）
    judge_id: str | None = None        # judge 出自の最小メタ（R3.3）

class Judge[SubjectT](Protocol):       # 注入シーム（parser スキップ、Tool 前例）
    async def grade(self, subject: SubjectT, /) -> GradeReport: ...
```

不変条件: `AxisScore.rationale` が空/空白のみのとき `GradeReport` 構築は
loud-fail する（silent empty 禁止 / R1.5）。`rating` は `Rating` 語彙以外を
取らない。`aggregate` は `float` だが **NaN/inf は受理しない**（非有限値は
比較を silent に壊すため `allow_inf_nan=False`、silent-empty 禁止と同趣旨）。`Rating` を整数 `Literal[1..5]` でなく**文字列 Literal の名前付き
エイリアス**にしているのは、ドリフト parser が README と package 双方を
対称に語彙一致できるようにするため（AD-1）。独立性（self-eval 回避）は契約型
ではなく実装規律（別モデル注入・物理分離）で担保する（R3.3 / ADR-3）。

## Rating rubric（1–5 + Unknown / Google Vertex rating_rubric 方式）

各軸スコアの `rating` は以下の段階で採点し、`rationale` に根拠を必ず添える。

| rating | 意味 |
|---|---|
| `"5"` | 当該軸を完全に満たす。欠陥・逸脱なし。 |
| `"4"` | おおむね満たす。軽微で実害のない欠点が 1 つ程度。 |
| `"3"` | 部分的に満たす。目立つ欠点があるが致命的ではない。 |
| `"2"` | 多くを満たさない。重大な欠点・逸脱がある。 |
| `"1"` | ほぼ満たさない。誤り・違反が支配的。 |
| `"unknown"` | **証拠不足**で数値採点できない。silent に低評価せず明示する（ADR-2）。 |

最終集約 `aggregate` は partial credit を許す `float`。スケール（例 0.0–1.0 や
重み付き平均）は採点ハーネスが定義し、契約は plain `float` に留める（R1.3）。
`"unknown"` を含む軸を集約へどう織り込むかもハーネスの裁量（契約は強制しない）。

## 採点軸（outcome / behavior の例）

軸名 `criterion` は自由文字列（閉じた語彙にしない＝AD-2）。代表例:

### outcome 軸（最終成果物の品質）

- `correctness` — 出力が事実・要求に対して正しいか（Anthropic / AWS）。
- `completeness` — 要求された範囲を網羅しているか。

### behavior 軸（過程・振る舞いの規律）

- `tool_use_discipline` — ツール選択・呼び出しが適切か（AWS Tool Selection Accuracy）。
- `guardrail_adherence` — ガードレール（承認・許可ツール・予算）を遵守したか。
- `faithfulness` — 出力が参照ソースに忠実で、根拠のない主張をしていないか（IBM faithfulness）。
  deep-research では `ResearchNote.key_point` が空/低信号のとき、この軸を silent に
  スコアせず `"unknown"` へマップする（R2.4）。

## 独立 judge 規律（self-eval バイアス回避）

採点は被評価系と**物理分離**した judge で行う（`Judge[SubjectT]` 注入シーム /
R3.1）。独立性は契約の型制約ではなく**実装規律**で担保する（ADR-3）:

- 生成系（Generator/被評価ランタイム）と評価系（Judge）を別実装・別モデルにする。
- `self_eval_forbidden` のようなフラグは契約に入れない（型で誤った安全感を与えない）。
- 採点の出自は任意の `judge_id` メタで監査証跡として残す（誰が採点したか / IBM）。

## ランタイムゲートとの併存（後方互換 / ADR-4）

`GradeReport` は**オフライン/CI の多軸採点**レイヤであり、各パターンの
**ランタイム収束ゲート（in-the-loop）を置換しない**。
`OptimizationResult`（`verdict: pass|revise`）/ `ResearchReport` /
`AgentRunResult` は無改変のまま維持され、グレーダ契約は純加算で併存する
（R2.2）。in-the-loop の判断点（収束判定）と offline の eval（CI 採点）は
補完的な 2 モードである（IBM / Anthropic）。

## 参照（各パターン eval）

オフライン hermetic eval は別 venv 制約によりレーン側テストに置く（AD-5）:

- evaluator-optimizer / autonomous-agent: [`frameworks/pydantic-ai`](frameworks/pydantic-ai/)
  の `tests/` がフェイク `Judge` で `OptimizationResult` / `AgentRunResult` を採点。
- deep-research: [`deep-research`](deep-research/) の `tests/` がフェイク
  `Judge[ResearchReport]` で `Finding.notes` を含む `ResearchReport` を採点。

各パターン README の評価節は本書を**参照のみ**し、`GradeReport` 系を再宣言しない
（one-README 不変条件）。
