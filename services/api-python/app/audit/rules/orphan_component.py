"""ORPHAN_COMPONENT — backend components that nothing references and that reference nothing."""

from __future__ import annotations

from app.audit.context import AuditContext
from app.audit.engine import audit_rule
from app.models.ir import AuditFinding, AuditRuleId, Layer, Severity

# Data carriers and unclassified helpers are legitimately standalone; only flag core layers.
_AUDITED_LAYERS = frozenset(
    {Layer.CONTROLLER, Layer.SERVICE, Layer.REPOSITORY, Layer.VIEWMODEL}
)


@audit_rule
def orphan_component(context: AuditContext) -> list[AuditFinding]:
    connected: set[str] = set()
    for relation in context.relations:
        connected.add(relation.source_id)
        connected.add(relation.target_id)

    findings: list[AuditFinding] = []
    for node in context.nodes:
        if node.layer not in _AUDITED_LAYERS or node.id in connected:
            continue

        findings.append(
            AuditFinding(
                id=f"{AuditRuleId.ORPHAN_COMPONENT}:{node.id}",
                rule_id=AuditRuleId.ORPHAN_COMPONENT,
                severity=Severity.INFO,
                title=f"Orphan component: {node.name}",
                message=(
                    f"`{node.name}` ({node.layer}) has no relations to or from any other discovered "
                    f"component — nothing uses it and it uses nothing."
                ),
                suggestion=(
                    "Confirm the component is still wired into the application (or is a deliberate "
                    "entry point); otherwise delete it or connect it to the layer it belongs to."
                ),
                node_ids=[node.id],
                edge_keys=[],
                file_path=node.file_path,
            )
        )

    return findings
