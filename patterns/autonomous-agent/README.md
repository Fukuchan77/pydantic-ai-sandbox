# Autonomous-Agent パターン（Anthropic taxonomy / IBM: Agent 粒度）

ツールループ + 環境フィードバック + 停止条件で自律実行する、唯一の「Agent」型
パターン。OWASP Agentic AI Top 10 の主戦場であり、ガードレール4種（最大反復数 /
ツール許可リスト / 危険操作のヒューマン承認フック / ループ毎予算消費記録）を
**契約レベルで全3レーン共通化**する。`stop_reason` の閉じた語彙が、どのガードレール
（または完了）でループが止まったかを記録する。

## パターン契約（正本）

契約の実体は依存ゼロの [`patterns_contracts`](../contracts/) パッケージ。下記の
Python コードブロックがその**正本**であり、
[`patterns/contracts/tests/unit/test_contract_drift.py`](../contracts/tests/unit/test_contract_drift.py)
が両者（クラス集合・フィールド集合・`Literal` 語彙）の一致を1点で検証する
（Req 2.1–2.3 / NFR-5）。エントリ signature・`Tool` Protocol・`ApprovalHook`
エイリアスはドキュメント目的で、ドリフト parser はスキップする（正本一致は
pyright strict が担保。Req 6.1, ADR-7）。

```python
class Tool(Protocol):              # parser スキップ: pyright strict が正本一致を担保
    name: str                      # allowed_tools と照合する識別子（最小権限、Req 6.4）
    dangerous: bool                # True なら呼出前に approval_hook を要する（Req 6.5）
    def run(self, args: str) -> str: ...

ApprovalHook = Callable[[str, str], bool]  # parser スキップ: (tool_name, args) -> approved

class AgentStep(BaseModel):
    index: int                # 0始まりの反復番号
    tool: str                 # 当該反復で呼び出したツール名
    observation: str          # ツールが返した環境フィードバック
    budget_spent: int         # 当該反復のトークン消費（ge=0、非負）

class AgentRunResult(BaseModel):
    steps: list[AgentStep]            # ループ反復の記録
    final_output: str | None = None   # ガードレール発火で未完了時は None
    stop_reason: Literal["completed", "max_iterations", "budget_exceeded", "denied", "disallowed_tool"]  # 語彙固定（Req 6.2）
    total_budget_spent: int           # 全ステップ累積トークン（ge=0、非負）

async def run_autonomous_agent(
    goal: str, *, model/llm, max_iterations: int,
    allowed_tools: Sequence[Tool], approval_hook: ApprovalHook, budget: int,
) -> AgentRunResult: ...
```

ガードレール契約: `max_iterations` 到達 → `stop_reason="max_iterations"`（Req 6.3）/
`allowed_tools` 外のツールは実行せず、試行を記録してループ停止
`stop_reason="disallowed_tool"`（Req 6.4、`denied` とは判別可能なハード停止）/
危険操作は `approval_hook` 否認で `stop_reason="denied"`（Req 6.5）/
`total_budget_spent > budget` で `stop_reason="budget_exceeded"`（Req 6.6）。

## 3実装

| レーン | chat プリミティブ | tool-call 検出 / budget シーム |
|---|---|---|
| [pydantic-ai](../frameworks/pydantic-ai/src/patterns_pydantic_ai/autonomous_agent.py) | `Model.request` 直叩き手動ループ（初の非 `Agent` レーンコード） | native tool part、`_args_text`（dict→sorted-json / None→""）。`_budget_spent = response.usage.total_tokens` |
| [beeai](../frameworks/beeai/src/patterns_beeai/autonomous_agent.py) | `ChatModel.create(messages=...)` | `output.get_tool_calls()`（`MessageToolCallContent`）、args は `str` 固定。`_budget_spent = output.usage.total_tokens if output.usage else 0` |
| [llamaindex](../frameworks/llamaindex/src/patterns_llamaindex/autonomous_agent.py) | `llm.acomplete(transcript)`（completion-only） | **JSON 規約** `{"tool":...,"args":...}` を `_parse_action` で分岐。`_budget_spent = response.raw["usage"]["total_tokens"]`（`_as_mapping` で I/O 境界 narrow） |

3レーンとも手動一様ループで4ガードレールと `stop_reason` Literal を同一化。**fan-out は無し**（逐次ツールループ）。`_budget_spent` を1関数に閉じ込めて予算会計を決定論化（plan「決定論性の核心」）。

## ツール設計（Anthropic「Writing tools for agents」準拠）

