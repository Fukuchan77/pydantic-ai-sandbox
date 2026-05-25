# pydantic-ai-sandbox

A sandbox repository for experimenting with **Pydantic AI V2 (Beta) + FastAPI + multi-provider LLM routing**. The design lives in [specs/inputs/idea0.md](specs/inputs/idea0.md); the binding rules live in [.sdd/memory/constitution.md](.sdd/memory/constitution.md).

## Onboarding

The fastest path from a fresh clone to a green quality-gate run:

```bash
git clone <repo-url> pydantic-ai-sandbox
cd pydantic-ai-sandbox
mise install            # provisions Python 3.14 and uv (mise.toml)
mise run setup          # equivalent to: uv sync && uv run pre-commit install
cp .env.example .env    # then fill in any secrets you need locally
mise run check          # lint + format-check + pyright + pytest (Constitution V)
```

`mise run setup` is the canonical bootstrap; it is intentionally idempotent so
re-running after pulling main is safe.

## Day-to-day commands

All quality gates flow through `mise` — never invoke bare `ruff` / `pyright` /
`pytest` (Constitution V / [CLAUDE.md](CLAUDE.md)). Available tasks:

| Task                          | Purpose                                                        |
| ----------------------------- | -------------------------------------------------------------- |
| `mise run lint`               | `ruff check .`                                                 |
| `mise run format`             | `ruff format --check .`                                        |
| `mise run typecheck`          | `pyright` (strict, Python 3.14)                                |
| `mise run test`               | `pytest` (asyncio auto mode)                                   |
| `mise run check`              | Aggregate gate — lint + format + typecheck + test              |
| `mise run pre-commit:default` | Run the default pre-commit stage on all files                  |
| `mise run pre-commit:manual`  | Run the manual stage (pytest / pip-audit)                      |
| `mise run test:integration`   | Live-Ollama integration lane (sets `RUN_INTEGRATION_OLLAMA=1`) |

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
**never** hardcoded in `src/` — see [CLAUDE.md](CLAUDE.md) "Model-ID hygiene"
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

In CI, the same lane runs on push-to-main, weekly cron, and any pull-request
that touches the LLM router / agents / schemas / integration tests
([specs/001-agentic-platform/tasks.md](specs/001-agentic-platform/tasks.md) T12.3).

## Specs and process

Non-trivial features flow through the SDD pipeline:

```
/sdd-init → /sdd-spec → /sdd-design → /sdd-tasks → /sdd-impl
         → /sdd-validate-impl → /sdd-reflect
```

Specifications live under `specs/{feature}/`; reviews under `.sdd/reviews/`;
the active feature is [001-agentic-platform](specs/001-agentic-platform/). For
small, contained changes use `/dev-discovery` instead.
