# Evaluator-Optimizer パターン（Anthropic taxonomy / IBM: Agentic Workflow 粒度）

生成器が候補を作り、評価器が `pass` / `revise` を判定するループ。`revise` の
フィードバックを次反復の生成器入力へ反映し、`pass` 到達か `max_iterations`
到達で打ち切る。打切理由は `stop_reason` の閉じた語彙で固定する。

## パターン契約（正本）

契約の実体は依存ゼロの [`patterns_contracts`](../contracts/) パッケージ。下記の
Python コードブロックがその**正本**であり、
[`patterns/contracts/tests/unit/test_contract_drift.py`](../contracts/tests/unit/test_contract_drift.py)
が両者（クラス集合・フィールド集合・`Literal` 語彙）の一致を1点で検証する
（Req 2.1–2.3 / NFR-5）。エントリ signature はドキュメント目的で、ドリフト
parser はスキップする。

```python
class Iteration(BaseModel):
    index: int                # 0始まりの反復番号
    candidate: str            # 当該反復の生成候補
    verdict: Literal["pass", "revise"]   # 評価器の判定
    feedback: str             # revise 時に次反復へ渡すフィードバック（Req 5.3）

class OptimizationResult(BaseModel):
    iterations: list[Iteration]  # 生成→評価の記録
    final_output: str            # 最終的に採用（または最後）の候補
    stop_reason: Literal["passed", "max_iterations"]  # 打切理由（Req 5.4）

async def run_evaluator_optimizer(
    task: str, *, model/llm, max_iterations: int = 3
) -> OptimizationResult: ...
```

不変条件: ループは `verdict == "pass"` か `max_iterations` 到達で停止し、
`stop_reason` は `passed` / `max_iterations` 以外を取らない（Req 5.2, 5.4）。

## 3実装

| レーン | generator / evaluator dispatch | 評価器の構造化出力 |
|---|---|---|
| [pydantic-ai](../frameworks/pydantic-ai/src/patterns_pydantic_ai/evaluator_optimizer.py) | generator=`output_type=str` / evaluator=structured `_Evaluation`。dispatch シームは **JSON schema が `verdict` プロパティを露出**するか | フレームワーク検証済みモデルを直接取得（`instrument_model` 注入） |
| [beeai](../frameworks/beeai/src/patterns_beeai/evaluator_optimizer.py) | generator=`llm.create`（plain）/ evaluator=`llm.create_structure`。dispatch は**メソッド分岐** | `_Evaluation.model_validate(output.object)` で契約再検証（語彙外 verdict を loud-fail） |
| [llamaindex](../frameworks/llamaindex/src/patterns_llamaindex/evaluator_optimizer.py) | generator=`llm.acomplete`（plain）/ evaluator=`llm.astructured_predict(_Evaluation, ...)`。dispatch は**プロンプト内容**（quoted `"verdict"`） | 検証済み Pydantic モデルを直接返す（再検証不要なレーン差分） |

3レーンとも **Workflow を使わない plain `for` ループ**（fan-out 無しの純逐次でイベント機構が契約価値を足さないため）。`max_iterations<1` は `ValueError`。

## 必須4セクション

### 型安全

- **構造化出力方式（レーン差分が最も顕著なパターン）**: 評価器のみ構造化出力
  `_Evaluation{verdict,feedback}`（レーン内 private モデル — `index`/`candidate`
  はループが stamp）。取得方式が3レーンで異なる: pydantic-ai=schema-property
  dispatch、beeai=`create_structure` + `model_validate` 再検証、llamaindex=
  `astructured_predict` の直接検証済みモデル。
- `verdict` は `Literal["pass","revise"]`、`stop_reason` は
  `Literal["passed","max_iterations"]` — 早期 return で二値以外を到達不能化
  （Req 5.4）。

### テスト

- ネットワークゼロ（Req 7.3）。**フェイク台本化手段（レーン差分）**:
  pydantic-ai=`verdict_sequenced_model`、beeai=`VerdictSequencedChatModel`、
  llamaindex=`VerdictSequencedLLM` の verdict 列台本フェイクで pass 到達 /
  max_iterations 打切を決定論検証。
- feedback の次反復反映（Req 5.3）は cursor フェイクの出力に現れないため、各
  レーンが**テスト境界ローカル**の記録フェイク（`_recording_model` /
  `_RecordingChatModel` / `_RecordingLLM`）で「2回目 generator プロンプトが
  1回目 evaluator feedback + 前 candidate を含む」をアサートする。
- **オフライン多軸 eval（outcome+behavior グレーダ）**: ランタイムの収束ゲート
  （`verdict` / `stop_reason`）とは**別レイヤ**で、`OptimizationResult` を
  outcome+behavior の多軸 `GradeReport` で採点するオフライン eval を
  [pydantic-ai](../frameworks/pydantic-ai/) の `tests/` が決定論フェイク `Judge` で
  ネットワークゼロ検証する（Spec 011）。共有グレーダ契約の正本・rating rubric・独立
  judge 規律は横断 README [EVAL-GRADERS.md](../EVAL-GRADERS.md) が所有し、本パターンは
  **参照のみ**（`GradeReport` 系をここに再宣言しない＝one-README 不変条件）。

### 可観測性

- 計装はレーン毎（routing と同一の3方式）: pydantic-ai=`instrument_model`
  注入、beeai=手動 `traced`（`pattern.evaluator_optimizer`）、llamaindex=
  OpenInference process-global instrumentor（Workflow 不在でも
  `acomplete`/`astructured_predict` の leaf LLM span が dispatcher 経由で出る）。
- span≥1 を `InMemorySpanExporter` で検証。トークンは末端 LLM span のみ集計
  （research.md R-5）。

### セキュリティ

- **固有リスク = 無制限な反復消費**: 評価器が永遠に `revise` を返すと生成
  ループが止まらない。`max_iterations` が上限を構成し（`<1` は `ValueError`）、
  `stop_reason` の閉じた語彙が打切理由（`passed` / `max_iterations`）を監査
  可能にする（silent 打切の禁止、OWASP Unbounded Consumption）。
- `verdict` 語彙外は loud-fail — 評価器の不正判定で silent に進行しない。
- 依存フロアは [SECURITY-NOTES.md](../SECURITY-NOTES.md)。
