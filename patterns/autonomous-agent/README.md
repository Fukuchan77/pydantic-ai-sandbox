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
    stop_reason: Literal["completed", "max_iterations", "budget_exceeded", "denied"]  # 語彙固定（Req 6.2）
    total_budget_spent: int           # 全ステップ累積トークン（ge=0、非負）

async def run_autonomous_agent(
    goal: str, *, model/llm, max_iterations: int,
    allowed_tools: Sequence[Tool], approval_hook: ApprovalHook, budget: int,
) -> AgentRunResult: ...
```

ガードレール契約: `max_iterations` 到達 → `stop_reason="max_iterations"`（Req 6.3）/
`allowed_tools` 外のツールは実行拒否（Req 6.4）/ 危険操作は `approval_hook` 否認で
`stop_reason="denied"`（Req 6.5）/ `total_budget_spent > budget` で
`stop_reason="budget_exceeded"`（Req 6.6）。
