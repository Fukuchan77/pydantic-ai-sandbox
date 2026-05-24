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

---

## 2026-05-24 — Task 4: ModelFactory ディスパッチと Ollama provider 実装

**Scope**: `get_model()` の env-driven dispatch 実装。`ollama` のみ実体
(`OpenAIChatModel` + `OllamaProvider`)、`watsonx`/`anthropic`/`bedrock` は
follow-up spec へ誘導する `NotImplementedError` stub。`fallback` は T5.4
までプレースホルダ。Req 2.6 の "constructor は I/O しない" 不変条件を
契約テストで物理的に固定する。

### What was done

| Sub-task | Files                                                                                                                                                                                                  | Outcome                                                                                                                                                                                                                                                                                                                       |
| -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 4.1      | `tests/unit/test_factory_dispatch.py`                                                                                                                                                                  | 5 ケース: ollama→Model、stub 3 種で `NotImplementedError` + 後続 spec ヒント (parametrize)、unknown→`ValueError`、引数なしで `Settings.llm_provider` を経由、`_MVP_STUB_PROVIDERS` の語彙ロック。Settings は `_seat_ollama_settings` ヘルパで lru_cache に種付け、各テストで `finally: get_settings.cache_clear()` を徹底。 |
| 4.2      | `tests/unit/test_factory_ollama_no_io.py`                                                                                                                                                              | `httpx.Client.send` / `httpx.AsyncClient.send` を `_NetworkAccessError` 投擲版に monkeypatch し、`get_model("ollama")` が成功する (= 無 I/O) ことを assert。OpenAI SDK 内部実装に依存せず transport 層で罠を張る方針。                                                                                                          |
| 4.3      | `src/pydantic_ai_sandbox/llm/__init__.py`, `llm/factory.py`, `llm/providers/__init__.py`, `llm/providers/{ollama,watsonx,anthropic,bedrock}.py`                                                          | `get_model()` で env→Model の 1:1 dispatch。`_MVP_STUB_PROVIDERS = frozenset({"watsonx","anthropic","bedrock"})` を `__all__` 公開。`_build_ollama` は `str(HttpUrl)` 経由で `OllamaProvider(base_url=..., api_key=...)` を組み、`OpenAIChatModel(model_name=..., provider=...)` を返す。3 stub は `Never` 型で provider 名 + `002-multi-provider` 文言の `NotImplementedError` を raise。 |

### RED→GREEN trace (Constitution I)

> **Note (retrospective)**: 本節は `/sdd-validate-impl Task 4` で「Task 2/3 と
> 同型の RED→GREEN 節が欠落」と検出された LOW 指摘の修正として、依存チェーン
> (`_Depends:_ 4.1, 4.2 → 4.3`) と test ファイルの import 表面から検証可能な
> 事実のみで再構成した。観測当時の pytest 生ログは保全されていないため、
> 再現可能性は (a) 並列タスクの `(P)` マーカ、(b) 各テストの import 行、
> (c) `_build_*` を提供する src 側不在時の collection 失敗仕様、の 3 点を
> 根拠とする。後続タスク (T5–T12) は同節を contemporaneous に書く。

1. T4.1 / T4.2 は `(P)` 並列タスクとして T4.3 より先に着地する設計
   (tasks.md の依存宣言: `4.3 _Depends:_ 4.1, 4.2`)。
   `tests/unit/test_factory_dispatch.py:30-33` は
   `from pydantic_ai_sandbox.llm import get_model` /
   `from pydantic_ai_sandbox.llm.factory import _MVP_STUB_PROVIDERS` を
   import するため、`src/pydantic_ai_sandbox/llm/` 不在状態で
   `uv run pytest tests/unit/test_factory_dispatch.py` を走らせると
   pytest collection 段で `ModuleNotFoundError: No module named
   'pydantic_ai_sandbox.llm'` を返して **RED**。
   `tests/unit/test_factory_ollama_no_io.py:31-32` も同経路で同 import を
   保有しており、collection 失敗の語彙は同一。
2. T4.3 で `src/pydantic_ai_sandbox/llm/{__init__,factory}.py` と
   `llm/providers/{__init__,ollama,watsonx,anthropic,bedrock}.py` の 7 ファイル
   を投入 → 同テスト群を再走 → **8 / 8 PASSED** (dispatch 7 + no-io 1) で **GREEN**。
3. `mise run check` で 4 ゲート (lint / format / typecheck / test) 全 green。
   全テスト合計 19 / 19 passed (T2.x の 2 + T3.2 の 9 + T4.1 の 7 + T4.2 の 1)。

### Errors and root causes

1. **Pyright strict が `_build_*` / `_MVP_STUB_PROVIDERS` の cross-module
   import を `reportPrivateUsage` で叩いた + 各 provider 関数が
   `reportUnusedFunction` で flag された**。
   - **Root cause**: 命名は spec mandate (plan.md §2.3 / §2.4) で
     leading underscore を要求。Pyright strict は `_` 名を module-private
     と解釈し、別モジュールから参照すると警告する。さらに provider 関数
     は呼出側 (`factory.py`) でしか参照されないため、自モジュール内で
     未使用扱いとなる。
   - **Fix**: 二段構え。(a) 各 provider モジュールに `__all__ = ["_build_*"]`
     を宣言して `reportUnusedFunction` を解消、`__all__` を介してその
     名前が "module の公開面" であることを pyright に伝える。
     (b) `factory.py` の import 行 (および test の import) に
     `# pyright: ignore[reportPrivateUsage]` を付与し、共通 rationale
     コメントで「leading underscore は人間向けシグナル、`__all__`
     経由で正式公開されている」旨を明記。Constitution V (don't weaken
     local config) を守りつつ spec 命名を維持。
