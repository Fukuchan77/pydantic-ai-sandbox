# 008-2c-cross-platform — Discovery & Research Log

`/sdd-plan` 生成。`gap-analysis.md`（要件 ↔ 既存コードの差分）を起点に、外部依存
（Pydantic AI V2 ストリーミング / sse-starlette 切断 / httpx ASGITransport / FastAPI
切断検知）の一次検証と設計判断（ADR）を確定する。実測 PoC（uv.lock 差分・CI 時間・
ASGITransport 切断挙動の最終確認）は `/sdd-impl` 冒頭の Spike タスクに委譲し、本ログは
その判断基準を固定する。

調査日: 2026-06-14 / 一次情報: 各 OSS 公式ドキュメント・ソース（context7 /
GitHub raw）・PyPI メタデータ・既存レーン実コード。

## Discovery type

**Extension（light）**。005/006-2a/007-2b が確立した patterns/ 規律（独立 uv レーン・
`patterns/contracts/` パス依存・単一点ドリフト・per-lane テスト三層・OTel/OpenInference
計装・mise/CI 二系統・SECURITY-NOTES/README 索引）に、**2 つ目の応用レイヤ（SSE 配信
インフラ）**を積む。**Spec 007-2b の `patterns/rag/` がほぼそのまま型紙**（depth 1 で
`frameworks/` の兄弟・`contracts` パス依存・独自 `pyproject.toml`/`uv.lock`/
`.python-version`・専用 mise 行・CI 専用ジョブ）。新規ビルドは 2 点に局所化される
（① エージェント実行 → イベント列の導出、② 切断・キャンセル経路の hermetic 再現）。
greenfield 探索は不要で、整合点の確認と上記 2 点の一次検証が主。

## Investigations

### I-1. Pydantic AI V2 のストリーミング/イベント API（R3/R4 ⇄ NFR-2）

- **Question**: `run_routing` は最終値 `RoutedAnswer` のみ返す。`step_started →
  tool_called* → token* → completed` をどの API で導出できるか。決定論
  （NFR-2）を満たせるか。
- **Findings**: pydantic-ai **v2.0.0b3**（本プロジェクトの宣言版、`pydantic-ai>=2.0.0b3`）
  は 3 つのストリーミング入口を持つ。最も写像が素直なのは **`agent.run_stream_events()`**
  （async context manager → `AgentStreamEvent` の async iterator、最後に
  `AgentRunResultEvent` で終端）。代替は `agent.run_stream(..., event_stream_handler=...)`
  と `agent.iter()`（ノード単位）。イベント型と SSE 契約の写像:
  - `PartStartEvent` / モデルリクエストノード開始 → **`step_started`**
  - `FunctionToolCallEvent`（`event.part.tool_name` / `args`） → **`tool_called`**
  - `PartDeltaEvent` の `TextPartDelta.content_delta`（増分テキスト） → **`token`**
  - `AgentRunResultEvent`（`event.result.output`） → **`completed`**
  - 実行中の例外 → **`error`**（R4.3）
  - `tool_called` / `token` は 0 回以上（R4.1）。routing（分類→専門応答、ツールなし）は
    2 つのモデルリクエストで `step_started` + `token*` を自然に産み、`tool_called` は 0 回
    （R4.1 が許容）。豊富なツールイベントが要るなら autonomous-agent を DI seam で差し替え。
  - **決定論**: 実モデルのトークンデルタは非決定的なので、**オフラインは pydantic-ai を
    一切使わず**、台本フェイク（固定チャンク列を yield する `EventSource` 実装）で
    `token` を供給する（NFR-2 / R5.3、ADR-2）。pydantic-ai の `run_stream_events` は
    **結合アダプタ**でのみ用い「実モデル × 実ストリーミング」を実証する。
- **Evidence**: context7 `/pydantic/pydantic-ai/v2.0.0b3` —
  `docs/agent.md`（`run_stream_events()` で `AgentStreamEvent`→`AgentRunResultEvent`、
  `PartStartEvent`/`PartDeltaEvent`/`TextPartDelta`/`FunctionToolCallEvent`/
  `FinalResultEvent` の一覧と出力例）。既存 `patterns/frameworks/pydantic-ai/src/
  patterns_pydantic_ai/routing.py`（`run_routing(*, model, instrumentation)` の DI seam
  と `instrument_model` 適用前例）。

