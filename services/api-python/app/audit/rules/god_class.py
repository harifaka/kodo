"""GOD_CLASS — components that accumulate too many responsibilities."""

from __future__ import annotations

from app.audit.context import AuditContext
from app.audit.engine import audit_rule
from app.models.ir import AuditFinding, AuditRuleId, NodeKind, Severity

MAX_FIELDS = 15
MAX_METHODS = 20
MAX_MEMBERS = 30

_ELIGIBLE_KINDS = frozenset({NodeKind.CLASS, NodeKind.RECORD, NodeKind.MODULE})


@audit_rule
def god_class(context: AuditContext) -> list[AuditFinding]:
    findings: list[AuditFinding] = []

    for node in context.nodes:
        if node.kind not in _ELIGIBLE_KINDS:
            continue

        field_count = len(node.fields)
        method_count = len(node.methods)
        member_count = field_count + method_count

        if (
            field_count < MAX_FIELDS
            and method_count < MAX_METHODS
            and member_count < MAX_MEMBERS
        ):
            continue

        findings.append(
            AuditFinding(
                id=f"{AuditRuleId.GOD_CLASS}:{node.id}",
                rule_id=AuditRuleId.GOD_CLASS,
                severity=Severity.WARNING,
                title=f"God class: {node.name}",
                message=(
                    f"`{node.name}` declares {field_count} fields and {method_count} methods "
                    f"({member_count} members), beyond the {MAX_MEMBERS}-member guideline."
                ),
                suggestion=(
                    "Split the component by responsibility: extract cohesive collaborators "
                    "(e.g. mapping, persistence and policy) and keep the class focused on one job."
                ),
                node_ids=[node.id],
                edge_keys=[],
                file_path=node.file_path,
            )
        )

    return findings
