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

---

### [2026-07-12 13:15] Task 3 (AuditTrail: `audit.py` 新設 + 注入シーム) Started

- Objective: `/resume` の承認判断ごとに 1 件の構造化監査イベントを記録する
  `audit.py` を新設し、`create_app(audit_emitter=...)` の注入シームで既定
  `LogfireAuditEmitter`(fail-soft)へ配線する(R3.1–3.5)。
- Approach: TDD で `test_audit_trail.py` + `tests/support/in_memory_audit.py`
  (`InMemoryAuditEmitter` / `RaisingAuditEmitter`)を先行作成 → 赤確認 →
  `audit.py` 実装 + `app.py` 配線 → 緑化。

### [2026-07-12 13:25] RED confirmed

- `uv run pytest tests/unit/test_audit_trail.py --no-cov`
  → 収集エラー: `ModuleNotFoundError: No module named 'patterns_hitl.audit'`
  (`test_audit_trail.py:27` の `from patterns_hitl.audit import build_audit_event`)。
  `audit.py` が存在しないため確実に赤であることを確認。

### [2026-07-12 13:40] GREEN — audit.py 実装 + app.py 配線

- `audit.py`(新規): `AuditEvent`(`session_id` / `tool_call_id` / `tool_name` /
  `decision: Literal["approved","approved_with_override","denied"]` /
  `denial_message` / `overridden_keys: tuple[str, ...]` / `timestamp` —
  引数の生値フィールドを持たない、R3.2/3.3)、`AuditEmitter` Protocol、
  `LogfireAuditEmitter`(`logfire.info(...)`)、`build_audit_event(...)`
  (Decision の生の `approved`/`override_args`/`denial_message` から
  `AuditEvent` を組み立てる純関数 — override 時は `overridden_keys` のみ
  記録し値は捨てる)、`emit_audit_event(emitter, event)`(fail-soft 境界を
  1 箇所に集約 — `contextlib.suppress(Exception)`、R3.4)。
- `app.py`: `create_app` に `audit_emitter: AuditEmitter | None = None`
  (既定 `LogfireAuditEmitter()`)を追加。`_handle_resume` へ
  `_tool_names_by_call_id(record.history, ...)`(`claim()` 直後の履歴に
  残る直前ラウンドの `ToolCallPart` を走査して `tool_call_id → tool_name`
  を再構築 — `SessionRecord` の契約を広げず app.py 内で閉じる)を追加し、
  409 判定通過後・`await harness.resume()` 呼出前に decisions 全件へ
  `build_audit_event` + `emit_audit_event` を適用する(「判断適用点」= 実際の
  ツール実行結果を待たず、資格のある decisions が確定した時点)。
- `tests/support/in_memory_audit.py`(新規): `InMemoryAuditEmitter`
  (イベントをリストに蓄積)、`RaisingAuditEmitter`(常に例外を投げ、
  fail-soft 境界を検証する)。
- 5/5 `test_audit_trail.py` green: (a)/(b) approve/deny 各 1 件 ×
  必須フィールド、(c) override は `overridden_keys` のみで生値が
  シリアライズに現れない(HTTP 経由 + `build_audit_event` 直接呼び出しの
  両方で検証)、(d) 例外を投げる emitter でも `/resume` は 200 で完了。

### [2026-07-12 13:45] ❌ Error Encountered — テスト自体の誤検知(タイムスタンプ衝突)

**Error**: `test_override_decision_records_only_the_overridden_keys` が
`assert "5.0" not in serialized` で失敗。

**Context**: override 値に `amount_usd=5.0` を使ったところ、
`AuditEvent.timestamp` の ISO8601 マイクロ秒表記(例:
`...05.072940Z`)に偶然 `"5.0"` という部分文字列が含まれ、
実装の漏洩ではなく**テストのアサーションが自分自身のタイムスタンプに
誤って一致した**ことが原因。

**Root Cause Investigation**: 実装側 (`build_audit_event`) は
`overridden_keys` のみを記録し、`override_args` の値そのものは
どのフィールドにも渡していない(コードレビューで確認)。したがって
漏洩は実装ではなく、テストが選んだ数値リテラルが時刻表現と衝突した
テスト設計の問題。

**Solution Design**: 衝突しにくい値(`12345.0` / `98765.0` と
`"confidential-override-reason"` などの長い一意な文字列)へ置き換え、
タイムスタンプの数字表現と偶然一致しないようにした。

**Execution**: `test_audit_trail.py` の 2 箇所(HTTP 経由テストと
`build_audit_event` 直接呼び出しテスト)の override 値を置き換え。

**Result**: ✅ Success — 5/5 green。

