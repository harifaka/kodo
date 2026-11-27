from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.models.ir import (
    ComponentField,
    ComponentMethod,
    ComponentNode,
    ComponentRelation,
    Layer,
    NodeKind,
    Stack,
)
from app.services.mermaid import MAX_MEMBER_LENGTH, generate_class_diagram


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


def test_mermaid_route_renders_a_filtered_subset_in_memory() -> None:
    """Phase 11 sends the 1-hop/filtered Core IR subset here; the route is stateless."""
    client = TestClient(app)
    controller = _node("OrderController", "OrderController", Layer.CONTROLLER)
    service = _node("OrderService", "OrderService", Layer.SERVICE)
    repository = _node("OrderRepository", "OrderRepository", Layer.REPOSITORY)

    full = client.post(
        "/api/v1/mermaid",
        json={
            "nodes": [controller.model_dump(by_alias=True), service.model_dump(by_alias=True), repository.model_dump(by_alias=True)],
            "relations": [
                {"sourceId": "OrderController", "targetId": "OrderService", "type": "depends_on"},
                {"sourceId": "OrderService", "targetId": "OrderRepository", "type": "depends_on"},
                {"sourceId": "OrderService", "targetId": "Missing", "type": "depends_on"},
            ],
        },
    )

    assert full.status_code == 200, full.text
    body = full.json()
    assert body["nodeCount"] == 3
    assert body["relationCount"] == 2
    assert "OrderRepository" in body["diagram"]

    subset = client.post(
        "/api/v1/mermaid",
        json={
            "nodes": [controller.model_dump(by_alias=True), service.model_dump(by_alias=True)],
            "relations": [
                {"sourceId": "OrderController", "targetId": "OrderService", "type": "depends_on"},
                {"sourceId": "OrderService", "targetId": "OrderRepository", "type": "depends_on"},
            ],
        },
    )

    assert subset.status_code == 200, subset.text
    assert subset.json()["nodeCount"] == 2
    assert subset.json()["relationCount"] == 1
    assert "Repositories" not in subset.json()["diagram"]


# --- Phase 14: layered namespaces, direction and member density -------------------------------


def _layered_node(
    node_id: str,
    name: str,
    layer: Layer,
    *,
    kind: NodeKind = NodeKind.CLASS,
    fields: list[ComponentField] | None = None,
    methods: list[ComponentMethod] | None = None,
    annotations: list[str] | None = None,
) -> ComponentNode:
    return ComponentNode(
        id=node_id,
        name=name,
        stack=Stack.SPRING_BOOT,
        layer=layer,
        kind=kind,
        file_path=f"{name}.java",
        annotations=annotations or [],
        fields=fields or [],
        methods=methods or [],
    )


def _architecture_sample() -> list[ComponentNode]:
    return [
        _layered_node("view", "HomeView", Layer.VIEW),
        _layered_node("ctrl", "OrderController", Layer.CONTROLLER),
        _layered_node("router", "tasks_router", Layer.OTHER, kind=NodeKind.ROUTER),
        _layered_node("svc", "OrderService", Layer.SERVICE),
        _layered_node("repo", "OrderRepository", Layer.REPOSITORY),
        _layered_node("ent", "OrderEntity", Layer.ENTITY),
        # Python/TS payloads land on Layer.OTHER: the DTO name rule must still cluster them.
        _layered_node("dto", "OrderDto", Layer.OTHER),
        _layered_node("misc", "Helper", Layer.OTHER),
    ]


def test_layer_buckets_are_emitted_in_the_fixed_architectural_order() -> None:
    diagram = generate_class_diagram(_architecture_sample(), [])
    lines = diagram.splitlines()

    assert lines[0] == "classDiagram"
    assert lines[1].strip() == "direction TB"

    order = ["UI", "Controllers", "Services", "Repositories", "Entities", "DTOs", "Other"]
    positions = [lines.index(f"    namespace {bucket} {{") for bucket in order]
    assert positions == sorted(positions)

    for bucket in order:
        assert f"    namespace {bucket} {{" in lines

    # Sorted inside a bucket by (name.lower(), id) and DTOs clustered away from Other.
    controllers = _bucket_members(lines, "Controllers")
    assert controllers == ['class C1["OrderController"]', 'class C2["tasks_router"]']
    assert _bucket_members(lines, "DTOs") == ['class C6["OrderDto"]']
    assert _bucket_members(lines, "Other") == ['class C7["Helper"]']


def _bucket_members(lines: list[str], bucket: str) -> list[str]:
    start = lines.index(f"    namespace {bucket} {{")
    members: list[str] = []
    for line in lines[start + 1 :]:
        if line == "    }":
            break
        members.append(line.strip())
    return members


def test_empty_namespaces_are_omitted() -> None:
    diagram = generate_class_diagram([_layered_node("svc", "OrderService", Layer.SERVICE)], [])

    assert "namespace Services {" in diagram
    for bucket in ("UI", "Controllers", "Repositories", "Entities", "DTOs", "Other"):
        assert f"namespace {bucket}" not in diagram


def test_relations_are_emitted_once_after_every_namespace_block() -> None:
    nodes = _architecture_sample()
    relations = [
        ComponentRelation(source_id="svc", target_id="repo", type="depends_on"),
        ComponentRelation(source_id="ctrl", target_id="svc", type="depends_on"),
        ComponentRelation(source_id="svc", target_id="repo", type="depends_on"),
    ]

    diagram = generate_class_diagram(nodes, relations)
    lines = diagram.splitlines()

    last_namespace_close = max(index for index, line in enumerate(lines) if line == "    }")
    arrow_lines = [line.strip() for line in lines[last_namespace_close + 1 :] if "-->" in line]

    # Deterministic (sourceId, targetId, type) ordering, duplicates collapsed by the caller's view.
    assert arrow_lines == ["C1 --> C3", "C3 --> C4"]
    for line in lines[: last_namespace_close + 1]:
        assert "-->" not in line

    # One declaration per class even though relations and members follow the namespaces.
    for alias in ("C1", "C3", "C4"):
        assert diagram.count(f'class {alias}[') == 1
    assert diagram.count('class C6["OrderDto"]') == 1


