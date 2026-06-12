# Cross-Framework Agent Patterns（Spec 005-cross-platform）

PydanticAI・BeeAI Framework・LlamaIndex Workflows を横断した
エージェント実装ベストプラクティス・パターン集。同一の**パターン契約**
（Pydantic モデル + エントリポイント）を3フレームワークで実装比較する。

## 二軸タクソノミー

縦軸 = Anthropic「Building Effective Agents」のワークフロー分類、
横軸 = IBM の粒度区分（**AI Agent** = 単一タスク構成要素 / **Agentic AI** =
複数エージェントのオーケストレーション）。

| Anthropic パターン | IBM 粒度 | 状態 |
|---|---|---|
| Prompt Chaining | Agentic AI | 将来イテレーション |
| **Routing** | Agentic AI（分類器→専門家の協調） | ✅ [routing/](routing/README.md) |
| Parallelization | Agentic AI | 将来イテレーション |
| **Orchestrator-Workers** | Agentic AI（動的計画→並列実行→統合） | ✅ [orchestrator-workers/](orchestrator-workers/README.md) |
| Evaluator-Optimizer | Agentic AI | 将来イテレーション |
| Autonomous Agent | Agentic AI | 将来イテレーション |
| 単一エージェント（構造化出力・型付きツール） | AI Agent | ルートアプリ `src/pydantic_ai_sandbox` が参照実装 |

> Anthropic の中核主張（逐語）: "Consistently, the most successful
> implementations weren't using complex frameworks or specialized
> libraries. Instead, they were building with simple, composable
> patterns." — 本パターン集は各フレームワークの**最小プリミティブ**で
> パターンを組む方針を踏襲する。

## フレームワーク比較（本イテレーションで実測した差異）

| 比較軸 | PydanticAI (v2 Beta) | BeeAI Framework (0.1.x) | LlamaIndex Workflows (0.14.x) |
|---|---|---|---|
| 制御哲学 | Agent + 型付き出力の合成 | Pydantic state のステートマシン（戻り値で遷移） | 疎結合 step 間の非同期イベント発行/購読 |
| 構造化出力 | `output_type=Model`（検証失敗で自動リトライ） | `create_structure` + **明示再検証が必要** | `astructured_predict`（FC/テキスト補完に自動分岐） |
| 並列 fan-out | `asyncio.gather` | ステップ内 `asyncio.gather`（カーソルは単一） | `ctx.send_event` / `ctx.collect_events`（順序復元が必要） |
| オフラインテスト | TestModel / FunctionModel（公式・一級） | **公式モック無し** → ChatModel 継承フェイク自作（厳密ピン必須） | MockLLM は JSON 不可 → CustomLLM フェイク自作 |
| 可観測性 | `instrument_model`（gen_ai.* ネイティブ） | 依存可能な公式 OTel API 無し → 手動スパン | OpenInference Instrumentor（プロセスグローバル） |
| 型安全（pyright strict） | そのまま通る | ほぼ通る（ProviderName Literal 等は良質） | 上流スタブ不足で限定 ignore が必要 |

## レーン構成

各レーンは**独立 uv プロジェクト**（独自 lockfile / Python / ゲート）。
理由: beeai-framework の `<3.14` 上限とルートの `>=3.14` が uv workspace の
単一解決では両立しない（specs/005-cross-platform/research.md R-3）。

- [frameworks/pydantic-ai/](frameworks/pydantic-ai/README.md) — Python 3.14
- [frameworks/beeai/](frameworks/beeai/README.md) — Python 3.13（上限制約）
- [frameworks/llamaindex/](frameworks/llamaindex/README.md) — Python 3.13

契約はレーン間で複製され、ルートの
`tests/unit/test_patterns_contract_sync.py` がドリフトを検知する。

## 実行

```bash
mise run patterns:setup            # 3レーン同期（uv が 3.13/3.14 を自動解決）
mise run patterns:check            # lint + format + typecheck + test（オフライン）
mise run patterns:audit            # レーン毎 pip-audit
mise run patterns:test:integration # 要ローカル Ollama（RUN_INTEGRATION_PATTERNS=1）
```

CI: `.github/workflows/patterns-ci.yml`（レーンマトリクス）/
`patterns-integration-ollama.yml`（週次 + paths PR）。

## セキュリティ

[SECURITY-NOTES.md](SECURITY-NOTES.md) — CVE 根拠・依存フロア・
OWASP Agentic AI Top 10 マッピング。
