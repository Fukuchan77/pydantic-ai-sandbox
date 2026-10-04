#!/usr/bin/env bash
# Verify an immutable hub commit under a migrated Python series and preserve evidence.
set -uo pipefail

usage() {
  cat >&2 <<'EOF'
Usage: verify-hub-python.sh --hub-repo PATH --commit SHA --python 3.14|3.15 --output ABSOLUTE_PATH
EOF
}

need_value() {
  local option=$1
  local count=$2
  if ((count < 2)); then
    printf 'Option requires a value: %s\n' "$option" >&2
    usage
    exit 2
  fi
}

hub_repo=""
commit=""
python_series=""
output=""
while (($#)); do
  case "$1" in
    --hub-repo) need_value "$1" "$#"; hub_repo=$2; shift 2 ;;
    --commit) need_value "$1" "$#"; commit=$2; shift 2 ;;
    --python) need_value "$1" "$#"; python_series=$2; shift 2 ;;
    --output) need_value "$1" "$#"; output=$2; shift 2 ;;
    *) usage; printf 'Unknown argument: %s\n' "$1" >&2; exit 2 ;;
  esac
done

if [[ -z "$hub_repo" || -z "$commit" || -z "$python_series" || -z "$output" ]]; then
  usage
  exit 2
fi
if [[ "$python_series" != "3.14" && "$python_series" != "3.15" ]]; then
  printf 'Python must be 3.14 or 3.15, got: %s\n' "$python_series" >&2
  exit 2
fi
if ! hub_repo=$(cd "$hub_repo" 2>/dev/null && pwd -P); then
  printf 'Hub repository does not exist: %s\n' "$hub_repo" >&2
  exit 2
fi
if ! git -C "$hub_repo" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  printf 'Hub path is not a Git repository: %s\n' "$hub_repo" >&2
  exit 2
fi
if ! resolved_commit=$(git -C "$hub_repo" rev-parse --verify "${commit}^{commit}" 2>/dev/null); then
  printf 'Commit is not resolvable: %s\n' "$commit" >&2
  exit 2
