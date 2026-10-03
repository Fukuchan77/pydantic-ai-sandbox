# レート制限（`limits` 直結 / slowapi 置き換えの検証レーン）

ハブ `vaz-agentic-ai-next/services/api` の slowapi 0.1.10 を、すでに直接依存している
[`limits`](https://github.com/alisaifee/limits) の上に組んだ自前の ASGI ミドルウェアと FastAPI 依存関数で
置き換えられるかを検証する独立レーン（`patterns/rate-limit/`）。計画の正本は
[`docs/slowapi-replacement-plan.md`](../../docs/slowapi-replacement-plan.md)。本レーンはその第 4 節
「検証レーン」の実体である。

ワークフローパターンでも契約パターンでもない。`patterns_contracts` には型を足さず、兄弟レーンも
import しない（`patterns-contracts` は live suite の空振り検知のためだけの dev 依存）。

## 何を固定して検証するか

| 項目 | 本レーンの値 | ハブの現状 | 理由 |
|---|---|---|---|
| Python | **3.15**（`.python-version`、検証時点は 3.15.0rc2） | 3.13 固定 | 3.14 以降の `asyncio.iscoroutinefunction` 非推奨が slowapi と starlette 0.52 でハードエラーになる |
| fastapi | `>=0.142.2`、上限なし | `<0.137` | 0.137 の `_IncludedRouter` で slowapi のグローバル制限が黙って無効になる |
| starlette | `>=1.7.0`、上限なし | `<1.0` | slowapi 0.1.10 が 1.x と非互換 |
| `filterwarnings` | `error::DeprecationWarning`、ignore なし | ignore 1 件（`starlette.testclient`） | 計画 §4 手順 3 |

上限を付けないのは意図的である。外すこと自体が検証対象なので、ここで上限を付けると何も検証しない。
実際に検証した版は `uv.lock` が記録する。`tests/unit/test_smoke.py` は Python・fastapi・starlette が
上の境界を下回っていないことと、slowapi が入っていないことを assert する。lockfile が後退すると、
他のテストが緑のまま何も検証しなくなるためである。

## 構成

| 部品 | 場所 | 担う振る舞い |
|---|---|---|
| `RateLimiter` | [`limiter.py`](src/patterns_rate_limit/limiter.py) | ストレージ選択（Redis → メモリ縮退、B4）、固定窓での計数、`X-RateLimit-*` / `Retry-After` の算出、**唯一の 429 実装** `exceeded_response`（B5） |
| `RateLimitMiddleware` | [`middleware.py`](src/patterns_rate_limit/middleware.py) | 純 ASGI。ルーティング前に全 HTTP リクエストを既定の上限で数える（B1）。成功レスポンスに `X-RateLimit-*` を付ける |
| `rate_limit(limit)` | 同上 | ルート依存関数。既定より厳しい上限（B2）。上限は文字列か、リクエストから読む関数 |
| `add_rate_limiting(app, limiter)` | 同上 | `app.state.rate_limiter`・ミドルウェア・例外ハンドラを一度に登録する |

グローバル側はミドルウェアが `exceeded_response` を直接返し、ルート側は依存関数が
`RateLimitExceededError` を投げてハンドラが同じ `exceeded_response` を返す。2 経路が 1 つの関数に
合流するので（B6）、slowapi の「ハンドラが `async def` だと自前の既定ハンドラに差し替えられる」罠は
構造的に起きない。ハンドラは `async def` のままでよい。

キー関数は注入する。既定の `peer_address` は TCP の接続元だけを見る。`X-Forwarded-For` を信頼済み
プロキシから右から左へ辿る B3 は、ハブの `get_client_identifier` が slowapi 非依存で実装済みなので、
取り込み時はそれを `key_func` に渡す。

## slowapi との意図的な差分（ハブ取り込み時に確認すること）

1. **既定の上限のバケットは「クライアントごと・全ルート共通」**。slowapi は既定の上限を
   (クライアント, エンドポイント) ごとに数えていた（`extension.py` の `limit_scope = lim.scope or endpoint`）。
   エンドポイントを知るにはルート走査が要り、それがまさに 0.137 で壊れた部分である。
   ミドルウェアはルーティング前に動くので、存在しないパスへの 404 も予算を消費する。
   ハブの既定は `1000/minute` で、ヘルスチェックを含めても全ルート合算で足りるかを取り込み時に確認する。
2. **`Retry-After` は 429 にだけ付ける**。slowapi は 2xx にも付けていたが、RFC 9110 では意味を持たない。
   ハブのテストで 2xx の `Retry-After` を要求しているものは無い。
3. **`X-RateLimit-Reset` は窓のリセット時刻を epoch 秒の整数に切り上げたもの**。slowapi は `1 + reset_time` を
   小数付きの文字列で送っていた。ハブのテストは `float()` で読むので、どちらでも通る。
4. **縮退からの復帰**。主ストレージで失敗すると警告を 1 回出してメモリへ移り、`recovery_seconds`（既定 30 秒）
   経過後の次のリクエストで主ストレージを再試行する。起動時に Redis に届かない場合も、最初のリクエストで
   同じ経路を通るので、起動時の疎通確認は別に持たない。
5. **Redis クライアントは `redis.asyncio`**（`limits.aio` の `redispy` 実装）。ハブの slowapi は同期 API を
   イベントループ上で呼んでいた。`redis://` の URI はそのまま渡せる（内部で `async+redis://` に読み替える）。

## テスト

| ファイル | 守る振る舞い | ハブ側の移植元 |
|---|---|---|
| `tests/unit/test_global_limit.py` | B1。素のルート、`include_router` 配下（0.137 の canary）、404、成功時ヘッダの減算、窓のリセット | `tests/e2e/test_rate_limiting_enforcement.py`、`test_middleware_rate_limit_global_envelope.py`、`test_middleware_rate_limit.py` |
| `tests/unit/test_envelope.py` | B5・B6。本文 `{message, code}` の完全一致、ヘッダ、`Retry-After` が delay-seconds、2 経路の 429 が同形 | `test_middleware_rate_limit_global_envelope.py`、`middleware/test_rate_limit_retry_after.py` |
| `tests/unit/test_route_limit.py` | B2。厳しい上限が先に効く、成功時はグローバルのヘッダ、上限をリクエストから読む | `test_middleware_llm_rate_limit.py` |
| `tests/unit/test_storage_fallback.py` | B4 のオフライン側。失敗するストレージでも応答し続ける、クールダウン後の復帰 | `test_middleware_rate_limit_storage_uri.py` |
| `tests/integration/test_redis.py` | B4 の実 Redis 側。2 つの limiter が 1 つのバケットを共有、Redis 上での 429、到達不能 Redis からの縮退 | `-m redis` レーン |

ユニットは `block_network` で外部ソケットを遮断して走る。integration は `RATE_LIMIT_REDIS_URL` が無ければ
skip し、CI と `patterns:test:integration:rate-limit` は `EXPECT_LIVE_TESTS=3` で全 skip を赤にする。

```bash
cd patterns/rate-limit
uv sync --all-groups
uv run pytest --cov                                    # ユニット（Redis 不要）
RATE_LIMIT_REDIS_URL=redis://localhost:6379/0 \
  EXPECT_LIVE_TESTS=3 uv run pytest tests/integration  # 実 Redis
```

## 検証記録

計画 §5 の取り込み条件「第 4 節の 1〜4 の記録を残す」に対応する。

- **日付**: 2026-10-03
- **環境**: CPython 3.15.0rc2、fastapi 0.142.2、starlette 1.7.0、limits 5.8.0、redis-py 7.4.1、
  Redis 7.0.15（ローカル）
- **結果**: `uv run pytest --cov` で 27 passed / 3 skipped、カバレッジ 100%。
  `RATE_LIMIT_REDIS_URL` を付けて 30 passed。`error::DeprecationWarning`（ignore なし）の下で警告 0 件。
  `ruff check` / `ruff format --check` / `pyright`（strict）/ `pip-audit` はすべて clean

ハブの PR で使うチェックリスト、再実装で踏みやすい罠（依存関数の `Request` を `TYPE_CHECKING` 下に
置くと上限が黙って効かなくなる、starlette 1.7 の `TestClient` の警告が `error::DeprecationWarning` で捕まらない等）、
starlette の `--ignore-vuln` 5 件の特定結果は [`docs/hub-intake-2026-10.md`](../../docs/hub-intake-2026-10.md) §2 にある。

### `services/api` の依存一式は 3.15 で解決するか（計画 §6）

slowapi を外し、fastapi / starlette の上限を外した `services/api` の `pyproject.toml` で `uv lock` を試した。

- **Python 3.15: 解決しない。** `chromadb>=0.6.3,<1.0` → `onnxruntime>=1.14.1` が cp315 の wheel を
  まだ出していない（1.30.0 時点で cp311〜cp314t のみ）。slowapi は 3 つの据え置きの共通原因だが、
  3.15 へ上げる上での唯一の障害ではない、という計画 §6 の懸念が実際に当たった。
- **Python 3.14: 解決する**（203 パッケージ）。ただし `uv lock` までで、`uv sync` とテスト実行はしていない。

したがって、ハブの Python 版上げの現実的な次の目標は 3.14 であり、3.15 は onnxruntime（または chromadb 1.x
への移行）待ちである。
