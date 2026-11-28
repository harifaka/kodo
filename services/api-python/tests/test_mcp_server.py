"""Phase 15 MCP server tests — hermetic: no network, no Docker daemon, no workspace writes.

Every Laya `/v1/systemone` call is served by an ``httpx.MockTransport``; the ephemeral builder is
driven through the runner's ``_run_cli`` / ``_stream_container`` seams. The API is exercised through
``TestClient`` exactly like a real MCP client would (POST /mcp, JSON-RPC 2.0).
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
import subprocess
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app import __version__
from app.auth.jwt_utils import create_session_token
from app.builders import runner
from app.db import repository
from app.db.engine import reset_engine
from app.decision.client import set_transport_override
from app.main import app
from app.mcp import MCP_ENDPOINT_PATH
from app.mcp.protocol import DEFAULT_PROTOCOL_VERSION, PROTOCOL_VERSIONS
from app.mcp.stdio_server import local_context, serve
from app.mcp.tools import TOOL_SPECS, ToolContext, list_tool_definitions

Handler = Callable[[httpx.Request], httpx.Response]

JAVA_CONTROLLER = """
package com.acme.shop.controller;

import com.acme.shop.repository.OrderRepository;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class OrderController {
    private final OrderRepository orderRepository;

    public OrderController(OrderRepository orderRepository) {
        this.orderRepository = orderRepository;
    }

    public String list() {
        return orderRepository.findAll();
    }
}
"""

JAVA_REPOSITORY = """
package com.acme.shop.repository;

import org.springframework.stereotype.Repository;

@Repository
public class OrderRepository {
    public String findAll() {
        return "orders";
    }
}
"""

JAVA_SERVICE = """
package com.acme.shop.service;

import com.acme.shop.repository.OrderRepository;
import org.springframework.stereotype.Service;

@Service
public class OrderService {
    private final OrderRepository orderRepository;

