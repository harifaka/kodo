"""HTTP surface of the Kodo orchestrator."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from app import __version__
from app.audit import run_audit
from app.auth.dependencies import CurrentUser
from app.config import (
    MAX_AUDIT_NODES,
    MAX_AUDIT_RELATIONS,
    MAX_INSPECT_BYTES,
    csharp_analyzer_url,
)
from app.db import repository
from app.generators import GeneratorError
from app.models.blueprint import BLUEPRINT_FILE_NAME, Blueprint, load_blueprint
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
from app.patching.python_patcher import patch_python
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
from app.services.mermaid import generate_class_diagram
from app.services.paths import enforce_workspace_access
from app.services.scaffold_service import build_scaffold_plan
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


class MermaidRequest(BaseModel):
    """A filtered Core IR subset to re-render as a Mermaid classDiagram. No disk access."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")

    nodes: list[ComponentNode] = Field(..., max_length=MAX_AUDIT_NODES)
    relations: list[ComponentRelation] = Field(..., max_length=MAX_AUDIT_RELATIONS)


class MermaidResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    diagram: str
    node_count: int
    relation_count: int


class FileContent(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    rel_path: str
    content: str
    language: str
    size: int


class BlueprintResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    exists: bool
    blueprint: Blueprint | None = None
    warnings: list[str] = Field(default_factory=list)


class ScaffoldRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")

    root_path: str = Field(..., min_length=1)
    blueprint: Blueprint
    include_project_skeleton: bool = False
    save_blueprint: bool = False


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
async def scan(
    request: ScanRequest,
    user: CurrentUser,
) -> WorkspaceIR:
    root = enforce_workspace_access(request.path, user)
    try:
        workspace = await build_workspace(str(root))
    except WorkspaceNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    _remember_scan(user.id, workspace)
    return workspace


def _remember_scan(user_id: str, workspace: WorkspaceIR) -> None:
    try:
        repository.record_workspace_scan(
            user_id,
            name=workspace.name,
            local_path=workspace.root_path,
            health_score=workspace.audit.score,
        )
    except Exception:
        # Workspace metadata is a convenience; a failed write must not fail the scan.
        pass


def _touch_workspace(user_id: str, root: Path) -> None:
    """Record read/apply/export activity so the SaaS TTL cleanup keeps active workspaces."""
    try:
        repository.touch_workspace(user_id, str(root))
    except Exception:
        pass


@router.post("/api/v1/audit", response_model=AuditReport, tags=["analysis"])
async def audit_preview(request: AuditRequest) -> AuditReport:
    """Re-score an edited (draft) IR so the UI can preview the impact of macro edits."""
    return run_audit(request.nodes, _live_relations(request.nodes, request.relations))


@router.post("/api/v1/mermaid", response_model=MermaidResponse, tags=["analysis"])
async def mermaid_preview(request: MermaidRequest) -> MermaidResponse:
    """Re-render the classDiagram for a filtered / 1-hop Core IR subset (Phase 11 ergonomics)."""
    relations = _live_relations(request.nodes, request.relations)
    return MermaidResponse(
        diagram=generate_class_diagram(request.nodes, relations),
        node_count=len(request.nodes),
        relation_count=len(relations),
    )


def _live_relations(
    nodes: list[ComponentNode],
    relations: list[ComponentRelation],
) -> list[ComponentRelation]:
    """Drop dangling and duplicate relations exactly like the scan pipeline does."""
    node_ids = {node.id for node in nodes}
    live: list[ComponentRelation] = []
    seen: set[tuple[str, str, str]] = set()
    for relation in relations:
        key = (relation.source_id, relation.target_id, relation.type)
        if relation.source_id not in node_ids or relation.target_id not in node_ids or key in seen:
            continue
        seen.add(key)
        live.append(relation)
    return live


@router.post("/api/v1/dry-run", response_model=DryRunResponse, tags=["patching"])
async def dry_run(
    request: DryRunRequest,
    user: CurrentUser,
) -> DryRunResponse:
    """Compute proposed file contents in memory. No file is created, modified or deleted."""
    try:
        root = enforce_workspace_access(request.root_path, user)
        targets = build_targets(str(root), request.operations)
    except PatchRejected as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    patches: list[PatchResult] = []
    for target in targets:
        if target.language == "java":
            outcome = patch_java(target.content, target.operations)
        elif target.language in {"typescript", "javascript"}:
            outcome = patch_script(target.content, target.operations, target.file_path)
        elif target.language == "python":
            outcome = patch_python(target.content, target.operations)
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


@router.get("/api/v1/blueprint", response_model=BlueprintResponse, tags=["builder"])
def get_blueprint(
    user: CurrentUser,
    root: str = Query(..., description="Workspace root exactly as returned by /api/v1/scan."),
) -> BlueprintResponse:
    """Load ``kodo.blueprint.json`` from the workspace root, if present."""
    root_path = enforce_workspace_access(root, user)
    exists, blueprint, warnings = load_blueprint(root_path)
    if blueprint is not None:
        _persist_blueprint(user.id, root_path, blueprint)
    return BlueprintResponse(exists=exists, blueprint=blueprint, warnings=warnings)


def _persist_blueprint(user_id: str, root: Path, blueprint: Blueprint) -> None:
    try:
        repository.save_blueprint(
            user_id,
            workspace_path=str(root),
            name=blueprint.project_name,
            stack=str(blueprint.stack),
            blueprint_json=blueprint.render(),
        )
    except Exception:
        # Saved blueprints are a convenience index; never fail the blueprint read/apply.
        pass


@router.post("/api/v1/scaffold/dry-run", response_model=DryRunResponse, tags=["builder"])
def scaffold_dry_run(
    request: ScaffoldRequest,
    user: CurrentUser,
) -> DryRunResponse:
    """Render a blueprint into a reviewable patch plan. Nothing is written to disk."""
    root = enforce_workspace_access(request.root_path, user)
    try:
        return build_scaffold_plan(
            str(root),
            request.blueprint,
            include_project_skeleton=request.include_project_skeleton,
            save_blueprint=request.save_blueprint,
        )
    except GeneratorError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "GENERATOR_ERROR", "message": str(exc)},
        ) from exc
    except PatchRejected as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": "PATH_REJECTED", "message": str(exc)},
        ) from exc


