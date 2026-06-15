"""Anti-false-green guard for the gated live-Ollama integration lanes (P3).

The live suites are gated (``RUN_INTEGRATION_PATTERNS=1``, plus
``RUN_LLAMAINDEX_INTEGRATION=1`` for llamaindex). A gated suite that collected
nothing, skipped every test, or failed to import silently reports "green" while
never exercising the live path -- the "hidden never-green" that masked the
llamaindex import failure across specs 005-007 (see specs/ci-strategy-review).

This plugin turns that into a hard failure. When ``EXPECT_LIVE_TESTS=<n>`` is set
-- the per-lane ``patterns:test:integration:<lane>`` mise tasks declare the count
they expect to run -- the suite must actually execute at least ``n`` tests; a run
that executed fewer (because tests were skipped, deselected, or never collected)
fails loudly even if pytest would otherwise exit 0. Import/collection errors
already fail pytest on their own (exit 2); this closes the all-skipped /
collected-zero gap.

The guard is inert when ``EXPECT_LIVE_TESTS`` is unset -- offline unit runs, the
aggregate local task, and the intentionally-quarantined llamaindex lane in
per-PR CI -- so it never produces a false failure.

It is wired into each lane via a one-line ``tests/integration/conftest.py`` that
re-exports the two hooks below, keeping the logic in this single source of truth.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest

# Module-level counter; one pytest process runs per lane, so this is per-lane.
_executed = 0


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    """Count tests that ran their call phase (passed or failed, never skipped)."""
    global _executed
    if report.when == "call":
        _executed += 1


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Fail the session when fewer live tests ran than ``EXPECT_LIVE_TESTS`` declares."""
    expected_raw = os.environ.get("EXPECT_LIVE_TESTS")
    if not expected_raw:
        return
    expected = int(expected_raw)
    if _executed >= expected:
        return
    message = (
        f"anti-false-green (P3): expected >= {expected} live test(s) to execute but "
        f"only {_executed} ran. A gated live suite that skipped everything or collected "
        f"nothing is a hidden never-green -- see specs/ci-strategy-review. Failing the suite."
    )
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    if reporter is not None:
        reporter.write_line(message, red=True)
    # Override a would-be green; leave a real test failure's exit code intact.
    if session.exitstatus == 0:
        session.exitstatus = 1