**Learning**: 「シリアライズに値が現れない」ことを文字列包含で検証する
テストは、他のフィールド(特にタイムスタンプの数字表現)との偶然の
部分文字列一致に弱い。検証用の値は十分にユニークで短い数字の並びを
避けるべき。

### [2026-07-12 13:55] ❌ Error Encountered — ruff SIM105/S110 + I001、pyright missing annotation

**Error**:
1. `patterns:lint`: `audit.py` の `try: emitter.emit(event) / except
   Exception: pass` に `SIM105`(`contextlib.suppress` を使うべき)と
   `S110`(try-except-pass はログを検討)。
2. `patterns:lint`: `test_audit_trail.py` の 1 行にまとめた
   `from tests.support.function_model_scripts import (...)` が `I001`
   (import 未整形)。
3. `patterns:typecheck`: `test_audit_trail.py` の `_build_app(*phases,
   audit_emitter=...)` の `*phases` に型注釈が無く
   `reportMissingParameterType` / `reportUnknownParameterType` /
   `reportUnknownArgumentType`。
4. `patterns:format`: `app.py` の未整形(import 並び変更後の再フォーマット)。

**Context**: fail-soft 境界を素朴な `try/except Exception: pass` で書き、
かつ長い import 文を 1 行にまとめ、既存テストの `*phases` 引数の
型注釈省略パターンをそのまま模倣した結果。

**Root Cause Investigation**: (1) は 012 の `observability.py` が
`except Exception:  # noqa: BLE001` という個別 justify 済みパターンを
使っていたのに対し、013 では ruff がより新しい `SIM105` 提案
(`contextlib.suppress`)を追加要求していた。(2) は `ruff format`/`isort`
の折返しルールに合わせていなかった。(3) は他の `*phases` 呼び出し
(`test_consumption.py` 等)は同じ関数 `call_counting_script` を呼ぶが、
pyright が `ToolCallPart` への逆伝播を要求する組み合わせで、
本テストファイルでは型注釈を明示しないと unknown 型が伝播した。

**Solution Design**: (1) `contextlib.suppress(Exception)` へ書き換え
(justify コメントは docstring 側に「フェイルソフト境界」として明記し、
`noqa` は不要と確認)。(2) 複数行の import へ整形
(`ruff format` に委譲)。(3) `_build_app(*phases: ToolCallPart, ...)`
と明示。(4) `uv run ruff format .` を実行。

**Execution**: 上記を適用し再実行。

**Result**: ✅ Success — `ruff check` / `ruff format --check` /
`pyright` すべて 0 件。

**Learning**: fail-soft な `try/except pass` は 012 の個別 `noqa`
パターンより `contextlib.suppress` の方が ruff の新しい提案
(`SIM105`)と衝突しない。テストヘルパーの `*phases` パラメータは
呼び出し元の型が pyright strict の推論境界を超える場合、明示注釈が
必要になることがある(委譲元と同じ書き方でも常に安全ではない)。

## Verification Gate Evidence (Task 3)

```
$ cd patterns/hitl && uv run pytest tests/unit/test_audit_trail.py --no-cov -q
.....
5 passed in 0.19s

$ uv run pytest tests/unit --no-cov -q   # lane 全体、regression なし
......................................................                   [100%]
54 passed, 1 warning in 0.64s

$ uv run ruff check . && uv run ruff format --check . && uv run pyright
All checks passed!
23 files already formatted
0 errors, 0 warnings, 0 informations

$ uv run pytest --cov
...
src/patterns_hitl/audit.py              30      0      4      0   100%
TOTAL                                  284      0     44      0   100%
Required test coverage of 98.0% reached. Total coverage: 100.00%
54 passed, 2 skipped, 1 warning in 1.12s

$ uv run pip-audit
No known vulnerabilities found

$ cd /Users/Shared/codes/pydantic-ai-sandbox && mise run patterns:check
... (全レーン)
[patterns:test] TOTAL                                  284      0     44      0   100%
[patterns:test] Required test coverage of 98.0% reached. Total coverage: 100.00%
[patterns:typecheck] == typecheck patterns/hitl
[patterns:typecheck] 0 errors, 0 warnings, 0 informations
Finished in 33.13s   # exit code 0
```

### [2026-07-13] Task 4.1 (ResumeSchemaGuard — RED) Started

- Objective: `test_resume_schema.py` を先行作成し、`/resume`・`/run` の
  未知フィールド(`message_history` / `usage` / `model` / 任意キー)が
  現行実装(`RunRequest`/`ResumeRequest` に `extra="forbid"` 未設定)では
  pydantic の既定 `extra="ignore"` により静かに無視され、422 ではなく
  200 で通ってしまうことを固定する(R4.1, R4.3)。
