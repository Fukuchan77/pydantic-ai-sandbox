# Prompt-Chaining パターン（Anthropic taxonomy / IBM: Agentic Workflow 粒度）

タスクを逐次ステップに分解し、各ステップ間にプログラム検証ゲートを置く
ワークフロー。ゲート不合格ならチェーンを早期終了し、`final_output=None` で
silent な継続を禁止する（モデルではなくコードが進行可否を決める点が
autonomous-agent との違い）。

## パターン契約（正本）

契約の実体は依存ゼロの [`patterns_contracts`](../contracts/) パッケージ。下記の
Python コードブロックがその**正本**であり、
[`patterns/contracts/tests/unit/test_contract_drift.py`](../contracts/tests/unit/test_contract_drift.py)
が両者（クラス集合・フィールド集合・`Literal` 語彙）の一致を1点で検証する
（Req 2.1–2.3 / NFR-5）。エントリ signature はドキュメント目的で、ドリフト
parser はスキップする。

```python
class ChainStep(BaseModel):
    name: str                 # チェーン内のステップ識別子
    output: str               # ステップ出力（次ステップの入力になる）

class GateOutcome(BaseModel):
    passed: bool              # ゲートが現時点までのチェーンを受理したか
    detail: str               # 判定理由

class ChainResult(BaseModel):
    steps: list[ChainStep]    # ゲート判定までに実行したステップ列
    gate: GateOutcome
    final_output: str | None = None  # ゲート不合格時は None（早期終了、Req 3.3）

async def run_prompt_chain(input_text: str, *, model/llm) -> ChainResult: ...
```

不変条件: ゲート不合格（`gate.passed is False`）のとき `final_output is None`。
早期終了は `ChainResult` 単体から判別可能でなければならない（Req 3.3）。
