#!/usr/bin/env python3
"""Summarize a hub Python verification artifact using only the standard library."""

from __future__ import annotations

import argparse
import csv
import re
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

REQUIRED_STAGES = ("uv-lock", "uv-sync", "api-check")
WARNING_RE = re.compile(
    r"^(?P<path>[^:\n]+):(?P<line>\d+):\s*"
    r"(?P<category>StarletteDeprecationWarning|DeprecationWarning):\s*(?P<message>.+)$",
    re.MULTILINE,
)


@dataclass(frozen=True)
class Command:
    """One recorded verification command."""

    role: str
    stage: str
    command: str
    exit_code: int
    log: str


@dataclass(frozen=True)
class JunitResult:
    """Counts for one command-scoped JUnit report."""

    status: str
    counts: Counter[str]

    def compact(self) -> str:
        """Return a ledger-friendly one-line count."""
        if self.status != "available":
            return self.status
        return (
            f"{self.counts['total']} total, {self.counts['passed']} passed, "
            f"{self.counts['failed']} failed, {self.counts['errors']} errors, "
            f"{self.counts['skipped']} skipped"
        )


def parse_args() -> argparse.Namespace:
    """Parse the artifact directory argument."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact", required=True, type=Path)
    return parser.parse_args()


def read_metadata(path: Path) -> dict[str, str]:
    """Read the runner's deliberately simple key=value metadata."""
    metadata: dict[str, str] = {}
    if not path.exists():
        return metadata
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            key, value = line.split("=", maxsplit=1)
            metadata[key] = value
    return metadata


def read_commands(path: Path) -> list[Command]:
    """Read command results from the stable TSV interchange file."""
    with path.open(encoding="utf-8", newline="") as handle:
        rows = csv.DictReader(handle, delimiter="\t")
        return [
            Command(
                role=row["role"],
                stage=row["stage"],
                command=row["command"],
                exit_code=int(row["exit"]),
                log=row["log"],
            )
            for row in rows
        ]


def parse_junit(report: Path) -> tuple[JunitResult, Counter[tuple[str, str, str]]]:
    """Parse one bounded JUnit file and preserve structured skip dimensions."""
    counts: Counter[str] = Counter()
    skips: Counter[tuple[str, str, str]] = Counter()
    if not report.is_file():
        return JunitResult("unavailable (missing report)", counts), skips
    try:
        if report.stat().st_size > 10 * 1024 * 1024:
            raise ET.ParseError("JUnit report exceeds the 10 MiB safety limit")
        report_text = report.read_text(encoding="utf-8", errors="strict")
        if "<!DOCTYPE" in report_text or "<!ENTITY" in report_text:
            raise ET.ParseError("DTD and entity declarations are not accepted")
        root = ET.fromstring(  # noqa: S314 - bounded local JUnit after explicit DTD/entity rejection
            report_text
        )
    except (ET.ParseError, UnicodeError) as error:
        return JunitResult(f"unavailable ({type(error).__name__})", counts), skips
    for case in root.iter("testcase"):
        counts["total"] += 1
        failure = case.find("failure")
        error = case.find("error")
        skipped = case.find("skipped")
        if failure is not None:
            counts["failed"] += 1
        elif error is not None:
            counts["errors"] += 1
        elif skipped is not None:
            counts["skipped"] += 1
            properties = {
                item.get("name", ""): item.get("value", "")
                for item in case.findall("./properties/property")
            }
            service = properties.get("service", "unknown")
            marker = properties.get("marker", "unknown")
            reason = skipped.get("message") or (skipped.text or "unspecified").strip()
            skips[(service, marker, reason)] += 1
        else:
            counts["passed"] += 1
    return JunitResult("available", counts), skips


