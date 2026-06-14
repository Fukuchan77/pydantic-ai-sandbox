# 008-2c-cross-platform

> **ドラフト（要件未承認）**: 本 spec.md は `/sdd-spec` 承認前の起草版。
> `## Clarifications` の5論点は 2026-06-13 の `/sdd-init` セッションで全て
> **CONFIRMED（推奨採用）**。sse-starlette / FastAPI の現行 API・切断
> ハンドリングは `/sdd-plan` 時に `research.md` で一次情報検証する。

## Project Description

`005-cross-platform`（patterns/ 基盤 + 3フレームワーク実装）と
`006-2a-cross-platform`（shared-contracts パッケージ `patterns/contracts/` 昇格、
単一点ドリフト検知）を前提に、idea2-006 §2c を実体化する。エージェント実行の
イベント（ステップ開始 / ツール呼び出し / トークン / 完了 / エラー）を
**Server-Sent Events でストリーム配信**する最小デモアプリを FastAPI +
sse-starlette で構築し、`httpx` の `ASGITransport` でネットワーク外部依存ゼロの
オフライン検証を行う。

本イテレーション（008）は idea2-008 §2 に範囲を限定する。SSE はワークフロー
パターンではなく**配信インフラの応用レイヤ**であり、原典調査の「FastAPI
EventSourceResponse」に対応する。フロントエンド・WebSocket・本格的な認証は
後続に繰り越す。

- 入力: `specs/inputs/idea2-008-crossplatform.md`
- 全体起票: `specs/inputs/idea2-006-crossplatform.md` §2c / §4 論点4
- 原典調査: `specs/005-cross-platform/research.md`（FastAPI SSE / ストリーミング節）

## Clarifications

### Session 2026-06-13（/sdd-init — 全5論点 CONFIRMED）

idea2-008 §4 論点1–5 を `/sdd-init` のクラリフィケーションで確認。全て draft の
PROPOSED（推奨）を採用し CONFIRMED とした。

- Q: デモアプリの配置はルートアプリ拡張か patterns/ 独立プロジェクトか
  （idea2-008 §4 論点1）→ **A: patterns/ 配下の独立 uv プロジェクト**
  （例 `patterns/sse/`、独自 `pyproject.toml` / `uv.lock` / `.python-version`）。
  ルート CI 無変更の原則（005 で確立）を確実に維持。既存3レーンと同じ独立性規律。
- Q: 配信対象エージェントは何か（§4 論点5）→ **A: routing 単体の最小デモ +
  DI seam**。autonomous-agent（ツール呼び出しイベントが豊富）は差し替え可能な
  DI seam による任意拡張とし、006-2a の4パターン実装完了を硬い前提にしない。
- Q: イベント契約の表現（§4 論点4）→ **A: 判別共用体**
  （`Literal` 判別子 `type` + `Annotated[Union[...], Field(discriminator="type")]`）。
  pyright strict と JSON シリアライズの両立を優先。
- Q: 切断・キャンセル検知の実装（§4 論点3）→ **A**: `request.is_disconnected()`
  を基本とし、ジェネレータ側の `asyncio.CancelledError` / `GeneratorExit` で
  クリーンアップを保証。最終 API は `/sdd-plan` の `research.md` で一次情報検証。
- Q: token イベントの決定論化（§4 論点2 / NFR-2）→ **A**: フェイクモデルが増分
  トークンを固定チャンク列で台本供給し、テストの flakiness を排除する。

## Overview

005/006 で確立した patterns/ の規律を、初の**配信インフラ応用レイヤ（SSE）**へ
拡張する。中核価値は2点。第一に、エージェント実行イベントを **Pydantic で型付け
した判別共用体** として `patterns/contracts/` に定義し、SSE の `event:` 名と
`data:`（JSON）を型から導出することで、クライアント↔サーバ契約をフロントエンド
非依存に固定すること。第二に、`httpx.ASGITransport` + フェイクモデルでストリーム
全体を **ネットワークゼロでオフライン検証**し、とりわけ**切断・キャンセル経路**
（クライアント早期切断でサーバ側ジェネレータが確実に停止しリソースリークしない
こと）を hermetic に保証することである。

イベント契約は 006-2a の単一点ドリフト検知（README 正本 == パッケージ）に乗せる。
デモアプリは patterns/ 配下の独立 uv プロジェクトとし、既存3レーンと同じ独立性
規律（レーン間 import 禁止、契約共有はパス依存のみ、ルート無変更）に従う。

