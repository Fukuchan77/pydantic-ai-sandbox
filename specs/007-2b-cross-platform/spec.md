# 007-2b-cross-platform

> **要件生成済み（未承認）**: 本 spec.md は `/sdd-spec` で生成した要件版。
> `## Clarifications` の5論点は 2026-06-13 セッションで全て CONFIRMED（推奨採用）。
> 配置（論点1）・Docling 依存重量（論点2）は方向性確定済みだが、最終確定値は
> 実装冒頭の Spike（tasks Task 0）PoC 実測（uv.lock 差分・CI 時間）で固める。研究項目
> （Docling 依存ツリー・現行 API）は `/sdd-plan` 時に `research.md` で一次情報検証済み。

## Project Description

`005-cross-platform`（patterns/ 基盤 + 3フレームワーク実装）と
`006-2a-cross-platform`（shared-contracts パッケージ `patterns/contracts/` 昇格、
単一点ドリフト検知）を前提に、idea2-006 §2b を実体化する。Docling
`HybridChunker` でドキュメントをチャンク化し、**引用（ソースアンカー）付き回答**を
返す RAG パイプラインを **LlamaIndex** で構築する。

本イテレーション（007）は idea2-007 §2 に範囲を限定する。RAG は Anthropic
「Building Effective Agents」のワークフローパターンではなく**応用レイヤ**であり、
原典調査の「LlamaIndex = RAG / ドキュメント処理」の役割分担に対応する。
PydanticAI / BeeAI への RAG 移植・マルチモーダル・再ランキングは後続に繰り越す。

- 入力: `specs/inputs/idea2-007-crossplatform.md`
- 全体起票: `specs/inputs/idea2-006-crossplatform.md` §2b / §4 論点3
- 原典調査: `specs/005-cross-platform/research.md`（Docling HybridChunker / RAG 節）

## Clarifications

### Session 2026-06-13（CONFIRMED — 全5論点を推奨採用で確定）

- Q: 配置は llamaindex レーン同居か独立レーンか（idea2-007 §4 論点1）→
  **A: 独立レーン `patterns/rag/`（方向性確定）**。Docling は torch/transformers
  等の重量依存を引き込む可能性が高く、既存 llamaindex レーンの lockfile / CI 時間を
  汚染しないよう隔離する。最終確定値は実装冒頭の Spike（tasks Task 0）PoC で uv.lock
  差分・CI 時間を実測して固める（実測で軽量と判明すれば同居に倒す余地を残す）。
- Q: Docling 依存の重量（torch 引き込み）を許容するか（§4 論点2）→
  **A: 許容するが CPU-only / 軽量バックエンドを優先（方向性確定）**。重量が CI
  非実用と実測されれば、結合テストのみ重量依存を要求し、オフラインは事前生成
  チャンクのフィクスチャで回す方式へ退避する。
- Q: 引用 locator の粒度（§4 論点3）→ **A: ドキュメント種別非依存の
  `locator: str`**（例 `page=3` / `section=2.1` / `char=120-240`）。Docling の
  チャンクメタデータから決定論的に導出し、契約は文字列1本に保つ。
- Q: 埋め込みのオフライン決定論化（§4 論点5）→ **A: ハッシュベースのスタブ
  埋め込み**（チャンク内容→決定論ベクトル）。近傍検索順序を固定し、スコア同点時は
  `chunk_id` 昇順タイブレーク（R3.3）で flakiness を排除する。
- Q: ゴールデンスナップショットの更新運用（§4 論点4）→ **A: 手動再生成 / CI 比較
  のみ**。チャンク境界はスナップショットファイルで固定し、Docling バージョン更新時
  のみ明示再生成（差分レビュー必須）。CI は再生成せず比較のみで回帰を loud-fail。

## Overview

005/006 で確立した patterns/ の規律（同一契約 + 必須4セクション + オフライン
hermetic テスト + Ollama 結合ゲート + span 存在検証 + ルート無変更）を、初の
**応用レイヤ（RAG）**へ拡張する。中核価値は、Docling の決定論的チャンカーと
LlamaIndex のクエリエンジンを組み合わせ、**回答の各主張が実在チャンクを指す引用**を
契約レベルで保証すること。引用なりすまし（dangling citation）を loud-fail させ、
RAG 固有の OWASP リスク（インデックス汚染 / データ漏洩 / 過度の依存）を多層防御で
緩和する参照実装を提供する。

契約は `patterns/contracts/` に RAG モデルを追加し、006-2a の単一点ドリフト検知
（README 正本 == パッケージ）にそのまま乗せる。新規 RAG レーンは独立 uv
プロジェクトとして既存3レーンと同じ独立性規律（レーン間 import 禁止、契約共有は
パス依存のみ）に従う。

