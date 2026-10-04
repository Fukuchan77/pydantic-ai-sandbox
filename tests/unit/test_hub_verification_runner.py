"""Hermetic contracts for the immutable hub Python verification runner."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Mapping

ROOT = Path(__file__).parents[2]
RUNNER = ROOT / "scripts" / "verify-hub-python.sh"
SUMMARIZER = ROOT / "scripts" / "summarize_hub_verification.py"


def _run(
    argv: list[str],
    *,
    env: Mapping[str, str] | None = None,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a test-owned fixed argv without a shell."""
    return subprocess.run(  # noqa: S603 - argv is fixed by this test module
        argv,
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=timeout,
    )


def _git(repo: Path, *args: str) -> str:
    result = _run(["git", "-C", str(repo), *args])
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def _write_fake_mise(bin_dir: Path) -> Path:
    mise = bin_dir / "mise"
    mise.write_text(
        textwrap.dedent(
            """\
            #!/bin/sh
            set -eu
            : "${FAKE_MISE_LOG:?}"
            printf '%s\\t%s\\t%s\\t%s\\t%s\\t%s\\n' \\
              "$PWD" "${MISE_AUTO_INSTALL-unset}" \\
              "${MISE_EXEC_AUTO_INSTALL-unset}" \\
              "${MISE_NOT_FOUND_AUTO_INSTALL-unset}" \\
              "${MISE_TASK_RUN_AUTO_INSTALL-unset}" "$*" >> "$FAKE_MISE_LOG"
            scratch=$PWD
            if [ ! -f "$scratch/root-sentinel.txt" ]; then scratch=$(cd ../.. && pwd); fi
            test -f "$scratch/root-sentinel.txt"
            test "${MISE_TRUSTED_CONFIG_PATHS-unset}" = "$scratch/mise.toml"

            stage=unknown
            case "$*" in
              'exec -- uv lock') stage=uv-lock ;;
              'exec -- uv sync') stage=uv-sync ;;
              'run api:check') stage=api-check ;;
              'run api:lint') stage=api-lint ;;
              'run api:test:ci') stage=api-test-ci ;;
              'run api:audit') stage=api-audit ;;
              'run api:typecheck') stage=api-typecheck ;;
            esac
            printf '%s\\n' "$stage output"
            if [ "$stage" = "api-test-ci" ]; then
              printf '%s\\n' 'pkg/tests/test_api.py:7: DeprecationWarning: legacy api'
              printf '%s\\n' '.venv/lib/python3.14/site-packages/starlette/testclient.py:9: StarletteDeprecationWarning: TestClient is deprecated'
            fi
            if [ "$stage" = "api-audit" ]; then
              printf '%s\\n' 'No known vulnerabilities found'
            fi
            if [ "${FAKE_SLEEP_STAGE-}" = "$stage" ]; then
              sleep 30 & child=$!
              if [ -n "${FAKE_CHILD_PID_FILE-}" ]; then printf '%s\n' "$child" > "$FAKE_CHILD_PID_FILE"; fi
              wait "$child"
            fi
            if [ "${FAKE_FAIL_STAGE-}" = "$stage" ]; then exit 23; fi
            """
        ),
        encoding="utf-8",
    )
    mise.chmod(0o755)
    return mise


