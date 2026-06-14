# 005-cross-platform — Requirements

**Feature Branch**: `claude/happy-noether-939dgs`
**Created**: 2026-06-12
**Status**: Draft
**Input**: PydanticAI・BeeAI Framework・LlamaIndex Workflows を横断した
エージェント実装ベストプラクティス・パターン集（第1イテレーション:
基盤 + routing + orchestrator-workers）。`specs/inputs/idea2-005-cross-platform.md`
および検証済み調査ドキュメント2本（research.md 参照）を起点とする。

## Overview

既存の `src/pydantic_ai_sandbox` は PydanticAI V2 (Beta) 単独の本番志向アプリで
あり、フレームワーク選定の比較材料を提供しない。本フィーチャは `patterns/` 配下に
**同一のパターン契約を 3 フレームワーク（PydanticAI / BeeAI / LlamaIndex）で
実装比較するパターン集** を新設し、各実装に型安全・テスト・可観測性・セキュリティ
の4観点を必須記載することで、フレームワーク選定とベストプラクティス確立の
判断材料を提供する。

第1イテレーションは Anthropic「Building Effective Agents」タクソノミーのうち
**routing** と **orchestrator-workers** の2パターンを対象とする。

## Clarifications

### Session 2026-06-12

- Q: uv workspace か独立プロジェクトか? → A: **独立 uv プロジェクト**。
  beeai-framework の requires-python は `>=3.11,<3.14`（PyPI 確認済）、
  ルートアプリは `>=3.14` であり、workspace の単一解決では交差が空集合になる。
- Q: パッケージ分割の軸は? → A: **フレームワーク単位3プロジェクト**
  （`patterns/frameworks/{pydantic-ai,beeai,llamaindex}`）。各プロジェクトが
  両パターンをモジュールとして内包。パターン横断の比較・契約正本は
  `patterns/<pattern>/README.md` に置く。
- Q: パターン間で共有する契約コード（Pydantic モデル）はどこに置くか? →
  A: **第1イテレーションは各レーンに複製**（約25行）。独立プロジェクト間の
  パス依存配管を避ける。正本はパターン README に明記し、ドリフトは契約テスト
  （同一フィールド名のアサーション）で防ぐ。
- Q: 既存ルートゲート（ruff/pyright/pre-commit/カバレッジ98%）との関係は? →
  A: **ルートゲートから patterns/ を除外**し、レーン毎のゲート
  （`mise run patterns:check` + patterns-ci.yml マトリクス）で担保する。
  gitleaks とモデルIDハードコード禁止ガードはリポジトリ全域で継続適用。
- Q: LlamaAgents（llamactl）を使うか? → A: **第1イテレーションでは不使用**。
  公式 docs が検証時 403 で裏取り不能だったため、`llama-index-core` の
  Workflows のみ使用し、LlamaAgents は将来イテレーションで実測評価する。
- Q: BeeAI のオフラインテストはどうするか? → A: 公式モックが存在しない
  （upstream issue #750）ため、**`ChatModel` を継承した ScriptedChatModel**
  を自作する。upstream 自身のテストスイートが同方式を採る。

## Scope

**In scope（第1イテレーション）**

- `patterns/` ディレクトリ新設（タクソノミー README、SECURITY-NOTES、
  パターン別 README、フレームワーク別レーン3つ）
- routing / orchestrator-workers の 3 フレームワーク実装（計6実装）
- レーン毎のオフラインユニットテスト + ゲート付き Ollama 結合テスト
- レーン毎の OTel 計装ユーティリティとスパン存在テスト
- `mise patterns:*` タスク群、patterns-ci.yml / patterns-integration-ollama.yml
- ルート設定への最小ガード追加（ruff/pyright/pre-commit の patterns/ 除外）

**Out of scope（将来イテレーション、idea2 §3）**

- 残り4パターン、Docling RAG、FastAPI SSE デモ、A2A/ACP 相互運用、
  Pydantic Evals CI 組込、shared-contracts パッケージ化

## Glossary

- **レーン (lane)**: `patterns/frameworks/<fw>/` 配下の独立 uv プロジェクト1つ。
- **パターン契約 (pattern contract)**: 全レーンが共有する入出力 Pydantic モデル
  とエントリポイント関数シグネチャ。正本はパターン README。
- **routing**: 分類器がクエリを `Literal` 経路語彙のいずれかに割り当て、
  経路別の回答器に委譲するワークフロー（Anthropic taxonomy）。
- **orchestrator-workers**: プランナが動的にサブタスクを生成し、並列ワーカーの
  結果をシンセサイザが統合するワークフロー（Anthropic taxonomy）。

## Requirements

### Requirement 1: パターン集の構造

`patterns/` 配下に、比較可能で拡張可能なパターン集の骨格を提供する。

**Acceptance Criteria**

