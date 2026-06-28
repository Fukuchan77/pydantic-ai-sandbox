"""Single-point contract drift guard (Spec 006-2a Req 2.1, 2.2, 2.3 / NFR-5).

Each ``patterns/<pattern>/README.md`` carries a normative ``python`` fenced
block under the ``## パターン契約`` heading. This test parses every such block
with ``ast`` (no framework lanes are imported -- only the dependency-zero
``patterns_contracts`` package) and asserts that the three contract sets agree
with the package's runtime introspection:

* **class set** -- the Pydantic model classes documented vs. exported,
* **field set** -- each model's annotated field names,
* **Literal vocabulary** -- the closed value sets of every ``Literal`` (both
  inline field literals such as ``variant`` / ``verdict`` / ``stop_reason`` and
  named module-level aliases such as ``Route``).

This single point replaces the Spec 005 cross-lane AST comparison: the lanes no
longer duplicate ``contracts.py``; the package is the sole implementation and
each README block is its normative copy.

Deliberately **out of scope** for the parser (documentation-only in the READMEs;
their cross-lane agreement is the type system's responsibility under pyright
strict, per ADR-7 / plan §"contract drift guard"):

* the ``Tool`` ``Protocol`` (carries no ``model_fields``),
* the ``ApprovalHook`` ``Callable`` alias,
* the ``async def run_*`` entry-point signatures (contain ``model/llm`` etc.,
  which is not valid Python -- so each top-level construct is parsed
  individually rather than the block as a whole).
"""

from __future__ import annotations

import ast
import re
from collections import Counter
from pathlib import Path
from typing import Literal, get_args, get_origin

from pydantic import BaseModel

import patterns_contracts

# patterns/contracts/tests/unit/ -> parents[3] == patterns/
_PATTERNS_DIR = Path(__file__).resolve().parents[3]
_NORMATIVE_HEADING = "## パターン契約"
_PYTHON_FENCE = "```python"
_FENCE = "```"
_ASSIGNMENT = re.compile(r"^[A-Za-z_]\w*\s*=")

_README_PATHS: dict[str, Path] = {
    "routing": _PATTERNS_DIR / "routing" / "README.md",
    "orchestrator-workers": _PATTERNS_DIR / "orchestrator-workers" / "README.md",
    "prompt-chaining": _PATTERNS_DIR / "prompt-chaining" / "README.md",
    "parallelization": _PATTERNS_DIR / "parallelization" / "README.md",
    "evaluator-optimizer": _PATTERNS_DIR / "evaluator-optimizer" / "README.md",
    "autonomous-agent": _PATTERNS_DIR / "autonomous-agent" / "README.md",
    "rag": _PATTERNS_DIR / "rag" / "README.md",
    "sse": _PATTERNS_DIR / "sse" / "README.md",
    "deep-research": _PATTERNS_DIR / "deep-research" / "README.md",
    "eval-graders": _PATTERNS_DIR / "EVAL-GRADERS.md",
}


class _Shape:
    """Normalized contract surface comparable between README and package."""

    def __init__(self) -> None:
        self.fields: dict[str, frozenset[str]] = {}
        """Model class name -> its annotated field names."""
        self.field_literals: dict[tuple[str, str], frozenset[str]] = {}
        """(model class, field) -> the field's Literal value vocabulary."""
        self.named_literals: dict[str, frozenset[str]] = {}
        """Module-level Literal alias name (e.g. ``Route``) -> its vocabulary."""

    @property
    def classes(self) -> frozenset[str]:
        """The set of documented/exported Pydantic model class names."""
        return frozenset(self.fields)


# --- README side: parse the normative fenced block ----------------------------


def _normative_block(readme: str) -> str:
    """Return the body of the ``python`` fence under the normative heading."""
    heading = readme.index(_NORMATIVE_HEADING)
    fence_open = readme.index(_PYTHON_FENCE, heading)
    body_start = fence_open + len(_PYTHON_FENCE)
    fence_close = readme.index(_FENCE, body_start)
    return readme[body_start:fence_close]


def _top_level_chunks(block: str) -> list[str]:
    """Split a fenced block into top-level constructs (col-0 header + body).

    The block as a whole is not valid Python (entry signatures use ``model/llm``),
    so each construct is isolated for individual ``ast.parse``.
    """
    chunks: list[str] = []
    current: list[str] = []
    for line in block.splitlines():
        if line and not line[0].isspace():
            if current:
                chunks.append("\n".join(current))
            current = [line]
        elif current:
            current.append(line)
    if current:
        chunks.append("\n".join(current))
    return chunks


def _is_protocol(node: ast.ClassDef) -> bool:
    """True when the class derives from ``Protocol`` (e.g. ``Tool``)."""
    for base in node.bases:
        if isinstance(base, ast.Name) and base.id == "Protocol":
            return True
        if isinstance(base, ast.Attribute) and base.attr == "Protocol":
            return True
    return False


def _annotation_literal(
    node: ast.expr, aliases: dict[str, frozenset[str]]
) -> frozenset[str] | None:
    """Extract a Literal vocabulary from an annotation, resolving named aliases."""
    if isinstance(node, ast.Subscript):
        head = node.value
        is_literal = (isinstance(head, ast.Name) and head.id == "Literal") or (
            isinstance(head, ast.Attribute) and head.attr == "Literal"
        )
        if is_literal:
            slice_node = node.slice
            elements = slice_node.elts if isinstance(slice_node, ast.Tuple) else [slice_node]
            return frozenset(
                element.value
                for element in elements
                if isinstance(element, ast.Constant) and isinstance(element.value, str)
            )
    if isinstance(node, ast.Name) and node.id in aliases:
        return aliases[node.id]
    return None


