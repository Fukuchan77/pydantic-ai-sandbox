# ハブへの取り込み候補（2026-10-03）

- **作成日**: 2026-10-03
- **最終更新日**: 2026-10-04（§7 追記）
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

## 1. Evidence ledger（正規化表）

status は `landed` / `verified` / `proposed` / `already-present` / `waiting` / `rejected` のいずれかで管理する。
完了・不採用になった行も削除せず、判断履歴として保持する。確認対象の immutable hub commit は
`3646b473db41d853380d7088bf381f1f6ce1e08c`（2026-10-03、PR #76）である。

| ID | 変更 | status | 2026-10-04 の根拠・次の条件 |
|---|---|---|---|
| H1 | slowapi を `limits` 直結の自前実装へ置換 | `landed` | hub `3646b47` の `services/api/app/middleware/rate_limit.py` と `services/api/pyproject.toml`。PR #76 で反映済み |
| H2 | starlette の audit suppression 5 件を版上げで解消 | `landed` | hub `3646b47` は `starlette>=1.3.1,<2.0` / resolved 1.7.0、旧 starlette 5 件の suppression を削除済み |
| H3 | hub `services/api` を Python 3.14 へ移行 | `proposed` | §6（`3646b47`）と §7.1（`afbe6eb`）は failed。§7.2 の候補 commit `966becc`（hub branch `claude/project-thread-583dhe`）は 3.14 で §8.1 satisfied。hub `main` に入った commit で同じ runner が green になった時点で `verified` へ移す。3.15 は下記 blocker が全て wheel-ready になるまで待つ |
| L1 | `UsageLimits` と request / stream timeout | `already-present` | hub `3646b47` の `services/api/app/api/v1/agent.py` と `_stream.py` に `UsageLimits`、request timeout、stream event timeout が存在 |
| L2 | 生成された `sources` を実ツール結果と照合 | `waiting` | hub spec `009` R6 の確認結果待ち。受領時に hub の RAG node ID 照合有無を記録する |
| L3 | tool docstring をモデル向け説明だけに限定 | `waiting` | hub spec `009` R6 の tool docstring audit 結果待ち |
| L4 | direct `Model.request()` loop の tool contract | `waiting` | 現行判断は「取り込まない（確認だけする）」。hub spec `009` R6 で direct call を確認後、影響なしなら行を残したまま `rejected` へ移す。`3646b47` では health probe に direct call が 1 件あるが agent tool loop ではない |
| L5 | deep-research の sub-researcher brief | `rejected` | hub intake 対象外の pattern-lane 固有変更。相当機能が将来できる場合だけ新規 trial として再評価 |
| L6 | sandbox 固有 test fixture | `rejected` | hub へコピーしない。sandbox の fixture 専用 |

### 1.1 Python 3.15 blocker ledger

必要 wheel tag は macOS / Linux の実 runner を含む `cp315`。版は hub `3646b47` の
`services/api/uv.lock` に固定されたものを使い、最新 upstream 版へ読み替えない。

| package | hub lock 版 | 必要 artifact | sdist | 確認日 | 状態 | 根拠 |
|---|---:|---|---|---|---|---|
| `onnxruntime` | 1.30.0 | `cp315` wheel | なし | 2026-10-04 | blocked | PyPI release files に `cp315` wheel / sdist ともに無し |
| `torch` | 2.14.0 | `cp315` wheel | なし | 2026-10-04 | blocked | PyPI release files に `cp315` wheel / sdist ともに無し |
| `pydantic-core` | 2.46.5 | `cp315` wheel | `pydantic_core-2.46.5.tar.gz` あり | 2026-10-04 | source-only | `cp315` wheel は無く、Rust source build になる |

### 1.2 月次 dependency refresh checklist

`chore/dependency-security-refresh` の各月次作業で、同じ PR / evidence 更新として次を実施する。

1. hub の当月対象 commit と `services/api/uv.lock` から上表 3 package の **lock 版**を取り直す。
2. PyPI release files で lock 版の `cp315` wheel tag と sdist の有無を確認し、日付・状態・file name を上表へ追記する。
   3 package がすべて必要 platform の `cp315` wheel-ready になった場合だけ、§6 と同じ runner を `--python 3.15` で反復する。
