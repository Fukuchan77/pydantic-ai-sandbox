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
