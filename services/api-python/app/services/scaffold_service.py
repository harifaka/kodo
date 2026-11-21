"""Scaffold dry-run: render a blueprint into a standard ``DryRunResponse``.

The generator output never reaches disk from here. Each generated file becomes a patch item with
``isNewFile: true`` (create-only) except ``kodo.blueprint.json``, which may be updated through the
normal SHA-256 overwrite path when the blueprint is saved again.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath

from app.generators import GeneratedFile, generate_files, language_for_path
from app.models.blueprint import BLUEPRINT_FILE_NAME, Blueprint
from app.patching.models import DryRunResponse, PatchResult, sha256_hex
from app.patching.paths import PatchRejected, resolve_root


def build_scaffold_plan(
    root_path: str,
    blueprint: Blueprint,
    *,
    include_project_skeleton: bool,
    save_blueprint: bool,
) -> DryRunResponse:
    """Render the blueprint and describe every write as a reviewable patch. Nothing is written."""
    root = resolve_root(root_path)
    files = generate_files(blueprint, include_project_skeleton=include_project_skeleton)

    if save_blueprint:
        files = [*files, _blueprint_file(blueprint)]

    patches: list[PatchResult] = []
    conflicts: list[str] = []

    for generated in files:
        patch = _patch_for(root, generated)
        if patch.conflict:
            conflicts.append(generated.file_path)
        patches.append(patch)

    warnings: list[str] = []
    if conflicts:
        warnings.append(
            f"{len(conflicts)} generated file(s) already exist on disk. Kodo never overwrites files "
            "while scaffolding, so the apply will be rejected with FILE_EXISTS until they are removed "
            "or renamed."
        )

    return DryRunResponse(patches=patches, warnings=warnings)


def _blueprint_file(blueprint: Blueprint) -> GeneratedFile:
    return GeneratedFile(
        file_path=BLUEPRINT_FILE_NAME,
        content=blueprint.render(),
        summary="Versioned kodo.blueprint.json for review alongside the generated code",
    )


def _patch_for(root: Path, generated: GeneratedFile) -> PatchResult:
    relative = _safe_relative(generated.file_path)
    target = root.joinpath(*PurePosixPath(relative).parts)
    language = language_for_path(relative)

    if relative == BLUEPRINT_FILE_NAME and target.is_file():
        try:
            raw = target.read_bytes()
        except OSError as exc:
            raise PatchRejected(400, f"{relative} is not readable: {exc}") from exc
        return PatchResult(
            file_path=relative,
            language=language,
            original_content=raw.decode("utf-8", errors="replace"),
            original_sha256=sha256_hex(raw),
            proposed_content=generated.content,
            summary="Update kodo.blueprint.json (SHA-256 verified overwrite)",
            warnings=["kodo.blueprint.json already exists; the apply updates it after the SHA-256 check."],
            is_new_file=False,
        )

    if target.exists() or target.is_symlink():
        return PatchResult(
            file_path=relative,
            language=language,
            original_content="",
            original_sha256=None,
            proposed_content=generated.content,
            summary=generated.summary,
            warnings=[f"{relative} already exists on disk; this create-only patch will be rejected."],
            is_new_file=True,
            conflict=True,
        )

    return PatchResult(
        file_path=relative,
        language=language,
        original_content="",
        original_sha256=None,
        proposed_content=generated.content,
        summary=generated.summary,
        warnings=[],
        is_new_file=True,
        conflict=False,
    )


def _safe_relative(file_path: str) -> str:
    normalized = file_path.replace("\\", "/")
    candidate = PurePosixPath(normalized)
    if (
        not normalized
        or candidate.is_absolute()
        or (len(normalized) > 1 and normalized[1] == ":")
        or any(part == ".." for part in candidate.parts)
    ):
        raise PatchRejected(400, f"Generator produced an unsafe path: {file_path!r}")
    return candidate.as_posix()


__all__ = ["build_scaffold_plan"]