3. PyPI の最新 LiteLLM release metadata で OpenAI SDK 3.x support 宣言を確認する。2026-10-04 の最新
   `litellm 1.104.0` は `openai>=2.20.0,<3.0.0` のため未対応。
4. LiteLLM が `openai>=3` を宣言した月は、R2.3 に従い root の direct `openai>=2.47.0,<3.0.0` と cap を撤去し、
   `pydantic-ai-slim` の `openai` extra へ戻す trial を行う。`tests/unit/test_ollama_openai_compat.py`、
   `tests/unit/test_litellm_dependency_floor.py`、`mise run check`、`mise run cov`、`uv run pip-audit` の結果、
   blocker、再試行条件を日付付きで本 ledger と Root baseline run に残す。失敗時は cap を保持し、暗黙に別構成へ移行しない。
5. L2–L4 は hub spec `009` R6 の受領結果を確認し、行を削除せず status と根拠を更新する。

### 1.3 pydantic-ai beta trial ledger

BeeAI / LlamaIndex lane は比較用として凍結し、今後の pydantic-ai beta trial は root を既定の実験場所とする。
hub より新しい pydantic-ai release が対象機能を含んだ時に、**1 機能につき 1 test + 1 record** を同じ変更で追加する。

| date | feature / API | sandbox test | hub affected file | versions | result | recommendation |
|---|---|---|---|---|---|---|
| 2026-10-04 | `pydantic-ai-slim` 2.54 系 + OpenAI SDK 2.x の非ストリーミング Chat Completions | `tests/unit/test_ollama_openai_compat.py` | `services/api/pyproject.toml` | `pydantic-ai-slim==2.54.0`; `openai==2.54.0`; `litellm==1.103.2` | normal response、timeout forwarding、request payload、error mapping が green。root gates / coverage / audit も green | `adopt`: 2.54 系は OpenAI 2.x compatibility contract を伴って採用可。`pydantic-ai-slim[openai]` の復帰と OpenAI 3.x は LiteLLM 対応まで `wait` |

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

- **3.15: まだ解決できない。** 2026-10-04 に hub `3646b47` の lock 版を再確認した結果は §1.1 のとおり。
  `onnxruntime==1.30.0` と `torch==2.14.0` には `cp315` wheel / sdist が無く、
  `pydantic-core==2.46.5` は sdist のみで `cp315` wheel が無い。3 package が必要 platform の wheel-ready に
  なるまで 3.15 verification は開始しない。
- **3.14: lock / sync は解決するが、gate は未達。** §6 の実測では standalone `uv lock` と `uv sync` は exit 0。
  ただし `api:check` は Ruff の Python 3.14 `UP037` 4 件で exit 1。独立 test diagnostic も
  `asyncio.iscoroutinefunction` の `DeprecationWarning` を error として 58 件失敗したため、H3 は `proposed` のまま。
- H3 の hub PR は `services/api/.python-version`、`pyproject.toml` の Python floor / Ruff target、
  `test_python_version_pin.py` を同時に更新し、§6 の blocker を解消して同じ immutable-commit runner を再実行する。
- **2026-10-04 追記**: §6 の 2 blocker は、3.13 のまま入れられる前段の修正で解消できることを §7.2 で確認した。
  H3 PR は「前段の修正（§7.3）→ 版上げ（§6.3 の migration diff + `uv lock` の再生成）」の 2 段にできる。

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
| 1 | §7.3 の前段修正（`UP037` 4 件を `typing.Self` へ、`asyncio.iscoroutinefunction` の emitter 限定 ignore 2 件）を hub `main` へ入れる。候補は hub branch `claude/project-thread-583dhe`（`966becc`）。対応版の upstream release は 2026-10-04 時点で無い（§7.3） | ハブ |
| 2 | 1 が入った hub `main` の commit を §6 と同じ runner で再検証し、required 3 phases が全て exit 0 の場合だけ H3 を `verified` へ移す | sandbox |
| 3 | H3 本体（§6.3 の migration diff と `uv lock` の再生成）を hub で別 PR にする | ハブ |
| 4 | hub spec `009` R6 の L2–L4 確認結果を受領し、ledger の行を削除せず status を更新する | ハブ → sandbox |
| 5 | 月次 refresh で LiteLLM OpenAI 3 metadata と cp315 blocker を §1.2 の手順で再確認する | sandbox |

