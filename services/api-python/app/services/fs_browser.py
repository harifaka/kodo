"""Zero-copy, in-place folder browsing for the local runtimes (Phase 11).

The browser lists real directories on the backend host or bind mount. Nothing is uploaded, copied or
written: the API only reads ``scandir`` metadata and a handful of marker filenames for the badges.

Roots are resolved in this order:

1. **Explicit** ``KODO_BROWSE_ROOTS`` — comma-separated allow-list, strict containment enforced.
2. **Docker local mode** (``/.dockerenv`` present or the ``/projects`` mount exists) — the
   ``/projects`` bind mount plus ``KODO_WORKSPACES_DIR`` when it exists, strict containment.
3. **Native (bare metal)** — Windows drive roots / ``~`` + ``/`` on POSIX, with no containment
   beyond the drive the user picked (same trust level as a manually typed scan path).

Strict containment rejects ``..`` traversal and symlinks whose target escapes the allowed roots with
``403 BROWSE_PATH_OUTSIDE_ROOTS``. Unreadable children and broken symlinks are skipped, never fatal.
"""

from __future__ import annotations

import os
import string
from dataclasses import dataclass, field
from pathlib import Path

from app.config import (
    DEFAULT_DOCKER_BROWSE_ROOT,
    MAX_BROWSE_ENTRIES,
    browse_roots_configured,
)
from app.services.paths import workspaces_dir

RUNTIME_DOCKER = "docker"
RUNTIME_NATIVE = "native"

# Module-level so tests can point them at temporary folders.
DOCKERENV_PATH = Path("/.dockerenv")
PROJECTS_MOUNT = Path(DEFAULT_DOCKER_BROWSE_ROOT)

# Heavy, hidden and system folders that are skipped unless `showHidden` is requested.
NOISE_DIRECTORY_NAMES = frozenset(
    {
        ".git",
        "node_modules",
        "target",
        "bin",
        "obj",
        ".venv",
        "venv",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".tox",
        "htmlcov",
        ".idea",
        ".vscode",
        "$RECYCLE.BIN",
        "System Volume Information",
    }
)

STACK_MARKER_FILES: dict[str, frozenset[str]] = {
    "java": frozenset({"pom.xml", "build.gradle", "build.gradle.kts"}),
    "nodejs": frozenset({"package.json"}),
    "python": frozenset({"pyproject.toml", "requirements.txt", "setup.py"}),
}
STACK_MARKER_SUFFIXES: dict[str, tuple[str, ...]] = {"csharp": (".csproj", ".sln")}
STACK_ORDER: tuple[str, ...] = ("java", "csharp", "nodejs", "python")

_NOISE_LOWER = frozenset(name.lower() for name in NOISE_DIRECTORY_NAMES)


