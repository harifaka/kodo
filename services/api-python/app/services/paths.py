"""Per-user workspace sandboxes and the SaaS path-containment gate.

Local mode keeps the original behaviour (any accessible folder may be scanned). In SaaS mode every
workspace path must resolve inside ``<KODO_WORKSPACES_DIR>/<user_id>/``; symlink escapes, ``..``
traversal, host paths and other tenants' sandboxes are rejected with ``403 SAAS_PATH_FORBIDDEN``.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from app.config import get_settings
from app.patching.paths import PatchRejected, resolve_root

SANDBOX_FORBIDDEN_CODE = "SAAS_PATH_FORBIDDEN"
_SANDBOX_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


def workspaces_dir() -> Path:
    configured = os.getenv("KODO_WORKSPACES_DIR")
    if configured and configured.strip():
        return Path(configured.strip()).expanduser().resolve()
    return (Path.home() / ".kodo" / "workspaces").resolve()


def user_sandbox_root(user_id: str) -> Path:
    """Return (and create) the strict sandbox folder for one user id."""
    if not _SANDBOX_ID.match(user_id or ""):
        raise HTTPException(
            status_code=403,
            detail={"code": SANDBOX_FORBIDDEN_CODE, "message": "Invalid user sandbox identifier."},
        )
    root = workspaces_dir() / user_id
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail={"code": "SANDBOX_UNAVAILABLE", "message": f"Cannot create the user sandbox: {exc}"},
        ) from exc
    return root.resolve()


def _user_id(user: Any) -> str:
    value = getattr(user, "id", user)
    return str(value)


def enforce_workspace_access(root_path: str, user: Any) -> Path:
    """Resolve a workspace root, enforcing the SaaS sandbox boundary."""
    try:
        root = resolve_root(root_path)
    except PatchRejected as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": "PATH_REJECTED", "message": str(exc)},
        ) from exc

    if not get_settings().is_saas:
        return root

    sandbox = user_sandbox_root(_user_id(user))
    if not root.is_relative_to(sandbox):
        raise HTTPException(
            status_code=403,
            detail={
                "code": SANDBOX_FORBIDDEN_CODE,
                "message": (
                    "In SaaS mode Kodo only operates on workspaces cloned into your own sandbox. "
                    "Use the Workspace Switcher or Clone Repo instead of a host folder path."
                ),
            },
        )
    return root


def is_inside_sandbox(path: Path, user_id: str) -> bool:
    try:
        sandbox = (workspaces_dir() / user_id).resolve()
        candidate = Path(path).expanduser().resolve()
    except OSError:
        return False
    return candidate.is_relative_to(sandbox) and candidate != sandbox


__all__ = [
    "SANDBOX_FORBIDDEN_CODE",
    "enforce_workspace_access",
    "is_inside_sandbox",
    "user_sandbox_root",
    "workspaces_dir",
]
