"""Phase 8 SaaS foundation: persistence, tenant isolation, fail-closed gates and GitHub OAuth.

Every external call is mocked: GitHub OAuth goes through ``httpx.MockTransport`` and the database is
a per-test temporary SQLite file (see ``conftest.py``).
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.auth import github_oauth
from app.auth.jwt_utils import create_session_token
from app.config import ConfigurationError, get_settings, validate_startup
from app.db import repository
from app.db.engine import reset_engine
from app.main import app
from app.models.blueprint import BLUEPRINT_FILE_NAME, Blueprint


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture()
def saas_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    monkeypatch.setenv("KODO_MODE", "saas")
    monkeypatch.setenv("KODO_JWT_SECRET", "s" * 48)
    monkeypatch.setenv("KODO_WORKSPACES_DIR", str(tmp_path / "workspaces"))
    monkeypatch.setenv("KODO_DATABASE_URL", f"sqlite:///{(tmp_path / 'saas.db').as_posix()}")
    reset_engine()
    try:
        yield
    finally:
        reset_engine()


def _user_token(username: str, github_id: str) -> tuple[repository.UserRecord, str]:
    user = repository.upsert_github_user(
        github_id=github_id,
        username=username,
        display_name=username.title(),
        avatar_url=None,
        email=None,
    )
    return user, create_session_token(user.id, user.username)


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _write_source(root: Path, relative: str, content: str) -> Path:
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8", newline="\n")
    return target


# ------------------------------------------------------------------ persistent rollback


def test_rollback_snapshot_survives_a_process_restart(client: TestClient, tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    original = "package com.acme;\n\npublic class Order {\n    private String code;\n}\n"
    _write_source(root, "src/main/java/com/acme/Order.java", original)

    applied = client.post(
        "/api/v1/apply",
        json={
            "rootPath": str(root),
            "allowNonGit": True,
            "patches": [
                {
                    "filePath": "src/main/java/com/acme/Order.java",
                    "expectedSha256": _sha(original),
                    "proposedContent": original.replace("String code", "String reference"),
                }
            ],
        },
    )
    assert applied.status_code == 200, applied.text
    apply_id = applied.json()["applyId"]

    # Simulate a container restart: every connection and in-memory cache is discarded.
    reset_engine()
    assert "reference" in (root / "src/main/java/com/acme/Order.java").read_text(encoding="utf-8")

    rolled_back = client.post("/api/v1/apply/rollback", json={"applyId": apply_id})

    assert rolled_back.status_code == 200, rolled_back.text
    assert (root / "src/main/java/com/acme/Order.java").read_text(encoding="utf-8") == original


# ---------------------------------------------------------------- multi-tenant isolation


def test_audit_log_is_strictly_per_user(client: TestClient) -> None:
    user_a, token_a = _user_token("alice", "1001")
    user_b, token_b = _user_token("bob", "1002")

    repository.record_audit_event(user_a.id, "apply", "/a", "alice applied", 1, "success")
    repository.record_audit_event(user_b.id, "apply", "/b", "bob applied", 1, "success")

    alice = client.get("/api/v1/audit-log", headers=_auth(token_a))
    bob = client.get("/api/v1/audit-log", headers=_auth(token_b))

    assert [entry["summary"] for entry in alice.json()["entries"]] == ["alice applied"]
    assert [entry["summary"] for entry in bob.json()["entries"]] == ["bob applied"]


def test_user_cannot_rollback_another_users_apply(client: TestClient, tmp_path: Path) -> None:
    _, token_a = _user_token("alice", "2001")
    _, token_b = _user_token("bob", "2002")

    root = tmp_path / "shared"
    original = "class Order {}\n"
    _write_source(root, "Order.java", original)

    applied = client.post(
        "/api/v1/apply",
        headers=_auth(token_a),
        json={
            "rootPath": str(root),
            "allowNonGit": True,
            "patches": [
                {
                    "filePath": "Order.java",
                    "expectedSha256": _sha(original),
                    "proposedContent": "class Order { int total; }\n",
                }
            ],
        },
    )
    assert applied.status_code == 200, applied.text
    apply_id = applied.json()["applyId"]

    stolen = client.post(
        "/api/v1/apply/rollback",
        headers=_auth(token_b),
        json={"applyId": apply_id},
    )

    assert stolen.status_code == 404
    assert stolen.json()["detail"]["code"] == "UNKNOWN_APPLY"
    assert "total" in (root / "Order.java").read_text(encoding="utf-8")


def test_saas_users_cannot_touch_another_sandbox(
    client: TestClient, saas_env: None, tmp_path: Path
) -> None:
    alice, token_a = _user_token("alice", "3001")
    _, token_b = _user_token("bob", "3002")

    sandbox = tmp_path / "workspaces" / alice.id
    _write_source(sandbox, "src/Order.java", "class Order {}\n")

    scanned = client.post(
        "/api/v1/scan", headers=_auth(token_a), json={"path": str(sandbox)}
    )
    assert scanned.status_code == 200, scanned.text

    leaked_scan = client.post(
        "/api/v1/scan", headers=_auth(token_b), json={"path": str(sandbox)}
    )
    assert leaked_scan.status_code == 403
    assert leaked_scan.json()["detail"]["code"] == "SAAS_PATH_FORBIDDEN"

    leaked_file = client.get(
        "/api/v1/file",
        headers=_auth(token_b),
        params={"root": str(sandbox), "relPath": "src/Order.java"},
    )
    assert leaked_file.status_code == 403

    workspaces = client.get("/api/v1/workspaces", headers=_auth(token_a)).json()["workspaces"]
    assert workspaces
    workspace_id = workspaces[0]["id"]

    stolen_delete = client.delete(f"/api/v1/workspaces/{workspace_id}", headers=_auth(token_b))
    assert stolen_delete.status_code == 404
    assert stolen_delete.json()["detail"]["code"] == "UNKNOWN_WORKSPACE"
    assert sandbox.is_dir()


# -------------------------------------------------------------------------- SaaS gates


def test_saas_startup_requires_a_strong_jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KODO_MODE", "saas")
    monkeypatch.delenv("KODO_JWT_SECRET", raising=False)

    with pytest.raises(ConfigurationError):
        validate_startup()

    monkeypatch.setenv("KODO_JWT_SECRET", "too-short")
    with pytest.raises(ConfigurationError):
        validate_startup()


def test_saas_requires_authentication_and_blocks_host_paths(
    client: TestClient, saas_env: None, tmp_path: Path
) -> None:
    unauthenticated = client.post("/api/v1/scan", json={"path": str(tmp_path)})
    assert unauthenticated.status_code == 401
    assert unauthenticated.json()["detail"]["code"] == "UNAUTHORIZED"

    _, token = _user_token("alice", "4001")
    host_scan = client.post(
        "/api/v1/scan", headers=_auth(token), json={"path": str(tmp_path)}
    )
    assert host_scan.status_code == 403
    assert host_scan.json()["detail"]["code"] == "SAAS_PATH_FORBIDDEN"


def test_saas_disables_host_docker_control_but_keeps_generation(
    client: TestClient, saas_env: None, tmp_path: Path
) -> None:
    user, token = _user_token("alice", "5001")
    sandbox = tmp_path / "workspaces" / user.id
    _write_source(sandbox, "package.json", '{"name":"acme","version":"1.0.0"}\n')

    docker_status = client.get(
        "/api/v1/deploy/docker/status", headers=_auth(token), params={"root": str(sandbox)}
    )
    assert docker_status.status_code == 403
    assert docker_status.json()["detail"]["code"] == "DOCKER_CONTROL_DISABLED_IN_SAAS"

    dry_run = client.post(
        "/api/v1/deploy/dry-run",
        headers=_auth(token),
        json={
            "rootPath": str(sandbox),
            "projectName": "Acme",
            "stack": "nodejs",
            "appPort": 3000,
            "backingServices": [],
            "overwriteExisting": False,
        },
    )
    assert dry_run.status_code == 200, dry_run.text
    assert any(patch["filePath"] == "Dockerfile" for patch in dry_run.json()["patches"])


def test_local_mode_auth_me_exposes_the_seeded_user(client: TestClient) -> None:
    body = client.get("/api/v1/auth/me").json()

    assert body["mode"] == "local"
    assert body["authenticated"] is True
    assert body["user"]["id"] == "local"
    assert body["githubOAuthConfigured"] is False


def test_owner_can_delete_a_sandbox_workspace(
    client: TestClient, saas_env: None, tmp_path: Path
) -> None:
    user, token = _user_token("alice", "6001")
    sandbox = tmp_path / "workspaces" / user.id
    repo_dir = sandbox / "demo-repo"
    _write_source(repo_dir, "README.md", "# demo\n")
    workspace = repository.remember_workspace(user.id, name="demo", local_path=str(repo_dir))

    deleted = client.delete(f"/api/v1/workspaces/{workspace.id}", headers=_auth(token))

    assert deleted.status_code == 200
    assert deleted.json()["directoryRemoved"] is True
    assert not repo_dir.exists()
    assert client.get("/api/v1/workspaces", headers=_auth(token)).json()["workspaces"] == []


# ------------------------------------------------------------------------- GitHub OAuth


def test_github_login_reports_missing_oauth_configuration(client: TestClient) -> None:
    response = client.get("/api/v1/auth/github/login", follow_redirects=False)

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "OAUTH_NOT_CONFIGURED"


def _oauth_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/login/oauth/access_token":
            return httpx.Response(200, json={"access_token": "gho_test_token", "token_type": "bearer"})
        if request.url.path == "/user":
            assert request.headers["Authorization"] == "Bearer gho_test_token"
            return httpx.Response(
                200,
                json={
                    "id": 777,
                    "login": "octocat",
                    "name": "Octo Cat",
                    "avatar_url": "https://avatars.example/octo.png",
                    "email": "octo@example.com",
                },
            )
        return httpx.Response(404, json={"message": "unexpected call"})

    return httpx.MockTransport(handler)


def test_github_oauth_round_trip(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("KODO_GITHUB_CLIENT_ID", "client-id")
    monkeypatch.setenv("KODO_GITHUB_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("KODO_PUBLIC_URL", "http://localhost:3000")
    monkeypatch.setenv("KODO_WORKSPACES_DIR", str(tmp_path / "workspaces"))
    monkeypatch.setattr(github_oauth, "_transport", _oauth_transport())

    login = client.get("/api/v1/auth/github/login", follow_redirects=False)
    assert login.status_code == 302
    location = login.headers["location"]
    assert location.startswith("https://github.com/login/oauth/authorize?")
    state = client.cookies.get("kodo_oauth_state")
    assert state and f"state={state}" in location

    callback = client.get(
        "/api/v1/auth/github/callback",
        params={"code": "the-code", "state": state},
        follow_redirects=False,
    )
    assert callback.status_code == 302
    set_cookie = callback.headers.get("set-cookie", "")
    assert "kodo_session=" in set_cookie
    assert "HttpOnly" in set_cookie

    me = client.get("/api/v1/auth/me")
    body = me.json()
    assert body["authenticated"] is True
    assert body["user"]["username"] == "octocat"

    logout = client.post("/api/v1/auth/logout")
    assert logout.status_code == 200
    assert logout.json() == {"ok": True}


def test_github_oauth_rejects_a_mismatched_state(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KODO_GITHUB_CLIENT_ID", "client-id")
    monkeypatch.setenv("KODO_GITHUB_CLIENT_SECRET", "client-secret")
    monkeypatch.setattr(github_oauth, "_transport", _oauth_transport())

    client.get("/api/v1/auth/github/login", follow_redirects=False)
    rejected = client.get(
        "/api/v1/auth/github/callback",
        params={"code": "the-code", "state": "forged-state"},
        follow_redirects=False,
    )

    assert rejected.status_code == 400
    assert rejected.json()["detail"]["code"] == "OAUTH_STATE_MISMATCH"


# ------------------------------------------------------- blueprints and user settings


def _blueprint() -> Blueprint:
    return Blueprint(
        project_name="Acme Shop",
        stack="spring-boot",
        base_package_or_namespace="com.acme.shop",
        slices=[],
    )


def test_saved_blueprints_are_indexed_per_user(client: TestClient, tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    blueprint = _blueprint()
    (root / BLUEPRINT_FILE_NAME).write_text(blueprint.render(), encoding="utf-8")

    loaded = client.get("/api/v1/blueprint", params={"root": str(root)})
    assert loaded.status_code == 200
    assert loaded.json()["exists"] is True

    listed = client.get("/api/v1/blueprints")
    assert listed.status_code == 200
    entries = listed.json()["blueprints"]
    assert [entry["name"] for entry in entries] == ["Acme Shop"]
    assert entries[0]["stack"] == "spring-boot"
    assert entries[0]["blueprint"]["projectName"] == "Acme Shop"


def test_user_settings_round_trip_never_persists_secrets(client: TestClient) -> None:
    saved = client.put(
        "/api/v1/user/settings",
        json={"settings": {"baseUrl": "https://api.deepseek.com/v1", "codeModel": "deepseek-chat"}},
    )
    assert saved.status_code == 200

    loaded = client.get("/api/v1/user/settings")
    assert loaded.json()["settings"]["codeModel"] == "deepseek-chat"

    rejected = client.put(
        "/api/v1/user/settings",
        json={"settings": {"baseUrl": "https://x", "apiKey": "sk-super-secret"}},
    )
    assert rejected.status_code == 400
    assert rejected.json()["detail"]["code"] == "SECRET_NOT_ALLOWED"

    after = client.get("/api/v1/user/settings").json()["settings"]
    assert "apiKey" not in after
    assert after["codeModel"] == "deepseek-chat"


def test_database_url_is_configurable(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    target = "postgresql+psycopg://user:pass@db.example.com:5432/kodo"
    monkeypatch.setenv("KODO_DATABASE_URL", target)
    assert get_settings().database_url == target

    monkeypatch.delenv("KODO_DATABASE_URL")
    monkeypatch.setenv("KODO_DATA_DIR", str(tmp_path))
    assert get_settings().database_url == f"sqlite:///{(tmp_path / 'kodo.db').as_posix()}"