## Scope

**In scope（007 = idea2-007 §2）**

- Docling `HybridChunker` による決定論的チャンク化（固定ドキュメント、チャンク
  メタデータ: source / locator / chunk_id）
- ベクトルインデックス化 + top-k 検索 + **引用付き回答**（LlamaIndex クエリ
  エンジン + 引用抽出ポストプロセッサ）
- RAG 契約の `patterns/contracts/` 追加（`RagAnswer` / `Citation` / `RetrievedChunk`）と
  単一点ドリフトテストの拡張
- オフライン hermetic テスト（チャンカー実物 + ゴールデンスナップショット、
  埋め込み・LLM はフェイク、引用健全性検証）
- `RUN_INTEGRATION_PATTERNS=1` ゲートの Ollama 結合（契約レベルアサート）
- `configure_tracing()` 適用 + span≥1 検証
- パターン README（必須4セクション）、`patterns/README.md` への応用レイヤ索引追加、
  SECURITY-NOTES への RAG リスク → OWASP マッピング
- mise タスク・CI への新レーン反映（ルート無変更維持）

**Out of scope（後続イテレーション、idea2-007 §3）**

- マルチモーダル（画像・表）チャンク化と引用
- 複数ドキュメント横断・再ランキング・ハイブリッド検索のチューニング
- PydanticAI / BeeAI レーンへの RAG 移植（本イテレーションは LlamaIndex のみ）
- idea2-006 §2c–2e（FastAPI SSE = spec 008 / A2A・ACP / Evals CI）

## Glossary

| 用語 | 定義 |
|------|------|
| RAG レーン | RAG パイプラインを収める独立 uv プロジェクト（配置は Clarifications で確定）。既存3レーンと同じ独立性規律に従う。 |
| HybridChunker | Docling のチャンカー。構造（見出し・段落）とトークン上限の双方を考慮してドキュメントをチャンク化する。本イテレーションでは決定論的挙動を前提に実物を使用。 |
| チャンクメタデータ | 各チャンクが保持する出所情報: `source`（ドキュメント識別子）/ `locator`（ページ・セクション・文字範囲のいずれか）/ `chunk_id`（一意キー）。 |
| 引用 (citation) | 回答中の主張を裏付けるソースアンカー。実在チャンクの `chunk_id` を必ず指す。 |
| dangling citation | 実在しないチャンクを指す引用。本イテレーションは契約検証で禁止し loud-fail させる。 |
| ゴールデンスナップショット | 固定ドキュメントを HybridChunker でチャンク化した既知の結果。回帰検知の基準。 |

## Requirements

<!--
EARS 形式。各 Requirement 見出しは数値 id のみ。受入基準は階層番号（1.1, 1.2）。
-->

### Requirement 1: RAG レーンの新設と契約配線

応用レイヤ RAG を、既存レーンと同じ独立性規律で収める。

**Acceptance Criteria**

1.1 THE システム SHALL RAG パイプラインを独立 uv プロジェクト（独自
`pyproject.toml` / `uv.lock` / `.python-version`）として新設すること。配置
（`patterns/rag/` 独立 or llamaindex レーン同居）は実装冒頭の Spike（tasks Task 0）の
PoC 実測で確定する。

1.2 THE RAG レーン SHALL `patterns/contracts/` を `tool.uv.sources` のパス依存で
import し、契約モデルの複製を持たないこと（006-2a の規律）。

1.3 THE RAG レーン SHALL 他のレーン（pydantic-ai / beeai / llamaindex）を import
しないこと（NFR レーン独立性）。

1.4 IF 配置が独立レーンに確定した場合、THEN THE システム SHALL ルートの
`mise run check` および既存ルートワークフローを無変更に保つこと。

### Requirement 2: Docling HybridChunker によるチャンク化

ドキュメントを決定論的にチャンク化し、出所メタデータを付与する。

**Acceptance Criteria**

2.1 THE システム SHALL Docling `HybridChunker` で固定ドキュメント（PDF /
Markdown 等）をチャンク化し、各チャンクに `source` / `locator` / `chunk_id` を
付与すること。

2.2 THE チャンク化 SHALL 同一入力に対し決定論的（同一チャンク境界・同一
`chunk_id`）であること。

2.3 THE `chunk_id` SHALL レーン内で一意であり、引用が実在チャンクを指せること。

### Requirement 3: インデックス化と検索

チャンクをベクトルインデックス化し、クエリに対する top-k 検索を提供する。

**Acceptance Criteria**