### I-2. sse-starlette `EventSourceResponse` の現行 API と切断ハンドリング（R3.1 / R6）

- **Question**: `EventSourceResponse` は何を yield させるか。クライアント切断時に
  サーバ側ジェネレータをどう停止し、クリーンアップ（R6.1/6.3）をどう保証するか。
- **Findings**:
  - 入力は async ジェネレータで、各 yield は `{"event": <名>, "data": <文字列>}`
    形式の dict（または `ServerSentEvent`）。→ SSE 契約は `event:` 名 = `evt.type`
    判別子、`data:` = `evt.model_dump_json()` で導出（R2.3、ADR-3）。
  - 切断機構（`ARCHITECTURE.md`）: `EventSourceResponse.__call__` は
    `anyio.create_task_group()` 内で 4 タスクを `cancel_on_finish` で並走させる:
    `_stream_response`（本体）/ `_ping`（~15s keepalive）/ `_listen_for_exit_signal`
    （サーバ shutdown）/ `_listen_for_disconnect`（クライアント切断）。
    `_listen_for_disconnect` の `receive()` が **`http.disconnect`** を検知すると
    `active=False` で return → `cancel_on_finish` が `_stream_response` を **cancel** →
    本体ジェネレータに **`asyncio.CancelledError`** が送出され、task group が exit する。
  - したがってクリーンアップ規約は: 本体ジェネレータを `try: … except asyncio.
    CancelledError: <cleanup>; raise` + `finally: <release>` で囲み、加えて
    `await request.is_disconnected()` を yield ループ先頭でポーリングして能動 break する
    （Clarifications の採択どおり、R6.1/6.3）。`send_timeout` でハングする send を打ち切れる。
- **Evidence**: context7 `/sysid/sse-starlette` — `README.md`（`is_disconnected()` 監視 +
  `except asyncio.CancelledError: … raise` のクリーンアップ例、`send_timeout`）/
  `ARCHITECTURE.md`（task group + `cancel_on_finish` + `_listen_for_disconnect` が
  `http.disconnect` を検知して本体を cancel する Flow 2）。PyPI: **sse-starlette 3.4.4**
  （`requires_python >=3.10`、`starlette>=0.49.1` / `anyio>=4.7.0`）。

### I-3.【最重要】httpx `ASGITransport` の応答バッファリングと切断非伝播（R5 ⇄ R6.2）

- **Question**: `httpx.ASGITransport` でインプロセス起動したアプリに対し、クライアントの
  早期切断（`client.stream(...)` 早期 close）はサーバ側へ `http.disconnect` として
  伝播するか。ストリームは逐次配信されるか。
- **Findings**（一次ソース精読）: **No / No**。
  - `ASGITransport` は応答ボディを **完全バッファ**する（`body_parts.append(body)` で蓄積し、
    `b"".join(self._body)` を 1 チャンクとして emit）。逐次配信されない。
  - クライアントの早期 close で **`http.disconnect` を送出しない**。`http.disconnect` は
    **リクエスト完了後**に `receive()` が再呼出しされた時、`await response_complete.wait()`
    の後に返るのみで、クライアント側の中断には反応しない。
  - **帰結（R5 ハッピーパス）**: 本フィーチャの SSE ストリームは**有限**（必ず `completed`
    または `error` で終端、R4.4）なので、ASGITransport はジェネレータ完走後に全
    `text/event-stream` ボディを返す。テストはバッファ済み全文を**イベント列にパース**して
    順序・型・各 `data` の `model_validate`（R4.1/4.2/5.2）を検証できる。逐次配信タイミングは
    観測できないが、spec はそれを要求しない（決定論トークンは台本フェイクが供給、R5.3）。
  - **帰結（R6 切断）**: httpx クライアント側の早期 close では sse-starlette の
    `_listen_for_disconnect` が発火しない。**R6.2 を httpx の通常クライアント API では
    再現できない**。→ ADR-4 で別技法（ASGI scope への `http.disconnect` 直接注入）を採用。
- **Evidence**: GitHub raw `encode/httpx@master:httpx/_transports/asgi.py`（`receive`:
  `if request_complete: await response_complete.wait(); return {"type":
  "http.disconnect"}` / `body_parts.append(body)` の完全バッファ / `ASGIResponseStream`
  が `b"".join` で 1 チャンク emit）。PyPI: **httpx 0.28.1**（`requires_python >=3.8`）。

