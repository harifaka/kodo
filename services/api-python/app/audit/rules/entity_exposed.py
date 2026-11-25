"""ENTITY_EXPOSED_IN_CONTROLLER — persistence entities leaking across the HTTP boundary."""

from __future__ import annotations

from app.audit.context import AuditContext, edge_key, signature_identifiers
from app.audit.engine import audit_rule
from app.models.ir import AuditFinding, AuditRuleId, Layer, Severity


def _entity_pairs(context: AuditContext) -> set[tuple[str, str]]:
    entities = context.by_layer(Layer.ENTITY)
    controllers = context.by_layer(Layer.CONTROLLER)
    entity_names = {entity.name: entity for entity in entities}
    pairs: set[tuple[str, str]] = set()

    outgoing: dict[str, list[str]] = {}
    for relation in context.relations:
        outgoing.setdefault(relation.source_id, []).append(relation.target_id)

    for controller in controllers:
        mentioned = signature_identifiers(controller)
        for name, entity in entity_names.items():
            if name in mentioned:
                pairs.add((controller.id, entity.id))

        for target_id in outgoing.get(controller.id, []):
            target = context.by_id.get(target_id)
            if target is not None and target.layer == Layer.ENTITY:
                pairs.add((controller.id, target.id))

    return pairs


@audit_rule
def entity_exposed_in_controller(context: AuditContext) -> list[AuditFinding]:
    findings: list[AuditFinding] = []

    for controller_id, entity_id in sorted(_entity_pairs(context)):
        controller = context.by_id[controller_id]
        entity = context.by_id[entity_id]
        edge_keys = sorted(
            {
                edge_key(relation)
                for relation in context.relations
                if relation.source_id == controller.id and relation.target_id == entity.id
            }
        )

        findings.append(
            AuditFinding(
                id=f"{AuditRuleId.ENTITY_EXPOSED_IN_CONTROLLER}:{controller.id}->{entity.id}",
                rule_id=AuditRuleId.ENTITY_EXPOSED_IN_CONTROLLER,
                severity=Severity.WARNING,
                title=f"Entity exposed in controller: {entity.name}",
                message=(
                    f"`{controller.name}` uses the persistence entity `{entity.name}` in its "
                    f"signature, so the database shape becomes the public HTTP contract."
                ),
                suggestion=(
                    "Introduce a DTO/response model, map the entity to it in the service layer, "
                    "and keep the entity inside the persistence boundary "
                    "(FastAPI `response_model=` / Django serializer)."
                ),
                node_ids=[controller.id, entity.id],
                edge_keys=edge_keys,
                file_path=controller.file_path,
            )
        )

    return findings
