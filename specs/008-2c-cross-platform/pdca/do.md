# 008-2c-cross-platform — PDCA Do Phase

`/sdd-impl` 実装ログ。タスク進捗・根本原因分析・学びを継続追記する。

---

## Task 0 — Spike: 配置確定 PoC（ブロッキング gate） ✅

実施日: 2026-06-14 / 状態: **完了（gate green）→ Wave 1 着手可**

スパイクの性質上、「実験スクリプト = テスト」。ADR-4 が予言する挙動をアサートとして
encode し、実装版ライブラリに対し green になることをもって仮説確定とした（Red→Green の
Red は「未確定の ADR」状態、Green は実測 PASS）。

### Do（実施内容）

- **0.1 PoC 雛形 + 依存実測**: `patterns/sse/{.python-version=3.14, pyproject.toml
  (package=false, throwaway)}` を作成。runtime `fastapi>=0.136 sse-starlette>=3.4` +
  dev `httpx>=0.28 pydantic-ai-slim[openai]>=2.0.0b6 pytest pytest-asyncio` を `uv sync
  --all-groups` で解決し lock 生成。
- **0.2 ASGITransport スパイク**: `patterns/sse/test_spike_asgi.py`（2 ケース）を作成・実行。
  - (a) 有限 `EventSourceResponse`（`token×3 → completed`）を `httpx.ASGITransport` で取得 →
    終端含む全文を 1 ボディでバッファ取得（R5）。
  - (b) `app(scope, receive, send)` 直接駆動 + K=3 フレーム後の `http.disconnect` 注入 →
    本体ジェネレータが `CancelledError` を受け `except`(再 raise)+`finally` 解放が走り
    早期停止（R6）。
- research.md Risk R-1 / R-3 のスパイクブロックへ実測値と判断（ADR-4 / R-3 クローズ）を追記。

### 実測値

| 指標 | 値 |
|------|-----|
| all-groups `uv.lock` | 42 パッケージ / 73.3 KiB（`.venv` 40 dist-info） |
| runtime-only 閉包（fastapi+sse-starlette） | 11 パッケージ、ML wheel ゼロ |
| provider extra 最大物 | openai 8.4 / pydantic_ai 3.9 / tiktoken 2.6 MiB |
| heavyweight ML（torch/onnxruntime/numpy/transformers） | **無し**（pure-Python） |
| cold `uv sync --all-groups`（uv cache 温） | 0.79s |
| warm `uv sync --all-groups --locked`（×3） | 0.01–0.02s |

### エラーと根本原因（blind retry 禁止に従い記録）

- **症状**: 初回 `uv sync` が `pydantic-graph==2.0.0b6` の pre-release 解決不能で失敗。
- **根本原因**: pydantic-ai V2 は beta で `pydantic-graph` を pre-release ピンするが、uv は
  既定で pre-release を採らない。
- **修正**: pydantic-ai レーン前例（`[tool.uv] prerelease = "allow"`）を踏襲。症状ではなく
  原因（pre-release 不許可）を解消。

### 学び（Act へ）

1. **ADR-4 は実測で確定**。scope 直接駆動が切断検証の唯一確実な技法（httpx 通常 API は
   早期 close を伝播しない）。Task 4/7 はこの技法を `tests/support/asgi_driver.py` に正式化。
2. **provider extra は軽量**で NFR-3 の dev/結合隔離で十分。RAG レーンのような ML 重量懸念は
   本レーンに非該当。
3. **Task 1 申し送り（要対応）**: `prerelease = "allow"` が runtime 閉包に波及し pydantic
   2.14.0a1(alpha)/starlette 1.3.1 を引く。本番レーンでは prerelease 許可を
   pydantic-graph/pydantic-ai へ per-package 限定するか pydantic を stable に上限ピンし、
   fw 非依存 src 閉包が alpha に乗らないようにする。

### 検証ゲート（証跡）

```
$ uv run pytest test_spike_asgi.py -v
platform darwin -- Python 3.14.5, pytest-9.1.0
configfile: pyproject.toml   asyncio: mode=Mode.AUTO
collected 2 items
test_spike_asgi.py::test_asgitransport_buffers_finite_stream PASSED      [ 50%]
test_spike_asgi.py::test_scope_drive_disconnect_reaches_cleanup PASSED   [100%]
============================== 2 passed in 0.17s ===============================
```

> レーンはまだ mise/CI に未配線（Task 12）。本 gate の検証コマンドはスパイク実験自身。
> `patterns/sse/` の throwaway 成果物（`pyproject.toml`/`uv.lock`/`test_spike_asgi.py`）は
> Task 1 で本番レーンへ置換される。

---

## Task 1 — (P) SSE レーンの新設と契約パス配線 ✅

実施日: 2026-06-14 / 状態: **完了（1.1 / 1.2 green）→ Wave 2（Task 3）着手可**

TDD: スモークテスト先行（Red）→ レーン scaffold（Green）。

### Do（実施内容）

- **PoC 全置換**: Task 0 throwaway を撤去（`test_spike_asgi.py` は `git rm`、spike
  `pyproject.toml`/`uv.lock`/`.venv` は本番構成へ置換）。証跡は本 do.md の Task 0 節に保全済み。
- **1.2 Red 先行**: `tests/unit/test_smoke.py`（import 健全性 + 兄弟レーン非 import〔NFR-3〕）を
  作成し `uv run --no-sync pytest` で `ModuleNotFoundError: No module named 'patterns_sse'`
  を確認（2 FAILED）。hermetic ガード/fake one-pass は Task 9 へ委譲し、Task 1 は構造のみ担保。
- **1.1 Green**: 本番 `pyproject.toml` を作成（runtime: `patterns-contracts`(path dep) /
  fastapi>=0.136 / sse-starlette>=3.4 / `pydantic>=2,<2.14` / otel sdk+otlp-http、dev: httpx /
  `pydantic-ai-slim[openai]>=2.0.0b6` / pytest 群 / pyright / ruff / pip-audit、ruff・pyright
  strict `py314`・coverage `fail_under=85` 初期フロア）。`.python-version=3.14` は維持。
- **1.2 Green**: `src/patterns_sse/__init__.py`（import 専用、公開面は Task 4.3）を作成し
  `uv sync --all-groups` で `uv.lock` 生成。スモーク 2 件 green。

### エラーと根本原因（blind retry 禁止に従い記録）