### I-4. 切断・キャンセルの hermetic 再現技法（R6.1 / R6.2 / R6.3）

- **Question**: I-3 を踏まえ、ネットワークゼロでクライアント切断 → ジェネレータ停止 →
  クリーンアップ実行をどう再現・検証するか。
- **Findings**: 2 層で担保する。
  1. **ASGI scope 直接駆動（R6.2 の主技法）**: 同一インプロセス ASGI アプリを
     `await app(scope, receive, send)` で駆動し、カスタム `receive()` が初回
     `{"type":"http.request", ...}` の後、所定の送出回数（K 件の `data:` を `send` が
     捕捉した）時点で **`{"type":"http.disconnect"}`** を返す。これが sse-starlette の
     `_listen_for_disconnect` を発火させ、本体ジェネレータが `CancelledError` を受けて
     停止し、`finally`/`except` のクリーンアップが走ることを検証する。ASGITransport は
     httpx の薄い ASGI ドライバに過ぎず、本技法も**実ソケットを開かず**同一アプリを
     インプロセス起動する点で R5.1/R6 の hermetic 意図（ネットワーク I/O ゼロ）を満たす。
     `http.disconnect` が存在する唯一の層（ASGI receive チャネル）を直接用いるのは、
     httpx ASGITransport が早期 close を意図的に切断として露出しないため（I-3、ADR-4）。
  2. **ジェネレータ単体（R6.1/6.3 の補完）**: 本体イベントジェネレータ（`EventSource` を
     駆動して SSE dict を yield する非同期ジェネレータ）を直接駆動し、数件 yield 後に
     `agen.aclose()`（→ `GeneratorExit`）またはラップ task の cancel を行い、リソース解放
     フラグ（`finally` で立てる sentinel）が真になることをアサート。例外を握り潰さない
     （R6.3）ことを別ケースで立証する。
- **Evidence**: I-2（sse-starlette task group の cancel 経路）/ I-3（ASGITransport では
  不可）/ ルート `tests/conftest.py`・`tests/unit/test_chat_endpoint_with_testmodel.py`
  の ASGITransport/TestClient 前例（ハッピーパスの型紙）。

### I-5. 単一点ドリフトテストの判別共用体対応（R2 / R2.4）

- **Question**: イベント判別共用体を `test_contract_drift.py` にどう乗せるか。既存契約を
  壊さないか。
- **Findings**（gap-analysis を一次コードで確認）: **加法のみで対応、無改修で判別共用体を
  サポート**。
  - `SseEvent = Annotated[Union[...], Field(discriminator="type")]` はモデルクラスでも
    `Literal` でもないため、パッケージ側 `_package_shape()` の `isinstance(member, type)`
    が False → `_value_literal()` None で **`ApprovalHook`（Callable 別名）と同じく
    スキップ**。README 側でも `_annotation_literal` が `Annotated` head を `Literal` と
    認識せず None → 両側で対称にスキップ。
  - 各イベントモデルの `type: Literal["step_started"]` 等の判別子は `_collect_model` が
    インライン `AnnAssign` の Literal として収集し、`field_literals` で README==パッケージの
    語彙一致を検証 → **`event:` 名の正本ドリフトを自動ロック**（R2.3 と整合）。
  - 必要作業: `patterns_contracts/sse.py` 追加 / `__init__.py` 再エクスポート追記 /
    `patterns/sse/README.md` 正本ブロック作成 / `_README_PATHS` に `"sse"` 1 行。
    one-README 不変条件（各モデルは 1 README のみ）を守るため 5 モデルは sse README のみに
    記載。R2.4（既存契約・ドリフトテスト非破壊）は構造的に満たされる。
- **Evidence**: `patterns/contracts/tests/unit/test_contract_drift.py`（`_README_PATHS` /
  `_collect_model` の AnnAssign Literal 収集 / `_value_literal` / one-README Counter）。
  `patterns/contracts/src/patterns_contracts/__init__.py`（flat 再エクスポート面）。

### I-6. 可観測性（R7）

