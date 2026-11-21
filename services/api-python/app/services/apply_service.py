"""Guarded apply-to-disk and rollback.

Every write goes through this module. It refuses to touch anything outside ``rootPath``, refuses
to overwrite files that changed since the dry-run (SHA-256 optimistic concurrency), inspects the
Git working tree before writing, writes atomically through a sibling temp file + ``os.replace``,
and keeps a bounded in-memory rollback snapshot of the last few applies.

Phase 4 adds create-only patches (``isNewFile: true``): a new file may never overwrite an existing
one (409 ``FILE_EXISTS`` aborts the whole batch), missing parent folders are created inside the
root, and rollback deletes the created files plus the empty folders the batch introduced.
"""

from __future__ import annotations

import os
import stat
import tempfile
import threading
import uuid
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

from app.config import MAX_APPLY_FILES, MAX_PATCH_BYTES
from app.patching.models import sha256_hex
from app.patching.paths import (
    PatchRejected,
    resolve_member,
    resolve_new_member,
    resolve_root,
)
from app.services.git_safety import GitStatus, inspect_git_status

MAX_ROLLBACK_BATCHES = 10


class ApplyModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


class ApplyPatch(ApplyModel):
    file_path: str = Field(..., min_length=1)
    expected_sha256: str | None = Field(default=None, pattern="^[0-9a-fA-F]{64}$")
    proposed_content: str
    # Create-only: the target must not exist and the batch is rejected with FILE_EXISTS otherwise.
    is_new_file: bool = False

    @model_validator(mode="after")
    def _sha_contract(self) -> ApplyPatch:
        if not self.is_new_file and not self.expected_sha256:
            raise ValueError("expectedSha256 is required unless isNewFile is true.")
        return self


class ApplyRequest(ApplyModel):
    root_path: str = Field(..., min_length=1)
    patches: list[ApplyPatch] = Field(..., min_length=1, max_length=MAX_APPLY_FILES)
    allow_dirty: bool = False
    allow_non_git: bool = False


class ApplyResponse(ApplyModel):
    apply_id: str
    applied_files: list[str] = Field(default_factory=list)
    created_files: list[str] = Field(default_factory=list)
    git_status: GitStatus
    warnings: list[str] = Field(default_factory=list)


class RollbackRequest(ApplyModel):
    apply_id: str = Field(..., min_length=1)
    force: bool = False


class RollbackResponse(ApplyModel):
    restored_files: list[str] = Field(default_factory=list)
    deleted_files: list[str] = Field(default_factory=list)


class ApplyRejected(Exception):
    """Structured apply/rollback rejection surfaced as a JSON ``detail`` payload."""

    def __init__(self, status_code: int, code: str, message: str, **extra: object) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.extra = {key: value for key, value in extra.items() if value is not None}

    def payload(self) -> dict[str, object]:
        return {
            "code": self.code,
            "message": str(self),
            **{to_camel(key): value for key, value in self.extra.items()},
        }


@dataclass(frozen=True)
class _Prepared:
    display: str
    path: Path
    previous_content: str | None
    current_bytes: bytes | None
    proposed_bytes: bytes
    expected_sha256: str | None
    is_new_file: bool


@dataclass(frozen=True)
class _SnapshotFile:
    file_path: str
    previous_content: str | None
    written_sha256: str
    is_new_file: bool


@dataclass(frozen=True)
class _RollbackBatch:
    apply_id: str
    root_path: str
    created_at: datetime
    files: tuple[_SnapshotFile, ...]
    created_dirs: tuple[str, ...]


@dataclass(frozen=True)
class _RollbackAction:
    path: Path
    display: str
    payload: bytes | None
    is_new_file: bool


_batches: deque[_RollbackBatch] = deque(maxlen=MAX_ROLLBACK_BATCHES)
_lock = threading.Lock()


