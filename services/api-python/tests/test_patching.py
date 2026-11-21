from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import csharp_analyzer_url
from app.main import app
from app.patching import csharp_patcher
from app.patching.csharp_patcher import patch_csharp
from app.patching.models import PatchField, PatchOperation

JAVA_ENTITY = """package com.acme.shop.entity;

public class Order {
    private String code;

    // Hand-written business rule - must stay verbatim.
    public boolean isPaid() {
        return code != null && !code.isBlank();
    }
}
"""

TYPESCRIPT_ENTITY = """export class Order {
  code: string;

  // Hand-written business rule - must stay verbatim.
  isPaid(): boolean {
    return this.code.length > 0;
  }
}
"""

CSHARP_ENTITY = """namespace Shop.Domain;

public class Order
{
    public decimal Amount { get; set; }

    // Hand-written business rule - must stay verbatim.
    public bool IsPaid() => Amount > 0;
}
"""


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def _roslyn_available() -> bool:
    try:
        response = httpx.get(f"{csharp_analyzer_url()}/health", timeout=1.5)
        return response.status_code == 200 and response.json().get("status") == "ok"
    except (httpx.HTTPError, ValueError):
        return False


def _write(root: Path, rel_path: str, content: str) -> Path:
    target = root / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


def _snapshot(paths: list[Path]) -> dict[Path, tuple[int, str]]:
    return {path: (path.stat().st_mtime_ns, path.read_text(encoding="utf-8")) for path in paths}


def test_dry_run_patches_java_and_preserves_hand_written_code(
    client: TestClient,
    tmp_path: Path,
) -> None:
    target = _write(tmp_path, "src/main/java/com/acme/shop/entity/Order.java", JAVA_ENTITY)
    before = _snapshot([target])

    response = client.post(
        "/api/v1/dry-run",
        json={
            "rootPath": str(tmp_path),
            "operations": [
                {
                    "op": "add_field",
                    "filePath": "src/main/java/com/acme/shop/entity/Order.java",
                    "typeName": "Order",
                    "field": {
                        "name": "total",
                        "type": "BigDecimal",
                        "visibility": "private",
                        "annotations": ["@NotNull", "@Column(nullable = false)"],
                    },
                },
                {
                    "op": "update_field",
                    "filePath": "src/main/java/com/acme/shop/entity/Order.java",
                    "typeName": "Order",
                    "originalName": "code",
                    "field": {
                        "name": "orderCode",
                        "type": "String",
                        "visibility": "private",
                        "annotations": ["@NotBlank"],
                    },
                },
                {
                    "op": "add_annotation",
                    "filePath": "src/main/java/com/acme/shop/entity/Order.java",
                    "typeName": "Order",
                    "annotation": '@Table(name = "orders")',
                },
            ],
        },
    )

    assert response.status_code == 200
    patch = response.json()["patches"][0]
    proposed = patch["proposedContent"]
    assert patch["language"] == "java"
    assert "import jakarta.validation.constraints.NotBlank;" in proposed
    assert "import jakarta.validation.constraints.NotNull;" in proposed
    assert "import java.math.BigDecimal;" in proposed
    assert "import jakarta.persistence.Table;" in proposed
    assert '@Table(name = "orders")' in proposed
    assert "@NotNull" in proposed
    assert "private BigDecimal total;" in proposed
    assert "private String orderCode;" in proposed
    assert "// Hand-written business rule - must stay verbatim." in proposed
    assert "public boolean isPaid() {" in proposed
    assert "return orderCode != null && !orderCode.isBlank();" in proposed
    assert patch["warnings"], "renaming a referenced field should ask for review"
    assert _snapshot([target]) == before, "dry-run must not modify the source file"


def test_dry_run_patches_typescript_class_and_interface(client: TestClient, tmp_path: Path) -> None:
    cls = _write(tmp_path, "src/order.ts", TYPESCRIPT_ENTITY)
    interface = _write(
        tmp_path,
        "src/order-dto.ts",
        """export interface OrderDto {
  code: string;

  // Hand-written contract comment.
  describe(): string;
}
""",
    )
    before = _snapshot([cls, interface])

    response = client.post(
        "/api/v1/dry-run",
        json={
            "rootPath": str(tmp_path),
            "operations": [
                {
                    "op": "add_field",
                    "filePath": "src/order.ts",
                    "typeName": "Order",
                    "field": {
                        "name": "total",
                        "type": "number",
                        "visibility": "public",
                        "annotations": ["@Column()", "@IsNumber()"],
                    },
                },
                {
                    "op": "add_field",
                    "filePath": "src/order-dto.ts",
                    "typeName": "OrderDto",
                    "field": {"name": "total", "type": "number", "annotations": []},
                },
                {
                    "op": "add_annotation",
                    "filePath": "src/order.ts",
                    "typeName": "Order",
                    "annotation": "@Entity()",
                },
            ],
        },
    )

    assert response.status_code == 200
    patches = {patch["filePath"]: patch for patch in response.json()["patches"]}

    class_patch = patches["src/order.ts"]
    assert "@Entity()" in class_patch["proposedContent"]
    assert "@Column()" in class_patch["proposedContent"]
    assert "@IsNumber()" in class_patch["proposedContent"]
    assert "public total: number;" in class_patch["proposedContent"]
    assert "// Hand-written business rule - must stay verbatim." in class_patch["proposedContent"]
    assert "isPaid(): boolean {" in class_patch["proposedContent"]
    assert "return this.code.length > 0;" in class_patch["proposedContent"]

    interface_patch = patches["src/order-dto.ts"]
    assert "total: number;" in interface_patch["proposedContent"]
    assert "// Hand-written contract comment." in interface_patch["proposedContent"]
    assert "describe(): string;" in interface_patch["proposedContent"]

    assert _snapshot([cls, interface]) == before, "dry-run must not modify the source files"


