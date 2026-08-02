"""Guard for the GHSA-xf7x-x43h-rpqh "not affected" determination (SECURITY-NOTES.md).

The lane's `pip-audit` suppression (`--ignore-vuln GHSA-xf7x-x43h-rpqh` in
mise.toml / patterns-ci.yml / security.yml) is justified by json-repair's
locked version predating the vulnerable `schema_repair.py` module, which
first shipped in 0.56.0 and stays unfixed through 0.60.0 (cycle detection
lands in 0.60.1). That justification is a fact about the *locked* version,
not the advisory's declared range, so nothing else re-checks it automatically
if a future bump ever lands the lockfile inside the real vulnerable window
(0.56.0-0.60.0). This test pins that invariant directly against the lane's
own uv.lock so a landing in the window fails loudly here instead of being
silently swallowed by the blanket suppression.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

LANE_ROOT = Path(__file__).resolve().parents[2]
UV_LOCK = LANE_ROOT / "uv.lock"

# The real vulnerable window (SECURITY-NOTES.md), not the advisory's
# over-broad declared range (`< 0.60.1`, missing its `>= 0.56.0` lower bound).
_VULNERABLE_FLOOR = (0, 56, 0)


def _locked_json_repair_version() -> tuple[int, ...]:
    data = tomllib.loads(UV_LOCK.read_text(encoding="utf-8"))
    packages = [pkg for pkg in data["package"] if pkg["name"] == "json-repair"]
    assert len(packages) == 1, f"expected exactly one locked json-repair entry, got {packages}"
    return tuple(int(part) for part in packages[0]["version"].split("."))


def test_locked_json_repair_stays_below_vulnerable_window() -> None:
    version = _locked_json_repair_version()
    assert version < _VULNERABLE_FLOOR, (
        f"json-repair {'.'.join(map(str, version))} is locked at or above 0.56.0: the "
        "GHSA-xf7x-x43h-rpqh 'not affected' determination in patterns/SECURITY-NOTES.md "
        "no longer holds. Re-evaluate reachability (SchemaRepairer.resolve_schema() via "
        "beeai_framework/backend/utils.py) before keeping the --ignore-vuln suppression "
        "in mise.toml / patterns-ci.yml / security.yml — see issue #30."
    )
