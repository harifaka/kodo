"""Workspace file discovery with hard safety and size limits."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from app.analyzers.common import posix_rel
from app.analyzers.typescript import SCRIPT_EXTENSIONS
from app.models.ir import Stack

# Directories that never contain first-party architecture.
SKIPPED_DIRECTORIES = frozenset(
    {
        "node_modules", ".git", "bin", "obj", "target", "dist", ".venv", "venv",
        "__pycache__", ".next", ".nuxt", ".turbo", ".cache", "coverage", ".idea",
        ".vs", ".gradle", "build", "out", ".pytest_cache", ".mypy_cache",
        # Phase 12: Python packaging/tooling noise is never first-party architecture.
        ".ruff_cache", ".tox", ".nox", ".eggs", "site-packages", "htmlcov", ".pytype",
    }
)

# Directory suffixes that hold installed packages (`foo.egg-info`) and never source code.
SKIPPED_DIRECTORY_SUFFIXES = (".egg-info",)

MARKER_FILES = frozenset(
    {
        "package.json",
        "pyproject.toml",
        "requirements.txt",
        "requirements-dev.txt",
        "setup.py",
        "setup.cfg",
        "Pipfile",
    }
)

# Mirrors RoslynAnalyzer.GeneratedFileSuffixes: generated sources never hold first-party architecture.
GENERATED_CSHARP_SUFFIXES = (
    ".g.cs",
    ".g.i.cs",
    ".designer.cs",
    ".generated.cs",
    ".assemblyattributes.cs",
    ".assemblyinfo.cs",
)

MAX_SCANNED_FILES = 6000
MAX_FILE_BYTES = 2_000_000

# Mirrors the folder-browser noise list: tests describe behaviour, not architecture.
_PYTHON_TEST_DIRECTORIES = frozenset({"tests", "test", "__tests__"})


@dataclass
class ScanFiles:
    java: list[str] = field(default_factory=list)
    scripts: list[str] = field(default_factory=list)
    csharp: list[str] = field(default_factory=list)
    python: list[str] = field(default_factory=list)
    markers: set[str] = field(default_factory=set)
    warnings: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.java) + len(self.scripts) + len(self.csharp) + len(self.python)


def collect_files(root: Path) -> ScanFiles:
    scan = ScanFiles()
    scanned = 0

    for current_dir, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(
            d
            for d in dirnames
            if d.lower() not in SKIPPED_DIRECTORIES
            and not d.lower().endswith(SKIPPED_DIRECTORY_SUFFIXES)
        )
        current_path = Path(current_dir)

        for filename in sorted(filenames):
            lower = filename.lower()
            if lower in MARKER_FILES:
                scan.markers.add(lower)

            if lower.endswith(".d.ts"):
                continue

            if lower.endswith(".cs") and lower.endswith(GENERATED_CSHARP_SUFFIXES):
                continue

            rel_path = posix_rel(os.path.relpath(current_path / filename, root))
            if lower.endswith(".java"):
                bucket = scan.java
            elif lower.endswith(SCRIPT_EXTENSIONS):
                bucket = scan.scripts
            elif lower.endswith(".cs"):
                bucket = scan.csharp
            elif lower.endswith(".py"):
                if _is_python_test_file(rel_path):
                    continue
                bucket = scan.python
            else:
                continue

            scanned += 1
            if scanned > MAX_SCANNED_FILES:
                scan.warnings.append(
                    f"Scan limit reached: only the first {MAX_SCANNED_FILES} source files were analyzed. "
                    "Point Kodo at a smaller service folder for complete results."
                )
                return scan

            if not _is_reasonable_size(current_path / filename, rel_path, scan):
                continue
            bucket.append(rel_path)

    return scan


def _is_python_test_file(rel_path: str) -> bool:
    parts = rel_path.split("/")
    if any(part.lower() in _PYTHON_TEST_DIRECTORIES for part in parts[:-1]):
        return True
    name = parts[-1].lower()
    return name == "conftest.py" or name.startswith("test_") or name.endswith("_test.py")


def _is_reasonable_size(path: Path, rel_path: str, scan: ScanFiles) -> bool:
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            scan.warnings.append(
                f"Skipped oversized file ({MAX_FILE_BYTES // 1_000_000} MB limit): {rel_path}."
            )
            return False
    except OSError:
        return False
    return True


def detect_stacks(scan: ScanFiles) -> list[Stack]:
    stacks: list[Stack] = []
    if scan.java:
        stacks.append(Stack.SPRING_BOOT)
    if scan.csharp:
        stacks.append(Stack.CSHARP_DOTNET)
    if scan.scripts or "package.json" in scan.markers:
        stacks.append(Stack.NODEJS)
    if scan.python or scan.markers & {
        "pyproject.toml",
        "requirements.txt",
        "requirements-dev.txt",
        "setup.py",
        "setup.cfg",
        "Pipfile",
    }:
        stacks.append(Stack.PYTHON)
    return stacks or [Stack.UNKNOWN]
