"""Kodo FastAPI orchestrator — scan, deterministic audit, dry-run patching, guarded apply and AI."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import __version__
from app.api.account_routes import router as account_router
from app.api.git_routes import router as git_router
from app.api.routes import router
from app.auth.context import reset_current_user_id, set_current_user_id
from app.auth.dependencies import authenticate_request
from app.auth.github_oauth import router as auth_router
from app.builders.routes import router as build_router
from app.config import (
    DEFAULT_API_PORT,
    ConfigurationError,
    cors_origins,
    get_settings,
    validate_startup,
)
from app.db import init_db
from app.db.repository import LOCAL_USER_ID
from app.decision.routes import router as decision_router
from app.deploy.routes import router as deploy_router
from app.llm.routes import router as ai_router


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    # Fail fast on unsafe SaaS configuration, then create tables and seed the local user.
    validate_startup()
    init_db()
    yield


app = FastAPI(
    lifespan=lifespan,
    title="Kodo API",
    description=(
        "Kodo Architecture Control Center — Phases 1–10. "
        "Analyzes Spring Boot, Node.js and .NET workspaces into the Core IR, runs the deterministic "
        "audit, computes dry-run AST patches in memory, scaffolds multi-stack vertical slices from a "
        "versioned blueprint, proposes AI patches through an OpenAI-compatible DeepSeek/Ollama client, "
        "triages/routes/screens with an advisory local System 1 (Laya) decision layer backed by "
        "tenant-scoped ADRs, generates production Docker artifacts (reviewed through the same diff), "
        "verifies proposed code in network-isolated ephemeral builder containers, controls local Docker "
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


@app.middleware("http")
async def tenant_guard(request: Request, call_next):  # type: ignore[no-untyped-def]
    """SaaS fail-closed gate: session auth for every API call, no host Docker control."""
    path = request.url.path
    if not path.startswith("/api/v1"):
        return await call_next(request)

    try:
        settings = get_settings()
    except ConfigurationError as exc:
        return JSONResponse(
            status_code=503,
            content={"detail": {"code": "CONFIGURATION_ERROR", "message": str(exc)}},
        )

    if settings.is_saas and path.startswith("/api/v1/deploy/docker/"):
        return JSONResponse(
            status_code=403,
            content={
                "detail": {
                    "code": "DOCKER_CONTROL_DISABLED_IN_SAAS",
                    "message": (
                        "Host Docker control is disabled in SaaS mode. Dockerfile/Compose generation, "
                        "the diff review and Git export remain fully available."
                    ),
                }
            },
        )

    is_auth_route = path.startswith("/api/v1/auth/")
    user = None if is_auth_route else authenticate_request(request)
    if settings.is_saas and not is_auth_route and user is None:
        return JSONResponse(
            status_code=401,
            content={
                "detail": {
                    "code": "UNAUTHORIZED",
                    "message": "Sign in with GitHub to use this Kodo instance.",
                }
            },
        )
    if user is not None:
        request.state.user = user
    token = set_current_user_id(user.id if user is not None else LOCAL_USER_ID)

    try:
        return await call_next(request)
    finally:
        reset_current_user_id(token)


app.include_router(router)
app.include_router(ai_router)
app.include_router(build_router)
app.include_router(deploy_router)
app.include_router(git_router)
app.include_router(auth_router)
app.include_router(account_router)
app.include_router(decision_router)


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
        "aiFixBuildErrors": "POST /api/v1/ai/fix-build-errors",
        "buildStatus": "GET /api/v1/build/status",
        "buildVerify": "POST /api/v1/build/verify",
        "buildVerifyStream": "POST /api/v1/build/verify/stream",
        "deployDryRun": "POST /api/v1/deploy/dry-run",
        "dockerStatus": "GET /api/v1/deploy/docker/status",
        "dockerUp": "POST /api/v1/deploy/docker/up",
        "dockerDown": "POST /api/v1/deploy/docker/down",
        "dockerLogs": "GET /api/v1/deploy/docker/logs",
        "auditLog": "GET /api/v1/audit-log",
        "gitClone": "POST /api/v1/git/clone",
        "gitExport": "POST /api/v1/git/export",
        "authMe": "GET /api/v1/auth/me",
        "workspaces": "GET /api/v1/workspaces",
        "blueprints": "GET /api/v1/blueprints",
        "userSettings": "GET /api/v1/user/settings",
        "systemOneTest": "POST /api/v1/decision/test-connection",
        "systemOneTriage": "POST /api/v1/decision/triage-audit",
        "systemOneRoute": "POST /api/v1/decision/route-task",
        "systemOneScreenDiff": "POST /api/v1/decision/screen-diff",
        "decisions": "GET /api/v1/decisions",
        "decisionsTrainingExport": "GET /api/v1/decisions/export-training",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=DEFAULT_API_PORT, reload=False)
