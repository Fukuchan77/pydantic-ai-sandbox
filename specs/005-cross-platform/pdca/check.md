# 005-cross-platform — PDCA: Check（2026-06-12）

## Req 充足確認

| Req | 判定 | 根拠 |
|---|---|---|
| 1.1–1.5 構造 | ✅ | 3独立 uv プロジェクト（3.14/3.13/3.13）、パターン README ×2（必須4セクション）、patterns/README.md タクソノミー、モデル ID は env のみ |
| 2.* routing | ✅ | 3実装 + 全経路パラメトライズ + 語彙外 ValidationError テスト |
| 3.* orchestrator-workers | ✅ | 3実装 + 上限/切り捨て/順序/max_workers=0 拒否テスト |
| 4.* オフラインテスト | ✅ | フェイク3種、スモーク3本、カバレッジ 97.8–98.0%（>85） |
| 5.* Ollama 結合 | ✅(構成) | RUN_INTEGRATION_PATTERNS ゲート + 契約レベルアサーション。**実機実行は未**（下記残課題） |
| 6.* 可観測性 | ✅ | configure_tracing ×3 + InMemorySpanExporter スパン存在テスト ×3 |
| 7.* セキュリティ | ✅ | SECURITY-NOTES.md、pip-audit クリーン、readers-web/llama-stack 非依存、gitleaks/モデルID ガード全域維持 |
| 8.* CI | ✅(構成) | patterns-ci.yml（fail-fast:false マトリクス）+ patterns-integration-ollama.yml。既存3ワークフロー無変更。**CI 上の green 確認は push 後** |
| 9.* DX | ✅ | mise patterns:* 8タスク。ルート check 無影響（279 passed / 98.83%） |
| 10.* ドキュメント | ✅ | レーン README ×3 + パターン README ×2 + 比較表 |

## 残課題（Act 候補）

1. **結合テストの実機実行**: ローカル/CI の Ollama デーモンでの green 確認が
   未実施（本環境にデーモンなし）。push 後に patterns-integration-ollama.yml
   を workflow_dispatch で起動して確認すること。
2. BeeAI の LLM 呼び出し粒度スパン（上流計装 API 待ち、Accepted Risk）。
3. 残り4パターン / Docling RAG / SSE / A2A / Evals CI（idea2 §3）。