---

## 5. Root baseline run

本リポジトリ（Python beta-verification lane）側で Root baseline を上げた際の実行証拠を 1 行ずつ記録する
（憲法 Principle 6）。ハブへはこの表の行を evidence として intake 手順経由で渡す。

| 日付 | Python | 主な resolved versions | `uv lock` | `uv sync` | `mise run check` | `mise run cov` | `uv run pip-audit` | `mise run patterns:check` |
|---|---|---|---|---|---|---|---|---|
| 2026-10-04 | 3.14（3.14.5 interpreter / mise 3.14.8 tool） | `ibm-watsonx-ai` 1.8.0+ 系（ModelInference import 済み green、ADR-1 再測定）、`pydantic-ai-slim` 2.31.1、`pydantic-core` 2.46.5 | 変更なし（既存 lock を再利用、`uv sync` のみ実施） | exit 0（`uv sync --all-groups`） | exit 0（lint/format/typecheck/test: 323 passed, 4 skipped） | exit 0（98.51% ≥ 98% ratchet） | exit 0（No known vulnerabilities found） | exit 0（deep-research 3.13.7 / hitl 3.14.5 / rate-limit 3.15.0rc2、各レーン green、root 変更の影響なし） |
| 2026-10-04（spec 014 task 2.2, option (c)） | 3.14（3.14.5 interpreter / mise 3.14.8 tool） | `pydantic-ai-slim` 2.31.1→2.54.0（hub-verified floor、`afbe6eb`/2026-10-03 確認）、`openai` を `pydantic-ai-slim[openai]` extra 経由から root 直接依存 `>=2.47.0,<3.0.0`（当初は `>=2.20.0,<3.0.0` としたが、独立 VDD review を契機に httpx2 対応下限へ訂正——下記参照）へ変更（resolve 後 2.54.0、変化なし）、`litellm` 1.103.2（resolve 結果は変化なし。ただし 3rd pass VDD review を契機に `litellm>=1.96.2` という明示的な version floor を `[project.optional-dependencies] litellm` と `[dependency-groups] dev` の両方に追加——root `openai` 下限だけでは litellm 1.83.0 の rollback を拒否できない（1.83.0 は `openai>=2.8.0` を無上限で宣言し、訂正後の root range 内でも trivially 満たされてしまう）ため、`tests/unit/test_litellm_dependency_floor.py` で manifest 宣言・installed 版の両方を contract 化した）。副次発見: この floor から `OpenAICompatibleProvider`（Ollama 含む）が既定で `httpx2.AsyncClient` を使うようになり、`respx` では mock できないため `tests/unit/test_ollama_openai_compat.py` の request-path テストを `httpx2.MockTransport` へ移行（`respx` dev 依存は task 2.1 の respx 版が唯一の消費者で、task 2.2 の書き換えでゼロになった——削除はせず pyproject.toml にコメントで記録）。**訂正（2026-10-04、独立 VDD review）**: 当初 `openai>=2.20.0,<3.0.0` を宣言したが、`openai` が `httpx2.AsyncClient` を `http_client=` として受理できるのは `2.47.0` 以降のみ（2.46.0 以前は provider 構築時に `TypeError`、連番 venv install で実測確認）。litellm の一部 patch release（1.83.2→`openai==2.30.0`、1.83.14→`openai==2.24.0`、いずれも PyPI JSON API で確認）はこの安全下限より古い openai を exact pin しており、当初の下限ではこれらへの resolve を防げなかった。`>=2.47.0,<3.0.0` へ訂正し、`test_installed_openai_sdk_meets_httpx2_transport_floor` を追加（PROVE evidence 済み）。`httpx2` は dev 依存として明示宣言（test が直接 import するため、PyYAML と同じ理由）。 | 変更あり（`mise exec -- uv lock`: Resolved 138 packages、pydantic-ai-slim/pydantic-graph を 2.31.1→2.54.0 に更新。`httpx2`/`httpcore2` 2.13.1 は本 task 以前から既に lock に存在——`genai-prices` 経由——していたことを `git show HEAD:uv.lock` で確認済み。新規に resolve されたのではなく、`pydantic-ai-slim` の provider 実装が既存の httpx2 を実際に使い始めた。`litellm>=1.96.2` floor 追加後も resolve 結果は 1.103.2 のまま不変） | exit 0（`uv sync --all-groups --all-extras`: 3 packages 入れ替え。openai floor 訂正後の再 sync でも resolve 結果は不変） | exit 0（lint/format/typecheck/test: 328 passed, 4 skipped → `litellm>=1.96.2` floor の contract test（`tests/unit/test_litellm_dependency_floor.py`、3 件）追加後、最終的に **332 passed, 4 skipped**） | exit 0（98.51% ≥ 98% ratchet） | exit 0（No known vulnerabilities found） | exit 0（deep-research（68 passed, 1 skipped, coverage 100%） / hitl（73 passed, 2 skipped, coverage 100%） / rate-limit（27 passed, 3 skipped, coverage 100%）各レーン green、root 変更の影響なし） |

