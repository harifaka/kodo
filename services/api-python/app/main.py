"""Kodo FastAPI orchestrator — scan, deterministic audit, dry-run patching, guarded apply and AI."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.git_routes import router as git_router
from app.api.routes import router
from app.config import DEFAULT_API_PORT, cors_origins
from app.deploy.routes import router as deploy_router
from app.llm.routes import router as ai_router

app = FastAPI(
    title="Kodo API",
    description=(
        "Kodo Architecture Control Center — Phases 1–6. "
        "Analyzes Spring Boot, Node.js and .NET workspaces into the Core IR, runs the deterministic "
        "audit, computes dry-run AST patches in memory, scaffolds multi-stack vertical slices from a "
        "versioned blueprint, proposes AI patches through an OpenAI-compatible DeepSeek/Ollama client, "
        "generates production Docker artifacts (reviewed through the same diff), controls local Docker "
        "Compose, and exports Git branches/pull requests — all applied to disk behind path-containment, "
        "SHA-256 optimistic concurrency and Git working-tree guards."
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
app.include_router(ai_router)
app.include_router(deploy_router)
app.include_router(git_router)


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
        "aiTestConnection": "POST /api/v1/ai/test-connection",
        "aiSpecToBlueprint": "POST /api/v1/ai/spec-to-blueprint",
        "aiAuditFix": "POST /api/v1/ai/audit-fix",
        "aiImplementMethod": "POST /api/v1/ai/implement-method",
        "deployDryRun": "POST /api/v1/deploy/dry-run",
        "dockerStatus": "GET /api/v1/deploy/docker/status",
        "dockerUp": "POST /api/v1/deploy/docker/up",
        "dockerDown": "POST /api/v1/deploy/docker/down",
        "dockerLogs": "GET /api/v1/deploy/docker/logs",
        "auditLog": "GET /api/v1/audit-log",
        "gitClone": "POST /api/v1/git/clone",
        "gitExport": "POST /api/v1/git/export",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=DEFAULT_API_PORT, reload=False)
