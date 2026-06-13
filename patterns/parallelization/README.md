# Parallelization パターン（Anthropic taxonomy / IBM: Agentic Workflow 粒度）

同一タスクを並列に fan-out するワークフロー。`variant` 切替で2変種を1契約に
統合する: sectioning（独立サブタスクへ分割して集約）と voting（同一タスクを
`n` 回実行して多数決）。`branches` は完了順に依らず `index` 昇順で決定論復元する。

## パターン契約（正本）

契約の実体は依存ゼロの [`patterns_contracts`](../contracts/) パッケージ。下記の
Python コードブロックがその**正本**であり、
[`patterns/contracts/tests/unit/test_contract_drift.py`](../contracts/tests/unit/test_contract_drift.py)
が両者（クラス集合・フィールド集合・`Literal` 語彙）の一致を1点で検証する
（Req 2.1–2.3 / NFR-5）。エントリ signature はドキュメント目的で、ドリフト
parser はスキップする。

```python
class Branch(BaseModel):
    index: int                # 決定論的順序キー（branches 復元に使用）
    output: str               # ブランチ出力

class ParallelResult(BaseModel):
    variant: Literal["sectioning", "voting"]  # fan-out 変種（Req 4.1）
    branches: list[Branch]    # index 昇順で復元（Req 4.4）
    aggregate: str            # ブランチ横断の集約結果

async def run_parallelization(
    task: str, *, variant: Literal["sectioning", "voting"], model/llm, n: int = 3
) -> ParallelResult: ...
```

不変条件: `len(branches) == n`、`branches` は `index` 昇順。voting の集約は
多数決で、同数時は `index` 昇順の決定論タイブレーク（Req 4.3, 4.4）。