def apply_patches(request: ApplyRequest) -> ApplyResponse:
    """Validate the whole batch, then write every file. Nothing is written on any rejection."""
    with _lock:
        root = _root(request.root_path)
        prepared, warnings = _preflight(root, request)

        apply_id = uuid.uuid4().hex
        written: list[_SnapshotFile] = []
        restore_plan: list[tuple[Path, bytes | None]] = []
        created_dirs: list[str] = []
        applied: list[str] = []
        created: list[str] = []

        try:
            for item in prepared:
                if item.is_new_file:
                    for directory in _ensure_parent(item.path, root):
                        relative = directory.relative_to(root).as_posix()
                        if relative not in created_dirs:
                            created_dirs.append(relative)
                _atomic_write(item.path, item.proposed_bytes)
                written.append(
                    _SnapshotFile(
                        file_path=item.display,
                        previous_content=item.previous_content,
                        written_sha256=sha256_hex(item.proposed_bytes),
                        is_new_file=item.is_new_file,
                    )
                )
                restore_plan.append(
                    (
                        item.path,
                        None
                        if item.previous_content is None
                        else item.previous_content.encode("utf-8"),
                    )
                )
                applied.append(item.display)
                if item.is_new_file:
                    created.append(item.display)
        except OSError as exc:
            _restore_all(restore_plan, created_dirs, root)
            raise ApplyRejected(
                500,
                "WRITE_FAILED",
                f"Writing failed ({exc}); every file from this batch was restored.",
            ) from exc

        _batches.append(
            _RollbackBatch(
                apply_id=apply_id,
                root_path=str(root),
                created_at=datetime.now(UTC),
                files=tuple(written),
                created_dirs=tuple(created_dirs),
            )
        )

        return ApplyResponse(
            apply_id=apply_id,
            applied_files=applied,
            created_files=created,
            git_status=inspect_git_status(str(root)),
            warnings=warnings,
        )


def rollback(request: RollbackRequest) -> RollbackResponse:
    """Undo a batch: restore overwritten bytes and delete created files (``force`` overrides drift)."""
    with _lock:
        batch = next((item for item in reversed(_batches) if item.apply_id == request.apply_id), None)
        if batch is None:
            raise ApplyRejected(
                404,
                "UNKNOWN_APPLY",
                "No rollback snapshot exists for this applyId. Kodo keeps only the last "
                f"{MAX_ROLLBACK_BATCHES} applies (server memory, lost on restart).",
            )

        root = _root(batch.root_path)
        plans: list[_RollbackAction] = []
        conflicts: list[str] = []

        for item in batch.files:
            path = _existing_path(root, item.file_path)

            if item.is_new_file:
                if path is None:
                    if not request.force:
                        conflicts.append(item.file_path)
                    continue
                if not _matches(path, item.written_sha256, request.force):
                    conflicts.append(item.file_path)
                    continue
                plans.append(_RollbackAction(path, item.file_path, None, True))
                continue

            payload = (item.previous_content or "").encode("utf-8")
            if path is None:
                if not request.force:
                    conflicts.append(item.file_path)
                    continue
                plans.append(
                    _RollbackAction(_recreate_path(root, item.file_path), item.file_path, payload, False)
                )
                continue

            if not _matches(path, item.written_sha256, request.force):
                conflicts.append(item.file_path)
                continue

            plans.append(_RollbackAction(path, item.file_path, payload, False))

        if conflicts:
            raise ApplyRejected(
                409,
                "STALE_FILE",
                "File(s) changed on disk after the apply, so the rollback was aborted and nothing was "
                "written. Re-scan the workspace or force the rollback.",
                paths=conflicts,
            )

        restored: list[str] = []
        deleted: list[str] = []
        try:
            for action in plans:
                if action.is_new_file:
                    action.path.unlink()
                    deleted.append(action.display)
                else:
                    _atomic_write(action.path, action.payload or b"")
                    restored.append(action.display)
        except OSError as exc:
            raise ApplyRejected(500, "WRITE_FAILED", f"Rollback failed while writing: {exc}") from exc

        _prune_directories(root, batch.created_dirs)
        _batches.remove(batch)
        return RollbackResponse(restored_files=restored, deleted_files=deleted)


