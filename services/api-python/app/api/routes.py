"""HTTP surface of the Kodo orchestrator."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from app import __version__
from app.config import MAX_INSPECT_BYTES, csharp_analyzer_url
from app.models.ir import WorkspaceIR
from app.services.csharp_client import check_health
from app.services.workspace import WorkspaceNotFoundError, build_workspace

router = APIRouter()


class ScanRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")

    path: str = Field(..., min_length=1, description="Absolute (or ~-prefixed) path of the folder to analyze.")


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
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@router.post("/api/v1/scan", response_model=WorkspaceIR, tags=["analysis"])
async def scan(request: ScanRequest) -> WorkspaceIR:
    try:
        return await build_workspace(request.path)
    except WorkspaceNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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