2. **ruff `SIM300 (Yoda condition detected)` が
   `_MVP_STUB_PROVIDERS == frozenset(...)` を flag した**。
   - **Root cause**: ruff の SIM300 は UPPER_SNAKE_CASE 名を「定数 ≒ literal」
     として扱い、左辺が literal だと Yoda と判定する。(通常 Yoda は
     `LITERAL == var`、ruff の解釈は逆方向にも機能している。)
   - **Fix**: 期待値を `expected = frozenset({...})` にバインドして
     `assert expected == _MVP_STUB_PROVIDERS` の順に書き換え。読みやすさ
     を犠牲にしないまま rule を満たす。
3. **ruff `TC002 (Move third-party import pytest into a type-checking block)`
   が test_factory_ollama_no_io.py で発火した**。
   - **Root cause**: 当該テストは `pytest.MonkeyPatch` を **annotation**
     としてしか使わず、`pytest.raises` 等の runtime API は呼ばない。
     `from __future__ import annotations` 下では annotation が文字列化
     されるため、TC002 は型注釈のみの import を `TYPE_CHECKING` 化せよ
     と要求する。
   - **Fix**: `import pytest` を `if TYPE_CHECKING:` ブロックへ移動。
4. **ruff `RUF100 (Unused noqa: ANN401)`** — `# noqa: ANN401` を予防的に
   付けたが、`ANN` ルール群はそもそも `pyproject.toml` で select されて
   おらず冗長だった。**Fix**: `# noqa` を撤去。
5. **ruff `I001 (import block un-sorted)`** が factory.py で連鎖発火 →
   `ruff check --fix` が複数行 import 形式 (`from ... import (\n    name, # ignore\n)`) に
   再フォーマット。**Fix**: 自動適用を採用。コメント付き `# pyright: ignore`
   は複数行 import の方が読みやすいので結果オーライ。

### What was learned

- **Spec の underscore 命名 vs pyright strict の衝突は今後も再来する**。
  T5.4 の `_build_fallback` でも同じ `__all__ + # pyright: ignore` パターン
  で対応する。Constitution に "spec mandates underscore naming for
  package-private helpers; resolve via `__all__` + targeted ignore" を
  運用ノート化する価値がある。
- **`Never` 戻り型 stub は契約テスト側で大きな価値**。実装ファイルが
  「呼ぶと爆ぜる」ことが型レベルで保証されるため、factory の dispatch
  分岐に `_build_watsonx(settings)  # Never returns` と書いても pyright
  は落ちない。stub にも署名対称性 (`settings: Settings`) を持たせたのは
  T5.4 の `_build_fallback` が再帰的に `get_model(member)` を呼ぶ際の
  シグネチャ均質性に効く。
- **transport 層で罠を張る no-I/O テスト戦略は OpenAI SDK 内部実装に
  非依存**。`httpx.{Client, AsyncClient}.send` を monkeypatch するだけで
  Pydantic AI / OpenAI / 任意の HTTP ライブラリ全てに通用する。
  T11.1 の integration テストでは逆に send が呼ばれる (= I/O が起きる)
  ことが期待値なので、本テストとミラー関係になっている。
- **`get_model` が lru_cache を持たない設計判断は意図的**。Settings 側で
  既に lru_cache が効いているので Model 自体のキャッシュは agent
  ライフサイクル単位 (= FastAPI Depends の lifetime) に任せる方が
  テスト観点でクリーン (test 毎に `get_settings.cache_clear()` だけで
  リセット可能)。

### Verification

```text
mise run lint       → All checks passed!
mise run format     → 14 files already formatted
mise run typecheck  → 0 errors, 0 warnings, 0 informations
mise run test       → 19 passed (config 9 + dispatch 7 + no-io 1 + model-id-guard 2)
```

### Requirements covered

T4.1 → 2.1, 2.3, 2.4, 2.5 ·
T4.2 → 2.6 ·
T4.3 → 2.1, 2.2, 2.3, 2.4, 2.5, 2.6

---

## 2026-05-24 — Task 5: FallbackModel 構築とフェイルオーバ検証

**Scope**: `FALLBACK_ORDER` から `FallbackModel` を組み立てる `_build_fallback`
の実装と、その挙動 (failover 成功 / 全 member 失敗 / all-stub fail-fast) の
契約テスト。`get_model` 経由の dispatch 配線 (T4.3 で deferred) を完成させる。
Test-First (Constitution I) を全サブタスクに適用。

### What was done

