# Verification — AI Agents / Agentic AI 実装ベストプラクティス

本リポジトリ(`pydantic-ai-sandbox`)の実装を、IBM / Anthropic / Google / AWS の公式定義と、
Anthropic の実装ガイダンス(Building Effective Agents / Writing tools for agents /
Effective context engineering / Demystifying evals)、および LangChain `open_deep_research`
等のフレームワーク実装ベストプラクティスに照らして検証した記録。重視軸は **実装ベストプラクティス**。
改善提案は `improvement-plan.md` を参照。

## Scope

- 対象: `patterns/`(6 パターン + `deep-research` / `rag` / `sse` 応用層 + `contracts` + 3 フレームワーク lane)、
  ルート単一エージェント `src/pydantic_ai_sandbox/`
- 参照ソース: 下記「References」。公式本文ページ(ibm.com / anthropic.com)は直接取得が 403 のため、
  WebSearch で取得した実質内容と、本リポジトリ内の規範ドキュメントの引用を突き合わせて検証した。

## Summary

本リポジトリは Anthropic「Building Effective Agents」を一次ソースに、IBM の粒度区分
(AI Agent = 単一タスク構成要素 / Agentic AI = 複数エージェントのオーケストレーション)を
明示採用した、定義整合性・実装品質ともに高水準なリファレンス実装である。3 フレームワーク
(PydanticAI / BeeAI / LlamaIndex)で同一契約を実装し、契約ドリフトテストで一貫性を担保している
点は、クロスフレームワーク・ベストプラクティスの好例。伸びしろは主に **(1) ツール設計原則の明示**
と **(2) context engineering(compaction / note-taking)の spec→実装** の 2 点。

## 検証結果(観点別)

| # | 観点 | 公式ベストプラクティス | 本リポジトリの状況 | 評価 | 主な根拠 |
|---|------|----------------------|------------------|------|---------|
| 1 | パターン分類・定義 | Anthropic: agents vs workflows / IBM: AI Agent vs Agentic AI | 6 パターン実装。2D 分類(縦=Anthropic, 横=IBM)を明示。autonomous-agent のみ「AI Agent」 | ✅ 強く一致 | `patterns/README.md`, `specs/005-cross-platform/spec.md` |
| 2 | 「単純さ優先」 | 複雑な framework より単純・合成可能なパターン。透明性 | autonomous-agent を framework Agent でなく `Model.request()` 手動ループで実装 | ✅ 一致 | `patterns/frameworks/pydantic-ai/src/patterns_pydantic_ai/autonomous_agent.py` |
| 3 | ツール設計 | Writing tools: 厳格データモデル / 入力検証 / token 効率 / namespacing / `response_format` | 型強制(`output_type` + `contracts/`)・実行前入力検証に加え、token 効率 / namespacing / `response_format` を規約化(`TOOL-DESIGN-NOTES.md`)し PydanticAI lane の `directory_*` デモで実演(P1 実装済) | ✅ 一致 | `patterns/TOOL-DESIGN-NOTES.md`, `patterns/frameworks/pydantic-ai/.../tool_design.py`, autonomous-agent README |
| 4 | ガードレール / セキュリティ | OWASP Agentic AI Top 10(Excessive Agency / Unbounded Consumption / Insecure Tool Use) | 4 ガードレール + fan-out 上限を明示マッピング | ✅ 強い実装 | `patterns/SECURITY-NOTES.md` |
| 5 | コンテキストエンジニアリング | sub-agent / context quarantine / compaction / note-taking | deep-research が sub-agent・並列 researcher→合成を実装。compaction / note-taking は未実装 | ✅/△ 部分的 | `patterns/deep-research/README.md`, `specs/009-deep-research/spec.md` |
| 6 | 評価(Evals) | Generator/Evaluator 分離・独立 judge・outcome+behavior・hermetic | 物理分離、ネットワークフリーテスト、契約レベル assertion | ✅ 準拠 | `patterns/frameworks/*/tests/`, `contracts/tests/unit/test_contract_drift.py` |
| 7 | フレームワーク横断 | 同一契約を複数 framework で検証 | PydanticAI / BeeAI / LlamaIndex 3 lane + 契約ドリフトテスト | ✅ 好例 | `patterns/frameworks/`, `patterns/contracts/` |
| 8 | プロバイダ非依存 | モデル ID ハードコード回避・env 駆動 | ModelFactory(4 プロバイダ + fallback)、env 駆動 | ✅ 一致 | `src/pydantic_ai_sandbox/llm/factory.py`, `config.py` |

## 主な検証ポイント(改善提案へ接続)

- **ツール設計の明示**: token 効率(pagination / filter / truncation)・namespacing・`response_format`
  を規約化(`patterns/TOOL-DESIGN-NOTES.md`)し、PydanticAI lane の `directory_*` デモで実演。→ 改善提案 P1 実装済。
- **context engineering の spec→実装ギャップ**: compaction / structured note-taking が未実装。→ 改善提案 P2。
- **AWS 参照**: 公式参照に AWS(Bedrock Agents / Well-Architected GenAI Lens)を追加し、本リポジトリの
  ガードレール/プロバイダ非依存設計との対応関係を明記。→ 改善提案 P3 実装済(下記 References)。

## References

- Anthropic — Building Effective Agents: https://www.anthropic.com/research/building-effective-agents
- Anthropic — Writing effective tools for AI agents: https://www.anthropic.com/engineering/writing-tools-for-agents
- Anthropic — Effective context engineering for AI agents: https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
- Anthropic — Demystifying evals for AI agents: https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents
- IBM — AI Agent Orchestration: https://www.ibm.com/think/topics/ai-agent-orchestration
- IBM — An IBM Guide to Agentic AI Systems: https://www.ibm.com/think/architectures/patterns/agentic-ai
- Google Cloud — What is agentic AI: https://cloud.google.com/discover/what-is-agentic-ai
- AWS — Amazon Bedrock Agents（ユーザーガイド）: https://docs.aws.amazon.com/bedrock/latest/userguide/agents.html
- AWS — Well-Architected Generative AI Lens: https://docs.aws.amazon.com/wellarchitected/latest/generative-ai-lens/generative-ai-lens.html

### AWS 公式との対応関係（改善提案 P3）

AWS の2件は本リポジトリのプロバイダ非依存設計・ガードレールと次のように対応する。
**Amazon Bedrock Agents** はマネージドなツール実行（action group）・オーケストレーション・
ガードレール（入出力フィルタ）を提供するが、本リポジトリは特定プロバイダにロックインせず、
同等の責務を**契約レベルで**実現する — ツールは `Tool` Protocol + 最小権限 `allowed_tools`、
ガードレールは `AgentRunResult.stop_reason` の閉じた語彙（`max_iterations` / `budget_exceeded` /
`denied` / `disallowed_tool`）で型レベルに記録し、3 フレームワーク lane 横断で同一化する
([SECURITY-NOTES.md](../../patterns/SECURITY-NOTES.md))。**Well-Architected Generative AI Lens**
が説く責任ある AI / コスト・運用上の上限設計は、本リポジトリの fan-out 上限・`max_iterations` ＋
`budget` の二重上界・hermetic 評価ゲートに対応する。AWS Bedrock を採用する場合も、これらの
契約は SDK 非依存の正本（[`patterns_contracts`](../../patterns/contracts/)）として再利用できる。
- LangChain — open_deep_research: https://github.com/langchain-ai/open_deep_research
