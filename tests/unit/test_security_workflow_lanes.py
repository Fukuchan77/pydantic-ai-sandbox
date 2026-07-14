"""Regression guard: every pydantic-ai-dependent uv lane stays CVE-scanned.

Spec 013 R9.1-9.3. ``security.yml``'s ``patterns-pip-audit`` job and
``dependabot.yml``'s pip block are never exercised by pytest at runtime, so
this hermetic static guard pins the "no lane silently drops off the CVE scan"
invariant the same way ``test_ollama_ci_workflows.py`` guards the Ollama
lanes' trigger surface.

``hitl`` (Spec 012) is already registered in both files at the time this
guard was written (``security.yml``'s matrix and ``dependabot.yml``'s
directories list), so the two positive tests below are green on creation.
The guard's value is as a **regression gate**, not a red-first TDD artifact
for hitl specifically — the red-first evidence for the underlying detection
mechanism is pinned permanently by
``test_missing_lanes_is_pure_and_detects_a_synthetic_gap`` below (H-2): it
feeds the pure ``missing_lanes()`` function a synthetic set missing a lane
and asserts the function reports it as missing. A future contributor who
deletes a lane from either registration file reproduces that same failure
in the two positive tests.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SECURITY_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "security.yml"
DEPENDABOT_CONFIG = REPO_ROOT / ".github" / "dependabot.yml"
PATTERNS_DIR = REPO_ROOT / "patterns"

# The pydantic-ai-dependent lane group (AD-9, dependabot.yml's second pip
# block): the three framework lanes plus hitl. Application sibling lanes
# (rag/sse/deep-research) are a known, scoped-out gap covered instead by
# security.yml's daily pip-audit cron (see dependabot.yml's comment block).
PYDANTIC_AI_DEPENDENT_LANES: frozenset[str] = frozenset(
    {"pydantic-ai", "beeai", "llamaindex", "hitl"}
)


def _load_yaml(path: Path) -> dict[str, Any]:
    """Parse a workflow/config YAML file, asserting it exists and is a mapping."""
    assert path.exists(), f"missing: {path.relative_to(REPO_ROOT)}"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict), f"{path.name} did not parse to a top-level mapping"
    return cast("dict[str, Any]", data)


def _discover_uv_lanes() -> frozenset[str]:
    """Enumerate every independent uv lane under patterns/ and patterns/frameworks/.

    A lane is any immediate subdirectory owning its own ``pyproject.toml``
    (Spec 005 AD-1: each lane is an independent uv project). This mirrors the
    directory-ownership test that ``mise run patterns:*`` tasks use to fan out.
    """
    lanes = {p.parent.name for p in PATTERNS_DIR.glob("*/pyproject.toml")}
    lanes.update(p.parent.name for p in (PATTERNS_DIR / "frameworks").glob("*/pyproject.toml"))
    return frozenset(lanes)


def _lanes_from_security_matrix() -> frozenset[str]:
    """Return the lane names registered in security.yml's patterns-pip-audit matrix."""
    data = _load_yaml(SECURITY_WORKFLOW)
    jobs = cast("dict[str, Any]", data["jobs"])
    matrix = cast("dict[str, Any]", jobs["patterns-pip-audit"]["strategy"]["matrix"])
    include = cast("list[dict[str, Any]]", matrix["include"])
    return frozenset(entry["lane"] for entry in include)


def _lanes_from_dependabot_pydantic_ai_block() -> frozenset[str]:
    """Return the lane names in dependabot.yml's pydantic-ai-dependent pip block.

    Directory strings look like ``/patterns/frameworks/pydantic-ai`` or
    ``/patterns/hitl``; the lane name is the final path segment.
    """
    data = _load_yaml(DEPENDABOT_CONFIG)
    updates = cast("list[dict[str, Any]]", data["updates"])
    directories: list[str] = []
    for block in updates:
        if block.get("package-ecosystem") == "pip" and "directories" in block:
            directories.extend(cast("list[str]", block["directories"]))
    return frozenset(Path(d).name for d in directories)


def missing_lanes(actual_lanes: frozenset[str], expected_lanes: frozenset[str]) -> frozenset[str]:
    """Pure set-difference: lanes in ``expected_lanes`` absent from ``actual_lanes``.

    Empty result == pass. Kept as a standalone pure function (no file I/O) so
    the detection mechanism itself can be red-tested with synthetic input,
    independent of what the real YAML files currently contain (H-2).
    """
    return expected_lanes - actual_lanes


def test_security_yml_matrix_covers_every_uv_lane() -> None:
    actual = _lanes_from_security_matrix()
    expected = _discover_uv_lanes()
    missing = missing_lanes(actual, expected)
    assert not missing, (
        f"security.yml patterns-pip-audit matrix is missing lane(s) {sorted(missing)}; "
        "a lane with its own pyproject.toml under patterns/ (or patterns/frameworks/) "
        "must have a matching {lane, dir} entry in the matrix include list, or its "
        "lockfile never gets scanned by the daily/dispatch CVE audit."
    )


def test_security_yml_hitl_lane_dir_is_correct() -> None:
    data = _load_yaml(SECURITY_WORKFLOW)
    jobs = cast("dict[str, Any]", data["jobs"])
    matrix = cast("dict[str, Any]", jobs["patterns-pip-audit"]["strategy"]["matrix"])
    include = cast("list[dict[str, Any]]", matrix["include"])
    hitl_entries = [entry for entry in include if entry.get("lane") == "hitl"]
    assert hitl_entries, "hitl lane missing from security.yml patterns-pip-audit matrix"
    assert hitl_entries[0]["dir"] == "patterns/hitl", (
        f"hitl lane's `dir` must be patterns/hitl, got {hitl_entries[0]['dir']!r}"
    )


def test_dependabot_pydantic_ai_dependent_block_covers_hitl() -> None:
    actual = _lanes_from_dependabot_pydantic_ai_block()
    missing = missing_lanes(actual, PYDANTIC_AI_DEPENDENT_LANES)
    assert not missing, (
        f"dependabot.yml's pydantic-ai-dependent pip block is missing lane(s) "
        f"{sorted(missing)}; each pydantic-ai-dependent lane (frameworks/pydantic-ai, "
        "frameworks/beeai, frameworks/llamaindex, hitl) must appear under that "
        "block's `directories:` list, or Dependabot never opens a bump PR for it."
    )


def test_missing_lanes_is_pure_and_detects_a_synthetic_gap() -> None:
    """H-2: pin the detection mechanism's red permanently via synthetic input.

    Independent of whatever security.yml/dependabot.yml currently contain,
    feeding `missing_lanes` a synthetic actual-set that omits "hitl" must
    report "hitl" as missing. This is the red-first evidence for the
    mechanism itself, since the two real-file assertions above are green on
    creation (hitl was already registered by Spec 012).
    """
    synthetic_matrix_include = [
        {"lane": "contracts", "dir": "patterns/contracts"},
        {"lane": "rag", "dir": "patterns/rag"},
    ]
    synthetic_actual = frozenset(entry["lane"] for entry in synthetic_matrix_include)
    synthetic_expected = frozenset({"contracts", "rag", "hitl"})

    missing = missing_lanes(synthetic_actual, synthetic_expected)

    assert missing == frozenset({"hitl"})