- Approach: `test_consumption.py`/`test_api.py` の `_build_app` +
  `call_counting_script` パターンに倣い、(a)–(d) 未知フィールド 4 種の
  422 期待、(e)(f) 正当 body の control(現状も 200 のまま)、(g) `/run`
  側の同種ガード、(h) スパイ(`FunctionModel` の呼び出し回数)で
  「拒否された /resume はモデルへ到達しない」ことを操作的に固定。

### [2026-07-13] RED confirmed

```
$ cd patterns/hitl && uv run pytest tests/unit/test_resume_schema.py -v
...
FAILED test_resume_with_client_supplied_message_history_is_rejected_as_422 — assert 200 == 422
FAILED test_resume_with_client_supplied_usage_is_rejected_as_422 — assert 200 == 422
FAILED test_resume_with_client_supplied_model_is_rejected_as_422 — assert 200 == 422
FAILED test_resume_with_an_arbitrary_unknown_field_is_rejected_as_422 — assert 200 == 422
FAILED test_run_with_an_unknown_field_is_rejected_as_422 — assert 200 == 422
FAILED test_resume_with_client_supplied_message_history_never_reaches_the_model — assert 200 == 422
6 failed, 2 passed in 0.23s
```

- 赤の理由: 現行 `RunRequest`/`ResumeRequest` は `model_config` を持たず、
  pydantic v2 の既定 `extra="ignore"` で未知フィールドが黙って捨てられる
  ため、422 を期待する 6 件は 200 のまま通ってしまう。control 2 件
  (既知フィールドのみの body)は実装前から緑 — 想定通り(4.2 の
  `extra="forbid"` 導入後もこの 2 件は変化しないことを保証する回帰網)。
- Regression check(既存 56 件、lane 全体): `uv run pytest tests/unit
  --no-cov -q` → `6 failed, 56 passed`(失敗は上記 6 件のみ、既存テストに
  regression なし)。新規ファイル単体で `ruff check` / `ruff format
  --check` / `pyright` は 0 件。
- Next: Task 4.2 で `RunRequest` / `ResumeRequest` / `Decision` に
  `model_config = ConfigDict(extra="forbid")` を追加し緑化する。

### [2026-07-13] Task 4.2 (ResumeSchemaGuard — GREEN) Completed

- Objective: `RunRequest` / `ResumeRequest` / `Decision` に
  `model_config = ConfigDict(extra="forbid")` を設定し、Task 4.1 の
  RED 6 件を緑化する(R4.1, R4.3)。履歴/usage/model フィールドは
  「定義しないこと自体が要件」のため追加しない(R4.2 は既存の構造 —
  `harness.resume()` が store 由来の history/usage のみを使う — で
  既に満たされている)。
- Approach: `app.py` に `from pydantic import ConfigDict` を追加し、
  3 モデルそれぞれの docstring 直後に `model_config = ConfigDict(extra="forbid")`
  を挿入。挙動変更なし(GREEN 化のみ)、ロジック分岐は増やさない。

```
$ cd patterns/hitl && uv run pytest tests/unit/test_resume_schema.py -v
8 passed in 0.18s

$ uv run pytest tests/unit --no-cov -q   # lane 全体、regression なし
62 passed in 0.62s

$ uv run ruff check . && uv run ruff format --check . && uv run pyright
All checks passed!
24 files already formatted
0 errors, 0 warnings, 0 informations

$ uv run pytest --cov
src/patterns_hitl/app.py               108      0     24      0   100%
TOTAL                                  287      0     44      0   100%
Required test coverage of 98.0% reached. Total coverage: 100.00%
62 passed, 2 skipped, 1 warning in 0.84s
```

- Learning: `extra="forbid"` の導入は既存の全テスト(既知フィールドのみの
  body を送るもの)に一切影響しない — 未知フィールドを送っていた新規
  テストのみが 200→422 へ切り替わった。純加算的な変更であることが
  カバレッジ 100% 維持と 0 regression で確認できた。

### [2026-07-13] Task 5.1 (EgressPolicyGuard — RED) Completed

- Objective: `test_egress_policy.py` を新設する。(a) レーン `src/` 全体を
  走査し `allow-local` / `force_download` が出現しないことを assert する
  番人テスト(将来 URL 取得ツールを追加する実装者への red シグナル、
  R5.1/R5.2)。(b) README に `safe_download` / egress ポリシー節(R5.3、
  CVE-2026-46678 明記)と R4 設計根拠節(R4.4、CVE-2026-25580 明記)が
  存在することの存在検査。
