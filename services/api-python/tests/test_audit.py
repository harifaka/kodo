from __future__ import annotations

from app.audit import registered_rules, run_audit
from app.models.ir import (
    ComponentField,
    ComponentMethod,
    ComponentNode,
    ComponentRelation,
    Layer,
    NodeKind,
    Severity,
    Stack,
)


def _node(
    node_id: str,
    name: str,
    layer: Layer,
    *,
    kind: NodeKind = NodeKind.CLASS,
    fields: tuple[tuple[str, str], ...] = (),
    methods: tuple[tuple[str, str, tuple[str, ...]], ...] = (),
    annotations: tuple[str, ...] = (),
) -> ComponentNode:
    return ComponentNode(
        id=node_id,
        name=name,
        stack=Stack.SPRING_BOOT,
        layer=layer,
        kind=kind,
        file_path=f"{name}.java",
        annotations=list(annotations),
        fields=[ComponentField(name=field_name, type=field_type) for field_name, field_type in fields],
        methods=[
            ComponentMethod(name=method_name, return_type=return_type, parameters=list(parameters))
            for method_name, return_type, parameters in methods
        ],
    )


def _edge(source: str, target: str, relation: str = "depends_on") -> ComponentRelation:
    return ComponentRelation(source_id=source, target_id=target, type=relation)


def test_all_six_rules_are_registered() -> None:
    assert len(registered_rules()) == 6


def test_controller_reaching_repository_is_a_layer_violation() -> None:
    controller = _node("shop.OrderController", "OrderController", Layer.CONTROLLER)
    repository = _node("shop.OrderRepository", "OrderRepository", Layer.REPOSITORY)

    report = run_audit([controller, repository], [_edge(controller.id, repository.id)])

    assert report.summary.errors == 1
    assert report.summary.warnings == 0
    assert report.score == 90
    finding = report.findings[0]
    assert finding.rule_id == "LAYER_VIOLATION"
    assert finding.severity == Severity.ERROR
    assert finding.id == "LAYER_VIOLATION:shop.OrderController->shop.OrderRepository"
    assert finding.node_ids == ["shop.OrderController", "shop.OrderRepository"]
    assert finding.edge_keys == ["shop.OrderController->shop.OrderRepository"]
    assert "OrderController" in finding.message and "OrderRepository" in finding.message
    assert finding.file_path == "OrderController.java"


def test_controller_to_service_is_allowed() -> None:
    controller = _node("shop.OrderController", "OrderController", Layer.CONTROLLER)
    service = _node("shop.OrderService", "OrderService", Layer.SERVICE)

    report = run_audit([controller, service], [_edge(controller.id, service.id)])

    assert report.findings == []
    assert report.score == 100


def test_lower_layer_depending_on_controller_is_a_violation() -> None:
    controller = _node("shop.OrderController", "OrderController", Layer.CONTROLLER)
    service = _node("shop.OrderService", "OrderService", Layer.SERVICE)

    report = run_audit([controller, service], [_edge(service.id, controller.id)])

    assert [finding.rule_id for finding in report.findings] == ["LAYER_VIOLATION"]
    assert report.findings[0].node_ids == ["shop.OrderService", "shop.OrderController"]


def test_circular_dependency_between_services() -> None:
    left = _node("shop.OrderService", "OrderService", Layer.SERVICE)
    right = _node("shop.PaymentService", "PaymentService", Layer.SERVICE)

    report = run_audit(
        [left, right],
        [_edge(left.id, right.id), _edge(right.id, left.id)],
    )

    assert report.summary.errors == 1
    finding = report.findings[0]
    assert finding.rule_id == "CIRCULAR_DEPENDENCY"
    assert finding.id == "CIRCULAR_DEPENDENCY:shop.OrderService,shop.PaymentService"
    assert finding.node_ids == ["shop.OrderService", "shop.PaymentService"]
    assert finding.edge_keys == [
        "shop.OrderService->shop.PaymentService",
        "shop.PaymentService->shop.OrderService",
    ]
    assert "OrderService" in finding.message and "PaymentService" in finding.message


def test_god_class_flags_excessive_members() -> None:
    fields = tuple((f"field{index}", "String") for index in range(31))
    blob = _node("shop.LegacyManager", "LegacyManager", Layer.OTHER, fields=fields)

    report = run_audit([blob], [])

    assert len(report.findings) == 1
    finding = report.findings[0]
    assert finding.rule_id == "GOD_CLASS"
    assert finding.severity == Severity.WARNING
    assert finding.id == "GOD_CLASS:shop.LegacyManager"
    assert "31 fields" in finding.message


