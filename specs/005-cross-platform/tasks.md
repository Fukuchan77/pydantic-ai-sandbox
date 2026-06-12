# 005-cross-platform — Tasks

| ID | タスク | 対応 Req | 状態 |
|---|---|---|---|
| T1 | SDD 起票（idea2 + spec/plan/research/tasks） | — | DONE |
| T2 | ルートガード（ruff/pyright/pre-commit の patterns/ 除外、dependabot 追加）+ `mise run check` グリーン確認 | 7.4, 9.2 | DONE |
| T3 | 3レーンのスキャフォールド（pyproject / src 骨格 / contracts / フェイク / スモークテスト）+ mise patterns:* タスク | 1.1, 1.2, 4.1, 4.2, 9.1 | TODO |
| T4 | patterns-ci.yml（スモーク段階で稼働開始） | 8.1, 8.3 | TODO |
| T5 | routing ×3 実装 + ユニットテスト + patterns/routing/README.md | 2.*, 4.3, 10.2 | TODO |
| T6 | orchestrator-workers ×3 実装 + ユニットテスト + README | 3.*, 4.3, 10.2 | TODO |
| T7 | observability ×3 + InMemorySpanExporter スパンテスト | 6.* | TODO |
| T8 | ゲート付き Ollama 結合テスト ×3 + patterns-integration-ollama.yml | 5.*, 8.2 | TODO |
| T9 | patterns/README.md タクソノミー + SECURITY-NOTES.md + レーン README + 最終ゲート（patterns:check / patterns:audit） | 1.3, 1.4, 7.1, 10.* | TODO |

## 検証コマンド（plan §4-6 / spec Req 9）

```bash
mise run check                                      # 既存ゲート無影響（Req 9.2）
mise run patterns:setup && mise run patterns:check  # 3レーン・オフライン
mise run patterns:audit
RUN_INTEGRATION_PATTERNS=1 mise run patterns:test:integration   # 要ローカル Ollama
uv run pre-commit run --all-files
```
