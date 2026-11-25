"""Phase 12 — full Python stack support (FastAPI / Django / Flask).

Hermetic: the analyzer/patcher/generator tests need neither network nor a Docker daemon, and the
builder tests only inspect fixed configuration/commands/parsers.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import jsonschema
import pytest
import yaml
from fastapi.testclient import TestClient

from app.analyzers.common import BASE_RELATION
from app.analyzers.python_analyzer import parse_python
from app.analyzers.scanner import collect_files, detect_stacks
from app.audit import run_audit
from app.builders import diagnostics as builder_diagnostics
from app.builders import runner as builder_runner
from app.builders.models import BuildPatchInput
from app.config import DEFAULT_BUILDER_IMAGE_PYTHON, builder_image
from app.deploy import generator as deploy_generator
from app.generators import generate_files
from app.main import app
from app.models.blueprint import Blueprint
from app.models.ir import (
    ComponentField,
    ComponentNode,
    Layer,
    NodeKind,
    RelationType,
    Stack,
)
from app.patching.models import PatchField, PatchOperation
from app.patching.python_patcher import patch_python
from app.services.workspace import build_workspace

SCHEMA_PATH = Path(__file__).resolve().parents[3] / "packages" / "core-ir" / "schema.json"

requires_git = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")

MODELS_SOURCE = '''
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base."""


class Order(Base):
    """Persistence entity."""

    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str]
    total: Mapped[Decimal]
'''

SCHEMAS_SOURCE = '''
from pydantic import BaseModel, Field


class OrderRequest(BaseModel):
    """Request payload."""

    number: str = Field(min_length=1, max_length=200)
    total: Decimal = Field(ge=0)


class OrderResponse(BaseModel):
    """Response payload."""

    id: int
    number: str
'''

SERVICE_SOURCE = '''
from app.models.order import Order
from app.repositories.order_repository import OrderRepository
from app.schemas.order import OrderRequest, OrderResponse


class OrderService:
    def __init__(self, repository: OrderRepository) -> None:
        self._repository = repository

    def create(self, payload: OrderRequest) -> OrderResponse:
        entity = Order(number=payload.number)
        return self._to_response(self._repository.add(entity))

    def _to_response(self, entity: Order) -> OrderResponse:
        return OrderResponse(id=entity.id, number=entity.number)
'''

REPOSITORY_SOURCE = '''
from sqlalchemy.orm import Session

from app.models.order import Order


class OrderRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, entity: Order) -> Order:
        self._session.add(entity)
        return entity
'''

ROUTES_SOURCE = '''
from fastapi import APIRouter, Depends

from app.schemas.order import OrderRequest, OrderResponse
from app.services.order_service import OrderService

router = APIRouter(prefix="/api/orders", tags=["Order"])


def get_order_service() -> OrderService:
    raise NotImplementedError


@router.post("", response_model=OrderResponse)
def create_order(
    payload: OrderRequest,
    service: OrderService = Depends(get_order_service),
) -> OrderResponse:
    return service.create(payload)