---

## 6. Immutable hub commit verification（Python 3.14）

artifact は一時的な参照物であり正本ではない。以下は
`/private/tmp/spec014-hub-3646b47-py314-20261004-v3` の `summary.md` 冒頭と
`migration.diff` を本 ledger へ転記したもの。artifact path は再確認の便宜だけに記す。

### 6.1 Ledger essentials

- **実行日**: 2026-10-04
- **Hub commit**: `3646b473db41d853380d7088bf381f1f6ce1e08c`
- **Python**: 3.14（実 interpreter 3.14.5）
- **Overall verdict**: `failed`
- **Hub dependency-policy §8.1**: **not satisfied**
- **Resolved versions**: 204 packages。主要版は `pydantic-ai-slim==2.52.0`、`pydantic-core==2.46.5`、
  `litellm==1.103.1`、`openai==2.54.0`、`chromadb==0.6.3`、`llama-index-workflows==2.25.0`、
  `onnxruntime==1.30.0`、`torch==2.14.0`、`starlette==1.7.0`、`redis==8.1.0`。
- **Commands**: `uv lock` exit 0; `uv sync` exit 0; `mise run api:check` exit 1;
  diagnostic `api:lint` exit 1; diagnostic `api:test:ci` exit 1; diagnostic `api:audit` exit 0。
- **Test diagnostic**: 1624 total / 1542 passed / 58 failed / 24 skipped / 0 errors、coverage 92.94%（下限 80%）。
- **Skip reasons**: Chroma model download 6、Docker daemon unavailable 7、Redis unavailable 9、Ollama live 1、
  optional `LOGFIRE_TOKEN` empty 1。これらは skip として記録し、service を自動 provision していない。
- **Audit**: `No known vulnerabilities found, 4 ignored`。ignore は hub 自身の `api:audit` policy による。
- **Required failure**: `api:check` は Python 3.14 Ruff `UP037` 4 件で停止した
  （`app/workflows/exceptions.py` 2 件、`tests/benchmarks/utils.py` 1 件、
  `tests/unit/api/v1/test_stream_lifecycle.py` 1 件）。そのため typecheck / pytest / audit は required gate 内では未到達。
- **Test failure blocker**: diagnostic pytest は warning-as-error により
  `asyncio.iscoroutinefunction` の `DeprecationWarning` で 58 件失敗。origin は主に
  `workflows/runtime/types/step_function.py:227`（`llama-index-workflows`）と
  `chromadb/telemetry/opentelemetry/__init__.py:128`。
- **再実行条件**: Ruff 4 件を Python 3.14 形式へ直し、上記 2 dependency path の
  `asyncio.iscoroutinefunction` 呼び出しを対応版へ更新した immutable hub commit を作る。その commit に対して
  `uv lock` / `uv sync` / `api:check` の全てが exit 0 になるまで H3 は `proposed` のままにする。

### 6.2 Warning observations