| Sub-task | Files                                                                              | Outcome                                                                                                                                                                                                                                                                                                                                                                                                            |
| -------- | ---------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 5.1      | `tests/support/__init__.py`, `tests/support/model_fakes.py`                        | `function_model_raising(exc, *, model_name)` と `function_model_returning_json(payload, *, model_name)` を 2 ヘルパとして公開。前者は `ModelAPIError` を投げると `FallbackModel` の default `fallback_on=(ModelAPIError,)` で recovery 経路が発火、それ以外は伝播するという pydantic-ai V2 の挙動を docstring に明記。production 側からの import 禁止 (Plan §2.10) は test-only パッケージ運用で物理的に保証。 |
| 5.2      | `tests/unit/test_factory_fallback.py`                                              | 3 ケース: 単一 real member (`FALLBACK_ORDER=ollama`) → `FallbackModel`、全 stub (`watsonx,anthropic`) → `RuntimeError` + メッセージに `FALLBACK_ORDER` を含むこと、混在 (`ollama,watsonx`) → 成功して real member のみで chain 構築。Settings 段で先に弾かれる "空 / 全 unknown" は到達不能ケースとして docstring で明記し test しない (test_config.py 側でカバー済)。                                              |
| 5.3      | `tests/unit/test_fallback_failover.py`                                             | 2 ケース: failing+success → success の output が返る + `invoke_agent` span の `model_name` 属性が `"fallback:<fail>,<success>"` 形式で両 provider 名を含む、全失敗 → `FallbackExceptionGroup.exceptions` に原 `ModelAPIError` インスタンスが identity で保持される。logfire テスト fixture は `capfire` を使わず `TestExporter` + `instrument_pydantic_ai` を最小構成で内製化。                                          |
| 5.4      | `src/pydantic_ai_sandbox/llm/fallback.py`, `src/pydantic_ai_sandbox/llm/factory.py` | `_build_fallback(settings)` 実装: members パース → all-stub 検出時 `RuntimeError` → 混在時 stub をフィルタ → `FallbackModel(default, *rest)` 構築。`factory.py::get_model` の `"fallback"` ブランチを `from .fallback import _build_fallback` の lazy import + `return _build_fallback(settings)` に書き換え。docstring の Raises 表 / モジュール docstring の遷移ノートも整合。                              |

### RED→GREEN trace (Constitution I)

1. **T5.1 着地直後** に `tests/support/{__init__,model_fakes}.py` を作成。
   この 2 ファイル単独では走るテストが無いため、`uv run pytest tests/support`
   は collection 0 で exit 5。RED 観測は subsequent な T5.2 / T5.3 の collection
   失敗で代替。
2. **T5.2 着地直後** に `uv run pytest tests/unit/test_factory_fallback.py
   tests/unit/test_fallback_failover.py -v` を実行 →
   `ModuleNotFoundError: No module named 'pydantic_ai_sandbox.llm.fallback'`
   で **collection error**。`tests/unit/test_factory_fallback.py:29` の
   `from pydantic_ai_sandbox.llm.fallback import _build_fallback` が解決
   不能 → **RED 観測完了**。
3. **T5.3 単独再走** (`uv run pytest tests/unit/test_fallback_failover.py`)
   は 2 件中 1 件 PASS / 1 件 FAIL を返した — failover 自体は src 不在でも
   pydantic-ai 既製の `FallbackModel` で完結するが、span filter を `name`
   ("invoke_agent a") に依存していたため pydantic-ai V2 が変数名を span
   name に埋め込む挙動 (実際は `"invoke_agent agent"`) と齟齬し AssertionError。
   → **属性ベース filter** (`gen_ai.operation.name == "invoke_agent"`) に
   置換して GREEN 化。これは "src 実装が無い段階で test を書くと、test
   側の壊れやすい仮定が早期に露見する" という TDD の本来の効用そのもの。
4. **T5.4 着地後** (`src/.../llm/fallback.py` 投入 + `factory.py` の
   fallback 分岐書き換え) に再走 → **24 / 24 PASSED** で GREEN。
   既存テスト (config 9 + dispatch 7 + no-io 1 + model-id-guard 2) と
   新規テスト (factory_fallback 3 + fallback_failover 2 = 5) の合算。

### Errors and root causes

1. **`mise run check` 初回 fail: `ruff format --check` が test_fallback_failover.py の改行を要求**。
   - 根本原因: 手書きの inline コメント文の段落幅が ruff の preferred wrapping と相違。
   - 修正: `uv run ruff format tests/unit/test_fallback_failover.py` で受容。意味変化なし。
2. **`RUF100 Unused noqa: ANN001`**。
   - 根本原因: pydantic-ai V2 の `FunctionDef` シグネチャ (`Callable[[list[ModelMessage], AgentInfo], ...]`) に対し `_respond` の引数を素のままにし `# noqa: ANN001` で抑止しようとしたが、`pyproject.toml` の ruff `select` に `ANN` 群は無く noqa が dead code 化 (T3 / T4 と同型のミス再来)。
   - 修正: `if TYPE_CHECKING:` ブロックに `ModelMessage` / `AgentInfo` を import し、`_respond` を完全 typed annotation に書き換え。`# noqa` 撤去。`# type: ignore` も同時撤去 (もう不要)。
   - 学び: `# noqa: <CODE>` を書く前に `pyproject.toml::[tool.ruff.lint] select` を必ず確認する。Constitution V "fix the cause, not the symptom" — 不必要な suppression は cause ではなく cosmetic noise。
3. **循環 import 設計圧力**。
   - 症状: `llm/fallback.py` が `from llm.factory import _MVP_STUB_PROVIDERS, get_model` を要し、`llm/factory.py` が `from llm.fallback import _build_fallback` を要する → top-level 解決不能。
   - 根本原因: `_build_fallback` が `get_model(member)` で再帰し、`get_model` 自身は dispatch 表として `_build_fallback` を呼び返す双方向依存。
   - 修正: `factory.py` の `if resolved == "fallback":` ブロック **内部** に `_build_fallback` の遅延 import を置き、関数呼出時にだけ循環が解決する形に。`fallback.py` の top-level 側は変更不要 (`factory.py` 全モジュールが先に初期化済みになる側を保つ)。
   - 学び: 循環依存は構造的問題のサインだが、片方を遅延 import に倒せば実害ゼロでパッチ可能。設計上、`_build_fallback` を `factory.py` 内に置く別案もあったが、Plan §4.1 が `llm/fallback.py` を独立ファイルとして指定しているのでファイル境界は維持。

### Design notes (mixed-stub config の挙動)

tasks.md は `_build_fallback` の動作として「全 member が stub なら `RuntimeError`」しか
明示制約しない。一方で `FALLBACK_ORDER=ollama,watsonx` のような **混在**
構成も合法な env 入力 (Settings の field validator は通る)。実装は:

- pre-check: 全 stub → `RuntimeError` (fail-fast)
- 混在: stub を **silent filter** し、real members のみで `FallbackModel` 構築

を採用した。これは:

1. ユーザの `FALLBACK_ORDER` の **相対順序** を尊重 (real provider 同士の順序保持)
2. stub 由来の `NotImplementedError` を `/chat` まで遅延させない (Plan §2.4 の意図)
3. `002-multi-provider` への段階的ロールアウトを許容 (stub を予め env に入れて
   おく運用が可能で、provider 実装が land した瞬間に member として有効化される)

逸脱解釈ではあるが Plan §2.4 の主目的 (NotImplementedError 遅延阻止) と
整合する最小実装。`/sdd-validate-impl` 段で再評価される可能性あり。

### Design notes (T5.3 logfire span 属性検証の二部構成)

T5.3 spec text は "logfire span 属性 (provider 名 / error class) が含まれること"
を要求するが、pydantic-ai V2 の `instrument_pydantic_ai()` 実装は:

- **成功 path**: `invoke_agent` span の `model_name` 属性に
  `"fallback:<fail-name>,<success-name>"` 形式で chain 全体を載せる
  → provider 名 (失敗 member 含む) は確かに span 属性に残る
- **失敗 attempt の error class**: span 属性として **emit されない**
  (`models/fallback.py::request` の `_set_span_attributes` が成功時のみ呼ばれる)

つまり "provider 名" と "error class" の両方を **同一 span 属性で**
証明することは現状の V2 Beta では不可能。test を二部構成に分解:

- (a) 成功 failover の span 属性 → 両 provider 名を `model_name` で assert
- (b) 全失敗時の `FallbackExceptionGroup.exceptions` → 原 `ModelAPIError`
  インスタンスの identity を assert (error class の正体性)

この設計判断は test の module docstring と上記 tasks.md Implementation Notes
の両方に明文化済。pydantic-ai V2 GA で span 属性に失敗 attempt 情報が
追加された場合は、本テストを (a) 単体で完結させる方向に refactor する余地。

### Design notes (test fixture の logfire 内製化)

`logfire.testing.capfire` は完全な capture (spans + metrics + logs) を提供
するが、T5.3 は spans のみで足りる。`fixtures` 名前空間を圧迫しない狙いで
`captured_spans` という名前で `TestExporter` を最小構成で組み立てた。
`capfire` の本体ソース (上記参照) と同じ pattern を 8 行に圧縮した内製版で、
`metrics_reader` / `log_exporter` を持たないため pyright 上もシンプル。
T7.1 で logfire の本格的な setup test が必要になった時点で `capfire` への
切替を再評価する。

### Verification

```text
mise run check
  [lint]      All checks passed!
  [format]    19 files already formatted
  [typecheck] 0 errors, 0 warnings, 0 informations
  [test]      24 passed in 0.93s
  Finished in 2.00s

uv run pre-commit run --all-files
  ruff check (lint; S/C90/D/N/T20)               Passed
  ruff format --check                            Passed
  pyright (strict, py3.14)                       Passed
  forbid-hardcoded-model-ids (Req 1.5)           Passed
  Detect hardcoded secrets                       Passed
```

合計 24 passed (config 9 + dispatch 7 + no-io 1 + model-id-guard 2 +
factory_fallback 3 + fallback_failover 2)。

### Learnings carried forward

- **循環 import** は 1 ファイル境界 + 1 モジュール内の lazy import で解決可能。
  T5 で確立したパターン (`if resolved == "fallback": from ... import _build_fallback`)
  は将来 provider が増えて factory ↔ provider-specific module の双方向依存が
  発生したときの再利用テンプレート。
- **`# noqa: <CODE>` を書く前に `pyproject.toml` の `select` を確認** —
  T3 / T4 / T5 の三回連続で同型のミスを踏んだ。`/sdd-reflect` 段で
  「`# noqa` を書く前のチェックリスト」をパターン化する候補。
- **TDD の RED 観測は test 側の脆い仮定を早期に露呈する** — T5.3 の
  span name 仮定 (`"invoke_agent a"` literal) はまさに RED 段で検出され、
  src 側を一度も触らずに test を堅牢化できた。RED が "ただの import error"
  に終わらず "test 自体が assert する世界の見方の検証" にもなる好例。
- **pydantic-ai V2 instrument の挙動は仕様文書ではなく実装で確認するのが速い** —
  spec の "span 属性に provider 名 / error class" は idea0.md / Plan に書かれ
  ているが、実際の attribute key 名 (`gen_ai.operation.name`,
  `gen_ai.request.model`, `model_name="fallback:..."` の format) は smoke
  script で `exporter.exported_spans_as_dict()` を読まないと分からない。
  T7 (Logfire 計装) でも同じ手順を踏む見込み。

### Requirements covered

T5.1 → 4.4, 10.2 ·
T5.2 → 4.1, 4.2, 4.5 ·
T5.3 → 4.3, 4.4 ·
T5.4 → 4.1, 4.2, 4.3, 4.5

---

## 2026-05-24 Task 6 — Schemas + ChatAgent (V2 Beta API 表面)

### Plan

- T6.1 / T6.2 を **並列で先に RED** → schemas (T6.3) → agents.chat_agent
  (T6.4) の順で GREEN 化。`build_chat_agent` は `agents/__init__.py`
  経由で公開、`search_kb` はモジュールトップレベル定義 + コンストラクタ
  `tools=[search_kb]` 登録の二段で実装する方針 (理由: T6.1 が
  `inspect.signature(search_kb)` で関数本体を直接 introspect するため
  クロージャ化を避ける)。