'''

PYTHON_FILES = {
    "app/models/order.py": MODELS_SOURCE,
    "app/schemas/order.py": SCHEMAS_SOURCE,
    "app/services/order_service.py": SERVICE_SOURCE,
    "app/repositories/order_repository.py": REPOSITORY_SOURCE,
    "app/api/order_routes.py": ROUTES_SOURCE,
}


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def _write(tmp_path: Path, files: dict[str, str]) -> Path:
    root = tmp_path / "workspace"
    for rel_path, content in files.items():
        target = root / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="")
    return root


# --------------------------------------------------------------------------- analyzer


def test_analyzer_extracts_classes_fields_layers_and_relations() -> None:
    result = parse_python("app/models/order.py", MODELS_SOURCE.encode(), {"app/models/order.py"})
    by_name = {node.name: node for node in result.nodes}

    assert set(by_name) == {"Base", "Order"}
    assert by_name["Base"].layer == Layer.ENTITY
    assert by_name["Order"].layer == Layer.ENTITY
    assert by_name["Order"].stack == Stack.PYTHON
    assert by_name["Order"].fields[0].name == "id"
    assert by_name["Order"].fields[0].annotations == ["@mapped_column"]
    assert by_name["Order"].fields[1].type == "Mapped[str]"
    assert any(
        ref.target_name == "Base" and ref.relation == BASE_RELATION for ref in result.references
    )


def test_analyzer_emits_a_synthetic_router_component_with_handlers_and_dependencies() -> None:
    known = set(PYTHON_FILES)
    result = parse_python("app/api/order_routes.py", ROUTES_SOURCE.encode(), known)

    routers = [node for node in result.nodes if node.kind == NodeKind.ROUTER]
    assert len(routers) == 1
    router = routers[0]
    assert router.id == "app/api/order_routes.py"
    assert router.name == "OrderRoutes"
    assert router.layer == Layer.CONTROLLER
    assert router.stack == Stack.PYTHON
    assert "@APIRouter" in router.annotations
    assert "@router.post" in router.annotations
    assert [method.name for method in router.methods] == ["create_order"]

    depends = {
        (ref.target_name, ref.relation)
        for ref in result.references
        if ref.source_id == router.id and ref.relation == RelationType.DEPENDS_ON
    }
    assert ("OrderService", RelationType.DEPENDS_ON) in depends
    assert any(ref.target_name == "OrderRequest" for ref in result.references if ref.source_id == router.id)


def test_analyzer_classifies_services_repositories_and_dtos() -> None:
    known = set(PYTHON_FILES)
    service = parse_python("app/services/order_service.py", SERVICE_SOURCE.encode(), known)
    repository = parse_python(
        "app/repositories/order_repository.py", REPOSITORY_SOURCE.encode(), known
    )
    schemas = parse_python("app/schemas/order.py", SCHEMAS_SOURCE.encode(), known)

    service_node = next(node for node in service.nodes if node.name == "OrderService")
    assert service_node.layer == Layer.SERVICE
    assert ("repository", "OrderRepository") in [(field.name, field.type) for field in service_node.fields]
    assert any(
        ref.target_name == "OrderRepository" and ref.relation == RelationType.DEPENDS_ON
        for ref in service.references
    )

    repository_node = next(node for node in repository.nodes if node.name == "OrderRepository")
    assert repository_node.layer == Layer.REPOSITORY

    request = next(node for node in schemas.nodes if node.name == "OrderRequest")
    assert request.layer == Layer.OTHER  # the Core IR contract has no dedicated dto layer
    assert request.annotations == []
    assert request.fields[0].annotations == ["@Field"]


def test_analyzer_supports_django_views_and_flask_blueprints() -> None:
    django_source = b'''
from django.db import models
from django.views import View


class Order(models.Model):
    number = models.CharField(max_length=32)
    total = models.DecimalField(max_digits=12, decimal_places=2)


class OrderView(View):
    def get(self, request):
        return None
'''
    django = parse_python("shop/views.py", django_source, {"shop/views.py"})
    layers = {node.name: node.layer for node in django.nodes}
    assert layers["Order"] == Layer.ENTITY
    assert layers["OrderView"] == Layer.CONTROLLER
    entity = next(node for node in django.nodes if node.name == "Order")
    assert [field.type for field in entity.fields] == ["str", "Decimal"]

    flask_source = b'''
from flask import Blueprint

bp = Blueprint("orders", __name__)


@bp.route("/orders")
def list_orders():
    return []
'''
    flask = parse_python("shop/blueprints/orders.py", flask_source, {"shop/blueprints/orders.py"})
    router = next(node for node in flask.nodes if node.kind == NodeKind.ROUTER)
    assert router.layer == Layer.CONTROLLER
    assert "@Blueprint" in router.annotations
    assert "@bp.route" in router.annotations
    assert [method.name for method in router.methods] == ["list_orders"]

    django_function_views = b'''
from rest_framework.decorators import api_view


@api_view(["GET"])
def order_list(request):
    return []
