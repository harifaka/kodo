"""SaaS / Git adapter endpoints (Phase 6).

``/git/clone`` validates an HTTPS GitHub/GitLab URL and shallow-clones into Kodo's managed
workspace directory; ``/git/export`` creates a branch, commits the applied changes and optionally
pushes + opens a GitHub Pull Request. Tokens live in the request only and are never persisted,
logged or echoed back.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from app.auth.dependencies import CurrentUser
from app.db import repository
from app.services.git_remote import (
    CloneResult,
    ExportResult,
    GitRemoteError,
    clone_repository,
    export_branch,
)
from app.services.paths import enforce_workspace_access

router = APIRouter()


class GitModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


class CloneRequest(GitModel):
    repo_url: str = Field(..., min_length=1, max_length=500)
    branch: str | None = Field(default=None, max_length=200)
    token: str | None = Field(default=None, max_length=512)


class ExportRequest(GitModel):
    root_path: str = Field(..., min_length=1)
    branch_name: str = Field(..., min_length=1, max_length=200)
    commit_message: str = Field(..., min_length=1, max_length=500)
    create_pr: bool = False
    pr_title: str | None = Field(default=None, max_length=250)
    pr_body: str | None = Field(default=None, max_length=20_000)
    token: str | None = Field(default=None, max_length=512)


@router.post("/api/v1/git/clone", response_model=CloneResult, tags=["git"])
def git_clone(
    request: CloneRequest,
    user: CurrentUser,
) -> CloneResult:
    """Shallow-clone a remote repository into the user's workspace directory for scanning."""
    try:
        return clone_repository(
            request.repo_url,
            branch=request.branch,
            token=request.token,
            user_id=user.id,
        )
    except GitRemoteError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


@router.post("/api/v1/git/export", response_model=ExportResult, tags=["git"])
def git_export(
    request: ExportRequest,
    user: CurrentUser,
) -> ExportResult:
    """Branch + commit the workspace, and optionally push and open a GitHub pull request."""
    root = enforce_workspace_access(request.root_path, user)
    try:
        result = export_branch(
            str(root),
            branch_name=request.branch_name,
            commit_message=request.commit_message,
            create_pr=request.create_pr,
            pr_title=request.pr_title,
            pr_body=request.pr_body,
            token=request.token,
        )
    except GitRemoteError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc
    try:
        repository.touch_workspace(user.id, str(root))
    except Exception:
        pass
    return result
