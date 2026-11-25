"""Phase 13 production SaaS hardening: Alembic migrations, quotas, TTL cleanup, rate limiting.

Everything here is hermetic: temporary SQLite files, temporary workspace sandboxes and an
in-memory rate-limiter instance reset between cases. No network and no Docker are required.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text

from alembic import command
from app.auth.jwt_utils import create_session_token
from app.config import quota_enabled, rate_limit_enabled
from app.db import repository
from app.db.engine import (
    ALEMBIC_INI_PATH,
    INITIAL_REVISION,
    alembic_config,
    init_db,
    reset_engine,
    run_migrations,
    session_scope,
)
from app.db.models import Workspace
from app.main import app
from app.services import quota as quota_service
from app.services.quota import (
    CLONE_SIZE_LIMIT_EXCEEDED,
    WORKSPACE_QUOTA_EXCEEDED,
    cleanup_stale_workspaces,
    compute_dir_size_bytes,
    enforce_post_clone_size,
    get_user_storage_usage,
    is_strictly_inside_sandbox,
)

HEAD_REVISION = "0002_workspace_size_and_activity"
EXPECTED_TABLES = {
    "users",
    "workspaces",
    "rollback_batches",
    "audit_events",
    "saved_blueprints",
    "user_settings",
    "architecture_decision_records",
}


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
def saas_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Path]:
    """Sandboxed SaaS mode with its own SQLite file and workspace root."""
    monkeypatch.setenv("KODO_MODE", "saas")
    monkeypatch.setenv("KODO_JWT_SECRET", "s" * 48)
    monkeypatch.setenv("KODO_WORKSPACES_DIR", str(tmp_path / "workspaces"))
    monkeypatch.setenv("KODO_DATABASE_URL", f"sqlite:///{(tmp_path / 'saas.db').as_posix()}")
    reset_engine()
    try:
        yield tmp_path / "workspaces"
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


def _write(root: Path, relative: str, content: str = "class Order {}\n") -> Path:
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8", newline="\n")
    return target


# ------------------------------------------------------------------------------ Alembic


def test_alembic_fresh_upgrade_builds_the_full_schema(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "fresh.db"
    url = f"sqlite:///{database.as_posix()}"
    monkeypatch.setenv("KODO_DATABASE_URL", url)

    # No `sqlalchemy.url` in the Config on purpose: env.py must read KODO_DATABASE_URL itself.
    config = alembic_config()
    assert config.get_main_option("sqlalchemy.url") in (None, "")
    command.upgrade(config, "head")

    engine = create_engine(url)
    try:
        inspector = inspect(engine)
        assert EXPECTED_TABLES <= set(inspector.get_table_names())
        columns = {column["name"] for column in inspector.get_columns("workspaces")}
        assert {"size_bytes", "last_accessed_at"} <= columns
        with engine.connect() as connection:
            recorded = connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
        assert recorded == HEAD_REVISION
    finally:
        engine.dispose()


def test_legacy_create_all_database_is_stamped_then_upgraded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A Phase 8/10 database (tables, no alembic_version, no size_bytes) upgrades cleanly."""
    database = tmp_path / "legacy.db"
    url = f"sqlite:///{database.as_posix()}"
    monkeypatch.setenv("KODO_DATABASE_URL", url)
    reset_engine()

    legacy = create_engine(url)
    config = alembic_config(url)
    with legacy.connect() as connection:
        config.attributes["connection"] = connection
        # Build exactly the baseline schema, then hide the version table as create_all would.
        command.upgrade(config, "0001_initial_schema")
        connection.execute(text("DROP TABLE alembic_version"))
        connection.execute(
            text(
                "INSERT INTO users (id, username, created_at) "
                "VALUES ('legacy-user', 'legacy', '2024-01-01 00:00:00')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO workspaces (id, user_id, name, local_path, created_at) "
                "VALUES ('legacy-ws', 'legacy-user', 'proj', '/tmp/proj', '2024-01-01 00:00:00')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO architecture_decision_records "
                "(id, user_id, workspace_path, decision_type, subject, model, recommended_route, "
                " confidence, latency_ms, state_json, answers_json, feedback_status, created_at) "
                "VALUES ('adr-1', 'legacy-user', '', 'triage', 'subject', 'laya', 'auto', 0.9, 12, "
                " '{}', '{}', 'pending', '2024-01-01 00:00:00')"
            )
        )
        connection.commit()
    legacy.dispose()

    upgraded = create_engine(url)
    try:
        assert "alembic_version" not in inspect(upgraded).get_table_names()
        run_migrations(upgraded)

        inspector = inspect(upgraded)
        columns = {column["name"] for column in inspector.get_columns("workspaces")}
        assert {"size_bytes", "last_accessed_at"} <= columns
        with upgraded.connect() as connection:
            assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar() == HEAD_REVISION
            assert connection.execute(text("SELECT id FROM users")).scalars().all() == ["legacy-user"]
            assert connection.execute(text("SELECT id FROM architecture_decision_records")).scalars().all() == [
                "adr-1"
            ]
            assert connection.execute(text("SELECT size_bytes FROM workspaces")).scalar() == 0

        # Idempotent: a second startup is a no-op.
        run_migrations(upgraded)
    finally:
        upgraded.dispose()


