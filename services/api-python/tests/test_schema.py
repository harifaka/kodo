from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest
from fastapi.testclient import TestClient

from app.main import app

SCHEMA_PATH = Path(__file__).resolve().parents[3] / "packages" / "core-ir" / "schema.json"

JAVA_SOURCE = """
package com.acme.shop.web;

import com.acme.shop.service.OrderService;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class OrderController {
    private final OrderService orderService;

    public OrderController(OrderService orderService) {
        this.orderService = orderService;
    }

    public String ping() { return "pong"; }
}
"""


@pytest.fixture()
def schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def test_scanned_workspace_matches_canonical_schema(schema: dict, tmp_path: Path) -> None:
    root = tmp_path / "shop"
    package = root / "src" / "main" / "java" / "com" / "acme" / "shop"
    (package / "web").mkdir(parents=True)
    (package / "web" / "OrderController.java").write_text(JAVA_SOURCE, encoding="utf-8")

    response = TestClient(app).post("/api/v1/scan", json={"path": str(root)})

    assert response.status_code == 200
    jsonschema.validate(instance=response.json(), schema=schema)


def test_schema_rejects_unknown_properties(schema: dict) -> None:
    instance = {
        "name": "demo",
        "rootPath": "/tmp/demo",
        "detectedStacks": ["unknown"],
        "nodes": [],
        "relations": [],
        "mermaidClassDiagram": "",
        "warnings": [],
        "unexpected": True,
    }

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=instance, schema=schema)
