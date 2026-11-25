"""Phase 4 — stack generators, blueprint persistence and create-only apply.

Covers vertical-slice rendering for all three stacks, the 100/100 self-audit bar, blueprint
save/load round-trips and the guarded create-only apply pipeline (FILE_EXISTS, nested folders,
rollback with empty-directory pruning).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import httpx
import jsonschema
import pytest
from fastapi.testclient import TestClient

from app.config import csharp_analyzer_url
from app.generators import generate_files, get_plugin, registry
from app.main import app
from app.models.blueprint import BLUEPRINT_FILE_NAME, Blueprint
from app.services.workspace import build_workspace

BLUEPRINT_SCHEMA_PATH = (
    Path(__file__).resolve().parents[3] / "packages" / "core-ir" / "blueprint.schema.json"
)

requires_git = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")

STACKS = {
    "spring-boot": "com.acme.shop",
    "csharp-wpf": "Acme.Desktop",
    "nodejs": "src",
    "python-fastapi": "app",
}

DEMO_SLICES = [
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
            {"name": "status", "type": "string", "required": True, "annotations": []},
        ],
        "dependsOnSlices": ["Customer"],
        "includeTests": True,
    },
    {
        "name": "Payment",
        "fields": [
            {"name": "reference", "type": "string", "required": True, "annotations": []},
            {"name": "amount", "type": "decimal", "required": True, "annotations": []},
            {"name": "method", "type": "string", "required": True, "annotations": []},
        ],
        "dependsOnSlices": ["Order"],
        "includeTests": True,
    },
]


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def _blueprint(stack: str, *, project: str = "Acme Shop", slices: list[dict] | None = None) -> dict:
    return {
        "schemaVersion": "1.0",
        "projectName": project,
        "stack": stack,
        "basePackageOrNamespace": STACKS[stack],
        "slices": slices if slices is not None else DEMO_SLICES,
    }


def _scaffold(
    client: TestClient,
    root: Path,
    blueprint: dict,
    *,
    skeleton: bool = True,
    save: bool = False,
) -> dict:
    response = client.post(
        "/api/v1/scaffold/dry-run",
        json={
            "rootPath": str(root),
            "blueprint": blueprint,
            "includeProjectSkeleton": skeleton,
            "saveBlueprint": save,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _apply(client: TestClient, root: Path, patches: list[dict], **flags: bool) -> httpx.Response:
    body = {
        "rootPath": str(root),
        "patches": [
            {
                "filePath": patch["filePath"],
                "expectedSha256": patch["originalSha256"],
                "proposedContent": patch["proposedContent"],
                "isNewFile": patch["isNewFile"],
            }
            for patch in patches
        ],
        "allowDirty": flags.get("allowDirty", False),
        "allowNonGit": flags.get("allowNonGit", True),
    }
    return client.post("/api/v1/apply", json=body)


def _patch_map(response: dict) -> dict[str, dict]:
    return {patch["filePath"]: patch for patch in response["patches"]}


def _csharp_reachable() -> bool:
    try:
        return httpx.get(f"{csharp_analyzer_url()}/health", timeout=1.0).status_code == 200
    except Exception:  # noqa: BLE001 - any transport error means "offline"
        return False


def _scan(root: Path):
    return asyncio.run(build_workspace(str(root)))


# --------------------------------------------------------------------------------------
# Registry and plugin contract
# --------------------------------------------------------------------------------------


def test_registry_exposes_all_four_stack_plugins() -> None:
    assert set(registry()) == {"spring-boot", "csharp-wpf", "nodejs", "python-fastapi"}
    assert get_plugin("spring-boot").display_name == "Spring Boot"
    assert get_plugin("python-fastapi").display_name == "FastAPI"
    for stack in STACKS:
        blueprint = Blueprint.model_validate(_blueprint(stack))
        files = generate_files(blueprint, include_project_skeleton=True)
        assert all(generated.content.strip() for generated in files)


# --------------------------------------------------------------------------------------
# Vertical slice + project skeleton generation
# --------------------------------------------------------------------------------------


def test_spring_boot_slice_and_project_skeleton(client: TestClient, tmp_path: Path) -> None:
    root = tmp_path / "spring"
    root.mkdir()
    patches = _patch_map(_scaffold(client, root, _blueprint("spring-boot")))

    base = "src/main/java/com/acme/shop"
    expected = {
        f"{base}/entity/OrderEntity.java",
        f"{base}/dto/OrderDto.java",
        f"{base}/mapper/OrderMapper.java",
        f"{base}/repository/OrderRepository.java",
        f"{base}/service/OrderService.java",
        f"{base}/controller/OrderController.java",
        "src/test/java/com/acme/shop/service/OrderServiceTest.java",
        "pom.xml",
        f"{base}/AcmeShopApplication.java",
        "src/main/resources/application.yml",
    }
    assert expected <= set(patches)
    assert all(patch["isNewFile"] is True for patch in patches.values())
    assert all(patch["originalContent"] == "" for patch in patches.values())
    assert all(patch["originalSha256"] is None for patch in patches.values())

    controller = patches[f"{base}/controller/OrderController.java"]["proposedContent"]
    assert "@RestController" in controller
    assert "OrderDto" in controller
    assert "OrderEntity" not in controller
    assert "OrderRepository" not in controller

    dto = patches[f"{base}/dto/OrderDto.java"]["proposedContent"]
    assert "public record OrderDto(" in dto
    assert "@NotBlank String number" in dto
    assert "@NotNull BigDecimal total" in dto
    assert "import jakarta.validation.constraints.NotBlank;" in dto

    service = patches[f"{base}/service/OrderService.java"]["proposedContent"]
    assert "private final CustomerService customerService;" in service
    assert "public OrderDto create(OrderDto dto)" in service
    # The cross-slice lookup returns CustomerDto, so the service must import that DTO.
    assert "import com.acme.shop.dto.CustomerDto;" in service
    assert "public CustomerDto findCustomer(Long id)" in service

    entity = patches[f"{base}/entity/OrderEntity.java"]["proposedContent"]
    assert "@Entity" in entity
    assert '@Table(name = "orders")' in entity
    assert '@Column(name = "total", nullable = false)' in entity

    pom = patches["pom.xml"]["proposedContent"]
    assert "spring-boot-starter-web" in pom
    assert "spring-boot-starter-validation" in pom


def test_spring_boot_skips_test_skeleton_when_disabled(client: TestClient, tmp_path: Path) -> None:
    root = tmp_path / "spring-no-tests"
    root.mkdir()
    slices = [{**DEMO_SLICES[0], "includeTests": False}]
    patches = _patch_map(_scaffold(client, root, _blueprint("spring-boot", slices=slices)))
    assert not any(path.endswith("Test.java") for path in patches)


def test_csharp_wpf_slice_and_project_skeleton(client: TestClient, tmp_path: Path) -> None:
    root = tmp_path / "wpf"
    root.mkdir()
    patches = _patch_map(_scaffold(client, root, _blueprint("csharp-wpf")))

    assert {
        "Models/OrderModel.cs",
        "Services/IOrderService.cs",
        "Services/OrderService.cs",
        "ViewModels/OrderViewModel.cs",
        "Views/OrderView.xaml",
        "Views/OrderView.xaml.cs",
        "Tests/OrderServiceTests.cs",
        "AcmeShop.csproj",
        "App.xaml",
        "App.xaml.cs",
    } <= set(patches)

    model = patches["Models/OrderModel.cs"]["proposedContent"]
    assert "[Required]" in model
    assert "using System.ComponentModel.DataAnnotations;" in model

    view_model = patches["ViewModels/OrderViewModel.cs"]["proposedContent"]
    assert "CommunityToolkit.Mvvm.ComponentModel" in view_model
    assert "[ObservableProperty]" in view_model
    assert "[RelayCommand]" in view_model
    assert "ICustomerService customerService" in view_model

    view = patches["Views/OrderView.xaml.cs"]["proposedContent"]
    assert "OrderViewModel" in view
    assert "DataContext = viewModel;" in view

    project = patches["AcmeShop.csproj"]["proposedContent"]
    assert "<TargetFramework>net8.0-windows</TargetFramework>" in project
    assert "<UseWPF>true</UseWPF>" in project
    assert "CommunityToolkit.Mvvm" in project


def test_nodejs_slice_and_project_skeleton(client: TestClient, tmp_path: Path) -> None:
    root = tmp_path / "node"
    root.mkdir()
    patches = _patch_map(_scaffold(client, root, _blueprint("nodejs")))

    assert {
        "src/modules/order/order.entity.ts",
        "src/modules/order/order.dto.ts",
        "src/modules/order/order.repository.ts",
        "src/modules/order/order.service.ts",
        "src/modules/order/order.controller.ts",
        "src/modules/order/order.service.spec.ts",
        "package.json",
        "tsconfig.json",
        "src/index.ts",
    } <= set(patches)

    dto = patches["src/modules/order/order.dto.ts"]["proposedContent"]
    assert "@IsNotEmpty()" in dto
    assert "export class CreateOrderDto {" in dto

    controller = patches["src/modules/order/order.controller.ts"]["proposedContent"]
    assert "export class OrderController {" in controller
    assert "OrderEntity" not in controller
    assert "OrderRepository" not in controller

    service = patches["src/modules/order/order.service.ts"]["proposedContent"]
    assert "private readonly customerService: CustomerService" in service
    # The cross-slice lookup returns the dependency's response DTO, so it must be imported.
    assert "import { CustomerResponseDto } from '../customer/customer.dto';" in service

    # strictPropertyInitialization: required fields use the definite assignment assertion so the
    # generated project passes `tsc --noEmit` in the Phase 9 builder.
    entity = patches["src/modules/order/order.entity.ts"]["proposedContent"]
    assert "number!: string;" in entity
    assert "number!: string;" in dto

    assert '"express"' in patches["package.json"]["proposedContent"]
    assert "experimentalDecorators" in patches["tsconfig.json"]["proposedContent"]


# --------------------------------------------------------------------------------------
# Self-audit quality bar: generated projects must score 100/100
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("stack", ["spring-boot", "nodejs", "python-fastapi"])
def test_generated_projects_score_100(client: TestClient, tmp_path: Path, stack: str) -> None:
    root = tmp_path / stack
    root.mkdir()
    blueprint = _blueprint(stack)
    response = _scaffold(client, root, blueprint)

    applied = _apply(client, root, response["patches"])
    assert applied.status_code == 200, applied.text
    assert len(applied.json()["createdFiles"]) == len(response["patches"])

    workspace = _scan(root)
    assert workspace.audit.summary.errors == 0
    assert workspace.audit.summary.warnings == 0
    assert workspace.audit.summary.info == 0, [finding.id for finding in workspace.audit.findings]
    assert workspace.audit.score == 100
    assert workspace.warnings == []

    layers = {node.layer for node in workspace.nodes}
    assert {"controller", "service", "repository", "entity"} <= layers


@pytest.mark.skipif(not _csharp_reachable(), reason="C# Roslyn analyzer is not running")
def test_generated_csharp_project_scores_100(client: TestClient, tmp_path: Path) -> None:
    root = tmp_path / "wpf-audit"
    root.mkdir()
    response = _scaffold(client, root, _blueprint("csharp-wpf"))

    applied = _apply(client, root, response["patches"])
    assert applied.status_code == 200, applied.text

    workspace = _scan(root)
    assert workspace.audit.summary.errors == 0
    assert workspace.audit.summary.warnings == 0
    assert workspace.audit.summary.info == 0, [finding.id for finding in workspace.audit.findings]
    assert workspace.audit.score == 100

    layers = {node.layer for node in workspace.nodes}
    assert {"service", "viewmodel", "view"} <= layers


# --------------------------------------------------------------------------------------
# Guarded create-only apply
# --------------------------------------------------------------------------------------


def test_create_only_apply_rejects_existing_files_as_a_whole_batch(
    client: TestClient,
    tmp_path: Path,
) -> None:
    root = tmp_path / "existing"
    root.mkdir()
    (root / "pom.xml").write_text("<project/>", encoding="utf-8")

    response = _scaffold(client, root, _blueprint("spring-boot"))
    conflicting = [patch for patch in response["patches"] if patch["conflict"]]
    assert [patch["filePath"] for patch in conflicting] == ["pom.xml"]
    assert response["warnings"]

    applied = _apply(client, root, response["patches"])
    assert applied.status_code == 409
    detail = applied.json()["detail"]
    assert detail["code"] == "FILE_EXISTS"
    assert detail["paths"] == ["pom.xml"]

    saved = sorted(path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file())
    assert saved == ["pom.xml"], "a rejected batch must not create any file"
    assert (root / "pom.xml").read_text(encoding="utf-8") == "<project/>"


@pytest.mark.parametrize("stack", ["spring-boot", "nodejs", "python-fastapi"])
def test_repeated_scaffold_reports_conflicts(client: TestClient, tmp_path: Path, stack: str) -> None:
    root = tmp_path / f"{stack}-twice"
    root.mkdir()
    blueprint = _blueprint(stack)
    first = _scaffold(client, root, blueprint)
    assert not any(patch["conflict"] for patch in first["patches"])
    assert _apply(client, root, first["patches"]).status_code == 200

    second = _scaffold(client, root, blueprint)
    assert all(patch["conflict"] for patch in second["patches"])
    assert _apply(client, root, second["patches"]).status_code == 409


@requires_git
def test_clean_apply_creates_nested_dirs_and_rollback_prunes_them(
    client: TestClient,
    tmp_path: Path,
) -> None:
    root = tmp_path / "scaffold-git"
    root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "kodo@example.com"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Kodo Tests"], cwd=root, check=True)
    (root / "README.md").write_text("# empty\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=root, check=True)

    response = _scaffold(client, root, _blueprint("nodejs"), save=True)
    applied = _apply(client, root, response["patches"])
    assert applied.status_code == 200, applied.text
    body = applied.json()
    assert len(body["createdFiles"]) == len(response["patches"])

    for patch in response["patches"]:
        assert (root / patch["filePath"]).is_file()
    assert (root / "src/modules/payment/payment.service.ts").is_file()

    rolled_back = client.post(
        "/api/v1/apply/rollback",
        json={"applyId": body["applyId"], "force": False},
    )
    assert rolled_back.status_code == 200, rolled_back.text
    assert len(rolled_back.json()["deletedFiles"]) == len(response["patches"])
    assert rolled_back.json()["restoredFiles"] == []

    for patch in response["patches"]:
        assert not (root / patch["filePath"]).exists()
    assert not (root / "src").exists(), "empty folders created by the batch must be pruned"
    assert root.is_dir()
    assert (root / "README.md").read_text(encoding="utf-8") == "# empty\n"


@requires_git
def test_rollback_deletes_only_new_files_and_restores_updated_blueprint(
    client: TestClient,
    tmp_path: Path,
) -> None:
    root = tmp_path / "scaffold-update"
    root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "kodo@example.com"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Kodo Tests"], cwd=root, check=True)

    first = _scaffold(client, root, _blueprint("nodejs"), skeleton=False, save=True)
    applied = _apply(client, root, first["patches"])
    assert applied.status_code == 200, applied.text
    original_blueprint = (root / BLUEPRINT_FILE_NAME).read_bytes()
    assert json_project_name(original_blueprint) == "Acme Shop"

    updated = _scaffold(
        client,
        root,
        _blueprint("nodejs", project="Acme Shop v2", slices=[]),
        skeleton=False,
        save=True,
    )
    blueprint_patch = _patch_map(updated)[BLUEPRINT_FILE_NAME]
    assert blueprint_patch["isNewFile"] is False
    assert blueprint_patch["originalSha256"] == hashlib.sha256(original_blueprint).hexdigest()

    second = _apply(client, root, updated["patches"], allowDirty=True)
    assert second.status_code == 200, second.text
    assert second.json()["createdFiles"] == []
    assert json_project_name((root / BLUEPRINT_FILE_NAME).read_bytes()) == "Acme Shop v2"

    rolled_back = client.post(
        "/api/v1/apply/rollback",
        json={"applyId": second.json()["applyId"], "force": False},
    )
    assert rolled_back.status_code == 200, rolled_back.text
    assert rolled_back.json()["deletedFiles"] == []
    assert rolled_back.json()["restoredFiles"] == [BLUEPRINT_FILE_NAME]
    assert (root / BLUEPRINT_FILE_NAME).read_bytes() == original_blueprint


def json_project_name(payload: bytes) -> str:
    return json.loads(payload.decode("utf-8"))["projectName"]


def test_rollback_refuses_when_new_file_changed(
    client: TestClient,
    tmp_path: Path,
) -> None:
    root = tmp_path / "changed"
    root.mkdir()
    response = _scaffold(client, root, _blueprint("nodejs"), skeleton=False)
    applied = _apply(client, root, response["patches"])
    assert applied.status_code == 200, applied.text

    target = root / "src/modules/order/order.controller.ts"
    target.write_text("// edited after apply\n", encoding="utf-8")

    blocked = client.post(
        "/api/v1/apply/rollback",
        json={"applyId": applied.json()["applyId"], "force": False},
    )
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "STALE_FILE"
    assert blocked.json()["detail"]["paths"] == ["src/modules/order/order.controller.ts"]
    assert target.is_file()


# --------------------------------------------------------------------------------------
# Blueprint persistence
# --------------------------------------------------------------------------------------


def test_blueprint_save_and_load_round_trip(client: TestClient, tmp_path: Path) -> None:
    root = tmp_path / "blueprint"
    root.mkdir()

    missing = client.get("/api/v1/blueprint", params={"root": str(root)})
    assert missing.status_code == 200
    assert missing.json() == {"exists": False, "blueprint": None, "warnings": []}

    blueprint = _blueprint("spring-boot")
    response = _scaffold(client, root, blueprint, skeleton=False, save=True)
    applied = _apply(client, root, response["patches"])
    assert applied.status_code == 200, applied.text

    saved = root / BLUEPRINT_FILE_NAME
    assert saved.is_file()
    loaded = client.get("/api/v1/blueprint", params={"root": str(root)})
    assert loaded.status_code == 200
    body = loaded.json()
    assert body["exists"] is True
    assert body["warnings"] == []
    assert body["blueprint"] == blueprint
    assert Blueprint.model_validate(body["blueprint"]).render() == saved.read_text(encoding="utf-8")


def test_invalid_blueprint_file_degrades_to_warning(client: TestClient, tmp_path: Path) -> None:
    root = tmp_path / "broken-blueprint"
    root.mkdir()
    (root / BLUEPRINT_FILE_NAME).write_text("{ not json", encoding="utf-8")

    response = client.get("/api/v1/blueprint", params={"root": str(root)})
    assert response.status_code == 200
    body = response.json()
    assert body["exists"] is True
    assert body["blueprint"] is None
    assert body["warnings"]


@pytest.mark.parametrize("stack", ["spring-boot", "csharp-wpf", "nodejs", "python-fastapi"])
def test_rendered_blueprint_matches_the_canonical_schema(stack: str) -> None:
    schema = json.loads(BLUEPRINT_SCHEMA_PATH.read_text(encoding="utf-8"))
    document = json.loads(Blueprint.model_validate(_blueprint(stack)).render())

    jsonschema.validate(instance=document, schema=schema)
    assert document["schemaVersion"] == "1.0"
    assert document["stack"] == stack


def test_blueprint_schema_rejects_unknown_versions() -> None:
    schema = json.loads(BLUEPRINT_SCHEMA_PATH.read_text(encoding="utf-8"))
    document = json.loads(Blueprint.model_validate(_blueprint("spring-boot")).render())
    document["schemaVersion"] = "2.0"

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=document, schema=schema)


def test_blueprint_rejects_unknown_dependency(client: TestClient, tmp_path: Path) -> None:
    root = tmp_path / "bad-dependency"
    root.mkdir()
    slices = [{**DEMO_SLICES[0], "dependsOnSlices": ["Ghost"]}]
    response = client.post(
        "/api/v1/scaffold/dry-run",
        json={
            "rootPath": str(root),
            "blueprint": _blueprint("spring-boot", slices=slices),
            "includeProjectSkeleton": False,
            "saveBlueprint": False,
        },
    )
    assert response.status_code == 422
    assert "Ghost" in response.text


def test_scaffold_rejects_unknown_stack(client: TestClient, tmp_path: Path) -> None:
    root = tmp_path / "bad-stack"
    root.mkdir()
    payload = _blueprint("spring-boot")
    payload["stack"] = "rust-axum"
    response = client.post(
        "/api/v1/scaffold/dry-run",
        json={
            "rootPath": str(root),
            "blueprint": payload,
            "includeProjectSkeleton": False,
            "saveBlueprint": False,
        },
    )
    assert response.status_code == 422
