# 014-hub-python-beta-lane — PDCA Do Log

## Implementation Log

### [2026-10-04 00:00] Task 1.1 Started

- Objective: 失敗する Python 3.14 baseline rules-as-tests 契約を
  `tests/unit/test_python_baseline.py` に作成する。
- Approach: `EXPECTED_SERIES = "3.14"` を単一の正本とし、
  `pyproject.toml`（requires-python / ruff target-version / pyright
  pythonVersion）・`mise.toml`・`.pre-commit-config.yaml`（pyright hook
  name）・`.github/workflows/ci.yml`（onboarding comment）の 6 ピンそれぞれに
  対する一致テストを書く。interpreter 一致と `ibm-watsonx-ai` import は
  3.13 でも green のため赤の根拠にしない（task 記述どおり）。

### [2026-10-04 00:05] Task 1.1 Test Evidence

**RED evidence** (before implementation):

- Test: `tests/unit/test_python_baseline.py`
- Command: `uv run pytest --no-cov tests/unit/test_python_baseline.py -v`
- Failure (6 件、すべて対象 path を明示):
  - `test_pyproject_requires_python_matches_expected_series`:
    `AssertionError: .../pyproject.toml: [project] requires-python is pinned
    to 3.13, expected 3.14`
  - `test_mise_python_matches_expected_series`:
    `AssertionError: .../mise.toml: [tools] python is pinned to 3.13,
    expected 3.14`
  - `test_ruff_target_version_matches_expected_series`:
    `AssertionError: .../pyproject.toml: [tool.ruff] target-version is
    pinned to 3.13, expected 3.14`
  - `test_pyright_version_matches_expected_series`:
    `AssertionError: .../pyproject.toml: [tool.pyright] pythonVersion is
    pinned to 3.13, expected 3.14`
  - `test_pre_commit_pyright_hook_matches_expected_series`:
    `AssertionError: .../.pre-commit-config.yaml: pyright hook name is
    pinned to 3.13, expected 3.14`
  - `test_ci_workflow_matches_expected_series`:
    `AssertionError: .../.github/workflows/ci.yml: onboarding comment is
    pinned to 3.13, expected 3.14`
- 3 passed（non-red-basis）: `test_expected_series_is_well_formed`,
  `test_interpreter_matches_python_version_file`,
  `test_watsonx_import_succeeds`
- Result: 6 failed, 3 passed in 0.58s（RED 確認済み。1回目は
  `.pre-commit-config.yaml` の `py3.13` 形式を `pyXYY` 正規表現が誤検出せず
  AssertionError になったため、regex を `py(\d+\.\d+)` に修正して再実行）

### [2026-10-04 00:10] Task 1.2 Started

- Objective: 1.1 の RED 契約を GREEN 化する。`EXPECTED_SERIES = "3.14"` に対して
  `.python-version` / `mise.toml` / `pyproject.toml`
  （requires-python・ruff target-version・pyright pythonVersion・ADR-1 コメント）/
  `.pre-commit-config.yaml` / `.github/workflows/ci.yml` / `README.md` /
  `CLAUDE.md` / `.sdd/memory/constitution.md` の 3.13 記述をすべて 3.14 へ同期する。
- Approach: tasks.md の順に機械的な find-and-sync を実施。README.md と
  CLAUDE.md は「ROOT の Python 版」を指す行だけを変更し、ハブ側の制約を記述する
  行（README.md L15 の `fastapi<0.137` / `starlette<1.0` / Python 3.13 holds は
  ハブの話）は意図的に変更しなかった。

### [2026-10-04 00:20] Task 1.2 Substitute Failure Evidence（統治文書）

`constitution.md` と `CLAUDE.md` は `.sdd/` および `CLAUDE.md` 自体が
`.gitignore` 対象（`.gitignore:223`, `.gitignore:228`）のため、
`git show HEAD:<path>` は `fatal: path '...' exists on disk, but not in 'HEAD'`
となり実行不能（tasks.md が許容する「red test が成立しない」ケースに該当）。
代わりに、改訂前に Read 済みだった原文をそのまま代替の失敗証拠として引用する:

- `.sdd/memory/constitution.md` Principle 3（改訂前）:
  > ルートは `pyright` strict mode と Python 3.13 設定で clean でなければならない。
- `.sdd/memory/constitution.md` Additional Constraints「Current root baseline」（改訂前）:
  > **Current root baseline**: `requires-python >=3.13`、Ruff `py313`、Pyright
  > `pythonVersion = "3.13"`。将来版への変更は、承認済み spec と検証結果を伴う同一変更で行う。
- `.sdd/memory/constitution.md` フッター（改訂前）: `**Version**: 2.0.0 | **Ratified**:
  2026-05-24 | **Last amended**: 2026-10-03`
