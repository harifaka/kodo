"""LAYER_VIOLATION — dependencies that skip or invert an architectural boundary."""

from __future__ import annotations

from app.audit.context import AuditContext, edge_key
from app.audit.engine import audit_rule
from app.models.ir import (
    AuditFinding,
    AuditRuleId,
    ComponentNode,
    Layer,
    RelationType,
    Severity,
)

# Targets each layer may depend on. Anything else short-circuits a boundary.
_ALLOWED_TARGETS: dict[Layer, frozenset[Layer]] = {
    Layer.CONTROLLER: frozenset({Layer.CONTROLLER, Layer.SERVICE, Layer.VIEWMODEL, Layer.OTHER}),
    Layer.VIEW: frozenset({Layer.VIEW, Layer.VIEWMODEL, Layer.COMPONENT, Layer.OTHER}),
    Layer.VIEWMODEL: frozenset({Layer.VIEWMODEL, Layer.SERVICE, Layer.ENTITY, Layer.OTHER}),
    Layer.COMPONENT: frozenset({Layer.COMPONENT, Layer.SERVICE, Layer.OTHER}),
    Layer.SERVICE: frozenset(
        {Layer.SERVICE, Layer.REPOSITORY, Layer.ENTITY, Layer.VIEWMODEL, Layer.OTHER}
    ),
    Layer.REPOSITORY: frozenset({Layer.REPOSITORY, Layer.ENTITY, Layer.OTHER}),
    Layer.ENTITY: frozenset({Layer.ENTITY, Layer.OTHER}),
    Layer.OTHER: frozenset(Layer),
}

_SUGGESTIONS: dict[tuple[Layer, Layer], str] = {
    (Layer.CONTROLLER, Layer.REPOSITORY): (
        "Move the query behind a service and inject that service into the controller."
    ),
    (Layer.CONTROLLER, Layer.ENTITY): (
        "Map the entity to a DTO in the service layer and expose the DTO instead of the entity."
    ),
    (Layer.VIEW, Layer.SERVICE): (
        "Bind the view to a view model that calls the service, so the UI stays presentation-only."
    ),
    (Layer.VIEW, Layer.REPOSITORY): (
        "Introduce a view model between the view and the repository; views must not query persistence."
    ),
    (Layer.VIEW, Layer.ENTITY): (
        "Expose a view model that shapes entity data for display instead of binding entities directly."
    ),
    (Layer.VIEWMODEL, Layer.REPOSITORY): (
        "Route view model reads through a service so persistence stays behind the service layer."
    ),
    (Layer.REPOSITORY, Layer.SERVICE): (
        "Remove the upward dependency: the repository should expose data and let services compose behaviour."
    ),
}

_DEFAULT_SUGGESTION = (
    "Introduce an intermediate component in an allowed layer, or move the shared type to a lower layer."
)


def _suggestion(source: ComponentNode, target: ComponentNode) -> str:
    if (source.layer, target.layer) in _SUGGESTIONS:
        return _SUGGESTIONS[(source.layer, target.layer)]
    if source.layer == Layer.ENTITY:
        return "Entities must stay persistence-agnostic; move this collaborator use into a service."
    if target.layer == Layer.CONTROLLER:
        return "A lower layer must never depend on an inbound boundary; invert the call direction."
    return _DEFAULT_SUGGESTION


@audit_rule
def layer_violation(context: AuditContext) -> list[AuditFinding]:
    findings: list[AuditFinding] = []

    for relation in context.relations:
        if relation.type != RelationType.DEPENDS_ON:
            continue

        source = context.by_id.get(relation.source_id)
        target = context.by_id.get(relation.target_id)
        if source is None or target is None or source.layer == target.layer:
            continue

        if target.layer in _ALLOWED_TARGETS[source.layer]:
            continue

        findings.append(
            AuditFinding(
                id=f"{AuditRuleId.LAYER_VIOLATION}:{relation.source_id}->{relation.target_id}",
                rule_id=AuditRuleId.LAYER_VIOLATION,
                severity=Severity.ERROR,
                title=f"Layer violation: {source.name} reaches into {target.name}",
                message=(
                    f"`{source.name}` ({source.layer}) depends on `{target.name}` ({target.layer}). "
                    f"A {source.layer} component must not reach the {target.layer} layer directly."
                ),
                suggestion=_suggestion(source, target),
                node_ids=[source.id, target.id],
                edge_keys=[edge_key(relation)],
                file_path=source.file_path,
            )
        )

    return findings