def test_dry_run_preserves_crlf_line_endings(client: TestClient, tmp_path: Path) -> None:
    _write(tmp_path, "order.ts", TYPESCRIPT_ENTITY.replace("\n", "\r\n"))

    response = client.post(
        "/api/v1/dry-run",
        json={
            "rootPath": str(tmp_path),
            "operations": [
                {
                    "op": "add_field",
                    "filePath": "order.ts",
                    "typeName": "Order",
                    "field": {"name": "total", "type": "number", "annotations": ["@Column()"]},
                },
            ],
        },
    )

    assert response.status_code == 200
    proposed = response.json()["patches"][0]["proposedContent"]
    assert "total: number;" in proposed
    assert "\r\n" in proposed
    assert "\n" not in proposed.replace("\r\n", ""), "inserted members must reuse the file's line endings"


def test_dry_run_removes_java_annotations_and_fields(client: TestClient, tmp_path: Path) -> None:
    source = """package com.acme.shop.entity;

public class Order {
    @Entity
    @Deprecated
    public static class Nested {
    }

    @Id
    @NotNull
    private Long id;

    private String code;

    // Hand-written business rule - must stay verbatim.
    public boolean isPaid() {
        return code != null && !code.isBlank();
    }
}
"""
    target = _write(tmp_path, "Order.java", source)
    before = _snapshot([target])

    response = client.post(
        "/api/v1/dry-run",
        json={
            "rootPath": str(tmp_path),
            "operations": [
                {
                    "op": "remove_annotation",
                    "filePath": "Order.java",
                    "typeName": "Nested",
                    "annotation": "@Deprecated",
                },
                {
                    "op": "remove_annotation",
                    "filePath": "Order.java",
                    "typeName": "Order",
                    "fieldName": "id",
                    "annotation": "@NotNull",
                },
                {"op": "remove_field", "filePath": "Order.java", "typeName": "Order", "fieldName": "code"},
            ],
        },
    )

    assert response.status_code == 200
    proposed = response.json()["patches"][0]["proposedContent"]
    assert "@Deprecated" not in proposed
    assert "@Entity" in proposed
    assert "@NotNull" not in proposed
    assert "@Id" in proposed
    assert "private String code;" not in proposed
    assert "// Hand-written business rule - must stay verbatim." in proposed
    assert "return code != null && !code.isBlank();" in proposed
    assert _snapshot([target]) == before


def test_dry_run_removes_typescript_decorators_and_properties(
    client: TestClient,
    tmp_path: Path,
) -> None:
    source = """@Entity()
export class Order {
  @Column()
  code: string;

  // Hand-written business rule - must stay verbatim.
  isPaid(): boolean {
    return this.code.length > 0;
  }
}
"""
    target = _write(tmp_path, "order.ts", source)
    before = _snapshot([target])

    response = client.post(
        "/api/v1/dry-run",
        json={
            "rootPath": str(tmp_path),
            "operations": [
                {
                    "op": "remove_annotation",
                    "filePath": "order.ts",
                    "typeName": "Order",
                    "annotation": "@Entity()",
                },
                {
                    "op": "remove_annotation",
                    "filePath": "order.ts",
                    "typeName": "Order",
                    "fieldName": "code",
                    "annotation": "@Column()",
                },
                {"op": "remove_field", "filePath": "order.ts", "typeName": "Order", "fieldName": "code"},
            ],
        },
    )

    assert response.status_code == 200
    proposed = response.json()["patches"][0]["proposedContent"]
    assert "@Entity()" not in proposed
    assert "@Column()" not in proposed
    assert "code: string;" not in proposed
    assert "// Hand-written business rule - must stay verbatim." in proposed
    assert "isPaid(): boolean {" in proposed
    assert "return this.code.length > 0;" in proposed
    assert _snapshot([target]) == before


