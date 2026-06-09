"""Structural contract guard for the watsonx CI integration workflow (Task 9).

``.github/workflows/integration-watsonx.yml`` is never exercised by pytest at
runtime, so this hermetic static guard pins its load-bearing contract the same
way ``test_no_hardcoded_model_ids.py`` guards source files: parse the YAML and
assert the cost-control + fail-not-skip invariants that Req 11.1-11.3 / SC-007
depend on. A future edit that silently re-adds a push / pull_request / cron
trigger (blowing the live-API budget) or drops the missing-secret guard (letting
the lane go green-by-skip) fails here.

Covered acceptance criteria:

* 11.1 - all four ``WATSONX_*`` credentials are wired from CI ``secrets``.
* 11.2 / SC-007 - the workflow is triggered *exclusively* by
  ``workflow_dispatch`` and declares concurrency controls.
* 11.3 - a step explicitly fails (non-zero exit) when a required secret is
  absent, rather than skipping.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "integration-watsonx.yml"

# The four credentials the live watsonx lane cannot run without. Mirrors the
# Task 2.2 credential gate's required set; CI must wire each from secrets.
REQUIRED_SECRETS: tuple[str, ...] = (
    "WATSONX_APIKEY",
    "WATSONX_PROJECT_ID",
    "WATSONX_URL",
    "WATSONX_MODEL_ID",
)


def _load_workflow() -> dict[str, Any]:
    """Parse the workflow YAML, asserting it exists and is a mapping.

    ``yaml.safe_load`` is typed ``-> Any``; ``isinstance`` narrows it to a bare
    ``dict[Unknown, Unknown]`` which pyright strict rejects, so the verified
    mapping is ``cast`` to ``dict[str, Any]`` (project convention).
    """
    assert WORKFLOW.exists(), f"workflow file missing: {WORKFLOW.relative_to(REPO_ROOT)} (Task 9.1)"
    data = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
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


def _iter_run_steps(data: dict[Any, Any]) -> list[dict[str, Any]]:
    """Flatten every step (mapping) across all jobs into a single list."""
    steps: list[dict[str, Any]] = []
    jobs = cast("dict[str, Any]", data.get("jobs") or {})
    for job in jobs.values():
        for step in cast("list[Any]", job.get("steps") or []):
            if isinstance(step, dict):
                steps.append(cast("dict[str, Any]", step))
    return steps


def test_triggered_exclusively_by_workflow_dispatch() -> None:
    data = _load_workflow()
    on = _on_section(data)
    assert isinstance(on, dict), f"`on:` should be a mapping of triggers, got {on!r}"
    on_keys = set(cast("dict[str, Any]", on))
    assert on_keys == {"workflow_dispatch"}, (
        "the watsonx integration lane MUST be triggered exclusively by "
        f"workflow_dispatch (Req 11.2 / SC-007 cost control); found triggers {on_keys!r}. "
        "push / pull_request / schedule would run the live-API lane automatically and "
        "blow the integration-test budget."
    )


def test_declares_concurrency_controls() -> None:
    data = _load_workflow()
    concurrency = data.get("concurrency")
    assert isinstance(concurrency, dict), (
        "Req 11.2 requires concurrency controls; the `concurrency:` block is missing or malformed."
    )
    concurrency = cast("dict[str, Any]", concurrency)
    assert concurrency.get("group"), "concurrency.group must be set"
    assert "cancel-in-progress" in concurrency, (
        "concurrency.cancel-in-progress must be declared so duplicate manual dispatches "
        "collapse to one active run."
    )


def test_all_four_credentials_wired_from_secrets() -> None:
    # Parse first so a malformed file fails loudly here too, then assert the
    # secret wiring against the raw text (the `${{ secrets.X }}` expression is
    # the wiring contract, regardless of which step consumes it).
    _load_workflow()
    raw = WORKFLOW.read_text(encoding="utf-8")
    for secret in REQUIRED_SECRETS:
        assert f"secrets.{secret}" in raw, (
            f"{secret} must be wired from CI secrets (Req 11.1); no `secrets.{secret}` "
            "reference found in the workflow."
        )


def test_fails_explicitly_when_a_required_secret_is_missing() -> None:
    """Req 11.3: a step must exit non-zero on missing secrets - never skip."""
    data = _load_workflow()
    guard_steps = [
        step
        for step in _iter_run_steps(data)
        if isinstance(step.get("run"), str)
        and "exit 1" in step["run"]
        and all(name in step["run"] for name in REQUIRED_SECRETS)
    ]
    assert guard_steps, (
        "no fail-on-missing-secret guard found: expected a `run:` step that names all "
        f"four required secrets {REQUIRED_SECRETS!r} and exits non-zero (Req 11.3 - fail, "
        "not skip). GitHub injects absent secrets as empty strings, so without this guard "
        "the lane would pass by silently running with blank credentials."
    )


def test_integration_gate_is_enabled_so_tests_run_not_skip() -> None:
    """``RUN_INTEGRATION_WATSONX=1`` must be set so the gated e2e test runs.

    Req 11.3's fail-not-skip posture is only meaningful if the integration
    test actually executes; an unset gate would skip it (Req 10.1) and the lane
    would pass without ever touching watsonx.
    """
    raw = WORKFLOW.read_text(encoding="utf-8")
    assert "RUN_INTEGRATION_WATSONX" in raw, (
        "RUN_INTEGRATION_WATSONX must be set in the workflow so the opt-in e2e lane "
        "runs rather than skips (Req 10.1 / 11.3)."
    )
