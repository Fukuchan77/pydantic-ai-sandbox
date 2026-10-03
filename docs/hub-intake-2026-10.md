# ハブへの取り込み候補（2026-10-03）

- **作成日**: 2026-10-03
- **宛先**: `vaz-agentic-ai-next/services/api`（FastAPI + Pydantic AI レーンの正本。ハブ ADR-0007）
- **取り込み手順**: ハブの `docs/dependency-policy.md` §8。ファイルのコピーではなく、ハブ側で再実装する
  （本リポジトリの Constitution III「ベンダリング禁止」とも同じ考え方）

散文は日本語、識別子・パス・コードは英語。

本リポジトリで検証した変更のうち、ハブへ持っていけるものとその条件をまとめる。対象は 2 つ。

1. slowapi 置き換えの検証レーン [`patterns/rate-limit/`](../patterns/rate-limit/README.md)（PR #40。計画は [slowapi-replacement-plan.md](./slowapi-replacement-plan.md)）
2. ブランチ `claude/laughing-ritchie-87q19c`（コミット `72e5e4a`、2026-09-24）。本書と同じ変更で main へマージした

**出所について**: 本書は、#40 と並行して同じ計画を別に実装したブランチ `claude/wonderful-johnson-qbl71d`
（`ad0bda7` / `f4a8f0a`）の調査結果を、#40 の実装（API 名・検証記録）に合わせて書き直したものである。
そのブランチの実装は #40 と重複するため取り込んでいない。調査結果のうち再確認できたものは「確認済み」、
できなかったものは出所を明記した。

---

## 1. 結論

| # | 変更 | 出所 | ハブへ | 一言 |
|---|---|---|---|---|
| H1 | slowapi を `limits` 直結の自前実装に置き換え、`fastapi<0.137` / `starlette<1.0` を外す | `patterns/rate-limit/` | **取り込む**（検証済み） | 計画 §4 の 1〜4 がすべて green。1 PR で入れる |
| H2 | starlette の `--ignore-vuln` 5 件を削除 | 同上 | **取り込む**（H1 と同じ PR） | 5 件とも修正版は 1.x 系にしかなく、最も新しいものが 1.3.1。`starlette>=1.3.1` で閉じる |
| H3 | Python の版上げ | 同上 | **3.14 なら取り込む。3.15 はまだ不可** | 3.15 では onnxruntime / torch の wheel が無く、依存一式が解決できない。H1 とは別 PR |
| L1 | `agent.run()` に `UsageLimits` と全体のタイムアウトを付ける | laughing-ritchie `src/…/api/routes/chat.py`、`config.py` | **取り込む（要修正）** | 本番 API に必要なガードレール。ただし 429 の使い方をハブの契約に合わせて変える（§3.2） |
| L2 | モデルが出した `sources` を、実際のツール結果と照合する | laughing-ritchie `chat.py::_grounded_sources` | **考え方だけ取り込む** | コードはサンドボックスの `search_kb` スタブ専用。ハブの RAG の引用検証と比較して判断する |
| L3 | ツールの docstring にはモデル向けの説明だけを書き、開発者向けメモはコメントへ移す | laughing-ritchie `agents/chat_agent.py` | **規約として取り込む** | コード変更ではなく、ハブのツール docstring の監査項目 |
| L4 | 自前のモデル呼び出しループで `function_tools` を送り、1 ターン内の全ツール呼び出しに応答する | laughing-ritchie `patterns/frameworks/pydantic-ai/…/autonomous_agent.py` | **取り込まない（確認だけする）** | パターン集のレーンの修正。ハブが `Agent.run` を使っていれば pydantic-ai が処理するので関係ない |
| L5 | deep-research のサブ研究者に brief（目的と対象外）を渡す | laughing-ritchie `patterns/deep-research/…` | **取り込まない** | パターン集のレーンの修正。ハブに相当機能があるときだけ参照する |
| L6 | テスト基盤（`tests/conftest.py` の環境変数上書き） | laughing-ritchie | **取り込まない** | 本リポジトリのフィクスチャ専用 |

---

## 2. slowapi 置き換え（H1〜H3）— 検証済み

検証記録の正本は [`patterns/rate-limit/README.md`](../patterns/rate-limit/README.md) の「検証記録」。
ここではハブの PR に必要な事項だけを挙げる。

### 2.1 検証結果

| 計画 §4 | 結果（CPython 3.15.0rc2 / fastapi 0.142.2 / starlette 1.7.0 / limits 5.8.0 / redis-py 7.4.1） |
|---|---|
| 1. A の実装 | ruff・pyright strict ともに clean |
| 2. B1・B5・B6 のテスト | 27 passed / 3 skipped、カバレッジ 100%。B1 は `include_router` 配下（0.137 の `_IncludedRouter`）でも上限が効くことを確認 |
| 3. `error::DeprecationWarning`（ignore なし） | 警告 0 件 |
| 4. Redis（B4、縮退を含む） | `RATE_LIMIT_REDIS_URL` 付きで 30 passed |
| pip-audit | 0 件（`--ignore-vuln` なし） |

