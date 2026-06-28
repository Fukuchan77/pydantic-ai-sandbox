# Deep Research パターン（応用レイヤー / Multi-Agent オーケストレーション）

ユーザーの調査クエリを **lead エージェントが分解**（`ResearchBrief` → `ResearchPlan`）し、
**有界並列の sub-researcher** がそれぞれ独立コンテキストで search→read→reflect の反復ループを
回して `Finding`（要約＋引用）を返し、**report writer** が引用付き `ResearchReport` に統合する、
単一レーン（`patterns/deep-research/`）の **Agentic AI（Multi-Agent System）応用レイヤ**。

Anthropic「Building Effective Agents」の6ワークフローとは別系の応用レイヤであり、参照アーキテクチャは
[Anthropic multi-agent research system](https://www.anthropic.com/engineering/multi-agent-research-system) /
[langchain open_deep_research](https://github.com/langchain-ai/open_deep_research) /
[HF open-deep-research](https://huggingface.co/blog/open-deep-research) /
[local-deep-research](https://github.com/LearningCircuit/local-deep-research)。既存パターンの**最小プリミティブ**で組む方針を踏襲し、
orchestrator-workers の動的計画＋並列実行、parallelization の fan-out、autonomous-agent の有界ループ＋
ガードレール、RAG の `Citation`／引用検証、SSE の進捗イベントを**合成**する（再実装しない）。

検索は **`SearchProvider` DI seam**（`@runtime_checkable` Protocol）で受け取り、レーン src は
検索プロバイダ・フレームワークに非結合。オフライン unit は決定論フェイク（`FakeSearchProvider`）で
**ネットワークゼロ**に完走し、ライブ検索（DuckDuckGo / Tavily / SearXNG）は env フラグで遅延 import する
（NFR-3 / 兄弟レーン非 import）。フレームワーク横断比較・ハイブリッド活用方針は [COMPARISON.md](COMPARISON.md)。

## パターン契約（正本）

契約の実体は依存ゼロの [`patterns_contracts`](../contracts/) パッケージ
（[`deep_research.py`](../contracts/src/patterns_contracts/deep_research.py)）。下記の Python コードブロックが
その**正本**であり、
[`patterns/contracts/tests/unit/test_contract_drift.py`](../contracts/tests/unit/test_contract_drift.py)
が両者（クラス集合・フィールド集合・`Literal` 語彙）の一致を1点で検証する（006-2a NFR-5）。
`Citation` は RAG レーンが所有する契約（[`rag.py`](../contracts/src/patterns_contracts/rag.py)）を
**再利用**するため（研究クレームの grounding は RAG の引用と同型）、本レーンは import して用いるだけで
**ここに再掲しない**（ドリフトテストの「1クラス＝1README」所有則）。判別共用体 `ProgressEvent` は
`Annotated` エイリアスでありモデルクラスでも `Literal` でもないため、parser は `SseEvent` 同様に
両側で対称スキップする。本レーンはこれらをパス依存で import し、レーン内で再定義しない（NFR-3）。

```python
class ResearchBrief(BaseModel):        # lead エージェントによるクエリのスコープ化（Anthropic lead-agent brief）
    query: str           # 元のユーザークエリ（逐語）
    objective: str       # 完全な回答が満たすべき条件（成功基準）
    out_of_scope: list[str]   # sub-researcher の脱線を防ぐ明示的除外

class SubQuestion(BaseModel):          # 1 sub-researcher 向けの自己完結タスク
    description: str     # 他の subquestion を見ずに回答可能な自己完結指示

class ResearchPlan(BaseModel):         # brief を subquestion 群へ分解した計画
    brief: ResearchBrief   # 計画が対象とする brief
    subquestions: list[SubQuestion]   # 順序付き。downstream で max_researchers に cap（fan-out ガード）

class SearchQuery(BaseModel):          # researcher が SearchProvider seam に発行するクエリ
    text: str            # researcher が決定した検索クエリ文字列

class SearchResult(BaseModel):         # SearchProvider seam が返す 1 ヒット（finding の grounding）
    source: str          # ヒット元の文書識別子（Citation.source に対応）
    locator: str         # source 内のアンカー（url / section 等。Citation.locator に対応）
    snippet: str         # finding を grounding する結果テキスト
    score: float         # プロバイダ関連度スコア。同点は source 昇順で tie-break

class ResearchNote(BaseModel):         # distill 済み高信号ノート（外部 notebook の 1 エントリ、frozen）
    source: str          # distill 元 SearchResult.source（dedup アンカー）
    locator: str         # distill 元 SearchResult.locator（dedup アンカー）
    key_point: str       # 先頭文を key_point_chars で truncate（可視マーカー付き）
    score: float         # distill 元 score。降順ランキングのキー（decision 系は将来拡張）

class Finding(BaseModel):              # 1 sub-researcher の圧縮済み出力
    subquestion: SubQuestion   # この finding が回答する subquestion
    summary: str         # subquestion に対する圧縮済み所見
    citations: list[Citation]   # summary を裏付ける引用（>=1 をパイプラインが強制）
    iterations: int      # 実際に回した search→read→reflect ループ数（<= max_iterations）
    truncated: bool = False   # iteration cap に達してから「十分」と判断できなかった場合 True
    notes: list[ResearchNote] = []   # ハンドオフ用 distill 済みノート（既定 []、生トランスクリプト非伝播）

class ResearchReport(BaseModel):       # 最終統合出力
    brief: ResearchBrief   # レポートが対象とする brief
    findings: list[Finding]   # subquestion 毎の finding（plan 順、最大 max_researchers 件）
    report: str          # インライン引用マーカ付きの統合レポート本文
    citations: list[Citation]   # 各 finding 引用の重複排除済み和集合
    truncated: bool = False   # plan が max_researchers を超える subquestion を出した場合 True

class BriefReadyEvent(BaseModel):      # 進捗: lead が brief を生成
    type: Literal["brief_ready"] = "brief_ready"   # 判別子 = 進捗イベント名
    objective: str       # brief の objective（成功基準）

class PlanReadyEvent(BaseModel):       # 進捗: lead が（cap 後の）plan を生成
    type: Literal["plan_ready"] = "plan_ready"     # 判別子 = 進捗イベント名
    count: int           # 実行される subquestion 数（fan-out cap 後）

class ResearcherStartedEvent(BaseModel):   # 進捗: sub-researcher が subquestion 着手
    type: Literal["researcher_started"] = "researcher_started"   # 判別子 = 進捗イベント名
    subquestion: str     # 着手した subquestion の説明

class FindingReadyEvent(BaseModel):    # 進捗: sub-researcher が grounding 済み finding を返却
    type: Literal["finding_ready"] = "finding_ready"   # 判別子 = 進捗イベント名
    subquestion: str     # finding が回答する subquestion
    citation_count: int  # finding を裏付ける引用数

class ReportReadyEvent(BaseModel):     # 進捗: report writer が最終レポートを生成（終端イベント）
    type: Literal["report_ready"] = "report_ready"   # 判別子 = 進捗イベント名
    citation_count: int  # レポートの重複排除済み引用数

ProgressEvent = Annotated[BriefReadyEvent | PlanReadyEvent | ResearcherStartedEvent | FindingReadyEvent | ReportReadyEvent, Field(discriminator="type")]   # 判別共用体。parser はスキップ（SseEvent 同様）
```

## パイプライン（lead → 有界並列 researcher → citation → report）

| 段 | 実装 | 決定論シーム / 不変条件 |
|---|---|---|
| DI seam（検索） | `SearchProvider` Protocol（[`search.py`](src/patterns_deep_research/search.py)） | `async def search(query, *, top_k) -> list[SearchResult]` を構造適合で注入（fake / ライブ env）。レーン src は検索プロバイダ非結合（NFR-3） |
| lead / 計画 | `build_brief_and_plan`（[`orchestrator.py`](src/patterns_deep_research/orchestrator.py)） | planner `Agent[None, ResearchPlan]` が分解を決める（コードではなく LLM）。subquestion は自己完結・非重複（orchestrator-workers の planner 流儀＋Anthropic brief） |
| fan-out cap | `run_deep_research`（[`research.py`](src/patterns_deep_research/research.py)） | `plan.subquestions[:max_researchers]` ＋ `ResearchReport.truncated`。無制限 plan を無制限 LLM 呼び出しに変換しない（OWASP excessive-agency / unbounded-consumption） |
| 並列実行 | `asyncio.gather`（[`research.py`](src/patterns_deep_research/research.py)） | researcher を plan 順で並列実行（gather が入力順を保持） |
| researcher | `run_subquestion`（[`researcher.py`](src/patterns_deep_research/researcher.py)） | search→read→reflect の**有界ループ**（`max_iterations`）。`Finding.truncated`/`iterations` で cap を可視化（autonomous-agent の停止規律を移植）。reflect digest は `digest_fn` seam（既定 `_results_digest` byte 互換、`compact_digest` opt-in。下記「コンテキストエンジニアリング」節） |
| 引用 grounding | `compression`（[`compression.py`](src/patterns_deep_research/compression.py)） | 各 `Citation` は実際に見た `SearchResult` に対応。空引用 `EmptyCitationError` / dangling `DanglingCitationError` で loud-fail（RAG の引用健全性を移植） |
| 統合 | `write_report`（[`report.py`](src/patterns_deep_research/report.py)） | synthesizer `Agent[None, str]` が引用付きレポートを合成。引用は重複排除和集合、`truncated` を伝播 |
| 進捗（任意） | `on_event` コールバック seam（[`research.py`](src/patterns_deep_research/research.py)） | `ProgressEvent` を emit。sse への橋渡しはレーン外でアダプト（兄弟レーン非 import、NFR-3） |

## コンテキストエンジニアリング（compaction / structured note-taking の本線昇格）

Anthropic「Effective context engineering for AI agents」の **compaction** と
**structured note-taking** を本線へ配線済み（Spec 010）。解説と注入手順は
[../../docs/context-engineering.md](../../docs/context-engineering.md)。

- **`digest_fn` DI seam（reflect ループ）**: `run_subquestion` / `run_deep_research` が
  `digest_fn: Callable[[Sequence[SearchResult]], str]` を公開。既定は `_results_digest` と
  byte 互換（後方互換）、`notes.compact_digest` を **opt-in 注入**するとノートベース縮約
  （dedup + score cap + truncate）へ切り替わる。既存の `SearchProvider` / `model` / `on_event`
  と同じ seam 規律に揃え、決定論フェイクで hermetic にテスト可能。
- **compression は full digest 維持**: 引用源選択ターンは注入有無に関わらず `_results_digest`
  の full 出力を使い citation grounding を保全する（縮約で source を落とし `EmptyCitationError` /
  `DanglingCitationError` を誘発しない）。
- **ハンドオフ凝縮**: ループ終了後に `Finding.notes = distill_notes(collected)` を充填し、
  sub-researcher → lead は「凝縮サマリ + ノート」のみを渡す（生トランスクリプト非伝播）。
  契約は上記正本ブロックの `ResearchNote` / `Finding.notes`（既定 `[]`、空 gather でも安全）。
- **拡張点（v1 非対象）**: トークン上限トリガの文脈再初期化・生 result の畳み込み（Anthropic
  「tool result clearing」相当）は v1 非対象で、v1 は常時 digest 縮約に限定する。上限トリガ実装は
  deep-research が文書化済みの **token-budget seam**（autonomous-agent の `_budget_spent` ≒
  `ModelResponse.usage` 合算、後述セキュリティ節）へ接続し、予算ガードが上限近傍を検知したら
  `digest_fn` 縮約から文脈再初期化へエスカレートする段階化が拡張点（[SECURITY-NOTES.md](../SECURITY-NOTES.md)）。

## 必須4セクション

### 型安全

- 契約 `ResearchBrief` / `SubQuestion` / `ResearchPlan` / `SearchQuery` / `SearchResult` / `Finding` /
  `ResearchReport` と判別共用体 `ProgressEvent` は `patterns_contracts` の単一実体。`Citation` は RAG レーン
  所有の契約をパス依存で再利用する。レーンはいずれも再定義しない（NFR-3）。pyright **strict**（Python 3.13）。
- `SearchProvider` は `@runtime_checkable` な DI seam。検索プロバイダは構造適合で注入し、レーン src は
  プロバイダ・兄弟レーンに非結合。全 entry は `async def run_*(..., *, model: Model, ...caps...,
  instrumentation=None)` 形で、`instrument_model(model, instrumentation) if instrumentation else model` を適用。
- `ProgressEvent` は `Annotated[Union[...], Field(discriminator="type")]` で JSON シリアライズと pyright strict を
  両立。`TypeAdapter(ProgressEvent).validate_json` で判別子から元モデルへ逆写像。

### テスト

- **オフライン hermetic**: 全 unit がネットワーク I/O ゼロで完走。`block_network` フィクスチャが
  AF_INET/AF_INET6 reach を loud-fail（load-bearing）。モデルは pydantic-ai `FunctionModel`/`TestModel` を
  スクリプト化、検索は `FakeSearchProvider`（決定論 corpus、`score` 降順・`source` 昇順 tie-break）。
- **ガードレール検証**: `max_researchers` 超の plan で実行 researcher 数＝cap・`findings` 長＝cap・
  `ResearchReport.truncated is True`・plan 順保持。「十分」にならない fake で `max_iterations` 到達・
  `Finding.truncated`/`iterations` を検証。
- **引用 grounding 検証**: 各 `Citation` が実 `SearchResult` に対応、`ResearchReport.citations` は重複排除和集合、
  植えた dangling/empty が `DanglingCitationError`/`EmptyCitationError` で loud-fail。
- **カバレッジゲート**: 兄弟レーン parity で `fail_under=98`。残る到達困難なグルー分岐は rationale を
  `pyproject.toml` に恒久記録。
- **実 Ollama 結合**: `RUN_INTEGRATION_PATTERNS=1` でゲート（既定は ライブモデル × `FakeSearchProvider`）。
  ライブ検索は第2フラグ `RUN_INTEGRATION_SEARCH=1` のみ。契約形状（`ResearchReport` に finding≥1 /
  citation≥1 / span≥1）だけアサートし、正確な文言は禁止（非決定的な実モデルゆえ、決定論はフェイクの所掌）。
- **オフライン多軸 eval（outcome+behavior グレーダ）**: `ResearchReport`（`Finding.notes` 含む）を
  outcome+behavior の多軸 `GradeReport` で採点するオフライン eval を `tests/` が決定論フェイク
  `Judge[ResearchReport]` でネットワークゼロ検証する（Spec 011）。`ResearchNote.key_point` が空/低信号の
  とき faithfulness 軸を silent にスコアせず `"unknown"`（証拠不足）へマップする規律は純粋ヘルパ
  `faithfulness_rating_for` に閉じ、空/非空の両分岐を直接テストする（R2.4、台本焼き込みによる同義反復を回避）。
  共有グレーダ契約の正本・rating rubric・独立 judge 規律は横断 README
  [EVAL-GRADERS.md](../EVAL-GRADERS.md) が所有し、本パターンは**参照のみ**
  （`GradeReport` 系をここに再宣言しない＝one-README 不変条件）。

### 可観測性

- `configure_tracing(exporter=None) -> TracerProvider`（[`observability.py`](src/patterns_deep_research/observability.py)）を
  兄弟レーンと同形で適用。exporter 優先チェーン: **注入 > `OTEL_EXPORTER_OTLP_ENDPOINT` > no-op**。
- 各ステージ（brief/plan/researcher/report）の span は entry が自前で開き、`instrument_model` で `gen_ai.*` span を
  同一 provider に集約。`InMemorySpanExporter` 注入で span≥1 の**存在**を検証（属性集計はバックエンド責務）。

### セキュリティ

- **進捗イベントに機微情報を載せない**: `ProgressEvent` は最小フィールド設計（生プロンプト全文・認証情報・
  full traceback を載せない）。
- **ガードレール = 過剰エージェンシ / 無制限消費の緩和**（OWASP Agentic AI Top 10）: fan-out cap
  `max_researchers`・iteration cap `max_iterations`・`top_k` cap・検索 seam の最小権限（任意 URL/ツール不可）。
  multi-agent は ~15x トークンになり得るため cap でコストを抑制する（拡張点として token-budget seam を文書化）。
- **モデル ID / 鍵のハードコード禁止**: Ollama / ライブ検索の接続・モデル・鍵は env 専属
  （`OLLAMA_BASE_URL` / `OLLAMA_MODEL_NAME` / `DEEP_RESEARCH_SEARCH_BACKEND` / `TAVILY_API_KEY` / `SEARXNG_URL`）。
  gitleaks / forbid-hardcoded-model-ids は `patterns/` 全域を除外しない。
- Deep Research 固有リスク（プロンプトインジェクション経由の検索結果汚染 / 無制限消費 / 引用スプーフィング）→
  OWASP（LLM Top 10 / Agentic AI）の詳細マッピングは [SECURITY-NOTES.md](../SECURITY-NOTES.md)。

## 使用ライブラリとバージョン

| ライブラリ | バージョン | 役割 / 注記 |
|---|---|---|
| `patterns-contracts` | path dep | 契約の単一実体（`deep_research.py`＋再利用する `rag.Citation`）。レーンは再定義しない（NFR-3） |
| `pydantic-ai-slim[openai]` | 2.0.0b6 系（**beta**） | オーケストレーション本体（lead / researcher / report の各 `Agent`）。**ランタイム依存** |
| `pydantic` | >=2,<2.14 | 契約モデル基底。runtime 閉包を **stable** に固定（pydantic-ai beta が引く alpha を遮断） |
| `opentelemetry-sdk` / `-exporter-otlp-proto-http` | 最新 | `configure_tracing` の span sink（OTLP 既定 / no-op フォールバック） |
| `ddgs` / `tavily-python` 等（任意・結合のみ） | — | ライブ検索プロバイダ。`load_search_provider()` が env で遅延 import。unit には漏らさない（NFR-3） |

> **ベータ注記**: `pydantic-ai-slim` は **V2 ベータ**で `pydantic-graph` を pre-release にピンするため
> `[tool.uv] prerelease = "allow"` が解決に必須だが、runtime の pydantic は `<2.14` 上限で stable に固定し
> alpha 漏れを防ぐ。モデル ID は版に追従して 3〜6か月で変わるため env 経由で解決する。

## 使用例（オフライン最小）

```python
import asyncio
from patterns_deep_research import run_deep_research
from tests.support.fake_search import FakeSearchProvider  # オフラインデモ用フェイク
from tests.support.model_fakes import plan_payload, scripted_model  # オフライン台本モデル

async def main() -> None:
    report = await run_deep_research(
        "What are the trade-offs of multi-agent research systems?",
        # 結合時は Ollama-backed model（pydantic-ai OpenAIChatModel+OllamaProvider）と
        # load_search_provider() を注入する。下記はオフライン決定論デモ。
        model=scripted_model(plan=plan_payload(["lead/researcher の役割分割は?"])),
        search=FakeSearchProvider(),
        max_researchers=3,
        max_iterations=3,
    )
    print(report.report)
    print([c.source for c in report.citations])

asyncio.run(main())
```