@router.get("/api/v1/git/status", response_model=GitStatus, tags=["safety"])
def git_status(
    user: CurrentUser,
    root: str = Query(..., description="Workspace root exactly as returned by /api/v1/scan."),
) -> GitStatus:
    """Read-only Git inspection: Kodo never runs a mutating Git command."""
    root_path = enforce_workspace_access(root, user)
    return inspect_git_status(str(root_path))


@router.post("/api/v1/apply", response_model=ApplyResponse, tags=["patching"])
def apply_to_disk(
    request: ApplyRequest,
    user: CurrentUser,
) -> ApplyResponse:
    """Write reviewed dry-run patches to disk behind Git + SHA-256 + path-containment guards."""
    root = enforce_workspace_access(request.root_path, user)
    try:
        response = apply_patches(request, user_id=user.id)
    except ApplyRejected as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc

    _touch_workspace(user.id, root)

    for patch in request.patches:
        if patch.file_path.replace("\\", "/").endswith(BLUEPRINT_FILE_NAME):
            blueprint = _parse_blueprint(patch.proposed_content)
            if blueprint is not None:
                _persist_blueprint(user.id, root, blueprint)
    return response


def _parse_blueprint(content: str) -> Blueprint | None:
    try:
        return Blueprint.model_validate_json(content)
    except ValueError:
        return None


@router.post("/api/v1/apply/rollback", response_model=RollbackResponse, tags=["patching"])
def rollback_apply(
    request: RollbackRequest,
    user: CurrentUser,
) -> RollbackResponse:
    """Restore the previous bytes of an apply batch (aborts if a file changed, unless forced)."""
    try:
        return rollback(request, user_id=user.id)
    except ApplyRejected as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


@router.get("/api/v1/file", response_model=FileContent, tags=["inspection"])
async def read_file(
    user: CurrentUser,
    root: str = Query(..., description="Workspace root exactly as returned by /api/v1/scan."),
    rel_path: str = Query(..., alias="relPath", description="File path relative to the workspace root."),
) -> FileContent:
    root_path = enforce_workspace_access(root, user)
    target = _resolve_inside_root(str(root_path), rel_path)
    _touch_workspace(user.id, root_path)

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
