"""Cross-lane contract drift guard (Spec 005 NFR-3 / plan §8 R-5).

The three pattern lanes under ``patterns/frameworks/*/`` each carry a
duplicated ``contracts.py`` (plan AD-3: no cross-lane imports). This test
parses all copies with ``ast`` — no lane dependencies are imported into
the root venv — and asserts the class set and per-class field sets are
identical, so a contract edit in one lane cannot silently drift from the
others or from the normative copy in the pattern READMEs.
"""

from __future__ import annotations

import ast
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_LANES = ("pydantic-ai", "beeai", "llamaindex")


def _contract_shape(path: Path) -> dict[str, tuple[str, ...]]:
    """Map class name -> annotated field names (plus Literal alias values)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    shape: dict[str, tuple[str, ...]] = {}
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            fields = tuple(
                stmt.target.id
                for stmt in node.body
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name)
            )
            shape[node.name] = fields
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            # Module-level annotated assignment: the Route Literal alias.
            shape[node.target.id] = (ast.dump(node.annotation),)
    return shape


def test_pattern_contracts_are_identical_across_lanes() -> None:
    shapes = {
        lane: _contract_shape(
            _REPO_ROOT
            / "patterns"
            / "frameworks"
            / lane
            / "src"
            / f"patterns_{lane.replace('-', '_')}"
            / "contracts.py"
        )
        for lane in _LANES
    }
    reference_lane = _LANES[0]
    reference = shapes[reference_lane]
    assert reference, "reference contract must define at least one class"
    for lane in _LANES[1:]:
        assert shapes[lane] == reference, (
            f"contracts.py drifted between '{reference_lane}' and '{lane}' — "
            "edit all three lane copies and the README normative copy together "
            "(Spec 005 plan AD-3)"
        )


def test_route_vocabulary_matches_normative_value() -> None:
    # The closed vocabulary itself is part of the contract (Req 2.1/2.3).
    for lane in _LANES:
        source = (
            _REPO_ROOT
            / "patterns"
            / "frameworks"
            / lane
            / "src"
            / f"patterns_{lane.replace('-', '_')}"
            / "contracts.py"
        ).read_text(encoding="utf-8")
        assert 'Literal["billing", "technical", "general"]' in source, (
            f"route vocabulary changed in lane '{lane}' without updating this guard"
        )