fi
case "$output" in
  /*) ;;
  *) printf 'Output must be an absolute path: %s\n' "$output" >&2; exit 2 ;;
esac
if [[ -e "$output" || -L "$output" ]]; then
  printf 'Output path must not already exist: %s\n' "$output" >&2
  exit 2
fi
output_parent=$(dirname "$output")
output_name=$(basename "$output")
if ! output_parent=$(cd "$output_parent" 2>/dev/null && pwd -P); then
  printf 'Output parent must already exist: %s\n' "$(dirname "$output")" >&2
  exit 2
fi
output="$output_parent/$output_name"
sandbox_root=$(cd "$(dirname "$0")/.." && pwd -P)
for source_root in "$hub_repo" "$sandbox_root"; do
  case "$output/" in
    "$source_root/"*)
      printf 'Output must be outside the hub and sandbox repositories: %s\n' "$output" >&2
      exit 2
      ;;
  esac
done
if ! mkdir "$output"; then
  printf 'Failed to create exclusive output directory: %s\n' "$output" >&2
  exit 2
fi
output=$(cd "$output" && pwd -P)
for source_root in "$hub_repo" "$sandbox_root"; do
  case "$output/" in
    "$source_root/"*)
      printf 'Resolved output entered a source repository: %s\n' "$output" >&2
      exit 2
      ;;
  esac
done
mkdir "$output/logs" "$output/junit"
printf 'role\tstage\tcommand\texit\tlog\n' > "$output/commands.tsv"
printf 'hub_commit=%s\npython=%s\nreport_injection=PYTEST_ADDOPTS\n' \
  "$resolved_commit" "$python_series" > "$output/metadata.env"

scratch=$(mktemp -d "${TMPDIR:-/tmp}/hub-python-verify.XXXXXX")
scratch=$(cd "$scratch" && pwd -P)
active_pid=""
terminate_active() {
  local pid=$active_pid
  [[ -z "$pid" ]] && return
  active_pid=""
  kill -TERM -- "-$pid" 2>/dev/null || true
  for _ in {1..50}; do
    kill -0 "$pid" 2>/dev/null || break
    sleep 0.02
  done
  if kill -0 "$pid" 2>/dev/null; then
    kill -KILL -- "-$pid" 2>/dev/null || true
  fi
  wait "$pid" 2>/dev/null || true
}
cleanup() {
  terminate_active
  rm -rf "$scratch"
}
on_interrupt() {
  cleanup
  exit 130
}
trap cleanup EXIT
trap on_interrupt INT TERM HUP
printf 'scratch=%s\n' "$scratch" > "$output/run.env"

if ! git -C "$hub_repo" archive "$resolved_commit" | tar -x -C "$scratch"; then
  printf 'Failed to archive commit %s\n' "$resolved_commit" >&2
  exit 2
fi
for required_path in \
  services/api/.python-version \
  services/api/pyproject.toml \
  services/api/uv.lock \
  services/api/app \
  services/api/tests \
  packages/evals \
  .github/workflows/api.yml \
  packages/schemas/src/generated; do
  if [[ ! -e "$scratch/$required_path" ]]; then
    printf 'Archived commit is missing required full-repository path: %s\n' "$required_path" >&2
    exit 2
  fi
  if [[ -L "$scratch/$required_path" ]]; then
    printf 'Archived required path must not be a symlink: %s\n' "$required_path" >&2
    exit 2
  fi
done

python3 - "$scratch" "$python_series" <<'PY'
from __future__ import annotations

import re
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve(strict=True)
series = sys.argv[2]
target = series.replace(".", "")


def assert_scratch_path(path: Path, *, kind: str) -> None:
    relative = path.relative_to(root)
    current = root
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise SystemExit(f"migration path must not contain symlinks: {relative}")
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(root):
        raise SystemExit(f"migration path escaped scratch: {relative}")
    if kind == "file" and not resolved.is_file():
        raise SystemExit(f"migration expected regular file: {relative}")
    if kind == "directory" and not resolved.is_dir():
        raise SystemExit(f"migration expected real directory: {relative}")


for relative, kind in {
    "mise.toml": "file",
    "services/api/.python-version": "file",
    "services/api/pyproject.toml": "file",
    "services/api/uv.lock": "file",
    "services/api/app": "directory",
    "services/api/tests": "directory",
}.items():
    assert_scratch_path(root / relative, kind=kind)


def replace_exact(path: Path, old: str, new: str, label: str) -> None:
    if not path.is_file():
        raise SystemExit(f"migration expected {label} file: {path}")
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"migration expected exactly one {label} in {path}, found {count}")
    path.write_text(text.replace(old, new), encoding="utf-8")


replace_exact(
    root / "services/api/.python-version", "3.13", series, "services/api Python version pin"
)
api_pyproject = root / "services/api/pyproject.toml"
replace_exact(
    api_pyproject,
    'requires-python = ">=3.13"',
    f'requires-python = ">={series}"',
    "services/api Python floor",
)
replace_exact(
    api_pyproject,
    'target-version = "py313"',
    f'target-version = "py{target}"',
    "services/api Ruff target",
)
expectation_matches: list[tuple[Path, str]] = []
expectation_pattern = re.compile(r'(?m)^(?P<constant>_?EXPECTED_SERIES) = "3\.13"$')
for path in root.glob("services/api/tests/**/*.py"):
    assert_scratch_path(path, kind="file")
    text = path.read_text(encoding="utf-8")
    expectation_matches.extend(
        (path, match.group("constant")) for match in expectation_pattern.finditer(text)
    )
if len(expectation_matches) != 1:
    raise SystemExit(
        "migration expected exactly one interpreter expectation, "
        f"found {len(expectation_matches)}"
    )
