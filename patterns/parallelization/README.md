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

## 3実装

| レーン | fan-out 機構 | 決定論的順序復元 |
|---|---|---|
| [pydantic-ai](../frameworks/pydantic-ai/src/patterns_pydantic_ai/parallelization.py) | `asyncio.gather` | モデル応答が返った瞬間に共有カウンタから `index` を claim（同期フェイクは完了順=カーソル消費順） |
| [beeai](../frameworks/beeai/src/patterns_beeai/parallelization.py) | `asyncio.gather` | 同上（500試行 probe で単一正出力へ収束を実機確認） |
| [llamaindex](../frameworks/llamaindex/src/patterns_llamaindex/parallelization.py) | **Workflows ネイティブ**: `dispatch` → `ctx.send_event` n×`_BranchEvent` → `run_branch`（`@step(num_workers=8)`）→ `collect`（`ctx.collect_events` バリア） | `collect_events` は完了順返却 → `index` で明示ソートし復元を pin（Req 4.4） |

集約は3レーン同型: sectioning=`index` 昇順 join / voting=`Counter` 多数決（strict `>` で同数は first-seen=最小 index タイブレーク、Req 4.3）。`n<1` は `ValueError`（空 fan-out の封鎖）。

## 必須4セクション

### 型安全

- **構造化出力方式（レーン差分）**: 各ブランチ出力は plain-text。aggregate は
  レーンコードが算出（sectioning=join / voting=多数決）して契約
  `ParallelResult` を組み立てる。`variant` は `Literal["sectioning","voting"]`
  で2変種を1契約に閉じる（語彙外 = ValidationError）。
- `len(branches) == n` かつ `branches` は `index` 昇順 — 並列実行の非決定性を
  契約面で吸収し、呼び出し側に到着順を漏らさない。

### テスト

- ネットワークゼロ（Req 7.3）。**フェイク台本化手段（レーン差分）**:
  pydantic-ai=`voting_model`、beeai=`VotingChatModel`、llamaindex=`VotingLLM`
  の投票台本フェイクを利用。いずれも**真の suspension point を持たない同期
  フェイク**であり、`gather` / worker-pool 下で cursor 消費順=完了順を保証して
  決定論を成立させる（実機 probe で裏付け）。
- 割れた票（例 2:1）/ 同数タイブレーク（index 昇順）/ `n` 件順序復元 /
  `n<1` 拒否を3レーン共通で検証。

### 可観測性

- 計装はレーン毎（routing と同一の3方式）: pydantic-ai=`instrument_model`
  注入の leaf `gen_ai` span、beeai=手動 `traced`（`pattern.parallelization`）、
  llamaindex=OpenInference process-global instrumentor。
- 並列実行は親スパンへのトークン二重計上が起きやすい — 末端 LLM span のみを
  集計対象とする（research.md R-5）。span≥1 を `InMemorySpanExporter` で検証。

### セキュリティ

- **固有リスク = Unbounded Consumption**: fan-out 幅 `n` が LLM 呼び出し数の
  上限を構成する。`n<1` を `ValueError` で弾き、空 fan-out / 無制限増殖を封鎖
  （OWASP Agentic AI）。
- voting の多数決・タイブレークは決定論（index 昇順）— 非決定な集約が監査を
  困難にするリスクを排除。
- 依存フロアは [SECURITY-NOTES.md](../SECURITY-NOTES.md)。