    public OrderService(OrderRepository orderRepository) {
        this.orderRepository = orderRepository;
    }
}
"""

CONTROLLER_PATH = "src/main/java/com/acme/shop/controller/OrderController.java"


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture(autouse=True)
def _reset_rate_limiter() -> Iterator[None]:
    app.state.rate_limiter.reset()
    try:
        yield
    finally:
        app.state.rate_limiter.reset()


@pytest.fixture()
def shop(tmp_path: Path) -> Path:
    """A tiny Spring Boot tree with one real layer violation (controller -> repository)."""
    root = tmp_path / "shop" / "src" / "main" / "java" / "com" / "acme" / "shop"
    for package, name, source in (
        ("controller", "OrderController.java", JAVA_CONTROLLER),
        ("repository", "OrderRepository.java", JAVA_REPOSITORY),
        ("service", "OrderService.java", JAVA_SERVICE),
    ):
        folder = root / package
        folder.mkdir(parents=True, exist_ok=True)
        (folder / name).write_text(source, encoding="utf-8", newline="\n")
    return tmp_path / "shop"


def _rpc(
    client: TestClient,
    method: str,
    params: dict | None = None,
    *,
    request_id: int | str | None = 1,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    message: dict[str, object] = {"jsonrpc": "2.0", "method": method, "params": params or {}}
    if request_id is not None:
        message["id"] = request_id
    return client.post(MCP_ENDPOINT_PATH, json=message, headers=headers or {})


def _call(
    client: TestClient,
    tool: str,
    arguments: dict,
    *,
    headers: dict[str, str] | None = None,
) -> dict:
    response = _rpc(client, "tools/call", {"name": tool, "arguments": arguments}, headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert "error" not in body, body["error"]
    return body["result"]


def _structured(client: TestClient, tool: str, arguments: dict) -> dict:
    result = _call(client, tool, arguments)
    assert result["isError"] is False, result
    return result["structuredContent"]


def _tree_signature(root: Path) -> dict[str, tuple[int, str]]:
    """Every file plus its size and SHA-256 — proves a read-only tool never touched the workspace."""
    signature: dict[str, tuple[int, str]] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            payload = path.read_bytes()
            signature[path.relative_to(root).as_posix()] = (
                len(payload),
                hashlib.sha256(payload).hexdigest(),
            )
    return signature


# ------------------------------------------------------------------------- System 1 mocking


@contextmanager
def mock_systemone(answers: dict[str, str], *, confidence: float = 0.93) -> Iterator[list[httpx.Request]]:
    """Serve `/v1/systemone` from memory with fixed, high-confidence answers."""

    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        body: dict[str, object] = {}
        for question in payload["questions"]:
            options = [option["key"] for option in question.get("options", [])]
            key = answers.get(question["id"], "uncertain")
            if key not in options and options:
                key = options[-1]
            others = [option for option in options if option != key]
            share = round((1.0 - confidence) / max(1, len(others)), 4)
            body[question["id"]] = {
                "answer": key,
                "probabilities": {key: confidence, **{option: share for option in others}},
                "confidence": confidence,
            }
        calls.append(request)
        return httpx.Response(200, json={"model": "laya-test", "answers": body})

    set_transport_override(httpx.MockTransport(handler))
    try:
        yield calls
    finally:
        set_transport_override(None)


# ------------------------------------------------------------------------ handshake & catalog


@pytest.mark.parametrize("requested", PROTOCOL_VERSIONS)
def test_initialize_negotiates_each_supported_protocol_version(
    client: TestClient, requested: str
) -> None:
    response = _rpc(client, "initialize", {"protocolVersion": requested, "capabilities": {}})

    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert result["protocolVersion"] == requested
    assert result["serverInfo"]["name"] == "kodo"
    assert result["serverInfo"]["version"] == __version__
    assert result["capabilities"]["tools"]["listChanged"] is False
    assert "read-only" in result["instructions"]


def test_initialize_falls_back_to_the_default_protocol_version(client: TestClient) -> None:
    result = _rpc(client, "initialize", {"protocolVersion": "1999-01-01"}).json()["result"]

    assert result["protocolVersion"] == DEFAULT_PROTOCOL_VERSION


def test_tools_list_exposes_seven_read_only_tools(client: TestClient) -> None:
    tools = _rpc(client, "tools/list").json()["result"]["tools"]

    names = {tool["name"] for tool in tools}
    assert names == {
        "kodo_scan_workspace",
        "kodo_audit_workspace",
        "kodo_get_component",
        "kodo_route_task",
        "kodo_screen_diff",
        "kodo_dry_run_patch",
        "kodo_verify_build",
    }
    assert len(tools) == len(TOOL_SPECS) == 7

    for tool in tools:
        annotations = tool["annotations"]
        assert annotations["readOnlyHint"] is True
        assert annotations["destructiveHint"] is False
        assert tool["inputSchema"]["type"] == "object"
        assert tool["inputSchema"]["additionalProperties"] is False
        assert "rootPath" in tool["inputSchema"]["properties"]


def test_no_tool_can_write_apply_rollback_or_deploy() -> None:
    forbidden = ("apply", "rollback", "deploy", "export", "write", "delete", "scaffold", "clone")
    for spec in list_tool_definitions():
        name = spec["name"].lower()
        assert not any(word in name for word in forbidden), name
        assert spec["annotations"]["readOnlyHint"] is True
        assert spec["annotations"]["destructiveHint"] is False


def test_initialized_notification_is_acknowledged_without_a_body(client: TestClient) -> None:
    response = _rpc(client, "notifications/initialized", request_id=None)

    assert response.status_code == 202
    assert response.content == b""


def test_ping_returns_an_empty_result(client: TestClient) -> None:
    body = _rpc(client, "ping").json()

    assert body["result"] == {}


def test_protocol_version_header_is_echoed(client: TestClient) -> None:
    response = _rpc(
        client,
        "ping",
        headers={"Mcp-Protocol-Version": "2025-06-18", "Mcp-Method": "ping", "Mcp-Name": "kodo_ping"},
    )

    assert response.headers["mcp-protocol-version"] == "2025-06-18"


def test_unknown_method_and_unknown_tool_are_rejected(client: TestClient) -> None:
    missing = _rpc(client, "tools/nope").json()
    assert missing["error"]["code"] == -32601
    assert "tools/call" in missing["error"]["data"]["supported"]

    unknown_tool = _rpc(client, "tools/call", {"name": "kodo_apply_everything", "arguments": {}}).json()
    assert unknown_tool["error"]["code"] == -32602
    assert "kodo_scan_workspace" in unknown_tool["error"]["data"]["available"]


def test_invalid_arguments_report_the_offending_field(client: TestClient) -> None:
    body = _rpc(client, "tools/call", {"name": "kodo_scan_workspace", "arguments": {"nope": 1}}).json()

    assert body["error"]["code"] == -32602
    paths = [error["path"] for error in body["error"]["data"]["errors"]]
    assert any("root_path" in path or "rootPath" in path for path in paths)


def test_malformed_json_is_a_parse_error(client: TestClient) -> None:
    response = client.post(MCP_ENDPOINT_PATH, content=b"{not json")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == -32700


def test_sse_transport_is_used_when_the_client_prefers_event_stream(client: TestClient) -> None:
    response = client.post(
        MCP_ENDPOINT_PATH,
        json={"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {}},
        headers={"Accept": "text/event-stream"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["x-accel-buffering"] == "no"
    assert response.text.startswith("event: message\ndata: ")
    payload = json.loads(response.text.split("data: ", 1)[1])
    assert payload["result"] == {}


def test_get_and_delete_are_method_not_allowed(client: TestClient) -> None:
    for response in (client.get(MCP_ENDPOINT_PATH), client.delete(MCP_ENDPOINT_PATH)):
        assert response.status_code == 405
        assert response.json()["detail"]["code"] == "METHOD_NOT_ALLOWED"
        assert response.headers["allow"] == "POST"


# -------------------------------------------------------------------------------- tools


def test_scan_workspace_returns_a_compact_overview_with_layered_mermaid(
    client: TestClient, shop: Path
) -> None:
    before = _tree_signature(shop)

    payload = _structured(
        client,
        "kodo_scan_workspace",
        {"rootPath": str(shop), "includeMermaid": True, "memberDetail": "compact"},
    )

    assert payload["componentCount"] == 3
    assert payload["relationCount"] >= 2
    assert payload["stacks"] == ["spring-boot"]
    assert payload["layerCounts"] == {"controller": 1, "repository": 1, "service": 1}
    assert 0 <= payload["healthScore"] <= 100
    assert set(payload["auditSummary"]) == {"errors", "warnings", "info"}
    assert {component["name"] for component in payload["components"]} == {
        "OrderController",
        "OrderRepository",
        "OrderService",
    }
    assert payload["componentsTruncated"] is False
    assert all(set(item) == {"id", "name", "layer", "kind", "stack", "filePath"} for item in payload["components"])

    diagram = payload["mermaidClassDiagram"]
    assert diagram.startswith("classDiagram")
    assert "namespace Controllers" in diagram
    assert "namespace Repositories" in diagram

    # Two scans of the same tree must be byte-identical and never touch the workspace.
    repeat = _structured(client, "kodo_scan_workspace", {"rootPath": str(shop)})
    assert repeat["components"] == payload["components"]
    assert _tree_signature(shop) == before


def test_scan_workspace_rejects_a_missing_root(client: TestClient, tmp_path: Path) -> None:
    result = _call(client, "kodo_scan_workspace", {"rootPath": str(tmp_path / "absent")})

    assert result["isError"] is True
    error = json.loads(result["content"][0]["text"])["error"]
    assert error["code"] == "PATH_REJECTED"


def test_audit_workspace_reports_deterministic_findings(client: TestClient, shop: Path) -> None:
    first = _structured(client, "kodo_audit_workspace", {"rootPath": str(shop)})
    second = _structured(client, "kodo_audit_workspace", {"rootPath": str(shop)})

    assert first == second
    assert first["findingCount"] == len(first["findings"]) >= 1
    assert first["summary"]["errors"] == sum(1 for f in first["findings"] if f["severity"] == "error")
    violated = [finding for finding in first["findings"] if finding["ruleId"] == "LAYER_VIOLATION"]
    assert violated, first["findings"]
    assert "OrderController" in violated[0]["title"]
    assert first["score"] == max(0, 100 - 10 * first["summary"]["errors"]
                                 - 4 * first["summary"]["warnings"] - first["summary"]["info"])
    assert "layaAvailable" not in first


def test_audit_workspace_annotates_with_mocked_laya_triage(client: TestClient, shop: Path) -> None:
    answers = {
        "risk_level": "critical_arch_risk",
        "fix_route": "deterministic_ast",
        "needs_human_design": "no_mechanical_fix",
    }
    with mock_systemone(answers) as calls:
        payload = _structured(
            client, "kodo_audit_workspace", {"rootPath": str(shop), "includeLayaTriage": True}
        )

    assert calls, "the triage must reach the System 1 endpoint"
    assert payload["layaAvailable"] is True
    assert payload["layaTriage"]["model"] == "laya-test"
    assert len(payload["layaTriage"]["items"]) == payload["findingCount"]
    item = payload["layaTriage"]["items"][0]
    assert item["recommendedRoute"] == "deterministic_ast"
    assert item["riskLevel"] == "critical_arch_risk"
    assert item["confidence"] == pytest.approx(0.93)
    assert item["escalatedToSystem2"] is False
    assert item["adrId"]

    records = repository.list_decision_records(
        repository.LOCAL_USER_ID, decision_type="audit_triage"
    )
    assert len(records) == payload["findingCount"]


def test_audit_workspace_degrades_when_laya_is_disabled(
    client: TestClient, shop: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KODO_SYSTEMONE_ENABLED", "false")

    payload = _structured(
        client, "kodo_audit_workspace", {"rootPath": str(shop), "includeLayaTriage": True}
    )

    assert payload["layaAvailable"] is False
    assert payload["layaTriage"]["items"] == []
    assert payload["layaWarning"]
    assert payload["findings"], "deterministic findings must survive an offline System 1"


def test_get_component_returns_the_one_hop_neighbourhood(client: TestClient, shop: Path) -> None:
    payload = _structured(
        client, "kodo_get_component", {"rootPath": str(shop), "componentQuery": "ordercontroller"}
    )

    assert payload["found"] is True
    assert payload["match"] == "exact_name"
    component = payload["component"]
    assert component["name"] == "OrderController"
    assert component["layer"] == "controller"
    assert component["filePath"] == CONTROLLER_PATH
    assert component["methods"], "the component detail must include its methods"

    outgoing = payload["neighborhood"]["outgoing"]
    assert [item["target"]["name"] for item in outgoing] == ["OrderRepository"]
    assert outgoing[0]["type"] == "depends_on"
    assert payload["neighborhood"]["incoming"] == []
    assert [finding["ruleId"] for finding in payload["auditFindings"]] == ["LAYER_VIOLATION"]


def test_get_component_matches_by_id_and_reports_unknown_queries(
    client: TestClient, shop: Path
) -> None:
    by_id = _structured(
        client, "kodo_get_component", {"rootPath": str(shop), "componentQuery": "com.acme.shop.service.OrderService"}
    )
    assert by_id["match"] == "exact_id"
    assert by_id["component"]["name"] == "OrderService"
    assert [item["target"]["name"] for item in by_id["neighborhood"]["outgoing"]] == ["OrderRepository"]

    missing = _structured(
        client, "kodo_get_component", {"rootPath": str(shop), "componentQuery": "DoesNotExist"}
    )
    assert missing["found"] is False
    assert "OrderController" in missing["suggestions"]


def test_route_task_persists_a_tenant_scoped_adr(client: TestClient, shop: Path) -> None:
    answers = {
        "execution_path": "deterministic_ast",
        "blast_radius": "single_file_local",
        "escalate_to_system2": "act_system1_deterministic",
    }
    with mock_systemone(answers):
        payload = _structured(
            client,
            "kodo_route_task",
            {
                "rootPath": str(shop),
                "intent": "Add an audit timestamp field to the order entity",
                "targetNodeId": "com.acme.shop.repository.OrderRepository",
            },
        )

    assert payload["available"] is True
    assert payload["recommendedRoute"] == "deterministic_ast"
    assert payload["blastRadius"] == "single_file_local"
    assert payload["escalateToSystem2"] is False
    assert payload["confidence"] == pytest.approx(0.93)
    assert payload["adrId"]

    records = repository.list_decision_records(repository.LOCAL_USER_ID, decision_type="task_route")
    assert [record.id for record in records] == [payload["adrId"]]
    assert records[0].recommended_route == "deterministic_ast"


def test_route_task_degrades_when_laya_is_offline(
    client: TestClient, shop: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KODO_SYSTEMONE_BASE_URL", "http://127.0.0.1:9")

    class _UnreachableTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused", request=request)

    set_transport_override(_UnreachableTransport())
    try:
        payload = _structured(
            client, "kodo_route_task", {"rootPath": str(shop), "intent": "Refactor the order slice"}
        )
    finally:
        set_transport_override(None)

    assert payload["available"] is False
    assert payload["recommendedRoute"] == "human_review"
    assert payload["adrId"] is None
    assert payload["warning"]


def test_screen_diff_returns_an_advisory_verdict_without_writing(
    client: TestClient, shop: Path
) -> None:
    before = _tree_signature(shop)
    answers = {
        "logic_deletion_risk": "safe_preserved",
        "layer_boundary_risk": "clean_boundaries",
        "review_priority": "routine_quick_check",
    }
    proposed = JAVA_REPOSITORY.replace('return "orders";', 'return "orders-v2";')

    with mock_systemone(answers):
        payload = _structured(
            client,
            "kodo_screen_diff",
            {
                "rootPath": str(shop),
                "patches": [
                    {
                        "filePath": "src/main/java/com/acme/shop/repository/OrderRepository.java",
                        "proposedContent": proposed,
                    }
                ],
            },
        )

    assert payload["available"] is True
    assert payload["status"] == "pass"
    assert payload["flags"] == []
    assert payload["confidence"] == pytest.approx(0.93)
    assert "Advisory only" in payload["advisoryNote"]
    assert payload["adrId"]
    assert _tree_signature(shop) == before


def test_dry_run_patch_returns_the_sha256_and_never_mutates_disk(
    client: TestClient, shop: Path
) -> None:
    before = _tree_signature(shop)
    controller = shop / CONTROLLER_PATH
    original = controller.read_bytes()

    payload = _structured(
        client,
        "kodo_dry_run_patch",
        {
            "rootPath": str(shop),
            "operations": [
                {
                    "op": "add_field",
                    "filePath": CONTROLLER_PATH,
                    "typeName": "OrderController",
                    "field": {"name": "auditTrail", "type": "String", "annotations": []},
                }
            ],
        },
    )

    assert payload["applied"] is False
    assert len(payload["patches"]) == 1
    patch = payload["patches"][0]
    assert patch["filePath"] == CONTROLLER_PATH
    assert patch["originalSha256"] == hashlib.sha256(original).hexdigest()
    assert patch["isNewFile"] is False
    assert "auditTrail" in patch["proposedContent"]
    assert "add_field" in patch["summary"]

    # Zero writes: identical bytes, identical tree, no rollback batch created.
    assert controller.read_bytes() == original
    assert _tree_signature(shop) == before


def test_dry_run_patch_rejects_operations_outside_the_root(client: TestClient, shop: Path) -> None:
    result = _call(
        client,
        "kodo_dry_run_patch",
        {
            "rootPath": str(shop),
            "operations": [
                {"op": "add_field", "filePath": "../escape.java", "field": {"name": "x", "type": "int"}}
            ],
        },
    )

    assert result["isError"] is True
    assert json.loads(result["content"][0]["text"])["error"]["code"] == "PATCH_REJECTED"


# ---------------------------------------------------------------------------- verify build


class FakeDocker:
    """Answers the runner's inspection calls and records every ``docker`` invocation."""

    def __init__(self, images: set[str] | None = None) -> None:
        self.images = images if images is not None else {os.environ.get("KODO_BUILDER_IMAGE_JAVA", "kodo-builder-java:local")}
        self.calls: list[list[str]] = []

    def __call__(
        self, args: list[str], *, timeout: int, data: bytes | None = None
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(args))
        if args[:2] == ["docker", "--version"]:
            return subprocess.CompletedProcess(args, 0, "Docker version 28.4.0\n", "")
        if args[:2] == ["docker", "info"]:
            return subprocess.CompletedProcess(args, 0, "28.4.0\n", "")
        if args[:3] == ["docker", "image", "inspect"]:
            found = args[-1] in self.images
            return subprocess.CompletedProcess(
                args, 0 if found else 1, "[]" if found else "", "" if found else "No such image"
            )
        if args[:2] == ["docker", "create"]:
            return subprocess.CompletedProcess(args, 0, "cid123\n", "")
        return subprocess.CompletedProcess(args, 0, "", "")

    def find(self, *prefix: str) -> list[list[str]]:
        return [call for call in self.calls if call[: len(prefix)] == list(prefix)]


