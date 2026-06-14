# patterns-contracts — 共有契約パッケージ

クロスフレームワーク・パターン集（Spec 006-2a）の **依存ゼロ契約パッケージ**。
6パターン（routing / orchestrator-workers / prompt-chaining / parallelization /
evaluator-optimizer / autonomous-agent）の入出力 Pydantic モデル・`Literal` 語彙・
autonomous-agent のツール抽象（`Tool` Protocol / `ApprovalHook` 型エイリアス）を
**唯一の実体**として保持する。

## 設計方針

- **唯一の実体**: 契約型の定義はこのパッケージにのみ存在する。各レーン
  （`patterns/frameworks/*`）は旧 `contracts.py` の複製を持たず、
  `tool.uv.sources` のパス依存で本パッケージを import する（レーン間 import は
  禁止 / NFR-3）。
- **正本との二重化**: 各モデルの正本（フィールド定義と `Literal` 語彙）は
  対応する `patterns/<pattern>/README.md` の ```python fenced block にも記載され、
  単一点ドリフトテスト（`tests/unit/test_contract_drift.py`、Task 2）が
  README 正本とパッケージ実体の一致を検証する。
- **依存ゼロ**: runtime 依存は `pydantic>=2` のみ（Principle III / NFR-5）。
- **クロスバージョン install**: `requires-python >=3.13`（全3レーンの下限。
  beeai/llamaindex=3.13、pydantic-ai=3.14）でピンし、`.python-version`=3.13 で
  固定する。pyright も 3.13 ターゲットのため 3.14 専用構文は拒否される。

## import 面

```python
from patterns_contracts import (
    # routing / orchestrator-workers（005 から移行）
    Route, RouteDecision, RoutedAnswer,
    SubTask, TaskPlan, WorkerResult, OrchestratedResult,
    # prompt-chaining
    ChainStep, GateOutcome, ChainResult,
    # parallelization
    Branch, ParallelResult,
    # evaluator-optimizer
    Iteration, OptimizationResult,
    # autonomous-agent
    AgentStep, AgentRunResult, Tool, ApprovalHook,
)
```

> 注: フラット再エクスポートはサブモジュール移植（Task 1.2 / 1.3）と
> 再エクスポート確立（Task 1.4）で段階的に有効化される。本スケルトン時点では
> `__init__` は何も再エクスポートしない。

## セットアップ / 実行

```bash
uv sync --all-groups          # Python 3.13 / 独立 venv
uv run pytest                 # 契約ドリフトテスト（ネットワーク不要、Task 2 以降）
uv run ruff check . && uv run ruff format --check . && uv run pyright
```
