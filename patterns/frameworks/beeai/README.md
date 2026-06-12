# patterns-beeai — BeeAI Framework レーン

クロスフレームワーク・パターン集（Spec 005）の BeeAI Framework 実装。
パターン契約の正本は `patterns/routing/README.md` /
`patterns/orchestrator-workers/README.md` を参照。

## セットアップ / 実行

```bash
uv sync --all-groups          # Python 3.13 / 独立 venv（beeai-framework は <3.14 上限）
uv run pytest                 # オフラインユニット（ネットワーク不要）
uv run ruff check . && uv run ruff format --check . && uv run pyright
RUN_INTEGRATION_PATTERNS=1 OLLAMA_MODEL_NAME=<model> uv run pytest tests/integration  # 要ローカル Ollama
```

## 構成

| ファイル | 役割 |
|---|---|
| `src/patterns_beeai/contracts.py` | パターン契約（レーン間複製、正本はパターン README） |
| `src/patterns_beeai/routing.py` | routing: Workflow ステートマシン（classify → answer → END） |
| `src/patterns_beeai/orchestrator_workers.py` | plan → work（ステップ内 `asyncio.gather` 並列）→ synthesize |
| `src/patterns_beeai/observability.py` | `configure_tracing()` + `traced()` 手動スパンラッパ |
| `tests/support/fake_chat_model.py` | `ScriptedChatModel`（ChatModel 継承、`_create*` をカンニング実装） |

## 設計メモ

- **構造化出力の明示再検証**: `create_structure` の戻り dict を必ず
  `Model.model_validate` で再検証する（Req 2.3）。バックエンド実装に
  依存せず語彙外経路が `ValidationError`（Workflow 経由では
  `FrameworkError` にラップ、`__cause__` 保持）で失敗する。
- **並列性はステップ内**: BeeAI Workflow は単一カーソルのステートマシンの
  ため、ワーカー並列は work ステップ内の `asyncio.gather` で実現。
- **計装は手動スパン**（plan §8 R-3 フォールバック）: 0.1.x に依存可能な
  公式 OTel 計装 API がないため、`traced()` がパターン実行を外側から包む。

## バージョン / リスク注意

- `beeai-framework==0.1.39` — **厳密ピン**。公式モックが無いため
  （upstream issue #750）フェイクが内部 `_create*` シグネチャに依存しており、
  マイナーバンプでも壊れ得る（plan §8 R-1）。dependabot は個別 PR で浮上。
- RequirementAgent / HandoffTool / A2A・ACP サーバは将来イテレーション
  （マルチエージェント協調）で評価する。
