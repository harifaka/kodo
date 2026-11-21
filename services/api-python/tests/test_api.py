from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app

JAVA_CONTROLLER = """
package com.acme.shop.controller;

import com.acme.shop.service.OrderService;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class OrderController {
    private final OrderService orderService;

    public OrderController(OrderService orderService) {
        this.orderService = orderService;
    }
}
"""

JAVA_SERVICE = """
package com.acme.shop.service;

import org.springframework.stereotype.Service;

@Service
public class OrderService {
}
"""


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def test_health_reports_analyzer_status(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["analyzers"]["csharp"]["url"].startswith("http")


def test_scan_returns_core_ir_with_relations(client: TestClient, tmp_path: Path) -> None:
    source_root = tmp_path / "shop" / "src" / "main" / "java" / "com" / "acme" / "shop"
    controller_dir = source_root / "controller"
    service_dir = source_root / "service"
    controller_dir.mkdir(parents=True)
    service_dir.mkdir(parents=True)
    (controller_dir / "OrderController.java").write_text(JAVA_CONTROLLER, encoding="utf-8")
    (service_dir / "OrderService.java").write_text(JAVA_SERVICE, encoding="utf-8")

    response = client.post("/api/v1/scan", json={"path": str(tmp_path / "shop")})

    assert response.status_code == 200
    workspace = response.json()
    assert workspace["detectedStacks"] == ["spring-boot"]
    assert [node["id"] for node in workspace["nodes"]] == [
        "com.acme.shop.controller.OrderController",
        "com.acme.shop.service.OrderService",
    ]
    assert workspace["relations"] == [
        {
            "sourceId": "com.acme.shop.controller.OrderController",
            "targetId": "com.acme.shop.service.OrderService",
            "type": "depends_on",
        }
    ]
    assert "classDiagram" in workspace["mermaidClassDiagram"]


def test_scan_rejects_unknown_root(client: TestClient, tmp_path: Path) -> None:
    response = client.post("/api/v1/scan", json={"path": str(tmp_path / "missing")})

    assert response.status_code == 400


def test_scan_returns_deterministic_audit_findings(client: TestClient, tmp_path: Path) -> None:
    package = tmp_path / "shop" / "src" / "main" / "java" / "com" / "acme" / "shop"
    (package / "repository").mkdir(parents=True)
    (package / "controller").mkdir(parents=True)
    (package / "repository" / "OrderRepository.java").write_text(
        "package com.acme.shop.repository;\npublic class OrderRepository {}\n",
        encoding="utf-8",
    )
    (package / "controller" / "OrderController.java").write_text(
        (
            "package com.acme.shop.controller;\n"
            "import com.acme.shop.repository.OrderRepository;\n"
            "import org.springframework.web.bind.annotation.RestController;\n"
            "@RestController\n"
            "public class OrderController {\n"
            "    private final OrderRepository repository;\n"
            "    public OrderController(OrderRepository repository) { this.repository = repository; }\n"
            "}\n"
        ),
        encoding="utf-8",
    )

    response = client.post("/api/v1/scan", json={"path": str(tmp_path / "shop")})

    assert response.status_code == 200
    audit = response.json()["audit"]
    assert audit["score"] < 100
    finding = next(item for item in audit["findings"] if item["ruleId"] == "LAYER_VIOLATION")
    assert finding["id"] == (
        "LAYER_VIOLATION:com.acme.shop.controller.OrderController"
        "->com.acme.shop.repository.OrderRepository"
    )
    assert finding["severity"] == "error"
    assert finding["edgeKeys"] == [
        "com.acme.shop.controller.OrderController->com.acme.shop.repository.OrderRepository"
    ]
    assert finding["filePath"] == "src/main/java/com/acme/shop/controller/OrderController.java"


def test_audit_preview_rescores_draft_relations(client: TestClient) -> None:
    nodes = [
        {
            "id": "com.acme.shop.controller.OrderController",
            "name": "OrderController",
            "stack": "spring-boot",
            "layer": "controller",
            "kind": "class",
            "filePath": "src/main/java/com/acme/shop/controller/OrderController.java",
        },
        {
            "id": "com.acme.shop.repository.OrderRepository",
            "name": "OrderRepository",
            "stack": "spring-boot",
            "layer": "repository",
            "kind": "class",
            "filePath": "src/main/java/com/acme/shop/repository/OrderRepository.java",
        },
    ]
    violation = {
        "sourceId": "com.acme.shop.controller.OrderController",
        "targetId": "com.acme.shop.repository.OrderRepository",
        "type": "depends_on",
    }

    with_violation = client.post("/api/v1/audit", json={"nodes": nodes, "relations": [violation]})
    without_violation = client.post("/api/v1/audit", json={"nodes": nodes, "relations": []})

    assert with_violation.status_code == 200
    assert without_violation.status_code == 200
    assert any(item["ruleId"] == "LAYER_VIOLATION" for item in with_violation.json()["findings"])
    assert not any(item["ruleId"] == "LAYER_VIOLATION" for item in without_violation.json()["findings"])
    assert without_violation.json()["score"] > with_violation.json()["score"]


def test_audit_preview_deduplicates_repeated_relations(client: TestClient) -> None:
    nodes = [
        {
            "id": "OrderController",
            "name": "OrderController",
            "stack": "spring-boot",
            "layer": "controller",
            "kind": "class",
            "filePath": "OrderController.java",
        },
        {
            "id": "OrderRepository",
            "name": "OrderRepository",
            "stack": "spring-boot",
            "layer": "repository",
            "kind": "class",
            "filePath": "OrderRepository.java",
        },
    ]
    violation = {"sourceId": "OrderController", "targetId": "OrderRepository", "type": "depends_on"}

    response = client.post(
        "/api/v1/audit",
        json={"nodes": nodes, "relations": [violation, violation]},
    )

    assert response.status_code == 200
    findings = [item for item in response.json()["findings"] if item["ruleId"] == "LAYER_VIOLATION"]
    assert len(findings) == 1


def test_audit_preview_ignores_relations_to_unknown_nodes(client: TestClient) -> None:
    nodes = [
        {
            "id": "OrderService",
            "name": "OrderService",
            "stack": "spring-boot",
            "layer": "service",
            "kind": "class",
            "filePath": "OrderService.java",
        }
    ]
    dangling = {"sourceId": "OrderService", "targetId": "Ghost", "type": "depends_on"}

    response = client.post("/api/v1/audit", json={"nodes": nodes, "relations": [dangling]})

    assert response.status_code == 200
    body = response.json()
    assert all(item["edgeKeys"] == [] for item in body["findings"])
    assert all("Ghost" not in item["nodeIds"] for item in body["findings"])


def test_audit_preview_rejects_unknown_relation_types(client: TestClient) -> None:
    response = client.post(
        "/api/v1/audit",
        json={"nodes": [], "relations": [{"sourceId": "a", "targetId": "b", "type": "teleports_to"}]},
    )

    assert response.status_code == 422


def test_file_inspector_returns_source(client: TestClient, tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "Order.java").write_text("class Order {}", encoding="utf-8")

    response = client.get("/api/v1/file", params={"root": str(root), "relPath": "Order.java"})

    assert response.status_code == 200
    body = response.json()
    assert body["content"] == "class Order {}"
    assert body["language"] == "java"


def test_file_inspector_blocks_path_traversal(client: TestClient, tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (tmp_path / "secret.txt").write_text("classified", encoding="utf-8")

    response = client.get("/api/v1/file", params={"root": str(root), "relPath": "../secret.txt"})

    assert response.status_code == 400
    assert "classified" not in response.text