- `CLAUDE.md`（改訂前、3 箇所）:
  > 1. **Root app** — `src/pydantic_ai_sandbox/` (Python 3.13): ...
  > | `mise run typecheck` | `pyright` (strict, Python 3.13) |
  > Pyright runs **strict** against Python 3.13. `Any` is allowed only at I/O
  > boundaries and must be narrowed via Pydantic models before flowing inward.

これらを 3.14 へ同期し、`constitution.md` は MINOR bump 2.0.0 → 2.1.0
（Principle 3 と Additional Constraints の実質的な記述変更のため）、
SYNC IMPACT REPORT と Last amended（2026-10-04）を更新した。

### [2026-10-04 00:30] Task 1.2 Environment Switch

- Command: `mise install python` → `python@3.14.8 already installed`
- Command: `mise exec -- uv sync --all-groups` → exit 0（.venv が Python 3.14.5 に切替）
- Confirm: `mise exec -- uv run python3 --version` → `Python 3.14.5`

### [2026-10-04 00:35] Task 1.2 GREEN Evidence

- Command: `mise exec -- uv run pytest --no-cov tests/unit/test_python_baseline.py -v`
- Result: `9 passed, 2 warnings in 10.23s`（6 件の pin 一致テストすべて green。
  `test_watsonx_import_succeeds` も 3.14 で green — ADR-1 の `ibm-watsonx-ai>=1.8.0`
  が 3.14 で import できることを再確認した）

### [2026-10-04 00:40] Task 1.2 PROVE Evidence

- Stub: `mise.toml` の `python = "3.14"` を一時的に `python = "3.13"` に書き換え
- Command: `mise exec -- uv run pytest --no-cov tests/unit/test_python_baseline.py::test_mise_python_matches_expected_series -v`
- Observed failure: `AssertionError: .../mise.toml: [tools] python is pinned to
  3.13, expected 3.14`（期待どおりのメッセージ。テストが非空虚であることを確認）
- Restore: `mise.toml` を `python = "3.14"` に戻し、全体を再実行して
  `9 passed` に復帰したことを確認

### [2026-10-04 00:45] Task 1.2 Mechanical py314 Ruff Fixes

`mise run check` の `[format]` が 2 ファイルの未整形を検出:

- `src/pydantic_ai_sandbox/config.py:197` — `except (TypeError, ValueError):` →
  `except TypeError, ValueError:`（PEP 758, Python 3.14 の括弧なし複数例外構文。
  ruff の formatter が `target-version = "py314"` に伴いこの形へ正規化した。
  `mise exec -- uv run python3 -c "..."` で実際に 3.14 で catch できることを確認済み）
- `tests/unit/test_python_baseline.py` の 3 箇所 — f-string の行結合（通常の
  line-length 整形、Python 版とは無関係）

`uv run ruff format .` で両ファイルを整形。加えて pyright strict が
`tests/unit/test_python_baseline.py:99` の `ModelInference` import を
`reportUnusedImport` として検出したため、import した名前を
`hasattr(ModelInference, "__name__")` で実際に参照する形へ修正（`# noqa` /
`# pyright: ignore` で黙らせるのではなく、import の目的（ADR-1 の import 契約）
を保ったまま両方の strict ゲートを満たした）。

### [2026-10-04 00:55] Task 1.2 Verification Gate

- `mise run check` → lint All checks passed / format 67 files already
  formatted / typecheck 0 errors, 0 warnings, 0 informations / test
  **323 passed, 4 skipped**
- `mise run cov` → **Required test coverage of 98.0% reached. Total
  coverage: 98.51%**（323 passed, 4 skipped）
- `uv run pip-audit`（`mise exec --`） → **No known vulnerabilities found**
  （`pydantic-ai-sandbox` 自体は PyPI 未公開のため skip、想定どおり）
- `mise run patterns:check` → exit 0。deep-research は Python 3.13.7、
  hitl は 3.14.5、rate-limit は 3.15.0rc2 のまま、それぞれ独立 pin で green
  （root の 3.14 移行の影響なし）

Evidence 1 行を `docs/hub-intake-2026-10.md` 新設の「## 5. Root baseline run」
節に記録（憲法 Principle 6）。

### [2026-10-04 01:00] Task 1.2 VDD Review Trigger Check

5 トリガーをすべて確認し、非該当のため reviewer 起動を省略:

1. Boundary 外の変更なし（`tests/unit/test_python_baseline.py` の追加修正は
   task group 1 の全体 `_Boundary:_` に含まれる）
2. 新規 third-party dependency の追加なし（pyproject.toml はコメント・版のみ変更）
3. 既存テストの変更・削除・skip/xfail 化なし（変更したのは今回新設したテストのみ）
4. coverage 低下なし（98.51% ≥ 98%、ratchet 維持）
5. PROVE evidence は上記で提示済み

### [2026-10-04 01:05] Task 1.2 Marked Complete

`specs/014-hub-python-beta-lane/tasks.md` の `- [ ] 1.2` を `- [x] 1.2` に更新。
