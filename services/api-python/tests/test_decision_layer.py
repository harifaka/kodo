"""Phase 10 System 1 (Laya) decision layer tests â€” deterministic, zero live network.

Every `/v1/systemone` call is served by an ``httpx.MockTransport``; the database is the per-test
temporary SQLite file from ``conftest.py``. No Ollama/laya-serve server, Docker daemon or network is
required, and no test may write to the analysed workspace.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.auth.jwt_utils import create_session_token
from app.db import repository
from app.db.engine import reset_engine
from app.decision.client import (
    MAX_REQUEST_BYTES,
    SystemOneClient,
    set_transport_override,
)
from app.decision.client import (
    test_connection as probe_system_one,
)
from app.decision.config import SystemOneConfig
from app.decision.errors import SystemOneError
from app.decision.schemas import (
    AUDIT_TRIAGE_QUESTIONS,
    DIFF_SAFETY_QUESTIONS,
    MAX_CHOICE_OPTIONS,
    NEUTRAL_KEYS,
    QUESTION_SETS,
    TASK_ROUTER_QUESTIONS,
    question_payload,
    validate_question_set,
)
from app.decision.state_packer import (
    MAX_STATE_BYTES,
    dumps_state,
    pack_diff_state,
    pack_finding_state,
    pack_task_state,
    removed_signatures,
    state_size,
)
from app.main import app
from app.models.ir import (
    AuditFinding,
    WorkspaceIR,
)

Handler = Callable[[httpx.Request], httpx.Response]

LOCAL_USER = repository.LOCAL_USER_ID
CONTROLLER = "com.acme.shop.controller.OrderController"
REPOSITORY = "com.acme.shop.repository.OrderRepository"
SERVICE = "com.acme.shop.service.OrderService"


def _config(**overrides: Any) -> SystemOneConfig:
    base: dict[str, Any] = {
        "enabled": True,
        "base_url": "http://localhost:11434",
        "model": "laya",
        "api_key": "",
        "timeout_seconds": 5.0,
        "auto_threshold": 0.78,
    }
    base.update(overrides)
    return SystemOneConfig(**base)


@contextmanager
def mock_systemone(handler: Handler) -> Iterator[list[httpx.Request]]:
    calls: list[httpx.Request] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return handler(request)

    set_transport_override(httpx.MockTransport(wrapped))
    try:
        yield calls
    finally:
        set_transport_override(None)


def _answers(**choices: tuple[str, float]) -> Handler:
    """Answer every question with the matching typed choice (defaults to a neutral answer)."""

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        answers: dict[str, Any] = {}
        for question in payload["questions"]:
            options = [option["key"] for option in question.get("options", [])]
            key, confidence = choices.get(question["id"], ("uncertain", 0.55))
            if question["id"] == "reachability" and "reachability" not in choices:
                key, confidence = "ok", 0.99
            if key not in options and options:
                key = options[-1]
            others = [option for option in options if option != key]
            remaining = max(0.0, 1.0 - confidence)
            share = round(remaining / max(1, len(others)), 4)
            probabilities = {key: confidence, **{option: share for option in others}}
            answers[question["id"]] = {
                "answer": key,
                "probabilities": probabilities,
                "confidence": confidence,
            }
        return httpx.Response(
            200,
            json={"model": "laya-test", "answers": answers, "usage": {"total_tokens": 11}},
        )

    return handler


def _failing(error: Exception) -> Handler:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise error

    return handler


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def _finding(
    finding_id: str,
    rule_id: str,
    severity: str,
    node_ids: list[str],
    *,
    message: str = "Controller reaches a repository directly.",
) -> dict[str, Any]:
    return {
        "id": finding_id,
        "ruleId": rule_id,
        "severity": severity,
        "title": f"{rule_id} on {node_ids[0].rsplit('.', 1)[-1]}",
        "message": message,
        "suggestion": "Route the call through the service layer.",
        "nodeIds": node_ids,
        "edgeKeys": [],
        "filePath": "src/main/java/com/acme/shop/controller/OrderController.java",
    }


def _workspace_payload(root: Path, findings: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    findings = findings or [
        _finding(
            "LAYER_VIOLATION:controller->repository",
            "LAYER_VIOLATION",
            "error",
            [CONTROLLER, REPOSITORY],
        ),
        _finding(
            "GOD_CLASS:OrderService",
            "GOD_CLASS",
            "warning",
            [SERVICE],
            message="OrderService has 42 fields and 31 methods.",
        ),
    ]
    return {
        "name": "shop",
        "rootPath": str(root),
        "detectedStacks": ["spring-boot"],
        "nodes": [
            {
                "id": CONTROLLER,
                "name": "OrderController",
                "stack": "spring-boot",
                "layer": "controller",
                "kind": "class",
                "filePath": "src/main/java/com/acme/shop/controller/OrderController.java",
                "annotations": ["@RestController"],
                "fields": [{"name": "repository", "type": "OrderRepository"}],
                "methods": [{"name": "list", "returnType": "String", "parameters": []}],
            },
            {
                "id": REPOSITORY,
                "name": "OrderRepository",
                "stack": "spring-boot",
                "layer": "repository",
                "kind": "interface",
                "filePath": "src/main/java/com/acme/shop/repository/OrderRepository.java",
                "fields": [],
                "methods": [],
            },
            {
                "id": SERVICE,
                "name": "OrderService",
                "stack": "spring-boot",
                "layer": "service",
                "kind": "class",
                "filePath": "src/main/java/com/acme/shop/service/OrderService.java",
                "fields": [],
                "methods": [],
            },
        ],
        "relations": [
            {"sourceId": CONTROLLER, "targetId": REPOSITORY, "type": "depends_on"},
        ],
        "mermaidClassDiagram": "classDiagram",
        "warnings": [],
        "audit": {
            "score": 72,
            "summary": {"errors": 1, "warnings": 1, "info": 0},
            "findings": findings,
        },
    }


def _workspace_ir(root: Path, findings: list[dict[str, Any]] | None = None) -> WorkspaceIR:
    return WorkspaceIR.model_validate(_workspace_payload(root, findings))


def _user_token(username: str, github_id: str) -> str:
    user = repository.upsert_github_user(
        github_id=github_id,
        username=username,
        display_name=username.title(),
        avatar_url=None,
        email=None,
    )
    return create_session_token(user.id, user.username)


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "shop"
    source = root / "src" / "main" / "java" / "com" / "acme" / "shop" / "controller" / "OrderController.java"
    source.parent.mkdir(parents=True)
    source.write_text("public class OrderController {}\n", encoding="utf-8")
    return root


# --------------------------------------------------------------------------------------------
# Question schemas
# --------------------------------------------------------------------------------------------


def test_question_sets_are_bounded_and_have_neutral_fallbacks() -> None:
    for name, questions in QUESTION_SETS.items():
        validate_question_set(questions)
        assert questions, name
        for question in questions:
            assert question.type == "choice"
            assert 2 <= len(question.options) <= MAX_CHOICE_OPTIONS
            assert {option.key for option in question.options} & NEUTRAL_KEYS


def test_question_payload_is_deterministic_and_wire_shaped() -> None:
    payload = question_payload(AUDIT_TRIAGE_QUESTIONS)
    assert [item["id"] for item in payload] == ["risk_level", "fix_route", "needs_human_design"]
    assert list(payload[0]) == ["id", "type", "text", "options"]
    assert payload[0]["options"][0]["key"] == "critical_arch_risk"
    assert payload == question_payload(AUDIT_TRIAGE_QUESTIONS)
    assert len(TASK_ROUTER_QUESTIONS) == 3
    assert len(DIFF_SAFETY_QUESTIONS) == 3


# --------------------------------------------------------------------------------------------
# State packer
# --------------------------------------------------------------------------------------------


def test_finding_state_key_order_is_deterministic(workspace: Path) -> None:
    workspace_ir = _workspace_ir(workspace)
    finding = workspace_ir.audit.findings[0]

    first = pack_finding_state(finding, workspace_ir)
    second = pack_finding_state(finding, workspace_ir)

    assert dumps_state(first) == dumps_state(second)
    assert list(first) == ["kind", "stack", "workspace", "finding", "nodes"]
    assert list(first["workspace"]) == [
        "name",
        "stacks",
        "healthScore",
        "findings",
        "components",
        "relations",
    ]
    assert first["nodes"][0]["incoming"] == 0
    assert first["nodes"][0]["outgoing"] == 1
    assert first["finding"]["ruleId"] == "LAYER_VIOLATION"


def test_finding_state_is_clamped_to_the_budget(workspace: Path) -> None:
    huge = _finding(
        "GOD_CLASS:huge",
        "GOD_CLASS",
        "warning",
        [SERVICE],
        message="x" * 80_000,
    )
    workspace_ir = _workspace_ir(workspace, [huge])

    state = pack_finding_state(workspace_ir.audit.findings[0], workspace_ir)

    assert state_size(state) <= MAX_STATE_BYTES
    assert len(state["finding"]["message"]) < 80_000
    assert dumps_state(state) == dumps_state(pack_finding_state(workspace_ir.audit.findings[0], workspace_ir))


def test_task_state_is_compact_and_keeps_target_summary(workspace: Path) -> None:
    workspace_ir = _workspace_ir(workspace)

    state = pack_task_state("y" * 20_000, workspace_ir, SERVICE)

    assert state_size(state) <= MAX_STATE_BYTES
    assert list(state)[:3] == ["kind", "intent", "workspace"]
    assert state["target"]["name"] == "OrderService"
    plain = pack_task_state("Add email validation to OrderDto", workspace_ir)
    assert "target" not in plain


def test_diff_state_detects_removed_signatures_and_stays_in_budget(workspace: Path) -> None:
    original = (
        "public class OrderService {\n"
        "    public void keep() {}\n"
        "    public int removed(int value) {\n"
        "        return value * 2;\n"
        "    }\n"
        "}\n"
    )
    proposed = "public class OrderService {\n    public void keep() {}\n}\n"

    state = pack_diff_state(
        [
            {
                "file_path": "src/OrderService.java",
                "original_content": original,
                "proposed_content": proposed,
                "is_new_file": False,
            }
        ],
        _workspace_ir(workspace),
    )

    assert state["filesChanged"] == 1
    assert state["methodsRemoved"] is True
    assert "removed" in state["removedSignatures"]
    assert state["totalRemoved"] > 0
    assert list(state)[:6] == [
        "kind",
        "filesChanged",
        "totalAdded",
        "totalRemoved",
        "methodsRemoved",
        "removedSignatures",
    ]
    assert state_size(state) <= MAX_STATE_BYTES


def test_diff_state_clamps_a_huge_diff(workspace: Path) -> None:
    original = "\n".join(f"line {index} of original" for index in range(20_000))
    proposed = "\n".join(f"line {index} of rewritten" for index in range(20_000))

    state = pack_diff_state(
        [
            {
                "filePath": "src/Huge.java",
                "originalContent": original,
                "proposedContent": proposed,
                "isNewFile": False,
            }
        ]
    )

    assert state_size(state) <= MAX_STATE_BYTES
    assert state["files"][0]["path"] == "src/Huge.java"
    assert removed_signatures("--- a\n+++ b\n-    public void gone() {\n") == ["gone"]


# --------------------------------------------------------------------------------------------
# Client parsing & error codes
# --------------------------------------------------------------------------------------------


def _ask(coro):
    return asyncio.run(coro)


def test_client_parses_a_normal_response() -> None:
    async def scenario() -> None:
        with mock_systemone(_answers(risk_level=("critical_arch_risk", 0.93))) as calls:
            response = await SystemOneClient(_config()).ask(
                {"kind": "audit_finding"}, AUDIT_TRIAGE_QUESTIONS
            )

        assert len(calls) == 1
        assert calls[0].url.path == "/v1/systemone"
        payload = json.loads(calls[0].content)
        assert list(payload) == ["model", "state", "questions"]
        assert response.model == "laya-test"
        assert response.answers["risk_level"].answer == "critical_arch_risk"
        assert response.answers["risk_level"].confidence == 0.93
        assert response.answers["risk_level"].probabilities["critical_arch_risk"] == 0.93
        assert response.abstain is True  # the other questions defaulted to `uncertain`

    _ask(scenario())


def test_client_accepts_probabilities_without_explicit_confidence() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "laya-serve-1",
                "answers": {
                    "risk_level": {
                        "answer": "moderate_maintainability",
                        "probabilities": {"moderate_maintainability": 0.81, "uncertain": 0.19},
                    }
                },
                "abstain": False,
                "route": "deterministic_ast",
                "prediction_set": [{"key": "moderate_maintainability"}],
            },
        )

    async def scenario() -> None:
        with mock_systemone(handler):
            response = await SystemOneClient(_config()).ask(
                {"kind": "audit_finding"}, AUDIT_TRIAGE_QUESTIONS
            )

        assert response.model == "laya-serve-1"
        assert response.answers["risk_level"].confidence == 0.81
        assert response.route == "deterministic_ast"
        assert response.prediction_set == [{"key": "moderate_maintainability"}]

    _ask(scenario())


def test_client_maps_timeouts_and_unreachable_servers() -> None:
    async def scenario() -> None:
        with mock_systemone(_failing(httpx.ReadTimeout("slow"))):
            with pytest.raises(SystemOneError) as timeout:
                await SystemOneClient(_config()).ask({"kind": "ping"}, AUDIT_TRIAGE_QUESTIONS)
        assert timeout.value.code == "SYSTEMONE_TIMEOUT"

        with mock_systemone(_failing(httpx.ConnectError("refused"))):
            with pytest.raises(SystemOneError) as unreachable:
                await SystemOneClient(_config()).ask({"kind": "ping"}, AUDIT_TRIAGE_QUESTIONS)
        assert unreachable.value.code == "SYSTEMONE_UNREACHABLE"

    _ask(scenario())


def test_client_maps_auth_errors_and_invalid_bodies() -> None:
    async def scenario() -> None:
        with mock_systemone(lambda _request: httpx.Response(401, json={"error": "bad key"})):
            with pytest.raises(SystemOneError) as unauthorized:
                await SystemOneClient(_config()).ask({"kind": "ping"}, AUDIT_TRIAGE_QUESTIONS)
        assert unauthorized.value.code == "SYSTEMONE_UNAUTHORIZED"

        with mock_systemone(lambda _request: httpx.Response(200, json={"model": "laya", "answers": {}})):
            with pytest.raises(SystemOneError) as invalid:
                await SystemOneClient(_config()).ask({"kind": "ping"}, AUDIT_TRIAGE_QUESTIONS)
        assert invalid.value.code == "SYSTEMONE_INVALID_RESPONSE"

    _ask(scenario())


def test_client_rejects_disabled_config_without_network() -> None:
    async def scenario() -> None:
        with mock_systemone(_answers()) as calls:
            with pytest.raises(SystemOneError) as disabled:
                await SystemOneClient(_config(enabled=False)).ask(
                    {"kind": "ping"}, AUDIT_TRIAGE_QUESTIONS
                )

        assert disabled.value.code == "SYSTEMONE_DISABLED"
        assert calls == []

    _ask(scenario())


def test_request_never_exceeds_the_wire_budget(workspace: Path) -> None:
    workspace_ir = _workspace_ir(workspace)
    huge = _finding(
        "GOD_CLASS:huge",
        "GOD_CLASS",
        "warning",
        [SERVICE],
        message="z" * 60_000,
    )
    state = pack_finding_state(AuditFinding.model_validate(huge), workspace_ir)

    async def scenario() -> None:
        with mock_systemone(_answers()) as calls:
            await SystemOneClient(_config()).ask(state, AUDIT_TRIAGE_QUESTIONS)

        body = calls[0].content
        payload = json.loads(body)
        assert len(body) <= MAX_REQUEST_BYTES
        assert len(json.dumps(payload["state"], separators=(",", ":")).encode("utf-8")) <= MAX_STATE_BYTES

    _ask(scenario())


def test_connection_probe_reports_latency_model_and_provider() -> None:
    async def scenario() -> None:
        with mock_systemone(_answers()):
            probe = await probe_system_one(_config(base_url="http://ollama:11434"))

        assert probe.reachable is True
        assert probe.model == "laya-test"
        assert probe.provider_hint == "ollama"
        assert probe.latency_ms >= 0

        disabled = await probe_system_one(_config(enabled=False))
        assert disabled.reachable is False
        assert disabled.error_code == "SYSTEMONE_DISABLED"

    _ask(scenario())


# --------------------------------------------------------------------------------------------
# Audit triage
# --------------------------------------------------------------------------------------------


def test_triage_audit_persists_tenant_scoped_adrs(
    client: TestClient, workspace: Path
) -> None:
    before = _snapshot(workspace)
    handler = _answers(
        risk_level=("critical_arch_risk", 0.91),
        fix_route=("deterministic_ast", 0.9),
        needs_human_design=("no_mechanical_fix", 0.88),
    )

    with mock_systemone(handler) as calls:
        response = client.post(
            "/api/v1/decision/triage-audit",
            json={
                "rootPath": str(workspace),
                "workspaceIr": _workspace_payload(workspace),
                "systemOneConfig": {"baseUrl": "http://localhost:11434", "model": "laya"},
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["available"] is True
    assert body["model"] == "laya-test"
    assert len(body["items"]) == 2
    assert len(calls) == 2
    # Highest severity first, deterministic rank.
    assert body["items"][0]["findingId"].startswith("LAYER_VIOLATION")
    assert body["items"][0]["riskLevel"] == "critical_arch_risk"
    assert body["items"][0]["recommendedRoute"] == "deterministic_ast"
    assert body["items"][0]["confidence"] == pytest.approx(0.88)
    assert body["items"][0]["escalatedToSystem2"] is False
    assert body["items"][0]["priority"] > body["items"][1]["priority"]

    rows = repository.list_decision_records(LOCAL_USER)
    assert len(rows) == 2
    assert all(row.decision_type == "audit_triage" for row in rows)
    assert all(row.feedback_status == "pending" for row in rows)
    assert all(row.workspace_path == str(workspace.resolve()) for row in rows)

    # Deterministic state key order survives persistence and no workspace byte changed.
    state = json.loads(rows[0].state_json)
    assert list(state)[:2] == ["kind", "stack"]
    assert _snapshot(workspace) == before


def test_triage_escalates_low_confidence_findings(client: TestClient, workspace: Path) -> None:
    handler = _answers(
        risk_level=("low_boilerplate", 0.95),
        fix_route=("deterministic_ast", 0.41),
        needs_human_design=("no_mechanical_fix", 0.95),
    )

    with mock_systemone(handler):
        response = client.post(
            "/api/v1/decision/triage-audit",
            json={"rootPath": str(workspace), "workspaceIr": _workspace_payload(workspace)},
        )

    body = response.json()
    assert body["available"] is True
    assert body["items"][0]["escalatedToSystem2"] is True
    assert body["items"][0]["recommendedRoute"] == "deepseek_refactor"
    assert "confidence" in body["warning"]


def test_triage_honours_finding_filter_and_caps_at_fifteen(
    client: TestClient, workspace: Path
) -> None:
    findings = [
        _finding(f"GOD_CLASS:svc{index}", "GOD_CLASS", "warning", [SERVICE]) for index in range(20)
    ]
    payload = _workspace_payload(workspace, findings)

    with mock_systemone(_answers(risk_level=("low_boilerplate", 0.9))) as calls:
        capped = client.post(
            "/api/v1/decision/triage-audit",
            json={"rootPath": str(workspace), "workspaceIr": payload},
        )
    assert capped.status_code == 200
    assert len(capped.json()["items"]) == 15
    assert len(calls) == 15

    with mock_systemone(_answers()) as filtered_calls:
        filtered = client.post(
            "/api/v1/decision/triage-audit",
            json={
                "rootPath": str(workspace),
                "workspaceIr": payload,
                "findingIds": ["GOD_CLASS:svc3", "GOD_CLASS:svc7"],
            },
        )
    assert len(filtered.json()["items"]) == 2
    assert len(filtered_calls) == 2


def test_triage_degrades_gracefully_when_system_one_is_offline(
    client: TestClient, workspace: Path
) -> None:
    with mock_systemone(_failing(httpx.ConnectError("refused"))):
        response = client.post(
            "/api/v1/decision/triage-audit",
            json={"rootPath": str(workspace), "workspaceIr": _workspace_payload(workspace)},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["available"] is False
    assert body["items"] == []
    assert body["warning"].startswith("SYSTEMONE_UNREACHABLE")
    assert repository.list_decision_records(LOCAL_USER) == []


def test_triage_timeout_is_reported_not_raised(client: TestClient, workspace: Path) -> None:
    with mock_systemone(_failing(httpx.ReadTimeout("slow"))):
        response = client.post(
            "/api/v1/decision/triage-audit",
            json={"rootPath": str(workspace), "workspaceIr": _workspace_payload(workspace)},
        )

    assert response.status_code == 200
    assert response.json()["available"] is False
    assert response.json()["warning"].startswith("SYSTEMONE_TIMEOUT")


def test_disabled_system_one_never_calls_the_network(client: TestClient, workspace: Path) -> None:
    with mock_systemone(_answers()) as calls:
        response = client.post(
            "/api/v1/decision/triage-audit",
            json={
                "rootPath": str(workspace),
                "workspaceIr": _workspace_payload(workspace),
                "systemOneConfig": {"enabled": False},
            },
        )
        probe = client.post("/api/v1/decision/test-connection", json={"systemOneConfig": {"enabled": False}})

    assert response.status_code == 200
    assert response.json()["available"] is False
    assert response.json()["warning"].startswith("SYSTEMONE_DISABLED")
    assert calls == []
    assert probe.status_code == 200
    assert probe.json()["reachable"] is False
    assert probe.json()["errorCode"] == "SYSTEMONE_DISABLED"


# --------------------------------------------------------------------------------------------
# Task router
# --------------------------------------------------------------------------------------------


def test_route_task_recommends_a_deterministic_path(client: TestClient, workspace: Path) -> None:
    handler = _answers(
        execution_path=("deterministic_ast", 0.93),
        blast_radius=("single_file_local", 0.9),
        escalate_to_system2=("act_system1_deterministic", 0.91),
    )

    with mock_systemone(handler):
        response = client.post(
            "/api/v1/decision/route-task",
            json={
                "rootPath": str(workspace),
                "intent": "Add email validation to OrderDto",
                "workspaceIr": _workspace_payload(workspace),
                "targetNodeId": CONTROLLER,
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["available"] is True
    assert body["adrId"]
    assert body["recommendedRoute"] == "deterministic_ast"
    assert body["blastRadius"] == "single_file_local"
    assert body["escalateToSystem2"] is False
    assert body["confidence"] == pytest.approx(0.9)
    assert "deterministic_ast" in body["rationale"]

    rows = repository.list_decision_records(LOCAL_USER, decision_type="task_route")
    assert len(rows) == 1
    assert rows[0].subject == "Task: Add email validation to OrderDto"
    assert rows[0].recommended_route == "deterministic_ast"


def test_route_task_escalates_low_confidence_to_system_2(client: TestClient, workspace: Path) -> None:
    handler = _answers(
        execution_path=("deterministic_ast", 0.52),
        blast_radius=("cross_layer_slice", 0.55),
        escalate_to_system2=("act_system1_deterministic", 0.52),
    )

    with mock_systemone(handler):
        body = client.post(
            "/api/v1/decision/route-task",
            json={
                "rootPath": str(workspace),
                "intent": "Split billing into two services",
                "workspaceIr": _workspace_payload(workspace),
            },
        ).json()

    assert body["available"] is True
    assert body["recommendedRoute"] == "deepseek_reasoning"
    assert body["escalateToSystem2"] is True
    assert "below the 0.78" in body["rationale"]


def test_route_task_abstain_forces_human_review(client: TestClient, workspace: Path) -> None:
    def abstaining(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        answers = {
            question["id"]: {
                "answer": "uncertain",
                "probabilities": {"uncertain": 0.99},
                "confidence": 0.99,
            }
            for question in payload["questions"]
        }
        return httpx.Response(200, json={"model": "laya", "answers": answers, "abstain": True})

    with mock_systemone(abstaining):
        body = client.post(
            "/api/v1/decision/route-task",
            json={
                "rootPath": str(workspace),
                "intent": "Rearchitect the checkout flow",
                "workspaceIr": _workspace_payload(workspace),
            },
        ).json()

    assert body["recommendedRoute"] == "human_review"
    assert body["escalateToSystem2"] is False


def test_route_task_escalation_answer_promotes_a_deterministic_route(
    client: TestClient, workspace: Path
) -> None:
    handler = _answers(
        execution_path=("deterministic_ast", 0.96),
        blast_radius=("single_file_local", 0.95),
        escalate_to_system2=("escalate_system2_deepseek", 0.9),
    )

    with mock_systemone(handler):
        body = client.post(
            "/api/v1/decision/route-task",
            json={
                "rootPath": str(workspace),
                "intent": "Refactor the pricing calculation",
                "workspaceIr": _workspace_payload(workspace),
            },
        ).json()

    assert body["recommendedRoute"] == "deepseek_reasoning"
    assert body["escalateToSystem2"] is True


def test_route_task_offline_returns_a_safe_fallback(client: TestClient, workspace: Path) -> None:
    with mock_systemone(_failing(httpx.ConnectError("refused"))):
        response = client.post(
            "/api/v1/decision/route-task",
            json={
                "rootPath": str(workspace),
                "intent": "Add email validation to OrderDto",
                "workspaceIr": _workspace_payload(workspace),
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["available"] is False
    assert body["adrId"] is None
    assert body["recommendedRoute"] == "human_review"
    assert body["warning"].startswith("SYSTEMONE_UNREACHABLE")
    assert repository.list_decision_records(LOCAL_USER) == []


# --------------------------------------------------------------------------------------------
# Pre-diff safety gate
# --------------------------------------------------------------------------------------------


def _diff_payload(workspace: Path) -> dict[str, Any]:
    return {
        "rootPath": str(workspace),
        "patches": [
            {
                "filePath": "src/main/java/com/acme/shop/service/OrderService.java",
                "originalContent": "public class OrderService {\n    public int total() { return 1; }\n}\n",
                "proposedContent": "public class OrderService {\n    public int total() { return 2; }\n}\n",
                "isNewFile": False,
            }
        ],
        "workspaceIr": _workspace_payload(workspace),
    }


def test_screen_diff_flags_business_logic_loss(client: TestClient, workspace: Path) -> None:
    before = _snapshot(workspace)
    handler = _answers(
        logic_deletion_risk=("possible_logic_loss", 0.92),
        layer_boundary_risk=("clean_boundaries", 0.9),
        review_priority=("high_risk_block_advised", 0.9),
    )

    with mock_systemone(handler):
        response = client.post("/api/v1/decision/screen-diff", json=_diff_payload(workspace))

    assert response.status_code == 200
    body = response.json()
    assert body["available"] is True
    assert body["adrId"]
    assert body["status"] == "high_risk"
    assert "possible_logic_loss" in body["flags"]
    assert "high_risk_block_advised" in body["flags"]
    assert "Advisory only" in body["advisoryNote"]

    rows = repository.list_decision_records(LOCAL_USER, decision_type="diff_safety")
    assert len(rows) == 1
    assert rows[0].subject == "Diff: 1 file"
    assert rows[0].recommended_route == "high_risk"
    assert _snapshot(workspace) == before


def test_screen_diff_passes_a_routine_change(client: TestClient, workspace: Path) -> None:
    handler = _answers(
        logic_deletion_risk=("safe_preserved", 0.94),
        layer_boundary_risk=("clean_boundaries", 0.93),
        review_priority=("routine_quick_check", 0.9),
    )

    with mock_systemone(handler):
        body = client.post("/api/v1/decision/screen-diff", json=_diff_payload(workspace)).json()

    assert body["status"] == "pass"
    assert body["flags"] == []
    assert body["confidence"] == pytest.approx(0.9)


def test_screen_diff_offline_is_caution_and_never_blocks(client: TestClient, workspace: Path) -> None:
    with mock_systemone(_failing(httpx.ConnectError("refused"))):
        response = client.post("/api/v1/decision/screen-diff", json=_diff_payload(workspace))

    assert response.status_code == 200
    body = response.json()
    assert body["available"] is False
    assert body["status"] == "caution"
    assert body["adrId"] is None
    assert body["warning"].startswith("SYSTEMONE_UNREACHABLE")
    assert repository.list_decision_records(LOCAL_USER) == []


# --------------------------------------------------------------------------------------------
# ADR list, feedback, training export and tenant isolation
# --------------------------------------------------------------------------------------------


def _seed_adrs(client: TestClient, workspace: Path, count: int = 2) -> list[dict[str, Any]]:
    findings = [
        _finding(f"GOD_CLASS:svc{index}", "GOD_CLASS", "warning", [SERVICE]) for index in range(count)
    ]
    with mock_systemone(_answers(risk_level=("moderate_maintainability", 0.9))):
        body = client.post(
            "/api/v1/decision/triage-audit",
            json={"rootPath": str(workspace), "workspaceIr": _workspace_payload(workspace, findings)},
        ).json()
    return body["items"]


def test_decisions_are_listed_newest_first_and_filterable(
    client: TestClient, workspace: Path
) -> None:
    items = _seed_adrs(client, workspace, count=2)

    listed = client.get("/api/v1/decisions", params={"rootPath": str(workspace)})
    assert listed.status_code == 200
    decisions = listed.json()["decisions"]
    assert len(decisions) == 2
    assert {decision["id"] for decision in decisions} == {item["adrId"] for item in items}
    assert decisions[0]["decisionType"] == "audit_triage"
    assert decisions[0]["answers"]["risk_level"]["answer"] == "moderate_maintainability"

    assert client.get("/api/v1/decisions", params={"decisionType": "task_route"}).json()[
        "decisions"
    ] == []
    assert client.get("/api/v1/decisions", params={"rootPath": str(workspace / "other")}).json()[
        "decisions"
    ] == []


def test_feedback_updates_the_adr_and_records_an_audit_event(
    client: TestClient, workspace: Path
) -> None:
    items = _seed_adrs(client, workspace, count=1)
    adr_id = items[0]["adrId"]

    accepted = client.post(
        f"/api/v1/decisions/{adr_id}/feedback",
        json={"status": "accepted", "note": "Matches our layer policy."},
    )
    assert accepted.status_code == 200
    assert accepted.json()["feedbackStatus"] == "accepted"
    assert accepted.json()["feedbackNote"] == "Matches our layer policy."
    assert accepted.json()["feedbackAt"] is not None

    overridden = client.post(
        f"/api/v1/decisions/{adr_id}/feedback",
        json={"status": "overridden", "overrideRoute": "human_review", "note": "Architect will decide."},
    )
    assert overridden.status_code == 200
    assert overridden.json()["feedbackStatus"] == "overridden"
    assert overridden.json()["overrideRoute"] == "human_review"

    events = [entry for entry in client.get("/api/v1/audit-log").json()["entries"]
              if entry["action"] == "decision_feedback"]
    assert len(events) == 2


def test_feedback_rejects_unknown_adr_and_unsupported_status(
    client: TestClient, workspace: Path
) -> None:
    missing = client.post(
        "/api/v1/decisions/does-not-exist/feedback", json={"status": "accepted"}
    )
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "UNKNOWN_DECISION"

    items = _seed_adrs(client, workspace, count=1)
    invalid = client.post(
        f"/api/v1/decisions/{items[0]['adrId']}/feedback", json={"status": "pending"}
    )
    assert invalid.status_code == 422


def test_training_export_emits_confirmed_jsonl(client: TestClient, workspace: Path) -> None:
    items = _seed_adrs(client, workspace, count=2)
    accepted_id, overridden_id = items[0]["adrId"], items[1]["adrId"]
    client.post(f"/api/v1/decisions/{accepted_id}/feedback", json={"status": "accepted"})
    client.post(
        f"/api/v1/decisions/{overridden_id}/feedback",
        json={"status": "overridden", "overrideRoute": "human_review", "note": "Needs design review."},
    )

    response = client.get("/api/v1/decisions/export-training")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")
    assert "kodo-laya-training.jsonl" in response.headers["content-disposition"]
    lines = [json.loads(line) for line in response.text.splitlines() if line.strip()]
    assert len(lines) == 2
    assert {line["feedback_status"] for line in lines} == {"accepted", "overridden"}
    for line in lines:
        assert list(line) == [
            "state",
            "questions",
            "confirmed_answers",
            "feedback_status",
            "note",
        ]
        assert list(line["state"])[0] == "kind"
        assert [question["id"] for question in line["questions"]] == [
            "risk_level",
            "fix_route",
            "needs_human_design",
        ]
    override_line = next(line for line in lines if line["feedback_status"] == "overridden")
    assert override_line["confirmed_answers"]["fix_route"]["answer"] == "human_review"
    assert override_line["note"] == "Needs design review."


def test_cross_tenant_isolation_for_read_feedback_and_export(
    client: TestClient, workspace: Path
) -> None:
    items = _seed_adrs(client, workspace, count=1)
    adr_id = items[0]["adrId"]
    client.post(f"/api/v1/decisions/{adr_id}/feedback", json={"status": "accepted"})
    other = _auth(_user_token("mallory", "github-42"))

    assert client.get("/api/v1/decisions", headers=other).json()["decisions"] == []
    hidden = client.post(
        f"/api/v1/decisions/{adr_id}/feedback", headers=other, json={"status": "overridden"}
    )
    assert hidden.status_code == 404
    exported = client.get("/api/v1/decisions/export-training", headers=other)
    assert exported.status_code == 200
    assert exported.text == ""
    # The owner's rows are untouched by the other tenant's attempt.
    assert repository.get_decision_record(LOCAL_USER, adr_id).feedback_status == "accepted"


def test_saas_sandbox_blocks_triage_outside_the_user_sandbox(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, workspace: Path
) -> None:
    monkeypatch.setenv("KODO_MODE", "saas")
    monkeypatch.setenv("KODO_JWT_SECRET", "s" * 48)
    monkeypatch.setenv("KODO_WORKSPACES_DIR", str(tmp_path / "sandboxes"))
    reset_engine()
    try:
        with mock_systemone(_answers()) as calls:
            response = client.post(
                "/api/v1/decision/triage-audit",
                headers=_auth(_user_token("mallory", "github-99")),
                json={"rootPath": str(workspace), "workspaceIr": _workspace_payload(workspace)},
            )
    finally:
        reset_engine()

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "SAAS_PATH_FORBIDDEN"
    assert calls == []

