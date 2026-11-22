import re
import subprocess
import sys
from fnmatch import fnmatch
from pathlib import Path, PurePosixPath

from resume_agent.config import ConfigError, load_config

BLOCKED_NAME_PATTERNS = ("*.pdf", "listing.*", "*.xlsx", "*.xls", "*.docx", "~$*", "config.yaml")
BLOCKED_DIRS = (".state", "drafts")
PROTON_ACCOUNT_PATH = re.compile(r"ProtonDrive-[^/\s\"'*]*@")


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def staged_paths(repo: Path) -> list[str]:
    output = git(repo, "diff", "--cached", "--name-only", "-z", "--diff-filter=ACMR")
    return [path for path in output.split("\0") if path]


def staged_added_lines(repo: Path) -> list[str]:
    output = git(repo, "diff", "--cached", "-U0", "--no-color", "--text", "--diff-filter=ACMR")
    lines = output.splitlines()
    return [line[1:] for line in lines if line.startswith("+") and not line.startswith("+++")]


def blocked_by_name(path: str) -> bool:
    posix = PurePosixPath(path)
    name = posix.name.lower()
    in_blocked_dir = any(part in BLOCKED_DIRS for part in posix.parts[:-1])
    return in_blocked_dir or any(fnmatch(name, pattern) for pattern in BLOCKED_NAME_PATTERNS)


def contains_data_root(text: str, markers: set[str]) -> bool:
    return bool(PROTON_ACCOUNT_PATH.search(text)) or any(marker in text for marker in markers)


def data_root_markers(data_root: Path) -> set[str]:
    markers = {str(data_root)}
    home = str(Path.home())
    if str(data_root).startswith(home):
        markers.add("~" + str(data_root)[len(home) :])
    return markers


def find_violations(repo: Path, markers: set[str]) -> list[str]:
    violations = []
    for path in staged_paths(repo):
        if blocked_by_name(path):
            violations.append(f"{path}: data-like file type")
        if contains_data_root(path, markers):
            violations.append(f"{path}: path contains data_root")

    if any(contains_data_root(line, markers) for line in staged_added_lines(repo)):
        violations.append("staged content contains the data_root path")
    return violations


def run(repo: Path) -> int:
    try:
        markers = data_root_markers(load_config().data_root)
    except ConfigError as error:
        print(
            f"pre-commit: config not loaded, checking Proton account paths only:\n{error}",
            file=sys.stderr,
        )
        markers = set()

    violations = find_violations(repo, markers)
    if not violations:
        return 0

    print("pre-commit: blocked, these must never reach GitHub:", file=sys.stderr)
    for violation in violations:
        print(f"  {violation}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(run(Path.cwd()))
