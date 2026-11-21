"""Kodo FastAPI orchestrator — scan, deterministic audit, and zero-write dry-run patching."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.routes import router
from app.config import DEFAULT_API_PORT, cors_origins

app = FastAPI(
    title="Kodo API",
    description=(
        "Kodo Architecture Control Center — Phases 1–3b. "
        "Analyzes Spring Boot, Node.js and .NET workspaces into the Core IR, runs the deterministic "
        "audit, and computes dry-run AST patches in memory without ever writing to disk."
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
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=DEFAULT_API_PORT, reload=False)