- **Question**: 配信対象 routing に揃えた計装で span≥1 をオフラインで保証できるか。
- **Findings**: `observability.py`（`configure_tracing(exporter=None)`：注入 >
  `OTEL_EXPORTER_OTLP_ENDPOINT` > no-op）を pydantic-ai レーンから複製。**ただし**
  オフライン経路は pydantic-ai を使わず台本フェイク駆動なので `gen_ai.*` ネイティブ span は
  出ない。→ エンドポイントが**リクエストごとに 1 つのアプリ span（例 `sse.stream`）**を
  `TracerProvider` から開き、その中でイベント生成を回す。`InMemorySpanExporter` 注入時に
  span≥1（末端 span の**存在**のみ、R7.3）を検証する。結合では pydantic-ai
  `InstrumentationSettings` を併用し `gen_ai.*` も流れる。
- **Evidence**: `patterns/frameworks/pydantic-ai/src/patterns_pydantic_ai/observability.py`
  （`configure_tracing` の exporter 優先チェーン）/ `routing.py`（`instrument_model`）。

### I-7. Python バージョン選択（gap-analysis 論点 5）

- **Question**: SSE レーンは 3.13 か 3.14 か。
- **Findings**: RAG の 3.13 ピンは docling/llamaindex の 3.14 wheel ギャップ回避が理由で、
  **SSE 依存（fastapi 0.136.x / sse-starlette 3.4.4 / httpx 0.28.1）には該当しない**
  （いずれも `requires_python` は 3.10 以下フロアで 3.14 を含む）。結合アダプタが駆動する
  pydantic-ai V2 は **3.14 の pydantic-ai レーン**に在る。→ **SSE レーンは Python 3.14**
  を採用（`.python-version=3.14`、`requires-python>=3.14`、ruff `target-version=py314`、
  pyright `pythonVersion=3.14`）。これはルート `mise.toml` の `python=3.14` とも整合。
- **Evidence**: PyPI（fastapi/sse-starlette/httpx の requires_python）/
  `patterns/frameworks/pydantic-ai/.python-version`（3.14）/ ルート `mise.toml`（3.14）。

### I-8. 配線（mise / CI / SECURITY-NOTES / README）— RAG 前例の機械的踏襲（R8/R9/R10/R11）

- **Question**: `frameworks/` 外の独立レーンをどう配線するか。
- **Findings**: RAG レーンが唯一かつ完全な前例。
  - `mise.toml`: `patterns:{setup,lint,format,typecheck,test,audit}` のレーンループ後・
    `(cd patterns/rag && …)` 行の後に `(cd patterns/sse && …)` を 1 行追記。
    `patterns:test:integration` にも `(cd patterns/sse && RUN_INTEGRATION_PATTERNS=1 …)`
    を追記。ルート `check`/`cov`/`test` は `extend-exclude=["patterns"]` 等で patterns/ を
    既に除外済 → **ルート無変更**（R11.2/R10.3 が構造的に成立）。
  - `patterns-ci.yml`: `rag` ジョブと同型の **専用 `sse` ジョブ**（matrix エントリにしない）
    + `paths` に `patterns/sse/**` 追記（push/pull_request 双方）。`uv sync --all-groups
    --locked → ruff/pyright/pytest --cov/pip-audit`。
  - `patterns-integration-ollama.yml`: `pull_request.paths` に `patterns/sse/**` 追記
    （push は `patterns/**` で既被覆）。SSE 結合は既存 daemon に相乗り。生成 LLM env
    （`OLLAMA_*`）は既設で流用可。
  - `SECURITY-NOTES.md`: `### RAG 応用レイヤ → OWASP` 節と同型の **SSE 節**を追加。
  - `patterns/README.md`: `## 応用レイヤー（RAG）` 節に **SSE 行を追加**（応用レイヤとして
    索引、ワークフロー 6 表とは別軸。SSE は配信インフラの応用である旨を明記、R9.2）。
- **Evidence**: `mise.toml`（rag 明示行 + レーンループ）/ `patterns-ci.yml`（`rag` 専用
  ジョブ L153-192）/ `patterns-integration-ollama.yml`（`patterns/rag/**` paths L41）/
  `patterns/SECURITY-NOTES.md`（RAG→OWASP 節 L53-70）/ `patterns/README.md`（応用レイヤ
  索引 L29-44）。

## Existing patterns to reuse