本パターンは唯一のツールループ型で、ツールを `allowed_tools: Sequence[Tool]`（最小権限
allow-list = 注入シーム）として受け取る。公式原則（namespacing / token 効率 /
`response_format` / 厳格データモデル / 入力検証 / 最小権限）への準拠状況は
[TOOL-DESIGN-NOTES.md](../TOOL-DESIGN-NOTES.md) に正本として集約し、実演（runnable demo）を
[`tool_design.py`](../frameworks/pydantic-ai/src/patterns_pydantic_ai/tool_design.py)
（解説 [`docs/tool-design.md`](../../docs/tool-design.md)）で提供する。

| 原則 | 準拠 | 要点 |
|---|---|---|
| Namespacing（`<resource>_<verb>`） | ✅ 実演 | `directory_search` / `directory_get` が共通接頭辞 `directory_` を共有 |
| Token 効率（pagination/filter/truncation） | ✅ 実演 | 小さな既定 `limit`（上限クランプ）・`offset`/`next_offset` カーソル・`query` フィルタ・自由記述の可視 truncate |
| `response_format`（concise/detailed） | ✅ 実演 | 既定 `concise`（最小フィールド）、`detailed` 指定時のみ全メタデータ |
| 厳格データモデル / 入力検証 / 最小権限 | ✅ 既存実装 | `output_type` + `patterns_contracts`、noisy 引数の安全劣化、`allowed_tools` ハード停止 |

デモは凍結済みの6パターン契約・他 lane・ドリフト README を変更せず、既存の `Tool` Protocol /
`allowed_tools` シームに差し込む（Spec 006-2a 維持）。BeeAI / LlamaIndex lane への横展開は
将来イテレーション。

## 必須4セクション

### 型安全

- **構造化出力方式（レーン差分）**: tool-call の検出方式が3レーンで異なる —
  native part（pydantic-ai）/ `get_tool_calls()`（beeai）/ JSON 規約 parse
  （llamaindex、CustomLLM は completion-only で native tool part 非対応）。
  契約 `AgentRunResult`/`AgentStep` は3レーン同一。
- `stop_reason` は
  `Literal["completed","max_iterations","budget_exceeded","denied","disallowed_tool"]`
  — どのガードレールで止まったかが型レベルで判別可能。`final_output` は
  `str | None`（ガードレール発火で未完了時は `None`）。

### テスト

- ネットワークゼロ（Req 7.3）。**フェイク台本化手段（レーン差分）**: ターン列
  フェイク（pydantic-ai=`turn_sequenced_model`、beeai=`TurnSequencedChatModel`、
  llamaindex=`TurnSequencedLLM`）+ `FinalTurn` で tool 反復→最終回答の台本を
  供給し、`RequestUsage`/`ChatModelUsage`/`raw` でトークンを決定論注入する。
- budget/raw のエッジ（usage 欠落・非 JSON 最終回答）は台本フェイクでは到達
  不能なため、境界内ローカルフェイク（llamaindex `_RawScriptedLLM` 等）で補う。
- 正常完了 + 4契約違反系（許可リスト違反→停止 / 承認拒否 / 予算超過 /
  max_iterations 打切）を3レーン共通で網羅。

### 可観測性

- 計装はレーン毎（routing と同一の3方式）: pydantic-ai=`instrument_model`
  注入、beeai=手動 `traced`（`pattern.autonomous_agent`）、llamaindex=
  OpenInference process-global instrumentor。span≥1 を `InMemorySpanExporter`
  で検証、トークンは末端 LLM span のみ集計（research.md R-5）。

### セキュリティ

- 本パターンは唯一の「Agent」型で **OWASP Agentic AI Top 10 の主戦場**。固有
  リスクをガードレール4種が契約レベルで緩和する（全3レーン同一）:
  - 過剰エージェンシー / Insecure Tool Use → `allowed_tools` 外は**実行せず、
    拒否を記録してループ停止** `stop_reason="disallowed_tool"`（Req 6.4、
    ハード停止）。
  - Human-in-the-loop bypass → 危険操作は `approval_hook` 否認で
    `stop_reason="denied"`・`final_output=None`（Req 6.5）。
  - Unbounded Consumption → `total_budget_spent > budget` で
    `stop_reason="budget_exceeded"`（Req 6.6）、`max_iterations` 到達で
    `stop_reason="max_iterations"`（Req 6.3）。
- 試行（executed / refused / denied）は全て `steps` に記録 — 監査証跡が
  silent empty にならない（Req 10.3 多層防御）。OWASP リスク項目への詳細
  マッピングは [SECURITY-NOTES.md](../SECURITY-NOTES.md)（Task 11.3 で追記）。
