# PDCA — Do Phase: 002-watsonx-provider

Continuous implementation log. Newest entries at the bottom of each task.

---

## Task 1 — Dependencies, lockfile & coverage ratchet

**Date:** 2026-06-08 · **Status:** ✅ Done · **Boundary:** `pyproject.toml`, `.github/dependabot.yml`

### 1.1 — Dependency bump + optional litellm + coverage ratchet

**TDD framing (config task):** the verifiable assertion is the SDK import.

- **RED** — with the locked `ibm-watsonx-ai==1.5.12`:
  ```
  from ibm_watsonx_ai.foundation_models import ModelInference
  TypeError: object.__init__() takes exactly one argument (the instance to initialize)
    at ibm_watsonx_ai/utils/utils.py:1191  (StrEnum member construction, py3.14.5)
  ```
  Reproduces ADR-1 exactly.
- **GREEN** — after bumping to `>=1.5.13` and `uv sync --extra litellm`:
  ```
  version: 1.5.13
  ModelInference import: OK
  python: 3.14.5
  ```
- Edits to `pyproject.toml`: `ibm-watsonx-ai>=1.5.13` (with ADR-1 comment);
  new `[project.optional-dependencies] litellm = ["litellm"]`;
  `[tool.coverage.report] fail_under` 93 → 98.
- `uv.lock` regenerated: `ibm-watsonx-ai 1.5.13`, `litellm 1.89.0rc1` locked.

### 1.2 — Dependabot supply-chain-watch registration

- Added `ibm-watsonx-ai` to `groups.python-minor-and-patch.exclude-patterns`
  (joins `litellm`) so its bumps surface as standalone, never-auto-grouped PRs.
- Documented both packages as the registered watchlist with rationale
  (litellm 2026-03 yank; ibm-watsonx-ai ADR-1 py3.14 break).

### Root-cause note — coverage ratchet vs. task ordering

Raising `fail_under` to 98 in 1.1 precedes the watsonx tests (tasks 5–7), so
measured coverage is **97.40%**. Investigated where the floor is enforced:

- `mise run test` = bare `uv run pytest` (no `--cov`, Constitution V) → **GREEN**;
  canonical `mise run check` gate unaffected.
- CI `ci.yml:85` runs `uv run pytest --cov` → reports **97.40% < 98%** until
  task 11.1. This is the planned Req 9.10 split (1.1 raises, 11.1 confirms),
  not a defect. Self-resolves once SDK/LiteLLM branches are covered.

### Verification evidence

| Gate | Command | Result |
|------|---------|--------|
| Tests | `mise run test` | ✅ 57 passed, 1 skipped |
| Lint | `mise run lint` | ✅ All checks passed |
| Typecheck | `mise run typecheck` | ✅ 0 errors, 0 warnings |
| Import | `python -c "from ibm_watsonx_ai.foundation_models import ModelInference"` | ✅ OK on 3.14.5 |
| Coverage (CI-only) | `uv run pytest --cov` | ⚠️ 97.40% < 98% — expected until task 11.1 |

### Learnings for Act phase

- The coverage ratchet should ideally rise in the *same* wave as the covering
  tests, or the CI `--cov` step stays red across intermediate commits. The
  project's decoupling of coverage from `mise run test` softens this (local
  gate stays green), but PR CI does not.
- Dependabot v2 has no per-dependency label mechanism; the watchlist pattern
  (exclude-patterns + external label-bump workflow) is the project's idiom.
