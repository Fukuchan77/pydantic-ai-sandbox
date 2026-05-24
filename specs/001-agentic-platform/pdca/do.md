# PDCA — Do Phase Log (001-agentic-platform)

> Implementation log captured during `/sdd-impl` execution. Each entry records
> what was done, what failed (and the root cause), and what was learned.
> Format intentionally lean: prose first, tables second, only when they help.

---

## 2026-05-24 — Task 1: プロジェクト依存とタスクランナー整備

**Scope**: Bootstrap dependencies, task runner, env contract, and onboarding.
Per the task header, Task 1 does **not** touch `src/` and is therefore exempt
from Test-First (Constitution I); the focus is making subsequent TDD tasks
runnable.

### What was done

| Sub-task | Files            | Outcome                                                                                                                                                                                                                                                                                                                     |
| -------- | ---------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1.1      | `pyproject.toml` | Added `pydantic-ai-slim[openai]>=2.0.0b3` to runtime deps (Plan AD-6 / R-1); added `bandit`, `pip-audit` to dev group; added `[tool.coverage.run] source = ["src/pydantic_ai_sandbox"] branch = true` and `[tool.coverage.report] fail_under = 0` baseline. `requires-python = ">=3.14"` confirmed already present (no-op). |
| 1.2      | `mise.toml`      | Defined `lint`, `format`, `typecheck`, `test`, aggregate `check` (depends), `setup`, `pre-commit:default`, `pre-commit:manual`, `test:integration`. Pre-existing `[tools]` block kept.                                                                                                                                      |
| 1.3      | `.env.example`   | Authored canonical env contract for APP_ENV / LOG_LEVEL / LLM_PROVIDER / OLLAMA\_\* / WATSONX\_\* / ANTHROPIC\_\* / BEDROCK\_\* / FALLBACK_ORDER / LOGFIRE_TOKEN / LOG_SENSITIVE_PAYLOADS / RUN_INTEGRATION_OLLAMA. All secret-bearing variables left empty (Req 9.6).                                                      |
| 1.4      | `README.md`      | Replaced placeholder with onboarding (`mise install` → `mise run setup` → `cp .env.example .env` → `mise run check`), provider-switching guidance, FastAPI launch commands, and the Ollama integration lane.                                                                                                                |

### Errors and root causes

1. **`mise WARN unknown field tasks.pre-commit:default`** appeared on first
   `mise run check`. Root cause: TOML quoting placed the colon-bearing key
   inside a fully-quoted table header (`["tasks.pre-commit:default"]`),
   collapsing the dotted path into a single literal key. Fix: use
   `[tasks."pre-commit:default"]` so only the colon-segment is quoted.
   `mise tasks` now lists all nine tasks correctly. Lesson: in TOML, quote
   only the segment that needs it, not the whole dotted path.

2. **`pytest` exits 5 (no tests collected) → `mise run test` fails**. Root
   cause: not a defect; this is the expected bootstrap state. The first test
   file lands in T2.1 (`tests/unit/test_no_hardcoded_model_ids.py`). The
   `mise run check` aggregate gate becomes meaningfully enforceable after
   T2.1; until then `lint`/`format`/`typecheck` are individually green but
   `test` correctly reports "nothing to verify". No suppression added — the
   correct path is to ship T2.1 next, not to silence pytest.

### Verification

```text
mise run lint       → All checks passed!
mise run format     → (clean)
mise run typecheck  → 0 errors, 0 warnings, 0 informations
mise run test       → exit 5 (no tests yet; resolved by T2.1)
```

`uv sync` completed without resolution conflicts: 18 transitive packages
added (bandit, pip-audit, cyclonedx-python-lib, etc.); the
`pydantic-ai-slim[openai]` extra resolved compatibly with the existing
`pydantic-ai>=2.0.0b3` constraint.

### Learnings carried forward

- TOML key quoting is segment-scoped. Anywhere we add `task:subtask` style
  names later, write `[tasks."<colon-name>"]`.
- The `mise run check` aggregate is the single command future tasks should
  drive against. Avoid documenting raw `uv run` recipes in places other than
  fallback prose; everything routine flows through `mise`.