def test_orphan_component_only_applies_to_core_layers() -> None:
    service = _node("shop.DeadService", "DeadService", Layer.SERVICE)
    entity = _node("shop.Order", "Order", Layer.ENTITY)

    report = run_audit([service, entity], [])

    assert [finding.rule_id for finding in report.findings] == ["ORPHAN_COMPONENT"]
    assert report.findings[0].severity == Severity.INFO
    assert report.findings[0].id == "ORPHAN_COMPONENT:shop.DeadService"
    assert report.score == 99


def test_entity_exposed_in_controller_via_field_type() -> None:
    controller = _node(
        "shop.OrderController",
        "OrderController",
        Layer.CONTROLLER,
        fields=(("order", "Order"),),
    )
    entity = _node("shop.Order", "Order", Layer.ENTITY)

    report = run_audit([controller, entity], [_edge(controller.id, entity.id, "references")])

    assert [finding.rule_id for finding in report.findings] == ["ENTITY_EXPOSED_IN_CONTROLLER"]
    finding = report.findings[0]
    assert finding.id == "ENTITY_EXPOSED_IN_CONTROLLER:shop.OrderController->shop.Order"
    assert finding.node_ids == ["shop.OrderController", "shop.Order"]
    assert finding.edge_keys == ["shop.OrderController->shop.Order"]
    assert finding.severity == Severity.WARNING


def test_missing_validation_on_request_payload() -> None:
    controller = _node(
        "shop.OrderController",
        "OrderController",
        Layer.CONTROLLER,
        methods=(("create", "String", ("CreateOrderRequest request",)),),
    )
    payload = _node(
        "shop.CreateOrderRequest",
        "CreateOrderRequest",
        Layer.OTHER,
        fields=(("customer", "String"),),
    )

    report = run_audit([controller, payload], [_edge(controller.id, payload.id)])

    findings = [finding for finding in report.findings if finding.rule_id == "MISSING_VALIDATION"]
    assert len(findings) == 1
    assert findings[0].id == "MISSING_VALIDATION:shop.OrderController->shop.CreateOrderRequest"
    assert findings[0].node_ids == ["shop.OrderController", "shop.CreateOrderRequest"]


def test_missing_validation_is_satisfied_by_field_annotations() -> None:
    controller = _node(
        "shop.OrderController",
        "OrderController",
        Layer.CONTROLLER,
        methods=(("create", "String", ("CreateOrderRequest request",)),),
    )
    payload = _node(
        "shop.CreateOrderRequest",
        "CreateOrderRequest",
        Layer.OTHER,
        fields=(("customer", "String"),),
    )
    payload.fields[0].annotations = ["@NotBlank"]

    report = run_audit([controller, payload], [_edge(controller.id, payload.id)])

    assert [finding.rule_id for finding in report.findings] == []


def test_report_is_deterministic_and_findings_are_severity_ordered() -> None:
    controller = _node("shop.OrderController", "OrderController", Layer.CONTROLLER)
    repository = _node("shop.OrderRepository", "OrderRepository", Layer.REPOSITORY)
    orphan = _node("shop.DeadService", "DeadService", Layer.SERVICE)
    left = _node("shop.AService", "AService", Layer.SERVICE)
    right = _node("shop.BService", "BService", Layer.SERVICE)

    nodes = [right, orphan, repository, left, controller]
    relations = [
        _edge(controller.id, repository.id),
        _edge(left.id, right.id),
        _edge(right.id, left.id),
    ]

    first = run_audit(nodes, relations)
    second = run_audit(list(reversed(nodes)), list(reversed(relations)))

    assert [finding.id for finding in first.findings] == [finding.id for finding in second.findings]
    assert [finding.severity for finding in first.findings] == [
        Severity.ERROR,
        Severity.ERROR,
        Severity.INFO,
    ]
    assert first.model_dump(by_alias=True) == second.model_dump(by_alias=True)


def test_score_never_drops_below_zero() -> None:
    faults = 12
    controller = _node("shop.OrderController", "OrderController", Layer.CONTROLLER)
    repositories = [
        _node(f"shop.Repo{index}", f"Repo{index}", Layer.REPOSITORY) for index in range(faults)
    ]

    report = run_audit(
        [controller, *repositories],
        [_edge(controller.id, repository.id) for repository in repositories],
    )

    assert len(report.findings) == faults
    assert report.score == 0
