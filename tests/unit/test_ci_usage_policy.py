"""Structural guard for the GitHub Actions usage-reduction policy.

Companion to ``test_ollama_ci_workflows.py`` (which pins the live-Ollama lanes
to ``workflow_dispatch`` only). This module pins the *rest* of the cost-control
decisions, none of which are exercised by pytest at runtime and all of which
are easy to undo by accident:

* No workflow re-runs a commit on ``push`` to main — the pull-request run
  already gated the identical tree, so a push trigger doubles every run.
* ``ci.yml`` runs the test suite exactly once (it used to run it three times:
  ``check`` → ``pre-commit:manual`` → a separate coverage invocation).
* Only security scanning is scheduled — the daily cron must never grow a job
  that is not a dependency audit or a secret scan.
* Dependabot checks monthly with a small open-PR cap, because every Dependabot
  PR fans out into a full CI matrix.
* The live-Ollama lane that GitHub no longer runs automatically is actually
  wired into the local ``pre-push`` stage, so it still gates real pushes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"
PRE_COMMIT_CONFIG = REPO_ROOT / ".pre-commit-config.yaml"
DEPENDABOT_CONFIG = REPO_ROOT / ".github" / "dependabot.yml"
PRE_PUSH_SCRIPT = REPO_ROOT / "scripts" / "pre-push-ollama.sh"

# Every automatically-triggered workflow. The dispatch-only lanes
# (integration-ollama, patterns-integration-ollama, integration-watsonx) are
# covered by their own guards and have no push trigger to lose.
AUTO_WORKFLOWS: tuple[str, ...] = (
    "ci.yml",
    "patterns-ci.yml",
    "security.yml",
)

# security.yml is the only scheduled workflow, and every one of its jobs must
# be a security scan. Adding a non-scanning job here would put it on the daily
# cron by default (a job without an `if:` runs on every trigger).
SECURITY_JOB_IDS: frozenset[str] = frozenset({"pip-audit", "patterns-pip-audit", "gitleaks"})


def _load_yaml(path: Path) -> dict[Any, Any]:
    """Parse a YAML config, asserting it exists and is a top-level mapping."""
    assert path.exists(), f"config file missing: {path.relative_to(REPO_ROOT)}"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict), f"{path.name} did not parse to a top-level mapping"
    # ``dict[Any, Any]`` (not ``dict[str, Any]``): YAML 1.1 may resolve the
    # ``on:`` key to the bool ``True``, so keys are not necessarily ``str``.
    return cast("dict[Any, Any]", data)


def _on_section(data: dict[Any, Any]) -> dict[str, Any]:
    """Return the ``on:`` trigger mapping, tolerating PyYAML's keyword quirk.

    PyYAML (YAML 1.1) resolves the unquoted ``on:`` key to the boolean
    ``True``; GitHub Actions means the string ``"on"``.
    """
    on = data["on"] if "on" in data else data[True]
    assert isinstance(on, dict), f"`on:` should be a mapping of triggers, got {on!r}"
    return cast("dict[str, Any]", on)


def _jobs(data: dict[Any, Any]) -> dict[str, Any]:
    """Return the ``jobs:`` mapping."""
    jobs = data.get("jobs")
    assert isinstance(jobs, dict), "workflow has no `jobs:` mapping"
    return cast("dict[str, Any]", jobs)


@pytest.mark.parametrize("workflow_name", AUTO_WORKFLOWS)
def test_no_push_trigger(workflow_name: str) -> None:
    on = _on_section(_load_yaml(WORKFLOWS_DIR / workflow_name))
    assert "push" not in on, (
        f"{workflow_name} declares a `push:` trigger. Every change reaches main "
        "through a pull request, and the PR run already gated that exact tree, so "
        "a push trigger runs the whole matrix a second time for no new signal "
        "(Actions usage-limit control). Re-run main manually via workflow_dispatch "
        "if a post-merge run is genuinely needed."
    )


@pytest.mark.parametrize("workflow_name", AUTO_WORKFLOWS)
def test_pull_request_trigger_retained(workflow_name: str) -> None:
    """Cost control must not become 'no gate at all'."""
    on = _on_section(_load_yaml(WORKFLOWS_DIR / workflow_name))
    assert "pull_request" in on, (
        f"{workflow_name} lost its `pull_request:` trigger. With `push:` already "
        "retired, this workflow would never run automatically."
    )


def test_ci_runs_the_test_suite_exactly_once() -> None:
    """ci.yml used to run pytest three times for one set of results."""
    jobs = _jobs(_load_yaml(WORKFLOWS_DIR / "ci.yml"))
    # Only executed `run:` commands are inspected — the file's header comment
    # legitimately names the retired tasks while explaining why they are gone.
    commands = [
        str(cast("dict[str, Any]", step).get("run", "")).strip()
        for job in jobs.values()
        for step in cast("list[Any]", cast("dict[str, Any]", job).get("steps", []))
        if isinstance(step, dict)
    ]

    # `check` would re-run the test gate that `cov:xml` already owns; the manual
    # pre-commit stage would re-run both pytest and pip-audit. The aggregate is
    # matched on the whole command so `check:static` is not caught by it.
    aggregate = {"mise run check", 'mise run "check"'}
    for offenders, why in (
        ([cmd for cmd in commands if cmd in aggregate], "it includes the test gate `cov:xml` runs"),
        (
            [cmd for cmd in commands if "pre-commit:manual" in cmd],
            "the manual stage re-runs pytest + pip-audit",
        ),
    ):
        assert not offenders, (
            f"ci.yml invokes a duplicate gate ({offenders!r}): {why}. Use "
            "`check:static` + `cov:xml` (+ `pre-commit:validate`) so the suite runs once."
        )

    suite_runs = [cmd for cmd in commands if "cov:xml" in cmd or "pytest" in cmd]
    assert len(suite_runs) == 1, (
        f"ci.yml has {len(suite_runs)} step(s) running the test suite ({suite_runs!r}); "
        "exactly one is expected — `mise run cov:xml` produces the pass/fail gate, the "
        "coverage ratchet and coverage.xml in a single invocation."
    )


def test_only_security_jobs_are_scheduled() -> None:
    """The daily/weekly crons must carry security scanning and nothing else."""
    data = _load_yaml(WORKFLOWS_DIR / "security.yml")
    unexpected = set(_jobs(data)) - SECURITY_JOB_IDS
    assert not unexpected, (
        f"security.yml gained non-scanning job(s) {sorted(unexpected)!r}. It is the only "
        "scheduled workflow in the repository, and a job without an `if:` runs on every "
        "cron — scheduled usage is reserved for dependency audits and secret scans."
    )

    scheduled = {
        path.name
        for path in sorted(WORKFLOWS_DIR.glob("*.yml"))
        if "schedule" in _on_section(_load_yaml(path))
    }
    assert scheduled == {"security.yml"}, (
        f"expected security.yml to be the only workflow with a `schedule:` trigger, "
        f"found {sorted(scheduled)!r}."
    )


def test_dependabot_cadence_is_monthly_and_capped() -> None:
    updates = _load_yaml(DEPENDABOT_CONFIG).get("updates")
    assert isinstance(updates, list), "dependabot.yml must declare an `updates:` list"

    for entry in cast("list[Any]", updates):
        assert isinstance(entry, dict)
        block = cast("dict[str, Any]", entry)
        ecosystem = block.get("package-ecosystem")
        schedule = cast("dict[str, Any]", block.get("schedule", {}))
        assert schedule.get("interval") == "monthly", (
            f"dependabot `{ecosystem}` block checks on interval "
            f"{schedule.get('interval')!r}; monthly is the agreed cadence because each "
            "Dependabot PR triggers ci + security (+ patterns-ci). A newly filed CVE is "
            "still caught within a day by security.yml's pip-audit cron."
        )
        # `day:` only applies to weekly checks; leaving it on a monthly block is
        # silently ignored and misleads the next reader.
        assert "day" not in schedule, (
            f"dependabot `{ecosystem}` block sets `day:` on a monthly schedule, where "
            "Dependabot ignores it (monthly checks run on the 1st at `time`)."
        )
        limit = block.get("open-pull-requests-limit")
        assert isinstance(limit, int) and limit <= 3, (
            f"dependabot `{ecosystem}` block allows {limit!r} concurrent PRs; the cap is 3 "
            "so a batch of bumps cannot queue a dozen full CI matrices at once."
        )


def test_ollama_lane_runs_on_pre_push() -> None:
    """The lane GitHub no longer runs automatically must gate pushes locally."""
    config = _load_yaml(PRE_COMMIT_CONFIG)

    install_types = config.get("default_install_hook_types")
    assert isinstance(install_types, list), "`default_install_hook_types` must be a list"
    assert "pre-push" in cast("list[Any]", install_types), (
        "`.pre-commit-config.yaml` does not install the pre-push hook type, so "
        "`pre-commit install` would never wire .git/hooks/pre-push and the live-Ollama "
        "lane would run nowhere: GitHub's integration-ollama.yml is dispatch-only."
    )

    pre_push_hooks = [
        cast("dict[str, Any]", hook)
        for repo in cast("list[Any]", config.get("repos", []))
        for hook in cast("list[Any]", cast("dict[str, Any]", repo).get("hooks", []))
        if isinstance(hook, dict) and "pre-push" in cast("dict[str, Any]", hook).get("stages", [])
    ]
    assert pre_push_hooks, "no hook declares `stages: [pre-push]`"

    entries = [str(hook.get("entry", "")) for hook in pre_push_hooks]
    assert any(PRE_PUSH_SCRIPT.name in entry for entry in entries), (
        f"no pre-push hook invokes {PRE_PUSH_SCRIPT.name}; found entries {entries!r}."
    )
    assert PRE_PUSH_SCRIPT.exists(), f"missing {PRE_PUSH_SCRIPT.relative_to(REPO_ROOT)}"


def test_pre_push_script_skips_cleanly_without_a_daemon() -> None:
    """A machine with no Ollama daemon must still be able to push."""
    body = PRE_PUSH_SCRIPT.read_text(encoding="utf-8")
    assert "REQUIRE_OLLAMA_PREPUSH" in body, (
        "the pre-push script must offer an opt-in strict mode "
        "(REQUIRE_OLLAMA_PREPUSH=1) for machines where the daemon is always up."
    )
    assert "/api/tags" in body, (
        "the pre-push script must probe the daemon before running the lane; without a "
        "liveness check a developer with no daemon gets a wall of connection errors "
        "instead of a skip."
    )