1.1 THE システム SHALL `patterns/frameworks/{pydantic-ai,beeai,llamaindex}/` に
独立 uv プロジェクト3つ（各自の pyproject.toml / uv.lock / .python-version /
src レイアウト / tests/）を提供する。

1.2 各レーンの requires-python は SHALL 次の通り:
pydantic-ai レーン = `>=3.14`、beeai レーン = `>=3.13,<3.14`、
llamaindex レーン = `>=3.13,<3.14`。

1.3 THE システム SHALL `patterns/routing/README.md` と
`patterns/orchestrator-workers/README.md` に、パターン契約の正本と
**型安全 / テスト / 可観測性 / セキュリティの必須4セクション** を記載する。

1.4 THE システム SHALL `patterns/README.md` に Anthropic 6 ワークフロー ×
IBM「AI Agent vs Agentic AI」粒度の二軸タクソノミー、3フレームワーク比較表、
実装済みパターンの索引を記載する。

1.5 モデル ID は SHALL ハードコードせず、`OLLAMA_MODEL_NAME` /
`OLLAMA_BASE_URL` 環境変数から取得する（Spec 001 Req 1.5 継承。
pre-commit の forbid-hardcoded-model-ids ガードは patterns/ にも適用される）。

### Requirement 2: routing パターン

**Acceptance Criteria**

2.1 パターン契約は SHALL 次の通り:
`RouteDecision{route: Literal["billing","technical","general"], reasoning: str}` →
`RoutedAnswer{route, answer: str}`、エントリポイント
`async def run_routing(query: str, *, model/llm) -> RoutedAnswer`。

2.2 各レーンは SHALL 分類ステップ（構造化出力で RouteDecision を取得）と
経路別回答ステップの2段で実装する:
PydanticAI = 分類 Agent → 経路別 Agent の dispatch、
LlamaIndex = Workflow の `@step` 連鎖、
BeeAI = Workflow + ChatModel 構造化出力。

2.3 WHEN 分類器が経路語彙外の値を返した場合、THE 実装 SHALL 検証エラーを
発生させる（Literal / Enum による語彙固定。silent fallback 禁止）。

### Requirement 3: orchestrator-workers パターン

**Acceptance Criteria**

3.1 パターン契約は SHALL 次の通り:
`TaskPlan{subtasks: list[SubTask]}`（SubTask は `description` を持つ）→
並列実行で `WorkerResult{subtask, output}` のリスト →
`OrchestratedResult{plan, results, summary: str}`、エントリポイント
`async def run_orchestrator(task: str, *, model/llm, max_workers: int = 3) ->
OrchestratedResult`。

3.2 THE 実装 SHALL `max_workers` を上限としてサブタスク数を制限する
（過剰エージェンシー緩和、OWASP Agentic AI 対応。上限超過分は切り捨て、
切り捨ての発生が結果から判別可能であること）。

3.3 ワーカー実行は SHALL 並列（`asyncio.gather` または各フレームワークの
fan-out 機構）で行い、結果順序はプランのサブタスク順序を保持する。

### Requirement 4: オフラインテスト

**Acceptance Criteria**

4.1 各レーンのユニットテストは SHALL ネットワーク I/O ゼロで実行可能であること。
フェイクは: pydantic-ai = TestModel / FunctionModel、
llamaindex = MockLLM またはスクリプト化フェイク LLM、
beeai = `ChatModel` 継承の ScriptedChatModel。

4.2 各レーンは SHALL スモークテスト（パッケージ import + フェイク1ターン +
型付き結果の検証）を持つ。

4.3 各レーンの両パターンについて SHALL 正常系 + 契約違反系（経路語彙外 /
max_workers 超過）のユニットテストを持ち、カバレッジ `fail_under = 85` を
満たす。

4.4 各レーンのテストは SHALL レーンディレクトリ内で `uv run pytest` により
独立実行できる。

### Requirement 5: Ollama 結合テスト

**Acceptance Criteria**

5.1 各レーンは SHALL `RUN_INTEGRATION_PATTERNS=1` 環境変数でゲートされた
結合テストを `tests/integration/` に持つ（未設定時 skip。Spec 001 T11 と同形）。

5.2 結合テストのアサーションは SHALL 契約レベルに留める（route が Literal
語彙内、worker 結果が1件以上、summary 非空。正確なテキスト一致は禁止）。

5.3 結合テストは SHALL `OLLAMA_BASE_URL` / `OLLAMA_MODEL_NAME` を環境変数から
読む。

### Requirement 6: 可観測性

**Acceptance Criteria**

6.1 各レーンは SHALL `observability.py` に `configure_tracing()` を提供する:
`OTEL_EXPORTER_OTLP_ENDPOINT` 設定時のみ OTLP エクスポート、未設定時は
呼び出し側が注入した exporter（テスト）または no-op。