def _matches(path: Path, written_sha256: str, force: bool) -> bool:
    if force:
        return True
    try:
        return sha256_hex(path.read_bytes()) == written_sha256
    except OSError:
        return False


def _preflight(root: Path, request: ApplyRequest) -> tuple[list[_Prepared], list[str]]:
    prepared: list[_Prepared] = []
    seen: set[str] = set()
    existing: list[str] = []
    limit_mb = MAX_PATCH_BYTES // 1_000_000

    for patch in request.patches:
        if patch.is_new_file:
            try:
                path = resolve_new_member(root, patch.file_path)
            except PatchRejected as exc:
                raise ApplyRejected(exc.status_code, "PATH_REJECTED", str(exc)) from exc
            display = path.relative_to(root).as_posix()
            if display in seen:
                raise ApplyRejected(400, "DUPLICATE_TARGET", f"{display} appears more than once in the batch.")
            seen.add(display)
            if path.exists() or path.is_symlink():
                existing.append(display)

            proposed_bytes = patch.proposed_content.encode("utf-8")
            if len(proposed_bytes) > MAX_PATCH_BYTES:
                raise ApplyRejected(
                    413,
                    "FILE_TOO_LARGE",
                    f"Proposed content for {display} is larger than the {limit_mb} MB apply limit.",
                )
            prepared.append(
                _Prepared(
                    display=display,
                    path=path,
                    previous_content=None,
                    current_bytes=None,
                    proposed_bytes=proposed_bytes,
                    expected_sha256=None,
                    is_new_file=True,
                )
            )
            continue

        try:
            path = resolve_member(root, patch.file_path)
        except PatchRejected as exc:
            raise ApplyRejected(exc.status_code, "PATH_REJECTED", str(exc)) from exc

        display = path.relative_to(root).as_posix()
        if display in seen:
            raise ApplyRejected(400, "DUPLICATE_TARGET", f"{display} appears more than once in the batch.")
        seen.add(display)

        try:
            current_bytes = path.read_bytes()
        except OSError as exc:
            raise ApplyRejected(400, "NOT_READABLE", f"File is not readable: {display}") from exc

        if len(current_bytes) > MAX_PATCH_BYTES:
            raise ApplyRejected(
                413, "FILE_TOO_LARGE", f"{display} is larger than the {limit_mb} MB apply limit."
            )

        try:
            previous_content = current_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ApplyRejected(
                400,
                "NOT_UTF8",
                f"{display} is not valid UTF-8; Kodo only applies patches to UTF-8 sources.",
            ) from exc

        proposed_bytes = patch.proposed_content.encode("utf-8")
        if len(proposed_bytes) > MAX_PATCH_BYTES:
            raise ApplyRejected(
                413,
                "FILE_TOO_LARGE",
                f"Proposed content for {display} is larger than the {limit_mb} MB apply limit.",
            )

        prepared.append(
            _Prepared(
                display=display,
                path=path,
                previous_content=previous_content,
                current_bytes=current_bytes,
                proposed_bytes=proposed_bytes,
                expected_sha256=(patch.expected_sha256 or "").lower(),
                is_new_file=False,
            )
        )

    # Create-only scaffolding must fail the whole batch rather than silently overwrite a file.
    if existing:
        raise ApplyRejected(
            409,
            "FILE_EXISTS",
            "Kodo never overwrites files while scaffolding. Remove or rename the existing file(s), "
            "or delete them first, then re-run the dry-run.",
            paths=sorted(existing),
        )

    git_status = inspect_git_status(str(root))
    warnings = [git_status.warning] if git_status.warning else []

    if git_status.is_git_repo and git_status.is_dirty and not request.allow_dirty:
        raise ApplyRejected(
            409,
            "GIT_DIRTY",
            "The Git working tree has "
            f"{len(git_status.dirty_files)} uncommitted change(s). Commit or stash them, then retry — "
            "or confirm the override to apply anyway.",
            dirty_files=git_status.dirty_files,
        )

    if not git_status.is_git_repo and not request.allow_non_git:
        raise ApplyRejected(
            409,
            "NOT_A_GIT_REPO",
            "The workspace is not a Git repository, so Git cannot revert these changes. "
            "Confirm the override to apply anyway (Kodo's rollback snapshot is the only undo).",
            warning=git_status.warning,
        )

    stale = [
        item.display
        for item in prepared
        if item.current_bytes is not None and sha256_hex(item.current_bytes) != item.expected_sha256
    ]
    if stale:
        raise ApplyRejected(
            409,
            "STALE_FILE",
            "File(s) changed on disk since the dry-run, so the whole batch was aborted and nothing was "
            "written. Re-run the dry-run and review the diff again.",
            paths=stale,
        )

    return prepared, warnings


