# 009-deep-research

`patterns/deep-research/` — Agentic AI（Multi-Agent System）応用レイヤとして、
Pydantic AI で Deep Research を実装し、他フレームワークとの比較・ハイブリッド活用を検証する。

## Project Description

主要エージェントフレームワーク（LangGraph / CrewAI / Microsoft Agent Framework /
LlamaIndex / BeeAI / Langflow / Dify）と Pydantic AI を比較し、各フレームワークの優れた
ロジックを**安全に取り込み**、Pydantic AI をラップ／応用する活用法を検証する。その実証として、
Multi-Agent System の代表ユースケースである **Deep Research** を、既存パターン
（orchestrator-workers / parallelization / autonomous-agent / RAG / SSE）の最小プリミティブを
**合成**して実装する。参照アーキテクチャは Anthropic multi-agent research system /
langchain open_deep_research / HF open-deep-research / local-deep-research。

## Clarifications

### Session 2026-06-20（/sdd-init — 3論点 CONFIRMED）

- **成果物の粒度**: 実装レーン `patterns/deep-research/` ＋ 仕様 `specs/009-deep-research/` ＋
  テスト一式（RAG/SSE と同格）。
- **他フレームワークの扱い**: 新規コードレーンは作らず、比較分析ドキュメント
  （[COMPARISON.md](../../patterns/deep-research/COMPARISON.md)）＋各フレームの良所を Pydantic AI 実装へ蒸留。
- **検索バックエンド**: 差し替え可能な `SearchProvider` DI seam（オフライン fake でテスト、ライブは
  env フラグで遅延 import）。

## Overview

lead エージェントがクエリを `ResearchBrief`＋`ResearchPlan` に分解 → `max_researchers` で cap した
並列 sub-researcher（`asyncio.gather`、plan 順保持）が有界 search→read→reflect ループ
（`max_iterations`）を回し `SearchProvider` から grounding 結果を収集 → 引用 grounding
（dangling/empty loud-fail）→ report writer が引用付き `ResearchReport` に統合。進捗は任意の
`on_event`（`ProgressEvent` 判別共用体）で配信し、sse への橋渡しはレーン外でアダプトする。

## Scope

### In Scope

- `patterns/deep-research/` 独立 uv レーン（Python 3.13、契約パス依存、pydantic-ai ランタイム）。
- Deep Research 契約（contracts パッケージ）＋単一ドリフトテスト。`Citation` は RAG 契約を再利用。
- lead / 並列 researcher / 引用 grounding / report の各実装と DI seam（model / search / instrumentation / on_event）。
- ガードレール（fan-out / iteration / top_k cap、検索 seam の最小権限）＋ OWASP マッピング。
- オフライン hermetic unit ＋ gated Ollama 結合（既定 fake 検索、`RUN_INTEGRATION_SEARCH=1` でライブ）。
- フレームワーク比較・ハイブリッド doc、mise / CI / .env 配線。

### Out of Scope

- LangGraph / CrewAI / MAF / Langflow / Dify の新規コードレーン（COMPARISON.md の分析に留める）。
- ライブ検索プロバイダの runtime 実装（遅延 import の seam のみ；結合スイートで実体化）。
- 永続化（checkpoint/resume）・token-budget ガードレールの実装（拡張点として文書化）。
- 認証・レート制限（応用デモの範囲外）。

## Glossary

- **lead / orchestrator**: クエリを brief＋plan に分解する先導エージェント。
- **sub-researcher**: 単一 subquestion を独立コンテキストで担当する researcher。
- **SearchProvider**: 検索の DI seam（Protocol）。fake / ライブを構造適合で注入。
- **grounding**: 各 `Citation` が実取得 `SearchResult` に対応することの保証。

## Requirements（EARS）

### Requirement 1: 独立レーンと契約配線
1.1 `patterns/deep-research/` は独立 uv プロジェクト（自前 `.python-version` / lockfile / ゲート）として新設する。
1.2 契約は `patterns/contracts` をパス依存で import し、レーン内に複製しない。
1.3 レーン src は検索プロバイダ・兄弟レーンに非結合（`SearchProvider` seam のみが外部 I/O 経路）。

### Requirement 2: 契約と単一ドリフト
2.1 Deep Research 契約（`ResearchBrief`/`SubQuestion`/`ResearchPlan`/`SearchQuery`/`SearchResult`/`Finding`/`ResearchReport`/`ProgressEvent`）を contracts パッケージの単一実体とし、README 正本＝パッケージの一致を `test_contract_drift.py` で検証する。
2.2 `Citation` は RAG 契約を再利用し、deep-research README には再掲しない（1クラス＝1README）。