### 2.2 ハブの PR（H1 + H2）でやること

計画 §5 のチェックリストに、検証で分かった次の点を加える。

- [ ] slowapi を削除し、`patterns/rate-limit/src/` を手本に `app/middleware/rate_limit.py` を**再実装**する。
      対応は次のとおり
  - ハブの `add_rate_limiting()`（slowapi の `Limiter` + `SlowAPIMiddleware` + ハンドラ登録）→
    #40 の `add_rate_limiting(app, limiter)`（`app.state.rate_limiter`・`RateLimitMiddleware`・ハンドラを一度に登録）
  - `enforce_llm_rate_limit` → `rate_limit(lambda request: <settings>.llm_rate_limit)` が返す依存関数
  - `rate_limit_exceeded_handler` と slowapi private の `Limiter._inject_headers` → `RateLimiter.exceeded_response`（唯一の 429 実装）
  - Redis 疎通確認とメモリ縮退 → `RateLimiter` のストレージ選択（`recovery_seconds` 後に主ストレージを再試行）
  - `get_client_identifier`（B3）は slowapi 非依存なのでそのまま `key_func` に渡す
- [ ] `fastapi>=0.137,<1.0`、`starlette>=1.3.1,<2.0` を宣言する。fastapi が要求するのは
      `starlette>=0.46.0` だけなので、starlette は**直接依存として**下限を持たせる（脆弱版に戻らないように）
- [ ] `limits` を直接依存へ格上げする。Redis クライアントは `limits.aio` の `implementation="redispy"` で
      既存の `redis` を使う（`coredis` を追加しない）
- [ ] `mise run api:audit` の starlette グループ 5 件を削除する（§2.4）
- [ ] `.github/dependabot.yml` の `fastapi` / `starlette` の ignore を見直す
- [ ] 既定の上限のバケットが「クライアントごと・全ルート共通」になる点（slowapi は (クライアント, エンドポイント) ごと）を、
      ハブの既定 `1000/minute` で足りるか確認する。レーン README「slowapi との意図的な差分」1
- [ ] `services/api/CLAUDE.md` の "Dependency pins that are load-bearing" と "A fourth coupling" を更新する（`AGENTS.md` も合わせて）

### 2.3 再実装で踏みやすい罠

出所は wonderful-johnson の別実装の検証。#40 の実装は 1 をすでに避けている。

1. **依存関数の `request: Request` を `TYPE_CHECKING` 下で import すると、上限が黙って効かなくなる。**
   FastAPI が注釈を解決できず `request` をクエリ引数として扱い、依存関数そのものが実行されない
   （エラーにもならない）。ruff の `TC` 系ルールがこの import の移動を勧めるので、移動させないこと。
   #40 の `middleware.py` は `starlette.requests.Request` を実行時に import している。
   B2 のテスト（LLM ルートで実際に 429 が出ること）があれば検出できる。
2. **starlette 1.7 の `TestClient` は `httpx` に `StarletteDeprecationWarning` を出す**
   （"install `httpx2` instead"）。これは `UserWarning` の派生なので **`error::DeprecationWarning` では捕まらない**。
   #40 のレーンは `httpx.ASGITransport` で駆動しているので出ないが、ハブの `services/api/tests` は
   2026-10-03 時点で 29 ファイルが `TestClient` を使っている。`httpx2` を dev 依存に足すか
   `httpx.ASGITransport` に移し、`filterwarnings` に `error::starlette.exceptions.StarletteDeprecationWarning` を
   足して starlette 自身の非推奨も黙って通さないようにする。
3. **redis-py の asyncio 実装には `asyncio.iscoroutinefunction` がまだ残っている**（`redis/asyncio/connection.py`、
   `redis_connect_func` を渡したときだけ通る経路。redis-py 8.1 で確認）。`limits` はこれを渡さないので発火しないが、
   3.16 で関数自体が消えるので、そのときは redis-py 側の対応を確認する。

### 2.4 starlette の `--ignore-vuln` 5 件（H2）— 確認済み

starlette `<1.0` の最終版 0.52.1 を単独で監査した（`pip-audit --no-deps -r <(echo starlette==0.52.1)`、2026-10-03）。
検出は 5 件で、**修正版はすべて 1.x 系にしかない**。1.7.0 に対する同じ監査は 0 件。
この 5 件は、ハブ `mise.toml` の `api:audit` タスクが抑止している starlette の 5 件と ID が一致する
（ハブ `108b47c` で照合）。

