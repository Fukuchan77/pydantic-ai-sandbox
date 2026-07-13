"""Guard tests for the SSRF / egress policy (Task 5.1, spec 013 R4.4/R5.1-5.3).

The HITL lane has no URL-fetching tool today, so `allow-local` and
`force_download` cannot yet appear in `src/` -- the first assertion below
passes by construction. It exists as a sentinel (research.md WHERE-clause
guard) for whoever adds the first such tool: introducing an egress bypass
trips this test red instead of landing silently.

The remaining two tests are existence checks against the lane README: a
dedicated safe_download / egress-policy section (R5.3, citing
CVE-2026-46678) and a dedicated R4 design-rationale section (R4.4, citing
CVE-2026-25580). Neither section exists yet -- both are RED until Task 5.2
extends the README's security section.
"""

from __future__ import annotations

import re
from pathlib import Path

LANE_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = LANE_ROOT / "src"
README = LANE_ROOT / "README.md"

FORBIDDEN_EGRESS_LITERALS: tuple[str, ...] = ("allow-local", "force_download")

_HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.*)$", flags=re.MULTILINE)


def _iter_src_py_files() -> list[Path]:
    return [path for path in SRC_DIR.rglob("*.py") if path.name != "__init__.py"]


def _section_body(markdown: str, heading_pattern: str) -> str | None:
    """Return the body of the first heading whose text matches `heading_pattern`.

    The body runs until the next heading at the same-or-shallower level, so
    a nested subsection stays inside its parent's returned body.
    """
    headings = list(_HEADING_RE.finditer(markdown))
    for index, heading in enumerate(headings):
        if not re.search(heading_pattern, heading.group(2), flags=re.IGNORECASE):
            continue
        level = len(heading.group(1))
        body_end = len(markdown)
        for later in headings[index + 1 :]:
            if len(later.group(1)) <= level:
                body_end = later.start()
                break
        return markdown[heading.end() : body_end]
    return None


def test_no_egress_bypass_literals_in_src() -> None:
    """No tool wires an `allow-local` / `force_download` bypass into src/ (R5.1/R5.2)."""
    offenders: list[str] = []
    for path in _iter_src_py_files():
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            for literal in FORBIDDEN_EGRESS_LITERALS:
                if literal in line:
                    rel = path.relative_to(LANE_ROOT)
                    offenders.append(f"{rel}:{lineno} contains {literal!r}")

    assert not offenders, (
        "Egress bypass literal detected in src/ -- route URL fetches through "
        "pydantic-ai v2's safe_download path instead (R5.1/R5.2). Offenders:\n  "
        + "\n  ".join(offenders)
    )


def test_readme_documents_safe_download_egress_policy() -> None:
    """README carries a dedicated safe_download / egress-policy section (R5.3)."""
    body = _section_body(README.read_text(encoding="utf-8"), r"safe_download|egress")

    assert body is not None, (
        "README is missing a dedicated safe_download / egress-policy section (R5.3)"
    )
    assert "allow-local" in body, "egress-policy section must forbid `allow-local` (R5.2/R5.3)"
    assert "CVE-2026-46678" in body, (
        "egress-policy section must cite CVE-2026-46678 as the rationale (R5.3)"
    )


def test_readme_documents_r4_design_rationale() -> None:
    """README carries a dedicated R4 design-rationale section (R4.4)."""
    body = _section_body(README.read_text(encoding="utf-8"), r"\bR4\b")

    assert body is not None, "README is missing a dedicated R4 design-rationale section (R4.4)"
    assert "CVE-2026-25580" in body, (
        "R4 design-rationale section must cite CVE-2026-25580 as the mitigated advisory (R4.4)"
    )
