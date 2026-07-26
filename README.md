# pydantic-ai-sandbox

A sandbox repository for experimenting with **Pydantic AI V2 (Beta) + FastAPI + multi-provider LLM routing**. The design lives in [specs/inputs/idea0.md](specs/inputs/idea0.md); the binding rules live in `.sdd/memory/constitution.md`.

> **Note:** `.sdd/` and `CLAUDE.md` are git-ignored, locally-generated SDD
> artifacts (see [.gitignore](.gitignore)) — they are not present in a fresh
> clone. References to them below point at these local-only files.

## Onboarding

The fastest path from a fresh clone to a green quality-gate run:

```bash
git clone <repo-url> pydantic-ai-sandbox
cd pydantic-ai-sandbox
mise install            # provisions Python 3.13 and uv (mise.toml)
mise run setup          # equivalent to: uv sync && uv run pre-commit install
cp .env.example .env    # then fill in any secrets you need locally
mise run check          # lint + format-check + pyright + pytest (Constitution V)
```

`mise run setup` is the canonical bootstrap; it is intentionally idempotent so
re-running after pulling main is safe.

## Day-to-day commands

All quality gates flow through `mise` — never invoke bare `ruff` / `pyright` /
`pytest` (Constitution V / `CLAUDE.md`). Available tasks:

| Task                          | Purpose                                                        |
| ----------------------------- | -------------------------------------------------------------- |
| `mise run lint`               | `ruff check .`                                                 |
| `mise run format`             | `ruff format --check .`                                        |
| `mise run typecheck`          | `pyright` (strict, Python 3.13)                                |
| `mise run test`               | `pytest` (asyncio auto mode)                                   |
| `mise run check`              | Aggregate gate — lint + format + typecheck + test              |
| `mise run check:static`       | Aggregate gate without tests (what CI pairs with `cov:xml`)    |
| `mise run cov`                | Coverage-gated run (`fail_under` ratchet)                      |
| `mise run cov:xml`            | Same, plus `coverage.xml` for the CI diff-coverage comment     |
| `mise run pre-commit:default` | Run the default pre-commit stage on all files                  |
| `mise run pre-commit:manual`  | Run the manual stage (pytest / pip-audit)                      |
| `mise run test:integration`   | Live-Ollama integration lane (sets `RUN_INTEGRATION_OLLAMA=1`) |
| `mise run test:integration:pre-push` | The same lane exactly as the pre-push hook runs it       |

Run a single test file under the same ground rules:

```bash
uv run pytest tests/unit/test_config.py::test_some_case
```

## Switching LLM providers

Provider selection is **env-var driven**; nothing about the choice lives in
code. Edit `.env` (copied from [.env.example](.env.example)) and toggle:

```dotenv
LLM_PROVIDER=ollama       # ollama | watsonx | anthropic | bedrock | fallback
OLLAMA_MODEL_NAME=...     # required when LLM_PROVIDER=ollama
FALLBACK_ORDER=ollama     # required when LLM_PROVIDER=fallback
```

`Settings` (loaded by `pydantic-settings`) validates env at startup and
fail-fasts on missing required variables (Req 1.2 / Req 4.5). Model IDs are
**never** hardcoded in `src/` — see `CLAUDE.md` "Model-ID hygiene"
and the `forbid-hardcoded-model-ids` pre-commit hook for the enforced rule.

## Running the FastAPI app

The app entry point is `pydantic_ai_sandbox.main:app` (defined in
[src/pydantic_ai_sandbox/main.py](src/pydantic_ai_sandbox/main.py)).

```bash
mise run dev      # uvicorn + --reload (development)
mise run serve    # uvicorn on 0.0.0.0:8000 (production-style, no reload)

# Equivalent without mise:
uv run uvicorn pydantic_ai_sandbox.main:app --reload --env-file .env
uv run uvicorn pydantic_ai_sandbox.main:app --host 0.0.0.0 --port 8000 --env-file .env
```

## Integration testing against a live Ollama

The Ollama lane is opt-in to keep the default `pytest` run hermetic.

```bash
# Ensure ollama is running locally:
ollama serve &
ollama pull granite4.1:8b   # or whatever OLLAMA_MODEL_NAME is pinned to

# Then either:
mise run test:integration                       # uses mise's preset env
# or, equivalently:
RUN_INTEGRATION_OLLAMA=1 uv run pytest tests/integration
```

### The lane runs on `git push`, not in CI

Live 8B inference is slow and environment-bound, so it is **not** a GitHub
Actions gate. It runs from a `pre-push` hook instead
([scripts/pre-push-ollama.sh](scripts/pre-push-ollama.sh)), wired through
pre-commit's pre-push stage:

```bash
mise run setup   # required once on an existing clone: installs .git/hooks/pre-push
```

The hook probes the daemon first and **warns-and-skips when nothing is
listening**, so a docs-only push from a machine without Ollama is never
blocked. Controls:

| Variable / flag             | Effect                                                  |
| --------------------------- | ------------------------------------------------------- |
| `REQUIRE_OLLAMA_PREPUSH=1`  | Treat a missing daemon as a hard failure instead of skip |
| `SKIP_OLLAMA_PREPUSH=1`     | Skip the lane even when the daemon is up                 |
| `SKIP=ollama-integration`   | pre-commit's own per-hook skip variable                  |
| `git push --no-verify`      | Bypass every pre-push hook                               |

## CI cost policy

GitHub Actions usage is deliberately constrained (see the header comment in
each workflow for the full rationale):

| Workflow                          | Triggers                                             |
| --------------------------------- | ---------------------------------------------------- |
| `ci.yml`                          | pull request + manual dispatch                       |
| `patterns-ci.yml`                 | pull request (patterns paths) + manual dispatch      |
| `security.yml`                    | pull request + **daily** pip-audit + weekly gitleaks |
| `integration-ollama.yml`          | manual dispatch only (runs pre-push locally instead) |
| `patterns-integration-ollama.yml` | manual dispatch only                                 |
| `integration-watsonx.yml`         | manual dispatch only (metered SaaS)                  |

Rules of thumb: nothing is scheduled except security scanning; no workflow
re-runs a commit on push-to-main because the pull-request run already gated it;
`ci.yml` runs the test suite exactly once. These invariants are pinned by
[tests/unit/test_ci_usage_policy.py](tests/unit/test_ci_usage_policy.py) and
`tests/unit/test_ollama_ci_workflows.py`, so an edit that quietly re-inflates
the budget fails the suite.

## Specs and process

Non-trivial features flow through the SDD pipeline:

```
/sdd-init → /sdd-spec → /sdd-design → /sdd-tasks → /sdd-impl
         → /sdd-validate-impl → /sdd-reflect
```

Specifications live under `specs/{feature}/`; reviews under `.sdd/reviews/`;
the active feature is [001-agentic-platform](specs/001-agentic-platform/). For
small, contained changes use `/dev-discovery` instead.