- **症状**: 初回 lock で runtime `pydantic` が `2.14.0a1`(alpha) に解決（Task 0 申し送りの再現）。
- **根本原因**: dev の pydantic-ai 解決に必須な `[tool.uv] prerelease = "allow"` が無制約だと
  共有 pydantic を alpha へ巻き込み、fw 非依存 src 閉包が alpha に乗る。
- **修正**: runtime dep に `pydantic>=2,<2.14` の stable 上限ピンを追加（症状＝alpha 採択では
  なく原因＝無制約 prerelease を解消）。lock 上で `pydantic==2.13.4 / pydantic-core==2.46.4`
  (stable) に確定。prerelease は pydantic-graph(`2.0.0b7`) 自身の dev 閉包へ封じ込め。
- **派生対応**: `[project].readme` は未宣言（README は Task 11。欠損ファイル参照で hatchling
  build が壊れるため）。

### 学び（Act へ）

1. **prerelease は「全許可 + stable 上限ピン」で封じ込め可能**。per-package prerelease を
   uv config で直接表現するより、runtime dep の version specifier で stable 上限を切る方が
   宣言的で堅い（pydantic-ai レーンは runtime に pydantic-ai を持つため全許可で正しい＝差分理由）。
2. **scaffold の Red は「未生成パッケージの import 失敗」で十分担保**。意味的アサート
   （兄弟レーン非 import）は Green 後も load-bearing として残す。

### 検証ゲート（証跡）

```
$ uv run ruff check .         → All checks passed!
$ uv run ruff format --check . → 2 files already formatted
$ uv run pyright              → 0 errors, 0 warnings, 0 informations
$ uv run pytest --cov         → 2 passed; src/patterns_sse/__init__.py 100%;
                                 Required coverage 85.0% reached (total 100.00%)
$ uv sync --all-groups --locked → Resolved 76 / Checked 75（--locked グリーン、NFR-1）
```

解決バージョン: fastapi 0.136.3 / sse-starlette 3.4.4 / starlette 1.3.1(fastapi 要求 stable) /
pydantic 2.13.4 / pydantic-ai-slim 2.0.0b7(dev のみ)。

> レーンの mise/CI 配線は Task 12。本 gate はレーンローカル `uv run`（patterns:* 配線前の
> 正規検証）で実施。

---

## Task 2 — (P) shared-contracts への SSE 判別共用体追加 ✅

実施日: 2026-06-14 / 状態: **完了（2.1 / 2.2 green）→ Wave 2（Task 3 events.py）着手可**

TDD: 契約テスト先行（Red）→ `sse.py` + `__init__` 再エクスポート（Green）。

### Do（実施内容）

- **2.1 Red 先行**: `patterns/contracts/tests/unit/test_sse_contracts.py`（7 ケース: 再エクスポート /
  各モデルのフィールド集合〔R8.3 最小設計〕/ 判別子 tag 固定 / 判別共用体ディスパッチ /
  `model_dump_json` ラウンドトリップ / 未知 tag 棄却 / 判別子欠落棄却）を作成し、
  `ImportError: cannot import name 'CompletedEvent'` を確認（collection error = Red）。
- **2.1 Green**: `src/patterns_contracts/sse.py` に 5 モデル + `SseEvent` を定義。各 `type` は
  既定値付き `Literal`、`args_json` / `message` は機微情報非掲載のサニタイズ済 `str`（R8.3、
  サニタイズは producer 責務でフィールド制約にはしない）。`SseEvent = Annotated[A | B | ...,
  Field(discriminator="type")]`。
- **2.2 Green**: `__init__.py` に 5 モデル + `SseEvent` の import と `__all__` 追記（アルファベット
  順、既存スタイル踏襲）。新テスト 7 件 green。

### エラーと根本原因（blind retry 禁止に従い記録）

- **症状**: `__all__` への 5 モデル追記後、`test_contract_drift.py` の 4 ケースが赤
  （class set / field sets / literal vocab / one-README）。
- **根本原因（defect ではない）**: drift テストは `patterns_contracts.__all__` の全 BaseModel が
  いずれかの登録済 README 正本ブロックに記載されることを要求する。SSE README
  （`patterns/sse/README.md`）作成と `_README_PATHS["sse"]` 登録は **Task 11**（Task 4 依存の
  ため現時点着手不可）。差分は新規 5 モデルのみで既存7パターンは両側不変（回帰なし）。
- **対応**: ユーザ判断で **Task 2 境界を厳守**（README/登録へ越境しない）。当該赤は I-5 +
  wave 計画が予定した中間状態として保全し、Task 11 で構造的に解消（R2.4 充足）。symptom
  （drift 赤）を README スタブで糊塗せず、原因（Task 11 未了）を明示記録。

### 学び（Act へ）

1. **加法的契約追加の固有テンション**: 共有契約パッケージへモデルを足すと、README 登録
   （別タスク・別境界）が完了するまで単一点 drift テストが赤になる。wave 計画はこれを織り込み
   済みだが、`/sdd-impl` の per-task 検証ゲートとは緊張する。per-task 完了判定は「当該タスク
   自身の deliverable が green」で行い、下流結合由来の赤は根本原因 + 解消タスクを明示する。
2. **判別共用体は drift パーサ無改修で対称スキップ**（I-5 実測整合）。`Annotated[Union, Field]`
   は両側で `Literal`/モデルクラス判定に掛からずスキップ、判別子 `type` のみ `field_literals`
   で `event:` 名語彙としてロックされる。

### 検証ゲート（証跡）

```
# 2.1 Red（実装前）
$ uv run --no-sync pytest tests/unit/test_sse_contracts.py --no-cov
E  ImportError: cannot import name 'CompletedEvent' from 'patterns_contracts'
   1 error in 0.12s

# 2.1/2.2 Green（実装後）
$ uv run --no-sync pytest tests/unit/test_sse_contracts.py --no-cov   → 7 passed in 0.07s
$ uv run --no-sync ruff check .          → All checks passed!
$ uv run --no-sync ruff format --check . → 12 files already formatted
$ uv run --no-sync pyright               → 0 errors, 0 warnings, 0 informations
$ uv run --no-sync pytest tests/unit/test_sse_contracts.py --cov=patterns_contracts.sse
   src/patterns_contracts/sse.py  22  0  0  0  100%   → 7 passed

# 既知の中間状態（Task 11 で解消）
$ uv run --no-sync pytest --no-cov
   4 failed, 15 passed   # test_contract_drift の 4 件のみ。差分 = 新規 5 SSE モデル
                         # （既存7パターンは README==パッケージ両側で不変、回帰なし）
```