| ID | 別名 | 内容 | 修正版 |
|---|---|---|---|
| PYSEC-2026-161 | GHSA-86qp-5c8j-p5mr / CVE-2026-48710 | `Host` ヘッダを検証せずに URL を再構成するため、ホスト部にパスを注入できる | 1.0.1 |
| PYSEC-2026-2280 | GHSA-x746-7m8f-x49c / CVE-2026-48817 | `HTTPEndpoint` がメソッド名を `getattr` で引くため、`methods=` なしの `Route` で任意メソッドが届く | 1.1.0 |
| PYSEC-2026-2281 | GHSA-wqp7-x3pw-xc5r / CVE-2026-48818 | Windows の `StaticFiles` で UNC パスを `realpath` に渡し、SMB 経由の SSRF になる | 1.1.0 |
| PYSEC-2026-248 | GHSA-jp82-jpqv-5vv3 / CVE-2026-54282 | `/` で始まらないパスで `request.url` の authority がずれ、`hostname` / `netloc` を偽装できる | 1.3.0 |
| PYSEC-2026-249 | GHSA-82w8-qh3p-5jfq / CVE-2026-54283 | `application/x-www-form-urlencoded` では `max_fields` / `max_part_size` が効かない | 1.3.1 |

`starlette>=1.3.1` を直接依存に宣言すれば、5 件とも**版上げで閉じる**。ハブの `api:audit` に残る
chromadb 3 件と nltk 1 件はこの変更と無関係なので残す。

### 2.5 Python の版上げ（H3）は別 PR、上げ先は 3.14

- **3.15: 解決できない。** ハブの `services/api` の `pyproject.toml`（slowapi 削除・上限解除済み）で `uv lock` が失敗する
  （#40 で確認）。原因は `chromadb>=0.6.3,<1.0` → `onnxruntime`。加えて `sentence-transformers` → `torch` も同じ状態で、
  2026-10-03 時点の PyPI で onnxruntime 1.30.0・torch 2.14.1 とも cp315 の wheel も sdist も無い（回避策がない）。
- **3.14: 解決する**（#40 で `uv lock` まで確認。`uv sync` とテストは未実施）。wonderful-johnson の別実装は
  3.14.8 の venv で unit + Redis が green だったと記録しているが、#40 の実装は `requires-python = ">=3.15"` のため
  3.14 では実行していない。H3 の PR で `uv sync` とテストを 3.14 で通すこと。
- 3.15 では pydantic 2.13.5 が要求する pydantic-core 2.46.5 に cp315 wheel が無く、Rust のソースビルドになる
  （CI で約 3 分。キャッシュが効けば 2 回目以降は不要）。

H1 が main で安定した後に、`.python-version` / `mise.toml` / `test_python_version_pin.py` を 3.14 へ上げる。

---

## 3. `claude/laughing-ritchie-87q19c` の差分（L1〜L6）

### 3.1 ブランチの状態

- 1 コミット（`72e5e4a`）。基点は `ae0c418` で、PR #38・#39 より前から分岐していたが、main とは衝突しない
- main とマージした状態ではルートのカバレッジが 96.88% で、下限 98% を下回っていた。未テストだった次の 3 経路に
  テストを足し、98.51% にしてから main へ入れた
  - `config.py` の `_validate_chat_usage_limit` の拒否経路（0 以下の値）→ `tests/unit/test_config.py`
  - `config.py` の `_validate_chat_request_timeout` の拒否経路 → 同上
  - `chat.py::_grounded_sources` の `elif content is not None:` 分岐（ツール結果が list でない場合）→
    `tests/unit/test_chat_endpoint_guardrails.py`

ハブへ持っていく際にも同じテストが必要になる。

### 3.2 L1: `UsageLimits` とタイムアウト — 取り込む（要修正）

**内容**: `POST /chat` が `agent.run()` を上限なし・タイムアウトなしで呼んでいた。ブランチでは
`UsageLimits(request_limit=25, total_tokens_limit=50_000)` と `asyncio.wait_for(..., timeout=30)` を付け、
設定値として `CHAT_USAGE_REQUEST_LIMIT` / `CHAT_USAGE_TOTAL_TOKENS_LIMIT` / `CHAT_REQUEST_TIMEOUT` を追加し、
0 以下を起動時に拒否するバリデータも付けた。

**ハブへ持っていく理由**: ツールのループが暴走したり、プロバイダの応答が返らなかったりすると、
1 リクエストがトークンと接続を際限なく消費する（OWASP Agentic AI の "unbounded consumption"）。
これはサンドボックス固有の問題ではなく、`agent.run()` を呼ぶ本番ルートすべてに当てはまる。
レート制限（H1）はリクエストの**回数**を抑えるが、1 回あたりの**消費量**は抑えないので、両方必要になる。

