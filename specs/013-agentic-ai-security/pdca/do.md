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
