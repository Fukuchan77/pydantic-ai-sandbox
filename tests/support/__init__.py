"""Test-only helpers shared across the unit suite (plan.md §2.10).

This package hosts small ``FunctionModel``-based fakes and any future
ergonomic builders that the unit tests need but production code MUST NOT
import. Boundary rule (plan.md §2.10): nothing under
``src/pydantic_ai_sandbox/`` may reference symbols defined here. The
hardcoded-model-ID guard (T2.1) skips the ``tests/`` tree, so fixtures
remain free to spell test-bound model name strings inline.
"""
