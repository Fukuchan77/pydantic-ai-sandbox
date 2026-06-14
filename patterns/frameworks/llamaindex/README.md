# patterns-llamaindex — LlamaIndex Workflows レーン

クロスフレームワーク・パターン集（Spec 005 / 006-2a）の LlamaIndex 実装。
6パターン（routing / orchestrator-workers / prompt-chaining / parallelization /
evaluator-optimizer / autonomous-agent）を提供する。各パターン契約の正本は
`patterns/<pattern>/README.md`、型実体は共有パッケージ `patterns_contracts`
（`tool.uv.sources` のパス依存で import、レーン内に複製を持たない — NFR-3 / NFR-5）。
タクソノミー索引は `patterns/README.md`。

## セットアップ / 実行

```bash
uv sync --all-groups          # Python 3.13 / 独立 venv（ルートとは別解決）
uv run pytest                 # 全6パターンのオフラインユニット（ネットワーク不要）
uv run ruff check . && uv run ruff format --check . && uv run pyright
RUN_INTEGRATION_PATTERNS=1 OLLAMA_MODEL_NAME=<model> uv run pytest tests/integration  # 6パターン live（要ローカル Ollama）
```

各パターンは `run_<pattern>` 非同期エントリ関数として公開され、`llm=` 引数で
`LLM` を注入する（テストは `ScriptedLLM`、結合は Ollama）。

## 構成

| ファイル | 役割 |
|---|---|
| `src/patterns_llamaindex/routing.py` | routing: Workflow `@step classify`（astructured_predict）→ `@step answer` |
| `src/patterns_llamaindex/orchestrator_workers.py` | orchestrator-workers: `ctx.send_event` fan-out → 並列 `work` → `ctx.collect_events` fan-in |
| `src/patterns_llamaindex/prompt_chaining.py` | prompt-chaining: `run_prompt_chain` — イベント駆動 `@step` の直列チェーン（outline→draft→finalize）、ステップ間にプログラム検証ゲート |
| `src/patterns_llamaindex/parallelization.py` | parallelization: `run_parallelization` — `variant` で sectioning / voting を選ぶ並列ファンアウト |
| `src/patterns_llamaindex/evaluator_optimizer.py` | evaluator-optimizer: `run_evaluator_optimizer` — generator→evaluator ループ（pass/revise、`max_iterations` 上限） |
| `src/patterns_llamaindex/autonomous_agent.py` | autonomous-agent: `run_autonomous_agent` — `llm.acomplete` 直駆動の手動ツールループ。4ガードレール + 閉じた `stop_reason` 語彙をレーンが保持 |
| `src/patterns_llamaindex/observability.py` | `configure_tracing()` + OpenInference `LlamaIndexInstrumentor`（プロセスグローバル） |
| 契約（型実体） | 共有 `patterns_contracts` をパス依存で import（レーン内複製なし、NFR-3） |
| `tests/support/fake_llm.py` | `ScriptedLLM`（CustomLLM。構造化出力はテキスト補完プログラム + JSON パーサ経由） |

## 設計メモ

- **構造化出力のオフライン化**: `astructured_predict` は LLM の能力に応じて
  function-calling / テキスト補完 + JSON パーサに分岐する。フェイクは
  非 function-calling として後者を踏み、本物（Ollama）は前者を踏む。
  どちらも同じ Pydantic 検証面に着地する（plan §8 R-2 のフォールバック解）。
- **計装はプロセスグローバル**: PydanticAI レーンのモデル単位ラップと異なり、
  `LlamaIndexInstrumentor` は dispatcher 全体をフックする。テストは
  `uninstrument_llamaindex` で必ず解除する。

## バージョン / セキュリティ注意

- `llama-index-core>=0.14`（0.14.22 で検証）。Workflows API は安定化途上。
- **LlamaAgents（llamactl）は不採用**（公式 docs 未検証のため。spec Clarifications）。
- `llama-index-readers-web` 非依存（採用時は >=0.3.6 必須、CVE-2025-1752）。
  `llama-stack` は採用禁止（CVE-2024-50050）。詳細は `patterns/SECURITY-NOTES.md`。