def junit_results(
    artifact: Path, commands: list[Command]
) -> tuple[dict[str, JunitResult], Counter[tuple[str, str, str, str]]]:
    """Return stage-scoped counts so repeated suites are never summed together."""
    results: dict[str, JunitResult] = {}
    all_skips: Counter[tuple[str, str, str, str]] = Counter()
    for command in commands:
        if command.stage not in {"api-check", "api-test-ci"}:
            continue
        result, skips = parse_junit(artifact / "junit" / f"{command.stage}.xml")
        results[command.stage] = result
        for (service, marker, reason), count in skips.items():
            all_skips[(command.stage, service, marker, reason)] += count
    return results, all_skips


def warning_origin(path: str) -> str:
    """Derive an origin package from a warning source path."""
    normalized = path.replace("\\", "/")
    marker = "/site-packages/"
    if marker in normalized:
        remainder = normalized.split(marker, maxsplit=1)[1]
        return remainder.split("/", maxsplit=1)[0].replace("-", "_")
    return normalized.lstrip("./").split("/", maxsplit=1)[0] or "unknown"


def collect_warnings(artifact: Path, commands: list[Command]) -> Counter[tuple[str, str, str]]:
    """Collect warnings per stage; repeated gates remain visibly separate evidence."""
    warnings: Counter[tuple[str, str, str]] = Counter()
    for command in commands:
        log_path = artifact / command.log
        if not log_path.exists():
            continue
        text = log_path.read_text(encoding="utf-8", errors="replace")
        for match in WARNING_RE.finditer(text):
            warnings[
                (command.stage, match.group("category"), warning_origin(match.group("path")))
            ] += 1
    return warnings


def audit_result(artifact: Path, commands: list[Command]) -> str:
    """Extract the most useful pip-audit result line."""
    candidates = [command for command in commands if "audit" in command.stage]
    for command in reversed(candidates):
        path = artifact / command.log
        if not path.exists():
            continue
        for line in reversed(path.read_text(encoding="utf-8", errors="replace").splitlines()):
            if "No known vulnerabilities found" in line or "known vulnerabilities" in line:
                return f"{line.strip()} (`{command.log}`)"
    return "No audit result found"


def required_schema_error(commands: list[Command]) -> str | None:
    """Require exactly one ordered record for each required phase."""
    stages = [command.stage for command in commands if command.role == "required"]
    if stages != list(REQUIRED_STAGES):
        return f"expected {list(REQUIRED_STAGES)!r}, recorded {stages!r}"
    return None


def diagnostic_divergence(commands: list[Command]) -> list[str]:
    """Report disagreement between the verdict gate and diagnostic tasks."""
    check = next((command for command in commands if command.stage == "api-check"), None)
    diagnostics = [command for command in commands if command.role == "diagnostic"]
    if check is None or not diagnostics:
        return []
    failures = [command.stage for command in diagnostics if command.exit_code != 0]
    if check.exit_code == 0 and failures:
        return [f"api:check passed while diagnostics failed: {', '.join(failures)}"]
    if check.exit_code != 0 and not failures:
        return ["api:check failed while every diagnostic command passed"]
    return []


def command_map(metadata: dict[str, str]) -> list[tuple[str, str]]:
    """Map requirement-level commands to the upstream task that owns them."""
    typecheck_task = metadata.get("typecheck_task", "missing")
    typecheck_owner = (
        f"diagnostic task `{typecheck_task}`"
        if typecheck_task != "missing"
        else "missing / not executed"
    )
    return [
        ("uv lock", "standalone required phase `uv-lock`"),
        ("uv sync", "standalone required phase `uv-sync`"),
        ("ruff", "diagnostic task `api:lint`"),
        ("ty check", typecheck_owner),
        ("pytest (unit + integration + e2e)", "diagnostic task `api:test:ci`"),
        ("pip-audit", "diagnostic task `api:audit`"),
    ]


def resolved_versions(artifact: Path, metadata: dict[str, str]) -> str:
    """Return a compact reference to the resolved package inventory."""
    path = artifact / "resolved-versions.txt"
    if not path.is_file():
        if metadata.get("uv_lock_status") == "blocked":
            return "unavailable (uv-lock blocked)"
        return "unavailable"
    entries = [line for line in path.read_text(encoding="utf-8").splitlines() if line]
    return f"{len(entries)} packages (`resolved-versions.txt`)"