**そのまま持っていけない点**:

1. **上限超過を 429 にしている。** ハブの 429 はレート制限の応答で、`{message, code}` 本文、
   `X-RateLimit-*`、`Retry-After` を伴う（B5）。`UsageLimitExceeded` は同じリクエストを再送しても
   同じ結果になるので、「待てば通る」という意味の 429 と `Retry-After` を前提にしたクライアントや
   プロキシの再試行を招く。ハブでは別の `code`（例: `USAGE_LIMIT_EXCEEDED`）と、429 以外のステータスにする。
   どのステータスにするかはハブのエラー方針で決める
2. **本文が `HTTPException` の `{"detail": ...}` 形になっている。** ハブのエラー本文の形（`{message, code}`）と
   揃える。グローバルな例外ハンドラが変換しているかどうかはハブで確認する
3. **`detail=str(exc)` で pydantic-ai の内部メッセージ（上限値を含む）をそのまま返している。** 固定の文言にする

**ハブで確認すること**: `agent.run()` / `agent.iter()` を呼ぶルートの一覧。ストリーミングするルートでは
`asyncio.wait_for` で全体を囲めないので、別の方法（`UsageLimits` だけを付ける、イベント間のタイムアウトにするなど）を検討する。

### 3.3 L2: 引用（`sources`）の照合 — 考え方だけ取り込む

**内容**: `ChatResponse.sources` はモデルが自由に書ける `list[str]` なので、実在しない ID も書けてしまう。
`_grounded_sources` は実行履歴の `ToolReturnPart` から `search_kb` が実際に返した ID を集め、
それ以外を捨てる。`search_kb` が一度も呼ばれていなければ空にする。

**ハブでの扱い**: 実装は `search_kb` スタブ（`kb-stub:<query>` を返すだけ）に合わせた専用コードで、
そのままは使えない。持っていくのは「**構造化出力の引用フィールドも自由記述と同じく信用せず、
その実行で実際に得た検索結果と照合する**」という原則のほう。

**ハブで確認すること**: ハブの RAG（llama-index / chromadb）の応答に引用フィールドがあるか、
あるならすでに検索結果と照合しているか。照合していれば取り込む必要はない。照合していなければ、
ハブ側の検索結果（ノード ID など）を基準に再実装する。

### 3.4 L3: ツール docstring の書き方 — 規約として取り込む

**内容**: pydantic-ai はツール関数の docstring をそのままモデルへのツール説明として送る。`search_kb` の docstring に
仕様書の節番号やテストファイル名など開発者向けの記述があったので、モデル向けの説明だけに書き直し、
開発者向けのメモは送信されないコメントへ移した。

**ハブでの扱い**: コード変更はない。ハブの `@agent.tool` / `@agent.tool_plain` の docstring を同じ観点で見直す
（参考: [tool-design.md](./tool-design.md)、`patterns/TOOL-DESIGN-NOTES.md`）。

### 3.5 L4・L5・L6 — 取り込まない

- **L4（autonomous-agent）**: 自前で `Model.request()` を呼ぶループで `ModelRequestParameters()` を空のまま送っていたため、
  実際のモデルにはツールの存在が伝わっていなかった。また 1 ターンに複数のツール呼び出しがあっても最初の 1 つにしか
  応答していなかった。どちらもパターン集のレーンの修正。ハブが `Agent.run` / `Agent.iter` を使っていれば
  pydantic-ai 自身が処理するので影響はない。ハブに `Model.request()` を直接呼ぶ箇所があるかだけ確認する
- **L5（deep-research）**: `ResearchBrief.out_of_scope` が宣言されているのにサブ研究者のプロンプトに渡っていなかった
  問題の修正。パターン集のレーンの話で、ハブにマルチエージェントの調査機能がある場合だけ参照する
- **L6（テスト基盤）**: `app_with_overrides` に環境変数の上書きを足しただけ。本リポジトリのフィクスチャ専用

---

## 4. 次の作業

| 順 | 作業 | 場所 |
|---|---|---|
| 1 | H1 + H2 を 1 PR で取り込む（§2.2 のチェックリストと §2.3 の罠） | ハブ |
| 2 | L1 を §3.2 の修正を加えて取り込む。H1 の 429 の形が決まった後のほうが、ステータスと `code` を揃えやすい | ハブ |
| 3 | L2・L3 をハブの現状と突き合わせる（§3.3・§3.4 の「ハブで確認すること」） | ハブ |
| 4 | H1 が安定した後、Python を 3.14 へ上げる（H3）。`uv sync` とテストを 3.14 で通す | ハブ |
