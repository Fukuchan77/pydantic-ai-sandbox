"""Rules-as-tests contract for the root Python 3.14 baseline (Spec 014 R2.4/R2.5).

Every tool/config pin that must track the root's target Python series —
``pyproject.toml`` ``requires-python``, ``mise.toml``, Ruff ``target-version``,
Pyright ``pythonVersion``, the pre-commit ``pyright`` hook name, and the CI
workflow's onboarding comment — is fixed here as one executable contract
(Constitution Principle 1), with ``EXPECTED_SERIES`` as the single place the
target series is declared. Task 1.2 raises every pinned file to match
``EXPECTED_SERIES`` in the same change that turns this module green.

Two checks are included for completeness but are deliberately NOT the basis
for this module's red state on the current 3.13 baseline: the running
interpreter already matches ``.python-version`` and ``ibm-watsonx-ai``'s
``ModelInference`` already imports cleanly under 3.13 (ADR-1), so both stay
green regardless of ``EXPECTED_SERIES``. The red evidence comes from the six
pin-matching tests below, each of which still names a 3.13 pin.
"""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
PYPROJECT = REPO_ROOT / "pyproject.toml"
MISE_TOML = REPO_ROOT / "mise.toml"
PRE_COMMIT_CONFIG = REPO_ROOT / ".pre-commit-config.yaml"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"

# Single source of truth for the target series. Raising this value and syncing
# every pinned file below is exactly what task 1.2 does.
EXPECTED_SERIES = "3.14"

_SERIES_RE = re.compile(r"^(\d+)\.(\d+)$")


def _load_pyproject() -> dict[str, Any]:
    with PYPROJECT.open("rb") as fh:
        return tomllib.load(fh)


def _interpreter_series() -> str:
    return f"{sys.version_info.major}.{sys.version_info.minor}"


def _python_version_file_series() -> str:
    return (REPO_ROOT / ".python-version").read_text(encoding="utf-8").strip()


def _pyproject_requires_python_series() -> str:
    requires_python = _load_pyproject()["project"]["requires-python"]
    match = re.search(r">=(\d+\.\d+)", requires_python)
    assert match, f"{PYPROJECT}: requires-python has no '>=X.Y' pin: {requires_python!r}"
    return match.group(1)


def _mise_python_series() -> str:
    with MISE_TOML.open("rb") as fh:
        mise_config = tomllib.load(fh)
    return str(mise_config["tools"]["python"])


def _ruff_target_version_series() -> str:
    target_version = _load_pyproject()["tool"]["ruff"]["target-version"]
    match = re.fullmatch(r"py(\d)(\d+)", target_version)
    assert match, f"{PYPROJECT}: [tool.ruff] target-version is not 'pyXYY': {target_version!r}"
    return f"{match.group(1)}.{match.group(2)}"


def _pyright_version_series() -> str:
    return str(_load_pyproject()["tool"]["pyright"]["pythonVersion"])


def _pre_commit_pyright_hook_series() -> str:
    config = yaml.safe_load(PRE_COMMIT_CONFIG.read_text(encoding="utf-8"))
    for repo in config["repos"]:
        for hook in repo.get("hooks", []):
            if hook.get("id") == "pyright":
                match = re.search(r"py(\d+\.\d+)", hook.get("name", ""))
                assert match, f"{PRE_COMMIT_CONFIG}: pyright hook name has no 'pyX.Y': {hook!r}"
                return match.group(1)
    raise AssertionError(f"{PRE_COMMIT_CONFIG}: no hook with id 'pyright' found")


def _ci_workflow_series() -> str:
    text = CI_WORKFLOW.read_text(encoding="utf-8")
    match = re.search(r"Python (\d+\.\d+)", text)
    assert match, f"{CI_WORKFLOW}: no 'Python X.Y' onboarding comment found"
    return match.group(1)


def _watsonx_import_succeeds() -> bool:
    # The import itself is the contract under test (ADR-1); referencing the
    # class afterwards (rather than a bare `noqa: F401`) keeps both ruff and
    # pyright strict satisfied without an ignore comment.
    try:
        from ibm_watsonx_ai.foundation_models import ModelInference
    except ImportError:
        return False
    return hasattr(ModelInference, "__name__")


def test_expected_series_is_well_formed() -> None:
    # Guards the contract's own constant against a typo (e.g. "3.14.0" or "314").
    assert _SERIES_RE.match(EXPECTED_SERIES), f"EXPECTED_SERIES is not 'X.Y': {EXPECTED_SERIES!r}"


def test_interpreter_matches_python_version_file() -> None:
    """Running interpreter series must match `.python-version` (not a red-state basis)."""
    assert _interpreter_series() == _python_version_file_series(), (
        f"running interpreter is {_interpreter_series()} but {REPO_ROOT / '.python-version'} "
        f"pins {_python_version_file_series()}"
    )


def test_watsonx_import_succeeds() -> None:
    """`ibm-watsonx-ai`'s ModelInference must import on the running interpreter (ADR-1)."""
    assert _watsonx_import_succeeds(), (
        "ibm_watsonx_ai.foundation_models.ModelInference failed to import "
        f"on Python {_interpreter_series()}"
    )


def test_pyproject_requires_python_matches_expected_series() -> None:
    series = _pyproject_requires_python_series()
    assert series == EXPECTED_SERIES, (
        f"{PYPROJECT}: [project] requires-python is pinned to {series}, expected {EXPECTED_SERIES}"
    )


def test_mise_python_matches_expected_series() -> None:
    series = _mise_python_series()
    assert series == EXPECTED_SERIES, (
        f"{MISE_TOML}: [tools] python is pinned to {series}, expected {EXPECTED_SERIES}"
    )


def test_ruff_target_version_matches_expected_series() -> None:
    series = _ruff_target_version_series()
    assert series == EXPECTED_SERIES, (
        f"{PYPROJECT}: [tool.ruff] target-version is pinned to {series}, expected {EXPECTED_SERIES}"
    )


def test_pyright_version_matches_expected_series() -> None:
    series = _pyright_version_series()
    assert series == EXPECTED_SERIES, (
        f"{PYPROJECT}: [tool.pyright] pythonVersion is pinned to {series}, "
        f"expected {EXPECTED_SERIES}"
    )


def test_pre_commit_pyright_hook_matches_expected_series() -> None:
    series = _pre_commit_pyright_hook_series()
    assert series == EXPECTED_SERIES, (
        f"{PRE_COMMIT_CONFIG}: pyright hook name is pinned to {series}, expected {EXPECTED_SERIES}"
    )


def test_ci_workflow_matches_expected_series() -> None:
    series = _ci_workflow_series()
    assert series == EXPECTED_SERIES, (
        f"{CI_WORKFLOW}: onboarding comment is pinned to {series}, expected {EXPECTED_SERIES}"
    )