'''
    function_views = parse_python("shop/views.py", django_function_views, {"shop/views.py"})
    function_router = next(node for node in function_views.nodes if node.kind == NodeKind.ROUTER)
    assert function_router.name == "ShopViews"
    assert "@api_view" in function_router.annotations
    assert [method.name for method in function_router.methods] == ["order_list"]


# --------------------------------------------------------------------------- scanner


def test_scanner_skips_python_noise_and_test_files(tmp_path: Path) -> None:
    root = tmp_path / "python-app"
    files = {
        "app/main.py": "print('ok')\n",
        "app/api/routes.py": "x = 1\n",
        ".venv/lib/site.py": "x = 1\n",
        "venv/lib/site.py": "x = 1\n",
        "app/__pycache__/main.cpython-313.pyc": "",
        "build/generated.py": "x = 1\n",
        "dist/generated.py": "x = 1\n",
        "pkg.egg-info/top_level.py": "x = 1\n",
        "tests/test_routes.py": "def test_x(): pass\n",
        "app/api/conftest.py": "x = 1\n",
        "pyproject.toml": "[project]\n",
    }
    for rel_path, content in files.items():
        target = root / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    scan = collect_files(root)

    assert sorted(scan.python) == ["app/api/routes.py", "app/main.py"]
    assert Stack.PYTHON in detect_stacks(scan)


def test_scan_endpoint_detects_python_and_matches_the_canonical_schema(
    client: TestClient, tmp_path: Path
) -> None:
    root = _write(tmp_path, PYTHON_FILES)
    (root / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    response = client.post("/api/v1/scan", json={"path": str(root)})

    assert response.status_code == 200, response.text
    body = response.json()
    jsonschema.validate(instance=body, schema=schema)
    assert "python" in body["detectedStacks"]
    assert {node["kind"] for node in body["nodes"]} <= {
        "class",
        "interface",
        "record",
        "enum",
        "module",
        "router",
    }
    assert any(node["kind"] == "router" for node in body["nodes"])
    assert body["audit"]["summary"]["errors"] == 0


def test_missing_validation_rule_recognises_pydantic_field_markers() -> None:
    controller = ComponentNode(
        id="routes.OrderRoutes",
        name="OrderRoutes",
        stack=Stack.PYTHON,
        layer=Layer.CONTROLLER,
        kind=NodeKind.ROUTER,
        file_path="routes.py",
        methods=[
            {
                "name": "create",
                "returnType": "OrderResponse",
                "parameters": ["payload: OrderRequest", "other: LooseRequest"],
            }
        ],
    )
    validated = ComponentNode(
        id="schemas.OrderRequest",
        name="OrderRequest",
        stack=Stack.PYTHON,
        layer=Layer.OTHER,
        kind=NodeKind.CLASS,
        file_path="schemas.py",
        fields=[ComponentField(name="number", type="str", annotations=["@Field"])],
    )
    unvalidated = validated.model_copy(
        update={"id": "schemas.LooseRequest", "name": "LooseRequest", "fields": []}
    )

    report = run_audit([controller, validated, unvalidated], [])

    ids = {finding.id for finding in report.findings}
    assert "MISSING_VALIDATION:routes.OrderRoutes->schemas.OrderRequest" not in ids
    assert "MISSING_VALIDATION:routes.OrderRoutes->schemas.LooseRequest" in ids


# --------------------------------------------------------------------------- patcher


PATCH_TARGET = '''"""Order models."""

from pydantic import BaseModel


class OrderRequest(BaseModel):
    """Request payload that must keep its docstring."""

    number: str

    def describe(self) -> str:
        """Hand-written method that must stay verbatim."""
        return self.number
