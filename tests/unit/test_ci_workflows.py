"""Repo-wide guard: every third-party Action `uses:` must be SHA-pinned (X-1).

Unpinned tags (``uses: actions/checkout@v4``) let a compromised or re-tagged
upstream release run in CI with repo secrets and write access — the mutable
tag can move to different code after review without anyone noticing. A full
40-character commit SHA is immutable, so what was reviewed is what runs.

This mirrors ``test_ollama_ci_workflows.py`` / ``test_watsonx_ci_workflow.py``:
a hermetic static guard that parses workflow YAML (rather than exercising it)
and pins a load-bearing contract. Before this guard only ``jdx/mise-action``
was pinned (the fix for a prior 404 incident); every other ``uses:`` was a
mutable tag. Every workflow file under ``.github/workflows/`` is in scope, not
an enumerated allow-list, so a newly added workflow is covered automatically.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"

# `uses: <owner>/<repo>[/<path>]@<40-hex-char SHA>` — a full commit SHA, not a
# tag or branch name. The trailing `# vX.Y.Z` version comment is required so a
# reader (and Dependabot) can see which release the pin corresponds to without
# resolving the SHA by hand.
_SHA_PINNED_USES_RE = re.compile(
    r"^\s*uses:\s*[\w.-]+/[\w.-]+(?:/[\w./-]+)?@[0-9a-f]{40}\s*#\s*v\S+\s*$"
)
_USES_LINE_RE = re.compile(r"^\s*uses:\s*\S")


def _workflow_files() -> list[Path]:
    files = sorted(WORKFLOWS_DIR.glob("*.yml")) + sorted(WORKFLOWS_DIR.glob("*.yaml"))
    assert files, f"no workflow files found under {WORKFLOWS_DIR}"
    return files


def test_scans_at_least_one_workflow_file() -> None:
    # Guards against the whole test silently no-op'ing if the directory moves.
    assert len(_workflow_files()) > 0


def test_every_uses_line_is_sha_pinned_with_a_version_comment() -> None:
    violations: list[str] = []
    total_uses = 0
    for path in _workflow_files():
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not _USES_LINE_RE.match(line):
                continue
            total_uses += 1
            if not _SHA_PINNED_USES_RE.match(line):
                violations.append(f"{path.relative_to(REPO_ROOT)}:{lineno}: {line.strip()}")

    assert total_uses > 0, (
        "no `uses:` lines found across any workflow — scan is not exercising anything"
    )
    assert not violations, (
        "found `uses:` line(s) not pinned to a full 40-char commit SHA with a "
        "`# vX.Y.Z` comment:\n" + "\n".join(violations) + "\n\n"
        "Resolve the tag to its commit SHA (`git ls-remote --tags "
        "<https url> <tag>`; peel annotated tags with the `^{}` ref) and pin "
        "as `uses: <owner>/<repo>@<sha> # <tag>`."
    )