| Trap / warning | Python 3.14 observation | origin / reason |
|---|---|---|
| §2.3 trap 2: `TestClient` → `StarletteDeprecationWarning` | **発火しない** | diagnostic log に category / `testclient.py` occurrence なし。resolved `starlette==1.7.0` / `httpx2==2.13.1` の test path で未観測 |
| §2.3 trap 3: redis-py `asyncio.iscoroutinefunction` | **発火しない（経路未通過）** | Redis live tests 9 件は service unavailable で skip。`limits` は `redis_connect_func` を渡さず、log に `redis/.../connection.py` origin なし |
| additional blocker: `asyncio.iscoroutinefunction` | **発火して test failure** | `llama-index-workflows` step wrapper と Chroma telemetry が warning-as-error に抵触。58 failures の主因 |
| non-deprecation warnings | 7 warnings | `LogfireNotConfiguredWarning` 5、`PytestUnknownMarkWarning` 1、file-size policy `UserWarning` 1 |

### 6.3 Migration diff（転記）

```diff
--- a/services/api/.python-version
+++ b/services/api/.python-version
@@ -1 +1 @@
-3.13
+3.14
--- a/services/api/pyproject.toml
+++ b/services/api/pyproject.toml
@@ -3,7 +3,7 @@
 readme = "README.md"
-requires-python = ">=3.13"
+requires-python = ">=3.14"
@@ -105,7 +105,7 @@
 [tool.ruff]
 line-length = 100
-target-version = "py313"
+target-version = "py314"
--- a/services/api/tests/unit/test_python_version_pin.py
+++ b/services/api/tests/unit/test_python_version_pin.py
@@ -36,7 +36,7 @@
 PYPROJECT = _REPO_ROOT / "pyproject.toml"

-_EXPECTED_SERIES = "3.13"
+_EXPECTED_SERIES = "3.14"
```

### 6.4 Python 3.15 follow-up

§1.1 の 3 blocker が必要 platform の `cp315` wheel-ready になった時点で、同じ runner を
`--python 3.15` にして反復する。3.14 が failed の間に 3.15 を成功扱いへ飛び越えず、各 series の
required phases と blocker を別 record として残す。

---

## 7. Re-verification on hub `afbe6eb` and a candidate fix（Python 3.14、2026-10-04）

§6 と同じ runner（PR #44 の `scripts/verify-hub-python.sh`）を、§6 以後に進んだ hub `main` と、
§6 の 2 blocker だけを直した候補 commit に対して実行した。artifact は一時物で、要点だけをここへ転記する。

- **環境**: Linux x86_64、CPython 3.14.8（uv 管理）、uv 0.12.23（hub `mise.toml` の `uv = "0.12"`）、mise 2026.10.1。
  Redis / Docker daemon / Ollama / Hugging Face model は無く、該当 test は §6 と同じ理由で skip した（25 件）。
- **migration**: runner の scratch migration は §6.3 と同じ 4 行（`.python-version`、`requires-python`、Ruff target、
  `_EXPECTED_SERIES`）。

### 7.1 hub `main`@`afbe6eb`（依存更新 #77、spec 009 #78 の後）— failed、§6 と同じ

| stage | role | exit | 結果 |
|---|---|---:|---|
| `uv lock` | required | 0 | 204 packages |
| `uv sync` | required | 0 | |
| `mise run api:check` | required | 1 | Ruff `UP037` 4 件（§6.1 と同じ 4 箇所） |
| `mise run api:lint` | diagnostic | 1 | 同上 |
| `mise run api:test:ci` | diagnostic | 1 | 1624 total / 1541 passed / **58 failed** / 25 skipped。58 件すべてが `asyncio.iscoroutinefunction` の `DeprecationWarning`（warning-as-error） |
| `mise run api:audit` | diagnostic | 0 | No known vulnerabilities found, 4 ignored |

#77 の依存更新は 2 blocker のどちらも解消していない。PyPI の最新版でも未解消である（2026-10-04 確認）。

- `llama-index-workflows` 2.25.0 は最新版で、`workflows/runtime/types/step_function.py:227` と `:286` が
  `asyncio.iscoroutinefunction` を呼ぶ。
- `chromadb` は hub の `<1.0` 上限で 0.6.3 に固定され、`chromadb/telemetry/opentelemetry/__init__.py:128` が同じ呼び出しをする。
  0.x 系に修正版は無い。

Python 3.14 の `asyncio.iscoroutinefunction` は `warnings._deprecated(..., remove=(3, 16))` を `stacklevel=3` で出すため、
warning は呼び出し元モジュールに帰属する。したがって pytest の `module` 欄で emitter を限定できる。

