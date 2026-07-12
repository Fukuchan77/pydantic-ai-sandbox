# 013-agentic-ai-security — PDCA Do Phase

## Implementation Log

### [2026-07-12 10:05] Task 1 (SessionLifecycle) Started

- Objective: `patterns/hitl/src/patterns_hitl/store.py` に消費セマンティクスの
  状態機械(`pending → in_flight → consumed`)と `new_session_id()` 一元化を追加
  (R1.1, R1.2, R1.3, R2.1, R2.2, R2.3)。
- Approach: plan.md SessionLifecycle / research.md AD-1・AD-2 の仕様に従い、
  TDD(RED → GREEN)で `test_session_hygiene.py` / `test_consumption.py`(store 層)
  を先行作成してから `store.py` を拡張する。

### [2026-07-12 10:10] RED confirmed

- `uv run pytest tests/unit/test_session_hygiene.py tests/unit/test_consumption.py`
  → 2 件の収集エラー(`ImportError: cannot import name 'new_session_id'` /
  `'UnknownSessionError'` from `patterns_hitl.store`)。既存 `store.py` にこれらの
  シンボルが存在しないため確実に赤であることを確認。

### [2026-07-12 10:25] GREEN — store.py 拡張

- Status: `SessionRecord` に `state: Literal["pending","in_flight","consumed"]`
  (default `"pending"`)と `pending_call_ids: frozenset[str]`(default 空)を追加。
  モジュール関数 `new_session_id()` に `uuid4()` 生成を一元化。`UnknownSessionError`
  (区別情報を持たない例外)、`claim()`(`pending` のときのみ成功し同期的に
  `in_flight` へ遷移。未知/`in_flight`/`consumed` はいずれも同一の
  `UnknownSessionError`)、`settle_pending()`(`in_flight → pending`、
  `pending_call_ids` を丸ごと置換)、`consume()`(`→ consumed`)、
  `release()`(`in_flight → pending` 復元、409 用)を実装。既存 `create()` /
  `get()` / `update()` は 012 互換のまま(署名互換の `pending_call_ids` 任意引数を
  `create()` に追加)。
- 11/11 新規テスト green(`test_session_hygiene.py` 3件、`test_consumption.py` 8件)。

### [2026-07-12 10:32] ❌ Error Encountered — coverage ratchet + pyright strict

**Error**:
1. `mise run patterns:check` → `patterns:test` で hitl lane の coverage が
   97.64%(`fail_under = 98`)で red。`store.py` の未到達行 190/206/224 =
   `settle_pending` / `consume` / `release` の「未知 id → `UnknownSessionError`」
   防御チェック(未テスト分岐)。
2. `patterns:typecheck` → `store.py:71`
   `reportUnknownVariableType`(`pending_call_ids` の型が部分的に unknown)。

**Context**: `SessionRecord.pending_call_ids` のデフォルトを
`field(default_factory=frozenset)` としていた。また `settle_pending()` /
`consume()` / `release()` に `if record is None: raise UnknownSessionError` の
防御チェックを入れていたが、これらは呼び出し契約上「直前の `claim()` が
解決済みの id でのみ呼ばれる」内部専用メソッドであり、plan.md の
Public interface にも未知 id 時の挙動は明記されていない(`claim()` のみが
存在秘匿の統一エラーを持つ)。

**Root Cause Investigation**:

