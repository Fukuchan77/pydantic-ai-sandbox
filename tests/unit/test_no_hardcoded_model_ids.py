"""Static guard against hardcoded LLM model IDs and stray `.env` exposure.

This test is the runtime counterpart of the `forbid-hardcoded-model-ids`
pre-commit hook (Plan AD-4 / Req 1.5). The forbidden literal set defined here
is the single source of truth for both checks; the pre-commit hook duplicates
the regex by design and points back to this module in its inline comment.

A second assertion (Req 9.6) keeps `.env` covered by `.gitignore` so secrets
cannot be accidentally committed even when the dedicated `gitleaks` hook is
disabled or skipped.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = REPO_ROOT / "src"

# Canonical forbidden literal set. Add to this list whenever a new model ID
# enters the codebase via env-driven configuration; the pre-commit pygrep hook
# in `.pre-commit-config.yaml` MUST be updated in lockstep.
FORBIDDEN_MODEL_ID_LITERALS: tuple[str, ...] = (
    "granite4.1:8b",
    "claude-sonnet-4-6",
    "claude-haiku-4-5-20251001-v1:0",
    "llama3.2-vision:11b",
    "granite-4-h-small",
)


def _iter_scanned_py_files() -> list[Path]:
    """Yield Python source files under `src/` excluding package markers."""
    if not SRC_DIR.exists():
        return []
    return [path for path in SRC_DIR.rglob("*.py") if path.name != "__init__.py"]


def test_no_hardcoded_model_ids_in_src() -> None:
    offenders: list[str] = []
    for path in _iter_scanned_py_files():
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            for literal in FORBIDDEN_MODEL_ID_LITERALS:
                if literal in line:
                    rel = path.relative_to(REPO_ROOT)
                    offenders.append(f"{rel}:{lineno} contains {literal!r}")

    assert not offenders, (
        "Hardcoded LLM model IDs detected — route through env vars instead "
        "(Req 1.5). Offenders:\n  " + "\n  ".join(offenders)
    )


def test_gitignore_excludes_dotenv() -> None:
    gitignore = REPO_ROOT / ".gitignore"
    assert gitignore.exists(), ".gitignore is missing at the repo root"

    entries = {line.strip() for line in gitignore.read_text(encoding="utf-8").splitlines()}
    assert ".env" in entries, (
        "`.env` must remain in .gitignore so secrets stay out of version control (Req 9.6)"
    )
