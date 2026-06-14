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

## 3実装

| レーン | 連鎖機構 | 早期終了の構造封鎖 |
|---|---|---|
| [pydantic-ai](../frameworks/pydantic-ai/src/patterns_pydantic_ai/prompt_chaining.py) | 複数 `agent.run` の逐次連結（前ステップ出力を次プロンプトへ） | ゲート不合格でループ脱出し `final_output=None` を返す |
| [beeai](../frameworks/beeai/src/patterns_beeai/prompt_chaining.py) | `Workflow`（Pydantic state）の逐次ステップ | ゲートステップが `Workflow.END` へ遷移（`final_output=None`） |
| [llamaindex](../frameworks/llamaindex/src/patterns_llamaindex/prompt_chaining.py) | `@step` の event-driven 直列連鎖（`outline → _DraftEvent → draft → _FinalizeEvent\|StopEvent → finalize`） | draft ステップが gate 不合格時に終端 `StopEvent`（`final_output=None`）を**直接 emit** し finalize イベントを発行しない |

`GATE_MIN_WORDS=3` のプログラムゲートは3レーン共通。**fan-out は無し**（純逐次連鎖が本パターンの定義）。

## 必須4セクション

### 型安全

- **構造化出力方式（レーン差分）**: 本パターンは各ステップが plain-text 出力で
  足り、構造化出力は不要 — 3レーンとも text completion（pydantic-ai=`agent.run`、
  beeai=Workflow step、llamaindex=`llm.acomplete`）。構造化されるのは契約
  `ChainResult` であり、レーンコードがステップ列・ゲート判定を組み立てる。
- ゲート不合格時に `final_output` を `str | None` の `None` 枝へ倒すことで、
  早期終了が `ChainResult` 単体から型レベルで判別可能（文字列パース不要、Req 3.3）。

### テスト

- ネットワークゼロ（Req 7.3）。**フェイク台本化手段（レーン差分）**: 正常系は
  定数テキストの台本フェイク（beeai=`ScriptedChatModel`、llamaindex=`ScriptedLLM`、
  pydantic-ai=`FunctionModel` ベース）。
- 連鎖（step n プロンプトが step n-1 出力を含む）と早期終了（finalize 未到達）の
  観測には定数フェイクでは不十分なため、各レーンが**テスト境界ローカル**の記録
  フェイク（pydantic-ai `_recording_model` / beeai `_RecordingChatModel` /
  llamaindex `_RecordingLLM`）を定義し、プロンプト連結と呼出回数をアサートする。
- 正常系 + ゲート不合格（`final_output is None`）の2系統を3レーン共通で実施。

### 可観測性

- レーン毎に計装方式が異なる（routing と同一の3方式）: pydantic-ai=
  `instrument_model` 注入で leaf `gen_ai` span、beeai=手動 `traced` スパン
  （`pattern.prompt_chaining`）、llamaindex=OpenInference process-global
  instrumentor。
- いずれも span≥1 を `InMemorySpanExporter` で検証。トークン集計は末端 LLM
  span のみから行う（二重計上回避、research.md R-5）。

### セキュリティ

- **固有リスク = silent な継続**: ゲート不合格を無視してチェーンが進むと、
  検証されていない中間出力が下流ステップへ伝播する。緩和は
  `final_output=None` による早期終了の**型レベル可視化**。
- **進行可否を決めるのはコードでありモデルではない** — ゲートはプログラム検証
  （`GATE_MIN_WORDS`）であり、プロンプトインジェクションでゲートを越えさせる
  余地が無い（autonomous-agent との本質的な違い）。
- 依存フロアは [SECURITY-NOTES.md](../SECURITY-NOTES.md)。