3.1 THE システム SHALL チャンクをベクトルインデックス化し、クエリに対し top-k
（既定 k は実装で定義）の関連チャンクを検索すること。

3.2 THE 埋め込み生成 SHALL DI seam を介すること（オフラインは決定論的フェイク
埋め込み、結合は実埋め込みモデル）。

3.3 THE 検索結果 SHALL 決定論的な順序で復元されること（スコア同点時は
`chunk_id` 昇順の決定論タイブレーク）。

### Requirement 4: 引用付き回答

回答の各主張が実在チャンクを指す引用を伴うことを契約で保証する。

**Acceptance Criteria**

4.1 THE RAG 契約 SHALL 次の構造を定義すること: `RagAnswer{answer: str,
citations: list[Citation]}`、`Citation{source: str, locator: str,
chunk_id: str, score: float}`、`RetrievedChunk{chunk_id: str, source: str,
locator: str, text: str, score: float}`、エントリポイント
`async def run_rag(query: str, *, llm, retriever/index) -> RagAnswer`。

4.2 THE `RagAnswer` SHALL 1件以上の `Citation` を持つこと（引用なし回答を禁止）。

4.3 IF いずれかの `Citation.chunk_id` が検索済みチャンク集合に存在しない場合、
THEN THE RAG パイプライン SHALL 例外を送出して loud-fail すること（dangling
citation の silent 通過を禁止）。

4.4 THE `Citation.locator` SHALL 当該チャンクの出所範囲に対応すること
（locator はドキュメント種別非依存の文字列）。

### Requirement 5: shared-contracts への RAG 契約追加

RAG 契約を契約パッケージの単一実体として追加し、単一点ドリフトに乗せる。

**Acceptance Criteria**

5.1 THE システム SHALL `RagAnswer` / `Citation` / `RetrievedChunk` を
`patterns/contracts/` に追加し、`patterns_contracts` から再エクスポートすること。

5.2 THE システム SHALL `patterns/rag/README.md`（パターン README）に契約の正本
fenced block を記載し、006-2a のドリフトテストが README 正本 == パッケージ実体の
一致を検証すること。

5.3 THE 契約追加 SHALL 既存6パターンの契約・ドリフトテストを破壊しないこと。

### Requirement 6: オフラインテスト

RAG を完全 hermetic に検証する。チャンカーは実物、埋め込み・LLM はフェイク。

**Acceptance Criteria**

6.1 各テストは SHALL ネットワーク I/O ゼロで実行可能であること。

6.2 THE チャンク化テスト SHALL 固定ドキュメントを HybridChunker（実物）で
チャンク化し、ゴールデンスナップショットと一致を検証すること。

6.3 THE 埋め込み・LLM SHALL フェイク（決定論的スタブ埋め込み、引用を含む台本
LLM 応答）で供給すること。

6.4 THE システム SHALL 引用健全性テスト（各 `Citation` が実在チャンクを指し、
`locator` がソース範囲内）と dangling citation 検出テストを持つこと。

6.5 THE RAG レーンのカバレッジ SHALL `fail_under`（005/006 のレーンフロアに準拠、
ratchet で引き上げ）を満たすこと。

### Requirement 7: Ollama 結合テスト

**Acceptance Criteria**

7.1 THE RAG レーン SHALL `RUN_INTEGRATION_PATTERNS=1` でゲートされた結合テストを
持つこと（未設定時 skip）。

7.2 結合テストのアサーションは SHALL 契約レベルに留めること（citations が1件
以上 / 各 citation が既知ソースを指す / 正確なテキスト一致は禁止）。

7.3 結合テストは SHALL `OLLAMA_BASE_URL` / `OLLAMA_MODEL_NAME`（および必要な
埋め込みモデル設定）を環境変数から読むこと。

### Requirement 8: 可観測性

**Acceptance Criteria**

8.1 THE RAG レーン SHALL `configure_tracing()` を適用し、計装手段を LlamaIndex
レーン（OpenInference instrumentor）と揃えること。

8.2 各テストは SHALL `InMemorySpanExporter` を注入し、RAG 実行時にスパンが1つ
以上生成されることを検証すること。

8.3 スパン属性のアサーションは SHALL 末端 LLM / 検索スパンの存在確認に留める
こと（集計はバックエンドの責務）。

### Requirement 9: セキュリティ

**Acceptance Criteria**

9.1 THE システム SHALL `patterns/SECURITY-NOTES.md` に RAG 固有リスク
（インデックス汚染 / 引用なりすまし / PII を含むチャンクの露出）を OWASP LLM
Top 10（過度の依存 / データ漏洩）へマッピングすること。

