"""Rules-as-tests contract: litellm must stay at or above its vulnerability floor.

Spec 014 task 2.2, third fix cycle (2026-10-04 2nd-pass VDD review). The
root ``openai`` range (``pyproject.toml`` ADR-2) does NOT by itself reject
a vulnerable ``litellm`` rollback: ``litellm==1.83.0`` declares an
unbounded ``openai>=2.8.0``, which is trivially satisfiable inside the
root's ``>=2.47.0,<3.0.0`` range. pip-audit (2026-10-04, scratch venv)
confirmed 1.83.0 carries 14 known vulnerabilities, the slowest-patched of
which (``PYSEC-2026-4066``) is first fixed, across litellm's parallel
maintenance branches, at ``1.96.2``. That figure is declared as an
explicit floor — ``LITELLM_VULNERABILITY_FLOOR`` below — and checked two
ways:

1. **Declared floor** (`test_pyproject_declares_litellm_floor_in_*`): both
   the ``[project.optional-dependencies] litellm`` extra and the
   ``[dependency-groups] dev`` entry in ``pyproject.toml`` must spell a
   ``>=`` constraint at least as high as ``LITELLM_VULNERABILITY_FLOOR`` —
   parsed via ``tomllib``, mirroring ``tests/unit/test_python_baseline.py``'s
   pattern, so a manifest edit that weakens or removes the floor fails
   this module without needing a live resolve.
2. **Installed floor** (`test_installed_litellm_meets_vulnerability_floor`):
   defense-in-depth against lock drift — a ``uv.lock`` that resolved to a
   stale litellm despite the manifest floor (e.g. a hand-edited lockfile,
   or a resolver bug) would still be caught here, same pattern as
   ``test_ollama_openai_compat.py``'s installed-version guards.

This module is red on the pre-fix-cycle manifest, which declared bare
``"litellm"`` with no floor in either location.
"""

from __future__ import annotations

import tomllib
from importlib.metadata import version as installed_version
from pathlib import Path
from typing import Any

from tests.support.version_compare import release_tuple

REPO_ROOT = Path(__file__).resolve().parents[2]
PYPROJECT = REPO_ROOT / "pyproject.toml"

# See the module docstring for the provenance of this value: the first fix
# version, across litellm's parallel maintenance branches, for the
# slowest-patched of litellm 1.83.0's 14 known vulnerabilities
# (PYSEC-2026-4066), independently pip-audit-confirmed clean (2026-10-04).
LITELLM_VULNERABILITY_FLOOR = "1.96.2"


def _load_pyproject() -> dict[str, Any]:
    with PYPROJECT.open("rb") as fh:
        return tomllib.load(fh)


def _extra_litellm_requirement() -> str:
    entries = _load_pyproject()["project"]["optional-dependencies"]["litellm"]
    for entry in entries:
        if entry.startswith("litellm"):
            return str(entry)
    raise AssertionError(
        f"{PYPROJECT}: [project.optional-dependencies] litellm has no 'litellm...' entry: "
        f"{entries!r}"
    )


def _dev_group_litellm_requirement() -> str:
    dev = _load_pyproject()["dependency-groups"]["dev"]
    for entry in dev:
        if entry.startswith("litellm"):
            return str(entry)
    raise AssertionError(f"{PYPROJECT}: [dependency-groups] dev has no 'litellm...' entry: {dev!r}")


def _floor_from_requirement(requirement: str, *, where: str) -> str:
    prefix = "litellm>="
    assert requirement.startswith(prefix), (
        f"{where} declares {requirement!r}, which is not a 'litellm>=X.Y.Z' floor — "
        f"a bare 'litellm' or a '==' pin does not reject a vulnerable rollback "
        f"(see this module's docstring and pyproject.toml ADR-2)"
    )
    return requirement[len(prefix) :]


def test_pyproject_declares_litellm_floor_in_optional_extra() -> None:
    requirement = _extra_litellm_requirement()
    floor = _floor_from_requirement(requirement, where="[project.optional-dependencies] litellm")
    assert release_tuple(floor) >= release_tuple(LITELLM_VULNERABILITY_FLOOR), (
        f"[project.optional-dependencies] litellm declares {requirement!r}, whose floor "
        f"{floor!r} is below the vulnerability floor {LITELLM_VULNERABILITY_FLOOR!r} "
        f"(see this module's docstring for the pip-audit evidence)"
    )


def test_pyproject_declares_litellm_floor_in_dev_group() -> None:
    requirement = _dev_group_litellm_requirement()
    floor = _floor_from_requirement(requirement, where="[dependency-groups] dev")
    assert release_tuple(floor) >= release_tuple(LITELLM_VULNERABILITY_FLOOR), (
        f"[dependency-groups] dev declares {requirement!r}, whose floor {floor!r} is "
        f"below the vulnerability floor {LITELLM_VULNERABILITY_FLOOR!r} (see this "
        f"module's docstring for the pip-audit evidence)"
    )


def test_installed_litellm_meets_vulnerability_floor() -> None:
    """Defense-in-depth: the *resolved* litellm must meet the floor too (lock drift)."""
    installed = installed_version("litellm")
    assert release_tuple(installed) >= release_tuple(LITELLM_VULNERABILITY_FLOOR), (
        f"installed litellm is {installed}, which is older than the vulnerability "
        f"floor {LITELLM_VULNERABILITY_FLOOR!r}. Run 'uv lock' to re-resolve against "
        f"the pyproject.toml floor — see this module's docstring for the pip-audit "
        f"evidence this floor is based on."
    )
