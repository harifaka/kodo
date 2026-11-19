"""MISSING_VALIDATION — request payloads accepted without any validation constraints."""

from __future__ import annotations

from app.audit.context import AuditContext, edge_key, type_identifiers
from app.audit.engine import audit_rule
from app.models.ir import AuditFinding, AuditRuleId, ComponentNode, Layer, Severity

# Bean Validation (Java) and DataAnnotations (.NET) markers the analyzers surface as annotations.
_VALIDATION_MARKERS = (
    "valid",
    "validated",
    "notnull",
    "notblank",
    "notempty",
    "size",
    "min(",
    "max(",
    "pattern",
    "email",
    "required",
    "stringlength",
    "range",
    "regularexpression",
    "minlength",
    "maxlength",
)

_DTO_SUFFIXES = ("dto", "request", "command", "input", "payload", "form")


def _is_dto_name(name: str) -> bool:
    return name.lower().endswith(_DTO_SUFFIXES)


def _has_validation(node: ComponentNode) -> bool:
    annotations = [annotation.lower() for annotation in node.annotations]
    for field in node.fields:
        annotations.extend(annotation.lower() for annotation in field.annotations)
    return any(marker in annotation for annotation in annotations for marker in _VALIDATION_MARKERS)


def _payload_types(controller: ComponentNode) -> set[str]:
    identifiers: set[str] = set()
    for method in controller.methods:
        for parameter in method.parameters:
            identifiers |= type_identifiers(parameter)
    return {identifier for identifier in identifiers if _is_dto_name(identifier)}


@audit_rule
def missing_validation(context: AuditContext) -> list[AuditFinding]:
    findings: list[AuditFinding] = []

    for controller in context.by_layer(Layer.CONTROLLER):
        for type_name in sorted(_payload_types(controller)):
            candidates = [
                node
                for node in context.by_name(type_name)
                if node.id != controller.id and not _has_validation(node)
            ]
            for payload in candidates:
                edge_keys = sorted(
                    {
                        edge_key(relation)
                        for relation in context.relations
                        if relation.source_id == controller.id and relation.target_id == payload.id
                    }
                )
                findings.append(
                    AuditFinding(
                        id=f"{AuditRuleId.MISSING_VALIDATION}:{controller.id}->{payload.id}",
                        rule_id=AuditRuleId.MISSING_VALIDATION,
                        severity=Severity.WARNING,
                        title=f"Missing validation: {payload.name}",
                        message=(
                            f"`{controller.name}` accepts `{payload.name}` as request input, but neither "
                            f"the payload nor its fields carry any validation annotation."
                        ),
                        suggestion=(
                            "Annotate the payload (`@NotNull`, `@Size`, `[Required]`, `[StringLength]`, …) "
                            "and validate it at the controller boundary (`@Valid` / `[ApiController]`)."
                        ),
                        node_ids=[controller.id, payload.id],
                        edge_keys=edge_keys,
                        file_path=payload.file_path,
                    )
                )

    return findings