def test_direction_and_flat_layout_options() -> None:
    nodes = _architecture_sample()

    left_to_right = generate_class_diagram(nodes, [], direction="LR")
    assert left_to_right.splitlines()[1].strip() == "direction LR"

    flat = generate_class_diagram(nodes, [], group_by_layer=False)
    assert "namespace" not in flat
    assert flat.splitlines()[1].strip() == "direction TB"
    # Flat output keeps the same deterministic bucket ordering (UI first, Other last).
    declarations = [line.strip() for line in flat.splitlines() if line.strip().startswith("class ")]
    assert declarations[0].startswith('class C0["HomeView"]')
    assert declarations[-1].startswith('class C7["Helper"]')

    invalid = generate_class_diagram(nodes, [], direction="diagonal")  # type: ignore[arg-type]
    assert invalid.splitlines()[1].strip() == "direction TB"


def test_member_detail_compact_and_names_only() -> None:
    node = _layered_node(
        "svc",
        "OrderService",
        Layer.SERVICE,
        annotations=["@Service"],
        fields=[
            ComponentField(name=f"field{index}", type="String", visibility="private")
            for index in range(5)
        ],
        methods=[ComponentMethod(name="create", return_type="OrderDto"), ComponentMethod(name="find")],
    )

    compact = generate_class_diagram([node], [], member_detail="compact")
    assert "    C0 : -String field0" in compact
    assert "    C0 : -String field1" in compact
    assert "    C0 : -String field2" in compact
    assert "field3" not in compact
    assert "    C0 : +2 more fields, 2 methods" in compact
    assert "    <<@Service>>" in compact

    names_only = generate_class_diagram([node], [], member_detail="names_only")
    assert 'class C0["OrderService"] {' in names_only
    assert "    <<@Service>>" in names_only
    assert " : " not in names_only
    assert "field0" not in names_only

    full = generate_class_diagram([node], [], member_detail="full")
    assert "    C0 : +create() OrderDto" in full
    assert "field4" in full


def test_python_subscripts_never_break_the_mermaid_grammar() -> None:
    """`Mapped[str]` / `dict[str, Any]` are invalid member text — subscripts are stripped."""
    node = _layered_node(
        "ent",
        "ArchitectureDecisionRecord",
        Layer.ENTITY,
        fields=[
            ComponentField(name="id", type="Mapped[str]", visibility="public"),
            ComponentField(name="state", type="dict[str, Any]", visibility="public"),
        ],
        methods=[
            ComponentMethod(
                name="list_workspaces",
                return_type="list[WorkspaceSummary]",
                parameters=["user: CurrentUser", "limit: int | None"],
            )
        ],
    )

    diagram = generate_class_diagram([node], [])
    members = [line.strip() for line in diagram.splitlines() if line.strip().startswith("C0 :")]

    assert "C0 : +Mapped id" in members
    assert "C0 : +dict state" in members
    assert "C0 : +list_workspaces(user, limit) list" in members
    assert all("[" not in member and "]" not in member for member in members)


def test_long_members_are_clipped_at_a_word_boundary() -> None:
    node = _layered_node(
        "ctrl",
        "AccountRoutes",
        Layer.CONTROLLER,
        methods=[
            ComponentMethod(
                name="put_user_settings_and_recalculate_quota",
                return_type="UserSettingsResponsePayloadEnvelope",
                parameters=[],
            )
        ],
    )

    diagram = generate_class_diagram([node], [])
    body = next(line for line in diagram.splitlines() if line.strip().startswith("C0 :")).strip()[len("C0 : ") :]

    assert body.endswith(")…")
    assert len(body) <= MAX_MEMBER_LENGTH


def test_mermaid_route_is_backward_compatible_and_honours_overrides() -> None:
    client = TestClient(app)
    nodes = _architecture_sample()
    payload = {
        "nodes": [node.model_dump(by_alias=True) for node in nodes],
        "relations": [{"sourceId": "ctrl", "targetId": "svc", "type": "depends_on"}],
    }

    legacy = client.post("/api/v1/mermaid", json=payload)
    explicit = client.post(
        "/api/v1/mermaid",
        json={**payload, "groupByLayer": True, "direction": "TB", "memberDetail": "full"},
    )
    assert legacy.status_code == 200, legacy.text
    assert explicit.status_code == 200, explicit.text
    assert legacy.json()["diagram"] == explicit.json()["diagram"]
    assert legacy.json()["diagram"] == generate_class_diagram(
        nodes,
        [ComponentRelation(source_id="ctrl", target_id="svc", type="depends_on")],
    )

    flat_lr = client.post(
        "/api/v1/mermaid",
        json={**payload, "groupByLayer": False, "direction": "LR", "memberDetail": "names_only"},
    )
    assert flat_lr.status_code == 200, flat_lr.text
    diagram = flat_lr.json()["diagram"]
    assert "direction LR" in diagram
    assert "namespace" not in diagram
    assert " : " not in diagram

    rejected = client.post("/api/v1/mermaid", json={**payload, "direction": "sideways"})
    assert rejected.status_code == 422
