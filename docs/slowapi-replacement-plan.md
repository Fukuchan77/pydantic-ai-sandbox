# slowapi 置き換え計画 — Python 3.15 への道筋

- **作成日**: 2026-10-03
- **対象**: `vaz-agentic-ai-next/services/api`（FastAPI レーンの正本。ハブ ADR-0007）
- **検証の場**: 本リポジトリ（Python のベータ検証レーン。ハブの `docs/dependency-policy.md` §8）
- **起票元**: ハブ spec `008-hub-consolidation-followup` Requirement 5

散文は日本語、識別子・パス・コードは英語。

---

## 1. 結論

`services/api` には 3 つの据え置きがある。**3 つとも原因は slowapi 0.1.10 という 1 つの依存**である。
slowapi を、すでに直接依存している `limits` の上に組んだ自前の ASGI ミドルウェアと FastAPI 依存関数に
置き換えれば、3 つを 1 回の変更で同時に外せる。

| 据え置き | なぜ slowapi が原因か（`services/api/CLAUDE.md` / `pyproject.toml` の記録） |
|---|---|
| `fastapi<0.137` | 0.137 は include した router を `_IncludedRouter` で包み、`app.routes` へ平坦化しなくなった。slowapi の `_find_route_handler` は `app.routes` を非再帰で走査するため `.endpoint` を見つけられない。その結果 `_should_exempt` が**全リクエストを除外扱い**にし、グローバルなレート制限が黙って無効になる |
| `starlette<1.0` | slowapi 0.1.10 は starlette 1.x と非互換（例外ハンドラの誤ディスパッチ、`SlowAPIMiddleware` が `X-RateLimit-*` を出さなくなる） |
| Python 3.13 固定 | 3.14 で `asyncio.iscoroutinefunction` が非推奨になった。starlette 0.52（`routing.py`）と slowapi（`extension.py`）がまだ呼んでおり、`filterwarnings = ["error::DeprecationWarning"]` の下でハードエラーになる（PR CI run 31880991303 で 63 failed / 12 errors）。starlette は上の行の理由で 1.x へ上げられない。1.x 系が呼び出しを解消しているかは、第 4 節の検証レーンで確認する |

さらに、`starlette<1.0` は `mise run api:audit` の `--ignore-vuln` 第 1 グループ（starlette の 5 件）を
抱え続ける理由にもなっている。slowapi を外せば、この 5 件を starlette の版上げで閉じられるかを再評価できるようになる。

## 2. 現在 slowapi に依存している面（置き換えで守るべき振る舞い）

`services/api/app/middleware/rate_limit.py`（313 行）と `app/main.py` の実測。

| # | 振る舞い | 現在の実装 | 守っているテスト |
|---|---|---|---|
| B1 | 全ルートに既定の上限（1000/minute） | `SlowAPIMiddleware` + `Limiter(default_limits=...)` | `tests/e2e/test_rate_limiting_enforcement.py`（`fastapi<0.137` の canary） |
| B2 | LLM を呼ぶルートには、より厳しい上限（`llm_rate_limit`） | `enforce_llm_rate_limit` 依存関数。`limiter.limiter.hit(item, identifier)` を直接呼ぶ（**すでに `limits` を直接使っている**） | `tests/unit/middleware/` 配下 |
| B3 | キーは `get_client_identifier()`。`trusted_proxies` からのときだけ `X-Forwarded-For` を右から左へ辿る | slowapi の `key_func` に渡しているだけ。**slowapi 非依存** | `tests/unit/middleware/` 配下 |
| B4 | ストレージは Redis。到達できなければメモリへ縮退し、警告を出す | `Limiter(storage_uri=..., in_memory_fallback_enabled=True)` | `-m redis` レーン（`REDIS_LIVE_TEST_COUNT = 7`） |
| B5 | 429 はフラットな `{message, code}` 本文に、`X-RateLimit-*` と秒数の `Retry-After` を付ける | `limiter._inject_headers`（**private API**）に委譲 | `test_middleware_rate_limit_global_envelope.py`、`middleware/test_rate_limit_retry_after.py` |
| B6 | 429 の 2 つの発生源（グローバル / LLM ルート）が同じハンドラに合流する | `RateLimitExceeded` の例外ハンドラ（`def` であること。`async def` だと slowapi が自前のハンドラに差し替える） | 同上 |

B2・B3 はすでに slowapi を経由していない。置き換えが必要なのは **B1・B4・B5・B6** だけである。

## 3. 候補の比較

| 候補 | B1 全ルート | B4 Redis + メモリ縮退 | B5 ヘッダ | 新規依存 | 評価 |
|---|---|---|---|---|---|
| **A. `limits` 直結の自前実装**（推奨） | 純 ASGI ミドルウェアで実装 | `limits.storage` の Redis / Memory を自前で切り替え | `limits` の `get_window_stats()` から計算 | なし（`limits` は既存の推移依存。直接依存に格上げするだけ） | private API への依存が消える。ルート走査をしないので FastAPI の router 構造の変化に影響されない |
| B. `fastapi-limiter` | 依存関数ベースで、グローバルなミドルウェアが無い | Redis 専用。メモリ縮退が無い | 自前 | 追加 | B1・B4 を満たさない |
| C. slowapi を fork / パッチ | ○ | ○ | private API のまま | fork の保守 | 上流が止まっている依存を抱え込むだけ |
| D. ゲートウェイ（Nginx / Envoy / API Gateway）へ移す | ○ | ゲートウェイ次第 | ゲートウェイ次第 | インフラ | B2（LLM ルートだけ厳しくする）と B3 のアプリ層ロジックが失われる。ローカル開発とテストでの再現も難しい |

