"""Persistence helpers. Every query is scoped by ``user_id`` so tenants never see each other."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import delete, select

from app.db.engine import session_scope
from app.db.models import (
    ArchitectureDecisionRecord,
    AuditEvent,
    RollbackBatch,
    SavedBlueprint,
    User,
    UserSettings,
    Workspace,
    utcnow,
)

LOCAL_USER_ID = "local"
MAX_ROLLBACK_BATCHES = 20
MAX_AUDIT_EVENTS = 1000
DEFAULT_AUDIT_LIMIT = 100


@dataclass(frozen=True)
class UserRecord:
    id: str
    username: str
    display_name: str | None = None
    avatar_url: str | None = None
    email: str | None = None
    github_id: str | None = None


@dataclass(frozen=True)
class AuditEventRecord:
    timestamp: str
    action: str
    root_path: str
    summary: str = ""
    files_count: int = 0
    status: str = "success"


@dataclass(frozen=True)
class RollbackFileRecord:
    file_path: str
    previous_content: str | None
    written_sha256: str
    is_new_file: bool
    created_dirs: tuple[str, ...] = ()


@dataclass(frozen=True)
class RollbackBatchRecord:
    apply_id: str
    user_id: str
    root_path: str
    created_at: datetime
    files: tuple[RollbackFileRecord, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class WorkspaceRecord:
    id: str
    user_id: str
    name: str
    local_path: str
    repo_url: str | None
    branch: str | None
    last_health_score: int | None
    last_scanned_at: datetime | None
    created_at: datetime


@dataclass(frozen=True)
class BlueprintRecord:
    id: str
    workspace_path: str
    name: str
    stack: str
    blueprint_json: str
    updated_at: datetime


@dataclass(frozen=True)
class DecisionRecord:
    id: str
    user_id: str
    workspace_path: str
    decision_type: str
    subject: str
    model: str
    recommended_route: str
    confidence: float
    latency_ms: int
    state_json: str
    answers_json: str
    feedback_status: str
    override_route: str | None
    feedback_note: str | None
    created_at: datetime
    feedback_at: datetime | None


def _to_user(row: User) -> UserRecord:
    return UserRecord(
        id=row.id,
        username=row.username,
        display_name=row.display_name,
        avatar_url=row.avatar_url,
        email=row.email,
        github_id=row.github_id,
    )


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _to_workspace(row: Workspace) -> WorkspaceRecord:
    return WorkspaceRecord(
        id=row.id,
        user_id=row.user_id,
        name=row.name,
        local_path=row.local_path,
        repo_url=row.repo_url,
        branch=row.branch,
        last_health_score=row.last_health_score,
        last_scanned_at=row.last_scanned_at,
        created_at=row.created_at,
    )


# ------------------------------------------------------------------------------------- users


def seed_local_user(session: Any) -> None:
    row = session.get(User, LOCAL_USER_ID)
    if row is not None:
        return
    session.add(
        User(
            id=LOCAL_USER_ID,
            username=LOCAL_USER_ID,
            display_name="Local User",
            created_at=utcnow(),
        )
    )


def get_user(user_id: str) -> UserRecord | None:
    with session_scope() as session:
        row = session.get(User, user_id)
        return _to_user(row) if row is not None else None


def upsert_github_user(
    *,
    github_id: str,
    username: str,
    display_name: str | None,
    avatar_url: str | None,
    email: str | None,
) -> UserRecord:
    with session_scope() as session:
        row = session.scalar(select(User).where(User.github_id == github_id))
        now = utcnow()
        if row is None:
            row = User(
                id=uuid.uuid4().hex,
                github_id=github_id,
                username=username,
                display_name=display_name,
                avatar_url=avatar_url,
                email=email,
                created_at=now,
                last_login_at=now,
            )
            session.add(row)
        else:
            row.username = username
            row.display_name = display_name
            row.avatar_url = avatar_url
            row.email = email
            row.last_login_at = now
        session.flush()
        return _to_user(row)


# ------------------------------------------------------------------------------ audit events


def record_audit_event(
    user_id: str,
    action: str,
    root_path: str,
    summary: str,
    files_count: int,
    status: str,
    timestamp: datetime | None = None,
) -> None:
    with session_scope() as session:
        session.add(
            AuditEvent(
                user_id=user_id,
                timestamp=timestamp or utcnow(),
                action=action,
                root_path=str(root_path),
                summary=summary,
                files_count=max(0, int(files_count)),
                status=status,
            )
        )


def read_audit_events(user_id: str, limit: int = DEFAULT_AUDIT_LIMIT) -> list[AuditEventRecord]:
    clamped = max(1, min(int(limit), MAX_AUDIT_EVENTS))
    with session_scope() as session:
        rows = session.scalars(
            select(AuditEvent)
            .where(AuditEvent.user_id == user_id)
            .order_by(AuditEvent.timestamp.desc(), AuditEvent.id.desc())
            .limit(clamped)
        ).all()
        return [
            AuditEventRecord(
                timestamp=(row.timestamp.isoformat() if row.timestamp else ""),
                action=row.action,
                root_path=row.root_path,
                summary=row.summary,
                files_count=row.files_count,
                status=row.status,
            )
            for row in rows
        ]


# -------------------------------------------------------------------------- rollback batches


def save_rollback_batch(
    user_id: str,
    apply_id: str,
    root_path: str,
    entries: list[dict[str, Any]],
) -> None:
    with session_scope() as session:
        session.add(
            RollbackBatch(
                apply_id=apply_id,
                user_id=user_id,
                root_path=str(root_path),
                entries_json=json.dumps(entries, ensure_ascii=False),
                created_at=utcnow(),
            )
        )
        stale_ids = session.scalars(
            select(RollbackBatch.apply_id)
            .where(RollbackBatch.user_id == user_id)
            .order_by(RollbackBatch.created_at.desc(), RollbackBatch.apply_id.desc())
            .offset(MAX_ROLLBACK_BATCHES)
        ).all()
        if stale_ids:
            session.execute(delete(RollbackBatch).where(RollbackBatch.apply_id.in_(stale_ids)))


def load_rollback_batch(user_id: str, apply_id: str) -> RollbackBatchRecord | None:
    with session_scope() as session:
        row = session.get(RollbackBatch, apply_id)
        if row is None or row.user_id != user_id:
            return None
        try:
            payload = json.loads(row.entries_json)
        except (TypeError, ValueError):
            return None
        if not isinstance(payload, list):
            return None

        files: list[RollbackFileRecord] = []
        for entry in payload:
            if not isinstance(entry, dict):
                continue
            file_path = entry.get("filePath")
            if not isinstance(file_path, str) or not file_path:
                continue
            created_dirs = entry.get("createdDirs")
            files.append(
                RollbackFileRecord(
                    file_path=file_path,
                    previous_content=entry.get("previousContent"),
                    written_sha256=str(entry.get("writtenSha256") or ""),
                    is_new_file=bool(entry.get("isNewFile")),
                    created_dirs=tuple(
                        str(item) for item in created_dirs if isinstance(item, str)
                    )
                    if isinstance(created_dirs, list)
                    else (),
                )
            )
        return RollbackBatchRecord(
            apply_id=row.apply_id,
            user_id=row.user_id,
            root_path=row.root_path,
            created_at=row.created_at,
            files=tuple(files),
        )


def delete_rollback_batch(apply_id: str) -> None:
    with session_scope() as session:
        session.execute(delete(RollbackBatch).where(RollbackBatch.apply_id == apply_id))


# ---------------------------------------------------------------------------------- workspaces


def remember_workspace(
    user_id: str,
    *,
    name: str,
    local_path: str,
    repo_url: str | None = None,
    branch: str | None = None,
) -> WorkspaceRecord:
    with session_scope() as session:
        row = session.scalar(
            select(Workspace).where(
                Workspace.user_id == user_id, Workspace.local_path == str(local_path)
            )
        )
        if row is None:
            row = Workspace(
                id=uuid.uuid4().hex,
                user_id=user_id,
                name=name,
                local_path=str(local_path),
                repo_url=repo_url,
                branch=branch,
                created_at=utcnow(),
            )
            session.add(row)
        else:
            row.name = name
            if repo_url:
                row.repo_url = repo_url
            if branch:
                row.branch = branch
        session.flush()
        return _to_workspace(row)


def record_workspace_scan(
    user_id: str, *, name: str, local_path: str, health_score: int | None
) -> WorkspaceRecord:
    with session_scope() as session:
        row = session.scalar(
            select(Workspace).where(
                Workspace.user_id == user_id, Workspace.local_path == str(local_path)
            )
        )
        now = utcnow()
        if row is None:
            row = Workspace(
                id=uuid.uuid4().hex,
                user_id=user_id,
                name=name,
                local_path=str(local_path),
                last_health_score=health_score,
                last_scanned_at=now,
                created_at=now,
            )
            session.add(row)
        else:
            row.name = name
            row.last_health_score = health_score
            row.last_scanned_at = now
        session.flush()
        return _to_workspace(row)


def list_workspaces(user_id: str) -> list[WorkspaceRecord]:
    with session_scope() as session:
        rows = session.scalars(
            select(Workspace)
            .where(Workspace.user_id == user_id)
            .order_by(Workspace.created_at.desc(), Workspace.id.desc())
        ).all()
        return [_to_workspace(row) for row in rows]


def get_workspace(user_id: str, workspace_id: str) -> WorkspaceRecord | None:
    with session_scope() as session:
        row = session.get(Workspace, workspace_id)
        if row is None or row.user_id != user_id:
            return None
        return _to_workspace(row)


def delete_workspace(user_id: str, workspace_id: str) -> WorkspaceRecord | None:
    with session_scope() as session:
        row = session.get(Workspace, workspace_id)
        if row is None or row.user_id != user_id:
            return None
        record = _to_workspace(row)
        session.delete(row)
        return record


# ---------------------------------------------------------------------------------- blueprints


def save_blueprint(
    user_id: str, *, workspace_path: str, name: str, stack: str, blueprint_json: str
) -> None:
    with session_scope() as session:
        row = session.scalar(
            select(SavedBlueprint).where(
                SavedBlueprint.user_id == user_id,
                SavedBlueprint.workspace_path == str(workspace_path),
            )
        )
        now = utcnow()
        if row is None:
            session.add(
                SavedBlueprint(
                    id=uuid.uuid4().hex,
                    user_id=user_id,
                    workspace_path=str(workspace_path),
                    name=name,
                    stack=stack,
                    blueprint_json=blueprint_json,
                    updated_at=now,
                )
            )
        else:
            row.name = name
            row.stack = stack
            row.blueprint_json = blueprint_json
            row.updated_at = now


def list_blueprints(user_id: str) -> list[BlueprintRecord]:
    with session_scope() as session:
        rows = session.scalars(
            select(SavedBlueprint)
            .where(SavedBlueprint.user_id == user_id)
            .order_by(SavedBlueprint.updated_at.desc())
        ).all()
        return [
            BlueprintRecord(
                id=row.id,
                workspace_path=row.workspace_path,
                name=row.name,
                stack=row.stack,
                blueprint_json=row.blueprint_json,
                updated_at=row.updated_at,
            )
            for row in rows
        ]


# --------------------------------------------------------------------------------- decisions

MAX_DECISIONS = 200
MAX_TRAINING_RECORDS = 500
DECISION_FEEDBACK_STATUSES = ("pending", "accepted", "overridden")


def _to_decision(row: ArchitectureDecisionRecord) -> DecisionRecord:
    return DecisionRecord(
        id=row.id,
        user_id=row.user_id,
        workspace_path=row.workspace_path,
        decision_type=row.decision_type,
        subject=row.subject,
        model=row.model,
        recommended_route=row.recommended_route,
        confidence=float(row.confidence or 0.0),
        latency_ms=int(row.latency_ms or 0),
        state_json=row.state_json,
        answers_json=row.answers_json,
        feedback_status=row.feedback_status,
        override_route=row.override_route,
        feedback_note=row.feedback_note,
        created_at=row.created_at,
        feedback_at=row.feedback_at,
    )


def save_decision_record(
    user_id: str,
    *,
    workspace_path: str,
    decision_type: str,
    subject: str,
    model: str,
    recommended_route: str,
    confidence: float,
    latency_ms: int,
    state_json: str,
    answers_json: str,
) -> DecisionRecord:
    """Persist one advisory System 1 decision for ``user_id`` only."""
    with session_scope() as session:
        row = ArchitectureDecisionRecord(
            id=uuid.uuid4().hex,
            user_id=user_id,
            workspace_path=str(workspace_path)[:2000],
            decision_type=decision_type[:40],
            subject=subject[:300],
            model=model[:120],
            recommended_route=recommended_route[:60],
            confidence=max(0.0, min(1.0, float(confidence))),
            latency_ms=max(0, int(latency_ms)),
            state_json=state_json,
            answers_json=answers_json,
            feedback_status="pending",
            created_at=utcnow(),
        )
        session.add(row)
        session.flush()
        return _to_decision(row)


def get_decision_record(user_id: str, adr_id: str) -> DecisionRecord | None:
    with session_scope() as session:
        row = session.get(ArchitectureDecisionRecord, adr_id)
        if row is None or row.user_id != user_id:
            return None
        return _to_decision(row)


def list_decision_records(
    user_id: str,
    *,
    workspace_path: str | None = None,
    decision_type: str | None = None,
    limit: int = 50,
) -> list[DecisionRecord]:
    clamped = max(1, min(int(limit), MAX_DECISIONS))
    with session_scope() as session:
        statement = select(ArchitectureDecisionRecord).where(
            ArchitectureDecisionRecord.user_id == user_id
        )
        if workspace_path:
            statement = statement.where(ArchitectureDecisionRecord.workspace_path == str(workspace_path))
        if decision_type:
            statement = statement.where(ArchitectureDecisionRecord.decision_type == decision_type)
        rows = session.scalars(
            statement.order_by(
                ArchitectureDecisionRecord.created_at.desc(),
                ArchitectureDecisionRecord.id.desc(),
            ).limit(clamped)
        ).all()
        return [_to_decision(row) for row in rows]


def update_decision_feedback(
    user_id: str,
    adr_id: str,
    *,
    status: str,
    override_route: str | None = None,
    note: str | None = None,
) -> DecisionRecord | None:
    """Record accept/override feedback. Another tenant's ADR is indistinguishable from unknown."""
    if status not in DECISION_FEEDBACK_STATUSES or status == "pending":
        raise ValueError(f"Unsupported decision feedback status: {status}")
    with session_scope() as session:
        row = session.get(ArchitectureDecisionRecord, adr_id)
        if row is None or row.user_id != user_id:
            return None
        row.feedback_status = status
        row.override_route = override_route[:60] if override_route else None
        row.feedback_note = note[:2000] if note else None
        row.feedback_at = utcnow()
        session.flush()
        return _to_decision(row)


