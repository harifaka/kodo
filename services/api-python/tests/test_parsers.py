from __future__ import annotations

from app.analyzers.common import BASE_RELATION
from app.analyzers.java import parse_java
from app.analyzers.typescript import parse_script
from app.models.ir import Layer, NodeKind, RelationType


def test_java_extracts_spring_annotations_fields_and_constructor_dependencies() -> None:
    source = b"""
package com.acme.shop.controller;

import com.acme.shop.service.OrderService;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class OrderController {
    private final OrderService orderService;

    public OrderController(OrderService orderService) {
        this.orderService = orderService;
    }

    public String list() { return "ok"; }
}
"""
    result = parse_java("src/OrderController.java", source)

    assert len(result.nodes) == 1
    node = result.nodes[0]
    assert node.id == "com.acme.shop.controller.OrderController"
    assert node.layer == Layer.CONTROLLER
    assert node.annotations == ["@RestController"]
    assert [(field.name, field.type, field.visibility) for field in node.fields] == [
        ("orderService", "OrderService", "private")
    ]
    assert node.methods[0].name == "list"
    assert node.methods[0].return_type == "String"
    assert any(
        ref.target_name == "OrderService" and ref.relation == RelationType.DEPENDS_ON
        for ref in result.references
    )


def test_java_interface_inheritance_becomes_base_reference() -> None:
    source = b"""
package com.acme.shop.repository;

public interface OrderRepository extends JpaRepository<Order, Long> {
}
"""
    result = parse_java("OrderRepository.java", source)
    node = result.nodes[0]

    assert node.kind == NodeKind.INTERFACE
    assert any(ref.target_name == "JpaRepository" and ref.relation == BASE_RELATION for ref in result.references)


def test_typescript_named_import_links_to_target_file() -> None:
    source = b"""
import { OrderService } from '../services/order.service';

@Component({ selector: 'app-orders' })
export class OrdersComponent {
  private service: OrderService;
}
"""
    result = parse_script("src/components/orders.component.ts", source, {"src/services/order.service.ts"})

    assert result.nodes[0].annotations == ["@Component"]
    assert result.nodes[0].layer == Layer.COMPONENT
    assert any(
        ref.file_hint == "src/services/order.service.ts" and ref.target_name == "OrderService"
        for ref in result.references
    )


def test_typescript_interface_extends_becomes_base_reference() -> None:
    source = b"""
export interface OrderRepository extends CrudRepository<Order> {
  findAll(): Order[];
}
"""
    result = parse_script("src/models/order.repository.ts", source)

    assert result.nodes[0].kind == NodeKind.INTERFACE
    assert any(ref.target_name == "CrudRepository" and ref.relation == BASE_RELATION for ref in result.references)