- Bootstrap PRs that don't touch `src/` will leave the `test` gate red.
  That's intentional discipline — the next task closes the gap rather than
  hiding it.

### Requirements covered

T1.1 → 1.4, 6.1, 7.7, 9.1, 9.2, 10.1, 10.4 ·
T1.2 → 7.1, 7.2, 7.3, 7.4, 7.5, 8.5 ·
T1.3 → 9.6 ·
T1.4 → 8.5

---

## 2026-05-24 — Amendment: bandit 非導入への一本化 (Spec Q3 修正)

**Trigger**: ユーザレビューで「ruff 設定に `S` (flake8-bandit) が含まれているので bandit を別途インストールする必要がない」との指摘。当初 T1.1 では spec/plan/tasks の文言通り bandit を dev 依存に追加していた。

**根本原因 (5 Why)**:

1. なぜ重複が発生したか → spec.md Q3 と plan.md / tasks.md が "pip-audit + bandit + gitleaks" の三層構成を前提に書かれていたから。
2. なぜそう書いたか → idea0.md §13 と一般的な OSS Python セキュリティ三点セットの定石を踏襲したから。
3. なぜ重複に気づかなかったか → 仕様策定時に `pyproject.toml` の既存 ruff 設定 (`select = [..., "S", ...]`) を相互参照しなかった (Plan §5 / §6 のトレーサビリティ表は要件→実装方向のみで、ツール重複の逆引きが無かった)。
4. なぜ T1.1 実装時に検出できなかったか → "spec が bandit を要求 → tasks.md が同じ文言を継承 → 実装が忠実追従" の経路でツール重複の独立検証ステップが無かった。レビュー段で初めて気づいた。
5. なぜレビューで気づけたか → ユーザが ruff の `[tool.ruff.lint] select` を直接読んで `S` の存在に気付いたため。

