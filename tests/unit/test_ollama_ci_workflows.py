"""Structural contract guard for the Ollama live-integration CI workflows.

``.github/workflows/integration-ollama.yml`` and
``.github/workflows/patterns-integration-ollama.yml`` are never exercised by
pytest at runtime, so this hermetic static guard pins their load-bearing
contract the same way ``test_watsonx_ci_workflow.py`` guards the watsonx lane:
parse the YAML and assert the cost-control invariants the CI optimization
depends on. Live 8B Ollama inference is slow and was consuming the GitHub
Actions usage budget, so both lanes are triggered exclusively by
``workflow_dispatch``. A future edit that silently re-adds a push /
pull_request / schedule trigger (re-inflating the usage budget) fails here.

Also pinned: ``security.yml``'s cron routing. Its jobs route on
``github.event.schedule == '<cron string>'`` job-level ``if:`` expressions,
which GitHub compares byte-for-byte against the ``on.schedule`` list — an
edit to one side without the other silently stops a scheduled job from ever
running, so every cron string referenced in an ``if:`` must appear verbatim
in ``on.schedule``.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, cast

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"

# The two live-Ollama lanes that MUST stay manual-only (usage-limit control).
OLLAMA_WORKFLOWS: tuple[str, ...] = (
    "integration-ollama.yml",
    "patterns-integration-ollama.yml",
)

SECURITY_WORKFLOW = WORKFLOWS_DIR / "security.yml"


def _load_workflow(path: Path) -> dict[str, Any]:
    """Parse the workflow YAML, asserting it exists and is a mapping.

    ``yaml.safe_load`` is typed ``-> Any``; ``isinstance`` narrows it to a bare
    ``dict[Unknown, Unknown]`` which pyright strict rejects, so the verified
    mapping is ``cast`` to ``dict[str, Any]`` (project convention).
    """
    assert path.exists(), f"workflow file missing: {path.relative_to(REPO_ROOT)}"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict), "workflow YAML did not parse to a top-level mapping"
    # ``dict[Any, Any]`` (not ``dict[str, Any]``): YAML 1.1 may resolve the
    # ``on:`` key to the bool ``True``, so keys are not necessarily ``str``.
    return cast("dict[Any, Any]", data)


def _on_section(data: dict[Any, Any]) -> Any:
    """Return the ``on:`` trigger mapping, tolerating PyYAML's keyword quirk.

    PyYAML (YAML 1.1) resolves the unquoted ``on:`` key to the boolean
    ``True``; GitHub Actions means the string ``"on"``. Accept either key so
    the test pins workflow behaviour rather than the parser's quirk.
    """
    if "on" in data:
        return data["on"]
    return data[True]


def _jobs(data: dict[Any, Any]) -> dict[str, Any]:
    """Return the ``jobs:`` mapping."""
    jobs = data.get("jobs")
    assert isinstance(jobs, dict), "workflow has no `jobs:` mapping"
    return cast("dict[str, Any]", jobs)


@pytest.mark.parametrize("workflow_name", OLLAMA_WORKFLOWS)
def test_triggered_exclusively_by_workflow_dispatch(workflow_name: str) -> None:
    data = _load_workflow(WORKFLOWS_DIR / workflow_name)
    on = _on_section(data)
    assert isinstance(on, dict), f"`on:` should be a mapping of triggers, got {on!r}"
    on_keys = set(cast("dict[str, Any]", on))
    assert on_keys == {"workflow_dispatch"}, (
        f"{workflow_name} MUST be triggered exclusively by workflow_dispatch "
        f"(Actions usage-limit control); found triggers {on_keys!r}. push / "
        "pull_request / schedule would run live 8B Ollama inference "
        "automatically and re-inflate the usage budget this optimization "
        "reclaimed."
    )


@pytest.mark.parametrize("workflow_name", OLLAMA_WORKFLOWS)
def test_declares_concurrency_controls(workflow_name: str) -> None:
    """Duplicate manual dispatches on one ref must collapse to a single run.

    ``integration-ollama.yml`` declares concurrency at workflow level;
    ``patterns-integration-ollama.yml`` declares it per job (keyed by matrix
    lane). Accept either shape, but every job must be covered by one of them.
    """
    data = _load_workflow(WORKFLOWS_DIR / workflow_name)

    def _valid_concurrency(block: Any) -> bool:
        if not isinstance(block, dict):
            return False
        block = cast("dict[str, Any]", block)
        return bool(block.get("group")) and "cancel-in-progress" in block

    if _valid_concurrency(data.get("concurrency")):
        return
    jobs = _jobs(data)
    uncovered = [
        job_id
        for job_id, job in jobs.items()
        if not _valid_concurrency(cast("dict[str, Any]", job).get("concurrency"))
    ]
    assert not uncovered, (
        f"{workflow_name}: no workflow-level `concurrency:` block, and job(s) "
        f"{uncovered!r} declare no job-level concurrency either. Without it, "
        "duplicate manual dispatches run live Ollama inference concurrently "
        "instead of collapsing to one active run."
    )


def test_security_cron_routing_strings_match() -> None:
    """Every cron string referenced by a job `if:` must exist in on.schedule.

    security.yml routes jobs to the daily/weekly crons via
    ``github.event.schedule == '<cron>'``, which GitHub compares byte-for-byte
    against the triggering entry of ``on.schedule``. A cron edited on one side
    only would silently stop the routed job from ever running on schedule.
    """
    data = _load_workflow(SECURITY_WORKFLOW)
    on = _on_section(data)
    assert isinstance(on, dict), f"`on:` should be a mapping of triggers, got {on!r}"
    schedule = cast("dict[str, Any]", on).get("schedule")
    assert isinstance(schedule, list), "security.yml must declare an `on.schedule` list"
    declared = {
        cast("dict[str, Any]", entry)["cron"]
        for entry in cast("list[Any]", schedule)
        if isinstance(entry, dict)
    }
    assert declared, "security.yml declares no cron entries"

    raw = SECURITY_WORKFLOW.read_text(encoding="utf-8")
    referenced = set(re.findall(r"github\.event\.schedule == '([^']+)'", raw))
    assert referenced, (
        "security.yml declares schedule triggers but no job routes on "
        "`github.event.schedule` — scheduled runs would execute every job, "
        "defeating the daily-vs-weekly split."
    )
    orphaned = referenced - declared
    assert not orphaned, (
        f"job `if:` expressions reference cron string(s) {sorted(orphaned)!r} that are "
        f"not declared in on.schedule {sorted(declared)!r}; the routed job(s) would "
        "never run on schedule. Keep both sides byte-identical."
    )