def list_training_records(user_id: str, limit: int = MAX_TRAINING_RECORDS) -> list[DecisionRecord]:
    """Confirmed/overridden ADRs only: the feedback signal Laya continuous learning consumes."""
    clamped = max(1, min(int(limit), MAX_TRAINING_RECORDS))
    with session_scope() as session:
        rows = session.scalars(
            select(ArchitectureDecisionRecord)
            .where(
                ArchitectureDecisionRecord.user_id == user_id,
                ArchitectureDecisionRecord.feedback_status.in_(("accepted", "overridden")),
            )
            .order_by(
                ArchitectureDecisionRecord.created_at.desc(),
                ArchitectureDecisionRecord.id.desc(),
            )
            .limit(clamped)
        ).all()
        return [_to_decision(row) for row in rows]


# ------------------------------------------------------------------------------ user settings
SECRET_FIELD_HINTS = (
    "apikey",
    "api_key",
    "secret",
    "password",
    "credential",
    "private_key",
    "access_token",
    "refresh_token",
)
SECRET_FIELD_EXACT = {"token", "authtoken", "auth_token", "githubtoken", "github_token"}


def _contains_secret(value: Any) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).replace("-", "_").replace(" ", "").lower()
            if normalized in SECRET_FIELD_EXACT or any(
                hint in normalized for hint in SECRET_FIELD_HINTS
            ):
                return True
            if _contains_secret(item):
                return True
        return False
    if isinstance(value, list):
        return any(_contains_secret(item) for item in value)
    return False


