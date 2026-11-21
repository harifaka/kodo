"""HTTP surface of the Kodo orchestrator."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from app import __version__
from app.audit import run_audit
from app.config import (
    MAX_AUDIT_NODES,
    MAX_AUDIT_RELATIONS,
    MAX_INSPECT_BYTES,
    csharp_analyzer_url,
)
from app.models.ir import AuditReport, ComponentNode, ComponentRelation, WorkspaceIR
from app.patching.csharp_patcher import patch_csharp
from app.patching.java_patcher import patch_java
from app.patching.models import (
    DryRunRequest,
    DryRunResponse,
    PatchResult,
    sha256_hex,
    summarize,
)
from app.patching.paths import PatchRejected, build_targets
from app.patching.ts_patcher import patch_script
from app.services.apply_service import (
    ApplyRejected,
    ApplyRequest,
    ApplyResponse,
    RollbackRequest,
    RollbackResponse,
    apply_patches,
    rollback,
)
from app.services.csharp_client import check_health
from app.services.git_safety import GitStatus, inspect_git_status
from app.services.workspace import WorkspaceNotFoundError, build_workspace

router = APIRouter()


class ScanRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")

    path: str = Field(..., min_length=1, description="Absolute (or ~-prefixed) path of the folder to analyze.")


class AuditRequest(BaseModel):
    """A draft Core IR to re-score. Nothing is read from or written to disk."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")

    nodes: list[ComponentNode] = Field(..., max_length=MAX_AUDIT_NODES)
    relations: list[ComponentRelation] = Field(..., max_length=MAX_AUDIT_RELATIONS)


class FileContent(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    rel_path: str
    content: str
    language: str
    size: int


class CSharpHealth(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    url: str
    reachable: bool


class HealthResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    status: str
    service: str
    version: str
    analyzers: dict[str, CSharpHealth]
    timestamp: str


_LANGUAGE_BY_SUFFIX = {
    ".java": "java",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".mts": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".cs": "csharp",
    ".json": "json",
    ".xml": "xml",
    ".xaml": "xml",
    ".csproj": "xml",
    ".pom": "xml",
    ".md": "markdown",
    ".yml": "yaml",
    ".yaml": "yaml",
    ".sql": "sql",
    ".css": "css",
    ".html": "html",
    ".py": "python",
    ".sh": "shell",
}


@router.get("/health", response_model=HealthResponse, tags=["system"])
async def health() -> HealthResponse:
    reachable = await check_health()
    return HealthResponse(
        status="ok",
        service="kodo-api-python",
        version=__version__,
        analyzers={"csharp": CSharpHealth(url=csharp_analyzer_url(), reachable=reachable)},
        timestamp=datetime.now(UTC).isoformat(),
    )


@router.post("/api/v1/scan", response_model=WorkspaceIR, tags=["analysis"])
async def scan(request: ScanRequest) -> WorkspaceIR:
    try:
        return await build_workspace(request.path)
    except WorkspaceNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/v1/audit", response_model=AuditReport, tags=["analysis"])
async def audit_preview(request: AuditRequest) -> AuditReport:
    """Re-score an edited (draft) IR so the UI can preview the impact of macro edits."""
    node_ids = {node.id for node in request.nodes}
    relations: list[ComponentRelation] = []
    seen: set[tuple[str, str, str]] = set()
    for relation in request.relations:
        key = (relation.source_id, relation.target_id, relation.type)
        # Mirror the scan pipeline: dangling and duplicate relations never reach the rules.
        if relation.source_id not in node_ids or relation.target_id not in node_ids or key in seen:
            continue
        seen.add(key)
        relations.append(relation)
    return run_audit(request.nodes, relations)


@router.post("/api/v1/dry-run", response_model=DryRunResponse, tags=["patching"])
async def dry_run(request: DryRunRequest) -> DryRunResponse:
    """Compute proposed file contents in memory. No file is created, modified or deleted."""
    try:
        targets = build_targets(request.root_path, request.operations)
    except PatchRejected as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    patches: list[PatchResult] = []
    for target in targets:
        if target.language == "java":
            outcome = patch_java(target.content, target.operations)
        elif target.language in {"typescript", "javascript"}:
            outcome = patch_script(target.content, target.operations, target.file_path)
        else:
            outcome = await patch_csharp(target.file_path, target.content, target.operations)

        patches.append(
            PatchResult(
                file_path=target.file_path,
                language=target.language,
                original_content=target.content,
                original_sha256=sha256_hex(target.raw),
                proposed_content=outcome.content,
                summary=summarize(outcome),
                warnings=outcome.warnings,
            )
        )

    return DryRunResponse(patches=patches, warnings=[])


@router.get("/api/v1/git/status", response_model=GitStatus, tags=["safety"])
def git_status(
    root: str = Query(..., description="Workspace root exactly as returned by /api/v1/scan."),
) -> GitStatus:
    """Read-only Git inspection: Kodo never runs a mutating Git command."""
    try:
        root_path = Path(root).expanduser().resolve(strict=True)
    except OSError as exc:
        raise HTTPException(status_code=400, detail="Workspace root does not exist.") from exc

    if not root_path.is_dir():
        raise HTTPException(status_code=400, detail="Workspace root is not a directory.")

    return inspect_git_status(str(root_path))


@router.post("/api/v1/apply", response_model=ApplyResponse, tags=["patching"])
def apply_to_disk(request: ApplyRequest) -> ApplyResponse:
    """Write reviewed dry-run patches to disk behind Git + SHA-256 + path-containment guards."""
    try:
        return apply_patches(request)
    except ApplyRejected as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


@router.post("/api/v1/apply/rollback", response_model=RollbackResponse, tags=["patching"])
def rollback_apply(request: RollbackRequest) -> RollbackResponse:
    """Restore the previous bytes of an apply batch (aborts if a file changed, unless forced)."""
    try:
        return rollback(request)
    except ApplyRejected as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


@router.get("/api/v1/file", response_model=FileContent, tags=["inspection"])
async def read_file(
    root: str = Query(..., description="Workspace root exactly as returned by /api/v1/scan."),
    rel_path: str = Query(..., alias="relPath", description="File path relative to the workspace root."),
) -> FileContent:
    target = _resolve_inside_root(root, rel_path)

    try:
        size = target.stat().st_size
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"File is not readable: {rel_path}") from exc

    if size > MAX_INSPECT_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File is larger than the {MAX_INSPECT_BYTES // 1_000_000} MB inspection limit.",
        )

    try:
        content = target.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"File is not readable: {rel_path}") from exc

    return FileContent(
        rel_path=rel_path.replace("\\", "/"),
        content=content,
        language=_LANGUAGE_BY_SUFFIX.get(target.suffix.lower(), "plaintext"),
        size=size,
    )


def _resolve_inside_root(root: str, rel_path: str) -> Path:
    if not rel_path or "\x00" in rel_path:
        raise HTTPException(status_code=400, detail="relPath is required.")

    try:
        root_path = Path(root).expanduser().resolve(strict=True)
    except OSError as exc:
        raise HTTPException(status_code=400, detail="Workspace root does not exist.") from exc

    if not root_path.is_dir():
        raise HTTPException(status_code=400, detail="Workspace root is not a directory.")

    try:
        target = (root_path / rel_path).resolve(strict=True)
    except OSError as exc:
        raise HTTPException(status_code=404, detail=f"File not found: {rel_path}") from exc

    if not target.is_relative_to(root_path):
        raise HTTPException(status_code=400, detail="Path traversal outside the workspace root is not allowed.")

    if not target.is_file():
        raise HTTPException(status_code=400, detail=f"Not a file: {rel_path}")

    return target