6.2 各レーンのユニットテストは SHALL `InMemorySpanExporter` を注入して
パターン実行時にスパンが1つ以上生成されることを検証する。
計装手段: pydantic-ai = `Agent(instrument=...)`、
llamaindex = openinference-instrumentation-llama-index、
beeai = フレームワーク OTel 統合または手動スパン（フォールバック許容）。

6.3 トークン使用量の二重計上を避けるため、スパン属性のアサーションは SHALL
末端 LLM スパンの存在確認に留める（集計はバックエンド側の責務とする。
research.md「トークン二重計上」参照）。

### Requirement 7: セキュリティ

**Acceptance Criteria**

7.1 THE システム SHALL `patterns/SECURITY-NOTES.md` に次を記録する:
CVE-2026-25580 / CVE-2026-46678（pydantic-ai SSRF → `>=2.0.0b6` は修正後継で
あることの根拠）、CVE-2025-1793（vector store SQLi → 本イテレーション非該当、
Docling RAG イテレーションのゲートとして記録）、CVE-2025-1752
（`llama-index-readers-web>=0.3.6` フロア。現時点で非依存）、
`llama-stack` 採用禁止（CVE-2024-50050）、OWASP Agentic AI Top 10 への
パターン別マッピング。

7.2 各レーンは SHALL `pip-audit` をレーン dev 依存に含み、
`mise run patterns:audit` および CI で実行する。

7.3 llamaindex レーンの依存は SHALL `llama-index-readers-web` と
`llama-stack` を含まない。

7.4 gitleaks / forbid-hardcoded-model-ids の pre-commit フックは SHALL
patterns/ を除外しない（リポジトリ全域の不変条件）。

### Requirement 8: CI

**Acceptance Criteria**

8.1 THE システム SHALL `.github/workflows/patterns-ci.yml` を新設する:
`patterns/**` 等の paths トリガ、`fail-fast: false` の 3 レーンマトリクス、
各レーンで `uv sync` → ruff check → ruff format --check → pyright →
pytest --cov → pip-audit。

8.2 THE システム SHALL `.github/workflows/patterns-integration-ollama.yml` を
新設する: 既存 integration-ollama.yml のデーモン構築（docker + モデルキャッシュ +
readiness ループ）を踏襲し、workflow_dispatch + 週次 cron + paths PR で
`mise run patterns:test:integration` を実行する。

8.3 既存ワークフロー（ci.yml / integration-ollama.yml / security.yml）は
SHALL 変更しない。

### Requirement 9: 開発体験

**Acceptance Criteria**

9.1 THE システム SHALL mise タスク `patterns:setup / patterns:lint /
patterns:format / patterns:typecheck / patterns:test / patterns:audit /
patterns:check / patterns:test:integration` を提供する（全レーンを順次実行、
`set -e` で最初の失敗で停止）。

9.2 ルートの `mise run check` は SHALL 本フィーチャ実装後も無変更でグリーン
であること（patterns/ 除外による独立性）。

### Requirement 10: ドキュメント

**Acceptance Criteria**

10.1 各レーンは SHALL README.md にセットアップ（`uv sync`）、テスト実行、
使用フレームワークのバージョン・ベータ注意事項を記載する。

10.2 パターン README の必須4セクションは SHALL フレームワーク間の差異
（構造化出力の方式、フェイクの作り方、計装手段、固有のリスク）を比較形式で
記載する。

## Non-Functional Requirements

- **NFR-1（再現性）**: 各レーンは uv.lock をコミットし、CI は lock どおりに
  解決する。
- **NFR-2（ベータ追従）**: pydantic-ai レーンはルートアプリと同じ
  `>=2.0.0b6` を使用し、ルートのバージョン更新に追従する。
- **NFR-3（独立性）**: レーン間に import 依存を持たない。契約の同一性は
  README 正本 + 各レーンの契約テストで担保する。
- **NFR-4（カバレッジ）**: レーン毎 `fail_under = 85`（初期値。ルートの
  ratchet 慣行に従い将来引き上げ）。

## Out of Scope / Future Work

idea2-005-cross-platform.md §3 参照（残り4パターン、Docling RAG、SSE、
A2A/ACP、Evals CI、shared-contracts）。

## Dependencies

- beeai-framework（PyPI、`>=3.11,<3.14`）— 厳密ピン（リスク R-1 参照）
- llama-index-core / llama-index-llms-ollama /
  openinference-instrumentation-llama-index
- pydantic-ai-slim[openai] >= 2.0.0b6（ルートと同一系）
- opentelemetry-sdk（テスト用 InMemorySpanExporter）

## References

- specs/005-cross-platform/research.md — 調査ドキュメント検証結果・CVE 表
- specs/005-cross-platform/plan.md — 設計（AD-1〜AD-5）
- Anthropic "Building Effective Agents" / IBM "AI Agents vs Agentic AI"
- OWASP Agentic AI Top 10 (2025-12) / OWASP LLM Top 10 2025