def get_user_settings(user_id: str) -> tuple[dict[str, Any], datetime | None]:
    with session_scope() as session:
        row = session.get(UserSettings, user_id)
        if row is None:
            return {}, None
        try:
            payload = json.loads(row.settings_json)
        except (TypeError, ValueError):
            payload = {}
        return (payload if isinstance(payload, dict) else {}), row.updated_at


def save_user_settings(user_id: str, settings: dict[str, Any]) -> datetime:
    if _contains_secret(settings):
        raise ValueError("API keys and other secrets must never be stored in Kodo's database.")
    with session_scope() as session:
        row = session.get(UserSettings, user_id)
        now = utcnow()
        payload = json.dumps(settings, ensure_ascii=False, sort_keys=True)
        if row is None:
            session.add(UserSettings(user_id=user_id, settings_json=payload, updated_at=now))
        else:
            row.settings_json = payload
            row.updated_at = now
        return now


__all__ = [
    "AuditEventRecord",
    "BlueprintRecord",
    "DECISION_FEEDBACK_STATUSES",
    "DEFAULT_AUDIT_LIMIT",
    "DecisionRecord",
    "LOCAL_USER_ID",
    "MAX_AUDIT_EVENTS",
    "MAX_DECISIONS",
    "MAX_ROLLBACK_BATCHES",
    "MAX_TRAINING_RECORDS",
    "RollbackBatchRecord",
    "RollbackFileRecord",
    "UserRecord",
    "WorkspaceRecord",
    "delete_rollback_batch",
    "delete_workspace",
    "get_decision_record",
    "get_user",
    "get_user_settings",
    "get_workspace",
    "list_blueprints",
    "list_decision_records",
    "list_training_records",
    "list_workspaces",
    "load_rollback_batch",
    "read_audit_events",
    "record_audit_event",
    "record_workspace_scan",
    "remember_workspace",
    "save_blueprint",
    "save_decision_record",
    "save_rollback_batch",
    "save_user_settings",
    "seed_local_user",
    "update_decision_feedback",
    "upsert_github_user",
]
