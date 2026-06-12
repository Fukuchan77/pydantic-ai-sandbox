# patterns-pydantic-ai — PydanticAI レーン

クロスフレームワーク・パターン集（Spec 005）の PydanticAI 実装。
パターン契約の正本は `patterns/routing/README.md` /
`patterns/orchestrator-workers/README.md` を参照。

## セットアップ / 実行

```bash
uv sync --all-groups          # Python 3.14 / 独立 venv（ルートとは別解決）
uv run pytest                 # オフラインユニット（ネットワーク不要）
uv run ruff check . && uv run ruff format --check . && uv run pyright
RUN_INTEGRATION_PATTERNS=1 OLLAMA_MODEL_NAME=<model> uv run pytest tests/integration  # 要ローカル Ollama
```

## 構成

| ファイル | 役割 |
|---|---|
| `src/patterns_pydantic_ai/contracts.py` | パターン契約（レーン間複製、正本はパターン README） |
| `src/patterns_pydantic_ai/routing.py` | routing: 分類 Agent（`output_type=RouteDecision`）→ 経路別 Agent |
| `src/patterns_pydantic_ai/orchestrator_workers.py` | planner → `asyncio.gather` workers → synthesizer |
| `src/patterns_pydantic_ai/observability.py` | `configure_tracing()`（OTLP は env 駆動、テストは exporter 注入） |
| `tests/support/model_fakes.py` | `scripted_model`（構造化出力は ToolCallPart、テキストは TextPart） |

## バージョン注意

- `pydantic-ai-slim[openai]>=2.0.0b6` — **V2 はベータ**。ルートアプリと同一
  フロアで追従する（NFR-2）。API 変動はマイナーリリースでも起こり得る。
- CVE-2026-25580 / CVE-2026-46678（SSRF）は v1.99.0 で修正済み。2.x ベータは
  修正後継（`patterns/SECURITY-NOTES.md`）。