- Approach: `test_no_hardcoded_model_ids.py` の走査パターンに倣い
  `_iter_src_py_files()` で禁止リテラルを grep する番人テストを 1 本、
  README の markdown 見出し(`^#{1,6}\s+...`)を正規表現で検出し次の
  同階層以下見出しまでを本文として切り出す `_section_body()` ヘルパーを
  新設し、見出しテキストに `safe_download|egress` / `\bR4\b` を含む節の
  本文に必須 CVE ID / キーワードが含まれるかを検証する 2 本を追加。
  見出し文言そのものは 5.2 実装者の裁量に委ねつつ、キー概念(節の存在 +
  該当 CVE ID)は固定する設計。

```
$ cd patterns/hitl && uv run pytest tests/unit/test_egress_policy.py -v --no-cov
tests/unit/test_egress_policy.py::test_no_egress_bypass_literals_in_src PASSED
tests/unit/test_egress_policy.py::test_readme_documents_safe_download_egress_policy FAILED
tests/unit/test_egress_policy.py::test_readme_documents_r4_design_rationale FAILED
2 failed, 1 passed in 0.04s
```

- 赤の理由: 現行 README の `## セキュリティ` 節は SSRF/egress を
  「信頼できない入力の SSRF リスク(記述のみ)」という箇条書きで触れているが、
  `safe_download`/`egress`/`R4` を見出しテキストに含む専用節がなく、
  `CVE-2026-46678` / `CVE-2026-25580` もどこにも記載がないため 2 件が赤。
  番人テスト(`test_no_egress_bypass_literals_in_src`)はレーンに URL 取得
  ツールが未実装のため構造的に緑(想定通り — 5.1 の目的は将来の bypass 検知)。
- Regression check(既存 63 件、lane 全体): `uv run pytest tests/unit
  --no-cov -q` → `2 failed, 63 passed`(失敗は上記 2 件のみ、既存テストに
  regression なし)。新規ファイル単体で `ruff check` / `ruff format
  --check` / `pyright` は 0 件。
- Next: Task 5.2 で README の `## セキュリティ` 節を拡充し、上記 2 件を
  緑化する(safe_download ポリシー節 + R4 設計根拠節 + authn/authz 設計
  ノート + 検証基準版の再掲)。

### [2026-07-13] Task 5.2 (EgressPolicyGuard — GREEN) Completed

- Objective: `patterns/hitl/README.md` の `## セキュリティ` 節を拡充し、
  Task 5.1 の RED 2 件を緑化する(R4.4, R5.3, R6.3)。
- Approach: (1) `### R4 設計根拠` 節を新設 — CVE-2026-25580 を明記し、
  「`/resume` の再開材料は常に `SessionStore` からのみ取得」+
  `extra="forbid"` によるスキーマ遮断の二重防御を説明。(2)
  `### SSRF / egress ポリシー(safe_download)` 節を新設 — 現状ツール未実装
  である旨、将来ツールは `safe_download` 経路必須・`allow-local` 禁止、
  CVE-2026-46678 を根拠として明記し、`test_egress_policy.py` への参照を
  記載。(3) 既存の「認証・レート制限・消費セマンティクス」箇条書きを
  「authn/authz 設計ノート」へ差し替え —「session id は認可トークンでは
  ない。本番は認証境界の内側に置く」を明記し、かつ「013 が担う」という
  陳腐化した記述(セッション衛生/監査証跡/消費セマンティクスは Task 1–3
  で既に実装済み)を実態に合わせて修正。(4) `> 検証基準版(R6.3 / R13.3
  再掲)` の blockquote を追加し、既存の「使用ライブラリと検証基準版」
  表(pydantic-ai-slim 2.9.0 / 2026-07-11)をセキュリティ節内から参照
  できるようにした。既存の「信頼できない入力の SSRF リスク(記述のみ)」
  箇条書きは (1)(2) の専用節に統合し削除(重複記述の解消)。

```
$ cd patterns/hitl && uv run pytest tests/unit/test_egress_policy.py -v --no-cov
tests/unit/test_egress_policy.py::test_no_egress_bypass_literals_in_src PASSED
tests/unit/test_egress_policy.py::test_readme_documents_safe_download_egress_policy PASSED
tests/unit/test_egress_policy.py::test_readme_documents_r4_design_rationale PASSED
3 passed in 0.01s

$ uv run pytest tests/unit --no-cov -q   # lane 全体、regression なし
65 passed, 1 warning in 0.59s
```

## Verification Gate Evidence (Task 5.2)