def _collect_named_literals(chunks: list[str]) -> dict[str, frozenset[str]]:
    """Map module-level Literal-alias names to their vocabulary (skips ``Callable``)."""
    aliases: dict[str, frozenset[str]] = {}
    for chunk in chunks:
        if not _ASSIGNMENT.match(chunk.splitlines()[0]):
            continue
        statement = ast.parse(chunk).body[0]
        if (
            isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
        ):
            values = _annotation_literal(statement.value, {})
            if values is not None:
                aliases[statement.targets[0].id] = values
    return aliases


def _collect_model(chunk: str, aliases: dict[str, frozenset[str]], shape: _Shape) -> str | None:
    """Parse one class chunk into ``shape`` (skips the ``Tool`` Protocol)."""
    class_def = ast.parse(chunk).body[0]
    if not isinstance(class_def, ast.ClassDef) or _is_protocol(class_def):
        return None
    names: set[str] = set()
    for stmt in class_def.body:
        if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            names.add(stmt.target.id)
            literal = _annotation_literal(stmt.annotation, aliases)
            if literal is not None:
                shape.field_literals[(class_def.name, stmt.target.id)] = literal
    shape.fields[class_def.name] = frozenset(names)
    return class_def.name


def _readme_shape() -> tuple[_Shape, list[tuple[str, str]]]:
    """Parse all six README normative blocks into a merged shape.

    Also returns every ``(class name, owning pattern)`` pairing -- a *list*, not
    a dict, so a class documented in two READMEs stays visible. A dict would
    collapse the duplicate to one key and ``shape.fields`` would silently
    overwrite, masking the divergence the one-README invariant must catch.
    """
    shape = _Shape()
    owners: list[tuple[str, str]] = []
    for pattern, path in _README_PATHS.items():
        chunks = _top_level_chunks(_normative_block(path.read_text(encoding="utf-8")))
        aliases = _collect_named_literals(chunks)
        shape.named_literals.update(aliases)
        for chunk in chunks:
            if not chunk.startswith("class "):
                continue
            name = _collect_model(chunk, aliases, shape)
            if name is not None:
                owners.append((name, pattern))
    return shape, owners


# --- package side: introspect patterns_contracts ------------------------------


def _value_literal(value: object) -> frozenset[str] | None:
    """Return a Literal's value vocabulary, or None if ``value`` is not one."""
    if get_origin(value) is Literal:
        return frozenset(str(arg) for arg in get_args(value))
    return None


def _package_shape() -> _Shape:
    """Introspect the package's exported models and Literal aliases."""
    shape = _Shape()
    for name in patterns_contracts.__all__:
        member: object = getattr(patterns_contracts, name)
        if isinstance(member, type):
            # Pydantic models contribute fields/literals; other classes (the
            # Tool Protocol) are skipped by design.
            if issubclass(member, BaseModel):
                shape.fields[name] = frozenset(member.model_fields)
                for field, info in member.model_fields.items():
                    literal = _value_literal(info.annotation)
                    if literal is not None:
                        shape.field_literals[(name, field)] = literal
            continue
        named = _value_literal(member)
        if named is not None:
            shape.named_literals[name] = named
        # Otherwise: ApprovalHook (Callable alias) -- skipped by design.
    return shape


_README, _OWNERS = _readme_shape()
_PACKAGE = _package_shape()


# --- the three contract sets (Req 2.3) ----------------------------------------


def test_documented_class_set_matches_package() -> None:
    assert _README.classes == _PACKAGE.classes, (
        "model class set drifted between the README normative blocks and "
        f"patterns_contracts: only in READMEs={_README.classes - _PACKAGE.classes}, "
        f"only in package={_PACKAGE.classes - _README.classes}"
    )


def test_documented_field_sets_match_package() -> None:
    drifted = sorted(
        name
        for name in _README.classes | _PACKAGE.classes
        if _README.fields.get(name) != _PACKAGE.fields.get(name)
    )
    assert _README.fields == _PACKAGE.fields, (
        f"field set drifted between README and package for: {drifted}"
    )


def test_documented_literal_vocabularies_match_package() -> None:
    assert _README.field_literals == _PACKAGE.field_literals, (
        "inline Literal vocabulary drifted between README and package: "
        f"README={_README.field_literals}, package={_PACKAGE.field_literals}"
    )
    assert _README.named_literals == _PACKAGE.named_literals, (
        "named Literal-alias vocabulary drifted between README and package: "
        f"README={_README.named_literals}, package={_PACKAGE.named_literals}"
    )


def test_each_package_model_is_documented_in_exactly_one_readme() -> None:
    # The merge in _readme_shape would mask drift if a class were documented in
    # two READMEs; guard the one-class-one-README invariant explicitly. Catch
    # duplicates *before* the set comparison -- collapsing to a set first would
    # hide a class documented twice (the very hole this invariant must close).
    counts = Counter(name for name, _ in _OWNERS)
    duplicated = {
        name: sorted(pattern for cls, pattern in _OWNERS if cls == name)
        for name, count in counts.items()
        if count > 1
    }
    assert not duplicated, f"model(s) documented in more than one README: {duplicated}"
    documented = frozenset(counts)
    assert documented == _PACKAGE.classes, (
        "every package model must be documented in exactly one README "
        f"(README owners={sorted(documented)}, package models={sorted(_PACKAGE.classes)})"
    )
