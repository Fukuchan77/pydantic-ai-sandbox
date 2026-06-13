# Routing パターン（Anthropic taxonomy / IBM: Agentic AI 粒度）

分類器がクエリを閉じた経路語彙のいずれかに割り当て、経路別の専門
エージェントに委譲する2段ワークフロー。「個別最適化したプロンプトを
経路毎に持てる」ことが単一巨大プロンプトに対する利点。

## パターン契約（正本）

契約の実体は依存ゼロの [`patterns_contracts`](../contracts/) パッケージ（旧
各レーンの `contracts.py` 複製はここへ移行・廃止、Req 1.5）。下記の Python
コードブロックがその**正本**であり、
[`patterns/contracts/tests/unit/test_contract_drift.py`](../contracts/tests/unit/test_contract_drift.py)
が両者（クラス集合・フィールド集合・`Literal` 語彙）の一致を1点で検証する
（Req 2.1–2.3 / NFR-5）。エントリ signature はドキュメント目的で、ドリフト
parser はスキップする。

```python
Route = Literal["billing", "technical", "general"]

class RouteDecision(BaseModel):
    route: Route
    reasoning: str

class RoutedAnswer(BaseModel):
    route: Route
    answer: str

async def run_routing(query: str, *, model/llm) -> RoutedAnswer: ...
```

## 3実装

| レーン | 分類ステージ | 回答ステージ |
|---|---|---|
| [pydantic-ai](../frameworks/pydantic-ai/src/patterns_pydantic_ai/routing.py) | `Agent[None, RouteDecision]`（`output_type` 検証 + 自動リトライ） | 経路→instructions 辞書から専門 `Agent[None, str]` |
| [beeai](../frameworks/beeai/src/patterns_beeai/routing.py) | Workflow step + `create_structure` + **明示 `model_validate`** | step が SystemMessage を切替え `Workflow.END` へ遷移 |
| [llamaindex](../frameworks/llamaindex/src/patterns_llamaindex/routing.py) | `@step classify` + `astructured_predict` | `_RouteEvent` 購読の `@step answer` → `StopEvent` |

## 必須4セクション

### 型安全

- 経路語彙は `Literal` で閉じる。**語彙外 = ValidationError**（Req 2.3）。
  デフォルト経路への silent fallback は3レーンとも禁止。
- PydanticAI: 検証はフレームワークが実施（失敗時リトライ→最終的に raise）。
- BeeAI: `create_structure` の戻り dict をレーンコードで
  `RouteDecision.model_validate` — バックエンド実装に依存しない保証。
  エラーは `FrameworkError`（`__cause__` に ValidationError）で表面化。
- LlamaIndex: JSON 出力パーサが同じ Pydantic 検証面に着地。
- 経路→instructions 辞書は import 時に語彙との一致をアサート（3レーン共通）。

### テスト

- ネットワークゼロ（Req 4.1）: PydanticAI = `FunctionModel`（出力スキーマの
  プロパティ名で structured/text を分岐）、BeeAI = `ChatModel` 継承
  `ScriptedChatModel`、LlamaIndex = `CustomLLM` 継承 `ScriptedLLM`。
- 全経路パラメトライズ + 語彙外拒否 + 契約検証の3点を各レーンで実施。
- 結合（Ollama）: route が語彙内 / answer 非空のみアサート（Req 5.2）。

### 可観測性

- PydanticAI: `instrument_model` ラップで `gen_ai.*` スパンがネイティブに出る。
- LlamaIndex: OpenInference Instrumentor（プロセスグローバル、テストでは
  必ず uninstrument）。
- BeeAI: `traced()` 手動スパン（フォールバック、SECURITY-NOTES の
  Accepted Risk 参照）。
- トークン集計は末端 LLM スパンのみから行うこと（二重計上問題、
  research.md R-5）。

### セキュリティ

- **過剰エージェンシー緩和**: 閉じた経路語彙そのものが認可境界 —
  分類器が任意の処理系へ委譲することはできない（OWASP Agentic AI）。
- 経路追加は契約変更 = 3レーン + 本 README + 契約同期テストの同時更新を強制。
- 依存フロアは [SECURITY-NOTES.md](../SECURITY-NOTES.md)。
