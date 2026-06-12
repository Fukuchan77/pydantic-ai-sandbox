# 005-cross-platform — Research

ユーザー提供の調査ドキュメント2本（①AI Agent/Agentic AI フレームワーク調査
レポート、②Production Architectures for Agentic AI）の主要主張を 2026-06-11 に
Web 一次情報で検証した。本書はその結果と、設計判断に直結する追加調査をまとめる。

## R-1: 調査ドキュメント検証結果（PydanticAI / FastAPI）

8項目すべて VERIFIED:

| 主張 | 判定 | 根拠 |
|---|---|---|
| v1.106.0 安定 / v2.0.0b6 ベータ | ✅ | PyPI / GitHub releases（検証時点の現行は v1.107.0 / v2.0.0b7、2026-06-10） |
| pydantic-ai-harness + Code Mode + Monty（Rust 製サンドボックス） | ✅ | github.com/pydantic/pydantic-ai-harness、pydantic.dev/docs/ai/harness/code-mode |
| CVE-2026-25580（URL ダウンロード SSRF、v1.56.0 修正） | ✅ | GHSA-2jrp-274c-jhv3、GitLab Advisory DB |
| CVE-2026-46678（IPv4-mapped IPv6 によるブロックリストバイパス、v1.99.0 修正） | ✅ | GHSA-cqp8-fcvh-x7r3 |
| TestModel / FunctionModel / Agent.override / ALLOW_MODEL_REQUESTS | ✅ | ai.pydantic.dev/testing |
| Pydantic Evals（LLMJudge、SpanTree スパンベース評価） | ✅ | ai.pydantic.dev/evals（Contains/MaxDuration の個別確認は省略） |
| MCP / A2A / AG-UI / Durable Execution 対応 | ✅ | ai.pydantic.dev |
| FastAPI 0.135.0+ EventSourceResponse（Rust シリアル化、15s keep-alive、Last-Event-ID） | ✅ | fastapi.tiangolo.com/tutorial/server-sent-events、release notes |

## R-2: 調査ドキュメント検証結果（LlamaIndex / BeeAI / Docling / OWASP）

10項目中9項目を確認:

| 主張 | 判定 | 根拠 / 備考 |
|---|---|---|
| LlamaIndex v0.14.x（v0.14.22 確認） | ✅(部分) | 「document agent and OCR platform」フレーズは実在するが主自己定義は data framework |
| LlamaAgents / llamactl / テンプレート群 | ⚠️ 未検証 | 公式 docs が 403。**本イテレーションでは LlamaAgents 不採用の根拠** |
| LlamaIndex Workflows（@step、StartEvent/StopEvent、Context） | ✅(部分) | PyPI llama-index-workflows。draw_all_possible_flows のみ未確認 |
| CVE-2025-1793（vector store SQLi、v0.12.28 修正） | ✅ | Endor Labs / Snyk。clickhouse 等8統合が対象 |
| CVE-2025-1752（KnowledgeBaseWebReader 再帰 DoS、readers-web 0.3.6 修正） | ✅ | GHSA-7c85-87cp-mr6g |
| CVE-2024-50050（Llama Stack pickle RCE、v0.0.41 修正） | ✅ | Oligo Security。**llama-stack 採用禁止の根拠** |
| BeeAI: IBM/LF、Py+TS、RequirementAgent/HandoffTool/A2A・ACP | ✅(部分) | github.com/i-am-bee/beeai-framework。RequirementAgent は experimental 扱い |
| Docling HybridChunker / Granite-Docling-258M | ✅(部分) | 将来の RAG イテレーションで使用 |
| OWASP Agentic AI Top 10（2025-12 公表）/ LLM Top 10 2025 LLM01 首位 | ✅ | genai.owasp.org ほか |
| beeai-framework-py-starter | ✅(部分) | uv 構成確認 |

**結論**: 両ドキュメントは計画根拠として信頼可能。未確認項目は実装時に実測する。

## R-3: uv workspace 不成立の確証

- beeai-framework の requires-python は `>=3.11,<3.14`（PyPI 確認済）。
- ルートは `>=3.14`。uv workspace は全メンバーの単一解決を要求するため
  交差が空集合となり**構造的に不可能**。→ plan.md AD-1（独立プロジェクト）。

## R-4: レーン毎オフラインフェイクの実現可能性

| レーン | フェイク | 確度 |
|---|---|---|
| pydantic-ai | TestModel / FunctionModel（`tests/support/model_fakes.py` の流儀） | 本リポジトリで実証済 |
| llamaindex | MockLLM は function-calling 非対応の想定 → 構造化出力はスクリプト化フェイク or prompt+JSON パース | 実装時に実測（フォールバック明記） |
| beeai | 公式モック無し（upstream issue #750）。upstream テスト自身が `ChatModel` 継承フェイクを使用 → ScriptedChatModel 自作 | upstream の前例あり。内部 `_create` シグネチャ依存のため厳密ピン必須 |

## R-5: トークン二重計上（可観測性の既知バグ領域）

調査ドキュメント②より: 親スパンと末端 LLM スパンの双方が usage を属性化すると
合計トークンが数倍に膨れる事故が頻発（Langfuse issue #8700 ほか）。対策は
(a) 集計は末端 LLM スパンのみフィルタ、(b) OTel 複数形キー
（prompt_tokens / completion_tokens / total_tokens）への正規化、
(c) ストリーミング時の `stream_options={"include_usage": True}` 明示。
→ 本イテレーションのテストは「スパン存在」のみアサートし、集計検証は
Evals イテレーションへ送る（Spec Req 6.3）。

## R-6: CVE → 依存フロアの対応表

| CVE | 対象 | 本リポジトリへの影響 | 対応 |
|---|---|---|---|
| CVE-2026-25580 / CVE-2026-46678 | pydantic-ai < 1.99.0 | v2.0.0b6 は修正後継（v2 ベータは v1.99.0 より後に分岐） | `>=2.0.0b6` フロア維持 |
| CVE-2025-1793 | llama-index-core <= 0.12.21 の vector store 統合 | 本イテレーションは vector store 不使用 | SECURITY-NOTES に RAG イテレーションのゲートとして記録 |
| CVE-2025-1752 | llama-index-readers-web <= 0.3.5 | 非依存 | 依存追加時 `>=0.3.6` フロア（SECURITY-NOTES 記録） |
| CVE-2024-50050 | llama-stack < 0.0.41 | 非依存 | **採用禁止**（SECURITY-NOTES 記録） |

## R-7: OWASP Agentic AI Top 10 とパターン設計の対応

- **過剰エージェンシー / Insecure Tool Use**: routing の `Literal` 経路語彙固定
  （語彙外は ValidationError）、orchestrator-workers の `max_workers` 上限。
- **Unbounded Consumption**: ワーカー数上限 + 結合テストの契約レベル
  アサーション（出力長に依存しない）。
- **Supply Chain**: レーン毎 uv.lock + pip-audit + dependabot 3 エントリ追加 +
  llama-stack 禁止。
