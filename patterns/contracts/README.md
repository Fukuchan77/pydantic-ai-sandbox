# patterns-contracts — 共有契約パッケージ

クロスフレームワーク・パターン集（Spec 006-2a 起点、007/008 で拡張）の
**依存ゼロ契約パッケージ**。下記をすべて **唯一の実体**として保持する:

- ワークフロー6パターン（routing / orchestrator-workers / prompt-chaining /
  parallelization / evaluator-optimizer / autonomous-agent）の入出力 Pydantic
  モデル・`Literal` 語彙・autonomous-agent のツール抽象（`Tool` Protocol /
  `ApprovalHook` 型エイリアス）。
- 応用レイヤ契約: RAG（`RetrievedChunk` / `Citation` / `RagAnswer`、Spec 007-2b）
  と SSE 配信（`StepStartedEvent` / `ToolCalledEvent` / `TokenEvent` /
  `CompletedEvent` / `ErrorEvent` と判別共用体 `SseEvent`、Spec 008-2c）。
- 横断評価グレーダ契約（`Rating` / `AxisScore` / `GradeReport` と `Judge[SubjectT]`
  注入シーム、Spec 011）。outcome+behavior を分離した多軸採点の単一ソースで、正本は
  6 パターン README ではなく横断 README [`EVAL-GRADERS.md`](../EVAL-GRADERS.md) が所有する。
- gated live-Ollama 結合ノブ（`LIVE_CONTEXT_WINDOW` / `LIVE_MAX_TOKENS` /
  `LIVE_REQUEST_TIMEOUT_SECONDS` / `LIVE_WORKFLOW_TIMEOUT_SECONDS`）。

## 設計方針

- **唯一の実体**: 契約型の定義はこのパッケージにのみ存在する。各レーン
  （`patterns/frameworks/*` の3フレームワークレーン、および応用レイヤの
  `patterns/rag` / `patterns/sse`）は旧 `contracts.py` の複製を持たず、
  `tool.uv.sources` のパス依存で本パッケージを import する（レーン間 import は
  禁止 / NFR-3）。
- **正本との二重化**: 各モデルの正本（フィールド定義と `Literal` 語彙）は
  対応する `patterns/<pattern>/README.md` の ```python fenced block にも記載され、
  単一点ドリフトテスト（`tests/unit/test_contract_drift.py`、Task 2）が
  README 正本とパッケージ実体の一致を検証する。
- **横断契約の正本所在**: 評価グレーダ（`GradeReport` 系）は個別パターンに属さない
  横断契約のため、正本を 6 パターン README ではなく横断 README
  [`EVAL-GRADERS.md`](../EVAL-GRADERS.md) が所有する（同 README を `_README_PATHS` に
  `eval-graders` として登録し、同一ドリフトテストで検証。Spec 011 / ADR-1）。独立性は
  型制約でなく実装規律（別モデル注入・物理分離）で担保し、契約は純データ＋`judge_id`
  最小メタに限定する（ADR-3）。`Judge[SubjectT]` Protocol は `model_fields` を持たないため
  `Tool` 同様ドリフト parser はスキップする（横断整合は pyright strict の責務）。
- **依存ゼロ**: runtime 依存は `pydantic>=2` のみ（Principle III / NFR-5）。
- **クロスバージョン install**: `requires-python >=3.13`（全レーンの下限。
  beeai/llamaindex/rag=3.13、pydantic-ai/sse=3.14）でピンし、`.python-version`=3.13
  で固定する。pyright も 3.13 ターゲットのため 3.14 専用構文は拒否される。

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
    # RAG（応用レイヤ, 007-2b）
    RetrievedChunk, Citation, RagAnswer,
    # SSE 配信（応用レイヤ, 008-2c）
    StepStartedEvent, ToolCalledEvent, TokenEvent, CompletedEvent, ErrorEvent, SseEvent,
    # 評価グレーダ（横断契約, 011）
    Rating, AxisScore, GradeReport, Judge,
    # gated live-Ollama 結合ノブ
    LIVE_CONTEXT_WINDOW, LIVE_MAX_TOKENS,
    LIVE_REQUEST_TIMEOUT_SECONDS, LIVE_WORKFLOW_TIMEOUT_SECONDS,
)
```

> 注: 上記シンボルはすべて `__init__.py` がサブモジュールからフラット再エクスポート
> 済み（`__all__` が安定 import 面を固定）。各レーンはサブモジュールパスではなく
> `from patterns_contracts import ...` のルート経路に依存する。

## セットアップ / 実行

```bash
uv sync --all-groups          # Python 3.13 / 独立 venv
uv run pytest                 # 契約ドリフトテスト（ネットワーク不要、Task 2 以降）
uv run ruff check . && uv run ruff format --check . && uv run pyright
```