expectation_path, expectation_constant = expectation_matches[0]
replace_exact(
    expectation_path,
    f'{expectation_constant} = "3.13"',
    f'{expectation_constant} = "{series}"',
    "interpreter expectation",
)
PY
migration_status=$?
if ((migration_status != 0)); then
  exit "$migration_status"
fi

# git archive has no .git directory; compare each approved migration file with
# its immutable commit version to build one reproducible patch.
: > "$output/migration.diff"
for relative in services/api/.python-version services/api/pyproject.toml; do
  original="$output/.original-${relative//\//_}"
  git -C "$hub_repo" show "$resolved_commit:$relative" > "$original"
  diff -u --label "a/$relative" --label "b/$relative" "$original" "$scratch/$relative" \
    >> "$output/migration.diff" || true
  rm -f "$original"
done
while IFS= read -r baseline_file; do
  relative=${baseline_file#"$scratch/"}
  original="$output/.original-${relative//\//_}"
  git -C "$hub_repo" show "$resolved_commit:$relative" > "$original"
  diff -u --label "a/$relative" --label "b/$relative" "$original" "$baseline_file" \
    >> "$output/migration.diff" || true
  rm -f "$original"
done < <(grep -RIl --include='*.py' \
  -e "_EXPECTED_SERIES = \"$python_series\"" \
  -e "EXPECTED_SERIES = \"$python_series\"" \
  "$scratch/services/api/tests")

export MISE_AUTO_INSTALL=0
export MISE_EXEC_AUTO_INSTALL=0
export MISE_NOT_FOUND_AUTO_INSTALL=0
export MISE_TASK_RUN_AUTO_INSTALL=0
export MISE_TRUSTED_CONFIG_PATHS="$scratch/mise.toml"

typecheck_task=$(python3 - "$scratch/mise.toml" <<'PY'
from __future__ import annotations

import sys
import tomllib
from pathlib import Path

config = tomllib.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
candidates: list[str] = []
for name, task in config.get("tasks", {}).items():
    if isinstance(task, dict):
        run = task.get("run", "")
        text = "\n".join(run) if isinstance(run, list) else str(run)
        if "ty check" in text:
            candidates.append(name)
if "api:lint" in candidates:
    print("api:lint")
elif candidates:
    print(sorted(candidates)[0])
else:
    print("missing")
PY
)
printf 'typecheck_task=%s\n' "$typecheck_task" >> "$output/metadata.env"

run_stage() {
  local role=$1
  local stage=$2
  local cwd=$3
  local command_label=$4
  shift 4
  local log="logs/$stage.log"
  local junit="$output/junit/$stage.xml"
  python3 - "$cwd" "$junit" "$@" > "$output/$log" 2>&1 <<'PY' &
from __future__ import annotations

import errno
import os
import shlex
import shutil
import sys
from pathlib import Path

cwd, junit, *argv = sys.argv[1:]
os.chdir(cwd)
os.environ["PYTEST_ADDOPTS"] = f"-rsx --junitxml={shlex.quote(junit)}"
os.setsid()
executable = shutil.which(argv[0], path=os.environ.get("PATH"))
if executable is None:
    raise SystemExit(f"executable not found: {argv[0]}")
try:
    os.execve(executable, [executable, *argv[1:]], os.environ)
except OSError as error:
    if error.errno not in {errno.EACCES, errno.ENOEXEC}:
        raise
    # Some hermetic test mounts deny direct script exec. Preserve shell-script
    # semantics without falling through to a different executable later on PATH.
    first_line = Path(executable).read_text(encoding="utf-8").splitlines()[0].lstrip()
    interpreter = shlex.split(first_line[2:].strip()) if first_line.startswith("#!") else ["/bin/sh"]
    os.execve(interpreter[0], [*interpreter, executable, *argv[1:]], os.environ)
PY
  active_pid=$!
  wait "$active_pid"
  local stage_status=$?
  active_pid=""
  printf '%s\t%s\t%s\t%s\t%s\n' "$role" "$stage" "$command_label" "$stage_status" "$log" \
    >> "$output/commands.tsv"
  return "$stage_status"
}

record_skipped() {
  local stage=$1
  local command_label=$2
  local reason=$3
  printf '%s\n' "$reason" > "$output/logs/$stage.log"
  printf 'required\t%s\t%s\t125\tlogs/%s.log\n' "$stage" "$command_label" "$stage" \
    >> "$output/commands.tsv"
}

first_required_failure=0
uv_lock_succeeded=0
if ! run_stage required uv-lock "$scratch/services/api" "uv lock" mise exec -- uv lock; then
  first_required_failure=$?
  # `!` normalizes `$?`; recover the recorded exit from the just-written TSV.
  first_required_failure=$(tail -n 1 "$output/commands.tsv" | cut -f4)
  record_skipped uv-sync "uv sync" "blocked: uv-lock failed"
  record_skipped api-check "mise run api:check" "blocked: uv-lock failed"
else
  uv_lock_succeeded=1
  if ! run_stage required uv-sync "$scratch/services/api" "uv sync" mise exec -- uv sync; then
    first_required_failure=$(tail -n 1 "$output/commands.tsv" | cut -f4)
    record_skipped api-check "mise run api:check" "blocked: uv-sync failed"
  elif ! run_stage required api-check "$scratch" "mise run api:check" mise run api:check; then
    first_required_failure=$(tail -n 1 "$output/commands.tsv" | cut -f4)
  fi
fi

# Diagnostics are evidence only and run through every selected task.
run_stage diagnostic api-lint "$scratch" "mise run api:lint" mise run api:lint || true
if [[ "$typecheck_task" == "missing" ]]; then
  printf 'ty check task not found in archived mise.toml\n' > "$output/logs/typecheck-missing.log"
  printf 'diagnostic\ttypecheck-missing\tty check task discovery\t127\tlogs/typecheck-missing.log\n' \
    >> "$output/commands.tsv"
elif [[ "$typecheck_task" != "api:lint" ]]; then
  typecheck_stage=${typecheck_task//:/-}
  run_stage diagnostic "$typecheck_stage" "$scratch" "mise run $typecheck_task" \
    mise run "$typecheck_task" || true
fi
run_stage diagnostic api-test-ci "$scratch" "mise run api:test:ci" mise run api:test:ci || true
run_stage diagnostic api-audit "$scratch" "mise run api:audit" mise run api:audit || true

original="$output/.original-uv.lock"
git -C "$hub_repo" show "$resolved_commit:services/api/uv.lock" > "$original"
diff -u --label a/services/api/uv.lock --label b/services/api/uv.lock \
  "$original" "$scratch/services/api/uv.lock" > "$output/lock.diff" || true
rm -f "$original"
if ((uv_lock_succeeded)); then
  printf 'uv_lock_status=succeeded\n' >> "$output/metadata.env"
  python3 - "$scratch/services/api/uv.lock" > "$output/resolved-versions.txt" <<'PY'
from __future__ import annotations

import sys
import tomllib
from pathlib import Path

data = tomllib.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
for package in sorted(data.get("package", []), key=lambda item: item.get("name", "")):
    name = package.get("name")
    version = package.get("version")
    if name and version:
        print(f"{name}=={version}")
PY
else
  printf 'uv_lock_status=blocked\n' >> "$output/metadata.env"
fi

python3 "$sandbox_root/scripts/summarize_hub_verification.py" --artifact "$output"
summary_status=$?
if ((first_required_failure != 0)); then
  ((summary_status != 0)) && printf 'Summarizer also failed with exit %s\n' "$summary_status" >&2
  exit "$first_required_failure"
fi
if ((summary_status != 0)); then
  printf 'Failed to summarize evidence artifact\n' >&2
  exit "$summary_status"
fi
exit 0
