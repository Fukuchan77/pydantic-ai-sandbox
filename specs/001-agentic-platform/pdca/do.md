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
