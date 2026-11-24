"""System 1 (Laya) decision workflows: audit triage, task routing and pre-diff safety.

Everything here is **advisory**. System 1 never writes to disk, never generates code and never
replaces the deterministic Audit Engine, the Monaco diff review, the SHA-256 guarded apply or the
Phase 9 builder verification. When the local server is offline the workflows degrade to a clean
``available: false`` result instead of raising, so no scan or diff can ever be broken by it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from app.db import repository
from app.decision.client import SystemOneClient, SystemOneResponse
from app.decision.config import SystemOneOverride, resolve_config
from app.decision.errors import SystemOneError
from app.decision.schemas import (
    AUDIT_TRIAGE_QUESTIONS,
    DIFF_SAFETY_QUESTIONS,
    TASK_ROUTER_QUESTIONS,
)
from app.decision.state_packer import (
    dumps_state,
    pack_diff_state,
    pack_finding_state,
    pack_task_state,
)
from app.models.ir import AuditFinding, Severity, WorkspaceIR

DECISION_TYPE_AUDIT = "audit_triage"
DECISION_TYPE_TASK = "task_route"
DECISION_TYPE_DIFF = "diff_safety"

MAX_TRIAGE_FINDINGS = 15
ADVISORY_NOTE = (
    "Advisory only — the deterministic Audit Engine, the Monaco diff review, the SHA-256 guarded "
    "apply and the Phase 9 builder verification remain required before anything reaches disk."
)

_SEVERITY_RANK = {Severity.ERROR: 3, Severity.WARNING: 2, Severity.INFO: 1}
_RISK_RANK = {
    "critical_arch_risk": 3,
    "moderate_maintainability": 2,
    "low_boilerplate": 1,
    "uncertain": 2,
}
_DETERMINISTIC_ROUTES = {"deterministic_ast", "template_builder", "ignore_benign"}
_STATUS_RANK = {"pass": 0, "caution": 1, "high_risk": 2}


@dataclass(frozen=True)
class TriageItem:
    adr_id: str
    finding_id: str
    risk_level: str
    recommended_route: str
    confidence: float
    escalated_to_system2: bool
    priority: float
    answers: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TriageResult:
    available: bool
    model: str
    latency_ms: int
    items: list[TriageItem] = field(default_factory=list)
    warning: str | None = None


@dataclass(frozen=True)
class RouteResult:
    available: bool
    adr_id: str | None
    recommended_route: str
    blast_radius: str
    confidence: float
    escalate_to_system2: bool
    rationale: str
    answers: dict[str, Any] = field(default_factory=dict)
    warning: str | None = None


@dataclass(frozen=True)
class DiffScreenResult:
    available: bool
    adr_id: str | None
    status: str
    confidence: float
    flags: list[str] = field(default_factory=list)
    answers: dict[str, Any] = field(default_factory=dict)
    advisory_note: str = ADVISORY_NOTE
    warning: str | None = None


def _choose(response: SystemOneResponse, question_id: str, default: str) -> str:
    value = response.selected(question_id)
    return value if value else default


def _confidence(response: SystemOneResponse) -> float:
    """Conservative confidence: the weakest answered question decides whether Kodo may act."""
    values = [answer.confidence for answer in response.answers.values()]
    return min(values) if values else 0.0


def _answers_json(answers: dict[str, Any]) -> str:
    return json.dumps(answers, ensure_ascii=False, separators=(",", ":"), sort_keys=False)


def _select_findings(
    workspace_ir: WorkspaceIR,
    finding_ids: list[str] | None,
) -> list[AuditFinding]:
    """Deduplicate and prioritise deterministically: severity first, then rule, then finding id."""
    candidates = workspace_ir.audit.findings
    if finding_ids:
        wanted = set(finding_ids)
        candidates = [finding for finding in candidates if finding.id in wanted]
    ordered = sorted(
        candidates,
        key=lambda finding: (
            -_SEVERITY_RANK.get(finding.severity, 1),
            str(finding.rule_id),
            finding.id,
        ),
    )
    selected: list[AuditFinding] = []
    seen: set[str] = set()
    for finding in ordered:
        if finding.id in seen:
            continue
        seen.add(finding.id)
        selected.append(finding)
        if len(selected) >= MAX_TRIAGE_FINDINGS:
            break
    return selected


def _finding_subject(finding: AuditFinding, workspace_ir: WorkspaceIR) -> str:
    nodes_by_id = {node.id: node for node in workspace_ir.nodes}
    names = [nodes_by_id[node_id].name for node_id in finding.node_ids[:2] if node_id in nodes_by_id]
    if names:
        return f"{finding.rule_id}:{'->'.join(names)}"[:300]
    return f"{finding.rule_id}:{finding.id}"[:300]


def _gated_triage_route(route: str, needs_human: str, *, escalated: bool) -> str:
    if route == "uncertain":
        return "human_review"
    if not escalated:
        return route
    if needs_human == "yes_architectural_decision":
        return "human_review"
    if route in _DETERMINISTIC_ROUTES:
        return "deepseek_refactor"
    return route


async def triage_audit(
    *,
    user_id: str,
    root_path: str,
    workspace_ir: WorkspaceIR,
    finding_ids: list[str] | None = None,
    override: SystemOneOverride | None = None,
) -> TriageResult:
    """Triage up to 15 findings, persist one ADR per finding and rank them deterministically."""
    cfg = resolve_config(override)
    findings = _select_findings(workspace_ir, finding_ids)
    if not findings:
        return TriageResult(
            available=False,
            model=cfg.model,
            latency_ms=0,
            items=[],
            warning="No audit findings to triage for this workspace.",
        )

    client = SystemOneClient(cfg)
    items: list[TriageItem] = []
    escalated_count = 0
    total_latency = 0
    model_used = cfg.model
    warning: str | None = None

    for finding in findings:
        state = pack_finding_state(finding, workspace_ir)
        try:
            response = await client.ask(state, AUDIT_TRIAGE_QUESTIONS)
        except SystemOneError as exc:
            if not items:
                return TriageResult(
                    available=False,
                    model=cfg.model,
                    latency_ms=total_latency,
                    items=[],
                    warning=exc.warning(),
                )
            warning = f"System 1 stopped after {len(items)} finding(s): {exc.warning()}"
            break

        total_latency += response.latency_ms
        model_used = response.model or model_used
        answers = response.answers_payload()
        risk_level = _choose(response, "risk_level", "uncertain")
        raw_route = _choose(response, "fix_route", "human_review")
        needs_human = _choose(response, "needs_human_design", "uncertain")
        confidence = _confidence(response)
        escalated = response.abstain or confidence < cfg.auto_threshold
        route = _gated_triage_route(raw_route, needs_human, escalated=escalated)
        priority = round(
            _SEVERITY_RANK.get(finding.severity, 1) * 2 + _RISK_RANK.get(risk_level, 2) + confidence,
            3,
        )

        record = repository.save_decision_record(
            user_id,
            workspace_path=root_path,
            decision_type=DECISION_TYPE_AUDIT,
            subject=_finding_subject(finding, workspace_ir),
            model=response.model or cfg.model,
            recommended_route=route,
            confidence=confidence,
            latency_ms=response.latency_ms,
            state_json=dumps_state(state),
            answers_json=_answers_json(answers),
        )
        if escalated:
            escalated_count += 1
        items.append(
            TriageItem(
                adr_id=record.id,
                finding_id=finding.id,
                risk_level=risk_level,
                recommended_route=route,
                confidence=confidence,
                escalated_to_system2=escalated,
                priority=priority,
                answers=answers,
            )
        )

    items.sort(key=lambda item: (-item.priority, item.finding_id))
    if escalated_count:
        note = (
            f"{escalated_count} finding(s) were below the {cfg.auto_threshold:.2f} confidence "
            "threshold and were escalated instead of acted on automatically."
        )
        warning = f"{warning} {note}".strip() if warning else note
    return TriageResult(
        available=True,
        model=model_used,
        latency_ms=total_latency,
        items=items,
        warning=warning,
    )


async def route_task(
    *,
    user_id: str,
    root_path: str,
    intent: str,
    workspace_ir: WorkspaceIR,
    target_node_id: str | None = None,
    override: SystemOneOverride | None = None,
) -> RouteResult:
    """Recommend a deterministic / DeepSeek / human path for one engineering request."""
    cfg = resolve_config(override)
    state = pack_task_state(intent, workspace_ir, target_node_id)
    client = SystemOneClient(cfg)

    try:
        response = await client.ask(state, TASK_ROUTER_QUESTIONS)
    except SystemOneError as exc:
        return RouteResult(
            available=False,
            adr_id=None,
            recommended_route="human_review",
            blast_radius="uncertain",
            confidence=0.0,
            escalate_to_system2=False,
            rationale=(
                "System 1 is unavailable — deterministic AST/Builder tools and manual DeepSeek "
                "triggers remain fully usable; nothing is blocked."
            ),
            warning=exc.warning(),
        )

    answers = response.answers_payload()
    confidence = _confidence(response)
    raw_route = _choose(response, "execution_path", "uncertain")
    blast_radius = _choose(response, "blast_radius", "uncertain")
    escalate_answer = _choose(response, "escalate_to_system2", "escalate_human_review")
    gated = response.abstain or confidence < cfg.auto_threshold

    route = raw_route
    if route == "uncertain":
        route = "human_review"
    if gated:
        if response.abstain or route == "human_review":
            route = "human_review"
        else:
            route = "deepseek_reasoning"
    elif escalate_answer == "escalate_human_review":
        route = "human_review"
    elif escalate_answer == "escalate_system2_deepseek" and route in {
        "deterministic_ast",
        "template_builder",
    }:
        route = "deepseek_reasoning"

    escalate_to_system2 = route in {"deepseek_code", "deepseek_reasoning"}

    rationale = (
        f"Laya ({response.model or cfg.model}) chose {route} with {confidence:.0%} confidence "
        f"(blast radius: {blast_radius})."
    )
    if gated:
        rationale += (
            f" Confidence was below the {cfg.auto_threshold:.2f} auto-route threshold, so Kodo "
            f"escalated instead of acting automatically."
        )
    if route == "human_review":
        rationale += " An architect should confirm the approach before any AI call."
    elif escalate_to_system2:
        rationale += " System 2 DeepSeek is warranted; deterministic tools are not sufficient."
    else:
        rationale += " Deterministic tools can handle it without spending cloud tokens."

    record = repository.save_decision_record(
        user_id,
        workspace_path=root_path,
        decision_type=DECISION_TYPE_TASK,
        subject=f"Task: {' '.join(intent.split())[:200]}",
        model=response.model or cfg.model,
        recommended_route=route,
        confidence=confidence,
        latency_ms=response.latency_ms,
        state_json=dumps_state(state),
        answers_json=_answers_json(answers),
    )

    return RouteResult(
        available=True,
        adr_id=record.id,
        recommended_route=route,
        blast_radius=blast_radius,
        confidence=confidence,
        escalate_to_system2=escalate_to_system2,
        rationale=rationale,
        answers=answers,
    )


async def screen_diff(
    *,
    user_id: str,
    root_path: str,
    patches: list[Any],
    workspace_ir: WorkspaceIR | None = None,
    override: SystemOneOverride | None = None,
) -> DiffScreenResult:
    """Advisory pre-diff safety screen. Never blocks: the deterministic pipeline stays authoritative."""
    cfg = resolve_config(override)
    state = pack_diff_state(patches, workspace_ir)
    if not patches:
        return DiffScreenResult(
            available=False,
            adr_id=None,
            status="caution",
            confidence=0.0,
            warning="No proposed patches to screen.",
        )

    client = SystemOneClient(cfg)
    try:
        response = await client.ask(state, DIFF_SAFETY_QUESTIONS)
    except SystemOneError as exc:
        return DiffScreenResult(
            available=False,
            adr_id=None,
            status="caution",
            confidence=0.0,
            warning=exc.warning(),
        )

    answers = response.answers_payload()
    confidence = _confidence(response)
    logic = _choose(response, "logic_deletion_risk", "uncertain")
    layer = _choose(response, "layer_boundary_risk", "uncertain")
    priority = _choose(response, "review_priority", "careful_manual_review")

    flags: list[str] = []

    def _add_flag(flag: str) -> None:
        if flag not in flags:
            flags.append(flag)

    status = "pass"
    if logic == "possible_logic_loss":
        _add_flag("possible_logic_loss")
        status = "high_risk"
    elif logic == "uncertain":
        _add_flag("logic_risk_uncertain")
        status = _max_status(status, "caution")

    if layer == "possible_layer_violation":
        _add_flag("possible_layer_violation")
        status = "high_risk"
    elif layer == "uncertain":
        _add_flag("layer_boundary_uncertain")
        status = _max_status(status, "caution")

    if priority == "high_risk_block_advised":
        _add_flag("high_risk_block_advised")
        status = "high_risk"
    elif priority == "careful_manual_review":
        status = _max_status(status, "caution")

    if state.get("methodsRemoved"):
        _add_flag("removed_signatures")
        status = _max_status(status, "caution")
    if response.abstain:
        _add_flag("abstained")
        status = _max_status(status, "caution")
    if confidence < cfg.auto_threshold:
        _add_flag("low_confidence")
        status = _max_status(status, "caution")

    files_changed = int(state.get("filesChanged", len(patches)))
    record = repository.save_decision_record(
        user_id,
        workspace_path=root_path,
        decision_type=DECISION_TYPE_DIFF,
        subject=f"Diff: {files_changed} file{'s' if files_changed != 1 else ''}"[:300],
        model=response.model or cfg.model,
        recommended_route=status,
        confidence=confidence,
        latency_ms=response.latency_ms,
        state_json=dumps_state(state),
        answers_json=_answers_json(answers),
    )

    return DiffScreenResult(
        available=True,
        adr_id=record.id,
        status=status,
        confidence=confidence,
        flags=flags,
        answers=answers,
    )


def _max_status(current: str, candidate: str) -> str:
    return candidate if _STATUS_RANK.get(candidate, 0) > _STATUS_RANK.get(current, 0) else current


__all__ = [
    "ADVISORY_NOTE",
    "DECISION_TYPE_AUDIT",
    "DECISION_TYPE_DIFF",
    "DECISION_TYPE_TASK",
    "DiffScreenResult",
    "MAX_TRIAGE_FINDINGS",
    "RouteResult",
    "TriageItem",
    "TriageResult",
    "route_task",
    "screen_diff",
    "triage_audit",
]
