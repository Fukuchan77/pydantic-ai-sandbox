# Orchestrator-Workers パターン（Anthropic taxonomy / IBM: Agentic AI 粒度）

プランナ LLM が動的にサブタスクを生成し（コードではなくモデルが分解を
決める点が parallelization との違い）、並列ワーカーの結果を
シンセサイザが統合する3段ワークフロー。

## パターン契約（正本）

```python
class SubTask(BaseModel):
    description: str

class TaskPlan(BaseModel):
    subtasks: list[SubTask]

class WorkerResult(BaseModel):
    subtask: SubTask
    output: str

class OrchestratedResult(BaseModel):
    plan: TaskPlan          # プランナの「全」出力を保持
    results: list[WorkerResult]  # max_workers 件以下、プラン順
    summary: str
    truncated: bool         # 上限による切り捨ての可視化（Req 3.2）

async def run_orchestrator(task: str, *, model/llm, max_workers: int = 3) -> OrchestratedResult: ...
```

不変条件: `max_workers >= 1`（違反は ValueError）、
`len(results) <= max_workers`、results はプランのサブタスク順（Req 3.3）。

## 3実装

| レーン | fan-out 機構 | 順序保証 |
|---|---|---|
| [pydantic-ai](../frameworks/pydantic-ai/src/patterns_pydantic_ai/orchestrator_workers.py) | `asyncio.gather` | gather が入力順を保持 |
| [beeai](../frameworks/beeai/src/patterns_beeai/orchestrator_workers.py) | work ステップ内 `asyncio.gather`（ステートマシンは単一カーソル） | 同上 |
| [llamaindex](../frameworks/llamaindex/src/patterns_llamaindex/orchestrator_workers.py) | `ctx.send_event` → `@step(num_workers=8)` → `ctx.collect_events` | 到着順は不定 → **index で明示再ソート** |

## 必須4セクション

### 型安全

- プランは `TaskPlan` への構造化出力で受け、各レーンの検証面
  （routing と同じ分岐）を通る。
- `OrchestratedResult.truncated` により「上限が発動したか」が型レベルで
  判別可能 — 呼び出し側の分岐を文字列パースに頼らせない。
- LlamaIndex のイベント（`_WorkerEvent`/`_ResultEvent`）は型付きフィールド
  で宣言し、collect 後に index で復元（暗黙の到着順依存を排除）。

### テスト

- 正常系（プラン順保持）/ 上限超過（4サブタスク × max_workers=2 →
  results 2件 + truncated=True + plan は4件保持）/ `max_workers=0` 拒否、
  の3点を3レーン共通で実施。
- フェイクはプラン JSON を缶詰返却（routing と同じフェイク基盤を共用）。
- 結合（Ollama）: results >= 1 / summary 非空のみ（Req 5.2）。

### 可観測性

- routing と同一の計装手段（レーン毎）。並列ワーカーのスパンは
  PydanticAI / LlamaIndex ではワーカー毎に出る。BeeAI は手動スパン
  （パターン粒度）のみ。
- 並列実行では親スパンへのトークン集計が二重計上しやすい —
  末端 LLM スパンのみをフィルタすること（research.md R-5）。

### セキュリティ

- **Unbounded Consumption / 過剰エージェンシー緩和**: `max_workers` が
  LLM 呼び出し数の上限を構成する。プランナがいくら多くのサブタスクを
  生成しても実行は上限まで（OWASP Agentic AI）。切り捨ては silent でなく
  `truncated` で監査可能。
- ワーカープロンプトには元タスク + サブタスク記述のみを渡す
  （ワーカー間の情報流通なし = 影響範囲の限定）。
- 依存フロアは [SECURITY-NOTES.md](../SECURITY-NOTES.md)。