@pytest.fixture
def fake_hub(tmp_path: Path) -> tuple[Path, str, Path, Path]:
    repo = tmp_path / "hub"
    repo.mkdir()
    (repo / "services" / "api" / "tests" / "unit").mkdir(parents=True)
    (repo / "packages" / "evals").mkdir(parents=True)
    (repo / ".github" / "workflows").mkdir(parents=True)
    (repo / "packages" / "schemas" / "src" / "generated").mkdir(parents=True)
    (repo / "root-sentinel.txt").write_text("committed\n", encoding="utf-8")
    (repo / "services" / "api" / ".python-version").write_text("3.13\n", encoding="utf-8")
    (repo / "services" / "api" / "pyproject.toml").write_text(
        '[project]\nrequires-python = ">=3.13"\n\n[tool.ruff]\ntarget-version = "py313"\n',
        encoding="utf-8",
    )
    (repo / "services" / "api" / "uv.lock").write_text(
        'version = 1\nrevision = 3\n\n[[package]]\nname = "demo"\nversion = "1.0.0"\n',
        encoding="utf-8",
    )
    (repo / "mise.toml").write_text(
        textwrap.dedent(
            """\
            [tasks."api:check"]
            run = "mise run api:lint && mise run api:test:ci && mise run api:audit"

            [tasks."api:lint"]
            run = "ruff check ."

            [tasks."api:typecheck"]
            run = "ty check"

            [tasks."api:test:ci"]
            run = "pytest"

            [tasks."api:audit"]
            run = "pip-audit"
            """
        ),
        encoding="utf-8",
    )
    (repo / "services" / "api" / "app").mkdir()
    (repo / "services" / "api" / "app" / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
    (repo / "services" / "api" / "tests" / "unit" / "test_python_version.py").write_text(
        '_EXPECTED_SERIES = "3.13"\n', encoding="utf-8"
    )
    (repo / "packages" / "evals" / "README.md").write_text("sentinel\n", encoding="utf-8")
    (repo / ".github" / "workflows" / "api.yml").write_text("name: api\n", encoding="utf-8")
    (repo / "packages" / "schemas" / "src" / "generated" / "schema.json").write_text(
        "{}\n", encoding="utf-8"
    )
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "fixture")
    commit = _git(repo, "rev-parse", "HEAD")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_fake_mise(bin_dir)
    invocation_log = tmp_path / "mise-invocations.tsv"
    return repo, commit, bin_dir, invocation_log


def _runner_env(bin_dir: Path, invocation_log: Path, **extra: str) -> dict[str, str]:
    return {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "FAKE_MISE_LOG": str(invocation_log),
        **extra,
    }


def _run_runner(
    fake_hub: tuple[Path, str, Path, Path],
    output: Path,
    *,
    python: str = "3.14",
    **env: str,
) -> subprocess.CompletedProcess[str]:
    repo, commit, bin_dir, invocation_log = fake_hub
    return _run(
        [
            "/bin/bash",
            str(RUNNER),
            "--hub-repo",
            str(repo),
            "--commit",
            commit,
            "--python",
            python,
            "--output",
            str(output),
        ],
        env=_runner_env(bin_dir, invocation_log, **env),
    )


@pytest.mark.parametrize("python", ["3.14", "3.15"])
def test_runner_archives_full_commit_migrates_only_scratch_and_preserves_source(
    fake_hub: tuple[Path, str, Path, Path], tmp_path: Path, python: str
) -> None:
    repo, _, _, invocation_log = fake_hub
    (repo / "root-sentinel.txt").write_text("dirty source\n", encoding="utf-8")
    source_before = _git(repo, "status", "--porcelain=v1")
    output = tmp_path / f"evidence-{python}"

    result = _run_runner(fake_hub, output, python=python)

    assert result.returncode == 0, result.stderr
    assert _git(repo, "status", "--porcelain=v1") == source_before
    migration = (output / "migration.diff").read_text(encoding="utf-8")
    assert f"+{python}" in migration
    assert "services/api/.python-version" in migration
    assert "services/api/pyproject.toml" in migration
    assert f'requires-python = ">={python}"' in migration
    assert f'target-version = "py{python.replace(".", "")}"' in migration
    calls = invocation_log.read_text(encoding="utf-8").splitlines()
    assert calls
    working_dirs = {Path(line.split("\t", maxsplit=1)[0]) for line in calls}
    scratch_roots = {path if path.name != "api" else path.parents[1] for path in working_dirs}
    assert len(scratch_roots) == 1
    scratch = next(iter(scratch_roots))
    assert not str(scratch).startswith(str(repo))
    assert not scratch.exists()


def test_runner_supports_output_path_with_spaces(
    fake_hub: tuple[Path, str, Path, Path], tmp_path: Path
) -> None:
    output = tmp_path / "hub evidence with spaces"

    result = _run_runner(fake_hub, output)

    assert result.returncode == 0, result.stderr
    assert (output / "summary.md").is_file()