### Requirement 3: lead（brief / plan）
3.1 lead は `ResearchBrief`（objective＋out_of_scope）と自己完結・非重複な `SubQuestion` 群を含む `ResearchPlan` を生成する（分解は LLM が決める）。
3.2 任意の clarify 前段でクエリを sharpen できる（既定オフ）。

### Requirement 4: 有界並列 researcher と検索 seam
4.1 capped subquestion を `asyncio.gather` で並列実行し、findings は plan 順を保つ。
4.2 researcher は注入 `SearchProvider` のみから grounding 結果を収集する（最小権限）。
4.3 search→read→reflect ループは `max_iterations` で上限化し、到達時は `Finding.truncated`/`iterations` で記録する。

### Requirement 5: 引用 grounding
5.1 各 `Finding` は実取得 `SearchResult` に対応する `Citation` を持つ。
5.2 引用ゼロは `EmptyCitationError` で loud-fail。
5.3 未取得出典の dangling 引用は `DanglingCitationError` で loud-fail。

### Requirement 6: レポート合成
6.1 report writer は findings を引用付き `ResearchReport` に統合し、`citations` は重複排除和集合とする。

### Requirement 7: ガードレールと OWASP
7.1 `max_researchers` で fan-out を上限化し、切り捨てを `ResearchReport.truncated` で可視化する。非正の cap は `ValueError`。
7.2 `top_k` で検索出力量を上限化する。
7.3 リスクを OWASP（過剰エージェンシー / Unbounded Consumption / プロンプトインジェクション / 引用スプーフィング）へマッピングする（SECURITY-NOTES.md）。

### Requirement 8: テスト
8.1 全 unit はネットワーク I/O ゼロ（autouse `block_network` ＋ scripted model/search フェイク）。
8.2 ガードレール（fan-out/iteration cap・truncated）と引用 grounding（dangling/empty loud-fail）を検証する。
8.3 gated Ollama 結合（`RUN_INTEGRATION_PATTERNS=1`）は契約形状（finding≥1 / citation≥1 / span≥1）のみアサートし、正確な文言は禁止。`EXPECT_LIVE_TESTS` で anti-false-green を担保。

### Requirement 9: 可観測性
9.1 `configure_tracing`（注入 > OTLP env > no-op）＋ `instrument_model` で `gen_ai.*` span を発行。`InMemorySpanExporter` で span≥1 の存在を検証（属性集計はしない）。

### Requirement 10: 進捗ストリーミング seam
10.1 任意の `on_event`（`ProgressEvent` 判別共用体）で brief→plan→researcher_started*→finding_ready*→report_ready を emit する。sse への橋渡しはレーン外（兄弟レーン非 import）。

### Requirement 11: ドキュメント・タクソノミー
11.1 lane README（契約正本＋必須4セクション）と COMPARISON.md（7フレーム比較・ハイブリッド）を提供し、`patterns/README.md` の応用レイヤー索引に登録する。

### Requirement 12: CI / mise 配線
12.1 `mise.toml` の各 `patterns:*` タスクと per-lane 結合タスク、`patterns-ci.yml` の専用ジョブ、`patterns-integration-ollama.yml` のマトリクスへ登録する。

### Requirement 13: セキュリティ
13.1 検索鍵・モデル ID は env 専属でハードコード禁止。`ProgressEvent` に機微情報を載せない。gitleaks / forbid-hardcoded-model-ids は patterns/ 全域を走査する。

## Non-Functional Requirements

- pyright strict（Python 3.13）/ ruff strict / coverage `fail_under=98`（実測 100%）。
- import 時 I/O ゼロ（ライブ検索クライアントは遅延 import）。
- 決定論（オフライン fake で byte 安定）。

## Out of Scope / Future Work

永続化（LangGraph 風 checkpoint）、token-budget ガードレール、ライブ検索プロバイダ実体、認証/レート制限。

## Dependencies

`patterns-contracts`（パス依存）、`pydantic-ai-slim[openai]>=2.0.0b6`、`pydantic>=2,<2.14`、
`opentelemetry-sdk` / `-exporter-otlp-proto-http`。

## References

- Anthropic, *How we built our multi-agent research system*
- LangChain, *open_deep_research* / Hugging Face, *open-deep-research* / LearningCircuit, *local-deep-research*
- 既存: `patterns/frameworks/pydantic-ai/`（orchestrator_workers / parallelization / autonomous_agent）、`patterns/rag/`、`patterns/sse/`
