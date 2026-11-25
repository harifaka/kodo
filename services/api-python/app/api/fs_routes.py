"""Local-only, zero-copy folder browsing (Phase 11).

``GET /api/v1/fs/browse`` lists one directory level of the real host/mount filesystem. It never
uploads, copies or writes a file — the UI simply fills the existing workspace path input with the
folder the user picked. The route is always disabled in ``KODO_MODE=saas`` (``403``), and the
middleware gates it before authentication so multi-tenant deployments can never reach it.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from app.auth.dependencies import CurrentUser
from app.config import get_settings
from app.services.fs_browser import BrowseError, browse

router = APIRouter()

FS_BROWSE_DISABLED_IN_SAAS = "FS_BROWSE_DISABLED_IN_SAAS"


class BrowseRootResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    label: str
    path: str


class BrowseMarkersResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    stacks: list[str] = Field(default_factory=list)
    is_git_repo: bool = False


class BrowseEntryResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    name: str
    path: str
    stacks: list[str] = Field(default_factory=list)
    is_git_repo: bool = False
    has_subdirectories: bool = False


class BrowseResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    runtime: str
    current_path: str
    parent_path: str | None = None
    roots: list[BrowseRootResponse] = Field(default_factory=list)
    current_markers: BrowseMarkersResponse = Field(default_factory=BrowseMarkersResponse)
    entries: list[BrowseEntryResponse] = Field(default_factory=list)
    truncated: bool = False
    empty_mount_hint: bool = False
    hint_message: str | None = None


def _saas_forbidden() -> HTTPException:
    return HTTPException(
        status_code=403,
        detail={
            "code": FS_BROWSE_DISABLED_IN_SAAS,
            "message": (
                "Browsing the server filesystem is disabled in SaaS mode. Sign in and use the "
                "Workspace Switcher or Clone Repo instead."
            ),
        },
    )


@router.get("/api/v1/fs/browse", response_model=BrowseResponse, tags=["filesystem"])
def browse_filesystem(
    user: CurrentUser,
    path: str | None = Query(None, description="Folder to list; defaults to the runtime start folder."),
    show_hidden: bool = Query(False, alias="showHidden", description="Include hidden/noise folders."),
) -> BrowseResponse:
    if get_settings().is_saas:
        raise _saas_forbidden()

    try:
        payload = browse(path, show_hidden=show_hidden)
    except BrowseError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": exc.message},
        ) from exc

    return BrowseResponse(
        runtime=payload.runtime,
        current_path=str(payload.current_path),
        parent_path=str(payload.parent_path) if payload.parent_path is not None else None,
        roots=[BrowseRootResponse(label=root.label, path=str(root.path)) for root in payload.roots],
        current_markers=BrowseMarkersResponse(
            stacks=payload.markers.stacks,
            is_git_repo=payload.markers.is_git_repo,
        ),
        entries=[
            BrowseEntryResponse(
                name=entry.name,
                path=str(entry.path),
                stacks=entry.stacks,
                is_git_repo=entry.is_git_repo,
                has_subdirectories=entry.has_subdirectories,
            )
            for entry in payload.entries
        ],
        truncated=payload.truncated,
        empty_mount_hint=payload.empty_mount_hint,
        hint_message=payload.hint_message,
    )


__all__ = ["FS_BROWSE_DISABLED_IN_SAAS", "BrowseResponse", "router"]