```
$ cd /Users/Shared/codes/pydantic-ai-sandbox && mise run patterns:check
... (全レーン)
[patterns:test] == test patterns/hitl
[patterns:test] tests/integration/test_ollama_hitl_e2e.py ss
[patterns:test] tests/unit/test_agent_tools.py ..
[patterns:test] tests/unit/test_api.py .........
[patterns:test] tests/unit/test_audit_trail.py .....
[patterns:test] tests/unit/test_consumption.py ................
[patterns:test] tests/unit/test_egress_policy.py ...
[patterns:test] tests/unit/test_observability.py ...
[patterns:test] tests/unit/test_output_validator.py ..
[patterns:test] tests/unit/test_resume_schema.py ........
[patterns:test] tests/unit/test_session_hygiene.py ...
[patterns:test] tests/unit/test_smoke.py ...
[patterns:test] tests/unit/test_stop_approve_resume.py .......
[patterns:test] tests/unit/test_store.py ....
[patterns:test] src/patterns_hitl/app.py               108      0     24      0   100%
[patterns:test] TOTAL                                  287      0     44      0   100%
[patterns:test] Required test coverage of 98.0% reached. Total coverage: 100.00%
[patterns:test] 65 passed, 2 skipped, 1 warning in 1.01s
[patterns:typecheck] == typecheck patterns/hitl
[patterns:typecheck] 0 errors, 0 warnings, 0 informations
Finished in 17.53s   # exit code 0(全レーン lint/format/typecheck/test 緑)
```

- 他レーンの出力にも `error`/`fail` 文字列は残るが、いずれも既存の
  `PydanticDeprecatedSince20` 警告(llamaindex/rag、無関係の pre-existing
  deprecation)と `test_error_termination.py` のテスト名一致のみ —
  regression 0 件を確認。
- Learning: README の「存在検査」テスト(5.1)は見出しテキストの正規表現
  一致 + 節本文への CVE ID / キーワード包含という 2 段検証にしたことで、
  見出し文言の細部(5.2 実装時点)は書き手の裁量に委ねつつ、必須概念
  (節の存在・CVE 番号)の欠落だけは機械的に拾える。既存の重複記述
  (SSRF リスクの箇条書き)を専用節へ統合したことで、セキュリティ節全体の
  一貫性も同時に改善された。

### [2026-07-14 Task 6.1] SECURITY-NOTES CVE 表更新 — 文書追記のみ(テスト境界なし)

- Objective: 「CVE 根拠と依存フロア」表を更新(R6.1)。CVE-2026-25580 /
  CVE-2026-46678 の既存行の対応列へ HITL レーンの対応(v2 フロア
  `pydantic-ai-slim>=2.9.0` + R4 スキーマ遮断)を追記し、CVE-2026-61437
  (Web UI XSS、<1.51.0)行を新規追加。gap-analysis ズレ5(既存対応列の
  `>=2.0.0b6` beta 表記が HITL の `>=2.9.0` と齟齬)も解消する。
- TDD 適用外の判断: tasks.md §6 は境界に `patterns/SECURITY-NOTES.md` のみを
  宣言し、専用テストファイルを持たない(§5 の `test_egress_policy.py` と異なり
  grep/存在検査ガードは指定されていない)。実際に `SECURITY-NOTES.md` を
  参照するテストがリポジトリ全体に存在しないことを事前に確認
  (`grep -rln "SECURITY-NOTES.md" --include="*.py"` → 0 件)。純粋な文書追記
  のため RED→GREEN サイクルは成立せず、直接編集した。
- 事前調査: 各レーンの実際のフロアを確認 — root/frameworks
  `pydantic-ai-slim>=2.3.0`、HITL `pydantic-ai-slim[openai]>=2.9.0`。いずれも
  `2.0.0b6` のような beta サフィックスを持たない。gap-analysis の記述
  (「HITL 行の `>=2.9.0`(GA 系)」)に従い、既存 CVE 行の対応列と「既知の
  制約(Accepted Risk)」の `pydantic-ai v2 Beta 採用 / v2 GA 時に見直し` 行を
  GA 系フロア採用済みの文言へ更新した(`patterns/frameworks/pydantic-ai/README.md`
  はタスク境界外のため未変更 — 別途の陳腐化として残る)。
- 変更内容:
  1. CVE-2026-25580 行: 対応列に「HITL レーンは `/resume` スキーマで
     `message_history` のクライアント供給を遮断(R4)」を追記。
  2. CVE-2026-46678 行: 対応列に「HITL レーンは URL 取得ツール非搭載のため
     攻撃面未発火、将来ツール追加時は `safe_download` 必須化方針を README に
     明記(R5.1–5.3)」を追記。
  3. CVE-2026-61437 行を新規追加: 本リポジトリはいずれのレーンも
     pydantic-ai Web UI 機能を採用していないため非依存と明記。
  4. 「既知の制約(Accepted Risk)」表の `pydantic-ai v2 Beta 採用` 行を
     `pydantic-ai v2 系の追従` へ変更し、GA 系フロア採用済みである旨を反映。