- TDD discipline: tests を書き、`uv run pytest` で `ModuleNotFoundError`
  を観測した後でのみ src 側を触る。

### Do

#### RED → GREEN サイクル

1. `tests/unit/test_chat_agent_tool.py` (4 tests) と
   `tests/unit/test_chat_agent_v2_surface.py` (5 tests) を先に書き、
   `pytest` で `ModuleNotFoundError: No module named
   'pydantic_ai_sandbox.agents'` を観測 (RED 状態確認済み)。
2. `schemas/__init__.py` + `schemas/chat.py` を実装 — `ChatRequest.message`
   は `min_length=1` で空文字列を 422 段階で弾く、`ChatResponse.sources`
   は `default_factory=list` で「ツール未呼出時にも構造妥当」な空配列を
   許容。
3. `agents/__init__.py` + `agents/chat_agent.py` を実装 — `search_kb`
   をモジュールトップレベルに、`build_chat_agent` は `Agent[None,
   ChatResponse](model=..., output_type=ChatResponse, instructions=...,
   deps_type=type(None), tools=[search_kb])` で構築。
4. 9/9 tests PASS、ただし pyright で 12 件のエラー残存 — 即座に対処へ。

#### 詰まりポイント

##### Pyright trap 1: `Agent[None, ChatResponse]` だけでは overload 不一致

エラー:
```
Argument of type "type[object]" cannot be assigned to parameter
"deps_type" of type "type[None]" in function "__init__"
```

`Agent.__init__` の `deps_type` 既定値が **`<class 'object'>`** で、
これは `Agent[None, ...]` 型引数 `AgentDepsT=None` (≡ `type[None]`) と
整合しない。`uv run python -c "import inspect; from pydantic_ai import
Agent; print(inspect.signature(Agent.__init__))"` で実シグネチャを確認:
```
deps_type: 'type[AgentDepsT]' = <class 'object'>
```

→ プロダクション (`build_chat_agent`) と V2 surface テスト 4 箇所すべてで
**`deps_type=type(None)` を明示**追加。`output_type=ChatResponse` も
既定値 `str` を上書きしないと overload に合致しないため既に明示済み。
これで pyright strict 0 errors。

##### Pyright trap 2: `from __future__ import annotations` で signature 評価が文字列のまま

T6.1 の最初の実装で
`inspect.signature(search_kb).parameters[name].annotation == "RunContext[None]"`
(文字列) となり `get_origin(annotation) or annotation` が文字列にフォール
バック。`origin is RunContext` が常に False で 2 件失敗。

`agents/chat_agent.py` の冒頭が `from __future__ import annotations`
(PEP 563) なので、`inspect.signature` は raw 文字列を返す。**
`typing.get_type_hints(search_kb)` 経由で評価**すれば実型に解決される。
テスト docstring に「PEP-563 評価」の理由を残し、将来同型のミスを防ぐ。

##### Pyright trap 3: `@agent.tool` 装飾対象が "未使用" 扱い

