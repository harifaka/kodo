"""Bounded, path-contained source reads for the AI Copilot.

The model only ever sees files that the audit finding / target node actually points at, resolved with
the same containment rules as the dry-run (no absolute paths, no ``..``, no symlink escapes, 2 MB cap).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.config import MAX_PATCH_BYTES
from app.patching.paths import (
    LANGUAGE_BY_SUFFIX,
    PatchRejected,
    resolve_member,
    resolve_root,
)

MAX_PATCH_FILES = 3


@dataclass(frozen=True)
class SourceFile:
    file_path: str
    content: str
    raw: bytes

    @property
    def language(self) -> str:
        return LANGUAGE_BY_SUFFIX.get(Path(self.file_path).suffix.lower(), "plaintext")


def read_sources(
    root_path: str,
    rel_paths: list[str],
    *,
    limit: int = MAX_PATCH_FILES,
    skipped: list[str] | None = None,
) -> list[SourceFile]:
    """Read at most ``limit`` workspace files behind the same containment rules as the dry-run.

    Traversal and absolute paths are always fatal (HTTP 400). A missing or oversized secondary
    candidate is skipped and reported through ``skipped`` so the primary file can still be fixed.
    """
    root = resolve_root(root_path)
    sources: list[SourceFile] = []
    seen: set[str] = set()

    for rel_path in rel_paths:
        normalized = rel_path.replace("\\", "/").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)

        try:
            target = resolve_member(root, normalized)
        except PatchRejected as exc:
            if exc.status_code == 400:
                raise
            if skipped is not None:
                skipped.append(f"{normalized}: {exc}")
            continue

        try:
            raw = target.read_bytes()
        except OSError as exc:
            raise PatchRejected(400, f"File is not readable: {normalized}") from exc
        if len(raw) > MAX_PATCH_BYTES:
            if skipped is not None:
                skipped.append(
                    f"{normalized} was skipped: larger than the {MAX_PATCH_BYTES // 1_000_000} MB AI context limit."
                )
            continue

        sources.append(
            SourceFile(
                file_path=target.relative_to(root).as_posix(),
                content=raw.decode("utf-8", errors="replace"),
                raw=raw,
            )
        )
        if len(sources) >= limit:
            break

    return sources


__all__ = ["MAX_PATCH_FILES", "SourceFile", "read_sources"]
