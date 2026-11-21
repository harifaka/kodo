"""Phase 5 AI Copilot tests — deterministic, zero live network (httpx.MockTransport only)."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.llm.client import (
    parse_llm_json,
    set_transport_override,
    strip_code_fences,
    strip_reasoning,
)
from app.llm.config import LlmConfig
from app.llm.context_packer import pack_workspace
from app.main import app
from app.models.ir import (
    AuditReport,
    ComponentField,
    ComponentMethod,
    ComponentNode,
    WorkspaceIR,
)

Handler = Callable[[httpx.Request], httpx.Response]

CLOUD_CONFIG = {
    "baseUrl": "https://api.deepseek.com/v1",
    "apiKey": "sk-test-not-a-real-key",
    "codeModel": "deepseek-chat",
    "reasoningModel": "deepseek-reasoner",
    "timeoutSeconds": 30,
}

JAVA_CONTROLLER = """package com.acme.shop.controller;

import com.acme.shop.repository.OrderRepository;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class OrderController {
    private final OrderRepository repository;

    public OrderController(OrderRepository repository) {
        this.repository = repository;
    }

    public String list() {
        return "orders";
    }
}
"""

ORDER_FINDING = {
    "id": "LAYER_VIOLATION:com.acme.shop.controller.OrderController->com.acme.shop.repository.OrderRepository",
    "ruleId": "LAYER_VIOLATION",
    "severity": "error",
    "title": "Controller depends on a repository",
    "message": "OrderController depends on OrderRepository directly.",
    "suggestion": "Route the call through OrderService.",
    "nodeIds": ["com.acme.shop.controller.OrderController", "com.acme.shop.repository.OrderRepository"],
    "edgeKeys": ["com.acme.shop.controller.OrderController->com.acme.shop.repository.OrderRepository"],
    "filePath": "src/main/java/com/acme/shop/controller/OrderController.java",
}

VALID_BLUEPRINT = {
    "schemaVersion": "1.0",
    "projectName": "Invoicing",
    "stack": "spring-boot",
    "basePackageOrNamespace": "com.acme.invoicing",
    "slices": [
        {
            "name": "Customer",
            "fields": [
                {"name": "fullName", "type": "string", "required": True, "annotations": ["@NotBlank"]},
                {"name": "email", "type": "email", "required": True, "annotations": ["@Email"]},
            ],
            "dependsOnSlices": [],
            "includeTests": True,
        },
        {
            "name": "Invoice",
            "fields": [
                {"name": "number", "type": "string", "required": True, "annotations": ["@NotBlank"]},
                {"name": "amount", "type": "decimal", "required": True, "annotations": []},
            ],
            "dependsOnSlices": ["Customer"],
            "includeTests": True,
        },
    ],
}

INVALID_BLUEPRINT = {
    "schemaVersion": "1.0",
    "projectName": "Invoicing",
    "stack": "spring-boot",
    "basePackageOrNamespace": "com.acme.invoicing",
    "slices": [
        {"name": "invoice", "fields": [], "dependsOnSlices": ["Ghost"], "includeTests": True}
    ],
}


def _chat_response(payload: Any, status: int = 200) -> httpx.Response:
    return httpx.Response(
        status,
        json={"choices": [{"message": {"role": "assistant", "content": json.dumps(payload)}}]},
    )


@contextmanager
def mock_llm(handler: Handler) -> Iterator[list[httpx.Request]]:
    calls: list[httpx.Request] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return handler(request)

    set_transport_override(httpx.MockTransport(wrapped))
    try:
        yield calls
    finally:
        set_transport_override(None)


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture()
def workspace(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "shop"
    source = root / "src" / "main" / "java" / "com" / "acme" / "shop" / "controller" / "OrderController.java"
    source.parent.mkdir(parents=True)
    source.write_text(JAVA_CONTROLLER, encoding="utf-8")
    return root, source


def _workspace_payload(root: Path) -> dict[str, Any]:
    return {
        "name": "shop",
        "rootPath": str(root),
        "detectedStacks": ["spring-boot"],
        "nodes": [
            {
                "id": "com.acme.shop.controller.OrderController",
                "name": "OrderController",
                "stack": "spring-boot",
                "layer": "controller",
                "kind": "class",
                "filePath": "src/main/java/com/acme/shop/controller/OrderController.java",
                "annotations": ["@RestController"],
                "fields": [{"name": "repository", "type": "OrderRepository", "annotations": []}],
                "methods": [{"name": "list", "returnType": "String", "parameters": []}],
            },
            {
                "id": "com.acme.shop.repository.OrderRepository",
                "name": "OrderRepository",
                "stack": "spring-boot",
                "layer": "repository",
                "kind": "class",
                "filePath": "src/main/java/com/acme/shop/repository/OrderRepository.java",
                "fields": [],
                "methods": [],
            },
        ],
        "relations": [
            {
                "sourceId": "com.acme.shop.controller.OrderController",
                "targetId": "com.acme.shop.repository.OrderRepository",
                "type": "depends_on",
            }
        ],
        "mermaidClassDiagram": "classDiagram",
        "warnings": [],
        "audit": {
            "score": 90,
            "summary": {"errors": 1, "warnings": 0, "info": 0},
            "findings": [ORDER_FINDING],
        },
    }


# --------------------------------------------------------------------------------------------
# JSON parsing
# --------------------------------------------------------------------------------------------


def test_parser_strips_reasoning_and_code_fences() -> None:
    raw = '<think>Let me reason about the schema first.</think>\n```json\n{"slices": [{"name": "Invoice"}]}\n```'

    assert strip_reasoning(raw).startswith("```json")
    assert strip_code_fences(strip_reasoning(raw)) == '{"slices": [{"name": "Invoice"}]}'
    assert parse_llm_json(raw) == {"slices": [{"name": "Invoice"}]}


def test_parser_handles_bare_fence_and_surrounding_prose() -> None:
    assert parse_llm_json("```\n[1, 2, 3]\n```") == [1, 2, 3]
    assert parse_llm_json('Here you go: {"ok": true} — done.') == {"ok": True}


def test_parser_rejects_non_json() -> None:
    from app.llm.errors import LlmError

    with pytest.raises(LlmError) as error:
        parse_llm_json("<think>only reasoning</think> no json here")
    assert error.value.code == "INVALID_JSON"


# --------------------------------------------------------------------------------------------
# Context packing
# --------------------------------------------------------------------------------------------


def _large_workspace() -> WorkspaceIR:
    nodes = [
        ComponentNode(
            id=f"com.acme.Node{index}",
            name=f"Node{index}",
            stack="spring-boot",
            layer="service",
            kind="class",
            file_path=f"src/main/java/com/acme/Node{index}.java",
            annotations=["@Service"],
            fields=[
                ComponentField(name="amount", type="BigDecimal", annotations=["@NotNull"]),
                ComponentField(name="label", type="String"),
            ],
            methods=[
                ComponentMethod(name="calculate", return_type="BigDecimal", parameters=["String currency"]),
                ComponentMethod(name="reset"),
            ],
        )
        for index in range(120)
    ]
    return WorkspaceIR(
        name="big",
        root_path="/workspace/big",
        detected_stacks=["spring-boot"],
        nodes=nodes,
        relations=[],
        audit=AuditReport(score=72, findings=[]),
    )


def test_context_packer_enforces_budget_and_flags_truncation() -> None:
    packed = pack_workspace(_large_workspace(), budget=2_000)

    assert len(packed.text) <= 2_000
    assert packed.truncated is True
    assert packed.warnings
    document = json.loads(packed.text)
    assert 0 < len(document["nodes"]) < 120
    assert document["health"]["score"] == 72


def test_context_packer_compacts_signatures_without_source() -> None:
    workspace = _large_workspace()
    packed = pack_workspace(workspace, budget=200_000)

    assert packed.truncated is False
    document = json.loads(packed.text)
    first = document["nodes"][0]
    assert first["id"] == "com.acme.Node0"
    assert first["layer"] == "service"
    assert "amount:BigDecimal @NotNull" in first["fields"]
    assert "calculate(String currency):BigDecimal" in first["methods"]
    # Only signatures cross the wire, never file contents.
    assert "src/main/java" in first["filePath"]
    assert "public class" not in packed.text


# --------------------------------------------------------------------------------------------
# Workflow 1 — spec to blueprint
# --------------------------------------------------------------------------------------------


def test_spec_to_blueprint_returns_validated_blueprint(client: TestClient) -> None:
    with mock_llm(lambda request: _chat_response({"blueprint": VALID_BLUEPRINT, "rationale": "Slices mirror the domain."})) as calls:
        response = client.post(
            "/api/v1/ai/spec-to-blueprint",
            json={
                "spec": "An invoicing system with customers and invoices.",
                "stack": "spring-boot",
                "projectName": "Invoicing",
                "basePackageOrNamespace": "com.acme.invoicing",
                "llmConfig": CLOUD_CONFIG,
            },
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["modelUsed"] == "deepseek-reasoner"
    assert body["rationale"] == "Slices mirror the domain."
    assert body["blueprint"]["slices"][1]["name"] == "Invoice"
    assert body["blueprint"]["slices"][1]["dependsOnSlices"] == ["Customer"]
    assert body["blueprint"]["slices"][0]["fields"][0]["name"] == "fullName"
    assert len(calls) == 1
    sent = json.loads(calls[0].content)
    assert sent["model"] == "deepseek-reasoner"
    assert sent["messages"][0]["role"] == "system"


def test_spec_to_blueprint_repairs_once_after_validation_error(client: TestClient) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        repair = any("invalid for the Kodo blueprint schema" in message["content"] for message in body["messages"])
        if repair:
            return _chat_response({"blueprint": VALID_BLUEPRINT, "rationale": "Repaired blueprint."})
        return _chat_response({"blueprint": INVALID_BLUEPRINT, "rationale": "First attempt."})

    with mock_llm(handler) as calls:
        response = client.post(
            "/api/v1/ai/spec-to-blueprint",
            json={"spec": "Invoicing with customers.", "stack": "spring-boot", "llmConfig": CLOUD_CONFIG},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["rationale"] == "Repaired blueprint."
    assert all("repaired with one automatic retry" in warning for warning in body["warnings"])
    assert len(calls) == 2


def test_spec_to_blueprint_fails_422_after_second_invalid_answer(client: TestClient) -> None:
    with mock_llm(lambda request: _chat_response({"blueprint": INVALID_BLUEPRINT, "rationale": "nope"})) as calls:
        response = client.post(
            "/api/v1/ai/spec-to-blueprint",
            json={"spec": "Invoicing with customers.", "stack": "spring-boot", "llmConfig": CLOUD_CONFIG},
        )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "INVALID_BLUEPRINT"
    assert detail["details"]
    assert len(calls) == 2


def test_spec_to_blueprint_pins_requested_stack(client: TestClient) -> None:
    with mock_llm(lambda request: _chat_response({"blueprint": VALID_BLUEPRINT, "rationale": ""})):
        response = client.post(
            "/api/v1/ai/spec-to-blueprint",
            json={
                "spec": "Desktop invoicing app.",
                "stack": "csharp-wpf",
                "projectName": "Acme.Desktop",
                "basePackageOrNamespace": "Acme.Desktop",
                "llmConfig": CLOUD_CONFIG,
            },
        )

    assert response.status_code == 200, response.text
    blueprint = response.json()["blueprint"]
    assert blueprint["stack"] == "csharp-wpf"
    assert blueprint["projectName"] == "Acme.Desktop"


# --------------------------------------------------------------------------------------------
# Workflow 2 — audit fix
# --------------------------------------------------------------------------------------------


def test_audit_fix_returns_dry_run_patch_and_never_writes(client: TestClient, workspace: tuple[Path, Path]) -> None:
    root, source_file = workspace
    before = source_file.read_bytes()
    on_disk = before.decode("utf-8")
    proposed = on_disk.replace("OrderRepository repository", "OrderService service")

    def handler(request: httpx.Request) -> httpx.Response:
        payload = {
            "explanation": "Controller now talks to the service layer.",
            "files": [
                {
                    "filePath": "src/main/java/com/acme/shop/controller/OrderController.java",
                    "proposedContent": proposed,
                    "summary": ["replaced repository dependency with service"],
                }
            ],
        }
        return _chat_response(payload)

    with mock_llm(handler) as calls:
        response = client.post(
            "/api/v1/ai/audit-fix",
            json={
                "rootPath": str(root),
                "finding": ORDER_FINDING,
                "workspaceIr": _workspace_payload(root),
                "llmConfig": CLOUD_CONFIG,
            },
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["explanation"] == "Controller now talks to the service layer."
    assert body["modelUsed"] == "deepseek-chat"
    assert len(body["patches"]) == 1

    patch = body["patches"][0]
    assert patch["filePath"] == "src/main/java/com/acme/shop/controller/OrderController.java"
    assert patch["language"] == "java"
    assert patch["originalContent"] == on_disk
    assert patch["originalSha256"] == hashlib.sha256(before).hexdigest()
    assert patch["proposedContent"] == proposed
    assert patch["isNewFile"] is False

    # Read-only contract: the file on disk is byte-identical, and the prompt carried file content.
    assert source_file.read_bytes() == before
    assert len(calls) == 1
    prompt = json.loads(calls[0].content)["messages"][1]["content"]
    assert "OrderController" in prompt
    assert "public String list()" in prompt


def test_audit_fix_rejects_path_traversal(client: TestClient, tmp_path: Path) -> None:
    root = tmp_path / "shop"
    root.mkdir()
    (tmp_path / "secret.java").write_text("class Secret {}", encoding="utf-8")
    finding = {**ORDER_FINDING, "nodeIds": [], "filePath": "../secret.java"}

    with mock_llm(lambda request: _chat_response({"explanation": "", "files": []})) as calls:
        response = client.post(
            "/api/v1/ai/audit-fix",
            json={
                "rootPath": str(root),
                "finding": finding,
                "workspaceIr": {
                    "name": "shop",
                    "rootPath": str(root),
                    "detectedStacks": ["spring-boot"],
                    "nodes": [],
                    "relations": [],
                },
                "llmConfig": CLOUD_CONFIG,
            },
        )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "PATH_REJECTED"
    assert calls == []


def test_audit_fix_rejects_edits_outside_the_provided_files(client: TestClient, workspace: tuple[Path, Path]) -> None:
    root, source_file = workspace
    before = source_file.read_bytes()

    payload = {
        "explanation": "",
        "files": [{"filePath": "src/main/java/com/acme/Evil.java", "proposedContent": "class Evil {}"}],
    }
    with mock_llm(lambda request: _chat_response(payload)):
        response = client.post(
            "/api/v1/ai/audit-fix",
            json={
                "rootPath": str(root),
                "finding": ORDER_FINDING,
                "workspaceIr": _workspace_payload(root),
                "llmConfig": CLOUD_CONFIG,
            },
        )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "INVALID_PATCH"
    assert source_file.read_bytes() == before


def test_audit_fix_drops_unrelated_model_edits_but_keeps_allowed_patch(
    client: TestClient, workspace: tuple[Path, Path]
) -> None:
    root, source_file = workspace
    before = source_file.read_bytes()
    on_disk = before.decode("utf-8")
    proposed = on_disk.replace("OrderRepository repository", "OrderService service")

    payload = {
        "explanation": "Rewired the controller.",
        "files": [
            {"filePath": "src/main/java/com/acme/shop/controller/OrderController.java", "proposedContent": proposed},
            {"filePath": "src/main/java/com/acme/shop/service/OrderService.java", "proposedContent": "class Evil {}"},
        ],
    }
    with mock_llm(lambda request: _chat_response(payload)):
        response = client.post(
            "/api/v1/ai/audit-fix",
            json={
                "rootPath": str(root),
                "finding": ORDER_FINDING,
                "workspaceIr": _workspace_payload(root),
                "llmConfig": CLOUD_CONFIG,
            },
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert [patch["filePath"] for patch in body["patches"]] == [
        "src/main/java/com/acme/shop/controller/OrderController.java"
    ]
    assert any("OrderService.java" in warning and "dropped" in warning for warning in body["warnings"])
    assert source_file.read_bytes() == before


# --------------------------------------------------------------------------------------------
# Workflow 3 — targeted method implementation
# --------------------------------------------------------------------------------------------


def test_implement_method_returns_patch_with_accurate_sha(client: TestClient, workspace: tuple[Path, Path]) -> None:
    root, source_file = workspace
    before = source_file.read_bytes()
    on_disk = before.decode("utf-8")
    proposed = on_disk.replace('return "orders";', 'return repository.findAll().toString();')

    with mock_llm(lambda request: _chat_response({"explanation": "Delegates to the repository.", "proposedContent": proposed})) as calls:
        response = client.post(
            "/api/v1/ai/implement-method",
            json={
                "rootPath": str(root),
                "filePath": "src/main/java/com/acme/shop/controller/OrderController.java",
                "nodeId": "com.acme.shop.controller.OrderController",
                "methodName": "list",
                "instruction": "Return the order numbers from the repository.",
                "workspaceIr": _workspace_payload(root),
                "llmConfig": CLOUD_CONFIG,
            },
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["explanation"] == "Delegates to the repository."
    patch = body["patches"][0]
    assert patch["originalSha256"] == hashlib.sha256(before).hexdigest()
    assert patch["originalContent"] == on_disk
    assert patch["proposedContent"] == proposed
    assert body["patches"][0]["warnings"] == []
    assert source_file.read_bytes() == before

    prompt = json.loads(calls[0].content)["messages"][1]["content"]
    assert "Method to implement or update\nlist" in prompt
    assert "Return the order numbers from the repository." in prompt


def test_implement_method_rejects_unknown_node(client: TestClient, workspace: tuple[Path, Path]) -> None:
    root, _ = workspace

    with mock_llm(lambda request: _chat_response({"explanation": "", "proposedContent": ""})) as calls:
        response = client.post(
            "/api/v1/ai/implement-method",
            json={
                "rootPath": str(root),
                "filePath": "src/main/java/com/acme/shop/controller/OrderController.java",
                "nodeId": "Ghost",
                "methodName": "list",
                "instruction": "Do something.",
                "workspaceIr": _workspace_payload(root),
                "llmConfig": CLOUD_CONFIG,
            },
        )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "UNKNOWN_NODE"
    assert calls == []


# --------------------------------------------------------------------------------------------
# Error handling and connection probe
# --------------------------------------------------------------------------------------------


def test_missing_api_key_is_rejected_before_any_http_call(client: TestClient) -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - must not run
        raise AssertionError("no HTTP call should happen without an API key")

    with mock_llm(handler):
        response = client.post(
            "/api/v1/ai/spec-to-blueprint",
            json={
                "spec": "An invoicing system with customers.",
                "stack": "spring-boot",
                "llmConfig": {"baseUrl": "https://api.deepseek.com/v1", "apiKey": ""},
            },
        )

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "MISSING_API_KEY"


def test_unauthorized_provider_response_is_structured(client: TestClient) -> None:
    with mock_llm(lambda request: httpx.Response(401, json={"error": {"message": "invalid api key"}})):
        response = client.post(
            "/api/v1/ai/spec-to-blueprint",
            json={"spec": "An invoicing system.", "stack": "spring-boot", "llmConfig": CLOUD_CONFIG},
        )

    assert response.status_code == 401
    detail = response.json()["detail"]
    assert detail["code"] == "UNAUTHORIZED"
    assert CLOUD_CONFIG["apiKey"] not in response.text


def test_rate_limit_is_structured(client: TestClient) -> None:
    with mock_llm(lambda request: httpx.Response(429, json={"error": {"message": "slow down"}})):
        response = client.post(
            "/api/v1/ai/spec-to-blueprint",
            json={"spec": "An invoicing system.", "stack": "spring-boot", "llmConfig": CLOUD_CONFIG},
        )

    assert response.status_code == 429
    assert response.json()["detail"]["code"] == "RATE_LIMITED"


def test_timeout_is_reported_as_504(client: TestClient) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out", request=request)

    with mock_llm(handler):
        response = client.post(
            "/api/v1/ai/spec-to-blueprint",
            json={"spec": "An invoicing system.", "stack": "spring-boot", "llmConfig": CLOUD_CONFIG},
        )

    assert response.status_code == 504
    assert response.json()["detail"]["code"] == "TIMEOUT"


def test_unreachable_local_ollama_is_reported_without_api_key(client: TestClient) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with mock_llm(handler):
        response = client.post(
            "/api/v1/ai/spec-to-blueprint",
            json={
                "spec": "An invoicing system.",
                "stack": "spring-boot",
                "llmConfig": {"baseUrl": "http://localhost:11434/v1", "apiKey": ""},
            },
        )

    assert response.status_code == 502
    detail = response.json()["detail"]
    assert detail["code"] == "UNREACHABLE"
    assert "11434" in detail["message"]


def test_test_connection_lists_models_for_local_server(client: TestClient) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/models"
        assert "authorization" not in {key.lower() for key in request.headers}
        return httpx.Response(200, json={"data": [{"id": "deepseek-r1:8b"}, {"id": "deepseek-coder-v2"}]})

    with mock_llm(handler):
        response = client.post(
            "/api/v1/ai/test-connection",
            json={"llmConfig": {"baseUrl": "http://localhost:11434/v1", "apiKey": ""}},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True
    assert body["provider"] == "local"
    assert body["models"] == ["deepseek-coder-v2", "deepseek-r1:8b"]


def test_llm_config_reads_environment_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.llm.config import resolve_config

    monkeypatch.setenv("KODO_LLM_BASE_URL", "http://vllm.internal:8000/v1/")
    monkeypatch.setenv("KODO_LLM_CODE_MODEL", "qwen2.5-coder")
    monkeypatch.setenv("KODO_LLM_REASONING_MODEL", "qwen2.5")
    monkeypatch.setenv("KODO_LLM_TIMEOUT_SECONDS", "12")
    monkeypatch.setenv("KODO_LLM_API_KEY", "env-secret")

    config = resolve_config()

    assert isinstance(config, LlmConfig)
    assert config.base_url == "http://vllm.internal:8000/v1"
    assert config.code_model == "qwen2.5-coder"
    assert config.reasoning_model == "qwen2.5"
    assert config.timeout_seconds == 12
    assert config.api_key == "env-secret"


def test_api_key_is_never_echoed_in_errors(client: TestClient) -> None:
    secret = "sk-super-secret-value"
    with mock_llm(lambda request: httpx.Response(500, json={"error": {"message": "boom"}})):
        response = client.post(
            "/api/v1/ai/spec-to-blueprint",
            json={
                "spec": "An invoicing system.",
                "stack": "spring-boot",
                "llmConfig": {**CLOUD_CONFIG, "apiKey": secret},
            },
        )

    assert response.status_code == 502
    assert secret not in response.text
    assert secret not in os.environ.get("KODO_LLM_API_KEY", "")
