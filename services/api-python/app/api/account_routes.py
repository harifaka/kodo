"""Account-scoped endpoints: workspaces, storage usage, saved blueprints and user settings."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from app.auth.dependencies import CurrentUser
from app.config import get_settings
from app.db import repository
from app.db.repository import WorkspaceRecord
from app.services.audit_log import AUDIT_ACTION_WORKSPACE_DELETE, record_event
from app.services.quota import (
    StorageUsage,
    get_user_storage_usage,
    remove_workspace_dir,
)

router = APIRouter()


class AccountModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


class WorkspaceModel(AccountModel):
    id: str
    name: str
    local_path: str
    repo_url: str | None = None
    branch: str | None = None
    last_health_score: int | None = None
    last_scanned_at: str | None = None
    created_at: str
    size_bytes: int = 0
    last_accessed_at: str | None = None


class WorkspaceListResponse(AccountModel):
    workspaces: list[WorkspaceModel] = Field(default_factory=list)


class DeleteWorkspaceResponse(AccountModel):
    ok: bool = True
    workspace_id: str
    directory_removed: bool = False
    storage: StorageUsage


class BlueprintSummary(AccountModel):
    id: str
    workspace_path: str
    name: str
    stack: str
    blueprint: dict[str, Any] | None = None
    updated_at: str


class BlueprintListResponse(AccountModel):
    blueprints: list[BlueprintSummary] = Field(default_factory=list)


class UserSettingsModel(AccountModel):
    settings: dict[str, Any] = Field(default_factory=dict)
    updated_at: str | None = None


class UserSettingsRequest(AccountModel):
    settings: dict[str, Any] = Field(default_factory=dict)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _workspace_payload(row: WorkspaceRecord) -> WorkspaceModel:
    return WorkspaceModel(
        id=row.id,
        name=row.name,
        local_path=row.local_path,
        repo_url=row.repo_url,
        branch=row.branch,
        last_health_score=row.last_health_score,
        last_scanned_at=_iso(row.last_scanned_at),
        created_at=_iso(row.created_at) or "",
        size_bytes=int(row.size_bytes or 0),
        last_accessed_at=_iso(row.last_accessed_at),
    )


@router.get("/api/v1/workspaces", response_model=WorkspaceListResponse, tags=["workspaces"])
def list_workspaces(user: CurrentUser) -> WorkspaceListResponse:
    """The current user's cloned/recent workspaces, newest first."""
    try:
        rows = repository.list_workspaces(user.id)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "WORKSPACES_UNAVAILABLE", "message": f"Workspace store unavailable: {exc}"},
        ) from exc
    return WorkspaceListResponse(workspaces=[_workspace_payload(row) for row in rows])


@router.get("/api/v1/workspaces/storage", response_model=StorageUsage, tags=["workspaces"])
def workspace_storage(user: CurrentUser) -> StorageUsage:
    """Disk usage vs. quota for the current user. ``enabled`` is false in local mode."""
    return get_user_storage_usage(user.id)


@router.delete(
    "/api/v1/workspaces/{workspace_id}",
    response_model=DeleteWorkspaceResponse,
    tags=["workspaces"],
)
def delete_workspace(
    workspace_id: str,
    user: CurrentUser,
) -> DeleteWorkspaceResponse:
    """Delete one of the current user's workspaces (and its sandbox directory when owned).

    Only the cloned folder inside ``<KODO_WORKSPACES_DIR>/<user_id>/`` is ever removed. Bookmarks
    that point at a local host folder are simply forgotten, so local self-hosting never loses data.
    """
    try:
        record = repository.get_workspace(user.id, workspace_id)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "WORKSPACES_UNAVAILABLE", "message": f"Workspace store unavailable: {exc}"},
        ) from exc
    if record is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "UNKNOWN_WORKSPACE", "message": "No such workspace in your account."},
        )

    directory_removed = False
    if get_settings().is_saas:
        directory_removed = remove_workspace_dir(Path(record.local_path), user.id)

    repository.delete_workspace(user.id, workspace_id)
    record_event(
        AUDIT_ACTION_WORKSPACE_DELETE,
        record.local_path,
        f"Deleted workspace '{record.name}'"
        + (" and its cloned files" if directory_removed else " (bookmark only)"),
        user_id=user.id,
    )
    return DeleteWorkspaceResponse(
        workspace_id=workspace_id,
        directory_removed=directory_removed,
        storage=get_user_storage_usage(user.id),
    )


@router.get("/api/v1/blueprints", response_model=BlueprintListResponse, tags=["builder"])
def list_blueprints(user: CurrentUser) -> BlueprintListResponse:
    """Blueprints saved or applied by the current user, newest first."""
    try:
        rows = repository.list_blueprints(user.id)
    except Exception:
        return BlueprintListResponse()

    def _document(raw: str) -> dict[str, Any] | None:
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError):
            return None
        return parsed if isinstance(parsed, dict) else None

    return BlueprintListResponse(
        blueprints=[
            BlueprintSummary(
                id=row.id,
                workspace_path=row.workspace_path,
                name=row.name,
                stack=row.stack,
                blueprint=_document(row.blueprint_json),
                updated_at=row.updated_at.isoformat(),
            )
            for row in rows
        ]
    )


@router.get("/api/v1/user/settings", response_model=UserSettingsModel, tags=["account"])
def get_user_settings(user: CurrentUser) -> UserSettingsModel:
    """Non-secret UI/LLM preferences. API keys are never stored server-side."""
    try:
        settings, updated_at = repository.get_user_settings(user.id)
    except Exception:
        settings, updated_at = {}, None
    return UserSettingsModel(settings=settings, updated_at=_iso(updated_at))


@router.put("/api/v1/user/settings", response_model=UserSettingsModel, tags=["account"])
def put_user_settings(
    request: UserSettingsRequest,
    user: CurrentUser,
) -> UserSettingsModel:
    """Persist provider/model preferences, rejecting any credential-shaped field."""
    try:
        updated_at = repository.save_user_settings(user.id, request.settings)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "SECRET_NOT_ALLOWED", "message": str(exc)},
        ) from exc
    return UserSettingsModel(settings=request.settings, updated_at=updated_at.isoformat())


__all__ = ["router"]