def render_summary(artifact: Path) -> str:
    """Render the ledger-ready Markdown summary."""
    metadata = read_metadata(artifact / "metadata.env")
    commands = read_commands(artifact / "commands.tsv")
    schema_error = required_schema_error(commands)
    required = [command for command in commands if command.role == "required"]
    is_green = schema_error is None and all(command.exit_code == 0 for command in required)
    reports, skips = junit_results(artifact, commands)
    warnings = collect_warnings(artifact, commands)
    divergences = diagnostic_divergence(commands)

    lines = [
        "# Hub Python verification: ledger essentials",
        "",
        f"- Hub commit: `{metadata.get('hub_commit', 'unknown')}`",
        f"- Python: `{metadata.get('python', 'unknown')}`",
        f"- Overall verdict: {'green' if is_green else 'failed'}",
        f"- §8.1 satisfied: {'yes' if is_green else 'no'}",
        f"- Required phase schema: {schema_error or 'valid'}",
        f"- Resolved versions: {resolved_versions(artifact, metadata)}",
        "- Commands: " + "; ".join(f"`{item.command}` exit {item.exit_code}" for item in commands),
        "- Pytest reports: "
        + "; ".join(f"`{stage}` {result.compact()}" for stage, result in reports.items()),
        "- Skip reasons: "
        + (
            "; ".join(
                f"{stage}/{service}/{marker}/{reason} ({count})"
                for (stage, service, marker, reason), count in sorted(skips.items())
            )
            if skips
            else "none recorded"
        ),
        "- Warning table: "
        + (
            "; ".join(
                f"{stage}/{category}/origin={origin} ({count})"
                for (stage, category, origin), count in sorted(warnings.items())
            )
            if warnings
            else "none recorded"
        ),
        f"- Audit: {audit_result(artifact, commands)}",
        "- Migration: `migration.diff`",
        "",
        "## Command results",
        "",
        "| Role | Stage | Command | Exit | Counts | Raw log |",
        "| --- | --- | --- | ---: | --- | --- |",
    ]
    lines.extend(
        f"| {item.role} | {item.stage} | `{item.command}` | {item.exit_code} | "
        f"{reports[item.stage].compact() if item.stage in reports else 'n/a'} | `{item.log}` |"
        for item in commands
    )
    lines.extend(
        ["", "## R1.2 command-to-task map", "", "| Command | Upstream owner |", "| --- | --- |"]
    )
    lines.extend(f"| `{command}` | {owner} |" for command, owner in command_map(metadata))
    lines.extend(["", "## Pytest skips", ""])
    if skips:
        lines.extend(
            f"- {stage} / {service} / {marker} / {reason}: {count} (`junit/{stage}.xml`)"
            for (stage, service, marker, reason), count in sorted(skips.items())
        )
    else:
        lines.append("- None recorded")
    lines.extend(["", "## Deprecation warnings", ""])
    if warnings:
        lines.extend(
            f"- {stage}: {category}, origin `{origin}`, {count} occurrence(s) (`logs/{stage}.log`)"
            for (stage, category, origin), count in sorted(warnings.items())
        )
    else:
        lines.append("- None recorded")
    lines.extend(["", "## Diagnostic divergence", ""])
    if divergences:
        lines.extend(f"- {item}" for item in divergences)
    else:
        lines.append("- None")
    lines.extend(
        [
            "",
            "## Report collection note",
            "",
            "Report-only JUnit injection used `PYTEST_ADDOPTS=-rsx --junitxml=...`; "
            "it adds evidence without changing warning filters or pass/fail semantics. "
            "Repeated suites are reported per stage and are never summed.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    """Write summary.md beside the raw artifact files."""
    args = parse_args()
    artifact = args.artifact.resolve()
    summary = render_summary(artifact)
    (artifact / "summary.md").write_text(summary, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
