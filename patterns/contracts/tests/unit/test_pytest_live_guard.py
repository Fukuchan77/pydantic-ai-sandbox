"""Unit tests for the anti-false-green guard (P3, patterns_contracts.pytest_live_guard).

The guard is a pytest plugin exercised live by every lane's integration suite, but
the contracts package owns it, so its behaviour is pinned here by calling the two
hooks directly with minimal fakes -- no subprocess, no live model. Each test gets a
freshly reloaded module so the per-process counter starts at zero, and assertions
read only the observable outcome (``session.exitstatus`` / reporter output), never
the module's internals. This both locks the guard's contract and keeps it inside
the contracts coverage floor.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

import pytest

import patterns_contracts.pytest_live_guard as live_guard

if TYPE_CHECKING:
    from types import ModuleType


class _Report:
    """Minimal stand-in for ``pytest.TestReport`` (only ``when`` is read)."""

    def __init__(self, when: str) -> None:
        self.when = when


class _Reporter:
    """Captures ``write_line`` calls so the reporting branch is covered."""

    def __init__(self) -> None:
        self.lines: list[str] = []

    def write_line(self, message: str, *, red: bool = False) -> None:
        self.lines.append(message)


class _PluginManager:
    def __init__(self, reporter: _Reporter | None) -> None:
        self._reporter = reporter

    def get_plugin(self, name: str) -> _Reporter | None:
        assert name == "terminalreporter"
        return self._reporter


class _Config:
    def __init__(self, reporter: _Reporter | None) -> None:
        self.pluginmanager = _PluginManager(reporter)


class _Session:
    """Minimal stand-in for ``pytest.Session`` (config + mutable exitstatus)."""

    def __init__(self, exitstatus: int = 0, reporter: _Reporter | None = None) -> None:
        self.config = _Config(reporter)
        self.exitstatus = exitstatus


@pytest.fixture
def guard() -> ModuleType:
    """A freshly reloaded guard module so its per-process counter starts at zero."""
    return importlib.reload(live_guard)


def test_call_phase_is_counted(guard: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    # One executed test satisfies an expectation of one -> green stays green.
    monkeypatch.setenv("EXPECT_LIVE_TESTS", "1")
    guard.pytest_runtest_logreport(_Report("call"))
    session = _Session(exitstatus=0)
    guard.pytest_sessionfinish(session, 0)
    assert session.exitstatus == 0


def test_non_call_phases_are_not_counted(
    guard: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    # setup/teardown reports (what a skipped test emits) must not count as executed.
    monkeypatch.setenv("EXPECT_LIVE_TESTS", "1")
    guard.pytest_runtest_logreport(_Report("setup"))
    guard.pytest_runtest_logreport(_Report("teardown"))
    session = _Session(exitstatus=0)
    guard.pytest_sessionfinish(session, 0)
    assert session.exitstatus == 1


def test_inert_when_expectation_unset(guard: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EXPECT_LIVE_TESTS", raising=False)
    session = _Session(exitstatus=0)
    guard.pytest_sessionfinish(session, 0)
    assert session.exitstatus == 0


def test_fails_a_would_be_green_when_nothing_ran(
    guard: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EXPECT_LIVE_TESTS", "1")
    reporter = _Reporter()
    session = _Session(exitstatus=0, reporter=reporter)  # no reports -> zero executed
    guard.pytest_sessionfinish(session, 0)
    assert session.exitstatus == 1
    assert reporter.lines and "anti-false-green" in reporter.lines[0]


def test_preserves_an_existing_failure_exit(
    guard: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A real test failure (exitstatus already non-zero) must not be masked or
    # rewritten by the guard, even when the expectation is also unmet.
    monkeypatch.setenv("EXPECT_LIVE_TESTS", "5")
    session = _Session(exitstatus=2, reporter=None)
    guard.pytest_sessionfinish(session, 2)
    assert session.exitstatus == 2
