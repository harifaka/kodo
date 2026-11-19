from __future__ import annotations

from app.models.ir import ComponentField, ComponentNode, ComponentRelation, Layer, NodeKind, Stack
from app.services.mermaid import generate_class_diagram


def _node(node_id: str, name: str, layer: Layer, fields: list[ComponentField] | None = None) -> ComponentNode:
    return ComponentNode(
        id=node_id,
        name=name,
        stack=Stack.SPRING_BOOT,
        layer=layer,
        kind=NodeKind.CLASS,
        file_path=f"{name}.java",
        fields=fields or [],
    )


def test_diagram_groups_layers_in_namespaces_and_draws_arrows() -> None:
    controller = _node("OrderController", "OrderController", Layer.CONTROLLER)
    service = _node(
        "OrderService",
        "OrderService",
        Layer.SERVICE,
        [ComponentField(name="repository", type="OrderRepository", visibility="private")],
    )

    diagram = generate_class_diagram(
        [controller, service],
        [ComponentRelation(source_id="OrderController", target_id="OrderService", type="depends_on")],
    )

    assert "classDiagram" in diagram
    assert "namespace Controllers {" in diagram
    assert "namespace Services {" in diagram
    assert 'class C0["OrderController"]' in diagram
    assert "C1 : -OrderRepository repository" in diagram
    assert "C0 --> C1" in diagram


def test_diagram_is_safe_for_empty_workspace() -> None:
    diagram = generate_class_diagram([], [])

    assert diagram.startswith("classDiagram")
    assert "No components discovered" in diagram


def test_diagram_drops_dangling_edges_and_dangerous_member_chars() -> None:
    node = _node(
        "A",
        "Weird",
        Layer.OTHER,
        [ComponentField(name="value", type="Map<String,String>", visibility="public", annotations=[])],
    )

    diagram = generate_class_diagram(
        [node],
        [ComponentRelation(source_id="A", target_id="Missing", type="depends_on")],
    )

    assert "Missing" not in diagram
    assert "C0 : +Map value" in diagram