1. **Codebase Search**: CLAUDE.md の Behavioral defaults
   ("Don't add error handling... for scenarios that can't happen. Trust
   internal code and framework guarantees.") に反する防御コードだった —
   `settle_pending` / `consume` / `release` は 012/013 のどのテストからも
   未知 id で呼ばれる契約がなく、到達不能分岐がカバレッジ比を落としていた。
2. **Hypothesis**: (a) `field(default_factory=frozenset)` は `frozenset`(無
   パラメータのクラス)をファクトリとして渡しており、pyright は戻り値型を
   `frozenset[Unknown]` と推論する。フィールドの型アノテーション
   `frozenset[str]` との突き合わせが起きず unknown 型が伝播した。
   (b) 未使用の防御分岐がカバレッジ比を下げていた。

**Solution Design**:

- Approach: (1) `pending_call_ids: frozenset[str] = frozenset()` を
  `field(default_factory=...)` なしの直接デフォルトに変更(`frozenset` は
  不変・hashable なので dataclass のミュータブルデフォルト禁則に当たらず、
  アノテーションによる双方向推論で `frozenset[str]` に確定する)。
  (2) `consume()` / `release()` は `replace(self._records[session_id], ...)`
  へ変更し、辞書アクセス自体が持つ自然な `KeyError` に委譲(明示的な
  `if None: raise` 分岐を削除)。(3) `settle_pending()` は既存レコードを
  読まずに丸ごと書き換えるため、防御チェックなしで契約通り「未知 id なら
  素通りで新規作成」と明記する docstring に変更。
- Rationale: 呼び出し元(Task 2 の app.py)は `claim()` 成功後の id しか
  渡さない契約であり、テストで踏めない分岐を残さないことがカバレッジ
  比の健全性と CLAUDE.md の最小実装方針の両方に合致する。

**Execution**: 上記 3 点を `store.py` に適用。

**Result**: ✅ Success —
`mise run patterns:check` 全レーン green(hitl coverage 100%、typecheck
0 errors)。

**Learning**: 「同一の `UnknownSessionError`」という要件(R1.2)は
`claim()` という単一のエントリポイントに閉じている。他の内部遷移メソッド
まで同じ防御を機械的に複製すると、契約上到達し得ない分岐がカバレッジ
比を下げる。呼び出し契約が「既に検証済みの id のみ渡される」内部専用
メソッドには、防御チェックを追加する前にテスト対象になり得るかを先に
確認する。

## Trial and Error Summary

| Attempt | Approach | Result | Learning |
| --- | --- | --- | --- |
| 1 | `settle_pending`/`consume`/`release` に `claim()` と同様の `if None: raise UnknownSessionError` を複製 | ❌ coverage ratchet 割れ(未テスト分岐)+ pyright `reportUnknownVariableType`(`field(default_factory=frozenset)`) | 契約上到達不能な防御は複製しない。dataclass の frozenset デフォルトは `field(default_factory=...)` でなく直接値で型推論を効かせる |
| 2 | 防御チェック削除 + `replace(self._records[session_id], ...)` による自然な `KeyError` 委譲、`frozenset()` 直接デフォルト | ✅ Success — hitl coverage 100%、typecheck 0 errors | 内部専用メソッドは呼び出し契約を信頼し、テストで踏める分岐だけを残す |

## Learnings

- R1.2(存在秘匿・統一エラー)の実装範囲は `claim()` のみ — 状態機械の他の
  遷移メソッドに同じ防御を機械的に複製すると未達コードになる。
- `dataclass(frozen=True)` の不変コレクション(`frozenset`)デフォルトは
  `field(default_factory=...)` より直接値の方が pyright strict と相性が良い
  (アノテーションからの双方向型推論が効く)。
- 既存 012 テスト(`test_store.py` など)は `SessionRecord` の新規フィールドに
  デフォルト値を与えたことで無改修のまま green を維持できた —
  純加算の設計が後方互換性を保つことを実測で確認。

## Verification Gate Evidence

```
$ cd patterns/hitl && uv run pytest --cov
...
tests/unit/test_consumption.py ........                                  [ 48%]
tests/unit/test_session_hygiene.py ...                                   [ 67%]
...
Name                                 Stmts   Miss Branch BrPart  Cover
src/patterns_hitl/store.py              41      0      4      0   100%
TOTAL                                  214      0     26      0   100%
Required test coverage of 98.0% reached. Total coverage: 100.00%
======================== 41 passed, 2 skipped in 0.77s =========================

$ mise run patterns:check
... (全レーン)
[patterns:typecheck] == typecheck patterns/hitl
[patterns:typecheck] 0 errors, 0 warnings, 0 informations
Finished in 20.20s   # exit code 0
```

---

### [2026-07-12 11:10] Task 2 (ConsumptionGuard: /run・/resume の HTTP 写像) Started

- Objective: `app.py` の `/run`・`/resume` 両ハンドラへ research.md AD-2 の写像表を実装する
  (`UnknownSessionError` → 404、pending 外判断 → 409、`HitlBudgetExceededError` →
  429、再 defer → 200 + `settle_pending()`)。既存違反(`/resume` 404 本文の
  session id 漏洩、両経路で未捕捉の予算超過)を是正する(R1.2, R2.1–2.4)。
- Approach: `test_consumption.py`(Task 1 が作成した store 層テストと同一ファイル)
  へ API 層(`TestClient`)のケース (a)–(e) を先行追加 → 赤確認 → `app.py` +
  `harness.py` を実装 → 緑化。

### [2026-07-12 11:20] RED confirmed

- `uv run pytest tests/unit/test_consumption.py -v --no-cov` → 新規 8 件が
  すべて失敗(既存 8 件の store 層テストは無傷で green)。失敗理由を個別に確認:
  - (a)/未知 id 共通: `AssertionError: 'does-not-exist' not in 'unknown session_id: does-not-exist'`
    — 現行 `app.py:202` の漏洩本文がそのまま検出された。
  - (b) 系 3 件: `pydantic_ai.exceptions.UserError: Tool call results need to
    be provided for all deferred tool calls. Expected: {...}, got: {...}`
    — pending 外の `tool_call_id` を含む decisions がノーチェックで
    `harness.resume()` まで到達し、pydantic-ai 自身が(409 ではなく)
    ハンドルされない `UserError` を投げていた。
  - (c)/(d): `TypeError: create_app() got an unexpected keyword argument
    'usage_limits'` — 予算超過を再現する注入シームが存在しなかった。
  - (e): (b) と同じ `UserError`(pending 集合チェックが無いため)。
  - 8 failed, 8 passed — 意図した理由での赤を確認。

### [2026-07-12 11:35] GREEN — harness.py + app.py 実装

- `harness.py`: `start()` が `store.create(..., pending_call_ids=...)` で
  最初の pending 集合を正しく登録するよう修正(従来は空集合のまま作成しており、
  作成直後の 409 判定が機能しない欠落があった)。`resume()` は
  `store.update()`(012 互換の全上書きメソッド、状態遷移を知らない)の呼び出しを
  廃止し、結果が `PendingResult` なら `settle_pending()`(pending 集合を新ラウンドの
  ものへ置換)、`TerminalResult` なら `consume()` を呼ぶよう変更。
  `UsageLimitExceeded` 捕捉時は再送前に `consume()` して session を失効させる
  (R2.4)。`store.update()` 自体は 012 の `test_store.py` が直接カバーしているため
  未使用化による到達不能コードにはならない。
- `app.py`: `create_app` に `usage_limits: UsageLimits = LIMITS` の注入シームを
  追加。`/run`・`/resume` の実処理を module-level の `_handle_run` /
  `_handle_resume` へ抽出(理由は下記 Error Encountered 参照)。
  `_handle_resume` は `store.claim()` → `UnknownSessionError` を 404
  (固定文言 `_UNKNOWN_SESSION_DETAIL`)、`claim()` 後・`await harness.resume()` 前に
  `decisions.keys() <= record.pending_call_ids` を検査し不整合なら
  `store.release()` + 409(固定文言、id/理由を含まない)、`harness.resume()` の
  `HitlBudgetExceededError` を 429 にマップする。`_handle_run` も同じ
  `HitlBudgetExceededError` → 429 マッピングを持つ(`/run` は失敗時に session を
  一度も作らないため、409 相当のクリーンアップは不要)。
- 16/16 `test_consumption.py`(既存 8 + 新規 8)green。lane 全体
  (`test_api.py` / `test_stop_approve_resume.py` / `test_store.py` 含む)も
  無傷(49 passed, 2 skipped integration)。

### [2026-07-12 11:40] ❌ Error Encountered — ruff C901(complexity)+ format

**Error**:
1. `mise run patterns:check` → `patterns:lint`: `C901 create_app is too
   complex (11 > 10)`(`app.py:165`)。
2. `patterns:format`: `Would reformat: tests/unit/test_consumption.py`
   その後 `src/patterns_hitl/app.py` も同様。

**Context**: `/run`・`/resume` の分岐(try/except × 2、409 判定の if、
`isinstance` 分岐)を `create_app` 内のネストした `@app.post` ハンドラに直接
書いたため、ハンドラの分岐が `create_app` 自体の循環的複雑度に加算された。

**Root Cause Investigation**:

1. **Codebase Search**: ruff の mccabe (`C901`) は関数定義本体に現れる
   ネスト関数の分岐も外側関数のノードグラフの一部として数える。
   `create_app` は元々 `store or SessionStore()` 等の分岐を持っていたところに
   Task 2 で 2 系統×複数分岐を追加したため閾値 10 を超えた。
2. **Hypothesis**: ハンドラの実処理を module-level 関数へ抽出すれば、
   `@app.post` に登録するネスト関数は「引数を渡して呼ぶだけ」の 1 分岐に
   縮み、`create_app` 自身の複雑度は元の水準に戻る。抽出先の
   `_handle_run` / `_handle_resume` はそれぞれ独立した関数として
   複雑度が再計算されるため、個々に閾値を超えない(実測: 超えなかった)。

**Solution Design**:

- Approach: `_handle_run(harness, body)` / `_handle_resume(harness, store,
  body)` を module scope に抽出し、`create_app` 内の `@app.post` ハンドラは
  それぞれ 1 行で委譲するだけにした。フォーマット崩れは
  `uv run ruff format <file>`(mise に fix 系タスクが無いため CLAUDE.md の
  ツール優先順位どおり `uv run` へフォールバック)で解消。
- Rationale: 責務(HTTP 委譲 vs ステータス写像ロジック)の分離は
  plan.md の「ConsumptionGuard は app.py の拡張」という記述とも整合し、
  かつテスト(`test_consumption.py`)からは `create_app()` 経由の
  `TestClient` しか触っていないため、内部構造の変更はテストに影響しない。

**Execution**: 上記 2 点を適用。

**Result**: ✅ Success — `mise run patterns:check` 全レーン green
(hitl coverage 100%、typecheck 0 errors、exit code 0)。

**Learning**: ネストした FastAPI ハンドラに複数の HTTP ステータス分岐を
直接書くと、囲む factory 関数(`create_app`)の複雑度に累積する。
分岐が増える段階で、ハンドラ本体を module-level 関数へ抽出し、
`@app.post` 直下は委譲 1 行に留めるのが ruff `C90` ポリシーと相性が良い。

## Verification Gate Evidence (Task 2)

```
$ cd patterns/hitl && uv run pytest tests/unit/test_consumption.py -v --no-cov
...
tests/unit/test_resume_after_terminal_completion_returns_404_and_leaks_nothing PASSED
tests/unit/test_resume_with_unknown_session_id_returns_the_same_404_body_as_consumed PASSED
tests/unit/test_resume_with_decision_outside_pending_set_returns_409_and_runs_no_tool PASSED
tests/unit/test_resume_with_one_bad_key_among_valid_ones_rejects_the_whole_request PASSED
tests/unit/test_resume_after_409_leaves_the_session_pending_and_resumable PASSED
tests/unit/test_resume_over_budget_returns_429_and_invalidates_the_session PASSED
tests/unit/test_run_over_budget_returns_429_and_saves_no_session PASSED
tests/unit/test_resume_after_re_defer_rejects_the_stale_tool_call_id_with_409 PASSED
============================== 16 passed in 0.23s ==============================

$ uv run pytest --no-cov   # lane 全体
...
======================== 49 passed, 2 skipped in 0.82s =========================

$ cd /Users/Shared/codes/pydantic-ai-sandbox && mise run patterns:check
... (全レーン)
[patterns:test] src/patterns_hitl/app.py                91      0     16      0   100%
[patterns:test] src/patterns_hitl/harness.py            54      0      6      0   100%
[patterns:test] TOTAL                                  240      0     32      0   100%
[patterns:test] Required test coverage of 98.0% reached. Total coverage: 100.00%
[patterns:test] ======================== 49 passed, 2 skipped in 1.03s =========================
[patterns:typecheck] == typecheck patterns/hitl
[patterns:typecheck] 0 errors, 0 warnings, 0 informations
Finished in 25.67s   # exit code 0
```