@pytest.mark.parametrize(
    "migration_path",
    ["services/api/.python-version", "mise.toml", "services/api/pyproject.toml"],
)
def test_runner_rejects_symlinked_migration_path_before_gate(
    fake_hub: tuple[Path, str, Path, Path], tmp_path: Path, migration_path: str
) -> None:
    repo, _, bin_dir, invocation_log = fake_hub
    target = tmp_path / f"external-{Path(migration_path).name}"
    target.write_text("external must stay unchanged\n", encoding="utf-8")
    path = repo / migration_path
    path.unlink()
    path.symlink_to(target)
    _git(repo, "add", migration_path)
    _git(repo, "commit", "-qm", f"symlink {migration_path}")
    commit = _git(repo, "rev-parse", "HEAD")

    result = _run(
        [
            "/bin/bash",
            str(RUNNER),
            "--hub-repo",
            str(repo),
            "--commit",
            commit,
            "--python",
            "3.14",
            "--output",
            str(tmp_path / "evidence"),
        ],
        env=_runner_env(bin_dir, invocation_log),
    )

    assert result.returncode != 0
    assert target.read_text(encoding="utf-8") == "external must stay unchanged\n"
    assert not invocation_log.exists()


def test_runner_rejects_symlinked_interpreter_expectation_before_gate(
    fake_hub: tuple[Path, str, Path, Path], tmp_path: Path
) -> None:
    repo, _, bin_dir, invocation_log = fake_hub
    target = tmp_path / "external-expectation.py"
    original = '_EXPECTED_SERIES = "3.13"\n'
    target.write_text(original, encoding="utf-8")
    relative = "services/api/tests/unit/test_python_version.py"
    path = repo / relative
    path.unlink()
    path.symlink_to(target)
    _git(repo, "add", relative)
    _git(repo, "commit", "-qm", "symlink interpreter expectation")
    commit = _git(repo, "rev-parse", "HEAD")

    result = _run(
        [
            "/bin/bash",
            str(RUNNER),
            "--hub-repo",
            str(repo),
            "--commit",
            commit,
            "--python",
            "3.14",
            "--output",
            str(tmp_path / "evidence"),
        ],
        env=_runner_env(bin_dir, invocation_log),
    )

    assert result.returncode != 0
    assert target.read_text(encoding="utf-8") == original
    assert not invocation_log.exists()


def test_runner_disables_mise_auto_install_and_limits_trust_to_scratch(
    fake_hub: tuple[Path, str, Path, Path], tmp_path: Path
) -> None:
    _, _, _, invocation_log = fake_hub

    result = _run_runner(fake_hub, tmp_path / "evidence")

    assert result.returncode == 0, result.stderr
    for line in invocation_log.read_text(encoding="utf-8").splitlines():
        fields = line.split("\t")
        assert fields[1:5] == ["0", "0", "0", "0"]


@pytest.mark.parametrize("failed_stage", ["uv-lock", "uv-sync", "api-check"])
def test_required_phase_failure_is_nonzero_but_diagnostics_continue(
    fake_hub: tuple[Path, str, Path, Path], tmp_path: Path, failed_stage: str
) -> None:
    output = tmp_path / f"failed-{failed_stage}"

    result = _run_runner(fake_hub, output, FAKE_FAIL_STAGE=failed_stage)

    assert result.returncode == 23
    commands = (output / "commands.tsv").read_text(encoding="utf-8")
    for diagnostic in ("api:lint", "api:typecheck", "api:test:ci", "api:audit"):
        assert diagnostic in commands
    summary = (output / "summary.md").read_text(encoding="utf-8")
    assert "§8.1 satisfied: no" in summary
    assert "Overall verdict: failed" in summary
    if failed_stage == "uv-lock":
        assert not (output / "resolved-versions.txt").exists()
        assert "Resolved versions: unavailable (uv-lock blocked)" in summary


