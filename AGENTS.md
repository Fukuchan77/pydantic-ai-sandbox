# AGENTS.md

`.gitignore` excludes `CLAUDE.md` and `.sdd/` — the home of this project's design
docs and constitution — so a fresh clone has no agent-facing contract at all. That
exclusion is a deliberate choice, not an oversight: this project's stance is that
enforceable rules belong in **tests**, not prose, and this file does not reopen
that decision. See `tests/unit/test_ci_usage_policy.py`,
`tests/unit/test_no_hardcoded_model_ids.py`,
`tests/unit/test_security_workflow_lanes.py`, and
`patterns/contracts/tests/unit/test_contract_drift.py` for what "rules-as-tests"
looks like here — those are the actual source of truth for what is and is not
allowed, and they will fail loudly if you violate them.

This file carries only the handful of "why"s a test cannot express: the reasoning
behind a few structural decisions that would otherwise look arbitrary, or worse,
look like something you should "fix" by undoing them.

## Why `patterns/` has no vendored code (Constitution Principle III)

Principle III forbids vendoring: copying a dependency's or a sibling lane's code
wholesale into this repository. When two lanes need the same behavior (e.g. the
`observability.py` tracing shim duplicated across the `llamaindex` and `rag`
lanes), the correct move is for each lane to **re-implement it independently
against the same contract**, not to copy-paste or symlink one lane's module into
another (`specs/007-2b-cross-platform/plan.md`, `tasks.md` R8.1 / NFR-3).

If you are asked to "reduce duplication" between lanes, do not vendor or share
files across lane boundaries. The only sanctioned form of sharing is
`patterns/contracts` — a real dependency each lane installs, containing pure
`pydantic` models and nothing else (see the "no vendoring" reasoning again in
`patterns/contracts/README.md`).

## Why quality gates run through one command (Constitution Principle V)

Principle V requires a **single entry point** for quality gates: `mise run check`
runs lint, format, typecheck, and test as one aggregate gate, and both local
development and CI (`.github/workflows/ci.yml`) invoke that same entry point
rather than each reimplementing the step list. The point is not "these four
checks happen to run" — it's that there is exactly one place that defines what
"green" means, so CI and a developer's machine can never silently diverge on
what passes.

If you add a new check, wire it into the `mise` task that gates `check`, not as
a parallel step bolted only onto CI (or only onto a pre-commit hook).

## Why `patterns/` is split into 8 independent lanes instead of one workspace

This is not an organizational preference — it is a hard version constraint.
`beeai-framework` declares `requires-python >=3.11,<3.14`, while the rest of the
stack targets `>=3.13`/`>=3.14`. A single `uv` workspace requires one resolution
that satisfies every member simultaneously, and the intersection of those ranges
with the beeai floor is empty: no single interpreter version can satisfy both.
That makes one shared workspace structurally impossible, not merely
inconvenient (`specs/005-cross-platform/research.md` R-3).

Each lane (`contracts`, `frameworks/{beeai,llamaindex,pydantic-ai}`, `rag`, `sse`,
`deep-research`, `hitl`) is therefore its own independent `uv` project with its
own lockfile, its own `.python-version`, and its own CI job. Do not try to
collapse them into one workspace or one lockfile "for consistency" — that
reintroduces the exact conflict this split exists to avoid. Cross-lane sharing
goes through `patterns/contracts` (a path dependency), never through a shared
workspace root.
