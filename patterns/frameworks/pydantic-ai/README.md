# patterns-pydantic-ai — PydanticAI レーン

クロスフレームワーク・パターン集（Spec 005 / 006-2a）の PydanticAI 実装。
6パターン（routing / orchestrator-workers / prompt-chaining / parallelization /
evaluator-optimizer / autonomous-agent）を提供する。各パターン契約の正本は
`patterns/<pattern>/README.md`、型実体は共有パッケージ `patterns_contracts`
（`tool.uv.sources` のパス依存で import、レーン内に複製を持たない — NFR-3 / NFR-5）。
タクソノミー索引は `patterns/README.md`。

## セットアップ / 実行

```bash
uv sync --all-groups          # Python 3.14 / 独立 venv（ルートとは別解決）
uv run pytest                 # 全6パターンのオフラインユニット（ネットワーク不要）
uv run ruff check . && uv run ruff format --check . && uv run pyright
RUN_INTEGRATION_PATTERNS=1 OLLAMA_MODEL_NAME=<model> uv run pytest tests/integration  # 6パターン live（要ローカル Ollama）
```

各パターンは `run_<pattern>` 非同期エントリ関数として公開され、`model=` 引数で
モデルを注入する（テストは `scripted_model`、結合は Ollama）。

## 構成

| ファイル | 役割 |
|---|---|
| `src/patterns_pydantic_ai/routing.py` | routing: 分類 Agent（`output_type=RouteDecision`）→ 経路別 Agent |
| `src/patterns_pydantic_ai/orchestrator_workers.py` | orchestrator-workers: planner → `asyncio.gather` workers → synthesizer |
| `src/patterns_pydantic_ai/prompt_chaining.py` | prompt-chaining: `run_prompt_chain` — outline→draft→finalize の逐次チェーン、ステップ間にプログラム検証ゲート |
| `src/patterns_pydantic_ai/parallelization.py` | parallelization: `run_parallelization` — `variant` で sectioning / voting を選ぶ並列ファンアウト |
| `src/patterns_pydantic_ai/evaluator_optimizer.py` | evaluator-optimizer: `run_evaluator_optimizer` — generator→evaluator ループ（pass/revise、`max_iterations` 上限） |
| `src/patterns_pydantic_ai/autonomous_agent.py` | autonomous-agent: `run_autonomous_agent` — `Model.request` 直駆動の手動ツールループ。4ガードレール + 閉じた `stop_reason` 語彙をレーンが保持 |
| `src/patterns_pydantic_ai/observability.py` | `configure_tracing()`（OTLP は env 駆動、テストは exporter 注入） |
| 契約（型実体） | 共有 `patterns_contracts` をパス依存で import（レーン内複製なし、NFR-3） |
| `tests/support/model_fakes.py` | `scripted_model`（構造化出力は ToolCallPart、テキストは TextPart） |

## バージョン注意

- `pydantic-ai-slim[openai]>=2.0.0b6` — **V2 はベータ**。ルートアプリと同一
  フロアで追従する（NFR-2）。API 変動はマイナーリリースでも起こり得る。
- CVE-2026-25580 / CVE-2026-46678（SSRF）は v1.99.0 で修正済み。2.x ベータは
  修正後継（`patterns/SECURITY-NOTES.md`）。