T6.2 の `stub_tool` は登録のみで戻り値を読まないため
`reportUnusedFunction` が発火。**`# pyright: ignore[reportUnusedFunction]`
を行内で局所抑制** + 抑制理由コメント (Constitution V "ungrounded
ignore" 禁止に対応)。プロダクション側は `tools=[search_kb]` 形式で
発生せず、抑制はテスト側 1 箇所のみに閉じている。

##### Pyright trap 4: `_callable` 内の `typing.cast` が冗長

最初に書いた `_callable(obj: object) -> Callable[..., object]` 内で
`return typing.cast("Callable[..., object]", obj)` が
`reportUnnecessaryCast` を発火 (`assert callable(obj)` で既に narrow
済みのため)。そもそも `search_kb` は型付き関数オブジェクトなので
`inspect.signature(search_kb)` を直接渡せば `_callable` ヘルパ自体が
不要 → ヘルパごと削除。テストコードの surface area が縮んだ副次効果も
あり。

#### 検証

`mise run check`: lint / format / typecheck / test 全 4 ゲート PASS。
合計 33 passed (T1-T5 既存 24 + T6 新規 9)。

### Check (test 結果と learnings)

#### Test results

| Task | Test file | Tests | Status |
| ---- | --------- | ----- | ------ |
| T6.1 | tests/unit/test_chat_agent_tool.py | 4 | ✅ |
| T6.2 | tests/unit/test_chat_agent_v2_surface.py | 5 | ✅ |
| T6.3 | (no dedicated test; consumed by T6.1/T6.2/T6.4) | — | — |
| T6.4 | (covered by T6.1/T6.2 above) | — | — |

#### Learnings carried forward

- **`Agent` の generic 型引数を書くなら `deps_type=type(None)` を必ず明示** —
  既定値 `object` は `Agent[None, ...]` の overload と合致しないため
  pyright strict で必ず落ちる。プロダクションに `Agent[None, OutT]` を
  書くたびに発生するパターン。Task 9.3 (chat ルート) や Task 11.1
  (E2E) の `Agent` 構築でも同じ予防策が要る。
- **`from __future__ import annotations` 配下の関数を `inspect.signature`
  で読むときは `typing.get_type_hints` を必ず噛ませる** — 生 annotation
  が文字列のまま `get_origin` を当てると常に `None` が返って silent
  pass の温床になる。テスト側に PEP-563 を理解した防御を入れないと、
  「test が green だけど実は何も見ていなかった」事故になる。
- **`@agent.tool` は副作用デコレータ** — 登録は agent 内部に向くので
  pyright の使用追跡が透けない。プロダクションは `tools=[fn]` 形式で
  避けるのが綺麗で、テストでデコレータ経路を踏むときだけ局所抑制を
  使う。本タスクはまさにこの選び分けで pyright を黙らせた。
- **TestModel.last_model_request_parameters.function_tools が公式の
  ツール内省窓口** — pydantic-ai V2 docs (`docs/toolsets.md`) が
  `[t.name for t in test_model.last_model_request_parameters.function_tools]`
  を例示。`agent.toolsets` / `agent._function_toolset` の peek より
  上位安定。Task 9.1 / 9.2 (chat エンドポイントテスト) でも同 surface
  を使う見込み。
- **モジュールトップレベル `search_kb` + `tools=[search_kb]` 登録**は
  「テストの import 可能性」と「プロダクション登録経路」を一致させる
  最小セットアップ。`@agent.tool` をクロージャ内で使うと `inspect.signature`
  の対象が消える/別物になるため、本パターンは将来ツールが増えたときの
  テンプレートとして再利用する。

#### Requirements covered

T6.1 → 3.3, 6.3 ·
T6.2 → 6.4 ·
T6.3 → 3.1, 3.2 ·
T6.4 → 3.3, 6.3, 6.4

---

## 2026-05-24 — Task 7 + Task 8 (combined): 可観測性 fail-soft 計装と Health エンドポイント

**Scope**: Logfire `configure_observability` (Req 5.1, 5.2, 5.3, 5.4, 5.5) と
`GET /healthz` + `create_app()` skeleton (Req 1.3) を一体で実装。tasks.md の
依存グラフ (T7.2 が T8.2 を `_Depends:_` で要求) を尊重し、両 Task を
同一 `/sdd-impl` 実行で完了させた。Task 7 単独着手では T7.2 がブロック
され、TDD の RED-GREEN-REFACTOR が成立しないため。

### What was done

| Sub-task | File(s) | Outcome |
| -------- | ------- | ------- |
| 8.1 | `tests/unit/test_health.py` | RED 確認 (`ModuleNotFoundError: pydantic_ai_sandbox.main`)。3 テスト: 既定 Ollama パス / `LLM_PROVIDER` パラメトリ (ollama, fallback)。`_build_client` ヘルパで env override + `get_settings.cache_clear()` + `create_app()` を 1 関数化。 |
| 8.2 | `src/.../api/__init__.py`, `api/deps.py`, `api/routes/__init__.py`, `api/routes/health.py`, `main.py` | GREEN: `get_settings_dep` を `Depends` ファクトリとして公開。`router.get("/healthz")` で `{"status": "ok", "provider": settings.llm_provider}` を返却。lifespan は no-op (T10.2 が `configure_observability` + fallback dry-run を上乗せ)。`app: FastAPI = create_app()` をモジュールレベルで公開し `fastapi dev` 互換。 |
| 7.1 | `tests/unit/test_logging_setup.py` | RED 確認 (`logging_setup` 不在)。3 テスト: token 未設定時の 1 行 WARNING (Req 5.2) / `instrument_pydantic_ai`+`instrument_fastapi(app)`+`instrument_httpx` の 3 呼び出し (Req 5.1) / `ScrubbingOptions.extra_patterns ⊇ {prompt, tool_input, tool_output}` (Req 5.4)。 |
| 7.2 | `tests/unit/test_logging_resilience.py` | RED 確認。`monkeypatch.setattr("pydantic_ai_sandbox.logging_setup.logfire.configure", _raise_runtime_error)` で transport 障害を再現。`create_app()` + `configure_observability(app, settings)` 直後に `TestClient.get('/healthz')` が 200 を返すことで Req 5.5 を立証。 |
| 7.3 | `src/pydantic_ai_sandbox/logging_setup.py` | GREEN: `configure_observability(app, settings)` を実装。token 未設定時に `logger.warning("LOGFIRE_TOKEN is unset; …")` を 1 行発火 → `logfire.configure(send_to_logfire='if-token-present', token=…, scrubbing=ScrubbingOptions(extra_patterns=['prompt','tool_input','tool_output']))` → `instrument_pydantic_ai/fastapi/httpx`。全体を `try/except Exception` で包み、失敗時は `logger.warning(..., exc_info=True)` で 1 行通知のみ (Req 5.5)。 |
| 7.4 | `tests/unit/test_logging_span_attributes.py` | 設計上 first-run GREEN: pydantic-ai V2 の `instrument_pydantic_ai()` が `gen_ai.provider.name` / `gen_ai.system` / `gen_ai.request.model` を chat span 属性として既に発火している。本テストは contract probe — 上記キーが将来 rename / drop された瞬間に赤化することが設計目的 (Req 5.3 / Req 6.4 の前段)。 |

### Errors and root causes

1. **依存グラフ衝突 (T7.2 `_Depends:_ 3.3, 8.2`)**。Task 7 単独では T7.2 が
   `create_app() + /healthz` を `TestClient` 経由で要求し RED-GREEN-REFACTOR が
   成立しない。**Root cause**: tasks.md でこの cross-task 依存は
   `_Depends:_` に明示されていたが、`/sdd-impl Task 7` の素朴解釈では
   見落とし得る。**Fix**: AskUserQuestion で 3 択 (8.1/8.2 を先に取り込む /
   T7.2/7.4 を defer / blocker 扱い) を提示し、ユーザ選択 (推奨案) で
   8.1 → 8.2 → 7.1 → 7.2 → 7.3 → 7.4 の順を採用。**Lesson**: `_sdd-impl Task N`
   呼び出し時は他 Task からの依存を最初の context load 段で確認し、
   違反時は AskUserQuestion で明示的に分岐する。
2. **`ruff format --check` 1 件失敗** (`tests/unit/test_logging_setup.py`)。
   f-string 連結が 1 行にまとまる長さだったため。**Fix**: `uv run ruff format`
   を 1 度走らせて反映。**Lesson**: f-string assertion メッセージは
   ruff の line-length 判断に乗るので、複数行に手動 break する前に
   format を回した方が安い。
3. **`RUF100 Unused noqa: BLE001`**。`pyproject.toml` の `select` に
   `BLE` (flake8-blind-except) は含まれていないため、`# noqa: BLE001`
   は未使用ディレクティブとして検出される。**Fix**: `noqa` を削除し、
   `except Exception:` 直下の複数行コメントで fail-soft 契約 (Req 5.5) と
   `BaseException` を意図的に外している点を明文化。**Lesson**: ruff の
   `select` セットを更新する前に `noqa` を書くと逆に lint が壊れる。
   この場合は inline コメントで意図を残す方が select-set との結合度が低い。
4. **`TC002 Move third-party import 'pytest' into a type-checking block`**
   (`tests/unit/test_logging_resilience.py`)。pytest の利用が `monkeypatch:
   pytest.MonkeyPatch` 注釈のみで、`from __future__ import annotations` 配下
   では文字列評価扱いとなり実行時 import 不要。**Fix**: `import pytest` を
   `if TYPE_CHECKING:` ブロックに移動。**Lesson**: 注釈以外で `pytest.fixture`
   デコレータや `pytest.raises` を使う場合は実行時 import が必要なので、
   テストファイルごとに pytest の利用形態を確認する。

### Verification

```text
mise run lint       → All checks passed!
mise run format     → (clean)
mise run typecheck  → 0 errors, 0 warnings, 0 informations
mise run test       → 41 passed in 1.17s (T7/T8 合算で +8 テスト)
```

### Learnings carried forward

- **依存横断 `/sdd-impl` パターン**: Task N の `_Depends:_` が他 Task の
  サブタスクを指す場合、まず両 Task を同一実行で完了させる選択肢を
  AskUserQuestion で提示する。ユーザ判断を得てから着手する方が、
  後で BLOCKED マーク + 巻き戻しより安い。
- **fail-soft の bare-except は `noqa` でなく inline コメント**。
  プロジェクトの `select` セットにそのルールが入っていない時に `noqa`
  を書くと `RUF100` で逆に壊れる。意図の文書化は コメントで行い、
  `select` 拡張時に `noqa` を足すかは将来判断。
- **`monkeypatch.setattr("pkg.module.logfire.configure", fn)` パターン**は
  `import logfire` で global module を bind しているコードに対して
  cross-test pollution なく介入できる。`monkeypatch` の teardown が
  module attribute を正しく復元するため、別テストでの logfire 利用に
  影響しない。
- **TestModel の OTel GenAI 属性表面**: `gen_ai.provider.name` (新キー) と
  `gen_ai.system` (legacy alias) が両方 emit される。テストは
  `provider.name OR system` で or-tolerant に書き、`request.model` は
  単独で必須化することで、上流の semantic-convention 移行に追従しつつ
  「provider 名 + model ID」両方の存在を Req 5.3 で必須化する。
- **`app_with_overrides` skeleton はまだ pytest.skip() のまま**。T9.1 / T9.2
  が body を埋める段で `app.dependency_overrides` + `agent.override` の
  合成パターンを確定する。T8.1 の `_build_client` ヘルパは
  `app_with_overrides` 完成後にローカル化されるか共有化されるかを
  そこで再評価する。
- **T7.4 = contract probe**: 既存実装が要件を満たしている場合、
  RED 状態は「テストの不在」自体である。今回の T7.4 は upstream
  pydantic-ai V2 の instrument_pydantic_ai 動作に対する regression net
  として機能する。同種パターン (V2 表面の上流契約に依存) は今後も
  出現するので、PDCA で「first-run GREEN は実装ギャップではなく
  契約 lock」と区別して記録する規約を確立。

#### Requirements covered

T7.1 → 5.1, 5.2, 5.4 ·
T7.2 → 5.5 ·
T7.3 → 5.1, 5.2, 5.4, 5.5 ·
T7.4 → 5.3 ·
T8.1 → 1.3 ·
T8.2 → 1.3

---

## 2026-05-24 — Task 9: Chat エンドポイント

**Scope**: `POST /chat` を Plan §2.7 + §3.1/§3.2 のフローで実装し、Req 3.1 / 3.2 / 3.4 / 3.5 / 3.6 を完全カバー。`agent.override(model=TestModel())` を `app_with_overrides` フィクスチャ経由で適用し、provider 不要のテストパス (Req 10.2) を確立。`function_model_returning_json` 経由で出力 schema 違反 → 5xx 経路 (Req 3.4) も同時に立証。

### What was done

| Sub-task | File(s) | Outcome |
| -------- | ------- | ------- |
| 9.1 | `tests/unit/test_chat_endpoint_with_testmodel.py` | RED 確認 (`ImportError: cannot import name 'get_chat_agent' from 'pydantic_ai_sandbox.api.deps'`)。2 テスト: 200 返却 + ChatResponse 構造 / 余分キーが付かないこと (`response_model=ChatResponse` 防御の lock)。 |
| 9.2 | `tests/unit/test_chat_endpoint_validation_errors.py` | RED 確認 (同上 ImportError による全テスト collection 失敗)。4 テスト: パラメトリ 422 (3 ケース: 空 body / 型違い / `min_length=1` 違反) + 出力 schema 違反 5xx + `"unexpected"` キーが body に漏れないこと (Req 3.4 partial-data 防御)。 |
| conftest 拡張 | `tests/conftest.py` | T3.1 が明示的に "中身は task 8/9 で拡張するため最小実装に留める" と委譲した `app_with_overrides` フィクスチャの本体を実装。`(model: Model) -> TestClient` を yield する builder 形式 + `contextlib.ExitStack` で `agent.override` の lifecycle 管理。`raise_server_exceptions=False` で 5xx を status code として観測可能に。 |
| 9.3 | `src/pydantic_ai_sandbox/api/deps.py` | GREEN: `get_chat_agent() -> Agent[None, ChatResponse]` を `lru_cache(maxsize=1)` で公開。caching の必然性: `agent.override` は agent インスタンスの ContextVar を変更するため、per-request factory だと override が見えない singleton を返してしまう。 |
| 9.3 | `src/pydantic_ai_sandbox/api/routes/chat.py` | GREEN: `@router.post("/chat", response_model=ChatResponse)` で `async def post_chat(req, agent=Depends(get_chat_agent))`。`await agent.run(req.message)` → `result.output` を返却。例外は FastAPI default に委譲 (Req 3.4)。 |

### Errors and root causes

1. **RUF002 — 全角ダッシュ (EN DASH `–`) docstring 検出**。`Req 3.1–3.6` を docstring に書いたところ ruff の `RUF002` (ambiguous unicode in docstring) が発火。**Root cause**: 日本語まじりの spec を写すときに半角ハイフンと全角ダッシュを混同しやすい。**Fix**: `Req 3.1-3.6` (ASCII hyphen) に置換。**Lesson**: docstring 内で範囲表現を書くときは ASCII `-` を使う。`日本語` 本文中の `—` は `RUF003` 側で扱われ docstring 外なので問題ない。
2. **`ruff format --check` が 2 ファイルで失敗**。`assert response.status_code == 200, (\n    f"... {response.status_code}: {response.text}"\n)` の f-string が 1 行に収まる長さだったため format が括弧を畳み直した。**Fix**: `uv run ruff format tests/unit/test_chat_endpoint_*.py` を 1 度走らせて反映。**Lesson**: T7 で同じパターンに既に当たっており、f-string assertion message は最初から 1 行で書く方が `format` 1 回のラウンドトリップを節約できる。

### Verification

```text
mise run check     → Finished in 2.57s (lint + format + typecheck + 47 tests passed)
  - lint:      All checks passed!
  - format:    (clean — 38 files already formatted)
  - typecheck: 0 errors, 0 warnings, 0 informations
  - test:      47 passed in 0.37s (T9 で +6 テスト: T9.1 ×2, T9.2 ×4)
```

### Learnings carried forward

- **`get_chat_agent` の lru_cache は契約に組み込まれている**。プロダクションでは「build once, override many」の効率上の最適化に見えるが、テストでは agent.override が ContextVar 経由で agent インスタンスの内部状態を変更する関係上、`Depends(get_chat_agent)` が同じインスタンスを返すことが override 見え方の必要条件である。`@lru_cache` を外すと test fixture が override したインスタンスと、route handler が `Depends` 経由で得るインスタンスが別物になり、テストは silent pass する 5xx 経路だけ正しく動き 200 経路が壊れる、という静かな汚染を起こす。コメントで明示しておくこと。
- **`raise_server_exceptions=False` フラグの選択基準**。TestClient のデフォルトは server (5xx) 例外を test process に re-raise し、client (4xx) 例外は HTTP response として返す。Req 3.4 のように 5xx を「status code として」観測したい場合は False を選ぶ。422 系のテストには影響しないので、共有 fixture では False で固定して問題なし。
- **`app_with_overrides` の builder 形式**。fixture が直接 TestClient を yield するのではなく `(model) -> TestClient` を yield する関数形式にしたのは、T9.2 が複数の異なる model (TestModel と FunctionModel) で同一テストフローを走らせるため。一テストで複数 model を切り替える必要があるケースは T11 の integration テストでも再利用しうる (e.g. 一連の retry 検証)。`ExitStack` で override を tracked に積むことで、二度目の builder 呼び出しは前の override の上に新しい override を重ねる semantics になる (LIFO で teardown)。
- **`function_model_returning_json` の output validation 経路は `UnexpectedModelBehavior("Exceeded maximum output retries (1)")` を投げる**。pydantic-ai V2 の output coercion は失敗時にリトライを使い果たしてからこの例外を出す。テストは exception class や message ではなく status code 範囲 (`500 <= code < 600`) と body 中の禁則文字列 (`"unexpected" not in response.text`) で contract を pin することで、upstream phrasing 変更に脆弱でない net を張った。
- **conftest 拡張の cross-task glue**。T3.1 の "task 8/9 で拡張するため最小実装に留める" コメントが今回 conftest 編集の license として機能した。同種の「将来の task で body を埋める」フィクスチャ skeleton は今後も `app_with_overrides` パターンに従って書き、license コメントを skeleton 側にも明示する規約を確立すると、boundary 違反かどうかが review 時に争点にならない。
- **chat router 登録の置き場**。T9.3 boundary は `api/routes/chat.py + api/deps.py` のみで `main.py` を含まない。T10.2 が `create_app()` でルータ登録を担う設計のため、T9 では fixture 側で `app.include_router(chat_router)` を実行した。T10.2 完了時に fixture から除去すべき glue が 1 行残ることを fixture docstring と本ログで明文化。

#### Requirements covered

T9.1 → 3.1, 3.2, 3.5 ·
T9.2 → 3.4, 3.6 ·
T9.3 → 3.1, 3.2, 3.3, 3.4, 3.5, 3.6
