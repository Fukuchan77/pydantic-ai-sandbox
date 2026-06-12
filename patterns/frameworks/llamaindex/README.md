# patterns-llamaindex — LlamaIndex Workflows レーン

クロスフレームワーク・パターン集（Spec 005）の LlamaIndex 実装。
パターン契約の正本は `patterns/routing/README.md` /
`patterns/orchestrator-workers/README.md` を参照。

## セットアップ / 実行

```bash
uv sync --all-groups          # Python 3.13 / 独立 venv（ルートとは別解決）
uv run pytest                 # オフラインユニット（ネットワーク不要）
uv run ruff check . && uv run ruff format --check . && uv run pyright
RUN_INTEGRATION_PATTERNS=1 OLLAMA_MODEL_NAME=<model> uv run pytest tests/integration  # 要ローカル Ollama
```

## 構成

| ファイル | 役割 |
|---|---|
| `src/patterns_llamaindex/contracts.py` | パターン契約（レーン間複製、正本はパターン README） |
| `src/patterns_llamaindex/routing.py` | routing: Workflow `@step classify`（astructured_predict）→ `@step answer` |
| `src/patterns_llamaindex/orchestrator_workers.py` | `ctx.send_event` fan-out → 並列 `work` → `ctx.collect_events` fan-in |
| `src/patterns_llamaindex/observability.py` | `configure_tracing()` + OpenInference `LlamaIndexInstrumentor`（プロセスグローバル） |
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