> 完全な `mise run patterns:test`（lane coverage）green 化は Task 11（SSE README 作成 +
> `_README_PATHS` 登録）完了時。Task 2 の deliverable 自体は上記の通り green。

---

## Task 3 — SSE 直列化ヘルパと EventSource seam ✅

`patterns/sse/src/patterns_sse/events.py` を新設（3.1）。`/sdd-impl` の TDD
（Red→Green→Refactor）で進行。

### Do（実施内容）

- **Red 先行**: `tests/unit/test_event_serialization.py` を先に作成し
  `ModuleNotFoundError: No module named 'patterns_sse.events'` で赤を確認。7 ケース:
  `to_sse` の `event:`=判別子 / `data:`=`model_dump_json()` / キー集合、
  `parse_sse_events` の判別子ディスパッチ・非 `data:` 行（keepalive `:` / `event:`）無視・
  ラウンドトリップ、`EventSource` Protocol の async-generator 構造適合。
- **Green 最小実装**: ADR-3 を 1 モジュールへ集約。`to_sse(event) -> {"event":
  event.type, "data": event.model_dump_json()}`、`parse_sse_events(body) ->
  list[SseEvent]`（`data:` 行のみ抽出 → `TypeAdapter(SseEvent).validate_json` で逆写像、
  R4.2）。`TypeAdapter` は import 時 1 回構築し module 定数で共有。`EventSource` は
  `@runtime_checkable` Protocol、メンバは非 `async def`（async-generator 実装の構造適合のため）。
- **Refactor**: docstring/Google 規約・`__all__` 整備。lint 指摘 2 件を是正
  （下記 根本原因）。

### エラーと根本原因（blind retry 禁止に従い記録）

