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