@pytest.mark.skipif(not _roslyn_available(), reason="Roslyn analyzer container is not running")
def test_dry_run_patches_csharp_and_preserves_hand_written_code(
    client: TestClient,
    tmp_path: Path,
) -> None:
    target = _write(tmp_path, "Domain/Order.cs", CSHARP_ENTITY)
    before = _snapshot([target])

    response = client.post(
        "/api/v1/dry-run",
        json={
            "rootPath": str(tmp_path),
            "operations": [
                {
                    "op": "add_field",
                    "filePath": "Domain/Order.cs",
                    "typeName": "Order",
                    "field": {
                        "name": "Total",
                        "type": "decimal",
                        "visibility": "public",
                        "annotations": ["[Required]"],
                    },
                },
                {
                    "op": "add_annotation",
                    "filePath": "Domain/Order.cs",
                    "typeName": "Order",
                    "annotation": '[Table("Orders")]',
                },
            ],
        },
    )

    assert response.status_code == 200
    patch = response.json()["patches"][0]
    proposed = patch["proposedContent"]
    assert patch["language"] == "csharp"
    assert "using System.ComponentModel.DataAnnotations;" in proposed
    assert "using System.ComponentModel.DataAnnotations.Schema;" in proposed
    assert '[Table("Orders")]' in proposed
    assert "[Required]" in proposed
    assert "public decimal Total;" in proposed
    assert "// Hand-written business rule - must stay verbatim." in proposed
    assert "public bool IsPaid() => Amount > 0;" in proposed
    assert _snapshot([target]) == before, "dry-run must not modify the source file"


@pytest.mark.skipif(not _roslyn_available(), reason="Roslyn analyzer container is not running")
def test_csharp_update_field_renames_references(client: TestClient, tmp_path: Path) -> None:
    _write(tmp_path, "Domain/Order.cs", CSHARP_ENTITY)

    response = client.post(
        "/api/v1/dry-run",
        json={
            "rootPath": str(tmp_path),
            "operations": [
                {
                    "op": "update_field",
                    "filePath": "Domain/Order.cs",
                    "typeName": "Order",
                    "originalName": "Amount",
                    "field": {
                        "name": "TotalAmount",
                        "type": "decimal",
                        "visibility": "public",
                        "annotations": ["[Range(0, 100000)]"],
                    },
                }
            ],
        },
    )

    assert response.status_code == 200
    patch = response.json()["patches"][0]
    assert "public decimal TotalAmount { get; set; }" in patch["proposedContent"]
    assert "public bool IsPaid() => TotalAmount > 0;" in patch["proposedContent"]
    assert "// Hand-written business rule - must stay verbatim." in patch["proposedContent"]


@pytest.mark.skipif(not _roslyn_available(), reason="Roslyn analyzer container is not running")
def test_dry_run_removes_csharp_attribute_and_field(client: TestClient, tmp_path: Path) -> None:
    source = """using System.ComponentModel.DataAnnotations;

namespace Shop.Domain;

public class Order
{
    [Key]
    public Guid Id { get; set; }

    public decimal Amount { get; set; }

    // Hand-written business rule - must stay verbatim.
    public bool IsPaid() => Amount > 0;
}
"""
    target = _write(tmp_path, "Domain/Order.cs", source)
    before = _snapshot([target])

    response = client.post(
        "/api/v1/dry-run",
        json={
            "rootPath": str(tmp_path),
            "operations": [
                {
                    "op": "remove_annotation",
                    "filePath": "Domain/Order.cs",
                    "typeName": "Order",
                    "fieldName": "Id",
                    "annotation": "[Key]",
                },
                {
                    "op": "remove_field",
                    "filePath": "Domain/Order.cs",
                    "typeName": "Order",
                    "fieldName": "Amount",
                },
            ],
        },
    )

    assert response.status_code == 200
    patch = response.json()["patches"][0]
    assert "[Key]" not in patch["proposedContent"]
    assert "public decimal Amount { get; set; }" not in patch["proposedContent"]
    assert "// Hand-written business rule - must stay verbatim." in patch["proposedContent"]
    assert "public bool IsPaid() => Amount > 0;" in patch["proposedContent"]
    assert any("still referenced" in warning for warning in patch["warnings"])
    assert _snapshot([target]) == before


def test_dry_run_rejects_path_traversal(client: TestClient, tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    secret = (tmp_path / "secret.java").resolve()
    secret.write_text("class Secret { }", encoding="utf-8")

    response = client.post(
        "/api/v1/dry-run",
        json={
            "rootPath": str(root),
            "operations": [
                {
                    "op": "add_field",
                    "filePath": "../secret.java",
                    "typeName": "Secret",
                    "field": {"name": "leak", "type": "String", "annotations": []},
                }
            ],
        },
    )

    assert response.status_code == 400
    assert "traversal" in response.json()["detail"].lower()
    assert "class Secret" not in response.text
    assert secret.read_text(encoding="utf-8") == "class Secret { }"


def test_dry_run_degrades_when_roslyn_is_offline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_client = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    def factory(*args: object, **kwargs: object) -> httpx.AsyncClient:
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(csharp_patcher.httpx, "AsyncClient", factory)

    outcome = asyncio.run(
        patch_csharp(
            "Domain/Order.cs",
            CSHARP_ENTITY,
            [
                PatchOperation(
                    op="add_field",
                    file_path="Domain/Order.cs",
                    type_name="Order",
                    field=PatchField(name="Total", type="decimal", visibility="public", annotations=[]),
                )
            ],
        )
    )

    assert outcome.content == CSHARP_ENTITY
    assert any("unreachable" in warning for warning in outcome.warnings)