- Verification: 変更はプレーンな Markdown 文字列のみ(コード変更ゼロ)。
  ruff/pyright の対象外。`SECURITY-NOTES.md` を参照するテストが存在しない
  ことを事前確認済みのため回帰リスクはゼロ。参考として hitl レーンの
  既存スイートが無関係であることのみ再確認:

```
$ grep -rn "v2 Beta 採用\|2\.0\.0b6\|CVE-2026" --include="*.py" . | grep -v .sdd
(patterns/hitl/tests/unit/test_egress_policy.py と test_resume_schema.py の
 CVE-2026-25580/46678 文字列参照のみ — SECURITY-NOTES.md の具体的な文言には
 依存しないアサーションであることを確認、regression なし)
```

- tasks.md 6.1 を `[x]` に更新。

### [2026-07-14 Task 6.2] SECURITY-NOTES OWASP マッピング節追加 — 文書追記のみ(テスト境界なし)

- Objective: 「HITL 応用レイヤ → OWASP マッピング(Spec 013)」節を既存4レーン
  (autonomous-agent / RAG / SSE / Deep Research)と同一表形式で追加(R7.1, R7.2)。
- TDD 適用外の判断: Task 6.1 と同様、tasks.md §6 は `patterns/SECURITY-NOTES.md`
  のみを境界とし専用テストファイルを持たない。文書追記のため直接編集。
- 事前調査: `src/patterns_hitl/agent.py` / `harness.py` / `app.py` / `audit.py` を
  grep して識別子(`Tool(requires_approval=True)`, `ApprovalRequired`,
  `DeferredToolRequests`, `HitlBudgetExceededError`, `claim`/`consume`/
  `settle_pending`/`release`, `AuditEvent`)を実コードで確認してから文言を作成。
  列構成は risk→mechanism 型(RAG/SSE/Deep Research)ではなく mechanism→risk 型
  (autonomous-agent の「ガードレール | OWASP 項目 | 緩和メカニズム」)を採用 —
  6.2 のタスク文自体が「承認ゲート → Excessive Agency」のように機構起点で
  要件を列挙しているため。
- 変更内容: Deep Research 節の直後(`## 公式参照` の直前)に新規
  `### HITL 応用レイヤ → OWASP マッピング` 節を追加。4行の表
  (承認ゲート→過剰なエージェンシー/Insecure Tool Use、`UsageLimits` 通算→
  Unbounded Consumption、セッション衛生+サーバー正本履歴→信頼できない入力面
  (LLM01)、マスク済み監査証跡→アカウンタビリティ/機微情報漏洩)+ 既存4節と
  対称な pre-commit 不変条件パラグラフ(gitleaks / forbid-hardcoded-model-ids が
  patterns/ 全域を除外しないことの確認)を追加。
- Verification: プレーンな Markdown 追記のみ(コード変更ゼロ)。新節を参照する
  テストが存在しないことを事前確認。

```
$ grep -rn "OWASP.*マッピング\|HITL 応用レイヤ" --include="*.py" . | grep -v .sdd
(0 件 — 新節に依存するテストなし、regression なし)

$ cd patterns/hitl && uv run pytest --no-cov -q
65 passed, 2 skipped, 1 warning in 0.76s
```

- tasks.md 6.2 を `[x]` に更新。

### [2026-07-14 Task 6.3] SECURITY-NOTES fix未提供アドバイザリ runbook 追加 — 文書追記のみ(テスト境界なし)

- Objective: 「fix 未提供アドバイザリの運用」節を追加(R8.1, R8.2)。手順
  (a)修正版不在確認→(b)悪用可能性評価→(c)レーン限定 `--ignore-vuln <ID>` +
  期限コメント + 追跡 issue → (d)修正着地で即撤去、を明記し、期限・追跡なしの
  抑止エントリを禁止する旨を明文化。nltk / PYSEC-2026-597 の実例を参照する。
- TDD 適用外の判断: Task 6.1/6.2 と同様、境界は `patterns/SECURITY-NOTES.md`
  のみで専用テストなし。文書追記のため直接編集。
