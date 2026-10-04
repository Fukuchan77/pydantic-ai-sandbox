"""Shared dotted-release-string comparison helper (plan.md §2.10).

Extracted from ``tests/unit/test_ollama_openai_compat.py`` (2026-10-04, spec
014 task 2.2 third fix cycle) so a second module —
``tests/unit/test_litellm_dependency_floor.py`` — can compare version floors
without duplicating the parsing logic. Boundary rule (plan.md §2.10):
nothing under ``src/pydantic_ai_sandbox/`` may import from here; this is a
test-only helper.
"""

from __future__ import annotations


def release_tuple(version_str: str) -> tuple[int, ...]:
    """Parse a dotted release prefix (``"2.54.0"`` -> ``(2, 54, 0)``).

    Only the leading run of dot-separated integers is read, so a
    pre-release suffix (``"3.15.0rc2"``) still compares correctly against
    final-release numbers. Good enough for the floor/ceiling comparisons
    this helper backs without pulling in a ``packaging`` dependency this
    project does not otherwise declare.
    """
    parts: list[int] = []
    for chunk in version_str.split("."):
        digits = ""
        for char in chunk:
            if not char.isdigit():
                break
            digits += char
        if not digits:
            break
        parts.append(int(digits))
    assert parts, f"version string has no leading numeric component: {version_str!r}"
    return tuple(parts)
