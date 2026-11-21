"""Kodo FastAPI orchestrator — scan, deterministic audit, dry-run patching and guarded apply."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.routes import router
from app.config import DEFAULT_API_PORT, cors_origins

app = FastAPI(
    title="Kodo API",
    description=(
        "Kodo Architecture Control Center — Phases 1–4. "
        "Analyzes Spring Boot, Node.js and .NET workspaces into the Core IR, runs the deterministic "
        "audit, computes dry-run AST patches in memory, scaffolds multi-stack vertical slices from a "
        "versioned blueprint, and applies reviewed patches to disk behind path-containment, SHA-256 "
        "optimistic concurrency and Git working-tree guards."
    ),
    version=__version__,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/", tags=["system"])
async def root() -> dict[str, str]:
    return {
        "service": "kodo-api-python",
        "version": __version__,
        "docs": "/docs",
        "scan": "POST /api/v1/scan",
        "audit": "POST /api/v1/audit",
        "dryRun": "POST /api/v1/dry-run",
        "blueprint": "GET /api/v1/blueprint",
        "scaffoldDryRun": "POST /api/v1/scaffold/dry-run",
        "gitStatus": "GET /api/v1/git/status",
        "apply": "POST /api/v1/apply",
        "rollback": "POST /api/v1/apply/rollback",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=DEFAULT_API_PORT, reload=False)