- 事前調査:
  1. `specs/document-review/agentic-ai-design-v2-review.md` §C-2/C-3 で
     nltk 3.9.4(rag / frameworks/llamaindex の推移的依存)への
     PYSEC-2026-597/CVE-2026-12243 登録(`_UNSAFE_NO_PROTOCOL_RE` がパーセント
     エンコードされたトラバーサルを検査しない不完全修正)と、
     `uv lock --upgrade-package nltk` で 3.10.0 へ更新して解消した実際の対応
     経緯を確認。本件は upstream 修正が既にあったため `--ignore-vuln` 抑止は
     不要だった旨も確認し、そのまま実例として引用。
  2. `mise.toml` の `patterns:audit` タスクを確認 — 各レーンは
     `(cd patterns/<lane> && uv run pip-audit)` で個別実行されるため、
     「レーン限定の `--ignore-vuln`」は該当レーンの行にのみ追加するという
     具体的な適用面を runbook 内で明記できた。
  3. 相対リンク `../specs/document-review/agentic-ai-design-v2-review.md`
     (patterns/SECURITY-NOTES.md からの相対パス)の実在を確認。
- 変更内容: 「CVE 根拠と依存フロア」節の運用パラグラフ直後、
  「## OWASP Agentic AI Top 10」節の直前に新規 `## fix 未提供アドバイザリの運用`
  節(h2)を追加。手順 1–4、禁止事項(R8.2)、実例パラグラフの3ブロック構成。
- Verification: プレーンな Markdown 追記のみ(コード変更ゼロ)。新節を参照する
  テストが存在しないことを事前確認。

```
$ grep -rn "fix 未提供\|ignore-vuln\|PYSEC-2026-597" --include="*.py" . | grep -v .sdd
(0 件 — 新節に依存するテストなし、regression なし)

$ cd patterns/hitl && uv run pytest --no-cov -q
65 passed, 2 skipped, 1 warning in 0.71s
```

- tasks.md 6.3 を `[x]` に更新。Section 6(6.1–6.3)完了。

### [2026-07-14 Task 7.1] `tests/unit/test_security_workflow_lanes.py` 新規作成 — CVE スキャン到達性の回帰防止ガード

- Objective: `security.yml` の `patterns-pip-audit` matrix と `dependabot.yml`
  の pip `directories` から `hitl`(または将来の任意レーン)が欠落したら
  fail red になる集合一致ガードを追加する(R9.1–9.3)。
- 事前調査(gap-analysis 論点 A の反映): `security.yml:162` に
  `{lane: hitl, dir: patterns/hitl}`、`dependabot.yml:91` に
  `/patterns/hitl` が**既に登録済み**であることを実測確認。したがって本ガードは
  「初回赤の新規保護」ではなく**回帰防止ゲート**であり、TDD の赤先行は
  A1+A2(tasks.md 実装ノート採用済み)に従い以下の二段構成で示す:
  1. 検出機構そのものの赤(H-2): `missing_lanes()` を純関数として切り出し、
     合成 include リスト/合成期待集合を渡して `hitl` 欠落を検出することを
     恒久的な負のユニットケースとしてスイートに固定
     (`test_missing_lanes_is_pure_and_detects_a_synthetic_gap`)。
  2. 実ファイルに対する一時的な赤確認(A1、手動手順): `security.yml` の
     hitl 行、`dependabot.yml` の `/patterns/hitl` 行をそれぞれ一時削除して
     赤を確認 → 復元。
- 実装: `tests/unit/test_security_workflow_lanes.py` を新規作成。
  - `_discover_uv_lanes()`: `patterns/*/pyproject.toml` +
    `patterns/frameworks/*/pyproject.toml` を glob し、独立 uv レーン名を
    全列挙(A2 — hitl 一点でなく将来レーンの追い漏れも拾う)。
  - `_lanes_from_security_matrix()` / `_lanes_from_dependabot_pydantic_ai_block()`:
    実 YAML から現状の登録レーン集合を抽出。
  - `missing_lanes(actual, expected) -> frozenset`: 純関数(ファイル I/O
    なし)。空集合 = 合格。
  - `test_security_yml_matrix_covers_every_uv_lane`: 全 uv レーン列挙 vs
    matrix の集合一致。
  - `test_security_yml_hitl_lane_dir_is_correct`: hitl エントリの `dir` 値。
  - `test_dependabot_pydantic_ai_dependent_block_covers_hitl`: dependabot 側は
    AD-9 方針(pydantic-ai 依存レーン群 = frameworks 3 + hitl)に限定した
    集合一致(rag/sse/deep-research は既知のスコープ外ギャップとして除外)。
  - `test_missing_lanes_is_pure_and_detects_a_synthetic_gap`: 上記 H-2 の
    恒久固定ケース。
- 赤の実測(A1、作業ツリー上で一時編集 → 確認 → 復元、コミットなし):

