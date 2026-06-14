# SSE 配信パターン（応用レイヤー / FastAPI + sse-starlette 役割分担）

エージェント実行イベント（ステップ開始 / ツール呼び出し / トークン / 完了 / エラー）を
**Server-Sent Events でストリーム配信**する単一レーン（`patterns/sse/`）。Anthropic の
6ワークフローパターンとは別系の**配信インフラ応用レイヤ**で、FastAPI +
[sse-starlette](https://github.com/sysid/sse-starlette) の `EventSourceResponse` を
「型付きイベント → `text/event-stream` ワイヤ表現」の役割分担に用いる。配信対象エージェントは
**DI seam（`EventSource` Protocol 注入）**で受け取り、レーン src はフレームワーク非結合に保つ
（オフライン=台本フェイク / 結合=Ollama-backed pydantic-ai アダプタ、NFR-3 / R1.3）。
クライアント早期切断時にサーバ側ジェネレータが確実に停止しリソースを解放すること（R6）と、
実行中エラーが silent に打ち切られず `error` イベントで終端すること（R4.3）を、
`httpx.ASGITransport` とインプロセス ASGI 駆動で**ネットワークゼロ**に検証する。

## パターン契約（正本）

契約の実体は依存ゼロの [`patterns_contracts`](../contracts/) パッケージ
（[`sse.py`](../contracts/src/patterns_contracts/sse.py)）。下記の Python コードブロックが
その**正本**であり、
[`patterns/contracts/tests/unit/test_contract_drift.py`](../contracts/tests/unit/test_contract_drift.py)
が両者（クラス集合・フィールド集合・`Literal` 語彙）の一致を1点で検証する（Req 2.2 / 006-2a NFR-5）。
各イベントの `type` 判別子の閉じた `Literal` 語彙が、そのまま SSE の `event:` 名としてロックされる
（Req 2.3）。判別共用体 `SseEvent` は `Annotated` エイリアスでありモデルクラスでも `Literal` でも
ないため、ドリフト parser は `ApprovalHook`（Callable エイリアス）同様に両側で対称スキップする
（research.md I-5）。SSE レーンは5モデルと `SseEvent` をここからパス依存で import し、レーン内で
再定義しない（NFR-3 / Req 1.3）。

```python
class StepStartedEvent(BaseModel):     # 実行ステップが開始した（例 classify / answer）
    type: Literal["step_started"] = "step_started"   # 判別子。SSE の event: 名に一致（R2.3）
    step: str           # 開始したステップ名

class ToolCalledEvent(BaseModel):      # 実行中にツールが呼び出された
    type: Literal["tool_called"] = "tool_called"     # 判別子 = event: 名
    tool: str           # 呼び出されたツール名
    args_json: str      # サニタイズ済みの引数 JSON 文字列。機微情報を載せない（R8.3）

class TokenEvent(BaseModel):           # 増分出力トークン（固定チャンクで決定論化、R5.3）
    type: Literal["token"] = "token"   # 判別子 = event: 名
    text: str           # 増分トークンテキスト

class CompletedEvent(BaseModel):       # 最終出力。ストリームを綺麗に終える終端マーカー（R4.4）
    type: Literal["completed"] = "completed"          # 判別子 = event: 名
    output: str         # エージェントの最終出力

class ErrorEvent(BaseModel):           # 実行時エラー。ストリームを終端する終端マーカー（R4.3/R4.4）
    type: Literal["error"] = "error"   # 判別子 = event: 名
    message: str        # 例外の1行要約。traceback / 認証情報を載せない（R8.3）

SseEvent = Annotated[StepStartedEvent | ToolCalledEvent | TokenEvent | CompletedEvent | ErrorEvent, Field(discriminator="type")]   # 判別共用体（R2.1）。parser はスキップ（I-5）
```

`event:` 名 = `type` 判別子 / `data:` = `model_dump_json()` の双方向写像は
[`events.py`](src/patterns_sse/events.py) の `to_sse` / `parse_sse_events` に集約する（ADR-3）。
受信側は `event:` で分岐せず `data:` の JSON を正本とし、`TypeAdapter(SseEvent).validate_json` で
判別子から元モデルへ逆写像する（Req 4.2）。

## パイプライン（単一レーン・FastAPI + sse-starlette 役割分担）

| 段 | 実装 | 決定論シーム / 不変条件 |
|---|---|---|
| DI seam | `EventSource` Protocol（[`events.py`](src/patterns_sse/events.py)） | `def stream(query) -> AsyncIterator[SseEvent]` を構造適合で注入（フェイク / Ollama アダプタ）。レーン src は配信対象に非結合（R1.3 / NFR-3） |
| アプリ生成 | `create_app(*, event_source, tracer_provider=None)`（[`app.py`](src/patterns_sse/app.py)） | DI seam で producer と tracer を closure。`POST /sse/runs`（body `{query: str}`）を公開 |
| 直列化 | `to_sse`（[`events.py`](src/patterns_sse/events.py)） | `event:` = `type` 判別子、`data:` = `model_dump_json()`（ADR-3 / R2.3） |
| 配信 | `EventSourceResponse`（sse-starlette） | `step_started → tool_called* → token* → completed` の順序保証（R4.1）、`completed`/`error` の終端マーカーで明確終了（R4.4） |
| 切断・終端 | `_event_stream` ジェネレータ（[`app.py`](src/patterns_sse/app.py)） | `is_disconnected()` 協調 break + `except CancelledError: raise` + `finally: aclose()` でリソース解放（R6.1/6.3）。実行中エラーは `error` 化し silent 打ち切り禁止（R4.3） |
| 逆写像 | `parse_sse_events`（[`events.py`](src/patterns_sse/events.py)） | `data:` 行のみ抽出し `TypeAdapter(SseEvent).validate_json` で逆写像（R4.2） |

## 必須4セクション

### 型安全

- 契約 `StepStartedEvent` / `ToolCalledEvent` / `TokenEvent` / `CompletedEvent` / `ErrorEvent` と
  判別共用体 `SseEvent` は `patterns_contracts` の単一実体。レーンはパス依存で import し再定義しない
  （NFR-3）。pyright **strict**（Python 3.14）で検査。
- イベント契約は `type: Literal[...]` を判別子に持つ判別共用体
  `Annotated[Union[...], Field(discriminator="type")]` で表現し、JSON シリアライズと pyright strict を
  両立する（Req 2.1）。`event:` 名と `data:` JSON を型から導出（Req 2.3）。
- `EventSource` Protocol は `@runtime_checkable` な DI seam。配信対象は関数注入で受け取り、レーン src は
  フレームワーク・兄弟レーンに非結合（R1.3）。`Any` は I/O 境界に留め、`TypeAdapter` 逆写像で
  契約モデルへ narrow してから内側へ流す。

### テスト

- **オフライン hermetic**（Req 5.1）: 全 unit がネットワーク I/O ゼロで完走。`block_network` フィクスチャが
  AF_INET/AF_INET6 の reach を monkeypatch で loud-fail（飾りでない load-bearing テスト併設）。
  ハッピーパスは `httpx.ASGITransport`、切断・キャンセルは `app(scope, receive, send)` の
  インプロセス直接駆動で実ソケットを開かずに再現（ADR-4）。
- **決定論フェイク**（NFR-2 / R5.3）: `ScriptedEventSource` が固定 `SseEvent` 列を決定論で yield し、
  `token` の増分テキスト列が実行間で完全一致することを検証。`fail_at` / `block_after` seam で実行中
  エラーと早期切断を任意点で誘発し、エラー終端（R4.3/4.4）と切断時のクリーンアップ（R6）を立証。
- **カバレッジゲート**: 兄弟レーン parity で `fail_under=98`（Req 5.4 / NFR-4）。残る到達困難なグルー分岐は
  rationale を `pyproject.toml` に恒久記録（research.md R-4）。
- **実 Ollama 結合**: `RUN_INTEGRATION_PATTERNS=1` でゲートし、`run_stream_events` の
  `AgentStreamEvent → SseEvent` 写像アダプタで契約レベル（イベント列順序 / 各 `data` の `model_validate`
  / span≥1）のみアサート、正確なテキスト一致は禁止（非決定的な実モデルゆえ、決定論は台本フェイクの所掌）。

### 可観測性

- `configure_tracing(exporter=None) -> TracerProvider`（[`observability.py`](src/patterns_sse/observability.py)）を
  兄弟レーンと同形で適用（Req 7.1 / ADR-5）。本レーンは framework instrumentor を持たず、per-request span は
  `app.py` の `_open_span`（`sse.stream`）が自前で開く（`None` 注入時は no-op）。
- exporter 優先チェーン: **注入 > `OTEL_EXPORTER_OTLP_ENDPOINT` > no-op**。`InMemorySpanExporter` 注入で
  リクエスト→実行時に span≥1 の**存在**を検証する（属性集計はバックエンド責務でアサートしない、
  Req 7.2/7.3）。結合では `InstrumentationSettings` 併用で `gen_ai.*` span も同一 provider に集約。

### セキュリティ

- **イベントに機微情報を載せない**（Req 8.3）: `data` に生のプロンプト全文・認証情報・full traceback を
  含めない最小フィールド設計。`ToolCalledEvent.args_json` と `ErrorEvent.message` は **producer 側が
  secret-free に保つ責務**を負うサニタイズ済み要約であり、契約は依存ゼロの素な形状を保つ（field 制約に
  しない）。`error` の `message` は `"<ExcType>: <str(exc)>"` の1行要約のみ。
- **接続あたりリソース上限**（NFR-6）: 終端マーカー忘れに備えた安全上限（`_MAX_EVENTS`）と stalled client に
  備えた `send_timeout` で、非終端 producer や滞留クライアントが配信タスクを wedge しないことを保証。
  切断時は `finally: aclose()` でジェネレータを確実に解放し接続リークを防ぐ（R6.1/6.3）。
- **認証前提**: 本デモは認証・レート制限を範囲外とし（curl / httpx での確認まで）、本番では認証済み
  コンテキストでの配信を前提とする。
- **モデル ID ハードコード禁止**: Ollama の接続/モデルは env 専属（`OLLAMA_BASE_URL` /
  `OLLAMA_MODEL_NAME`）。gitleaks / forbid-hardcoded-model-ids は `patterns/sse/` を含む `patterns/`
  全域を除外しない。
- SSE 固有リスク（イベントへの機微情報混入 / 無制限消費 / データ漏洩）→ OWASP（LLM Top 10 / Agentic AI）の
  詳細マッピングは [SECURITY-NOTES.md](../SECURITY-NOTES.md)（Task 13.2 で追記）。

## 使用ライブラリとバージョン

| ライブラリ | バージョン | 役割 / 注記 |
|---|---|---|
| `fastapi` | 0.136 系 | エンドポイント `POST /sse/runs`。`requires-python>=3.14`、floor `>=0.136`（Task 0 spike 解決版） |
| `sse-starlette` | 3.4 系（**1.0 後だが API 流動的**） | `EventSourceResponse`。切断は本体ジェネレータへの `asyncio.CancelledError`（task-group cancel）が load-bearing 経路 |
| `starlette` | 1.3 系 | fastapi 要求の stable（alpha ではない）。`request.is_disconnected()` は協調的二次手段 |
| `httpx` | 0.28 系（dev） | `ASGITransport` でハッピーパスを全文バッファ取得（ADR-4a）。有限ストリーム前提 |
| `pydantic` | >=2,<2.14 | 契約モデル基底。runtime 閉包を **stable** に固定（dev の pydantic-ai beta が引く alpha を遮断） |
| `opentelemetry-sdk` / `-exporter-otlp-proto-http` | 最新 | `configure_tracing` の span sink（OTLP 既定 / no-op フォールバック） |
| `pydantic-ai-slim[openai]` | 2.0.0b6 系（**beta**、dev/結合のみ） | gated Ollama 結合の `run_stream_events` アダプタ専用。レーン runtime には漏らさない（NFR-3） |

> **ベータ注記**: `sse-starlette` 3.4.x は API（特に切断ハンドリングと `EventSourceResponse` の
> 引数）が版間で変わり得るため `uv.lock` で固定し、版更新時は切断・キャンセル経路の hermetic テスト
> （`app(scope, receive, send)` 直接駆動）で回帰を検知する。`pydantic-ai-slim` は **V2 ベータ**で
> `pydantic-graph` を pre-release にピンするため `[tool.uv] prerelease = "allow"` が dev 解決に必須だが、
> runtime の pydantic は `<2.14` 上限で stable に固定し alpha 漏れを防ぐ。モデル ID は版に追従して
> 3〜6か月で変わるため、コードにハードコードせず env 経由で解決する。

## 接続例（curl / httpx）

アプリは DI seam で配信対象を受け取るため、起動時に `EventSource` を注入する。
ローカル起動（オフライン台本フェイクを注入する最小例）:

```python
# app/server.py（例: uvicorn で起動するエントリ）
from patterns_sse import create_app
from tests.support.scripted_source import ScriptedEventSource  # オフラインデモ用フェイク

app = create_app(event_source=ScriptedEventSource())
# 結合時は run_stream_events アダプタ（Ollama-backed）を注入（Task 10 参照）
```

```bash
# uvicorn 起動後、curl で text/event-stream を購読する
uvicorn app.server:app --port 8000

curl -N -X POST http://localhost:8000/sse/runs \
  -H 'Content-Type: application/json' \
  -d '{"query": "hello"}'
# => event: step_started / data: {"type":"step_started","step":"classify"}
#    event: token / data: {"type":"token","text":"..."}
#    ...
#    event: completed / data: {"type":"completed","output":"..."}
```

```python
# httpx クライアントで購読し、data: 行を型付き SseEvent へ逆写像する
import httpx
from patterns_sse import parse_sse_events

with httpx.Client(timeout=None) as client:
    with client.stream(
        "POST", "http://localhost:8000/sse/runs", json={"query": "hello"}
    ) as response:
        body = "".join(response.iter_text())
events = parse_sse_events(body)  # list[SseEvent]（判別子で元モデルへ逆写像、R4.2）
```

> **オフライン検証**: テストは実ソケットを開かず `httpx.ASGITransport` でインプロセス駆動する
> （`transport=httpx.ASGITransport(app=create_app(event_source=...))`）。上記の `localhost` 例は
> 手動確認・デモ用で、CI のオフライン検証はネットワークゼロの ASGITransport / scope 直接駆動で行う。
