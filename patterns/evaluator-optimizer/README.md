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
