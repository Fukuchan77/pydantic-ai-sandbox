# 学習パス上の位置づけ / This repo in the learning path（Stage 4–5）

このリポジトリ（`pydantic-ai-sandbox`）は、2 リポを貫く**統一学習パス**の
**Stage 4–5（参照/本番化・ガバナンス）**です。基礎〜応用（Stage 0–3）は入口の
[`agentic-ai-bootcamp`](../../agentic-ai-bootcamp/README.md) で学んでください。

> 統一パスの全体像と公式ソース対応表（入口）：
> **[agentic-ai-bootcamp / docs/learning-path.md](../../agentic-ai-bootcamp/docs/learning-path.md)**

---

## Stage 4 — 参照/本番化 / Reference & production

bootcamp で学んだパターンを、**3 フレームワーク横断**（PydanticAI / BeeAI / LlamaIndex）で、
契約・ドリフトテスト・カバレッジゲート・pyright strict・CI 付きの**本番品質**で実装した
参照実装です。

| 学びたいこと | 場所 |
|---|---|
| ワークフロー 6 パターン横断比較 | [`patterns/README.md`](../patterns/README.md) |
| 共有契約 + ドリフト検知（単一ソース）| [`patterns/contracts/`](../patterns/contracts/README.md) |
| RAG（検索→生成→引用検証）| [`patterns/rag/`](../patterns/rag/README.md) |
| SSE 配信（エージェントイベント）| [`patterns/sse/`](../patterns/sse/README.md) |
| Deep Research（マルチエージェント）| [`patterns/deep-research/`](../patterns/deep-research/README.md) |
| 評価グレーダ（outcome+behavior、3 パターン横断契約）| [`patterns/EVAL-GRADERS.md`](../patterns/EVAL-GRADERS.md)（main にマージ済・drift 検証あり、Spec 011）（→ bootcamp [Lesson 11](../../agentic-ai-bootcamp/lessons/11-evals/README.md)）|
| ツール設計 / コンテキスト工学（compaction は deep-research 本流）| [`docs/tool-design.md`](tool-design.md) ・ [`docs/context-engineering.md`](context-engineering.md) |

> 対応する公式ソース（Anthropic building-effective-agents / writing-tools / context-engineering /
> demystifying-evals、IBM architecture patterns）は bootcamp 側の対応表を参照。

## Stage 5 — ガバナンス & スケール / Governance & scale

identity 管理・OWASP・エンタープライズ規模の採用・デプロイ：
**[`governance-and-scale.md`](governance-and-scale.md)**（IBM identity-management / scale agentic AI /
watsonx deploy ＋ [`patterns/SECURITY-NOTES.md`](../patterns/SECURITY-NOTES.md) の OWASP マッピング）。