def test_diagnostic_divergence_is_recorded_without_changing_required_verdict(
    fake_hub: tuple[Path, str, Path, Path], tmp_path: Path
) -> None:
    output = tmp_path / "divergence"

    result = _run_runner(fake_hub, output, FAKE_FAIL_STAGE="api-lint")

    assert result.returncode == 0, result.stderr
    summary = (output / "summary.md").read_text(encoding="utf-8")
    assert "Overall verdict: green" in summary
    assert "§8.1 satisfied: yes" in summary
    assert "Diagnostic divergence" in summary
    assert "api:lint" in summary


@pytest.mark.parametrize(
    ("argument", "value", "message"),
    [
        ("--python", "3.13", "Python must be 3.14 or 3.15"),
        ("--commit", "not-a-commit", "Commit is not resolvable"),
    ],
)
def test_runner_rejects_invalid_python_or_commit(
    fake_hub: tuple[Path, str, Path, Path],
    tmp_path: Path,
    argument: str,
    value: str,
    message: str,
) -> None:
    repo, commit, bin_dir, invocation_log = fake_hub
    argv = [
        "/bin/bash",
        str(RUNNER),
        "--hub-repo",
        str(repo),
        "--commit",
        commit,
        "--python",
        "3.14",
        "--output",
        str(tmp_path / "evidence"),
    ]
    argv[argv.index(argument) + 1] = value

    result = _run(argv, env=_runner_env(bin_dir, invocation_log))

    assert result.returncode != 0
    assert message in result.stderr


def test_runner_rejects_output_inside_source_tree(fake_hub: tuple[Path, str, Path, Path]) -> None:
    repo, _, _, _ = fake_hub

    result = _run_runner(fake_hub, repo / "evidence")

    assert result.returncode != 0
    assert "outside the hub and sandbox repositories" in result.stderr


