"""Audit trail: per-user rows in the database plus a local JSONL mirror.

Every guarded write, Docker lifecycle action and Git export is recorded for the authenticated user.
The database is the system of record (per-user isolation, survives restarts); in local mode the same
event is also mirrored to ``~/.kodo/audit.jsonl`` (or ``KODO_AUDIT_LOG_PATH``) so existing
self-hosted tooling keeps working.

Only structured metadata is stored — never file contents, environment values or tokens. Summaries
are additionally redacted for credential-shaped strings, and every write is best-effort so an
unwritable audit file can never break the guarded apply/deploy path.
"""

from __future__ import annotations

import json
import os
import re
import threading
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from app.auth.context import current_user_id
from app.config import get_settings
from app.db import repository

AUDIT_ACTION_APPLY = "apply"
AUDIT_ACTION_ROLLBACK = "rollback"
AUDIT_ACTION_DEPLOY_UP = "deploy_up"
AUDIT_ACTION_DEPLOY_DOWN = "deploy_down"
AUDIT_ACTION_GIT_CLONE = "git_clone"
AUDIT_ACTION_GIT_EXPORT = "git_export"
AUDIT_ACTION_VERIFY_BUILD = "verify_build"
AUDIT_ACTION_DECISION_FEEDBACK = "decision_feedback"

AUDIT_ACTIONS = (
    AUDIT_ACTION_APPLY,
    AUDIT_ACTION_ROLLBACK,
    AUDIT_ACTION_DEPLOY_UP,
    AUDIT_ACTION_DEPLOY_DOWN,
    AUDIT_ACTION_GIT_CLONE,
    AUDIT_ACTION_GIT_EXPORT,
    AUDIT_ACTION_VERIFY_BUILD,
    AUDIT_ACTION_DECISION_FEEDBACK,
)

MAX_AUDIT_ENTRIES = 1000
DEFAULT_AUDIT_LIMIT = 100
_TAIL_BYTES = 512 * 1024

_redact_patterns = (
    re.compile(r"gh[pousr]_[A-Za-z0-9]{8,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{8,}"),
    re.compile(r"glpat-[A-Za-z0-9_-]{8,}"),
    re.compile(r"(?i)\b(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"(?i)http\.extraheader=\S+"),
    re.compile(r"(?i)\b(?:token|password|secret|api[_-]?key)\s*[=:]\s*\S+"),
)

_lock = threading.Lock()


class AuditEntry(BaseModel):
    """One audit record. Wire format is camelCase; Python attributes stay snake_case."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="ignore")

    timestamp: str
    action: str
    root_path: str
    summary: str = ""
    files_count: int = Field(default=0, ge=0)
    status: str = "success"


def audit_log_path() -> Path:
    configured = os.getenv("KODO_AUDIT_LOG_PATH")
    if configured and configured.strip():
        return Path(configured.strip()).expanduser()
    return Path.home() / ".kodo" / "audit.jsonl"


def redact(text: str) -> str:
    """Remove credential-shaped fragments from a summary before it is persisted."""
    cleaned = text
    for pattern in _redact_patterns:
        cleaned = pattern.sub("[redacted]", cleaned)
    return cleaned


def record_event(
    action: str,
    root_path: str,
    summary: str = "",
    *,
    files_count: int = 0,
    status: str = "success",
    timestamp: str | None = None,
    user_id: str | None = None,
) -> None:
    """Record one event. Never raises: audit logging must not break the caller's operation."""
    owner = user_id or current_user_id()
    clean_summary = redact(summary)
    moment = _parse_timestamp(timestamp)

    try:
        repository.record_audit_event(
            owner,
            action,
            str(root_path),
            clean_summary,
            max(0, int(files_count)),
            status,
            moment,
        )
    except Exception:
        pass

    # Local mode keeps the append-only JSONL mirror for self-hosted tooling compatibility.
    try:
        if get_settings().is_saas:
            return
    except Exception:
        return

    entry = {
        "timestamp": timestamp or _now(),
        "action": action,
        "rootPath": str(root_path),
        "summary": clean_summary,
        "filesCount": max(0, int(files_count)),
        "status": status,
    }
    try:
        path = audit_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(entry, ensure_ascii=False, separators=(",", ":"))
        with _lock, path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(payload + "\n")
    except (OSError, ValueError):
        return


def read_user_events(user_id: str, limit: int = DEFAULT_AUDIT_LIMIT) -> list[AuditEntry]:
    """Newest-first audit rows belonging strictly to ``user_id``."""
    clamped = max(1, min(int(limit), MAX_AUDIT_ENTRIES))
    try:
        rows = repository.read_audit_events(user_id, clamped)
    except Exception:
        return []
    return [
        AuditEntry(
            timestamp=row.timestamp,
            action=row.action,
            rootPath=row.root_path,
            summary=row.summary,
            filesCount=row.files_count,
            status=row.status,
        )
        for row in rows
    ]


def _parse_timestamp(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def read_events(limit: int = DEFAULT_AUDIT_LIMIT) -> list[AuditEntry]:
    """Return the newest entries first, tolerating malformed lines and an absent log file."""
    clamped = max(1, min(int(limit), MAX_AUDIT_ENTRIES))
    path = audit_log_path()
    if not path.is_file():
        return []

    try:
        raw = _read_tail(path)
    except OSError:
        return []

    entries: list[AuditEntry] = []
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            data = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        try:
            entries.append(AuditEntry.model_validate(data))
        except ValueError:
            continue

    return list(reversed(entries))[:clamped]


def _read_tail(path: Path) -> str:
    size = path.stat().st_size
    with path.open("rb") as handle:
        if size > _TAIL_BYTES:
            handle.seek(size - _TAIL_BYTES)
            handle.readline()  # drop the partial first line
        return handle.read().decode("utf-8", errors="replace")


def _now() -> str:
    return datetime.now(UTC).isoformat()


__all__ = [
    "AUDIT_ACTIONS",
    "AUDIT_ACTION_APPLY",
    "AUDIT_ACTION_DECISION_FEEDBACK",
    "AUDIT_ACTION_DEPLOY_DOWN",
    "AUDIT_ACTION_DEPLOY_UP",
    "AUDIT_ACTION_GIT_CLONE",
    "AUDIT_ACTION_GIT_EXPORT",
    "AUDIT_ACTION_ROLLBACK",
    "AUDIT_ACTION_VERIFY_BUILD",
    "AuditEntry",
    "audit_log_path",
    "read_events",
    "read_user_events",
    "record_event",
    "redact",
]
