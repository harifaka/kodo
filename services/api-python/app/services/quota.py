"""Per-user workspace storage accounting, clone caps and SaaS TTL cleanup.

Design rules:

* **Tenant containment.** Usage is measured under ``<KODO_WORKSPACES_DIR>/<user_id>/`` and deletion
  is only performed when the target resolves *strictly* inside that sandbox. A stray row pointing at
  a local host folder is never deleted — it is only forgotten from the database.
* **Symlink safety.** Directory sizes are walked with ``os.scandir(follow_symlinks=False)`` and a
  symlinked workspace root is never removed, so accounting and cleanup can never escape the sandbox.
* **Zero friction in local mode.** Quotas and TTL cleanup are SaaS-only by default; local
  self-hosting keeps unlimited disk and never has its own folders deleted automatically.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import (
    cleanup_interval_minutes,
    max_clone_size_mb,
    max_workspaces_per_user,
    quota_enabled,
    ttl_cleanup_enabled,
    user_quota_mb,
    workspace_ttl_hours,
)
from app.db.engine import session_scope
from app.db.models import Workspace, utcnow
from app.services.audit_log import AUDIT_ACTION_WORKSPACE_TTL_CLEANUP, record_event
from app.services.paths import workspaces_dir

logger = logging.getLogger("kodo.quota")

MB = 1024 * 1024
WORKSPACE_QUOTA_EXCEEDED = "WORKSPACE_QUOTA_EXCEEDED"
CLONE_SIZE_LIMIT_EXCEEDED = "CLONE_SIZE_LIMIT_EXCEEDED"


class StorageUsage(BaseModel):
    """``GET /api/v1/workspaces/storage`` payload (camelCase on the wire)."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")

    enabled: bool
    used_bytes: int
    quota_bytes: int
    workspace_count: int
    max_workspaces: int
    ttl_hours: int


def compute_dir_size_bytes(path: Path) -> int:
    """Total bytes below ``path``, never following symlinks and ignoring unreadable entries."""
    total = 0
    stack: list[Path] = [Path(path)]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    try:
                        if entry.is_symlink():
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(Path(entry.path))
                        elif entry.is_file(follow_symlinks=False):
                            total += entry.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
        except OSError:
            continue
    return total


def user_sandbox_dir(user_id: str) -> Path:
    """Sandbox path for ``user_id`` without creating it (accounting must stay read-only)."""
    return workspaces_dir() / user_id


def is_strictly_inside_sandbox(path: Path, user_id: str) -> bool:
    """True when ``path`` resolves inside (and is not equal to) the user's own sandbox."""
    candidate = Path(path).expanduser()
    if candidate.is_symlink():
        return False
    try:
        sandbox = user_sandbox_dir(user_id).resolve()
        resolved = candidate.resolve()
    except OSError:
        return False
    return resolved != sandbox and resolved.is_relative_to(sandbox)


def remove_workspace_dir(path: Path, user_id: str) -> bool:
    """Remove a sandboxed workspace folder.

    Returns ``True`` when the folder no longer exists afterwards (deleted now or already gone) and
    ``False`` when the path is outside the sandbox, a symlink, or could not be removed.
    """
    if not is_strictly_inside_sandbox(path, user_id):
        return False
    target = Path(path).expanduser()
    if target.is_symlink():
        return False
    if not target.exists():
        return True
    try:
        shutil.rmtree(target)
        return True
    except OSError as exc:
        logger.warning("Could not remove workspace %s: %s", target, exc)
        return False


def _records(session: Session, user_id: str) -> list[Workspace]:
    return list(session.scalars(select(Workspace).where(Workspace.user_id == user_id)).all())


def _used_bytes(user_id: str, rows: list[Workspace]) -> int:
    """Ground truth from the sandbox on disk; recorded sizes cover sandboxes not yet created."""
    sandbox = user_sandbox_dir(user_id)
    if sandbox.is_dir():
        return compute_dir_size_bytes(sandbox)
    return sum(max(0, row.size_bytes or 0) for row in rows)


def get_user_storage_usage(user_id: str, db: Session | None = None) -> StorageUsage:
    """Current usage/limits for one tenant. Never raises for an unreadable sandbox."""
    with (nullcontext(db) if db is not None else session_scope()) as session:
        rows = _records(session, user_id)
        used = _used_bytes(user_id, rows)
    return StorageUsage(
        enabled=quota_enabled(),
        used_bytes=used,
        quota_bytes=user_quota_mb() * MB,
        workspace_count=len(rows),
        max_workspaces=max_workspaces_per_user(),
        ttl_hours=workspace_ttl_hours(),
    )


def enforce_pre_clone_quota(user_id: str, db: Session | None = None) -> None:
    """Reject a new clone when the workspace count or disk quota is already exhausted."""
    if not quota_enabled():
        return
    usage = get_user_storage_usage(user_id, db)
    if usage.workspace_count >= usage.max_workspaces:
        raise HTTPException(
            status_code=413,
            detail={
                "code": WORKSPACE_QUOTA_EXCEEDED,
                "message": (
                    f"You already have {usage.workspace_count} workspaces, the maximum for your "
                    f"account ({usage.max_workspaces}). Delete one in the Workspace Switcher to free "
                    "a slot, then clone again."
                ),
            },
        )
    if usage.used_bytes >= usage.quota_bytes:
        raise HTTPException(
            status_code=507,
            detail={
                "code": WORKSPACE_QUOTA_EXCEEDED,
                "message": (
                    f"Your workspace storage is full ({_mb(usage.used_bytes)} of "
                    f"{_mb(usage.quota_bytes)} MB used). Delete a workspace to free space before "
                    "cloning another repository."
                ),
            },
        )