def test_interrupt_cleans_scratch_and_preserves_completed_artifacts(
    fake_hub: tuple[Path, str, Path, Path], tmp_path: Path
) -> None:
    repo, commit, bin_dir, invocation_log = fake_hub
    output = tmp_path / "interrupted"
    child_pid_file = tmp_path / "child.pid"
    process = subprocess.Popen(  # noqa: S603 - fixed test-owned runner argv
        [
            "/bin/bash",
            str(RUNNER),
            "--hub-repo",
            str(repo),
            "--commit",
            commit,
            "--python",
            "3.14",
            "--output",
            str(output),
        ],
        env=_runner_env(
            bin_dir,
            invocation_log,
            FAKE_SLEEP_STAGE="uv-lock",
            FAKE_CHILD_PID_FILE=str(child_pid_file),
        ),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    deadline = time.monotonic() + 10
    while not child_pid_file.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert child_pid_file.exists()
    child_pid = int(child_pid_file.read_text(encoding="utf-8"))

    process.send_signal(signal.SIGINT)
    _, stderr = process.communicate(timeout=10)

    assert process.returncode != 0, stderr
    run_env = (output / "run.env").read_text(encoding="utf-8")
    scratch = Path(
        next(
            line.split("=", maxsplit=1)[1]
            for line in run_env.splitlines()
            if line.startswith("scratch=")
        )
    )
    assert not scratch.exists()
    assert (output / "migration.diff").exists()
    with pytest.raises(ProcessLookupError):
        os.kill(child_pid, 0)


@pytest.mark.parametrize(
    "missing_path",
    [
        "services/api/pyproject.toml",
        "services/api/uv.lock",
        "services/api/app",
        "services/api/tests",
    ],
)
def test_runner_rejects_archive_missing_required_api_lane_path(
    fake_hub: tuple[Path, str, Path, Path], tmp_path: Path, missing_path: str
) -> None:
    repo, _, bin_dir, invocation_log = fake_hub
    _git(repo, "rm", "-qr", missing_path)
    _git(repo, "commit", "-qm", f"remove {missing_path}")
    commit = _git(repo, "rev-parse", "HEAD")

    result = _run(
        [
            "/bin/bash",
            str(RUNNER),
            "--hub-repo",
            str(repo),
            "--commit",
            commit,
            "--python",
            "3.14",
            "--output",
            str(tmp_path / "evidence"),
        ],
        env=_runner_env(bin_dir, invocation_log),
    )

    assert result.returncode != 0
    assert f"missing required full-repository path: {missing_path}" in result.stderr


@pytest.mark.parametrize("option", ["--hub-repo", "--commit", "--python", "--output"])
def test_runner_rejects_option_without_value(option: str) -> None:
    result = _run(["/bin/bash", str(RUNNER), option], timeout=2)

    assert result.returncode == 2
    assert f"Option requires a value: {option}" in result.stderr


def test_runner_rejects_output_in_sandbox_or_through_symlink(
    fake_hub: tuple[Path, str, Path, Path], tmp_path: Path
) -> None:
    repo, commit, bin_dir, invocation_log = fake_hub
    common = [
        "/bin/bash",
        str(RUNNER),
        "--hub-repo",
        str(repo),
        "--commit",
        commit,
        "--python",
        "3.14",
        "--output",
    ]
    sandbox_output = ROOT / ".task3-evidence-must-not-exist"
    sandbox_result = _run([*common, str(sandbox_output)], env=_runner_env(bin_dir, invocation_log))
    assert sandbox_result.returncode != 0
    assert not sandbox_output.exists()

    link = tmp_path / "linked-output"
    link.symlink_to(repo, target_is_directory=True)
    link_result = _run([*common, str(link)], env=_runner_env(bin_dir, invocation_log))
    assert link_result.returncode != 0
    assert "must not already exist" in link_result.stderr


def test_missing_typecheck_task_is_recorded_not_invented(
    fake_hub: tuple[Path, str, Path, Path], tmp_path: Path
) -> None:
    repo, _, bin_dir, invocation_log = fake_hub
    mise = repo / "mise.toml"
    mise.write_text(
        mise.read_text(encoding="utf-8").replace(
            'run = "ty check"', 'run = "ruff format --check ."'
        ),
        encoding="utf-8",
    )
    _git(repo, "add", "mise.toml")
    _git(repo, "commit", "-qm", "remove ty task")
    commit = _git(repo, "rev-parse", "HEAD")
    output = tmp_path / "evidence"

    result = _run(
        [
            "/bin/bash",
            str(RUNNER),
            "--hub-repo",
            str(repo),
            "--commit",
            commit,
            "--python",
            "3.14",
            "--output",
            str(output),
        ],
        env=_runner_env(bin_dir, invocation_log),
    )

    assert result.returncode == 0, result.stderr
    summary = (output / "summary.md").read_text(encoding="utf-8")
    assert "missing / not executed" in summary
    assert "typecheck-missing" in summary


def test_summarizer_requires_exact_required_stage_schema(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact"
    artifact.mkdir()
    (artifact / "junit").mkdir()
    (artifact / "logs").mkdir()
    (artifact / "metadata.env").write_text("hub_commit=abc\npython=3.14\n", encoding="utf-8")
    (artifact / "commands.tsv").write_text(
        "role\tstage\tcommand\texit\tlog\nrequired\tuv-lock\tuv lock\t0\tlogs/uv-lock.log\n",
        encoding="utf-8",
    )

    result = _run([sys.executable, str(SUMMARIZER), "--artifact", str(artifact)])

    assert result.returncode == 0, result.stderr
    summary = (artifact / "summary.md").read_text(encoding="utf-8")
    assert "Overall verdict: failed" in summary
    assert "§8.1 satisfied: no" in summary
    assert "recorded ['uv-lock']" in summary


def test_summarizer_marks_corrupt_junit_unavailable(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact"
    (artifact / "junit").mkdir(parents=True)
    (artifact / "logs").mkdir()
    (artifact / "metadata.env").write_text("hub_commit=abc\npython=3.14\n", encoding="utf-8")
    (artifact / "commands.tsv").write_text(
        "role\tstage\tcommand\texit\tlog\n"
        "required\tuv-lock\tuv lock\t0\tlogs/uv-lock.log\n"
        "required\tuv-sync\tuv sync\t0\tlogs/uv-sync.log\n"
        "required\tapi-check\tmise run api:check\t0\tlogs/api-check.log\n"
        "diagnostic\tapi-test-ci\tmise run api:test:ci\t1\tlogs/api-test-ci.log\n",
        encoding="utf-8",
    )
    (artifact / "junit" / "api-check.xml").write_text("<broken", encoding="utf-8")

    result = _run([sys.executable, str(SUMMARIZER), "--artifact", str(artifact)])

    assert result.returncode == 0, result.stderr
    summary = (artifact / "summary.md").read_text(encoding="utf-8")
    assert "api-check` unavailable (ParseError)" in summary
    assert "api-test-ci` unavailable (missing report)" in summary


def test_summarizer_aggregates_junit_skips_warning_origins_and_audit(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact"
    (artifact / "junit").mkdir(parents=True)
    (artifact / "logs").mkdir()
    (artifact / "metadata.env").write_text(
        "hub_commit=abc123\npython=3.14\nreport_injection=PYTEST_ADDOPTS\n"
        "typecheck_task=api:typecheck\n",
        encoding="utf-8",
    )
    (artifact / "commands.tsv").write_text(
        "role\tstage\tcommand\texit\tlog\n"
        "required\tuv-lock\tuv lock\t0\tlogs/uv-lock.log\n"
        "required\tuv-sync\tuv sync\t0\tlogs/uv-sync.log\n"
        "required\tapi-check\tmise run api:check\t0\tlogs/api-check.log\n"
        "diagnostic\tapi-test-ci\tmise run api:test:ci\t0\tlogs/api-test-ci.log\n"
        "diagnostic\tapi-audit\tmise run api:audit\t0\tlogs/api-audit.log\n",
        encoding="utf-8",
    )
    (artifact / "junit" / "api-test-ci.xml").write_text(
        textwrap.dedent(
            """\
            <testsuite tests="4" failures="1" errors="0" skipped="2">
              <testcase classname="tests.unit.test_ok" name="test_ok" />
              <testcase classname="tests.unit.test_bad" name="test_bad"><failure message="boom" /></testcase>
              <testcase classname="tests.integration.test_ollama" name="test_live">
                <properties><property name="service" value="ollama"/><property name="marker" value="integration"/></properties>
                <skipped message="daemon unavailable" />
              </testcase>
              <testcase classname="tests.e2e.test_search" name="test_search">
                <properties><property name="service" value="search"/><property name="marker" value="e2e"/></properties>
                <skipped message="missing token" />
              </testcase>
            </testsuite>
            """
        ),
        encoding="utf-8",
    )
    (artifact / "junit" / "api-check.xml").write_text(
        (artifact / "junit" / "api-test-ci.xml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (artifact / "resolved-versions.txt").write_text("demo==1.0.0\n", encoding="utf-8")
    (artifact / "logs" / "api-test-ci.log").write_text(
        "pkg/tests/test_api.py:7: DeprecationWarning: legacy api\n"
        ".venv/lib/python3.14/site-packages/starlette/testclient.py:9: "
        "StarletteDeprecationWarning: TestClient is deprecated\n",
        encoding="utf-8",
    )
    (artifact / "logs" / "api-audit.log").write_text(
        "No known vulnerabilities found\n", encoding="utf-8"
    )

    result = _run([sys.executable, str(SUMMARIZER), "--artifact", str(artifact)])

    assert result.returncode == 0, result.stderr
    summary = (artifact / "summary.md").read_text(encoding="utf-8")
    assert summary.startswith("# Hub Python verification: ledger essentials")
    assert "Hub commit: `abc123`" in summary
    assert "Python: `3.14`" in summary
    assert summary.count("4 total, 1 passed, 1 failed, 0 errors, 2 skipped") >= 2
    assert "8 total" not in summary
    assert "ollama / integration / daemon unavailable" in summary
    assert "search / e2e / missing token" in summary
    assert "DeprecationWarning" in summary and "origin `pkg`" in summary
    assert "StarletteDeprecationWarning" in summary and "origin `starlette`" in summary
    assert "No known vulnerabilities found" in summary
    assert "uv lock" in summary and "uv sync" in summary and "api:check" in summary
    assert "ruff" in summary and "ty check" in summary
    assert "pytest" in summary and "pip-audit" in summary
    assert "Report-only JUnit injection" in summary