class BrowseError(RuntimeError):
    """A user-actionable browse failure (HTTP status + structured code)."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


@dataclass(frozen=True)
class BrowseRoot:
    label: str
    path: Path


@dataclass(frozen=True)
class BrowseEntry:
    name: str
    path: Path
    stacks: list[str] = field(default_factory=list)
    is_git_repo: bool = False
    has_subdirectories: bool = False


@dataclass(frozen=True)
class BrowseMarkers:
    stacks: list[str] = field(default_factory=list)
    is_git_repo: bool = False


@dataclass(frozen=True)
class BrowsePayload:
    runtime: str
    current_path: Path
    parent_path: Path | None
    roots: list[BrowseRoot]
    markers: BrowseMarkers
    entries: list[BrowseEntry]
    truncated: bool
    empty_mount_hint: bool
    hint_message: str | None


def detect_runtime() -> str:
    """``docker`` when the API runs in a container, else ``native``.

    ``Path("/projects")`` maps onto the current drive on Windows, so the mount heuristic is only
    trusted on POSIX hosts; ``/.dockerenv`` is the primary signal everywhere.
    """
    if DOCKERENV_PATH.exists():
        return RUNTIME_DOCKER
    if os.name != "nt" and PROJECTS_MOUNT.is_dir():
        return RUNTIME_DOCKER
    return RUNTIME_NATIVE


def _within(path: Path, root: Path) -> bool:
    try:
        return path == root or path.is_relative_to(root)
    except (OSError, ValueError):
        return False


def _windows_drives() -> list[Path]:
    drives: list[Path] = []
    for letter in string.ascii_uppercase:
        candidate = Path(f"{letter}:\\")
        try:
            if candidate.exists():
                drives.append(candidate)
        except OSError:
            continue
    return drives


def _resolve_dir(raw: str | Path) -> Path | None:
    try:
        candidate = Path(raw).expanduser()
        if not candidate.is_dir():
            return None
        return candidate.resolve()
    except OSError:
        return None


@dataclass(frozen=True)
class _RootContext:
    runtime: str
    roots: list[BrowseRoot]
    strict: bool


def _resolve_roots() -> _RootContext:
    runtime = detect_runtime()
    roots: list[BrowseRoot] = []
    seen: set[str] = set()

    def add(label: str, candidate: str | Path) -> None:
        resolved = _resolve_dir(candidate)
        if resolved is None:
            return
        key = str(resolved).lower() if os.name == "nt" else str(resolved)
        if key in seen:
            return
        seen.add(key)
        roots.append(BrowseRoot(label=label, path=resolved))

    configured = browse_roots_configured()
    if configured:
        for entry in configured:
            candidate = Path(entry).expanduser()
            label = f"{candidate.name or str(candidate)} ({candidate})"
            add(label, candidate)
        return _RootContext(runtime=runtime, roots=roots, strict=True)

    if runtime == RUNTIME_DOCKER:
        add(f"Projects ({PROJECTS_MOUNT.as_posix()})", PROJECTS_MOUNT)
        try:
            add(f"Workspaces ({workspaces_dir()})", workspaces_dir())
        except OSError:
            pass
        return _RootContext(runtime=runtime, roots=roots, strict=True)

    home = Path.home()
    if os.name == "nt":
        for drive in _windows_drives():
            add(f"Drive {str(drive)[:2]}", drive)
        add(f"Home ({home})", home)
    else:
        add(f"Home ({home})", home)
        add("Filesystem (/)", "/")
    return _RootContext(runtime=runtime, roots=roots, strict=False)


def _default_start(context: _RootContext) -> Path:
    if context.runtime == RUNTIME_DOCKER:
        try:
            projects = PROJECTS_MOUNT.resolve()
            for root in context.roots:
                if root.path == projects:
                    return root.path
        except OSError:
            pass
        return context.roots[0].path
    if not browse_roots_configured():
        home = Path.home()
        if any(root.path == home for root in context.roots):
            return home
    return context.roots[0].path


def _resolve_requested(raw: str, context: _RootContext) -> Path:
    try:
        candidate = Path(raw).expanduser().resolve()
    except OSError as exc:
        raise BrowseError(400, "BROWSE_PATH_INVALID", f"That folder cannot be resolved: {exc}") from exc

    if context.strict and not any(_within(candidate, root.path) for root in context.roots):
        raise BrowseError(
            403,
            "BROWSE_PATH_OUTSIDE_ROOTS",
            "This folder is outside the roots Kodo may browse. Add it to KODO_BROWSE_ROOTS "
            "(or switch KODO_MODE) and restart the API.",
        )
    if not candidate.exists():
        raise BrowseError(404, "BROWSE_PATH_NOT_FOUND", "That folder no longer exists.")
    if not candidate.is_dir():
        raise BrowseError(400, "BROWSE_NOT_A_DIRECTORY", "That path is not a directory.")
    return candidate


def _parent_of(current: Path, context: _RootContext) -> Path | None:
    parent = current.parent
    if parent == current:
        return None
    if context.strict and not any(_within(parent, root.path) for root in context.roots):
        return None
    return parent


def scan_markers(directory: Path) -> BrowseMarkers:
    """Detect stack markers in one folder using a single non-recursive listing."""
    stacks: set[str] = set()
    is_git = False
    try:
        with os.scandir(directory) as entries:
            for entry in entries:
                name = entry.name.lower()
                if name == ".git":
                    is_git = True
                for stack, markers in STACK_MARKER_FILES.items():
                    if name in markers:
                        stacks.add(stack)
                for stack, suffixes in STACK_MARKER_SUFFIXES.items():
                    if name.endswith(suffixes):
                        stacks.add(stack)
    except OSError:
        pass
    ordered = [stack for stack in STACK_ORDER if stack in stacks]
    return BrowseMarkers(stacks=ordered, is_git_repo=is_git)


def _has_real_subdirectory(directory: Path) -> bool:
    try:
        with os.scandir(directory) as entries:
            for entry in entries:
                try:
                    if entry.is_dir():
                        return True
                except OSError:
                    continue
    except OSError:
        return False
    return False


def _is_noise(name: str) -> bool:
    return name.startswith(".") or name.lower() in _NOISE_LOWER


def _list_entries(
    current: Path,
    context: _RootContext,
    show_hidden: bool,
) -> tuple[list[BrowseEntry], bool]:
    try:
        with os.scandir(current) as entries:
            candidates = [
                entry.name
                for entry in entries
                if _safe_is_dir(entry) and (show_hidden or not _is_noise(entry.name))
            ]
    except PermissionError as exc:
        raise BrowseError(
            403,
            "BROWSE_PERMISSION_DENIED",
            f"Kodo cannot read this folder: {current.name or current}.",
        ) from exc
    except OSError as exc:
        raise BrowseError(400, "BROWSE_UNREADABLE", f"This folder cannot be listed: {exc}") from exc

    candidates.sort(key=lambda name: (name.lower(), name))
    truncated = len(candidates) > MAX_BROWSE_ENTRIES
    listed: list[BrowseEntry] = []
    for name in candidates[:MAX_BROWSE_ENTRIES]:
        try:
            child = (current / name).resolve()
        except OSError:
            continue
        if context.strict and not any(_within(child, root.path) for root in context.roots):
            # A symlink pointing outside the allowed roots is never offered or followed.
            continue
        try:
            markers = scan_markers(child)
            has_subdirectories = _has_real_subdirectory(child)
        except OSError:
            continue
        listed.append(
            BrowseEntry(
                name=name,
                path=child,
                stacks=markers.stacks,
                is_git_repo=markers.is_git_repo,
                has_subdirectories=has_subdirectories,
            )
        )
    return listed, truncated


def _safe_is_dir(entry: os.DirEntry[str]) -> bool:
    try:
        return entry.is_dir()
    except OSError:
        return False


def _empty_mount_hint(context: _RootContext, current: Path) -> str | None:
    if context.runtime != RUNTIME_DOCKER:
        return None
    try:
        projects = PROJECTS_MOUNT.resolve()
    except OSError:
        return None
    if current != projects or _has_real_subdirectory(current):
        return None
    return (
        "The /projects mount is empty, so Docker has nothing to browse. Docker can only see folders "
        "that are bind-mounted into the container: set KODO_LOCAL_PROJECTS_DIR in .env to the host "
        "folder that holds your projects (for example KODO_LOCAL_PROJECTS_DIR=C:\\Projects or "
        "KODO_LOCAL_PROJECTS_DIR=~/projects), then run `docker compose up -d`. The committed "
        ".kodo-empty placeholder is mounted until you do."
    )


def browse(path: str | None = None, *, show_hidden: bool = False) -> BrowsePayload:
    """List one directory level. Raises ``BrowseError`` for actionable failures only."""
    context = _resolve_roots()
    if not context.roots:
        raise BrowseError(
            409,
            "BROWSE_NO_ROOTS",
            "No browsable root is available. Set KODO_BROWSE_ROOTS to one or more existing folders.",
        )

    current = _resolve_requested(path.strip(), context) if path and path.strip() else _default_start(context)
    markers = scan_markers(current)
    entries, truncated = _list_entries(current, context, show_hidden)
    hint = _empty_mount_hint(context, current)

    return BrowsePayload(
        runtime=context.runtime,
        current_path=current,
        parent_path=_parent_of(current, context),
        roots=context.roots,
        markers=markers,
        entries=entries,
        truncated=truncated,
        empty_mount_hint=hint is not None,
        hint_message=hint,
    )


__all__ = [    "BrowseEntry",
    "BrowseError",
    "BrowseMarkers",
    "BrowsePayload",
    "BrowseRoot",
    "MAX_BROWSE_ENTRIES",
    "NOISE_DIRECTORY_NAMES",
    "RUNTIME_DOCKER",
    "RUNTIME_NATIVE",
    "browse",
    "detect_runtime",
    "scan_markers",
]
