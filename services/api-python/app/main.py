"""Kodo FastAPI orchestrator — read-only Phase 1."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.routes import router
from app.config import DEFAULT_API_PORT, cors_origins

app = FastAPI(
    title="Kodo API",
    description=(
        "Kodo Architecture Control Center — Phase 1 (Vibe-Code X-Ray). "
        "Read-only analysis of Spring Boot, Node.js and .NET workspaces into the Core IR."
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
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=DEFAULT_API_PORT, reload=False)