```
$ uv run pytest --no-cov tests/unit/test_security_workflow_lanes.py -v
# hitl 行削除前(初回): 4 passed — 既登録のため初回緑(gap-analysis 想定通り)

# security.yml から `{ lane: hitl, dir: patterns/hitl }` を一時削除:
test_security_yml_matrix_covers_every_uv_lane FAILED
test_security_yml_hitl_lane_dir_is_correct FAILED
test_dependabot_pydantic_ai_dependent_block_covers_hitl PASSED
test_missing_lanes_is_pure_and_detects_a_synthetic_gap PASSED
AssertionError: security.yml patterns-pip-audit matrix is missing lane(s) ['hitl']; ...
2 failed, 2 passed
# → security.yml を復元(git diff で無差分を確認)

# dependabot.yml から "/patterns/hitl" を一時削除:
test_dependabot_pydantic_ai_dependent_block_covers_hitl FAILED
AssertionError: dependabot.yml's pydantic-ai-dependent pip block is missing lane(s) ['hitl']; ...
1 failed, 3 passed
# → dependabot.yml を復元(git diff で無差分を確認)

$ uv run pytest --no-cov tests/unit/test_security_workflow_lanes.py -v
4 passed  # 復元後、緑に回帰
```

- Verification(フォーマッタ 1 件是正: `PYDANTIC_AI_DEPENDENT_LANES` の
  frozenset リテラルが折返し対象 — `uv run ruff format` で解消):

```
$ mise run check
[lint] All checks passed!
[format] 63 files already formatted
[typecheck] 0 errors, 0 warnings, 0 informations
[test] 286 passed, 4 skipped, 1 warning in 3.09s
```

- tasks.md 7.1 を `[x]` に更新。残タスクは 8.1(完了ゲート)のみ。

### [2026-07-14] Task 8.1(完了ゲート)— 検証のみ、コード変更なし

- Objective: レーン全ゲート緑 + hitl `fail_under=98` 維持 + root ユニット
  (`test_security_workflow_lanes.py`)緑を確認する。R6.2/6.3 は既充足の回帰
  確認のみ(gap-analysis 論点 B / B1、新規テスト追加なし)。

```
$ mise run patterns:check
[lint] All checks passed!(全 8 レーン: contracts / beeai / llamaindex /
  pydantic-ai / rag / sse / deep-research / hitl)
[format] 全レーンで "files already formatted"
[typecheck] 0 errors, 0 warnings, 0 informations(全レーン)
[test] deep-research: 63 passed, 1 skipped, coverage 100.00%(≥98% 達成)
[test] hitl: 65 passed, 2 skipped, coverage 100.00%(≥98% 達成)
Finished in 17.12s
```

```
$ uv run pytest --no-cov tests/unit/test_security_workflow_lanes.py -v
test_security_yml_matrix_covers_every_uv_lane PASSED
test_security_yml_hitl_lane_dir_is_correct PASSED
test_dependabot_pydantic_ai_dependent_block_covers_hitl PASSED
test_missing_lanes_is_pure_and_detects_a_synthetic_gap PASSED
4 passed in 0.06s
```

- R6.2/6.3 回帰確認(コード変更なし、目視確認): `patterns/hitl/pyproject.toml:29`
  = `pydantic-ai-slim[openai]>=2.9.0`(フロア未緩和)。`patterns/hitl/README.md:148-152`
  に検証基準版(pydantic-ai-slim 2.9.0 / 2026-07-11)の記録が現存。両方とも
  012 実装時のまま変更なしを確認。

- **既知の問題(013 スコープ外、別途対応が必要)**: `mise run patterns:audit`
  が `patterns/frameworks/beeai/` の `json-repair==0.39.1` で赤化
  (`GHSA-xf7x-x43h-rpqh`、CVSS 7.5、`SchemaRepairer.resolve_schema()` の
  `$ref` 循環未検出による無限ループ DoS。GitHub Advisory DB 登録日
  2026-07-13、修正版 0.60.1)。013 のスコープは hitl レーンのみであり、
  当該アドバイザリは 013 の変更と無関係(beeai の lockfile はこのブランチで
  未変更、アドバイザリ登録自体が前日付)。切り分けとして
  `(cd patterns/hitl && uv run pip-audit)` を単独実行し
  `No known vulnerabilities found` を確認済み — hitl レーン自体は clean。
  ユーザーとの合意により、8.1 は **hitl + root の実質スコープで完了と判定**し、
  beeai の json-repair 脆弱性は 013 とは別の追跡課題として報告するのみに
  とどめる(013 タスク境界「検証のみ・コード変更なし」を越えるレーン間
  依存バンプは対象外)。

- Status: 8.1 完了。013-agentic-ai-security の全 8 タスク完了。