| Pattern | Location | Why reuse |
|---|---|---|
| 独立 uv レーン雛形 | `patterns/rag/{pyproject.toml,.python-version,README.md}` | depth 1 兄弟レーンの完全な型紙。docling 依存を fastapi/sse-starlette へ差替え、Python は 3.14 に戻す（I-7） |
| 契約パス依存 import | `[tool.uv.sources] patterns-contracts = { path="../contracts", editable=true }` | NFR-3。`patterns/sse/` は RAG と同じ depth1 で相対は `../contracts` |
| `configure_tracing` | `patterns/frameworks/pydantic-ai/.../observability.py` | exporter 優先チェーン（注入>env>no-op）。複製で対応（レーン自前コピーが既存規律） |
| DI seam 前例 | `patterns/frameworks/pydantic-ai/.../routing.py`（`run_routing(*, model, instrumentation)`） | 注入で受ける seam の型。SSE は `EventSource` Protocol を注入で受ける（二層 seam: イベントソース + モデル） |
| 契約モジュール型 | `patterns/contracts/src/patterns_contracts/routing.py`（`Literal` 判別子）+ `__init__.py` 再エクスポート | `type: Literal[...]` 判別子付きモデル + 判別共用体別名の型紙 |
| 単一点ドリフト | `patterns/contracts/tests/unit/test_contract_drift.py` | `_README_PATHS` に `"sse"` 1 行追加で被覆（I-5、無改修） |
| 契約 unit テスト | `patterns/contracts/tests/unit/test_rag_contracts.py` | `test_sse_contracts.py`（判別共用体ラウンドトリップ）の型紙 |
| ASGITransport ハッピーパス | ルート `tests/conftest.py` / `tests/unit/test_chat_endpoint_with_testmodel.py` | インプロセス起動の前例（R5.1）。SSE は全文バッファをパースして検証（I-3） |
| 結合ゲート | `patterns/rag/tests/integration/test_ollama_e2e.py`（`RUN_INTEGRATION_PATTERNS` + `OLLAMA_*`） | 契約レベルアサート・env 読取りの型紙 |
| mise/CI 明示配線 | `mise.toml`（rag 行）/ `patterns-ci.yml`（`rag` ジョブ）/ integration paths | `frameworks/` 外レーン配線の前例（最小ドリフト） |
| パターン README 正本 | `patterns/rag/README.md` / `patterns/routing/README.md` | `## パターン契約` ```` ```python ```` 注釈のみブロック + 必須 4 セクション規約 |

## External dependencies

| Dependency | Version（方針） | Purpose | Verified |
|---|---|---|---|
| `patterns-contracts` | path（`../contracts`, editable） | イベント判別共用体の単一実体を import（NFR-3/5） | ✅ 既存規律 |
| `fastapi` | `>=0.136`（uv.lock でピン、実 PoC） | エンドポイント・DI・ルーティング | ✅ PyPI 0.136.3 / py>=3.10 |
| `sse-starlette` | `>=3.4`（uv.lock でピン） | `EventSourceResponse`・切断時 task-group cancel | ✅ PyPI 3.4.4 / starlette>=0.49.1 / anyio>=4.7 |
| `pydantic` | `>=2` | イベントモデル基底・`model_dump_json` | ✅ 既存規律 |
| `opentelemetry-sdk` / `-exporter-otlp-proto-http` | レーン同等 | `configure_tracing`（span≥1） | ✅ 複製 |
| `httpx`（dev） | `>=0.28` | `ASGITransport` ハッピーパス検証 | ✅ PyPI 0.28.1。**バッファ/切断非伝播は把握済**（I-3） |
| `pydantic-ai`（dev / 結合専用） | `>=2.0.0b3`（+ openai provider extra） | 結合アダプタ（`run_stream_events` → 実 Ollama） | ⚠️ 結合のみ。src は非依存（NFR-3）。openai provider extra は PoC でピン |

dev: `pip-audit` / `pyright` / `pytest` / `pytest-asyncio` / `pytest-cov` / `ruff`
（RAG レーンと同一）。各 runtime 依存は pyproject に 1 行 rationale（Constitution III）。
**src の runtime 依存は fastapi / sse-starlette / pydantic / otel / patterns-contracts のみ**。
pydantic-ai と httpx は**テスト専用**（src は framework-agnostic、ADR-2）。

## Architecture decisions

### ADR-1: 配置は独立レーン `patterns/sse/`（Python 3.14）

- **Context**: SSE は Anthropic ワークフロー 6 パターンではなく**配信インフラの応用レイヤ**
  （RAG に続く 2 つ目）。RAG 先例で「共有契約を再利用しつつ新しい兄弟レーンを足す」Hybrid が
  確立済み。SSE 依存は軽量（fastapi/sse-starlette/httpx）で 3.14 wheel ギャップ無し（I-7）。
- **Decision**: `patterns/sse/`（`frameworks/` 外、depth 1）に独立 uv プロジェクトを新設。
  パッケージ名 `patterns_sse`。**Python 3.14**（`.python-version`/`requires-python`/ruff/
  pyright を 3.14 に統一、I-7）。最終確定は impl 冒頭 Spike（uv.lock 差分・CI 時間実測）。
- **Alternatives**: (B) ルートアプリ拡張 = R1.4/R10.3（ルート無変更）と矛盾、Clarifications で
  却下済。(C) `frameworks/` 配下同居 = タクソノミー不整合（応用レイヤ ≠ フレームワーク役割
  分担）。却下。
- **Consequences**: mise/CI を RAG 前例で明示配線（I-8）。observability 複製 1 ファイル。
  ルートは patterns/ 除外済で無変更（R11.2/R10.3）。

### ADR-2: イベント導出は Hybrid（fw 非依存 `EventSource` Protocol + 注入）

- **Context**: gap-analysis のオープン軸。NFR-3（src がレーン/フレームワークに非結合）・
  NFR-2（決定論）・R6（切断制御の容易さ）・R3.3（実モデル DI seam）を同時に満たす必要。
  R1.3 は SSE レーン src からの `patterns_pydantic_ai` import を禁ずる。
- **Decision**: **Option C（Hybrid）**。SSE レーン src は **framework-agnostic** に保つ。
  - src に `EventSource` Protocol（`async def stream(query) -> AsyncIterator[SseEvent]`）を
    定義し、エンドポイントは**注入で受ける**（DI seam）。
  - **オフライン** = 台本 `ScriptedEventSource`（固定 `SseEvent` 列、`token` は固定チャンク列）。
    pydantic-ai を一切使わず完全決定論（NFR-2 / R5.3）・切断を任意点で制御可能（R6）。
  - **結合** = pydantic-ai `run_stream_events` アダプタ（`tests/integration/`）が routing 型の
    Agent を `pydantic_ai`（フレームワーク）+ Ollama-backed モデルで構築し、`AgentStreamEvent`
    → `SseEvent` に写像（I-1）。**pydantic-ai は dev/結合専用依存**であり、`patterns_pydantic_ai`
    レーンは import しない（NFR-3 不変条件を src/依存の両面で守る）。
  - モデル seam（R3.3）は結合アダプタ内（フェイク=台本 / 結合=Ollama）。
- **Alternatives**: (A) src が pydantic-ai ネイティブストリーミングに直結 = NFR-3 違反・
  フェイクのストリーム決定論に依存。(B) 完全自作ドライバのみ = 「実 routing 実行の実体感」が
  薄く結合実証が無い。却下。
- **Consequences**: 二実装（台本 / pydantic-ai アダプタ）の保守。`EventSource` Protocol 形状を
  契約化することで両者を一点に収束。`SseEvent` 契約は fw 非依存（pydantic のみ）。

### ADR-3: SSE 直列化は `event:` = `type` 判別子、`data:` = `model_dump_json()`

- **Context**: R2.3（`event:` を `type` から導出、`data:` を JSON 直列化）。判別共用体
  （Clarifications 採択）と JSON シリアライズ・pyright strict の両立。
- **Decision**: `events.py` の単一ヘルパが `SseEvent` を `{"event": evt.type, "data":
  evt.model_dump_json()}` に写し、`EventSourceResponse` に渡す。受信側は `event:` で
  分岐せず `data:` JSON を `TypeAdapter(SseEvent).validate_json` で判別子により逆写像
  （R4.2 の `model_validate` 検証）。
- **Alternatives**: 手書き `f"event: …\ndata: …"` = 改行/SSE 仕様の取りこぼしリスク。却下。
- **Consequences**: 判別子の値は契約 `Literal` でロックされ、`event:` 名の正本は
  ドリフトテストが守る（I-5）。

### ADR-4: 切断検証は ASGI scope への `http.disconnect` 直接注入（httpx 早期 close は不可）

- **Context**: I-3 で httpx `ASGITransport` が応答を**完全バッファ**し、クライアント早期
  close を **`http.disconnect` として伝播しない**ことを一次ソースで確認。R6.2 の「切断・
  キャンセル再現」を httpx 通常 API では実現できない。
- **Decision**:
  - **R5（ハッピーパス）**: ASGITransport を用い、有限ストリーム完走後のバッファ済み
    `text/event-stream` 全文をイベント列にパースして順序・型・`model_validate` を検証。
  - **R6（切断）**: 同一インプロセス ASGI アプリを `app(scope, receive, send)` で直接駆動し、
    カスタム `receive()` が K 件 send 後に `{"type":"http.disconnect"}` を返す。sse-starlette
    の `_listen_for_disconnect` → 本体 cancel → `CancelledError` → クリーンアップ実行を検証
    （I-2/I-4）。補完として `agen.aclose()`（`GeneratorExit`）でのリソース解放も unit で立証。
  - この技法も実ソケットを開かずネットワーク I/O ゼロで、R5.1/R6 の hermetic 意図を満たす。
- **Alternatives**: httpx `client.stream()` 早期 break = I-3 より無効（切断が伝播しない）。
  実 uvicorn 起動 + 実ソケット = ネットワーク依存で hermetic 違反。却下。
- **Consequences**: テストヘルパ（ASGI scope ドライバ + disconnect 注入）を `tests/support/`
  に 1 つ用意。R6.2 の「ASGITransport 上で」の文言は、同一 ASGI アプリのインプロセス駆動
  という意図で満たす（`http.disconnect` が存在する ASGI receive 層を直接用いる旨を README/
  テスト docstring に明記）。impl 冒頭 Spike で ASGITransport の挙動（バージョン差）を
  最終確認し、本 ADR を確定する。

### ADR-5: 可観測性はアプリ span を 1 つ開く（オフラインは pydantic-ai 非経由）

- **Context**: R7.2（リクエスト→実行で span≥1）。オフラインは台本フェイク駆動で `gen_ai.*`
  ネイティブ span が出ない（ADR-2）。
- **Decision**: エンドポイントが `configure_tracing` の `TracerProvider` からリクエスト
  ごとに 1 span（例 `sse.stream`）を開きイベント生成を内包。`InMemorySpanExporter` 注入で
  span≥1 と末端 span の**存在**のみ検証（R7.3、属性集計はしない）。結合では pydantic-ai
  `InstrumentationSettings` も併用。
- **Alternatives**: 計装をフレームワーク任せ = オフラインで span 0 になり R7.2 不成立。却下。
- **Consequences**: `observability.py` 複製 + エンドポイントの span ラップ 1 箇所。

## Risks & open questions

- ⚠️ **R-1 ASGITransport の切断挙動はバージョン依存**（R6.2）— I-3 は `encode/httpx@master`
  の精読。0.28.x も同様（バッファ + 早期 close 非伝播）と判断するが、**impl 冒頭 Spike
  （Task 0）で実装版 httpx に対し** (a) 有限ストリームのバッファ全文取得（R5）と
  (b) ASGI scope 直接駆動での `http.disconnect` 注入 → cancel 到達（R6）を実測確認する。
  万一 ASGITransport が将来逐次配信/切断伝播へ変わっても、ADR-4 の scope 直接駆動は
  上位互換（より低層で安定）。
  - **Spike 実測（Task 0.2, 2026-06-14 / 確定）**: 実装版 httpx 0.28.1 / sse-starlette
    3.4.4 / fastapi 0.136.3 / Python 3.14.5 に対し `patterns/sse/test_spike_asgi.py`
    （2 ケース）が両方 **PASS**。
    - (a) **有限ストリーム全文バッファ取得 = 確認**: `EventSourceResponse` の有限ストリーム
      （`token×3 → completed`）を `ASGITransport` 経由で取得すると、終端 `completed` を含む
      全文が 1 ボディとして返り、`event:`/`data:` 列にパースできた（逐次配信なしで R5 を満たす）。
    - (b) **scope 直接駆動 `http.disconnect` → cancel 到達 = 確認**: 同一 ASGI アプリを
      `app(scope, receive, send)` で駆動し、K=3 件の `data:` フレーム送出後にカスタム
      `receive()` が `{"type":"http.disconnect"}` を注入したところ、sse-starlette が本体
      ジェネレータを cancel し、`except asyncio.CancelledError`（再 raise）+ `finally` の
      解放 sentinel が実行され、ジェネレータは安全上限（1000）より前で早期停止した。
    - **判断**: **ADR-4 を確定**。httpx 通常クライアントの早期 close が切断を伝播しない件
      （I-3）は、本技法が `http.disconnect` の唯一の存在層（ASGI receive）を直接用いる
      *理由*そのものであり、構造的に成立（scope 直接駆動が上位互換）。R-1 クローズ。
- ⚠️ **R-2 sse-starlette の有限ストリームと ASGITransport バッファの相互作用**（R5）—
  本体ジェネレータが `completed`/`error` で必ず return することに依存（無限ストリームは
  ASGITransport でハングする）。mitigation: 終端マーカー（R4.4）を契約・テストで強制し、
  `send_timeout` を設定。台本/アダプタ双方に最大イベント数のガードを置く。
- ⚠️ **R-3 結合アダプタの pydantic-ai 依存重量と provider extra**（R3.3 / 結合のみ）—
  Ollama 駆動に必要な provider（`OpenAIChatModel + OllamaProvider`）の extra を dev グループに
  限定し src 閉包を汚さない。uv.lock 差分は Task 0 Spike で実測。`patterns_pydantic_ai` を
  import しない（NFR-3）。
  - **Spike 実測（Task 0.1, 2026-06-14 / 確定）**: throwaway PoC（`patterns/sse/`,
    `package=false`, Python 3.14.5）で `fastapi>=0.136 sse-starlette>=3.4` +
    dev `httpx>=0.28 pydantic-ai-slim[openai]>=2.0.0b6 pytest pytest-asyncio` を解決。
    - **依存重量 = 軽量・問題なし**: all-groups `uv.lock` = **42 パッケージ / 73.3 KiB**、
      `.venv` 実体 40 dist-info。**runtime-only 閉包（fastapi + sse-starlette）= 11 パッケージ**
      で ML wheel ゼロ。provider extra（dev: pydantic-ai-slim[openai]）が足す ~30 パッケージの
      最大は openai 8.4 MiB / pydantic_ai 3.9 MiB / tiktoken 2.6 MiB。**torch/onnxruntime/
      numpy/transformers いずれも無し**（RAG レーンの docling/ML 重量とは対照的に pure-Python）。
    - **同期時間 = CI 影響軽微**: cold `uv sync --all-groups`（uv グローバルキャッシュ温）
      = 0.79s、warm `uv sync --all-groups --locked` = 0.01–0.02s（×3 計測）。
    - **副次の確定事項（Task 1 への申し送り）**: pydantic-ai V2 beta（`pydantic-graph` の
      pre-release ピン）解決のため `[tool.uv] prerelease = "allow"` が必須だが、これが
      **runtime 閉包にも波及**し pydantic 2.14.0a1（alpha）/ starlette 1.3.1 を引く。Task 1 の
      本番レーンでは prerelease 許可を pydantic-graph/pydantic-ai 系へ限定（per-package）するか
      pydantic を stable に上限ピンし、fw 非依存 src 閉包が alpha pydantic に乗らないようにする。
    - **判断**: provider extra 重量は許容範囲（NFR-3 の「src は非依存・dev/結合のみ」で隔離
      可能）。**R-3 クローズ**、prerelease スコープのみ Task 1.1 で対応。
- ⚠️ **R-4 カバレッジフロア**（R5.4 / NFR-4）— 新規レーンは切断/エラー分岐が多い。
  mitigation: 兄弟レーン parity（98）を目標、被覆困難なグルー（OTLP 遅延 import 等）が残れば
  005/006 エントリフロア 85 から ratchet で着地し rationale を spec/commit に明示。RAG が
  98 を達成した先例あり。
- ❓ **Q-1 `ToolCalledEvent.args` の表現** — 機微情報非掲載（R8.3）と pyright strict の両立。
  初期案: `tool: str` + `args_json: str`（サニタイズ済み JSON 文字列、生プロンプト全文や認証
  情報を載せない）。最終形は impl 契約タスクで確定。
- ❓ **Q-2 既定の配信対象とエンドポイント形状** — `POST /sse/runs`（body: `{query}`）→
  `EventSourceResponse`。既定 routing、autonomous-agent は DI seam の任意拡張（spec R3.2）。
  パス/メソッドは impl の app タスクで確定。

---

_Discovery & research generated (/sdd-plan): 2026-06-14_