- **D301（docstring 内バックスラッシュ）**: 「`event: …\ndata: …` を手書きしない」を
  例示するため docstring に `\n` リテラルを書いたところ ruff D301 が発火。
  **根本原因**: `r"""` でない docstring に `\` を含めた。**対応**: `r"""` 付与ではなく
  散文（"newline-delimited `event:` / `data:`"）へ言い換え、意図（手書き整形回避＝ADR-3）を
  保ったまま `\` を除去。
- **I001（import 未ソート）**: `pydantic` を `patterns_contracts` より前に置いた。
  **根本原因**: `patterns_contracts` は path-dep だが third-party 扱いで、`p-a-t` <
  `p-y-d` のため `patterns_contracts` が先。isort `known-first-party=["patterns_sse"]` の
  自レーンのみが first-party。**対応**: third-party 内で正順へ並べ替え。

### 学び（Act へ）

1. **Protocol で async-generator を型付けるときは非 `async def` で宣言する**。
   `async def stream(...) -> AsyncIterator[...]: ...` と書くと「`AsyncIterator` を返す
   coroutine」型になり、`async def`+`yield` の実装が構造的に非適合になる（pyright strict）。
   返り値注釈は `AsyncIterator[SseEvent]` のまま、宣言を `def` にするのが正。
2. **ADR-3 の逆写像は `event:` 非依存**。受信は `data:` JSON を `TypeAdapter` で判別子
   ディスパッチするのが正本で、`event:` は人間可読の冗長情報。パーサを `data:` 限定に
   することで keepalive コメント・framing 行に頑健（SSE 仕様準拠）。

### 検証ゲート（証跡）

```
# 3.1 Red（実装前）
$ uv run pytest --no-cov tests/unit/test_event_serialization.py -q
E  ModuleNotFoundError: No module named 'patterns_sse.events'
   1 error in 0.64s

# 3.1 Green（実装後）→ ヘルパ単体
$ uv run pytest --no-cov tests/unit/test_event_serialization.py -q   → 7 passed in 0.07s

# レーン全体ゲート（Refactor 後）
$ uv run ruff check .          → All checks passed!
$ uv run ruff format --check . → 4 files already formatted
$ uv run pyright               → 0 errors, 0 warnings, 0 informations
$ uv run pytest --cov          → 9 passed in 0.09s
   src/patterns_sse/events.py   19  0  4  0  100%
   TOTAL                        20  0  4  0  100%   (fail_under=85 達成 / 100.00%)
```

---

## Task 4 — FastAPI アプリと SSE 配信（4.1 / 4.2 / 4.3）

### 実装サマリ

- **4.1 `ScriptedEventSource`**（`tests/support/scripted_source.py`）: 固定 `SseEvent` 列
  （`step_started → tool_called → token×4 → completed`、固定チャンク `("Hel","lo"," wor","ld")`
  → `"Hello world"`）を決定論で yield。seam = `fail_at`（N 件後 `RuntimeError`）/ `block_after`
  （N 件後に未 set Event で park）/ 公開属性 `cancelled`・`released`（Task 6/7 用）。
- **4.2 `create_app` + `POST /sse/runs`**（`src/patterns_sse/app.py`）: DI seam で `EventSource` を
  注入受領、`RunRequest{query:str}` を受け `_event_stream` を `EventSourceResponse` で配信。順序は
  source 順を保持（R4.1）、`except Exception → ErrorEvent` で終端（R4.3/4.4）、`except
  CancelledError: raise` + `finally: aclose` + `is_disconnected` poll で切断対応（R6.1/6.3）、
  `tracer_provider` から 1 span（R7.1）。`_MAX_EVENTS=1000` / `send_timeout=60s`（R-2）。
- **4.3 公開面再エクスポート**（`__init__.py`）: `create_app`/`EventSource`/`to_sse`/
  `parse_sse_events` を flat 再エクスポート。

### 一次確認（切断機構）

設計が併用を指示する `await request.is_disconnected()` と sse-starlette 自身の
`_listen_for_disconnect` の receive 競合を実装ソースで一次確認:
- starlette 1.3.1 `requests.py:328` の `is_disconnected` は**事前キャンセル済み `CancelScope`**
  内で `receive()` を呼ぶ非ブロッキング peek → ほぼ常に `False`・メッセージ非消費。
- httpx 0.28.1 `asgi.py:134` の receive は `response_complete` 待ち（同一 anyio Event の複数
  wait は安全）。
- 結論: **load-bearing な停止経路は CancelledError（task-group cancel）一本**。poll は設計どおり
  協調的二次手段として配置（飾りではなく仕様準拠）、実停止は `except/finally` が担保。Task 0
  spike(b) と整合。

### 学び（Act 候補）

1. **app-factory の nested route は pyright strict `reportUnusedFunction` を踏む**。closure が
   必要な DI seam では入れ子が正で、リポジトリ既存 idiom `# pyright: ignore[reportUnusedFunction]`
   （`tests/unit/test_chat_agent_v2_surface.py:79`）で抑止する。
2. **`is_disconnected` は事前キャンセル peek で実質ノーオペになり得る**。切断検証は sse-starlette
   の cancel 経路（CancelledError）に依存させ、poll はそれの補助と位置づけるのが正しい設計理解。
3. **AsyncIterator の cleanup は `getattr(agen,"aclose",None)`** で行う（Protocol は `aclose` を
   保証しないため、sse-starlette 自身の `sse.py:369` と同 idiom）。

### 検証ゲート（証跡）

```
# 4.2 Red（実装前 / ハッピーパステスト先行作成）
$ uv run pytest --no-cov tests/unit/test_stream_order.py -q
E  ImportError: cannot import name 'create_app' from 'patterns_sse'
   1 error in 0.25s

# 4 Green（4.1/4.2/4.3 実装後）→ Task 4 テスト + 既存ユニット
$ uv run pytest --no-cov tests/unit/test_stream_order.py tests/unit/test_smoke.py \
    tests/unit/test_event_serialization.py -q   → 16 passed in 0.23s

# レーン全体ゲート（Refactor 後）
$ uv run ruff check .          → All checks passed!
$ uv run ruff format --check . → 7 files already formatted
$ uv run pyright               → 0 errors, 0 warnings, 0 informations
$ uv run pytest --cov          → 16 passed in 0.23s
   src/patterns_sse/__init__.py   4  0   0  0  100%
   src/patterns_sse/app.py       46  7  10  4   80%   (73,102,106-110,113->exit = Wave4 Task6/7/8 被覆)
   src/patterns_sse/events.py    19  0   4  0  100%
   TOTAL                         69  7  14  4   87%   (fail_under=85 達成 / 86.75%)
```

- **被覆の中間状態**: `app.py` 未被覆分岐（is_disconnected break / CancelledError 再 raise /
  error 変換 / max-events / span 有効化）は Wave 4（Task 6 エラー終端・Task 7 切断・Task 8 span）が
  exercise、98 への ratchet は Task 9.2。floor 85 は充足、回帰なし。

---

## Task 5.1 — token イベントの決定論検証（Wave 4 / R5.3・NFR-2）

**成果物**: `patterns/sse/tests/unit/test_token_determinism.py`（テストのみ、production 無改変）。

### 実装

R5.3 の射程を `token` レーンへ絞った検証テスト 3 本を ASGITransport 経由で追加:
1. `test_token_increments_match_the_fixed_chunk_list` — 明示チャンク列 `("To","ken"," stream")`
   への完全一致（fake が固定チャンクを verbatim 供給する＝join/再分割で増分境界が揺れない）。
2. `test_token_increments_are_byte_identical_across_runs` — 同一 app 3 連続駆動で増分列が
   byte 一致（+ `len>=2` で空マッチ防御）。
3. `test_token_increments_are_stable_across_independent_sources` — 独立構築 source × 異なる
   query で一致（台本は query 非依存、NFR-2）。

既存 `test_stream_order::test_stream_is_deterministic_across_runs`（全列等価）との差別化:
本 Task は `TokenEvent.text` の増分列のみを isolate し、語彙でなく増分境界の安定を pin する。

### 検証ゲート（証跡）

```
# RED（assertion が bite することの立証 / 増分期待値を一時誤設定）
$ uv run pytest --no-cov tests/unit/test_token_determinism.py -q
E  AssertionError: assert ['To', 'ken', ' stream'] == ['To', 'ken']
   1 failed, 2 passed in 0.20s

# GREEN（期待値是正後）
$ uv run pytest --no-cov tests/unit/test_token_determinism.py -q  → 3 passed in 0.18s

# レーン全体ゲート
$ uv run pytest --cov          → 19 passed（16→+3）/ TOTAL 86.75%（fail_under=85 充足）
$ uv run ruff check .          → All checks passed!
$ uv run ruff format --check . → 8 files already formatted
$ uv run pyright               → 0 errors, 0 warnings, 0 informations
```

- 被覆はテスト追加のみのため src 不変（app.py 80% の未被覆分岐は Task 6/7/8 が exercise、
  98 への ratchet は Task 9.2）。回帰なし。

---

## Task 6: エラー終端の検証（test-only、Wave 4）— 2026-06-14

**スコープ**: R4.3（実行中エラーを `error` イベントで配信しストリーム終端、silent 打ち切り禁止）/
R4.4（終端マーカーで明確終了）を `patterns/sse/tests/unit/test_error_termination.py` に立証。
検証対象の `app.py` `except Exception -> ErrorEvent` 分岐は Task 4.2 実装済み、Task 6 は純テスト。

**実装**: 5 ケース — `fail_at=2`（部分配信＋error 終端・completed 非到達）/ `fail_at=1` の
fail_message 到達（`ErrorEvent` 件数==1、swallow でない）/ `fail_at=4`（唯一の終端マーカー・
後続なし）/ `fail_at=0`（即時失敗でも単一 error 終端）/ message 1 行要約（`\n`/`Traceback` 不在）。

### 学び
- **silent swallow は StopIteration へ波及**: error 分岐を `pass` 化すると `ErrorEvent` 不配信に
  加え、generator が yield せず終了 → sse-starlette 経由で `coroutine raised StopIteration` の
  loop error。5 ケース全 RED。アサートは「error 不在」を確実に bite（vacuous でない）。

### 検証ゲート（証跡）

```
# RED（app.py error 分岐を一時 silent swallow へ改変し load-bearing を立証）
$ uv run pytest --no-cov tests/unit/test_error_termination.py  → 5 failed in 0.22s
   （RuntimeError: coroutine raised StopIteration / error 不配信）

# GREEN（app.py revert 後）
$ uv run pytest --no-cov tests/unit/test_error_termination.py -v  → 5 passed in 0.19s

# レーン全体ゲート
$ uv run ruff check .          → All checks passed!
$ uv run ruff format --check . → 9 files already formatted
$ uv run pyright               → 0 errors, 0 warnings, 0 informations
$ uv run pytest --cov          → 24 passed（19→+5）/ TOTAL 90.36%（fail_under=85 充足）
```

- error 変換分岐が exercise され lane coverage 86.75%→90.36%。残る未被覆（span / is_disconnected
  break / CancelledError 再 raise / max-events）は Task 7・8 が exercise、98 ratchet は Task 9.2。回帰なし。

---

## Task 7: 切断・キャンセル経路の hermetic 検証（Wave 4）— 2026-06-14

**スコープ**: R6.1（早期切断でジェネレータ停止・リソース解放）/ R6.2（ネットワーク I/O
ゼロのインプロセス ASGI 駆動で切断再現）/ R6.3（例外を握り潰さない）を、新規
`tests/support/asgi_driver.py`（7.1）＋ `tests/unit/test_disconnect_cleanup.py`（7.2）で立証。
検証対象の `app.py` の `except CancelledError: raise` / `finally: aclose` / 協調的
`is_disconnected` break は Task 4 実装済み、Task 7 はそれを exercise する純テスト＋駆動基盤。

**実装**:
- **7.1 asgi_driver**: 同一 ASGI アプリを `await app(scope, receive, send)` で直接駆動
  （実ソケット非使用、ADR-4）。custom `receive` は初回 `http.request`（ボディパース用）、以降は
  K 件の `data:` 捕捉まで `armed.wait()` でブロックし `http.disconnect` を注入。`send` 側で
  `data:` 件数を数え arm。hang guard（`wait_for(timeout)`→AssertionError）付き。
- **7.2 4 ケース**: (a) `block_after=2`＋`disconnect_after=2` で scope 注入切断→
  `cancelled`/`released`・prefix のみ（`completed` 非到達）/ (b) `block_after=3` で
  CancelledError が `error` へ書換えられず伝播（R6.3、`error`/`completed` 非到達）/
  (c) `_event_stream` 直接駆動＋`aclose()`（GeneratorExit）で producer 解放（R6.1）/
  (d) `is_disconnected=True` 即時で協調 break・無 yield・解放（R6.1）。

### 学び
- **park 位置が cancel の決定論性を決める**: source が `gate.wait()` で suspend した状態を
  作ることで、anyio cancel が最内 await へ CancelledError を届け source の
  `except CancelledError`（`cancelled=True`）が発火。park させない（yield 直後に cancel）と
  app の `finally: aclose()` が GeneratorExit で source を閉じる経路になり `cancelled` が
  立たない可能性 → `block_after` で park を強制し race を排除。
- **receive の二消費者干渉なし**: `_listen_for_disconnect`（timeout なし）と
  `is_disconnected()`（極小 timeout）が同一 receive を消費するが、生成器は arm 後に gate で
  park 済みのため is_disconnected は arm 前の timeout→False しか引かず協調 break と非干渉。

### 検証ゲート（証跡）

```
# RED（app.py の協調 break＋finally aclose を除去 ＋ driver の armed.set() を除去し
#      4 ケース全てが bite することを立証）
$ uv run pytest --no-cov tests/unit/test_disconnect_cleanup.py -v  → 4 failed in 10.42s
   （(a)(b): disconnect 未注入で hang→wait_for timeout→AssertionError /
     (c): released False / (d): delivered != [] かつ released False）

# GREEN（app.py・driver を revert 後）
$ uv run pytest --no-cov tests/unit/test_disconnect_cleanup.py -v  → 4 passed in 0.18s

# レーン全体ゲート
$ uv run ruff check .          → All checks passed!
$ uv run ruff format --check . → 11 files already formatted
$ uv run pyright               → 0 errors, 0 warnings, 0 informations
$ uv run pytest --cov          → 28 passed（24→+4）/ TOTAL 93.98%（fail_under=85 充足）
```

- 切断・キャンセル・解放経路が exercise され lane coverage 90.36%→93.98%。app.py 残未被覆は
  L73（span 分岐）/ L106（max-events break）/ L113→exit（aclose 無し分岐）で Task 8 が exercise、
  98 への ratchet は Task 9.2。回帰なし（既存 24 件全 green）。

---

## Task 8: 可観測性の配線と span 検証（8.1 実装 + 8.2 test-only、Wave 4）— 2026-06-14

**スコープ**: R7.1（`configure_tracing` の exporter 優先チェーン）/ R7.2（`InMemorySpanExporter`
注入で span≥1）/ R7.3（末端 span 存在のみ・属性集計なし）。8.1 は `observability.py` 新規実装
（ADR-5 複製）、8.2 は Task 4 の `app.py` span 配線を exercise する純テスト。

**実装**:
- `observability.py` — `configure_tracing(exporter=None) -> TracerProvider`。pydantic-ai/rag
  レーンと同形だが framework instrumentor は持たない（per-request `sse.stream` span は `app.py`
  `_open_span` が自前で開く）。優先チェーン: 注入 exporter（`SimpleSpanProcessor`）>
  `OTEL_EXPORTER_OTLP_ENDPOINT`（OTLP 遅延 import + `BatchSpanProcessor`）> no-op。
- `test_observability.py` 5 ケース — 8.1: (a) 注入捕捉 / (b) env 下でも注入優先（OTLP 非構築）/
  (c) env のみで OTLP 構築 / (d) 双方未設定で processor 0・無害。8.2: (e) `create_app` 駆動で
  `sse.stream` span が `get_finished_spans()` に 1 つ以上。

### 学び
- **OTLP 分岐をオフラインで bite させる**: 遅延 import される `OTLPSpanExporter` を、in-memory
  exporter を返す recorder へ monkeypatch することで collector 不要・ネットワーク 0 のまま
  「env tier は OTLP exporter を構築する」を行動レベルで立証。env/no-op の判別は public API が
  無いため `_active_span_processor._span_processors` 件数を読む（pyright reportPrivateUsage を
  ignore、`SLF` は本レーン ruff select 外で noqa 不要 → 付けると unused noqa で fail）。
- **SimpleSpanProcessor で span 終端の race を排除**: 注入 exporter には同期 export の
  `SimpleSpanProcessor` を使うため、ASGITransport がレスポンスを確定する時点で `sse.stream`
  span は終端済み。`get_finished_spans()` は決定論的に span を返す。

### 検証ゲート（証跡）

```
# RED 8.1（observability モジュール未作成）
$ uv run pytest --no-cov tests/unit/test_observability.py  → ModuleNotFoundError: patterns_sse.observability

# GREEN 8.1（observability.py 作成後）
$ uv run pytest --no-cov tests/unit/test_observability.py  → 5 passed

# load-bearing RED 8.2（app.py _open_span を常時 nullcontext() へ改変）
$ uv run pytest --no-cov tests/unit/test_observability.py::test_create_app_emits_app_span_into_injected_exporter
   → 1 failed（assert spans / assert ()）

# GREEN 8.2（app.py revert 後）
$ uv run pytest --no-cov tests/unit/test_observability.py  → 5 passed in 0.25s

# レーン全体ゲート
$ uv run ruff check .          → All checks passed!
$ uv run ruff format --check . → 13 files already formatted
$ uv run pyright               → 0 errors, 0 warnings, 0 informations
$ uv run pytest --cov          → 33 passed（28→+5）/ TOTAL 97.03%（fail_under=85 充足）
```

- span 分岐が exercise され lane coverage 93.98%→97.03%。`observability.py` 100%。app.py 残未被覆は
  L106（max-events backstop）/ L113→exit（aclose 無し分岐）のみで Task 9.2 の 98 ratchet 対象。
  回帰なし（既存 28 件全 green）。

---

## Task 9 — オフライン hermetic 保証とカバレッジゲート ✅

実施日: 2026-06-14 / 状態: **完了（9.1 / 9.2 green）**

**スコープ**: R5.1（hermetic ガードで台本フェイク一巡が実ソケット非到達・到達時 loud-fail）/
R5.4（`fail_under` を兄弟レーン parity へ ratchet）。9.1 は `test_smoke.py` のみ、9.2 は
`pyproject.toml` のみの厳格境界。

### Do（実施内容）

- **9.1 hermetic ガード + fake one-pass（`test_smoke.py`）**: RAG レーン idiom を複製した
  `block_network` フィクスチャ（monkeypatch で `socket.socket.connect`/`connect_ex` +
  `socket.getaddrinfo` を差し替え、AF_INET/AF_INET6 のみ `NetworkReachError` で loud-fail、
  AF_UNIX 等は実体委譲）を追加。3 ケース新設:
  - `test_block_network_guard_loud_fails_on_internet_connect` — 実 AF_INET connect が I/O 前に
    遮断される（ガード非空虚性の load-bearing 証跡）。
  - `test_fake_one_pass_runs_hermetically` — `create_app(ScriptedEventSource())` を ASGITransport
    で駆動し、ガード下で終端 `completed` 到達（offline 完走、R5.1）。
  - `test_runaway_producer_is_bounded_by_the_backstop` — `tokens=_MAX_EVENTS+1` の非終端的台本で
    R-2 backstop（`app.py:106`）を exercise。terminal marker を出さない producer でも cap で完走し
    ASGITransport を wedge しないことを立証。
- **9.2 ratchet（`pyproject.toml`）**: `fail_under` 85→**98**（pydantic-ai/rag parity）。実測
  99.01%（1pt バッファ）。残る唯一の未被覆分岐 `app.py:113->exit` の rationale を coverage
  コメントに恒久記録。

### 学び

- **新規テストファイル増設なしで L106 を被覆**: Task 9 境界は `test_smoke.py` + `pyproject.toml`
  のみ。dedicated な max-events テストファイルは作れないため、「非終端 producer でも offline run が
  *完走*する」という hermetic-completion の射程に backstop 検証を載せ、既存 `ScriptedEventSource`
  の `tokens` 長で `completed` を cap の外側へ押し出すことで新規 src/support なしに L106 を exercise。
- **L113->exit は被覆困難グルーとして残置（R-4）**: `aclose is None` アームは注入される
  `EventSource` が全て async generator（`aclose` 保持）であるため実務到達不能。当該分岐専用の
  非 generator イテレータは作為的で、100 への brittle ratchet より R-4 の「rationale 明記の上で
  残置」を選択。98 parity は actual 99.01% で充足。
- **mise 配線は Task 12.1 へ委譲**: 9.2 が指す `mise run patterns:test` への sse 行追加は
  `mise.toml`（Task 12.1 境界）の所掌。本タスクはレーンローカル gate（mise が per-lane に呼ぶ
  `uv run pytest --cov` と同一実体）で `fail_under=98` 充足を検証した。

### 検証ゲート（証跡）

```
# load-bearing RED 9.1（app.py backstop break を一時 neuter: `and False`）
$ uv run pytest --no-cov tests/unit/test_smoke.py::test_runaway_producer_is_bounded_by_the_backstop
   → 1 failed（AssertionError: assert 1004 == 1000）
# → app.py revert（git diff --stat = empty、net-zero 境界保全）

# GREEN 9.1 + レーン全体ゲート（9.2 ratchet 後）
$ uv run ruff check .          → All checks passed!
$ uv run ruff format --check . → 13 files already formatted
$ uv run pyright               → 0 errors, 0 warnings, 0 informations
$ uv run pytest --cov          → 36 passed（33→+3）
   → app.py 98%（残 113->exit）/ observability・events・__init__ 100%
   → Required test coverage of 98.0% reached. Total coverage: 99.01%
```

- lane coverage 97.03%→**99.01%**、`fail_under` 85→98 で gate green。回帰なし（既存 33 件継続 green、
  新規 3 件追加で 36）。Wave 5（Task 9）完了 → 残 Wave 6（Task 10/11/12/13）。

---

## Task 10 — Ollama 結合テスト（run_stream_events アダプタ）

実施日: 2026-06-14 / 状態: **完了（10.1 green）**

**スコープ**: R3.3（実モデル × 実ストリーミングを契約レベルで検証）/ R7.1（instrumented run で
span≥1）。境界は `patterns/sse/tests/integration/test_ollama_e2e.py` のみ。`RUN_INTEGRATION_PATTERNS=1`
ゲート（未設定時 skip）。

### Do（実施内容）

- **結合テスト + アダプタを 1 ファイルに**（NFR-3 厳守）: `_agent_event_to_sse`（pydantic-ai
  `AgentStreamEvent`/`AgentRunResultEvent` → `SseEvent` 純写像、I-1）と `_PydanticAIEventSource`
  （`EventSource` 適合の async-generator アダプタ。`run_stream_events` を `async with` 駆動）を
  test 内に定義。lane src（fw 非結合）へは漏らさず、`patterns_pydantic_ai` も import しない。
  ルーティング形の `Agent[None, str]`（ツールなし最小プロンプト）を pydantic-ai から直接構築。
- **span 二系統を単一 provider へ集約**: `configure_tracing(InMemorySpanExporter())` を
  `create_app(tracer_provider=...)`（`sse.stream`）と `InstrumentationSettings(tracer_provider=...)`
  （`instrument_model` 経由の `gen_ai.*`）の双方へ注入。
- **契約レベルアサート**: ASGITransport 全文バッファ → `parse_sse_events` 逆写像で
  (a) 先頭 `step_started` / 末尾が唯一終端マーカー・後続なし（R4.1）、(b) `token`≥1、
  (c) 各 `data` の `model_validate` ラウンドトリップ（R4.2/5.2）、(d) span≥1（R7.1）。
  実テキスト一致は禁止（実モデル非決定、決定論は Task 5 台本フェイクの所掌）。

### 学び

- **`run_stream_events` は async context manager（2.0.0b7 実測）**: 戻り値は
  `AbstractAsyncContextManager[AsyncIterator[AgentStreamEvent | AgentRunResultEvent]]`。
  `async with agent.run_stream_events(q) as events: async for e in events:` で駆動し、
  早期停止時に背景 run タスクを決定論クリーンアップ。I-1 の「async iterator」記述を実 API で確定。
- **ゲート結合テストの load-bearing 検証は同一パイプライン × FunctionModel で代替**: 実 Ollama は
  オフライン/サンドボックス不可。adapter→`create_app`→ASGITransport→`parse_sse_events`→span の
  **実コードパス**を network-zero の `FunctionModel`（固定チャンク stream）で駆動する throwaway
  ハーネスで実証。`AgentRunResultEvent→CompletedEvent` を一時 neuter → `assert types[-1] in
  terminal` が `last not terminal: token` で RED 確認後 revert（GREEN: `['step_started','token',
  'token','completed']` + span 3 本 `chat function::_stream`/`invoke_agent agent`/`sse.stream`）。
  ハーネスは境界外のため非コミット（Task 0 spike 同様、証跡は本ログに保全）。
- **アダプタは test 内に閉じて被覆不変**: 写像ロジックを test に置くため src 被覆は 99.01% で不変、
  `fail_under=98` を維持。オフラインゲートでは skipif で 1 skipped。

### 検証ゲート（証跡）

```
# load-bearing RED（offline FunctionModel ハーネス、completed 分岐 neuter）
$ uv run python /tmp/sse_adapter_harness.py
   → AssertionError: last not terminal: token   # 終端マーカー欠落をアサートが検知
# → adapter revert（GREEN）
$ uv run python /tmp/sse_adapter_harness.py
   → TYPES: ['step_started', 'token', 'token', 'completed']
   → SPANS: ['chat function::_stream', 'invoke_agent agent', 'sse.stream']
   → HARNESS GREEN    （ハーネスは rm で破棄）

# レーン全体ゲート（オフライン）
$ uv run ruff check .          → All checks passed!
$ uv run ruff format --check . → 14 files already formatted
$ uv run pyright               → 0 errors, 0 warnings, 0 informations
$ uv run pytest --cov          → 36 passed, 1 skipped
   → tests/integration/test_ollama_e2e.py s   （RUN_INTEGRATION_PATTERNS 未設定で skip）
   → Required test coverage of 98.0% reached. Total coverage: 99.01%
```

- 回帰なし（既存 36 件継続、結合 1 件は offline skip）。Task 10 完了 → 残 Wave 6（Task 11/12/13）。

---

## Task 11: パターン契約正本と単一点ドリフト配線 (11.1, 11.2) — ✅

`/sdd-impl 008-2c-cross-platform Task11`。Task 2 が `__all__` 追記で残した既存 RED
（drift 4 ケース）を、SSE README 正本作成（11.1）+ `_README_PATHS["sse"]` 登録（11.2）で解消。

### RED → GREEN（既存 RED を再確認 → 解消）

```
# 実装前 RED（Task 2 申し送り: package に 5 SSE モデル / README owner に不在）
$ cd patterns/contracts && uv run pytest --no-cov tests/unit/test_contract_drift.py -q
   → 4 failed
     test_documented_class_set_matches_package
     test_documented_field_sets_match_package
     test_documented_literal_vocabularies_match_package
     test_each_package_model_is_documented_in_exactly_one_readme
   → Extra in package: CompletedEvent/ErrorEvent/StepStartedEvent/TokenEvent/ToolCalledEvent

# 11.1 patterns/sse/README.md 作成（正本 fenced block: 5 モデル + SseEvent 注釈のみ、
#       必須4セクション、版表+ベータ注記+curl/httpx 例、R8.3 機微情報非掲載方針）
# 11.2 _README_PATHS に "sse" 1 行追加
$ uv run pytest --no-cov tests/unit/test_contract_drift.py -q
   → 4 passed
```

### 検証ゲート（contracts + sse 両レーン）

```
# contracts レーン
$ uv run ruff check .          → All checks passed!
$ uv run ruff format --check . → 12 files already formatted
$ uv run pyright               → 0 errors, 0 warnings, 0 informations
$ uv run pytest --cov          → 19 passed
   → test_contract_drift.py .... / test_rag_contracts.py / test_sse_contracts.py

# sse レーン（README 追加が配信パイプラインへ非回帰なことを確認）
$ cd patterns/sse && uv run ruff check .  → All checks passed!
$ uv run pytest --cov          → 36 passed, 1 skipped（結合 offline skip）
   → Total coverage 99.01%（fail_under=98 充足、被覆不変）
```

### 学び / 申し送り

- **parser 互換が load-bearing**: 正本ブロックは `name: annotation` 形（`ast.AnnAssign`）+ `type:
  Literal[...]` で判別子語彙をロック。`SseEvent` は単一行代入で記載し parser が対称スキップ（I-5）。
  接続例の python fence は normative block の後段に配置（`_normative_block` は最初の fence のみ抽出）。
- **`[project].readme` 宣言は Task 11 境界外**（`pyproject.toml` 所掌）。README 欠損は解消したが
  long-description 宣言は未変更 — 境界厳守。hatchling build は引き続き既存挙動。
- 回帰なし。残 Wave 6: Task 12（mise/CI）/ Task 13（docs/security 索引・SECURITY-NOTES）。

---

## Task 12 — mise タスクと CI への新レーン反映（2026-06-14）

Wave 6。SSE レーンを `patterns:*` mise タスクと patterns 系 CI へ明示配線し、ルート
ワークフローを無変更に保つ。設定配線タスクのため src ユニットは無し（load-bearing は
RED=配線前 sse 不在 → GREEN=mise 経由で sse が実 exercise + YAML/TOML 構造 assertion）。

### 12.1 mise.toml（rag 行後に `(cd patterns/sse && …)`）

```
# RED: 配線前
$ grep -c 'patterns/sse' mise.toml  → 0   # gap（sse は frameworks/*/ glob に非該当）

# 7 タスク（setup/lint/format/typecheck/test/audit/test:integration）へ追加 + ヘッダコメント
$ grep -c 'patterns/sse' mise.toml  → 9   # 7 task 行 + comment 2
$ uv run python -c 'import tomllib; tomllib.load(open("mise.toml","rb"))'  → OK

# GREEN: mise 経由で sse レーンが実際に exercise される
$ mise run patterns:lint   → == lint patterns/sse  / All checks passed!
$ mise run patterns:test   → == test patterns/sse  / Total coverage: 99.01%
                              36 passed, 1 skipped（全 6 レーン green）
```

### 12.2 patterns-ci.yml（rag 同型の専用 `sse` ジョブ + paths）

- `working-directory: patterns/sse`、`setup-uv` cache=`patterns/sse/uv.lock`、
  `uv sync --all-groups --locked` → ruff check / ruff format --check / pyright /
  `pytest --cov`（floor 98）/ pip-audit。HF オフライン step は不要（net-zero）。
- push/pull_request 双方の `paths` へ `patterns/sse/**` を明示追加。matrix 3 レーン不変。

### 12.3 patterns-integration-ollama.yml（pull_request.paths）

- `pull_request.paths` に `patterns/sse/**` を rag と並列追記。push は `patterns/**` で既被覆。

### 検証ゲート

```
# YAML 構造 assertion（yaml.safe_load）
  patterns-ci.yml jobs = [lane, contracts, rag, sse]
  sse job steps に sync/ruff/pyright/pip-audit、push+pr paths に patterns/sse/**、matrix 不変
  integration-ollama.yml pr.paths に patterns/sse/**（push は patterns/** 既被覆）

# ルート不変（R1.4/11.2/10.3）
$ mise run check
  [format] 61 files already formatted
  [lint] All checks passed!
  [typecheck] 0 errors, 0 warnings, 0 informations
  [test] 277 passed, 4 skipped
```

### 学び / 申し送り

- **depth-1 sibling は loop に載らない**: `patterns/sse/` は `patterns/frameworks/*/` glob 外。
  rag と同じく明示 `(cd patterns/sse && …)` 行が必須（contracts/rag の既存 idiom を踏襲）。
- **ルート隔離が R1.4/11.2 を構造的に担保**: root の lint/format/typecheck/test と 3 ルート
  ワークフローは無改変。patterns/ は root pyproject の extend-exclude で隔離されるため、
  mise/CI 配線追加は root `mise run check` の挙動に波及しない（実測でも無変更グリーン）。
- 残 Wave 6: Task 13（patterns/README.md 索引 + SECURITY-NOTES.md）。

---

## Task 13: タクソノミー索引とセキュリティノート（Wave 6, docs/security）

### 13.1 patterns/README.md — SSE 応用レイヤ索引

- RAG 節の直後・フレームワーク比較表の前へ `## 応用レイヤー（SSE 配信）` を追加。
- blockquote で「SSE はワークフローパターンではなく**配信インフラの応用**」を明記（R9.2）、
  Anthropic 6パターン表とは別軸索引。契約は `contracts/` 集約 + 同一ドリフト検知（R2.2）を併記。
- `## レーン構成`（frameworks/ 3レーン列挙）には追記せず（RAG と同様、応用レイヤは別索引）。

### 13.2 patterns/SECURITY-NOTES.md — SSE → OWASP マッピング + pre-commit 不変条件

- `### SSE 配信応用レイヤ → OWASP マッピング（Spec 008 Req 8.1）` を「既知の制約」節の前へ追加。
- 4リスク → OWASP: 機微情報混入→LLM02 データ漏洩 / 無制限消費→Unbounded Consumption /
  切断リソースリーク→Unbounded Consumption / 認証前提の不在→過剰な公開面。緩和策は実装済みの
  `_MAX_EVENTS=1000` / `send_timeout=60s` / 1行 `ErrorEvent.message` / `is_disconnected`+
  `except CancelledError: raise`+`finally: aclose` / `asgi_driver` hermetic 検証と対応（R8.1/8.3）。
- pre-commit 不変条件（R8.4）を**実測確認のうえ**記載。

### 検証ゲート（docs タスクのため load-bearing = リンク実在 + 不変条件実測 + ルート不変）

```
# (1) 新規内部リンク実在
OK  patterns/sse/README.md
OK  patterns/contracts/README.md

# (2) R8.4 pre-commit 不変条件（yaml.safe_load + 正規表現マッチで assertion）
OK  gitleaks: covers patterns/sse (exclude=None)
OK  forbid-hardcoded-model-ids: covers patterns/sse (exclude='^(tests/.*|src/.*/config\.py)$')
INVARIANT HOLDS: both secret/model-ID hooks scan patterns/sse

# (3) ルート無変更グリーン（R11.2/R10.3）
$ mise run check
  [format] all formatted / [lint] All checks passed! / [typecheck] 0 errors
  [test] 277 passed, 4 skipped in 3.22s   # Task 12 baseline と同値
```

### 学び / 申し送り

- **応用レイヤ docs は lane gate の外**: `patterns/README.md` / `SECURITY-NOTES.md` は
  どの lane の `pyproject` にも属さず、契約ドリフトテストはパターン README（`patterns/sse/
  README.md`）のみ読む。よってこの2ファイルへの変更はテストスイートに inert で、docs タスクの
  load-bearing は「テスト緑」ではなく「主張の事実性（リンク実在・不変条件の実測）」で立てる。
- **R8.4 は誇張しない**: gitleaks/forbid-model-id は patterns/ 全域を走査するが、
  ruff/format/pyright の3フックは `exclude: ^patterns/` で lane gate へ委譲。両者を分離して
  記述（秘匿情報・モデル ID 禁止 = リポジトリ全域不変、品質ゲート = lane 委譲）。
- **Wave 6 完了 = 008-2c 全 13 タスク green**: 残タスクなし。次は /sdd-validate-impl。