9.2 THE RAG レーン SHALL `pip-audit` を dev 依存に含み、`mise run patterns:audit`
および CI で実行すること。

9.3 THE 実装 SHALL dangling citation 禁止（R4.3）を「引用なりすまし」緩和の
契約レベル防御として提供すること。

9.4 gitleaks / forbid-hardcoded-model-ids の pre-commit フックは SHALL RAG レーンを
含む patterns/ 全域を除外しないこと（リポジトリ全域の不変条件）。

### Requirement 10: ドキュメント・タクソノミー

**Acceptance Criteria**

10.1 THE RAG パターン README は SHALL 契約の正本と **型安全 / テスト / 可観測性 /
セキュリティの必須4セクション** を記載すること。

10.2 THE システム SHALL `patterns/README.md` に RAG を**応用レイヤ**として索引
追加すること（Anthropic ワークフロー6パターンの表とは別セクション。RAG は
ワークフローパターンではなく LlamaIndex 役割分担の応用である旨を明記）。

10.3 THE README は SHALL Docling / 使用ライブラリのバージョンとベータ注意事項を
記載すること。

### Requirement 11: CI

**Acceptance Criteria**

11.1 THE システム SHALL `patterns-ci.yml` の paths トリガとジョブが RAG レーンを
検証するよう反映すること。

11.2 THE システム SHALL `patterns-integration-ollama.yml` が RAG 結合を
`mise run patterns:test:integration` 経由で実行するよう反映すること。

11.3 既存ルートワークフロー（ci.yml / integration-ollama.yml / security.yml）は
SHALL 変更しないこと。

11.4 IF Docling 依存が CI 実行時間を著しく増やす場合、THEN THE システム SHALL
RAG 結合を別ジョブ / 別ゲートに隔離する選択肢を `/sdd-plan` で検討すること。

### Requirement 12: 開発体験

**Acceptance Criteria**

12.1 THE システム SHALL 既存 mise タスク（`patterns:setup / lint / format /
typecheck / test / audit / check / test:integration`）が RAG レーンを含めて
実行するよう反映すること。

12.2 THE ルート `mise run check` は SHALL 本フィーチャ実装後も無変更グリーンで
あること（patterns/ 除外による独立性維持）。

## Non-Functional Requirements

- **NFR-1（再現性）**: RAG レーンは `uv.lock` をコミットし、CI は `--locked` で
  解決する。
- **NFR-2（決定論性）**: チャンク境界はゴールデンスナップショット、埋め込みは
  ハッシュベースのフェイクで固定し、テストの flakiness をゼロにする。
- **NFR-3（独立性）**: レーン間 import を持たない。契約共有は
  `patterns/contracts/` のパス依存 import のみ。
- **NFR-4（カバレッジ）**: レーン毎 `fail_under`（005/006 のフロアを起点に
  ratchet）。
- **NFR-5（契約単一正本）**: RAG 契約の正本はパターン README、実体は
  `patterns/contracts/`。一致は単一点ドリフトテストで担保。
- **NFR-6（依存重量の管理）**: Docling 導入による依存増を実測し、CI 実用性を
  毀損する場合は隔離 / フィクスチャ退避で対処する。

## Out of Scope / Future Work

idea2-007 §3 / idea2-006 §2c–2e 参照: マルチモーダルチャンク化、再ランキング・
ハイブリッド検索、PydanticAI / BeeAI への RAG 移植、FastAPI SSE（spec 008）、
A2A/ACP、Pydantic Evals CI。

## Dependencies

- 005/006-2a の patterns/ 基盤（独立 uv プロジェクト規律、`patterns/contracts/`
  パッケージ、CI 2本、mise タスク群、SECURITY-NOTES）
- Docling（HybridChunker）/ llama-index-core（クエリエンジン・ノードポスト
  プロセッサ）/ 埋め込みプロバイダ（DI seam 経由）
- pydantic（`patterns/contracts/` の RAG モデル）

## References

- specs/inputs/idea2-007-crossplatform.md — 本イテレーションの起票文書
- specs/inputs/idea2-006-crossplatform.md §2b / §4 論点3 — 全体起票
- specs/005-cross-platform/research.md — Docling / RAG 節の一次情報
- specs/006-2a-cross-platform/ — shared-contracts 昇格・単一点ドリフトの設計
- patterns/README.md — 二軸タクソノミーとフレームワーク実測比較表
- patterns/contracts/ — 契約パッケージ（RAG 契約の追加先）
- OWASP LLM Top 10 2025 / OWASP Agentic AI Top 10 (2025-12)

---

_Initialized (draft): 2026-06-13T10:40:00Z_