### 7.2 候補 commit `966becc`（hub branch `claude/project-thread-583dhe`）— green、§8.1 satisfied

| stage | role | exit | 結果 |
|---|---|---:|---|
| `uv lock` | required | 0 | 204 packages、§7.1 と同じ解決結果 |
| `uv sync` | required | 0 | |
| `mise run api:check` | required | 0 | ruff / ty green、1624 total / **1599 passed / 0 failed** / 25 skipped、coverage 96.68%、audit green |
| `mise run api:lint` | diagnostic | 0 | |
| `mise run api:test:ci` | diagnostic | 0 | 1599 passed / 0 failed / 25 skipped |
| `mise run api:audit` | diagnostic | 0 | No known vulnerabilities found, 4 ignored |

- **Overall verdict**: green。**Hub dependency-policy §8.1（Python 3.14）: satisfied**（この候補 commit に対して）。
- **3.13 での回帰確認**: 同じ commit を migration なしの Python 3.13.14 で実行し、ruff / ty green、
  1599 passed / 25 skipped、coverage 96.73%。候補の修正は 3.13 では何も変えない。
- **主な resolved versions**: `pydantic-ai-slim==2.54.0`、`pydantic-core==2.46.5`、`litellm==1.103.2`、`openai==2.54.0`、
  `fastapi==0.142.2`、`starlette==1.7.0`、`chromadb==0.6.3`、`llama-index-core==0.14.25`、`llama-index-workflows==2.25.0`、
  `onnxruntime==1.30.0`、`torch==2.14.1`、`redis==8.1.0`、`ruff==0.16.10`、`ty==0.0.84`。
- **残る warning（7 件、いずれも DeprecationWarning ではない）**: `LogfireNotConfiguredWarning` 5、
  `PytestUnknownMarkWarning`（`pytest.mark.integration`）1、file-size policy の `UserWarning` 1。§6.2 と同じ内訳。
- §2.3 の罠 2・3 は §6.2 と同じく発火しない（Redis live test は未到達）。

### 7.3 候補の修正内容（hub `966becc`、4 files、+21 / −4）

1. **`UP037` 4 件**: `app/workflows/exceptions.py`（`RAGTransientError` / `RAGPermanentError` の `from_exception`）、
   `tests/benchmarks/utils.py`（`BenchmarkResults.from_latencies`）、`tests/unit/api/v1/test_stream_lifecycle.py`
   （`_TrackingAsyncGen.__aiter__`）の、自クラスを指す引用符付き戻り値型を `typing.Self` にした。
   Ruff の自動修正どおり引用符を外すだけでは、3.13 ではクラス定義中の名前解決で `NameError` になる（PEP 649 は 3.14 から）。
   `Self` なら 3.13 と 3.14 の両方で正しく、版上げ PR より先に入れられる。
2. **`asyncio.iscoroutinefunction` の 58 failures**: `services/api/pyproject.toml` の `filterwarnings` に、
   メッセージと emitter モジュールの両方で限定した ignore を 2 件足した。
   ```toml
   "ignore:'asyncio.iscoroutinefunction' is deprecated:DeprecationWarning:workflows.runtime.types.step_function",
   "ignore:'asyncio.iscoroutinefunction' is deprecated:DeprecationWarning:chromadb.telemetry.opentelemetry",
   ```
   既存の `ignore::DeprecationWarning:chromadb.types` と同じく emitter を名指しする形で、同じモジュールが出す別の
   deprecation と、他のモジュールが出す同じ deprecation はどちらも引き続き error になる。3.13 はこの warning を出さないので
   無害。`llama-index-workflows` が `inspect.iscoroutinefunction` へ移った版を出した時点で 1 件目を、
   `chromadb<1.0` の上限を外す時点で 2 件目を外す。

### 7.4 H3 の扱い

ledger の規則（§1、immutable hub commit に対する検証だけを根拠にする）に従い、H3 は `proposed` のままにする。
`966becc` は hub の push 済み branch 上の commit で再現はできるが、hub `main` ではない。§4 の 1 が hub `main` に入った後、
その commit で §7.2 と同じ結果になれば `verified` へ移す。
