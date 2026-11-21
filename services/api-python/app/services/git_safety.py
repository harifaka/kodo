"""Read-only Git working-tree inspection.

Kodo never runs mutating Git commands (no add/commit/checkout/stash/reset). Optional locks are
disabled so ``git status`` does not even refresh the index: inspection leaves the repository
byte-identical.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

GIT_TIMEOUT_SECONDS = 5


class GitStatus(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    is_git_repo: bool = False
    branch: str | None = None
    is_dirty: bool = False
    dirty_files: list[str] = Field(default_factory=list)
    untracked_count: int = 0
    git_available: bool = True
    warning: str | None = None


def inspect_git_status(root_path: str) -> GitStatus:
    """Inspect a workspace without ever raising or mutating the repository."""
    try:
        root = Path(root_path).expanduser().resolve(strict=True)
    except OSError:
        return GitStatus(
            is_git_repo=False,
            warning=f"Workspace root does not exist or is not accessible: {root_path}",
        )

    if not root.is_dir():
        return GitStatus(is_git_repo=False, warning=f"Workspace root is not a directory: {root_path}")

    probe = _git(root, "rev-parse", "--is-inside-work-tree")
    if probe is None:
        return GitStatus(
            is_git_repo=False,
            git_available=False,
            warning=(
                "Git is not installed or not on PATH, so Kodo cannot detect uncommitted changes. "
                "Apply will require an explicit override."
            ),
        )

    if probe.returncode != 0 or probe.stdout.strip() != "true":
        return GitStatus(
            is_git_repo=False,
            warning=(
                "The workspace is not a Git repository. Kodo cannot inspect pending changes and a "
                "rollback is the only way back to the previous bytes."
            ),
        )

    branch = _branch(root)
    status = _git(root, "status", "--porcelain", "--untracked-files=normal")
    if status is None:
        return GitStatus(
            is_git_repo=True,
            branch=branch,
            git_available=False,
            warning="Git status could not be read, so the working tree state is unknown.",
        )

    if status.returncode != 0:
        detail = status.stderr.strip() or f"exit code {status.returncode}"
        return GitStatus(
            is_git_repo=True,
            branch=branch,
            warning=f"git status failed: {detail[:200]}",
        )

    dirty_files, untracked_count = _parse_porcelain(status.stdout)
    return GitStatus(
        is_git_repo=True,
        branch=branch,
        is_dirty=bool(dirty_files),
        dirty_files=dirty_files,
        untracked_count=untracked_count,
    )


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str] | None:
    """Run a read-only git command; ``None`` means the git binary is unavailable."""
    try:
        return subprocess.run(
            ["git", *args],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_SECONDS,
            env=_git_env(),
            check=False,
        )
    except FileNotFoundError:
        return None
    except (subprocess.TimeoutExpired, OSError):
        return None


def _git_env() -> dict[str, str]:
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    # Never take optional locks: `git status` must not refresh/write .git/index.
    env["GIT_OPTIONAL_LOCKS"] = "0"
    return env


def _branch(root: Path) -> str | None:
    for args in (
        ("symbolic-ref", "--quiet", "--short", "HEAD"),
        ("rev-parse", "--abbrev-ref", "HEAD"),
    ):
        result = _git(root, *args)
        if result is not None and result.returncode == 0:
            value = result.stdout.strip()
            if value:
                return value
    return None


def _parse_porcelain(output: str) -> tuple[list[str], int]:
    files: list[str] = []
    untracked = 0
    seen: set[str] = set()

    for raw_line in output.splitlines():
        line = raw_line.rstrip("\r")
        if len(line) < 4:
            continue
        code = line[:2]
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        path = path.strip().strip('"')
        if not path or path in seen:
            continue
        seen.add(path)
        files.append(path)
        if code == "??":
            untracked += 1

    return files, untracked