def _root(raw_root: str) -> Path:
    try:
        return resolve_root(raw_root)
    except PatchRejected as exc:
        raise ApplyRejected(exc.status_code, "PATH_REJECTED", str(exc)) from exc


def _existing_path(root: Path, rel_path: str) -> Path | None:
    try:
        return resolve_member(root, rel_path)
    except PatchRejected as exc:
        if exc.status_code == 404:
            return None
        raise ApplyRejected(exc.status_code, "PATH_REJECTED", str(exc)) from exc


def _recreate_path(root: Path, rel_path: str) -> Path:
    """Resolve a path a forced rollback may recreate, still strictly inside ``root``."""
    normalized = PurePosixPath(rel_path.replace("\\", "/"))
    if normalized.is_absolute() or any(part == ".." for part in normalized.parts):
        raise ApplyRejected(
            400, "PATH_REJECTED", f"Path traversal outside the workspace root: {rel_path}"
        )

    try:
        parent = (root / normalized.parent).resolve(strict=True)
    except OSError as exc:
        raise ApplyRejected(
            400, "PATH_REJECTED", f"Cannot restore {rel_path}: parent folder is gone."
        ) from exc

    if not parent.is_relative_to(root) or not parent.is_dir():
        raise ApplyRejected(
            400, "PATH_REJECTED", f"Cannot restore {rel_path} outside the workspace root."
        )
    return parent / normalized.name


def _ensure_parent(target: Path, root: Path) -> list[Path]:
    """Create missing parent folders one level at a time, returning the ones created (shallow first)."""
    missing: list[Path] = []
    current = target.parent
    while not current.exists():
        missing.append(current)
        if current.parent == current:
            break
        current = current.parent

    created: list[Path] = []
    for directory in reversed(missing):
        try:
            directory.mkdir()
        except FileExistsError:
            continue
        created.append(directory)

    resolved = target.parent.resolve(strict=True)
    if not resolved.is_relative_to(root):
        raise OSError(f"Refusing to create {target.name} outside the workspace root")
    return created


def _prune_directories(root: Path, relative_dirs: tuple[str, ...]) -> None:
    """Remove folders this batch created, deepest first, only when they are empty. Never the root."""
    for relative in sorted(relative_dirs, key=lambda value: len(Path(value).parts), reverse=True):
        directory = root / relative
        if directory == root or not directory.is_dir():
            continue
        try:
            if not any(directory.iterdir()):
                directory.rmdir()
        except OSError:
            continue


def _atomic_write(target: Path, payload: bytes) -> None:
    """Write via a sibling temp file + ``os.replace`` so readers never see a partial file."""
    try:
        mode = stat.S_IMODE(target.stat().st_mode)
    except OSError:
        mode = None

    handle_fd, temp_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".kodo.tmp",
        dir=str(target.parent),
    )
    try:
        with os.fdopen(handle_fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if mode is not None:
            try:
                os.chmod(temp_name, mode)
            except OSError:
                pass
        os.replace(temp_name, target)
    except BaseException:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def _restore_all(
    plan: list[tuple[Path, bytes | None]],
    created_dirs: list[str],
    root: Path,
) -> None:
    for path, payload in reversed(plan):
        try:
            if payload is None:
                path.unlink(missing_ok=True)
            else:
                _atomic_write(path, payload)
        except OSError:
            continue
    _prune_directories(root, tuple(created_dirs))