## Scope

**In scope（008 = idea2-008 §2）**

- FastAPI エンドポイント + sse-starlette `EventSourceResponse` による SSE 配信
- 型付きイベントスキーマ（`step_started` / `tool_called` / `token` / `completed` /
  `error` の判別共用体）の `patterns/contracts/` 追加と単一点ドリフト拡張
- 実装済みパターン（既定 routing）をラップして実行を駆動、進行イベントを配信
- `httpx.ASGITransport` + フェイクモデルによるオフライン検証（イベント列順序・
  型・各 data の `model_validate`・切断/キャンセル経路・エラー終端）
- モデルの DI seam（オフライン=フェイク / 結合=Ollama）
- `configure_tracing()` 適用 + span≥1 検証
- パターン README（必須4セクション）、`patterns/README.md` への応用レイヤ索引追加、
  SECURITY-NOTES への SSE リスク → OWASP マッピング
- mise タスク・CI への新プロジェクト反映（ルート無変更維持）

**Out of scope（後続イテレーション、idea2-008 §3）**

- SSE デモのフロントエンド（curl / httpx クライアントでの確認まで）
- WebSocket / 双方向ストリーミング
- 認証・レート制限の本格実装（契約とリスク記述に留める）
- idea2-006 §2b（Docling RAG = spec 007）/ §2d（A2A・ACP）/ §2e（Evals CI）

## Glossary

| 用語 | 定義 |
|------|------|
| SSE プロジェクト | SSE デモアプリを収める独立 uv プロジェクト（配置は Clarifications で確定）。既存3レーンと同じ独立性規律に従う。 |
| EventSourceResponse | sse-starlette が提供する SSE レスポンス。非同期ジェネレータが yield するイベントを `text/event-stream` として配信する。 |
| イベント判別共用体 | `type: Literal[...]` を判別子に持つ Pydantic モデルの Union。SSE の `event:` 名と `data:` JSON を型から導出する。 |
| ASGITransport | httpx の ASGI 直結トランスポート。実ソケットを開かずアプリをインプロセス起動し、ストリームをオフライン検証できる。 |
| 切断経路 | クライアントが早期切断した際にサーバ側ジェネレータを確実に停止しリソースを解放するパス。 |

## Requirements

<!--
EARS 形式。各 Requirement 見出しは数値 id のみ。受入基準は階層番号（1.1, 1.2）。
-->

### Requirement 1: SSE プロジェクトの新設と契約配線

応用レイヤ SSE を、既存レーンと同じ独立性規律で収める。

**Acceptance Criteria**

1.1 THE システム SHALL SSE デモアプリを独立 uv プロジェクト（独自
`pyproject.toml` / `uv.lock` / `.python-version`）として新設すること。

1.2 THE SSE プロジェクト SHALL `patterns/contracts/` を `tool.uv.sources` の
パス依存で import し、イベント契約の複製を持たないこと（006-2a の規律）。

1.3 THE SSE プロジェクト SHALL 他のレーンを import しないこと。配信対象パターンは
DI seam（関数注入）で受け取り、レーンソースへの直接依存を避けること。

1.4 THE システム SHALL ルートの `mise run check` および既存ルートワークフローを
無変更に保つこと。

### Requirement 2: 型付きイベントスキーマと契約

エージェント実行イベントを Pydantic 判別共用体として契約化する。

**Acceptance Criteria**

2.1 THE パターン契約 SHALL 各イベントを `type: Literal[...]` 判別子付き Pydantic
モデルで定義すること: `StepStartedEvent` / `ToolCalledEvent` / `TokenEvent` /
`CompletedEvent` / `ErrorEvent`、および判別共用体 `SseEvent`。

2.2 THE システム SHALL イベントを `patterns/contracts/` に追加し
`patterns_contracts` から再エクスポートすること。`patterns/sse/README.md` に
契約の正本 fenced block を記載し、006-2a の単一点ドリフトテストが README 正本 ==
パッケージ実体の一致を検証すること。

2.3 THE SSE 配信 SHALL `event:` 名を各イベントの `type` 判別子から導出し、`data:`
を当該モデルの JSON 直列化として送出すること。

2.4 THE 契約追加 SHALL 既存パターンの契約・ドリフトテストを破壊しないこと。

### Requirement 3: FastAPI エンドポイントと SSE 配信

エージェント実行を駆動し、進行イベントを SSE でストリーム配信する。

**Acceptance Criteria**