**A を採る。** `limits` は slowapi の下で実際にカウントしているライブラリそのもので、B2 が既に直接使っている。
A は「slowapi という薄い層を剥がす」変更であって、新しいレート制限エンジンへの移行ではない。

### A の設計スケッチ

- `RateLimitMiddleware`（純 ASGI。`BaseHTTPMiddleware` は使わない）
  - `scope["type"] == "http"` のときだけ動く。キーは B3 の `get_client_identifier()` を再利用する
  - `FixedWindowRateLimiter`（slowapi の既定と同じ戦略）で `hit()` し、超過なら 429 を自分で返す
  - 成功レスポンスにも `X-RateLimit-*` を付ける（`send` をラップする）
- `build_storage(redis_url)`: `RedisStorage` を作って `check()` で疎通確認し、失敗したら
  `MemoryStorage` と警告ログ（B4）。実行中の Redis 断にも同じ縮退をかける
- `rate_limit_response(item, identifier)`: B5 / B6 の単一実装。グローバル側と `enforce_llm_rate_limit` の
  両方がここを通るので、例外ハンドラ経由の合流（と `def` / `async def` の罠）が要らなくなる
- `Settings.llm_rate_limit` のバリデータの文言（「slowapi が期待する形式」）を `limits` の形式に改める

## 4. 検証レーン（本リポジトリで行うこと）

本リポジトリは Python 3.13 固定のまま、**別レーン**として次を作る。`patterns/` の 8 レーン独立 uv 構成と
同じ流儀で、既存のゲートには影響させない。

1. `patterns/rate-limit/`（新設）に、上の A を最小構成で実装する。
   FastAPI と starlette は**上限なしの最新版**、Python は `.python-version` で **3.15** に固定する。
2. `services/api` の B1・B5・B6 を守っているテストのうち、アプリ固有でない部分を移植し、A に対して通す。
   特に次の 3 つ。
   - 全ルートに上限が効くこと（`_IncludedRouter` 下でも。B1 の canary の再現）
   - 429 の本文とヘッダの完全一致（B5）
   - グローバルと依存関数の 2 経路が同じ 429 になること（B6）
3. `filterwarnings = ["error::DeprecationWarning"]` を**素の形で**（ignore なしで）有効にし、
   Python 3.15 下で 1 件も出ないことを確認する。
4. Redis レーン（B4）は `redis:7-alpine` のサービスコンテナで、メモリ縮退を含めて確認する。

### 検証状況（2026-10-03）

1〜4 は [`patterns/rate-limit/`](../patterns/rate-limit/README.md) で実施した。記録（版・コマンド・結果）と、
slowapi との意図的な差分（既定の上限のバケットが全ルート共通になる点など）は同 README の「検証記録」と
「slowapi との意図的な差分」にある。

## 5. ハブへの取り込み条件

ハブ `docs/dependency-policy.md` §8.2 の手順に従う。この件に固有の条件は次のとおり。

- 第 4 節の 1〜4 がすべて green であること。その記録（コマンド・結果・コミット）を本リポジトリに残す
- ハブ側の変更は 1 PR にまとめる。
  - slowapi の削除と、A の実装を `services/api/app/middleware/rate_limit.py` へ移す
  - `fastapi<0.137` / `starlette<1.0` の上限を外す。新しい上限は次メジャーの手前に置く。
    `test_config_dependency_bounds.py` が上限の存在自体を要求する
  - `.github/dependabot.yml` の `fastapi` / `starlette` の ignore を見直す
  - `mise run api:audit` の starlette グループ（5 件）を、生の `pip-audit` で再評価する
  - `services/api/CLAUDE.md` の「Dependency pins that are load-bearing」と
    「A fourth coupling」（`_inject_headers`）の節を更新する。`AGENTS.md` とペアで
- **Python の版上げは別 PR にする。** slowapi の置き換えが main で安定してから
  `.python-version` / `mise.toml` / `test_python_version_pin.py` を動かす。
  2 つを同時に入れると、DeprecationWarning の検査がどちらの変更で落ちたのか切り分けられない。

## 6. 未確認事項

- Python 3.15 の配布状況と、`services/api` の他の依存（`llama-index-core`、`chromadb` 0.6.3、
  `sentence-transformers`、`litellm`）の 3.15 対応は**まだ調べていない**。slowapi は 3 つの据え置きの
  共通原因だが、3.15 へ上げる上での唯一の障害とは限らない。第 4 節の検証レーンでは
  `services/api` の依存一式を 3.15 で `uv sync` できるかも確認する。

  **2026-10-03 確認結果**: 3.15 では解決しない。`chromadb>=0.6.3,<1.0` が要求する `onnxruntime` に
  cp315 の wheel がまだ無い。3.14 では `uv lock` が解決する（`uv sync` とテストは未実施）。詳細は
  [`patterns/rate-limit/README.md`](../patterns/rate-limit/README.md) の検証記録。
