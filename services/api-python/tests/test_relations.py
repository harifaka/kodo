from __future__ import annotations

from app.analyzers.common import BASE_RELATION, ReferenceCandidate
from app.models.ir import (
    ComponentNode,
    ComponentRelation,
    Layer,
    NodeKind,
    RelationType,
    Stack,
)
from app.services.relations import merge_relations, resolve_relations


def _node(node_id: str, name: str, kind: NodeKind, file_path: str) -> ComponentNode:
    return ComponentNode(
        id=node_id,
        name=name,
        stack=Stack.SPRING_BOOT,
        layer=Layer.OTHER,
        kind=kind,
        file_path=file_path,
    )


def test_base_reference_resolves_to_implements_for_classes() -> None:
    interface = _node("app.Port", "Port", NodeKind.INTERFACE, "Port.java")
    implementation = _node("app.Adapter", "Adapter", NodeKind.CLASS, "Adapter.java")

    relations = resolve_relations(
        [interface, implementation],
        [ReferenceCandidate("app.Adapter", "Port", BASE_RELATION)],
    )

    assert [(r.source_id, r.target_id, r.type) for r in relations] == [
        ("app.Adapter", "app.Port", RelationType.IMPLEMENTS)
    ]


def test_interface_extending_interface_inherits() -> None:
    parent = _node("app.Base", "Base", NodeKind.INTERFACE, "Base.java")
    child = _node("app.Derived", "Derived", NodeKind.INTERFACE, "Derived.java")

    relations = resolve_relations([parent, child], [ReferenceCandidate("app.Derived", "Base", BASE_RELATION)])

    assert relations[0].type == RelationType.INHERITS


def test_ambiguous_simple_names_are_not_resolved() -> None:
    a = _node("a.Order", "Order", NodeKind.CLASS, "a/Order.java")
    b = _node("b.Order", "Order", NodeKind.CLASS, "b/Order.java")

    relations = resolve_relations([a, b], [ReferenceCandidate("a.Order", "Order", "depends_on")])

    assert relations == []


def test_file_hint_resolves_import_to_target_file() -> None:
    service = _node(
        "web/src/services/order.ts#OrderService",
        "OrderService",
        NodeKind.CLASS,
        "web/src/services/order.ts",
    )
    component = _node("web/src/App.tsx#App", "App", NodeKind.MODULE, "web/src/App.tsx")

    relations = resolve_relations(
        [service, component],
        [
            ReferenceCandidate(
                "web/src/App.tsx#App",
                "OrderService",
                RelationType.REFERENCES,
                file_hint="web/src/services/order.ts",
            )
        ],
    )

    assert len(relations) == 1
    assert relations[0].target_id == "web/src/services/order.ts#OrderService"


def test_merge_relations_keeps_strongest_edge_per_pair() -> None:
    merged = merge_relations(
        [
            ComponentRelation(source_id="A", target_id="B", type=RelationType.REFERENCES),
            ComponentRelation(source_id="A", target_id="B", type=RelationType.IMPLEMENTS),
        ]
    )

    assert len(merged) == 1
    assert merged[0].type == RelationType.IMPLEMENTS