3.1 THE システム SHALL FastAPI エンドポイントを提供し、`sse-starlette` の
`EventSourceResponse` でイベントを逐次配信すること。

3.2 THE エンドポイント SHALL 配信対象エージェント（既定 routing）を実行し、
進行に応じてイベントを yield すること。

3.3 THE 配信モデル SHALL DI seam を介すること（オフラインはフェイク、結合は
Ollama-backed モデル）。

### Requirement 4: イベント列の順序と意味

イベント列の順序と各イベントの妥当性を保証する。

**Acceptance Criteria**

4.1 THE 正常系イベント列 SHALL `step_started` → (`tool_called`)* →
(`token`)* → `completed` の順序に従うこと（`tool_called` / `token` は0回以上）。

4.2 各イベントの `data` SHALL 対応する契約モデルで `model_validate` 可能で
あること。

4.3 WHEN エージェント実行中にエラーが発生した場合、THE システム SHALL
`error` イベントを配信してストリームを終端すること（例外の silent な打ち切りを
禁止）。

4.4 THE ストリーム SHALL 終端マーカー（最終 `completed` または `error`）で
明確に終わること。

### Requirement 5: オフライン検証（ASGITransport）

ストリーム全体をネットワークゼロで検証する。

**Acceptance Criteria**

5.1 THE オフラインテスト SHALL `httpx.ASGITransport` でアプリをインプロセス起動
し、実ソケットを開かずに実行すること（ネットワーク I/O ゼロ）。

5.2 THE システム SHALL フェイクモデルでイベント列の順序と型を検証するテストを
持つこと（R4.1 の順序、各 data の `model_validate`）。

5.3 THE token イベント SHALL フェイクが固定チャンク列で増分トークンを台本供給
することで決定論的に検証されること。

5.4 THE SSE プロジェクトのカバレッジ SHALL `fail_under`（005/006 のレーンフロアに
準拠、ratchet で引き上げ）を満たすこと。

### Requirement 6: 切断・キャンセル経路

クライアント早期切断でサーバ側がリソースリークしないことを保証する。

**Acceptance Criteria**

6.1 WHEN クライアントが早期切断した場合、THE サーバ SHALL イベント生成ジェネ
レータを確実に停止し、保持リソースを解放すること。

6.2 THE システム SHALL ネットワーク I/O ゼロの**インプロセス ASGI 駆動**上で
切断・キャンセルを再現するテストを持ち、ジェネレータ停止（クリーンアップ実行）を
検証すること。ハッピーパス（R5）は `httpx.ASGITransport` を用いるが、httpx の
`ASGITransport` は応答を完全バッファしクライアント早期切断を `http.disconnect` と
して伝播しない（research.md I-3 で一次ソース確認）ため、本基準は同一 ASGI アプリを
`app(scope, receive, send)` で直接駆動し、カスタム `receive()` が `http.disconnect`
を注入する技法で満たす（research.md ADR-4）。いずれも実ソケットを開かない。

6.3 THE 切断処理 SHALL 例外を握り潰さず、リソース解放を保証すること。

### Requirement 7: 可観測性

**Acceptance Criteria**

7.1 THE SSE プロジェクト SHALL `configure_tracing()` を適用し、計装手段を既存
レーンと揃えること（配信対象が routing なら llamaindex/pydantic-ai と同方式）。

7.2 THE オフラインテスト SHALL `InMemorySpanExporter` を注入し、リクエスト→
エージェント実行時にスパンが1つ以上生成されることを検証すること。

7.3 THE スパン属性のアサーション SHALL 末端スパンの存在確認に留めること。

### Requirement 8: セキュリティ

**Acceptance Criteria**

8.1 THE システム SHALL `patterns/SECURITY-NOTES.md` に SSE 固有リスク（イベントに
機微情報を載せない / 接続あたりリソース上限 / 認証前提）を OWASP（無制限消費 /
データ漏洩）へマッピングすること。

8.2 THE SSE プロジェクト SHALL `pip-audit` を dev 依存に含み、`mise run
patterns:audit` および CI で実行すること。

8.3 THE イベント契約 SHALL 機微情報（生のプロンプト全文・認証情報）を `data` に
含めない設計とし、その方針を README に明記すること。

8.4 THE gitleaks / forbid-hardcoded-model-ids の pre-commit フック SHALL SSE
プロジェクトを含む patterns/ 全域を除外しないこと（リポジトリ全域の不変条件）。

### Requirement 9: ドキュメント・タクソノミー

**Acceptance Criteria**