def test_verify_build_runs_in_the_network_isolated_sandbox(
    client: TestClient, shop: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    docker = FakeDocker()
    monkeypatch.setattr(runner, "_run_cli", docker)
    monkeypatch.setattr(
        runner,
        "_stream_container",
        lambda container_id, timeout_seconds, on_line: (
            0,
            "BUILD SUCCESS\n"
            "[WARNING] /workspace/src/main/java/com/acme/shop/controller/OrderController.java:[7,5] unused field\n",
            False,
            False,
        ),
    )

    payload = _structured(client, "kodo_verify_build", {"rootPath": str(shop), "stack": "java"})

    assert payload["status"] == "passed"
    assert payload["stack"] == "java"
    assert payload["exitCode"] == 0
    assert payload["networkMode"] == "none"
    assert payload["diagnostics"] == [
        {
            "filePath": "src/main/java/com/acme/shop/controller/OrderController.java",
            "line": 7,
            "column": 5,
            "severity": "warning",
            "code": "",
            "message": "unused field",
        }
    ]
    assert "BUILD SUCCESS" in payload["output"]

    create = docker.find("docker", "create")
    assert create, docker.calls
    assert "--network" in create[0] and create[0][create[0].index("--network") + 1] == "none"
    assert "--cap-drop" in create[0]
    assert docker.find("docker", "rm", "-f"), "the container must always be removed"
    assert docker.find("docker", "cp", "-"), "the snapshot is streamed in, never mounted"


def test_verify_build_detects_the_stack_and_reports_missing_docker(
    client: TestClient, shop: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (shop / "pom.xml").write_text("<project/>", encoding="utf-8")
    monkeypatch.setattr(runner, "_run_cli", lambda *args, **kwargs: None)

    payload = _structured(client, "kodo_verify_build", {"rootPath": str(shop)})

    assert payload["stack"] == "java"
    assert payload["status"] == "unavailable"
    assert any("Docker" in warning for warning in payload["warnings"])


def test_verify_build_rejects_an_unknown_stack(client: TestClient, tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()

    result = _call(client, "kodo_verify_build", {"rootPath": str(empty)})

    assert result["isError"] is True
    assert json.loads(result["content"][0]["text"])["error"]["code"] == "UNKNOWN_STACK"


# -------------------------------------------------------------------------------- resources


def test_resources_list_and_read(client: TestClient) -> None:
    resources = _rpc(client, "resources/list").json()["result"]["resources"]
    uris = [resource["uri"] for resource in resources]
    assert uris == ["kodo://health", "kodo://stacks"]

    health = _rpc(client, "resources/read", {"uri": "kodo://health"}).json()["result"]["contents"][0]
    assert health["mimeType"] == "application/json"
    body = json.loads(health["text"])
    assert body["version"] == __version__
    assert body["mode"] == "local"
    assert body["mcp"]["toolCount"] == 7
    assert body["mcp"]["readOnly"] is True
    assert set(body["analyzers"]) == {"csharp"}
    assert set(body["systemOne"]) >= {"enabled", "baseUrl", "model"}

    stacks = _rpc(client, "resources/read", {"uri": "kodo://stacks"}).json()["result"]["contents"][0]
    catalog = json.loads(stacks["text"])
    assert [stack["id"] for stack in catalog["stacks"]] == ["java", "csharp", "nodejs", "python"]
    assert {rule["ruleId"] for rule in catalog["auditRules"]} >= {"LAYER_VIOLATION", "GOD_CLASS"}


def test_unknown_resource_is_rejected(client: TestClient) -> None:
    body = _rpc(client, "resources/read", {"uri": "kodo://nope"}).json()

    assert body["error"]["code"] == -32602
    assert body["error"]["data"]["available"] == ["kodo://health", "kodo://stacks"]


# ----------------------------------------------------------------------------- stdio bridge


def test_stdio_bridge_reuses_the_registry_and_keeps_stdout_clean() -> None:
    ctx = local_context()
    assert isinstance(ctx, ToolContext)

    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
        {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
    ]
    payload = "\n".join(json.dumps(message) for message in requests) + "\n"
    stdout = io.BytesIO()

    asyncio.run(serve(io.BytesIO(payload.encode("utf-8")), stdout, ctx))

    lines = [line for line in stdout.getvalue().decode("utf-8").splitlines() if line]
    assert len(lines) == 2, "the notification must not emit a response line"
    initialized, tools = (json.loads(line) for line in lines)
    assert initialized["result"]["protocolVersion"] == "2025-06-18"
    assert len(tools["result"]["tools"]) == 7


# --------------------------------------------------------------------- SaaS auth & hard limits


@pytest.fixture()
def saas_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Path]:
    monkeypatch.setenv("KODO_MODE", "saas")
    monkeypatch.setenv("KODO_JWT_SECRET", "s" * 48)
    monkeypatch.setenv("KODO_WORKSPACES_DIR", str(tmp_path / "workspaces"))
    monkeypatch.setenv("KODO_DATABASE_URL", f"sqlite:///{(tmp_path / 'saas.db').as_posix()}")
    reset_engine()
    try:
        yield tmp_path / "workspaces"
    finally:
        reset_engine()


def _saas_user(username: str, github_id: str) -> tuple[repository.UserRecord, dict[str, str]]:
    user = repository.upsert_github_user(
        github_id=github_id,
        username=username,
        display_name=username.title(),
        avatar_url=None,
        email=None,
    )
    return user, {"Authorization": f"Bearer {create_session_token(user.id, user.username)}"}


def test_saas_rejects_unauthenticated_mcp_calls(client: TestClient, saas_env: Path) -> None:
    response = _rpc(client, "initialize", {"protocolVersion": "2025-06-18"})

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "UNAUTHORIZED"


def test_saas_mcp_rejects_host_and_foreign_paths(client: TestClient, saas_env: Path) -> None:
    alice, alice_headers = _saas_user("alice", "8501")
    bob, bob_headers = _saas_user("bob", "8502")

    alice_repo = saas_env / alice.id / "repo"
    (alice_repo / "src").mkdir(parents=True)
    (alice_repo / "src" / "Order.java").write_text("class Order {}\n", encoding="utf-8")

    bob_repo = saas_env / bob.id / "repo"
    (bob_repo / "src").mkdir(parents=True)
    (bob_repo / "src" / "Order.java").write_text("class Order {}\n", encoding="utf-8")

    # A host path outside every sandbox is refused with the Phase 8 containment code.
    host = _call(
        client, "kodo_scan_workspace", {"rootPath": str(saas_env.parent)}, headers=alice_headers
    )
    host_error = json.loads(host["content"][0]["text"])["error"]
    assert host["isError"] is True
    assert host_error["code"] == "SAAS_PATH_FORBIDDEN"

    # Bob's sandbox is just as foreign to Alice.
    foreign = _call(
        client, "kodo_scan_workspace", {"rootPath": str(bob_repo)}, headers=alice_headers
    )
    foreign_error = json.loads(foreign["content"][0]["text"])["error"]
    assert foreign["isError"] is True
    assert foreign_error["code"] == "SAAS_PATH_FORBIDDEN"

    # Her own workspace is fine.
    own = _call(client, "kodo_scan_workspace", {"rootPath": str(alice_repo)}, headers=alice_headers)
    assert own["isError"] is False
    assert own["structuredContent"]["componentCount"] == 1


def test_saas_rate_limits_the_mcp_bucket(
    client: TestClient, saas_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KODO_RL_MCP_PER_MIN", "2")
    _, headers = _saas_user("alice", "8601")

    first = _rpc(client, "ping", headers=headers)
    second = _rpc(client, "ping", headers=headers)
    blocked = _rpc(client, "ping", headers=headers)

    assert first.status_code == 200, first.text
    assert first.headers["x-ratelimit-limit"] == "2"
    assert second.status_code == 200
    assert second.headers["x-ratelimit-remaining"] == "0"
    assert blocked.status_code == 429
    assert blocked.json()["code"] == "RATE_LIMITED"
    assert blocked.headers["retry-after"] == str(blocked.json()["retryAfterSeconds"])


def test_mcp_info_endpoint_reports_the_catalog(client: TestClient) -> None:
    body = client.get("/api/v1/mcp/info").json()

    assert body["enabled"] is True
    assert body["endpointPath"] == "/mcp"
    assert body["protocol"] == "streamable-http"
    assert body["toolCount"] == 7
    assert len(body["tools"]) == 7
    assert all(tool["readOnly"] is True for tool in body["tools"])
    assert body["mode"] == "local"
    assert body["saasRequiresAuth"] is False
    assert body["rateLimitPerMinute"] > 0
    assert body["protocolVersions"] == list(PROTOCOL_VERSIONS)


def test_disabling_mcp_returns_404_and_reports_it(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KODO_MCP_ENABLED", "false")

    response = _rpc(client, "initialize", {"protocolVersion": "2025-06-18"})
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "MCP_DISABLED"
    assert client.get(MCP_ENDPOINT_PATH).status_code == 404
    assert client.delete(MCP_ENDPOINT_PATH).status_code == 404

    info = client.get("/api/v1/mcp/info").json()
    assert info["enabled"] is False
    assert info["toolCount"] == 7
