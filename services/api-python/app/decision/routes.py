"""HTTP surface of the Phase 10 System 1 (Laya) decision layer.

Every route is tenant-scoped through Phase 8 auth. Anything that accepts a workspace root passes the
``enforce_workspace_access`` gate first. The routes only read in-memory IR/patches and write ADR rows
— they never write to a workspace. When System 1 is offline they answer HTTP 200 with
``available: false`` so the Audit panel and the diff preview keep working.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse

from app.auth.dependencies import CurrentUser
from app.db import repository
from app.decision.client import test_connection
from app.decision.config import resolve_config
from app.decision.models import (
    DecisionFeedbackRequest,
    DecisionListResponse,
    DecisionSummary,
    RouteTaskRequest,
    RouteTaskResponse,
    ScreenDiffRequest,
    ScreenDiffResponse,
    SystemOneTestResponse,
    TestConnectionRequest,
    TriageAuditRequest,
    TriageAuditResponse,
    TriageItemResponse,
)
from app.decision.schemas import questions_for
from app.decision.service import (
    DECISION_TYPE_AUDIT,
    DECISION_TYPE_DIFF,
    DECISION_TYPE_TASK,
    route_task,
    screen_diff,
    triage_audit,
)
from app.services import audit_log
from app.services.paths import enforce_workspace_access

router = APIRouter()


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _answers(raw: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _summary(record: repository.DecisionRecord) -> DecisionSummary:
    return DecisionSummary(
        id=record.id,
        workspace_path=record.workspace_path,
        decision_type=record.decision_type,
        subject=record.subject,
        model=record.model,
        recommended_route=record.recommended_route,
        confidence=record.confidence,
        latency_ms=record.latency_ms,
        feedback_status=record.feedback_status,
        override_route=record.override_route,
        feedback_note=record.feedback_note,
        created_at=_iso(record.created_at) or "",
        feedback_at=_iso(record.feedback_at),
        answers=_answers(record.answers_json),
    )


def _unknown_decision() -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={"code": "UNKNOWN_DECISION", "message": "No such decision record in your account."},
    )


@router.post(
    "/api/v1/decision/test-connection",
    response_model=SystemOneTestResponse,
    tags=["decision"],
)
async def test_system_one(
    _user: CurrentUser,
    request: TestConnectionRequest | None = None,
) -> SystemOneTestResponse:
    """Minimal one-question `/v1/systemone` ping with latency and provider hint."""
    cfg = resolve_config(request.system_one_config if request else None)
    probe = await test_connection(cfg)
    return SystemOneTestResponse(
        reachable=probe.reachable,
        latency_ms=probe.latency_ms,
        model=probe.model,
        provider_hint=probe.provider_hint,
        warning=probe.warning,
        error_code=probe.error_code,
    )


@router.post("/api/v1/decision/triage-audit", response_model=TriageAuditResponse, tags=["decision"])
async def triage_audit_route(
    request: TriageAuditRequest,
    user: CurrentUser,
) -> TriageAuditResponse:
    """Advisory Laya triage of up to 15 findings; one inspectable ADR per finding."""
    root = enforce_workspace_access(request.root_path, user)
    result = await triage_audit(
        user_id=user.id,
        root_path=str(root),
        workspace_ir=request.workspace_ir,
        finding_ids=request.finding_ids,
        override=request.system_one_config,
    )
    return TriageAuditResponse(
        available=result.available,
        model=result.model,
        latency_ms=result.latency_ms,
        items=[
            TriageItemResponse(
                adr_id=item.adr_id,
                finding_id=item.finding_id,
                risk_level=item.risk_level,
                recommended_route=item.recommended_route,
                confidence=item.confidence,
                escalated_to_system2=item.escalated_to_system2,
                priority=item.priority,
                answers=item.answers,
            )
            for item in result.items
        ],
        warning=result.warning,
    )


@router.post("/api/v1/decision/route-task", response_model=RouteTaskResponse, tags=["decision"])
async def route_task_route(
    request: RouteTaskRequest,
    user: CurrentUser,
) -> RouteTaskResponse:
    """System 1 -> System 2 router: deterministic AST/Builder vs DeepSeek vs human review."""
    root = enforce_workspace_access(request.root_path, user)
    result = await route_task(
        user_id=user.id,
        root_path=str(root),
        intent=request.intent,
        workspace_ir=request.workspace_ir,
        target_node_id=request.target_node_id,
        override=request.system_one_config,
    )
    return RouteTaskResponse(
        available=result.available,
        adr_id=result.adr_id,
        recommended_route=result.recommended_route,
        blast_radius=result.blast_radius,
        confidence=result.confidence,
        escalate_to_system2=result.escalate_to_system2,
        rationale=result.rationale,
        answers=result.answers,
        warning=result.warning,
    )


@router.post("/api/v1/decision/screen-diff", response_model=ScreenDiffResponse, tags=["decision"])
async def screen_diff_route(
    request: ScreenDiffRequest,
    user: CurrentUser,
) -> ScreenDiffResponse:
    """Advisory pre-diff safety gate. It never blocks the deterministic apply pipeline."""
    root = enforce_workspace_access(request.root_path, user)
    result = await screen_diff(
        user_id=user.id,
        root_path=str(root),
        patches=[patch.model_dump() for patch in request.patches],
        workspace_ir=request.workspace_ir,
        override=request.system_one_config,
    )
    return ScreenDiffResponse(
        available=result.available,
        adr_id=result.adr_id,
        status=result.status,
        confidence=result.confidence,
        flags=result.flags,
        answers=result.answers,
        advisory_note=result.advisory_note,
        warning=result.warning,
    )


@router.get("/api/v1/decisions", response_model=DecisionListResponse, tags=["decision"])
def list_decisions(
    user: CurrentUser,
    root_path: str | None = Query(default=None, alias="rootPath"),
    decision_type: str | None = Query(default=None, alias="decisionType"),
    limit: int = Query(default=50, ge=1, le=200),
) -> DecisionListResponse:
    """The current user's ADRs, newest first, optionally filtered by workspace and type."""
    try:
        records = repository.list_decision_records(
            user.id,
            workspace_path=root_path,
            decision_type=decision_type,
            limit=limit,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "DECISIONS_UNAVAILABLE", "message": f"Decision store unavailable: {exc}"},
        ) from exc
    return DecisionListResponse(decisions=[_summary(record) for record in records])


