# Idea: Spec 008 — Cross-Platform Pattern Collection 2c（FastAPI SSE）

- 起票日: 2026-06-13
- 前提:
  - `005-cross-platform` 完了（patterns/ 基盤 + 3フレームワーク実装、CI 2本）。
  - `006-2a-cross-platform` で **shared-contracts パッケージ
    `patterns/contracts/`**（依存ゼロ・`requires-python >=3.13`・PEP 561 `py.typed`）
    を昇格済み。契約ドリフト検知は「README 正本 == パッケージ」の単一点
    （4テスト GREEN）へ縮約済み。SSE のイベントスキーマも同パッケージ + 単一点
    ドリフトの規律に乗せる。
  - 注: 006-2a の残り4パターン実装（tasks 3〜12）は未完。本イテレーションは
    契約パッケージ基盤の上に積むが、4パターン実装の完了を硬い前提とはしない。
- ねらい: idea2-006 §2c を実体化する。エージェント実行のイベント（ステップ開始 /
  ツール呼び出し / トークン / 完了）を **Server-Sent Events でストリーム配信**する
  最小デモアプリを FastAPI + sse-starlette で構築し、`httpx` の `ASGITransport`
  でネットワーク外部依存ゼロのオフライン検証を行う。

---

## 1. 入力ドキュメントと検証前提

- 起票元: `specs/inputs/idea2-006-crossplatform.md` §2c / §4 論点4
- 原典調査: `specs/005-cross-platform/research.md`（FastAPI EventSourceResponse /
  Production Architectures for Agentic AI のストリーミング節）
- sse-starlette `EventSourceResponse` の現行 API・FastAPI バージョン整合・
  クライアント切断ハンドリングは**実装時に Web + 実測で再検証**し
  `specs/008-*/research.md` に記録する（005/006 の検証規律を踏襲）。

## 2. スコープ（2c = FastAPI SSE）

### 2a. SSE ストリーミングデモアプリ

- FastAPI エンドポイントがエージェント実行を駆動し、進行イベントを
  `sse-starlette` の `EventSourceResponse` で逐次配信する。
- 配信するエージェントは 005/006 のパターン（routing 等、実装済みのもの）を
  ラップする最小構成。LLM はデモ用に env 経由のローカルモデル or フェイクへ
  差し替え可能な DI seam を設ける。
- イベント種別: `step_started` / `tool_called` / `token`（増分テキスト） /
  `completed` / `error`。各イベントは **Pydantic モデルで型付け**し、SSE の
  `event:` 名と `data:`（JSON）を型から導出する。

### 2b. 型付きイベントスキーマと契約規律

- イベントスキーマは `patterns/contracts/` に追加（`SseEvent` 判別共用体 or
  種別毎モデル + `Literal` 判別子）。正本は新設パターン README、ドリフトは
  既存単一点テスト（006-2a）が検知する。
- クライアント↔サーバの契約（イベント名・data スキーマ・終端マーカー）を
  README 正本に明記し、フロントエンド非依存にする。

### 2c. オフライン検証（ASGITransport）

- `httpx.ASGITransport` でアプリをインプロセス起動し、**フェイクモデル**で
  ストリーム全体をオフライン検証（ネットワーク I/O ゼロ）。
- 検証対象: ① イベント列の順序と型（step→tool→token*→completed） ②
  各イベントの data が契約スキーマで `model_validate` 可能 ③ **切断・キャンセル
  経路**（クライアント早期切断でサーバ側ジェネレータが確実に停止しリソース
  リークしないこと） ④ エラー時に `error` イベントで終端すること。

### 2d. 配置 / 可観測性 / セキュリティ

- **配置**（idea2-006 §4 論点4）: ルートアプリ拡張 vs `patterns/` 配下の独立
  プロジェクト。ルート CI 無変更の原則（005 で確立）を維持できる方を選ぶ。
  既定候補は patterns/ 配下の独立 uv プロジェクト（ルート無影響を保証）。
- `configure_tracing()` 適用 + span≥1 検証（リクエスト→エージェント実行の
  スパンが生成されること）。
- SECURITY-NOTES に SSE 固有リスク（イベントに機微情報を載せない /
  接続あたりリソース上限 / 認証前提）を OWASP（無制限消費・データ漏洩）へ
  マッピング。`pip-audit` を新プロジェクト dev 依存に含む。

## 3. スコープ外（後続イテレーション）

- SSE デモのフロントエンド（`curl` / `httpx` クライアントでの確認まで。
  idea2-006 §3）
- WebSocket / 双方向ストリーミング（SSE 単方向に限定）
- 認証・レート制限の本格実装（契約とリスク記述に留め、実装は将来）
- idea2-006 §2b（Docling RAG = spec 007）/ §2d（A2A・ACP）/ §2e（Evals CI）

## 4. /sdd 起動時に解決すべき論点

1. **配置**（§2d）: ルートアプリ拡張 vs patterns/ 独立プロジェクト。ルート
   `mise run check` 無変更グリーンを維持できる方。既定は独立プロジェクト。
2. **token イベントの決定論化**: フェイクモデルが増分トークンを台本供給する
   方式（チャンク分割を固定し、テストの flakiness を排除）。
3. **切断検知の実装**: `EventSourceResponse` の切断ハンドリングを
   `request.is_disconnected()` で行うか、ジェネレータの `GeneratorExit` /
   `asyncio.CancelledError` で行うか（ASGITransport で再現可能な方式を選ぶ）。
4. **イベント契約の表現**: 判別共用体（`Literal` 判別子 + `Annotated` Union）か、
   共通基底 + 種別フィールドか。pyright strict と JSON シリアライズの両立を優先。
5. **どのパターンを配信対象にするか**: routing 単体の最小デモか、006-2a の
   autonomous-agent（ツール呼び出しイベントが豊富）か。後者は 006-2a 実装の
   完了に依存するため、最小デモ（routing）を既定とし autonomous は任意拡張。

## 5. 参考

- `specs/inputs/idea2-006-crossplatform.md` — 第2イテレーション全体の起票文書
- `specs/006-2a-cross-platform/` — shared-contracts 昇格・単一点ドリフトの設計
- `specs/005-cross-platform/research.md` — FastAPI SSE / ストリーミング節の一次情報
- `patterns/README.md` — 二軸タクソノミーとフレームワーク実測比較表
- `patterns/contracts/` — 契約パッケージ（本イテレーションのイベント契約の追加先）
- OWASP LLM Top 10 2025 / OWASP Agentic AI Top 10 (2025-12)