def test_legacy_phase8_database_gains_later_tables(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A Phase 8 install (no ADR table, no version table) still converges on the full schema."""
    database = tmp_path / "phase8.db"
    url = f"sqlite:///{database.as_posix()}"
    monkeypatch.setenv("KODO_DATABASE_URL", url)
    reset_engine()

    legacy = create_engine(url)
    config = alembic_config(url)
    with legacy.connect() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "0001_initial_schema")
        connection.execute(text("DROP TABLE architecture_decision_records"))
        connection.execute(text("DROP TABLE alembic_version"))
        connection.commit()
    legacy.dispose()

    upgraded = create_engine(url)
    try:
        run_migrations(upgraded)
        inspector = inspect(upgraded)
        assert EXPECTED_TABLES <= set(inspector.get_table_names())
        columns = {column["name"] for column in inspector.get_columns("workspaces")}
        assert {"size_bytes", "last_accessed_at"} <= columns
        with upgraded.connect() as connection:
            assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar() == HEAD_REVISION
    finally:
        upgraded.dispose()


def test_init_db_migrates_and_seeds_when_auto_migrate_is_enabled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("KODO_DB_AUTO_MIGRATE", "true")
    reset_engine()

    init_db()

    url = os.environ["KODO_DATABASE_URL"]
    engine = create_engine(url)
    try:
        inspector = inspect(engine)
        assert "alembic_version" in inspector.get_table_names()
        columns = {column["name"] for column in inspector.get_columns("workspaces")}
        assert {"size_bytes", "last_accessed_at"} <= columns
    finally:
        engine.dispose()
    assert repository.get_user("local") is not None


# ------------------------------------------------------------------------------- quotas


def test_storage_usage_endpoint_reports_quota(
    client: TestClient, saas_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KODO_USER_QUOTA_MB", "42")
    monkeypatch.setenv("KODO_MAX_WORKSPACES_PER_USER", "7")
    monkeypatch.setenv("KODO_WORKSPACE_TTL_HOURS", "12")
    user, token = _user_token("alice", "7001")

    sandbox = saas_env / user.id
    _write(sandbox / "repo", "README.md", "x" * 4096)
    repository.remember_workspace(user.id, name="repo", local_path=str(sandbox / "repo"))

    response = client.get("/api/v1/workspaces/storage", headers=_auth(token))

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["enabled"] is True
    assert payload["quotaBytes"] == 42 * 1024 * 1024
    assert payload["workspaceCount"] == 1
    assert payload["maxWorkspaces"] == 7
    assert payload["ttlHours"] == 12
    assert 4096 <= payload["usedBytes"] < 42 * 1024 * 1024


def test_storage_usage_is_disabled_in_local_mode(client: TestClient) -> None:
    payload = client.get("/api/v1/workspaces/storage").json()

    assert payload["enabled"] is False
    assert payload["workspaceCount"] == 0
    assert quota_enabled() is False


def test_pre_clone_quota_rejects_when_the_workspace_cap_is_reached(
    client: TestClient, saas_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KODO_MAX_WORKSPACES_PER_USER", "1")
    user, token = _user_token("alice", "7101")
    sandbox = saas_env / user.id
    _write(sandbox / "repo", "README.md")
    repository.remember_workspace(user.id, name="repo", local_path=str(sandbox / "repo"))

    response = client.post(
        "/api/v1/git/clone",
        headers=_auth(token),
        json={"repoUrl": "https://github.com/octocat/Hello-World"},
    )

    assert response.status_code == 413, response.text
    assert response.json()["detail"]["code"] == WORKSPACE_QUOTA_EXCEEDED
    assert "Delete one" in response.json()["detail"]["message"]


def test_pre_clone_quota_rejects_when_disk_is_full(
    client: TestClient, saas_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KODO_USER_QUOTA_MB", "1")
    user, token = _user_token("alice", "7102")
    sandbox = saas_env / user.id
    # 2 MB of sandboxed data against a 1 MB quota.
    _write(sandbox / "repo", "big.bin", "x" * (2 * 1024 * 1024))

    response = client.post(
        "/api/v1/git/clone",
        headers=_auth(token),
        json={"repoUrl": "https://github.com/octocat/Hello-World"},
    )

    assert response.status_code == 507, response.text
    assert response.json()["detail"]["code"] == WORKSPACE_QUOTA_EXCEEDED
    assert "storage is full" in response.json()["detail"]["message"]


def test_post_clone_size_cap_deletes_the_oversized_clone(
    saas_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KODO_MAX_CLONE_SIZE_MB", "1")
    monkeypatch.setenv("KODO_USER_QUOTA_MB", "500")
    user, _ = _user_token("alice", "7201")
    sandbox = saas_env / user.id
    clone = sandbox / "giant-repo"
    _write(clone, "payload.bin", "x" * (2 * 1024 * 1024))

    with pytest.raises(HTTPException) as excinfo:
        enforce_post_clone_size(clone, user.id)

    assert excinfo.value.status_code == 413
    assert excinfo.value.detail["code"] == CLONE_SIZE_LIMIT_EXCEEDED
    assert not clone.exists()


def test_post_clone_size_cap_never_deletes_outside_the_sandbox(
    saas_env: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KODO_MAX_CLONE_SIZE_MB", "1")
    monkeypatch.setenv("KODO_USER_QUOTA_MB", "500")
    user, _ = _user_token("alice", "7202")
    host_folder = tmp_path / "host-owned-repo"
    _write(host_folder, "payload.bin", "x" * (2 * 1024 * 1024))

    with pytest.raises(HTTPException):
        enforce_post_clone_size(host_folder, user.id)

    # The clone is rejected, but a host folder outside <KODO_WORKSPACES_DIR>/<user_id> survives.
    assert host_folder.is_dir()
    assert is_strictly_inside_sandbox(host_folder, user.id) is False


def test_compute_dir_size_ignores_unreadable_and_counts_nested_files(saas_env: Path) -> None:
    root = saas_env / "local" / "repo"
    _write(root, "a.txt", "12345")
    _write(root, "nested/b.txt", "123")

    assert compute_dir_size_bytes(root) == 8
    assert compute_dir_size_bytes(saas_env / "missing") == 0


def test_delete_workspace_is_tenant_scoped_and_reports_storage(
    client: TestClient, saas_env: Path
) -> None:
    alice, token_a = _user_token("alice", "7301")
    _, token_b = _user_token("bob", "7302")
    repo = saas_env / alice.id / "demo"
    _write(repo, "README.md", "# demo\n")
    workspace = repository.remember_workspace(alice.id, name="demo", local_path=str(repo))

    stolen = client.delete(f"/api/v1/workspaces/{workspace.id}", headers=_auth(token_b))
    assert stolen.status_code == 404
    assert stolen.json()["detail"]["code"] == "UNKNOWN_WORKSPACE"
    assert repo.is_dir()

    deleted = client.delete(f"/api/v1/workspaces/{workspace.id}", headers=_auth(token_a))

    assert deleted.status_code == 200, deleted.text
    payload = deleted.json()
    assert payload["directoryRemoved"] is True
    assert payload["storage"]["workspaceCount"] == 0
    assert not repo.exists()
    events = repository.read_audit_events(alice.id)
    assert [event.action for event in events] == ["workspace_delete"]


def test_delete_workspace_never_removes_a_local_host_folder(
    client: TestClient, saas_env: Path, tmp_path: Path
) -> None:
    user, token = _user_token("alice", "7303")
    host_folder = tmp_path / "host-project"
    _write(host_folder, "main.py", "print('hi')\n")
    workspace = repository.remember_workspace(user.id, name="host", local_path=str(host_folder))

    response = client.delete(f"/api/v1/workspaces/{workspace.id}", headers=_auth(token))

    assert response.status_code == 200, response.text
    assert response.json()["directoryRemoved"] is False
    assert host_folder.is_dir()
    assert client.get("/api/v1/workspaces", headers=_auth(token)).json()["workspaces"] == []


def test_delete_workspace_in_local_mode_only_drops_the_bookmark(
    client: TestClient, tmp_path: Path
) -> None:
    folder = tmp_path / "my-local-project"
    _write(folder, "app.py")
    workspace = repository.remember_workspace("local", name="mine", local_path=str(folder))

    response = client.delete(f"/api/v1/workspaces/{workspace.id}")

    assert response.status_code == 200, response.text
    assert response.json()["directoryRemoved"] is False
    assert folder.is_dir()


# --------------------------------------------------------------------------- TTL cleanup


def _age_workspace(workspace_id: str, hours: int) -> None:
    with session_scope() as session:
        row = session.get(Workspace, workspace_id)
        assert row is not None
        row.last_accessed_at = datetime.now(UTC) - timedelta(hours=hours)
        row.last_scanned_at = None
        session.flush()


def test_ttl_cleanup_removes_only_stale_saas_workspaces(saas_env: Path) -> None:
    user, _ = _user_token("alice", "7401")
    sandbox = saas_env / user.id
    stale = sandbox / "old-repo"
    fresh = sandbox / "new-repo"
    _write(stale, "README.md")
    _write(fresh, "README.md")

    stale_record = repository.remember_workspace(user.id, name="old", local_path=str(stale))
    fresh_record = repository.remember_workspace(user.id, name="new", local_path=str(fresh))
    _age_workspace(stale_record.id, hours=100)

    removed = cleanup_stale_workspaces()

    assert removed == 1
    assert not stale.exists()
    assert fresh.is_dir()
    remaining = {row.id for row in repository.list_workspaces(user.id)}
    assert remaining == {fresh_record.id}
    events = [event.action for event in repository.read_audit_events(user.id)]
    assert "workspace_ttl_cleanup" in events


def test_ttl_cleanup_keeps_host_folders_and_respects_custom_now(saas_env: Path, tmp_path: Path) -> None:
    user, _ = _user_token("alice", "7402")
    host_folder = tmp_path / "host-project"
    _write(host_folder, "README.md")
    record = repository.remember_workspace(user.id, name="host", local_path=str(host_folder))
    _age_workspace(record.id, hours=500)

    removed = cleanup_stale_workspaces(now=datetime.now(UTC) + timedelta(hours=24))

    assert removed == 0
    assert host_folder.is_dir()
    assert repository.get_workspace(user.id, record.id) is not None


def test_ttl_cleanup_never_runs_in_local_mode(tmp_path: Path) -> None:
    user, _ = _user_token("alice", "7403")
    sandbox = tmp_path / "workspaces" / user.id
    repo = sandbox / "repo"
    _write(repo, "README.md")
    record = repository.remember_workspace(user.id, name="repo", local_path=str(repo))
    _age_workspace(record.id, hours=1000)

    assert cleanup_stale_workspaces() == 0
    assert repo.is_dir()
    assert repository.get_workspace(user.id, record.id) is not None


def test_cleanup_loop_runs_passes_and_cancels_cleanly(monkeypatch: pytest.MonkeyPatch) -> None:
    """The lifespan task must run periodic passes and stop without leaking on shutdown."""
    passes: list[int] = []
    monkeypatch.setattr(
        quota_service, "cleanup_stale_workspaces", lambda *args, **kwargs: passes.append(1) or 0
    )

    async def scenario() -> None:
        stop = asyncio.Event()
        task = asyncio.create_task(quota_service.run_cleanup_loop(stop, interval_seconds=0.05))
        await asyncio.sleep(0.3)
        assert passes, "the cleanup loop never ran a pass"
        stop.set()
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        assert task.done()

    asyncio.run(scenario())


# ------------------------------------------------------------------------ rate limiting


def test_scan_rate_limit_returns_429_with_headers(
    client: TestClient, saas_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KODO_RL_SCAN_PER_MIN", "3")
    user, token = _user_token("alice", "7501")
    repo = saas_env / user.id / "repo"
    _write(repo, "src/Order.java")

    for index in range(3):
        allowed = client.post("/api/v1/scan", headers=_auth(token), json={"path": str(repo)})
        assert allowed.status_code == 200, allowed.text
        assert allowed.headers["x-ratelimit-limit"] == "3"
        assert allowed.headers["x-ratelimit-remaining"] == str(2 - index)
        assert int(allowed.headers["x-ratelimit-reset"]) > 0

    blocked = client.post("/api/v1/scan", headers=_auth(token), json={"path": str(repo)})

    assert blocked.status_code == 429, blocked.text
    body = blocked.json()
    assert body["code"] == "RATE_LIMITED"
    assert body["retryAfterSeconds"] >= 1
    assert body["message"] == f"Rate limit exceeded. Try again in {body['retryAfterSeconds']}s."
    assert blocked.headers["retry-after"] == str(body["retryAfterSeconds"])
    assert blocked.headers["x-ratelimit-remaining"] == "0"

    # CORS must wrap the limiter, so even a 429 is readable by a split-origin dev UI.
    cross_origin = client.post(
        "/api/v1/scan",
        headers={**_auth(token), "Origin": "http://localhost:5173"},
        json={"path": str(repo)},
    )
    assert cross_origin.status_code == 429
    assert cross_origin.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_rate_limit_buckets_are_per_user(
    client: TestClient, saas_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KODO_RL_SCAN_PER_MIN", "1")
    alice, token_a = _user_token("alice", "7601")
    bob, token_b = _user_token("bob", "7602")
    alice_repo = saas_env / alice.id / "repo"
    bob_repo = saas_env / bob.id / "repo"
    _write(alice_repo, "src/Order.java")
    _write(bob_repo, "src/Order.java")

    assert client.post("/api/v1/scan", headers=_auth(token_a), json={"path": str(alice_repo)}).status_code == 200
    assert client.post("/api/v1/scan", headers=_auth(token_a), json={"path": str(alice_repo)}).status_code == 429

    bob_scan = client.post("/api/v1/scan", headers=_auth(token_b), json={"path": str(bob_repo)})
    assert bob_scan.status_code == 200, bob_scan.text


def test_ai_bucket_is_rate_limited(
    client: TestClient, saas_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KODO_RL_AI_PER_MIN", "1")
    monkeypatch.setenv("KODO_SYSTEMONE_BASE_URL", "http://127.0.0.1:9")
    _, token = _user_token("alice", "7701")

    first = client.post("/api/v1/decision/test-connection", headers=_auth(token))
    second = client.post("/api/v1/decision/test-connection", headers=_auth(token))

    assert first.status_code == 200, first.text
    assert second.status_code == 429
    assert second.json()["code"] == "RATE_LIMITED"


def test_rate_limiting_is_disabled_by_default_in_local_mode(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KODO_RL_SCAN_PER_MIN", "1")
    project = tmp_path / "project"
    _write(project, "src/Order.java")

    assert rate_limit_enabled() is False
    for _ in range(4):
        response = client.post("/api/v1/scan", json={"path": str(project)})
        assert response.status_code == 200, response.text
        assert "x-ratelimit-limit" not in response.headers


def test_unlimited_routes_are_not_counted(
    client: TestClient, saas_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KODO_RL_SCAN_PER_MIN", "1")
    _, token = _user_token("alice", "7801")

    # /api/v1/workspaces is not in any bucket: repeated calls never 429 and carry no RL headers.
    for _ in range(5):
        response = client.get("/api/v1/workspaces", headers=_auth(token))
        assert response.status_code == 200
        assert "x-ratelimit-limit" not in response.headers


def test_initial_revision_constant_matches_the_baseline_migration() -> None:
    versions = ALEMBIC_INI_PATH.parent / "alembic" / "versions"
    assert (versions / f"{INITIAL_REVISION}.py").is_file()
    assert (versions / f"{HEAD_REVISION}.py").is_file()
    assert get_user_storage_usage.__module__ == "app.services.quota"
