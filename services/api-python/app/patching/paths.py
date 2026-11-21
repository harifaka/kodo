"""Strict path containment and in-memory file reads for the dry-run endpoint."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from app.config import MAX_PATCH_BYTES
from app.patching.models import PatchOperation

LANGUAGE_BY_SUFFIX = {
    ".java": "java",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".mts": "typescript",
    ".cts": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".cs": "csharp",
}


class PatchRejected(ValueError):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class PatchTarget:
    file_path: str
    absolute_path: Path
    language: str
    content: str
    raw: bytes
    operations: list[PatchOperation]


def build_targets(root_path: str, operations: list[PatchOperation]) -> list[PatchTarget]:
    root = resolve_root(root_path)
    grouped: dict[Path, list[PatchOperation]] = {}
    display: dict[Path, str] = {}

    for operation in operations:
        target = resolve_member(root, operation.file_path)
        if target not in grouped:
            grouped[target] = []
            display[target] = target.relative_to(root).as_posix()
        grouped[target].append(operation)

    targets: list[PatchTarget] = []
    for target, ops in grouped.items():
        suffix = target.suffix.lower()
        language = LANGUAGE_BY_SUFFIX.get(suffix)
        if language is None:
            raise PatchRejected(
                400,
                f"Unsupported file type for patching: {display[target]} (expected .java, .ts/.tsx, .js/.jsx or .cs).",
            )

        try:
            raw = target.read_bytes()
        except OSError as exc:
            raise PatchRejected(400, f"File is not readable: {display[target]}") from exc

        if len(raw) > MAX_PATCH_BYTES:
            raise PatchRejected(
                413,
                f"{display[target]} is larger than the {MAX_PATCH_BYTES // 1_000_000} MB dry-run limit.",
            )

        targets.append(
            PatchTarget(
                file_path=display[target],
                absolute_path=target,
                language=language,
                content=raw.decode("utf-8", errors="replace"),
                raw=raw,
                operations=ops,
            )
        )

    return targets


def resolve_root(raw_root: str) -> Path:
    try:
        root = Path(raw_root).expanduser().resolve(strict=True)
    except OSError as exc:
        raise PatchRejected(400, "Workspace root does not exist.") from exc
    if not root.is_dir():
        raise PatchRejected(400, "Workspace root is not a directory.")
    return root


def resolve_member(root: Path, raw_path: str) -> Path:
    normalized = _validate_relative(raw_path)

    try:
        target = (root / normalized).resolve(strict=True)
    except OSError as exc:
        raise PatchRejected(404, f"File not found: {raw_path}") from exc

    if not target.is_relative_to(root):
        raise PatchRejected(400, "Path traversal outside the workspace root is not allowed.")
    if not target.is_file():
        raise PatchRejected(400, f"Not a file: {raw_path}")
    return target


def resolve_new_member(root: Path, raw_path: str) -> Path:
    """Resolve a path Kodo intends to create.

    The file itself must not exist yet, but its parents may. Every surviving ancestor is resolved
    and must stay inside ``root``, so ``..``, absolute paths and symlinked folders are rejected
    before a single byte is written.
    """
    normalized = _validate_relative(raw_path)
    parts = normalized.parts

    ancestor = root
    index = 0
    while index < len(parts) - 1:
        candidate = ancestor / parts[index]
        if not candidate.exists():
            break
        if candidate.is_symlink():
            raise PatchRejected(400, f"Refusing to create files through a symlink: {parts[index]}")
        ancestor = candidate
        index += 1

    try:
        resolved = ancestor.resolve(strict=True)
    except OSError as exc:
        raise PatchRejected(400, f"Cannot create {raw_path}: parent folder is not accessible.") from exc

    if not resolved.is_relative_to(root):
        raise PatchRejected(400, "Path traversal outside the workspace root is not allowed.")
    if not resolved.is_dir():
        raise PatchRejected(400, f"Not a directory: {normalized.parent}")

    return resolved.joinpath(*parts[index:])


def _validate_relative(raw_path: str) -> PurePosixPath:
    if not raw_path or "\x00" in raw_path:
        raise PatchRejected(400, "filePath is required for every operation.")

    normalized = raw_path.replace("\\", "/")
    # Reject absolute paths before touching the filesystem: only root-relative edits are allowed.
    if (
        normalized.startswith("/")
        or (len(normalized) > 1 and normalized[1] == ":")
        or PurePosixPath(normalized).is_absolute()
    ):
        raise PatchRejected(400, f"Absolute paths are not allowed: {raw_path}")

    path = PurePosixPath(normalized)
    if any(part == ".." for part in path.parts):
        raise PatchRejected(400, "Path traversal outside the workspace root is not allowed.")
    if not path.parts:
        raise PatchRejected(400, "filePath is required for every operation.")
    return path
