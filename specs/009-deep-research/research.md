# 009-deep-research — Research & ADRs

## 背景

Multi-Agent System の代表ユースケースである Deep Research を Pydantic AI で実装し、他フレームワーク
（LangGraph / CrewAI / MAF / LlamaIndex / BeeAI / Langflow / Dify）の優れたロジックを取り込む方針を
検証する。参照: Anthropic multi-agent research system / langchain open_deep_research /
HF open-deep-research / local-deep-research。

## ADR-1: 既存プリミティブの「合成」で実装する（再実装しない）

Deep Research は新規の思考様式ではなく、既存パターンの組合せ:
orchestrator-workers（動的計画＋並列実行＋`truncated`）/ parallelization（`asyncio.gather` fan-out）/
autonomous-agent（有界ループ＋停止規律）/ RAG（`Citation`／引用健全性）/ SSE（進捗イベント判別共用体）。
Anthropic「最小の合成可能パターンで組む」を踏襲し、これらを合成する。

## ADR-2: Python 3.13（rag アプリレーンに合わせる）

pydantic-ai-slim / pydantic / OTel は 3.13 を完全サポートし、pydantic-ai・pydantic V2 ベータの 3.14
pre-release サポートはなお流動的。アプリレーンの先例（rag=3.13）に倣い floor を 3.13 に固定する
（sse / pydantic-ai レーンが 3.14 なのは spike の経緯）。pydantic-ai は本レーンの**ランタイム依存**で、
V2 ベータが `pydantic-graph` を pre-release にピンするため `[tool.uv] prerelease = "allow"` が必須。
runtime の pydantic は `<2.14` 上限で stable に固定し alpha 漏れを防ぐ。

## ADR-3: SearchProvider DI seam（オフライン fake＋遅延ライブ）

検索は `@runtime_checkable` Protocol で抽象化。unit は決定論 `FakeSearchProvider`（corpus 固定、
score 降順・source 昇順）でネットワークゼロ。ライブ（duckduckgo/tavily/searxng）は
`load_search_provider()` が env で**関数内遅延 import**し、未設定/未配線は `ValueError` で loud-fail。
これで import 時 I/O ゼロ・最小権限（任意 URL/ツール不可）を満たす。

## ADR-4: 上限設計でコスト/エージェンシを抑制

Anthropic 計測でマルチエージェントは ~15x トークン。`max_researchers`（fan-out、`truncated` 可視化）/
`max_iterations`（researcher 毎、`Finding.truncated`/`iterations`）/ `top_k`（検索出力量）の3上限で
暴走を遮断（OWASP 過剰エージェンシー / Unbounded Consumption）。token-budget seam
（autonomous-agent の `_budget_spent`＝`usage` 合算相当）は拡張点として文書化。

## ADR-5: 引用 grounding は RAG 規律の移植

`chunk_id=f"{source}::{locator}"` をキーに、各 `Citation` が実取得 `SearchResult` に対応することを検証。
引用ゼロ→`EmptyCitationError`、未取得出典→`DanglingCitationError`（引用スプーフィング防御）。

## ADR-6: ProgressEvent はドリフト parser 対称スキップ

`ProgressEvent = Annotated[Union[...], Field(discriminator="type")]` は `SseEvent` 同様、モデルクラスでも
`Literal` でもないため drift parser が README/パッケージ両側で対称スキップする（parser 改変不要）。
各メンバの `type: Literal[...]` は進捗イベント名として消費側がマップできる。

## ADR-7: 他フレームワークは分析に留める（新規レーンを作らない）

LangGraph/CrewAI/MAF はライブラリだが、本イテレーションの主眼は「Pydantic AI への良所取り込み」。
Langflow/Dify は低コード基盤でコード横断比較に不向き。よって新規コードレーンは作らず、
COMPARISON.md に「取り込む良所」「ラップの向き」を蒸留し、設計（役割分割・middleware seam・
checkpoint seam・契約境界）へ反映する。

## ハイブリッド方針（要約）

Pydantic AI を**型付き core**に据え、フレームは不足能力を補う層として採用:
durability=LangGraph（Pydantic AI ステージをノード化）、可視化/試作=Langflow、運用/公開=Dify
（Pydantic AI サービスを呼ぶ）、検索基盤=LlamaIndex（`SearchProvider` 実装に差し込む）。境界は常に
Pydantic 契約で切り、フレーム差し替えの影響を局所化する。詳細は COMPARISON.md。