**証拠** ([Astral docs - flake8-bandit (S)](https://docs.astral.sh/ruff/rules/#flake8-bandit-s)):

- ruff `S` の安定実装範囲: S101-S324 / S501-S612 / S701-S704 (assert / exec / 弱ハッシュ / SSL/TLS / subprocess / SQL injection / Jinja XSS など主要全項目)
- ruff 未実装: S309 (httplib HTTPSConnection - Py2era), S322 (input() - Py2), S325 (tempnam - 廃止), S320/S410 (lxml - 意図的削除)
- いずれも Python 3.14 strict プロジェクトには無関係。bandit 単体導入の追加価値はゼロに近い。

**修正範囲** (ユーザ承認済み: "spec.md も含めて全面整合"):

| Artifact         | 変更内容                                                                                                                                       |
| ---------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| `pyproject.toml` | `[dependency-groups] dev` から `bandit` 削除。コメントで非導入根拠と参照先 (do.md) を明示                                                      |
| `spec.md`        | Q3 を "pip-audit + ruff `S` + gitleaks" に書き換え + 注記。Q4 の bandit 言及を ruff `S` 経由に。8.3 / 9.2 を amend                             |
| `plan.md`        | File Structure Plan の `pyproject.toml` / `.pre-commit-config.yaml` / `security.yml` 行を ruff `S` 経路で書き直し。§7 受容ギャップの記述も整合 |
| `research.md`    | `security.yml` の job content から bandit を除外し、`pip-audit` / `gitleaks` のみに。"bandit 非導入の根拠" ブロックを追加 (gap analysis 含む)  |
| `tasks.md`       | T1.1 / T2.2 manual stage / T12.2 の bandit 言及を削除し ruff `S` 経路に。T1 Implementation Notes に追記                                        |
| `spec.json`      | `amendments` 配列を新設し、本変更の summary / scope / affected_artifacts を記録。`updated` を 19:10:00Z に進める                               |

**spec.md の保存方針**: 当初の Q3 回答テキストは「pip-audit + ruff `S` + gitleaks」に書き換えつつ、末尾注記で「当初は bandit 単体だったが実装段で重複と判明したため amendment した」旨を明示し、変更経緯のトレーサビリティを保持。8.3 / 9.2 も同様に注記。spec.json `amendments` でフォーマル記録。

**検証**:

```text
uv sync                                 # bandit と関連 17 deps が uninstall されることを確認
mise run lint / format / typecheck      # 全 green
mise run test                           # exit 5 (no tests yet) — T2.1 待ち
```

**学び**:

- Spec 策定時にツール重複の独立検証ステップ (既存 `pyproject.toml` / `mise.toml` の static analysis 設定との逆引き照合) が抜けていた。次の `/sdd-spec` 実行時に "ツールスタック重複監査" を Plan 段の自己点検項目に追加する候補。
- `S` ルールが flake8-bandit の上位互換であるという事実は ruff doc にしか書かれておらず、constitution.md の "flake8-bandit rules (`S`) are enforced" だけでは "bandit 単体不要" の含意までは読み取れなかった。constitution の Quality & Tooling Standards 節に "ruff `S` で bandit を兼ねる" を明記すべきか、`/sdd-reflect` 段で検討する。

---

## 2026-05-24 — Task 2: ハードコード model ID 防御 (lint stage)

**Scope**: Plan AD-4 の二段防御を成立させる。`tests/unit/test_no_hardcoded_model_ids.py`
を runtime 側のスナップショット検査として、`.pre-commit-config.yaml` の
`forbid-hardcoded-model-ids` (pygrep) を commit 段の即時遮断として配置し、
両者が同一の禁則語彙を共有する構成にした。Test-First (Constitution I) 適用。

### What was done

| Sub-task | Files                                       | Outcome                                                                                                                                                                                                                              |
| -------- | ------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 2.1      | `tests/unit/test_no_hardcoded_model_ids.py` | `FORBIDDEN_MODEL_ID_LITERALS` を 5 件で確定 (granite4.1:8b / claude-sonnet-4-6 / claude-haiku-4-5-20251001-v1:0 / llama3.2-vision:11b / granite-4-h-small)。`src/**/*.py` から `__init__.py` を除外して走査。`.gitignore` の `.env` 検査も同テスト内で兼用 (Req 9.6)。 |
| 2.2      | `.pre-commit-config.yaml`                   | default stage に ruff-check / ruff-format-check / pyright / pygrep `forbid-hardcoded-model-ids` / gitleaks v8.21.2 を、manual stage に pytest / pip-audit を配置。`language: system` で `mise run` と version-identical。`exclude` で `tests/**` と将来の `src/**/config.py` を除外。 |

### RED→GREEN trace (Constitution I)

1. `tests/unit/test_no_hardcoded_model_ids.py` 着地直後に `src/pydantic_ai_sandbox/_red_demo.py` を作成し
   `DEMO_MODEL_ID = "granite4.1:8b"` を埋め込んだ状態で `uv run pytest tests/unit/test_no_hardcoded_model_ids.py -v`
   を実行 → `test_no_hardcoded_model_ids_in_src` が `AssertionError: ... src/pydantic_ai_sandbox/_red_demo.py:4 contains 'granite4.1:8b'` で
   FAILED を返した (RED 観測完了)。
2. `_red_demo.py` を削除し空の `src/` を rmdir した上で再走 → 2 件全 PASSED (GREEN)。
3. `_red_demo.py` も含めて全ての `src/` 配下を削除しているため、commit 履歴には RED ファイル本体は残らず本ログのみが
   PDCA 記録となる。`tests/` ボーダーを破らない (T2.1 の `_Boundary:_` 遵守)。

### Verification

```text
uv run ruff check .                            → All checks passed!
uv run ruff format --check .                   → 1 file already formatted (after one auto-format pass on the test)
uv run pyright                                  → 0 errors, 0 warnings, 0 informations
uv run pytest                                   → 2 passed in 0.01s (test_no_hardcoded_model_ids_in_src + test_gitignore_excludes_dotenv)
mise run check                                  → all four gates green (aggregated)
uv run pre-commit run --all-files               → ruff-check / ruff-format-check / pyright / gitleaks all Passed; pygrep skipped (no candidate files yet — expected, src/ empty)
uv run pre-commit run --all-files --hook-stage manual → pytest / pip-audit Passed
```

追加サニティチェック: `src/pydantic_ai_sandbox/_pygrep_check.py` に `claude-sonnet-4-6` を一時注入して
`uv run pre-commit run forbid-hardcoded-model-ids --all-files` を走らせ、`Failed` で正しく検出されることを
確認 (regex / exclude pattern の双方が機能している証拠)。検査後に同ファイルと `src/` ツリー全体を削除済み。

### Errors and root causes

1. **`uv run ruff format --check` が初回失敗** — テスト本文の改行スタイルが ruff format 既定と相違。
   Root cause: 手書きの multiline f-string 連結スタイルが ruff の preferred line wrapping に合わなかった。
   Fix: `uv run ruff format tests/unit/test_no_hardcoded_model_ids.py` を 1 回実行して受け入れ。symptom (フォーマットエラー)
   ではなく cause (ruff の一意フォーマット) に従う方針を維持 (Constitution V "fix the cause, not the symptom")。
2. **`pre-commit run --all-files` が新規ファイルに対して "no files to check" Skipped** — git-tracked でないため。
   Root cause: pre-commit は `git ls-files` ベースで対象を決める。Fix: `git add -N` で intent-to-add 状態にした後で
   再走したところ全フックが期待通り fire。本件は CLAUDE.md の振る舞いではなく pre-commit の正規仕様。
   学びとして tasks.md Implementation Notes に明記し、初回コミット workflow の罠として後続タスクにも継承可能にした。

### Design notes (将来の語彙更新ポリシー)

`FORBIDDEN_MODEL_ID_LITERALS` は **新たな model ID literal が env 経由で codebase に入った瞬間に追記** するルールで運用する。
追記時は (a) `tests/unit/test_no_hardcoded_model_ids.py` の tuple、(b) `.pre-commit-config.yaml` の pygrep `entry`,
(c) (該当があれば) `.env.example` のコメントの三箇所を lockstep 更新。三箇所のうち一箇所でも忘れると
語彙ドリフトを起こすため、`/sdd-reflect` 段で「禁則語彙更新チェックリスト」をパターン化する候補。

`src/**/config.py` を `exclude` に組み込んだのは Plan §8 R-5 (default 値の偽陽性回避) への先回り対応。
T3.3 で `src/pydantic_ai_sandbox/config.py` が誕生する時点で、env-default の文字列 (今のところ皆無) は
このフックの対象から外れる。同時に T2.1 の runtime テストは `__init__.py` を除外するだけなので config.py を
通常通り検査する → "コミット段では緩く / runtime テストでは厳格に" の二層体制になる。

### Learnings carried forward

- Pre-commit `language: system` パターンは `mise run check` と完全に重複するため、コマンド統治の観点で扱いやすい。
  ただし developer machine に `uv` が前提となるので README.md (T1.4 完了済み) の "uv install" を欠かさないこと。
- pygrep hook は単一行リテラル限定。改行を跨ぐ難読化文字列 (例えば `"granite4.1:" + "8b"`) は検出できない。
  これは設計上の妥協点で、runtime テスト側も同様。難読化の悪意はそもそも `S` ルールや code review の領分で、
  本フックは "うっかり忘れ" の防止が目的。
- gitleaks `v8.21.2` を rev pin にした。9.x 系の改変があれば pre-commit の autoupdate で別途追従。

### Requirements covered

T2.1 → 1.5, 9.6 ·
T2.2 → 1.5, 7.6, 8.1, 8.2, 8.3

---

## 2026-05-24 — Task 3: Settings (config layer)

**Scope**: pydantic-settings ベースの `Settings` を `frozen=True` で実装し、
`get_settings()` を `lru_cache` シングルトンで提供する (Plan §2.1)。
Test-First (Constitution I) を適用 — RED → GREEN → quality gates の順。

### What was done

| Sub-task | Files                                  | Outcome                                                                                                                                                                                                                                              |
| -------- | -------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 3.1      | `tests/conftest.py`                    | `_MANAGED_ENV_KEYS` (20 keys, mirrors `.env.example`) を一元管理し、`settings_factory(monkeypatch)` が clear-then-set パターンで Settings を構築するヘルパを公開。`SettingsFactory` を `Protocol` で型付け (pyright strict 通過)。`app_with_overrides` は `pytest.skip` で T8.2/T9 までガード。 |
| 3.2      | `tests/unit/test_config.py`            | 9 件のテスト: ollama happy-path / Literal alphabet lock / OLLAMA_MODEL_NAME 必須 / unknown LLM_PROVIDER / FALLBACK_ORDER 空 / FALLBACK_ORDER 全 unknown / FALLBACK_ORDER 単一 known / LOGFIRE_TOKEN 任意 / `get_settings` lru_cache 同一性。                       |
| 3.3      | `src/pydantic_ai_sandbox/{__init__,config}.py` | `LLMProvider` Literal、`_KNOWN_FALLBACK_MEMBERS` frozenset、`Settings(BaseSettings, frozen=True)` + `model_validator(mode="after")` で provider 別 fail-fast、`get_settings = lru_cache(maxsize=1)`。`__init__.py` は `__version__` のみ公開。            |

### RED→GREEN trace (Constitution I)

1. `tests/conftest.py` と `tests/unit/test_config.py` 着地直後に
   `uv run pytest tests/unit/test_config.py -v` を実行 →
   `ImportError ... ModuleNotFoundError: No module named 'pydantic_ai_sandbox'`
   で **conftest 段の collection が落ちる RED 状態を観測** (src/ がまだ存在しないため意図通り)。
2. `src/pydantic_ai_sandbox/{__init__,config}.py` を作成 → `uv pip install -e .` で
   editable install を seat → 再走で **9 passed in 0.02s** (GREEN)。
3. `mise run check` で 4 ゲート (lint / format / typecheck / test) 全 green。
   テスト総数 11/11 passed (T2.x の 2 件 + T3.2 の 9 件)。

### Errors and root causes

1. **`uv sync` 直後の編集 import が失敗 (`ModuleNotFoundError: No module named 'pydantic_ai_sandbox'`)**
   - 症状: `src/pydantic_ai_sandbox/` を新規作成し `uv sync` を走らせても
     pytest の conftest が `from pydantic_ai_sandbox.config import Settings` を解決できなかった。
   - 根本原因: `pyproject.toml` に `[build-system]` セクションが無く、uv が
     hatchling default をフォールバックで使用している状態。`uv sync` は
     既にインストール済みの editable をスキップするが、**初回の editable
     install は別途トリガが必要**。`Resolved 153 packages in 5ms / Checked 147
     packages in 34ms` というログは "ロックファイルとの差分は無い" を意味し、
     "プロジェクト本体を register した" を意味しない。
   - 修正: `uv pip install -e .` を 1 回実行 → `Built pydantic-ai-sandbox @
     file://...; Installed 1 package; + pydantic-ai-sandbox==0.1.0` を確認。
     symptom (import error) ではなく cause (editable install seat 不在)
     を直す方針 (Constitution V "fix the cause, not the symptom")。
   - 再発防止: `mise.toml` の `setup` task は既に `uv sync` を含むが、
     `uv sync` 単体では src 構造の初期化を保証しない。後続 `/sdd-reflect`
     で `setup = "uv sync && uv pip install -e ."` 化を検討する候補
     (現状 `uv sync` の挙動はバージョン間で変動余地があり、明示的な
     editable install を含めるほうが robust)。

2. **`uv run ruff format --check .` が初回失敗** — `tests/conftest.py` の docstring 改行スタイルが ruff format 既定とズレ。
   - 根本原因: 手書きの multi-line docstring が ruff の preferred wrapping に合わなかった。
   - 修正: `uv run ruff format tests/conftest.py` を 1 回受け入れ。差分は文字列の改行位置のみで意味は変わらない。

3. **`RUF100 Unused noqa directive (non-enabled: ARG001)`**
   - 根本原因: `pyproject.toml` の ruff `select` に `ARG` 群が含まれていない (現状の rule set は `E,W,F,I,B,UP,RUF,S,A,SIM,T20,D,N,C4,C90,TCH`)。
     `ARG001` (Unused function argument) は無効なので `# noqa: ARG001` 自体が dead code。
   - 修正: コメントを通常の説明コメント (`# used for env-clearing side-effect; clear cache below.`)
     に置き換え。`ARG` を rule set に追加するか否かは別議論 (本タスクの境界外)。

### Verification

```text
mise run check
  [lint] All checks passed!
  [format] 5 files already formatted
  [typecheck] 0 errors, 0 warnings, 0 informations
  [test] 11 passed in 0.02s
  Finished in 1.29s
```

`uv pip install -e .` の出力:

```text
Resolved 116 packages in 980ms
Building pydantic-ai-sandbox @ file:///Users/Shared/codes/pydantic-ai-sandbox
   Built pydantic-ai-sandbox @ file:///Users/Shared/codes/pydantic-ai-sandbox
Prepared 1 package in 748ms
Installed 1 package in 1ms
 + pydantic-ai-sandbox==0.1.0 (from file:///Users/Shared/codes/pydantic-ai-sandbox)
```

### Design notes (validator semantics と Pydantic v2 の wrap-up 挙動)

タスク仕様文には「FALLBACK_ORDER の異常時に `ValueError`」「LLM_PROVIDER=foobar
で `ValueError`」と書かれているが、Pydantic v2 では:

- `@model_validator(mode="after")` 内で `raise ValueError(...)` →
  `pydantic.ValidationError` に **wrap される**
- `pydantic.ValidationError` は `ValueError` の subclass では **ない** (v1 と異なる)

したがって `pytest.raises(ValueError)` ではキャッチできない。テストは
**全件 `pytest.raises(ValidationError)` で書き、`str(exc.value)` に変数名や
不正値が含まれることを assert** する形にした。validator 側のコードは
`raise ValueError(msg)` のままなので wrap-up 経路は実コードでも踏まれる。
このセマンティクス差は `tests/unit/test_config.py` の module docstring と
`tasks.md` Task 3 Implementation Notes の双方に明文化済み。

### Design notes (Literal alphabet lock as drift sentinel)

`test_llm_provider_literal_alphabet_is_authoritative` は
`get_type_hints(Settings)["llm_provider"]` から Literal 引数を取り出し、
正準 5 要素集合との一致を assert する。これは T4.3 の `ModelFactory` ディスパッチ
表 (`ollama` / `watsonx` / `anthropic` / `bedrock` / `fallback` の 5 分岐 +
unknown) と T5.4 の `_KNOWN_FALLBACK_MEMBERS` (4 要素集合) の **両方が
Literal alphabet と lockstep であることを保証する語彙アンカー** として機能する。
将来 provider を追加するときに、Literal 更新を忘れたら本テストが赤化し、
忘れずに更新した場合は次に T4 / T5 のディスパッチ表との整合検査が後続する。

### Design notes (`_MANAGED_ENV_KEYS` と環境隔離)

`tests/conftest.py` の `_MANAGED_ENV_KEYS` は `.env.example` (T1.3) の変数集合
ミラー。`settings_factory()` 呼び出し時に毎回 `monkeypatch.delenv(key,
raising=False)` で全件クリアしてから override を適用するため、開発者の
シェル環境や `.env` の残留値が test 結果に流入しない。`KEY=None` 渡しは
"その変数は明示的に未設定" を意味し、kwarg 省略 (= デフォルト適用) と
区別する。これにより "LOGFIRE_TOKEN 未設定でも Settings 成立" のような
"absent" を要件で問うテストを誤魔化さず書ける。

### Learnings carried forward

- `uv sync` は editable install を初期化しない。`src/<pkg>/` を新規作成
  した直後は `uv pip install -e .` を 1 回踏む必要がある。`mise run setup`
  に組み込む案は `/sdd-reflect` 段で検討 (本タスク境界外なので推奨に留める)。
- Pydantic v2 の validator-raises-ValueError → wrap-into-ValidationError
  は仕様文と実コードの間でセマンティクス調停が必要なポイント。
  以後の `Settings` 追加 (T4–T7 の env 取り込みなど) でも同じ経路を踏む。
- `Literal` alphabet をテスト側で固定しておくと provider 追加時に
  Drift 検出が必ず火を吹く。Literal を持つコンポーネント (T6.3 の
  `ChatResponse` など) には同型の lock test を添えるのが定石になりそう。

### Requirements covered

T3.1 → 1.1, 1.2, 4.5 ·
T3.2 → 1.1, 1.2, 4.5 ·
T3.3 → 1.1, 1.2, 1.4, 4.5
