"""Read-only view over the Core IR that every audit rule shares."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from app.models.ir import ComponentNode, ComponentRelation, Layer, RelationType

DEPENDENCY_RELATIONS = frozenset(
    {
        RelationType.DEPENDS_ON,
        RelationType.INHERITS,
        RelationType.IMPLEMENTS,
    }
)

_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def edge_key(relation: ComponentRelation) -> str:
    return f"{relation.source_id}->{relation.target_id}"


def type_identifiers(text: str | None) -> set[str]:
    """Identifiers inside a rendered type/signature, e.g. `List<OrderRequest>` -> {List, OrderRequest}."""
    if not text:
        return set()
    return set(_IDENTIFIER.findall(text))


def signature_identifiers(node: ComponentNode) -> set[str]:
    """Every type identifier the node mentions in fields, parameters and return types."""
    identifiers: set[str] = set()
    for field in node.fields:
        identifiers |= type_identifiers(field.type)
    for method in node.methods:
        identifiers |= type_identifiers(method.return_type)
        for parameter in method.parameters:
            identifiers |= type_identifiers(parameter)
    return identifiers


@dataclass(frozen=True)
class AuditContext:
    nodes: tuple[ComponentNode, ...]
    relations: tuple[ComponentRelation, ...]
    by_id: dict[str, ComponentNode]

    @classmethod
    def build(
        cls,
        nodes: Iterable[ComponentNode],
        relations: Iterable[ComponentRelation],
    ) -> AuditContext:
        ordered_nodes = tuple(nodes)
        ordered_relations = tuple(relations)
        return cls(
            nodes=ordered_nodes,
            relations=ordered_relations,
            by_id={node.id: node for node in ordered_nodes},
        )

    def by_layer(self, *layers: Layer) -> list[ComponentNode]:
        wanted = set(layers)
        return [node for node in self.nodes if node.layer in wanted]

    def by_name(self, name: str) -> list[ComponentNode]:
        return [node for node in self.nodes if node.name == name]

    def outgoing(self, node_id: str) -> list[ComponentRelation]:
        return [relation for relation in self.relations if relation.source_id == node_id]

    def incoming(self, node_id: str) -> list[ComponentRelation]:
        return [relation for relation in self.relations if relation.target_id == node_id]
