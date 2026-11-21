"""HTTP surface of the Deploy Studio (Phase 6).

``/deploy/dry-run`` returns the standard ``DryRunResponse`` so generated Docker artifacts are
reviewed in the Monaco diff and applied through the guarded pipeline. The Docker control endpoints
shell out through :mod:`app.deploy.runner` (list args, ``shell=False``, timeouts, root containment).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from app.deploy.errors import DeployError
from app.deploy.runner import (
    DEFAULT_LOG_TAIL,
    MAX_LOG_TAIL,
    ComposeLogs,
    ComposeResult,
    DockerStatus,
    compose_down,
    compose_logs,
    compose_up,
    docker_status,
)
from app.deploy.studio_service import build_deploy_plan
from app.patching.models import DryRunResponse
from app.patching.paths import PatchRejected
from app.services.audit_log import (
    DEFAULT_AUDIT_LIMIT,
    MAX_AUDIT_ENTRIES,
    AuditEntry,
    read_events,
)

router = APIRouter()


class DeployModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


class DeployDryRunRequest(DeployModel):
    root_path: str = Field(..., min_length=1)
    project_name: str = Field(..., min_length=1, max_length=80)
    stack: str = Field(default="auto", max_length=40)
    app_port: int | None = Field(default=None, ge=1, le=65535)
    backing_services: list[str] = Field(default_factory=list, max_length=3)
    overwrite_existing: bool = False


class DockerUpRequest(DeployModel):
    root_path: str = Field(..., min_length=1)
    build: bool = False


class DockerDownRequest(DeployModel):
    root_path: str = Field(..., min_length=1)
    remove_volumes: bool = False


class AuditLogResponse(DeployModel):
    entries: list[AuditEntry] = Field(default_factory=list)


@router.post("/api/v1/deploy/dry-run", response_model=DryRunResponse, tags=["deploy"])
def deploy_dry_run(request: DeployDryRunRequest) -> DryRunResponse:
    """Generate Dockerfile/compose/.env.example in memory for review. Nothing is written."""
    try:
        return build_deploy_plan(
            request.root_path,
            project_name=request.project_name,
            stack=request.stack,
            app_port=request.app_port,
            backing_services=list(request.backing_services),
            overwrite_existing=request.overwrite_existing,
        )
    except DeployError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc
    except PatchRejected as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": "PATH_REJECTED", "message": str(exc)},
        ) from exc


@router.get("/api/v1/deploy/docker/status", response_model=DockerStatus, tags=["deploy"])
def docker_status_route(
    root: str = Query(..., description="Workspace root exactly as returned by /api/v1/scan."),
) -> DockerStatus:
    """Check the Docker CLI/daemon, the compose file and the parsed container table."""
    try:
        return docker_status(root)
    except DeployError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


@router.post("/api/v1/deploy/docker/up", response_model=ComposeResult, tags=["deploy"])
def docker_up(request: DockerUpRequest) -> ComposeResult:
    """Run ``docker compose up -d [--build]`` inside the workspace root."""
    try:
        return compose_up(request.root_path, build=request.build)
    except DeployError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


@router.post("/api/v1/deploy/docker/down", response_model=ComposeResult, tags=["deploy"])
def docker_down(request: DockerDownRequest) -> ComposeResult:
    """Run ``docker compose down [--volumes]`` inside the workspace root."""
    try:
        return compose_down(request.root_path, remove_volumes=request.remove_volumes)
    except DeployError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


@router.get("/api/v1/deploy/docker/logs", response_model=ComposeLogs, tags=["deploy"])
def docker_logs(
    root: str = Query(..., description="Workspace root exactly as returned by /api/v1/scan."),
    service: str | None = Query(default=None, max_length=63),
    tail: int = Query(default=DEFAULT_LOG_TAIL, ge=1, le=MAX_LOG_TAIL),
) -> ComposeLogs:
    """Recent container logs (tail clamped to 1000, service name validated)."""
    try:
        return compose_logs(root, service=service, tail=tail)
    except DeployError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


@router.get("/api/v1/audit-log", response_model=AuditLogResponse, tags=["audit"])
def audit_log(
    limit: int = Query(default=DEFAULT_AUDIT_LIMIT, ge=1, le=MAX_AUDIT_ENTRIES),
) -> AuditLogResponse:
    """Newest-first local audit entries (apply, rollback, deploy, git). Never contains secrets."""
    return AuditLogResponse(entries=read_events(limit))
