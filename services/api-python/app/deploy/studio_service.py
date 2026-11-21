"""Deploy dry-run: render container artifacts into a standard ``DryRunResponse``.

The generator output never reaches disk from here. Existing files become SHA-256 verified overwrite
patches when ``overwriteExisting`` is set, and create-only patches (rejected with ``FILE_EXISTS`` by
the apply pre-flight) otherwise.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath

from app.config import MAX_PATCH_BYTES
from app.deploy.errors import DeployError
from app.deploy.generator import (
    detect_stack,
    generate_artifacts,
    normalize_stack,
)
from app.generators.base import GeneratedFile, language_for_path
from app.patching.models import DryRunResponse, PatchResult, sha256_hex
from app.patching.paths import resolve_root


def build_deploy_plan(
    root_path: str,
    *,
    project_name: str,
    stack: str,
    app_port: int | None,
    backing_services: list[str] | None,
    overwrite_existing: bool,
) -> DryRunResponse:
    """Generate Docker artifacts in memory and describe every write as a reviewable patch."""
    root = resolve_root(root_path)
    stack_id = resolve_stack(stack, root)
    artifacts = generate_artifacts(
        stack=stack_id,
        project_name=project_name,
        app_port=app_port,
        backing_services=backing_services,
        root=root,
    )

    patches: list[PatchResult] = []
    conflicts: list[str] = []
    for generated in artifacts.files:
        patch = _patch_for(root, generated, overwrite_existing=overwrite_existing)
        if patch.conflict:
            conflicts.append(generated.file_path)
        patches.append(patch)

    warnings = list(artifacts.warnings)
    if conflicts:
        warnings.append(
            f"{len(conflicts)} container file(s) already exist on disk. Enable 'Overwrite existing' "
            "to replace them through the SHA-256 verified overwrite path, or remove/rename them first."
        )

    return DryRunResponse(patches=patches, warnings=warnings)


def resolve_stack(raw: str, root: Path) -> str:
    """Resolve ``auto``/empty to a detected stack; unknown values are rejected with 400."""
    value = (raw or "").strip().lower()
    if value in ("", "auto"):
        detected = detect_stack(root)
        if detected is None:
            raise DeployError(
                400,
                "STACK_NOT_DETECTED",
                "Could not detect a supported stack (Spring Boot, Node.js, C#/.NET) at the workspace "
                "root. Choose the stack explicitly.",
            )
        return detected
    return normalize_stack(value)


def _patch_for(root: Path, generated: GeneratedFile, *, overwrite_existing: bool) -> PatchResult:
    relative = _safe_relative(generated.file_path)
    target = root.joinpath(*PurePosixPath(relative).parts)
    language = language_for_path(relative)

    if target.is_symlink() or target.exists():
        if target.is_dir():
            raise DeployError(400, "PATH_REJECTED", f"{relative} is a directory, not a file.")
        if not overwrite_existing:
            return PatchResult(
                file_path=relative,
                language=language,
                original_content="",
                original_sha256=None,
                proposed_content=generated.content,
                summary=generated.summary,
                warnings=[
                    f"{relative} already exists; this create-only patch will be rejected with FILE_EXISTS."
                ],
                is_new_file=True,
                conflict=True,
            )

        try:
            raw = target.read_bytes()
        except OSError as exc:
            raise DeployError(400, "NOT_READABLE", f"{relative} is not readable.") from exc
        if len(raw) > MAX_PATCH_BYTES:
            raise DeployError(
                413,
                "FILE_TOO_LARGE",
                f"{relative} is larger than the {MAX_PATCH_BYTES // 1_000_000} MB apply limit.",
            )
        return PatchResult(
            file_path=relative,
            language=language,
            original_content=raw.decode("utf-8", errors="replace"),
            original_sha256=sha256_hex(raw),
            proposed_content=generated.content,
            summary=generated.summary,
            warnings=[f"{relative} will be replaced after the SHA-256 check."],
            is_new_file=False,
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
        raise DeployError(400, "PATH_REJECTED", f"Unsafe generated path: {file_path!r}")
    return candidate.as_posix()


__all__ = ["build_deploy_plan", "resolve_stack"]