def enforce_post_clone_size(cloned_dir: Path, user_id: str, db: Session | None = None) -> int:
    """Enforce the single-repo cap and the total quota *after* cloning.

    An oversized clone is deleted immediately (strictly verified inside the sandbox) so a hostile or
    accidental giant repository can never consume the tenant's disk. Returns the measured size.
    """
    size = compute_dir_size_bytes(cloned_dir)
    if not quota_enabled():
        return size

    clone_limit = max_clone_size_mb() * MB
    if size > clone_limit:
        remove_workspace_dir(cloned_dir, user_id)
        raise HTTPException(
            status_code=413,
            detail={
                "code": CLONE_SIZE_LIMIT_EXCEEDED,
                "message": (
                    f"The cloned repository is {_mb(size)} MB, above the {max_clone_size_mb()} MB "
                    "per-repository limit. The clone was removed — try a smaller repository or a "
                    "sparse/shallow checkout."
                ),
            },
        )

    usage = get_user_storage_usage(user_id, db)
    if usage.used_bytes > usage.quota_bytes:
        remove_workspace_dir(cloned_dir, user_id)
        raise HTTPException(
            status_code=413,
            detail={
                "code": WORKSPACE_QUOTA_EXCEEDED,
                "message": (
                    f"Cloning this repository would exceed your {_mb(usage.quota_bytes)} MB workspace "
                    "quota. The clone was removed — delete a workspace to free space."
                ),
            },
        )

    with (nullcontext(db) if db is not None else session_scope()) as session:
        row = session.scalar(
            select(Workspace).where(
                Workspace.user_id == user_id, Workspace.local_path == str(cloned_dir)
            )
        )
        if row is not None:
            row.size_bytes = size
            row.last_accessed_at = utcnow()
            session.flush()
    return size


def cleanup_stale_workspaces(db: Session | None = None, now: datetime | None = None) -> int:
    """Delete SaaS workspaces untouched for longer than the TTL. Returns the removed count.

    Only ever acts in ``KODO_MODE=saas`` with a positive TTL, and only on folders strictly inside the
    owning tenant's sandbox. Local host folders are left untouched.
    """
    if not ttl_cleanup_enabled():
        return 0

    ttl = workspace_ttl_hours()
    reference = _as_utc(now) or utcnow()
    cutoff = reference - timedelta(hours=ttl)
    removed = 0
    cleaned: list[tuple[str, str]] = []

    with (nullcontext(db) if db is not None else session_scope()) as session:
        for row in session.scalars(select(Workspace)).all():
            last = _as_utc(row.last_accessed_at or row.last_scanned_at or row.created_at)
            if last is None or last >= cutoff:
                continue
            if not is_strictly_inside_sandbox(Path(row.local_path), row.user_id):
                # Never delete (or forget the bookmark of) anything outside the tenant sandbox.
                continue
            if not remove_workspace_dir(Path(row.local_path), row.user_id):
                continue
            cleaned.append((row.user_id, row.local_path))
            session.delete(row)
            removed += 1

    for owner, local_path in cleaned:
        record_event(
            AUDIT_ACTION_WORKSPACE_TTL_CLEANUP,
            local_path,
            f"Removed workspace untouched for more than {ttl}h",
            user_id=owner,
        )
    if removed:
        logger.info("TTL cleanup removed %d stale workspace(s)", removed)
    return removed


async def run_cleanup_loop(
    stop_event: asyncio.Event, interval_seconds: float | None = None
) -> None:
    """Awaitable background loop: one cleanup pass per interval until ``stop_event`` is set.

    The default interval comes from ``KODO_CLEANUP_INTERVAL_MINUTES``; tests pass a short
    ``interval_seconds`` to exercise the loop without waiting.
    """
    configured = (
        float(interval_seconds)
        if interval_seconds is not None
        else cleanup_interval_minutes() * 60.0
    )
    interval = max(0.05, configured)
    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
            return
        except TimeoutError:
            pass
        try:
            await asyncio.to_thread(cleanup_stale_workspaces)
        except Exception:  # pragma: no cover - defensive: a failed pass must not stop the loop
            logger.exception("Workspace TTL cleanup pass failed")


def _as_utc(value: datetime | None) -> datetime | None:
    """SQLite returns naive datetimes even for ``timezone=True`` columns."""
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _mb(size: int) -> int:
    return int(round(size / MB))


__all__ = [
    "CLONE_SIZE_LIMIT_EXCEEDED",
    "StorageUsage",
    "WORKSPACE_QUOTA_EXCEEDED",
    "cleanup_stale_workspaces",
    "compute_dir_size_bytes",
    "enforce_post_clone_size",
    "enforce_pre_clone_quota",
    "get_user_storage_usage",
    "is_strictly_inside_sandbox",
    "remove_workspace_dir",
    "run_cleanup_loop",
    "user_sandbox_dir",
]