@router.post(
    "/api/v1/decisions/{adr_id}/feedback",
    response_model=DecisionSummary,
    tags=["decision"],
)
def decision_feedback(
    adr_id: str,
    request: DecisionFeedbackRequest,
    user: CurrentUser,
) -> DecisionSummary:
    """Accept or override one ADR. Another tenant's record is a 404, never a leak."""
    record = repository.get_decision_record(user.id, adr_id)
    if record is None:
        raise _unknown_decision()

    updated = repository.update_decision_feedback(
        user.id,
        adr_id,
        status=request.status,
        override_route=request.override_route,
        note=request.note,
    )
    if updated is None:
        raise _unknown_decision()

    summary = (
        f"{record.decision_type} · {record.subject} · recommended {record.recommended_route} "
        f"-> {request.status}"
    )
    if request.override_route:
        summary = f"{summary} ({request.override_route})"
    audit_log.record_event(
        audit_log.AUDIT_ACTION_DECISION_FEEDBACK,
        record.workspace_path,
        summary=summary,
        user_id=user.id,
    )
    return _summary(updated)


@router.get("/api/v1/decisions/export-training", tags=["decision"])
def export_training(user: CurrentUser) -> PlainTextResponse:
    """JSONL of accepted/overridden ADRs for local Laya calibration (no secrets, tenant-scoped)."""
    records = repository.list_training_records(user.id)
    lines: list[str] = []
    for record in records:
        answers = _answers(record.answers_json)
        confirmed = dict(answers)
        route_question = _route_question_id(record.decision_type)
        if route_question and record.override_route:
            previous = confirmed.get(route_question)
            confirmed[route_question] = {
                "answer": record.override_route,
                "probabilities": previous.get("probabilities", {}) if isinstance(previous, dict) else {},
                "confidence": 1.0,
                "source": "human_override",
            }
        line = {
            "state": _answers(record.state_json),
            "questions": [
                {
                    "id": question.id,
                    "type": question.type,
                    "text": question.text,
                    "options": [
                        {"key": option.key, "description": option.description} for option in question.options
                    ],
                }
                for question in questions_for(record.decision_type)
            ],
            "confirmed_answers": confirmed,
            "feedback_status": record.feedback_status,
            "note": record.feedback_note,
        }
        lines.append(json.dumps(line, ensure_ascii=False, separators=(",", ":"), sort_keys=False))

    body = "\n".join(lines)
    if body:
        body += "\n"
    return PlainTextResponse(
        body,
        media_type="application/x-ndjson",
        headers={"Content-Disposition": 'attachment; filename="kodo-laya-training.jsonl"'},
    )


def _route_question_id(decision_type: str) -> str | None:
    return {
        DECISION_TYPE_AUDIT: "fix_route",
        DECISION_TYPE_TASK: "execution_path",
        DECISION_TYPE_DIFF: "review_priority",
    }.get(decision_type)


__all__ = ["router"]