9.1 THE SSE パターン README SHALL 契約の正本（イベント判別共用体）と
**型安全 / テスト / 可観測性 / セキュリティの必須4セクション** を記載すること。

9.2 THE システム SHALL `patterns/README.md` に SSE を**応用レイヤ**として索引
追加すること（Anthropic ワークフロー6パターンの表とは別セクション。SSE は配信
インフラの応用である旨を明記）。

9.3 THE README SHALL FastAPI / sse-starlette のバージョンとベータ注意事項、
curl / httpx での接続例を記載すること。

### Requirement 10: CI

**Acceptance Criteria**

10.1 THE システム SHALL `patterns-ci.yml` の paths トリガとジョブが SSE
プロジェクトを検証するよう反映すること。

10.2 IF SSE 結合に Ollama が必要な場合、THEN THE システム SHALL
`patterns-integration-ollama.yml` 経由で `mise run patterns:test:integration` で
実行するよう反映すること（オフライン検証は通常 CI で実行）。

10.3 THE システム SHALL 既存ルートワークフロー（ci.yml / integration-ollama.yml /
security.yml）を変更しないこと。

### Requirement 11: 開発体験

**Acceptance Criteria**

11.1 THE システム SHALL 既存 mise タスク（`patterns:setup / lint / format /
typecheck / test / audit / check / test:integration`）が SSE プロジェクトを含めて
実行するよう反映すること。

11.2 THE ルート `mise run check` SHALL 本フィーチャ実装後も無変更グリーンで
あること（patterns/ 除外による独立性維持）。

## Non-Functional Requirements

- **NFR-1（再現性）**: SSE プロジェクトは `uv.lock` をコミットし、CI は
  `--locked` で解決する。
- **NFR-2（決定論性）**: token イベントは固定チャンク列のフェイクで供給し、
  テストの flakiness をゼロにする。
- **NFR-3（独立性）**: レーン間 import を持たない。契約共有は
  `patterns/contracts/` のパス依存 import のみ。配信対象は DI seam で注入。
- **NFR-4（カバレッジ）**: `fail_under`（005/006 のフロアを起点に ratchet）。
- **NFR-5（契約単一正本）**: イベント契約の正本はパターン README、実体は
  `patterns/contracts/`。一致は単一点ドリフトテストで担保。
- **NFR-6（リソース安全）**: 切断時にジェネレータとリソースが確実に解放され、
  接続リークが生じないこと。

## Out of Scope / Future Work

idea2-008 §3 / idea2-006 §2b・§2d・§2e 参照: フロントエンド、WebSocket / 双方向、
認証・レート制限の本格実装、Docling RAG（spec 007）、A2A/ACP、Pydantic Evals CI。

## Dependencies

- 005/006-2a の patterns/ 基盤（独立 uv プロジェクト規律、`patterns/contracts/`
  パッケージ、CI 2本、mise タスク群、SECURITY-NOTES）
- FastAPI / sse-starlette（`EventSourceResponse`）/ httpx（`ASGITransport`）
- 配信対象パターン（既定 routing）の実装済みエントリポイント（DI seam 経由）
- pydantic（`patterns/contracts/` のイベントモデル）

## References

- specs/inputs/aiagents-agenticai-bee-pydantic-ai.md — **原典（基盤となる
  オリジナルアイデア / フレームワーク役割分担調査）**。本フィーチャの上位文脈。
- specs/inputs/idea2-008-crossplatform.md — 本イテレーションの起票文書
- specs/inputs/idea2-006-crossplatform.md §2c / §4 論点4 — 全体起票
- specs/005-cross-platform/research.md — FastAPI SSE / ストリーミング節の一次情報
- specs/006-2a-cross-platform/ — shared-contracts 昇格・単一点ドリフトの設計
- patterns/README.md — 二軸タクソノミーとフレームワーク実測比較表
- patterns/contracts/ — 契約パッケージ（イベント契約の追加先）
- OWASP LLM Top 10 2025 / OWASP Agentic AI Top 10 (2025-12)

---

_Initialized (draft): 2026-06-13T10:40:00Z_
_Clarified (/sdd-init, 5/5 CONFIRMED): 2026-06-13T19:45:00Z_
_Requirements generated (/sdd-spec): 2026-06-13T20:10:00Z_
_Requirements validated (/sdd-spec re-run): 2026-06-14T16:10:00Z_
_R6.2 wording reconciled to research.md I-3/ADR-4 (/sdd-validate-plan): 2026-06-14_