'''


def test_patcher_adds_a_field_preserves_docstrings_and_adds_imports() -> None:
    outcome = patch_python(
        PATCH_TARGET,
        [
            PatchOperation(
                op="add_field",
                file_path="app/schemas/order.py",
                type_name="OrderRequest",
                field=PatchField(name="total", type="Decimal", annotations=["Field"]),
            )
        ],
    )

    assert outcome.applied == ["add field: OrderRequest.total"]
    assert '"""Request payload that must keep its docstring."""' in outcome.content
    assert '"""Hand-written method that must stay verbatim."""' in outcome.content
    assert "    total: Decimal = Field(...)\n" in outcome.content
    assert "from pydantic import Field" in outcome.content
    assert "from decimal import Decimal" in outcome.content


def test_patcher_updates_renames_and_removes_without_touching_methods() -> None:
    updated = patch_python(
        PATCH_TARGET,
        [
            PatchOperation(
                op="update_field",
                file_path="app/schemas/order.py",
                type_name="OrderRequest",
                original_name="number",
                field=PatchField(name="code", type="str"),
            )
        ],
    )
    assert "    code: str\n" in updated.content
    assert "return self.code" in updated.content
    assert updated.warnings and "Renamed 1 reference(s)" in updated.warnings[0]

    removed = patch_python(
        updated.content,
        [
            PatchOperation(
                op="remove_field",
                file_path="app/schemas/order.py",
                type_name="OrderRequest",
                field_name="code",
            )
        ],
    )
    assert "    code: str\n" not in removed.content
    assert "def describe(self) -> str:" in removed.content


def test_patcher_adds_and_removes_class_decorators() -> None:
    added = patch_python(
        PATCH_TARGET,
        [
            PatchOperation(
                op="add_annotation",
                file_path="app/schemas/order.py",
                type_name="OrderRequest",
                annotation="@dataclass",
            )
        ],
    )
    assert "\n@dataclass\nclass OrderRequest(BaseModel):" in added.content
    assert "from dataclasses import dataclass" in added.content

    removed = patch_python(
        added.content,
        [
            PatchOperation(
                op="remove_annotation",
                file_path="app/schemas/order.py",
                type_name="OrderRequest",
                annotation="@dataclass",
            )
        ],
    )
    assert "@dataclass" not in removed.content
    assert "class OrderRequest(BaseModel):" in removed.content


def test_patcher_degrades_gracefully_for_module_routers_and_unknown_types() -> None:
    router_source = 'x = APIRouter()\n\n\n@x.get("/ping")\ndef ping():\n    return 1\n'
    outcome = patch_python(
        router_source,
        [
            PatchOperation(
                op="add_field",
                file_path="app/api/routes.py",
                type_name="Routes",
                field=PatchField(name="value", type="str"),
            )
        ],
    )

    assert outcome.applied == []
    assert outcome.content == router_source
    assert "no class named 'Routes'" in outcome.warnings[0]


def test_dry_run_returns_python_patches_with_byte_exact_sha(client: TestClient, tmp_path: Path) -> None:
    root = _write(tmp_path, {"app/schemas/order.py": PATCH_TARGET})
    response = client.post(
        "/api/v1/dry-run",
        json={
            "rootPath": str(root),
            "operations": [
                {
                    "op": "add_field",
                    "filePath": "app/schemas/order.py",
                    "typeName": "OrderRequest",
                    "field": {"name": "status", "type": "str", "annotations": ["Field"]},
                }
            ],
        },
    )

    assert response.status_code == 200, response.text
    patch = response.json()["patches"][0]
    assert patch["language"] == "python"
    assert patch["originalSha256"] == hashlib.sha256(
        (root / "app/schemas/order.py").read_bytes()
    ).hexdigest()
    assert "status: str = Field(...)" in patch["proposedContent"]
    assert (root / "app/schemas/order.py").read_text(encoding="utf-8") == PATCH_TARGET


@requires_git
def test_python_apply_and_rollback_round_trip(client: TestClient, tmp_path: Path) -> None:
    root = _write(tmp_path, {"app/schemas/order.py": PATCH_TARGET})
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "kodo@example.com"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Kodo Tests"], cwd=root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=root, check=True)

    dry = client.post(
        "/api/v1/dry-run",
        json={
            "rootPath": str(root),
            "operations": [
                {
                    "op": "add_field",
                    "filePath": "app/schemas/order.py",
                    "typeName": "OrderRequest",
                    "field": {"name": "status", "type": "str", "annotations": ["Field"]},
                }
            ],
        },
    )
    assert dry.status_code == 200, dry.text
    patch = dry.json()["patches"][0]

    applied = client.post(
        "/api/v1/apply",
        json={
            "rootPath": str(root),
            "patches": [
                {
                    "filePath": patch["filePath"],
                    "expectedSha256": patch["originalSha256"],
                    "proposedContent": patch["proposedContent"],
                }
            ],
        },
    )
    assert applied.status_code == 200, applied.text
    assert "status: str = Field(...)" in (root / "app/schemas/order.py").read_text(encoding="utf-8")

    rollback = client.post(
        "/api/v1/apply/rollback",
        json={"applyId": applied.json()["applyId"], "force": False},
    )
    assert rollback.status_code == 200, rollback.text
    assert (root / "app/schemas/order.py").read_bytes() == PATCH_TARGET.encode("utf-8")


# --------------------------------------------------------------------------- generator


def _python_blueprint() -> Blueprint:
    return Blueprint.model_validate(
        {
            "schemaVersion": "1.0",
            "projectName": "Acme Shop",
            "stack": "python-fastapi",
            "basePackageOrNamespace": "app",
            "slices": [
                {
                    "name": "Customer",
                    "fields": [
                        {"name": "fullName", "type": "string", "required": True, "annotations": []},
                        {"name": "email", "type": "email", "required": True, "annotations": []},
                    ],
                    "dependsOnSlices": [],
                    "includeTests": True,
                },
                {
                    "name": "Order",
                    "fields": [
                        {"name": "number", "type": "string", "required": True, "annotations": []},
                        {"name": "total", "type": "decimal", "required": True, "annotations": []},
                    ],
                    "dependsOnSlices": ["Customer"],
                    "includeTests": True,
                },
            ],
        }
    )


def test_fastapi_generator_renders_slice_and_project_skeleton(client: TestClient, tmp_path: Path) -> None:
    root = tmp_path / "python"
    root.mkdir()

    response = client.post(
        "/api/v1/scaffold/dry-run",
        json={
            "rootPath": str(root),
            "blueprint": _python_blueprint().model_dump(by_alias=True, mode="json"),
            "includeProjectSkeleton": True,
            "saveBlueprint": False,
        },
    )

    assert response.status_code == 200, response.text
    patches = {patch["filePath"]: patch for patch in response.json()["patches"]}
    assert {
        "pyproject.toml",
        "app/__init__.py",
        "app/db.py",
        "app/main.py",
        "app/models/order.py",
        "app/schemas/order.py",
        "app/repositories/order_repository.py",
        "app/services/order_service.py",
        "app/api/order_routes.py",
        "tests/test_order_service.py",
    } <= set(patches)

    routes = patches["app/api/order_routes.py"]["proposedContent"]
    assert "APIRouter(prefix=\"/api/orders\"" in routes
    assert "OrderService" in routes
    assert "Order(" not in routes  # routers never touch entities

    service = patches["app/services/order_service.py"]["proposedContent"]
    assert "repository: OrderRepository" in service
    assert "customer_service: CustomerService" in service

    schemas = patches["app/schemas/order.py"]["proposedContent"]
    assert "Field(min_length=1, max_length=200)" in schemas
    assert "class OrderRequest(BaseModel):" in schemas


def test_generated_fastapi_project_scores_100(tmp_path: Path) -> None:
    root = tmp_path / "generated"
    for generated in generate_files(_python_blueprint(), include_project_skeleton=True):
        target = root / generated.file_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(generated.content, encoding="utf-8")

    workspace = asyncio.run(build_workspace(str(root)))

    assert workspace.detected_stacks == [Stack.PYTHON]
    assert workspace.warnings == []
    assert workspace.audit.summary.errors == 0
    assert workspace.audit.summary.warnings == 0
    assert workspace.audit.summary.info == 0, [finding.id for finding in workspace.audit.findings]
    assert workspace.audit.score == 100
    layers = {node.layer for node in workspace.nodes}
    assert {Layer.CONTROLLER, Layer.SERVICE, Layer.REPOSITORY, Layer.ENTITY} <= layers


def test_spec_prompt_covers_the_python_stack() -> None:
    from app.llm.prompts import spec_prompt
    from app.models.blueprint import BlueprintStack

    prompt = spec_prompt("Orders and customers.", BlueprintStack.PYTHON_FASTAPI, "Acme", "app")

    assert "python-fastapi" in prompt
    assert "FastAPI" in prompt and "Pydantic" in prompt


# --------------------------------------------------------------------------- deploy


def test_python_deploy_artifacts_are_multistage_nonroot_with_healthcheck(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='acme'\n", encoding="utf-8")

    artifacts = deploy_generator.generate_artifacts(
        stack="python",
        project_name="Acme API",
        app_port=None,
        backing_services=["postgres"],
        root=tmp_path,
    )

    dockerfile = next(item.content for item in artifacts.files if item.file_path == "Dockerfile")
    assert dockerfile.count("FROM python:3.12-slim") == 2
    assert "USER kodo" in dockerfile
    assert "EXPOSE 8000" in dockerfile
    assert "HEALTHCHECK" in dockerfile
    assert 'CMD ["uvicorn", "app.main:app"' in dockerfile
    assert "--chown=kodo:kodo" in dockerfile

    compose_text = next(item.content for item in artifacts.files if item.file_path == "docker-compose.yml")
    compose = yaml.safe_load(compose_text)
    app_service = compose["services"]["app"]
    assert app_service["environment"]["PYTHONUNBUFFERED"] == "1"
    assert "postgres:5432" in app_service["environment"]["DATABASE_URL"]
    assert app_service["healthcheck"]["test"][1].startswith("python -c")

    ignore = next(item.content for item in artifacts.files if item.file_path == ".dockerignore")
    assert ".venv" in ignore
    assert ".pytest_cache/" in ignore
    assert deploy_generator.detect_stack(tmp_path) == "python"


# --------------------------------------------------------------------------- builder


def test_python_builder_configuration_and_fixed_commands(tmp_path: Path) -> None:
    assert builder_image("python") == DEFAULT_BUILDER_IMAGE_PYTHON

    compile_only = builder_runner._command_for("python", run_tests=False, network_mode="none")
    tested = builder_runner._command_for("python", run_tests=True, network_mode="none")
    assert compile_only[:2] == ["sh", "-c"]
    assert "ruff check . --output-format concise" in compile_only[2]
    assert "mypy --ignore-missing-imports" in compile_only[2]
    assert "pytest -q" not in compile_only[2]
    assert "pytest -q" in tested[2]

    assert builder_runner.detect_build_stack(_write(tmp_path, {"pyproject.toml": "[project]\n"})) == "python"
    empty = tmp_path / "empty"
    empty.mkdir()
    assert builder_runner.detect_build_stack(empty) is None
    assert (
        builder_runner.detect_build_stack(
            empty, [BuildPatchInput(filePath="requirements.txt", proposedContent="fastapi\n", isNewFile=True)]
        )
        == "python"
    )


def test_python_builder_diagnostics_parse_ruff_and_mypy_output() -> None:
    output = (
        "app/main.py:3:8: F401 [*] `os` imported but unused\n"
        "app/models/order.py:10: error: Need type annotation for \"total\"  [var-annotated]\n"
        "app/services/order_service.py:5: note: Revealed type is \"builtins.str\"\n"
        "2 errors found\n"
    )

    parsed = builder_diagnostics.parse_diagnostics(output, "python")

    assert [(item.file_path, item.line, item.column, item.code) for item in parsed] == [
        ("app/main.py", 3, 8, "F401"),
        ("app/models/order.py", 10, 0, ""),
    ]
    assert all(item.severity == "error" for item in parsed)
    assert parsed[1].message.startswith("Need type annotation")
