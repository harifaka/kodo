"""Deterministic rule registry and scoring for the Phase 2 audit engine."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from app.audit.context import AuditContext
from app.models.ir import (
    AuditFinding,
    AuditReport,
    AuditSummary,
    ComponentNode,
    ComponentRelation,
    Severity,
)

Rule = Callable[[AuditContext], list[AuditFinding]]

_RULES: list[Rule] = []

_SEVERITY_ORDER = {Severity.ERROR: 0, Severity.WARNING: 1, Severity.INFO: 2}
_SEVERITY_WEIGHT = {Severity.ERROR: 10, Severity.WARNING: 4, Severity.INFO: 1}


def audit_rule(rule: Rule) -> Rule:
    """Register a rule. Import order is execution order; findings are re-sorted for determinism."""
    _RULES.append(rule)
    return rule


def registered_rules() -> tuple[Rule, ...]:
    return tuple(_RULES)


def run_audit(
    nodes: Iterable[ComponentNode],
    relations: Iterable[ComponentRelation],
) -> AuditReport:
    context = AuditContext.build(nodes, relations)
    findings = [finding for rule in _RULES for finding in rule(context)]
    findings.sort(key=lambda finding: (_SEVERITY_ORDER[finding.severity], finding.rule_id, finding.id))

    summary = AuditSummary(
        errors=sum(1 for finding in findings if finding.severity == Severity.ERROR),
        warnings=sum(1 for finding in findings if finding.severity == Severity.WARNING),
        info=sum(1 for finding in findings if finding.severity == Severity.INFO),
    )
    penalty = sum(_SEVERITY_WEIGHT[finding.severity] for finding in findings)
    score = max(0, min(100, 100 - penalty))

    return AuditReport(score=score, summary=summary, findings=findings)
