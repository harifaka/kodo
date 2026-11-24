"""In-memory workspace staging for the ephemeral builder (Phase 9).

The builder must never see the user's real files, so the whole build input is a tar stream built
from a bounded, symlink-aware walk with the proposed patches overlaid *in memory*. Nothing here
opens a file for writing: the container receives bytes, the workspace keeps its exact mtime/bytes.
"""

from __future__ import annotations

import io
import os
import tarfile
from pathlib import Path

from app.builders.models import BuildPatchInput, StagingError
from app.config import MAX_BUILDER_SNAPSHOT_BYTES
from app.patching.paths import PatchRejected, resolve_member, resolve_new_member

# Build outputs and tool caches are never part of a snapshot: they are recreated in the container.
SKIP_DIRECTORIES = frozenset(
    {".git", "node_modules", "target", "bin", "obj", ".venv", "__pycache__"}
)


def build_workspace_tar(
    root_path: Path,
    patches: list[BuildPatchInput],
    *,
    skipped: list[str] | None = None,
) -> bytes:
    """Return a gzip-free tar of the workspace with ``patches`` overlaid in memory.

    ``root_path`` must already be resolved and contained by the caller (``enforce_workspace_access``).
    Every patch is re-validated with the same containment rules as the guarded apply, so traversal,
    absolute paths and symlinked folders are rejected before anything is staged.
    """
    root = Path(root_path)
    if not root.is_dir():
        raise StagingError(400, "PATH_REJECTED", "Workspace root is not a directory.")

    overlay: dict[str, bytes] = {}
    overlay_bytes = 0
    for patch in patches:
        relative, _ = _resolve_patch(root, patch)
        data = patch.proposed_content.encode("utf-8")
        overlay_bytes += len(data)
        if overlay_bytes > MAX_BUILDER_SNAPSHOT_BYTES:
            raise StagingError(
                413,
                "SNAPSHOT_TOO_LARGE",
                f"The proposed patches exceed the {MAX_BUILDER_SNAPSHOT_BYTES // (1024 * 1024)} MB "
                "builder snapshot limit.",
            )
        overlay[relative] = data

    staged: dict[str, bytes] = {}
    total = 0
    for target in _walk_files(root):
        relative = target.relative_to(root).as_posix()
        if relative in staged:
            continue
        if relative in overlay:
            staged[relative] = overlay[relative]
        else:
            try:
                data = target.read_bytes()
            except OSError as exc:
                if skipped is not None:
                    skipped.append(f"{relative}: unreadable ({exc.strerror or 'I/O error'})")
                continue
            staged[relative] = data
        total += len(staged[relative])
        if total > MAX_BUILDER_SNAPSHOT_BYTES:
            raise StagingError(
                413,
                "SNAPSHOT_TOO_LARGE",
                f"The staged workspace exceeds the {MAX_BUILDER_SNAPSHOT_BYTES // (1024 * 1024)} MB "
                "builder snapshot limit. Exclude generated output folders before verifying.",
            )

    for relative, data in overlay.items():
        if relative in staged:
            continue
        staged[relative] = data
        total += len(data)
        if total > MAX_BUILDER_SNAPSHOT_BYTES:
            raise StagingError(
                413,
                "SNAPSHOT_TOO_LARGE",
                f"The staged workspace exceeds the {MAX_BUILDER_SNAPSHOT_BYTES // (1024 * 1024)} MB "
                "builder snapshot limit.",
            )

    return _tar_bytes(staged)


def _resolve_patch(root: Path, patch: BuildPatchInput) -> tuple[str, Path]:
    try:
        if patch.is_new_file:
            target = resolve_new_member(root, patch.file_path)
        else:
            target = resolve_member(root, patch.file_path)
    except PatchRejected as exc:
        raise StagingError(exc.status_code, "PATH_REJECTED", str(exc)) from exc

    relative = target.relative_to(root).as_posix()
    if SKIP_DIRECTORIES.intersection(Path(relative).parts):
        raise StagingError(
            400,
            "PATH_REJECTED",
            f"{relative} lives inside a folder the builder never stages "
            f"({', '.join(sorted(SKIP_DIRECTORIES))}).",
        )
    return relative, target


def _walk_files(root: Path) -> list[Path]:
    """Deterministic walk that never follows a symlink out of ``root``."""
    files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        current = Path(dirpath)
        dirnames[:] = sorted(
            name
            for name in dirnames
            if name not in SKIP_DIRECTORIES and not (current / name).is_symlink()
        )
        for name in sorted(filenames):
            candidate = current / name
            if candidate.is_symlink():
                try:
                    candidate = candidate.resolve(strict=True)
                except OSError:
                    continue
                if not candidate.is_relative_to(root):
                    continue
            if candidate.is_file():
                files.append(candidate)
    return files


def _tar_bytes(staged: dict[str, bytes]) -> bytes:
    """Deterministic tar: sorted entries, fixed metadata, no host timestamps or owner ids."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        for relative in sorted(staged):
            data = staged[relative]
            info = tarfile.TarInfo(relative)
            info.size = len(data)
            info.mtime = 0
            info.mode = 0o644
            info.uid = 0
            info.gid = 0
            info.uname = ""
            info.gname = ""
            archive.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


__all__ = ["SKIP_DIRECTORIES", "build_workspace_tar"]
