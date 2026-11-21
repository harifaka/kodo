"""Phase 6 Deploy Studio: Docker generation, Docker control panel, audit log and Git adapter.

Every Docker and GitHub call is mocked; the only real subprocesses are the local ``git`` commands
used by the export round-trip (skipped automatically when Git is not installed).
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
from pathlib import Path

import httpx
import pytest
import yaml
from fastapi.testclient import TestClient

from app.deploy import generator, runner
from app.deploy.errors import DeployError
from app.main import app
from app.services import audit_log, git_remote

requires_git = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def _completed(stdout: str = "", stderr: str = "", returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=["docker"], returncode=returncode, stdout=stdout, stderr=stderr)


def _workspace(tmp_path: Path, files: dict[str, str]) -> Path:
    root = tmp_path / "workspace"
    for rel_path, content in files.items():
        target = root / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")
    return root


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True)


def _init_repo(root: Path) -> None:
    _git(root, "init", "-q")
    _git(root, "symbolic-ref", "HEAD", "refs/heads/main")
    _git(root, "config", "user.email", "kodo@example.com")
    _git(root, "config", "user.name", "Kodo Tests")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "initial")


def _artifact(artifacts: generator.DeployArtifacts, file_path: str) -> str:
    return next(item.content for item in artifacts.files if item.file_path == file_path)


def _audit_path() -> Path:
    return Path(os.environ["KODO_AUDIT_LOG_PATH"])


# --------------------------------------------------------------------------- Dockerfile generation


@pytest.mark.parametrize(
    ("stack", "runtime", "port", "health_path"),
    [
        ("spring-boot", "eclipse-temurin:21-jre-alpine", 8080, "/actuator/health"),
        ("nodejs", "node:22-alpine", 3000, "/health"),
        ("csharp-dotnet", "mcr.microsoft.com/dotnet/aspnet:8.0-alpine", 8080, "/health"),
    ],
)
def test_dockerfile_is_multistage_non_root_with_healthcheck(
    tmp_path: Path, stack: str, runtime: str, port: int, health_path: str
) -> None:
    artifacts = generator.generate_artifacts(
        stack=stack,
        project_name="Acme Shop",
        app_port=port,
        backing_services=[],
        root=tmp_path,
    )
    dockerfile = _artifact(artifacts, "Dockerfile")

    assert dockerfile.count("\nFROM ") + dockerfile.startswith("FROM ") >= 2
    assert f"FROM {runtime}" in dockerfile
    assert "addgroup -S kodo && adduser -S kodo -G kodo" in dockerfile
    assert "\nUSER kodo" in dockerfile
    assert "HEALTHCHECK" in dockerfile
    assert f"http://127.0.0.1:{port}{health_path}" in dockerfile
    assert f"EXPOSE {port}" in dockerfile
    assert artifacts.stack == stack


def test_spring_dockerfile_uses_maven_build_stage(tmp_path: Path) -> None:
    artifacts = generator.generate_artifacts(
        stack="spring-boot", project_name="Acme", app_port=8080, backing_services=[], root=tmp_path
    )
    dockerfile = _artifact(artifacts, "Dockerfile")

    assert "FROM maven:3.9-eclipse-temurin-21 AS build" in dockerfile
    assert "mvn -B -q -DskipTests package" in dockerfile
    assert 'ENTRYPOINT ["java"' in dockerfile


def test_node_dockerfile_exposes_3000_and_builds_typescript(tmp_path: Path) -> None:
    artifacts = generator.generate_artifacts(
        stack="nodejs", project_name="Acme API", app_port=3000, backing_services=[], root=tmp_path
    )
    dockerfile = _artifact(artifacts, "Dockerfile")

    assert "FROM node:22-alpine AS build" in dockerfile
    assert "npm run build" in dockerfile
    assert "npm ci --omit=dev" in dockerfile
    assert 'CMD ["node", "dist/index.js"]' in dockerfile


def test_dotnet_dockerfile_uses_published_assembly_name(tmp_path: Path) -> None:
    artifacts = generator.generate_artifacts(
        stack="csharp-dotnet", project_name="Acme Shop", app_port=8080, backing_services=[], root=tmp_path
    )
    assert 'ENTRYPOINT ["dotnet", "AcmeShop.dll"]' in _artifact(artifacts, "Dockerfile")


def test_wpf_warns_and_generates_a_sidecar_instead_of_a_linux_image(tmp_path: Path) -> None:
    artifacts = generator.generate_artifacts(
        stack="csharp-wpf",
        project_name="Acme Desktop",
        app_port=None,
        backing_services=["postgres"],
        root=tmp_path,
    )
    paths = {item.file_path for item in artifacts.files}

    assert "Dockerfile" not in paths
    assert "Dockerfile.sidecar" in paths
    assert "Dockerfile.sidecar" in _artifact(artifacts, "docker-compose.yml")
    assert any("WPF cannot run in a Linux container" in warning for warning in artifacts.warnings)

    compose = yaml.safe_load(_artifact(artifacts, "docker-compose.yml"))
    assert compose["services"]["api"]["profiles"] == ["sidecar"]
    assert "postgres" in compose["services"]


def test_custom_app_port_is_applied_everywhere(tmp_path: Path) -> None:
    artifacts = generator.generate_artifacts(
        stack="spring-boot", project_name="Acme", app_port=9090, backing_services=[], root=tmp_path
    )
    compose = yaml.safe_load(_artifact(artifacts, "docker-compose.yml"))

    assert "EXPOSE 9090" in _artifact(artifacts, "Dockerfile")
    assert compose["services"]["app"]["ports"] == ["${APP_PORT:-9090}:9090"]
    assert "APP_PORT=9090" in _artifact(artifacts, ".env.example")


def test_stack_detection_reads_marker_files(tmp_path: Path) -> None:
    spring = _workspace(tmp_path / "spring", {"pom.xml": "<project />"})
    node = _workspace(tmp_path / "node", {"package.json": "{}"})
    wpf = _workspace(tmp_path / "wpf", {"Acme.csproj": "<Project />", "App.xaml": "<Application />"})
    dotnet = _workspace(tmp_path / "dotnet", {"Acme.csproj": "<Project />"})
    empty = tmp_path / "empty"
    empty.mkdir()

    assert generator.detect_stack(spring) == "spring-boot"
    assert generator.detect_stack(node) == "nodejs"
    assert generator.detect_stack(wpf) == "csharp-wpf"
    assert generator.detect_stack(dotnet) == "csharp-dotnet"
    assert generator.detect_stack(empty) is None


# ------------------------------------------------------------------------ compose / env wiring


def test_compose_wires_backing_services_network_and_healthchecks(tmp_path: Path) -> None:
    artifacts = generator.generate_artifacts(
        stack="spring-boot",
        project_name="Acme Shop",
        app_port=8080,
        backing_services=["postgres", "redis", "rabbitmq"],
        root=tmp_path,
    )
    compose = yaml.safe_load(_artifact(artifacts, "docker-compose.yml"))

    services = compose["services"]
    assert set(services) == {"app", "postgres", "redis", "rabbitmq"}
    app_service = services["app"]
    assert app_service["depends_on"] == {
        name: {"condition": "service_healthy"} for name in ("postgres", "redis", "rabbitmq")
    }
    assert app_service["networks"] == ["kodo-net"]
    assert compose["networks"]["kodo-net"]["driver"] == "bridge"
    for name in ("postgres", "redis", "rabbitmq"):
        assert "healthcheck" in services[name]
    assert app_service["environment"]["REDIS_URL"] == "redis://redis:6379/0"
    assert "${POSTGRES_DB" in app_service["environment"]["SPRING_DATASOURCE_URL"]
    assert compose["volumes"] == {"postgres-data": None, "redis-data": None, "rabbitmq-data": None}


def test_compose_omits_unselected_backing_services(tmp_path: Path) -> None:
    artifacts = generator.generate_artifacts(
        stack="nodejs", project_name="Acme", app_port=3000, backing_services=["redis"], root=tmp_path
    )
    compose = yaml.safe_load(_artifact(artifacts, "docker-compose.yml"))

    assert set(compose["services"]) == {"app", "redis"}
    assert compose["services"]["app"]["depends_on"] == {"redis": {"condition": "service_healthy"}}


def test_env_example_and_compose_hold_placeholders_only(tmp_path: Path) -> None:
    artifacts = generator.generate_artifacts(
        stack="spring-boot",
        project_name="Acme Shop",
        app_port=8080,
        backing_services=["postgres", "rabbitmq"],
        root=tmp_path,
    )
    compose_text = _artifact(artifacts, "docker-compose.yml")
    env_text = _artifact(artifacts, ".env.example")

    assert "change-me-local-only" in env_text
    yaml.safe_load(compose_text)  # valid YAML
    for value in ("POSTGRES_PASSWORD", "RABBITMQ_DEFAULT_PASS"):
        assert f'{value}: "${{{value}:-' in compose_text
    for secret_shape in ("ghp_", "glpat-", "AKIA", "-----BEGIN", "password123"):
        assert secret_shape not in compose_text
        assert secret_shape not in env_text


def test_dockerignore_excludes_stack_outputs_and_secrets(tmp_path: Path) -> None:
    spring = generator.generate_artifacts(
        stack="spring-boot", project_name="Acme", app_port=8080, backing_services=[], root=tmp_path
    )
    node = generator.generate_artifacts(
        stack="nodejs", project_name="Acme", app_port=3000, backing_services=[], root=tmp_path
    )
    dotnet = generator.generate_artifacts(
        stack="csharp-dotnet", project_name="Acme", app_port=8080, backing_services=[], root=tmp_path
    )

    for artifacts in (spring, node, dotnet):
        ignore = _artifact(artifacts, ".dockerignore")
        assert ".git" in ignore
        assert ".env" in ignore
        assert "!.env.example" in ignore
    assert "target/" in _artifact(spring, ".dockerignore")
    assert "node_modules/" in _artifact(node, ".dockerignore")
    assert "bin/" in _artifact(dotnet, ".dockerignore")


# ---------------------------------------------------- deploy dry-run -> apply -> rollback cycle


@requires_git
def test_deploy_dry_run_apply_and_rollback_round_trip(client: TestClient, tmp_path: Path) -> None:
    root = _workspace(tmp_path, {"pom.xml": "<project></project>", "src/main/java/App.java": "class App {}"})
    _init_repo(root)
    request = {
        "rootPath": str(root),
        "projectName": "Acme Shop",
        "stack": "auto",
        "appPort": 8080,
        "backingServices": ["postgres", "redis"],
        "overwriteExisting": False,
    }

    plan = client.post("/api/v1/deploy/dry-run", json=request)
    assert plan.status_code == 200
    body = plan.json()
    patches = {patch["filePath"]: patch for patch in body["patches"]}
    assert set(patches) == {"Dockerfile", ".dockerignore", "docker-compose.yml", ".env.example"}
    assert all(patch["isNewFile"] for patch in patches.values())
    assert all(patch["originalSha256"] is None for patch in patches.values())
    assert all(patch["conflict"] is False for patch in patches.values())

    applied = client.post(
        "/api/v1/apply",
        json={
            "rootPath": str(root),
            "patches": [
                {
                    "filePath": patch["filePath"],
                    "expectedSha256": patch["originalSha256"],
                    "proposedContent": patch["proposedContent"],
                    "isNewFile": patch["isNewFile"],
                }
                for patch in body["patches"]
            ],
            "allowDirty": False,
            "allowNonGit": False,
        },
    )
    assert applied.status_code == 200
    apply_id = applied.json()["applyId"]
    compose = yaml.safe_load((root / "docker-compose.yml").read_text(encoding="utf-8"))
    assert set(compose["services"]) == {"app", "postgres", "redis"}

    overwrite = client.post(
        "/api/v1/deploy/dry-run", json={**request, "overwriteExisting": True}
    )
    assert overwrite.status_code == 200
    overwritten = {patch["filePath"]: patch for patch in overwrite.json()["patches"]}
    assert overwritten["Dockerfile"]["isNewFile"] is False
    assert len(overwritten["Dockerfile"]["originalSha256"]) == 64
    assert "will be replaced" in overwritten["Dockerfile"]["warnings"][0]

    guarded = client.post("/api/v1/deploy/dry-run", json=request)
    assert guarded.status_code == 200
    assert all(patch["conflict"] for patch in guarded.json()["patches"])
    assert any("already exist" in warning for warning in guarded.json()["warnings"])

    rolled_back = client.post("/api/v1/apply/rollback", json={"applyId": apply_id})
    assert rolled_back.status_code == 200
    assert sorted(rolled_back.json()["deletedFiles"]) == [
        ".dockerignore",
        ".env.example",
        "Dockerfile",
        "docker-compose.yml",
    ]
    assert not (root / "Dockerfile").exists()
    assert (root / "pom.xml").is_file()

    entries = client.get("/api/v1/audit-log?limit=10").json()["entries"]
    assert [entry["action"] for entry in entries[:2]] == ["rollback", "apply"]
    assert entries[0]["status"] == "success"


def test_dry_run_writes_nothing_to_disk(client: TestClient, tmp_path: Path) -> None:
    root = _workspace(tmp_path, {"package.json": "{}"})
    response = client.post(
        "/api/v1/deploy/dry-run",
        json={
            "rootPath": str(root),
            "projectName": "Acme API",
            "stack": "nodejs",
            "appPort": 3000,
            "backingServices": ["redis"],
            "overwriteExisting": False,
        },
    )

    assert response.status_code == 200
    assert len(response.json()["patches"]) == 4
    assert sorted(path.name for path in root.iterdir()) == ["package.json"]


def test_dry_run_rejects_unknown_stack_and_missing_detection(client: TestClient, tmp_path: Path) -> None:
    root = _workspace(tmp_path, {"README.md": "no markers here"})
    base = {
        "rootPath": str(root),
        "projectName": "Acme",
        "appPort": 8080,
        "backingServices": [],
        "overwriteExisting": False,
    }

    unknown = client.post("/api/v1/deploy/dry-run", json={**base, "stack": "cobol"})
    assert unknown.status_code == 400
    assert unknown.json()["detail"]["code"] == "UNKNOWN_STACK"

    undetected = client.post("/api/v1/deploy/dry-run", json={**base, "stack": "auto"})
    assert undetected.status_code == 400
    assert undetected.json()["detail"]["code"] == "STACK_NOT_DETECTED"

    bad_service = client.post(
        "/api/v1/deploy/dry-run",
        json={**base, "stack": "nodejs", "backingServices": ["mysql"]},
    )
    assert bad_service.status_code == 400
    assert bad_service.json()["detail"]["code"] == "UNKNOWN_BACKING_SERVICE"

    missing_root = client.post(
        "/api/v1/deploy/dry-run", json={**base, "rootPath": str(tmp_path / "nope"), "stack": "nodejs"}
    )
    assert missing_root.status_code == 400

    bad_port = client.post("/api/v1/deploy/dry-run", json={**base, "stack": "nodejs", "appPort": 70_000})
    assert bad_port.status_code == 422


# --------------------------------------------------------------------- Docker control panel (mocked)


def _compose_workspace(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    root.mkdir(parents=True, exist_ok=True)
    (root / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    return root


def test_docker_status_reports_containers_within_the_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    root = _compose_workspace(tmp_path)
    commands: list[tuple[list[str], Path]] = []

    payload = json.dumps(
        [
            {
                "Name": "acme-app-1",
                "Service": "app",
                "State": "running",
                "Status": "Up 2 minutes (healthy)",
                "Health": "healthy",
                "Publishers": [
                    {"URL": "0.0.0.0", "TargetPort": 8080, "PublishedPort": 18080, "Protocol": "tcp"}
                ],
            },
            {"Name": "acme-redis-1", "Service": "redis", "State": "exited", "Status": "Exited (0)"},
        ]
    )

    def fake(args: list[str], *, cwd: Path, timeout: int) -> subprocess.CompletedProcess[str]:
        commands.append((list(args), cwd))
        if args[1] == "--version":
            return _completed("Docker version 29.9.2, build a82e528\n")
        if args[1] == "info":
            return _completed("29.9.2\n")
        if args[1:3] == ["compose", "ps"]:
            return _completed(payload)
        raise AssertionError(f"unexpected docker command: {args}")

    monkeypatch.setattr(runner, "_run_cli", fake)

    status = runner.docker_status(str(root))

    assert status.docker_available and status.daemon_running and status.has_compose_file
    assert [container.name for container in status.containers] == ["acme-app-1", "acme-redis-1"]
    assert status.containers[0].health == "healthy"
    assert status.containers[0].ports == ["18080->8080/tcp"]
    assert status.containers[1].health == "none"
    assert all(cwd == root for _, cwd in commands)


def test_docker_status_degrades_when_cli_daemon_or_compose_are_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()

    monkeypatch.setattr(runner, "_run_cli", lambda *args, **kwargs: None)
    no_cli = runner.docker_status(str(root))
    assert no_cli.docker_available is False
    assert "not installed" in (no_cli.warning or "")

    def failing(args: list[str], *, cwd: Path, timeout: int) -> subprocess.CompletedProcess[str]:
        if args[1] == "--version":
            return _completed("Docker version 29.9.2\n")
        return _completed("", "Cannot connect to the Docker daemon", returncode=1)

    monkeypatch.setattr(runner, "_run_cli", failing)
    no_daemon = runner.docker_status(str(root))
    assert no_daemon.docker_available is True
    assert no_daemon.daemon_running is False
    assert "daemon is not reachable" in (no_daemon.warning or "")

    def healthy(args: list[str], *, cwd: Path, timeout: int) -> subprocess.CompletedProcess[str]:
        return _completed("29.9.2\n")

    monkeypatch.setattr(runner, "_run_cli", healthy)
    no_compose = runner.docker_status(str(root))
    assert no_compose.daemon_running is True
    assert no_compose.has_compose_file is False
    assert "docker-compose.yml" in (no_compose.warning or "")


def test_run_cli_uses_list_args_without_a_shell(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured["args"] = args
        captured.update(kwargs)
        return _completed("ok")

    monkeypatch.setattr(runner.subprocess, "run", fake_run)

    result = runner._run_cli(["docker", "compose", "ps"], cwd=tmp_path, timeout=5)

    assert result is not None and result.returncode == 0
    assert captured["args"] == ["docker", "compose", "ps"]
    assert captured["shell"] is False
    assert captured["cwd"] == str(tmp_path)


def test_compose_up_builds_and_records_audit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    root = _compose_workspace(tmp_path)
    calls: list[list[str]] = []

    def fake(args: list[str], *, cwd: Path, timeout: int) -> subprocess.CompletedProcess[str]:
        calls.append(list(args))
        if args[1] == "--version":
            return _completed("Docker version 29.9.2\n")
        if args[1] == "info":
            return _completed("29.9.2\n")
        if args[1:3] == ["compose", "ps"]:
            return _completed("[]")
        if args[1:4] == ["compose", "up", "-d"]:
            return _completed("Container acme-app-1  Started\n")
        raise AssertionError(f"unexpected docker command: {args}")

    monkeypatch.setattr(runner, "_run_cli", fake)

    result = runner.compose_up(str(root), build=True)

    assert result.success is True
    assert result.command == "docker compose up -d --build"
    assert calls[0][1:5] == ["compose", "up", "-d", "--build"]
    assert result.status.has_compose_file is True

    events = audit_log.read_events(10)
    assert events[0].action == "deploy_up"
    assert events[0].status == "success"
    assert events[0].root_path == str(root)


def test_compose_down_removes_volumes_when_requested(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = _compose_workspace(tmp_path)
    calls: list[list[str]] = []

    def fake(args: list[str], *, cwd: Path, timeout: int) -> subprocess.CompletedProcess[str]:
        calls.append(list(args))
        if args[1] == "--version":
            return _completed("Docker version 29.9.2\n")
        if args[1] == "info":
            return _completed("29.9.2\n")
        if args[1:3] == ["compose", "ps"]:
            return _completed("[]")
        return _completed("Removed\n")

    monkeypatch.setattr(runner, "_run_cli", fake)

    result = runner.compose_down(str(root), remove_volumes=True)

    assert result.success is True
    assert calls[0] == ["docker", "compose", "down", "--volumes"]
    assert result.command == "docker compose down --volumes"
    assert audit_log.read_events(1)[0].action == "deploy_down"


def test_compose_logs_clamps_tail_and_rejects_unsafe_services(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = _compose_workspace(tmp_path)
    calls: list[list[str]] = []

    def fake(args: list[str], *, cwd: Path, timeout: int) -> subprocess.CompletedProcess[str]:
        calls.append(list(args))
        return _completed("\x1b[32mstarted\x1b[0m\n")

    monkeypatch.setattr(runner, "_run_cli", fake)

    logs = runner.compose_logs(str(root), service="app", tail=5000)
    assert logs.tail == 1000
    assert calls[0] == ["docker", "compose", "logs", "--no-color", "--tail", "1000", "app"]
    assert logs.logs.strip() == "started"  # ANSI colour codes stripped

    for unsafe in ("app; rm -rf /", "../../etc", "app$(whoami)", "-n", "a b", "x" * 64):
        with pytest.raises(DeployError) as rejected:
            runner.compose_logs(str(root), service=unsafe, tail=10)
        assert rejected.value.status_code == 400
        assert rejected.value.code == "INVALID_SERVICE"


def test_docker_endpoints_reject_missing_compose_and_bad_roots(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    monkeypatch.setattr(runner, "_run_cli", lambda *args, **kwargs: _completed("29.9.2\n"))

    with pytest.raises(DeployError) as no_compose:
        runner.compose_up(str(root), build=False)
    assert no_compose.value.status_code == 400
    assert no_compose.value.code == "NO_COMPOSE_FILE"

    with pytest.raises(DeployError) as missing_root:
        runner.docker_status(str(tmp_path / "does-not-exist"))
    assert missing_root.value.status_code == 400
    assert missing_root.value.code == "PATH_REJECTED"


def test_docker_routes_expose_structured_errors(client: TestClient, tmp_path: Path) -> None:
    response = client.get("/api/v1/deploy/docker/status", params={"root": str(tmp_path / "nope")})
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "PATH_REJECTED"

    logs = client.get(
        "/api/v1/deploy/docker/logs",
        params={"root": str(tmp_path), "service": "app; whoami", "tail": 200},
    )
    assert logs.status_code == 400
    assert logs.json()["detail"]["code"] == "INVALID_SERVICE"


# ---------------------------------------------------------------------------------- audit log


def test_audit_log_appends_redacts_and_returns_newest_first(client: TestClient, tmp_path: Path) -> None:
    audit_log.record_event(
        "git_clone",
        str(tmp_path),
        "Cloned https://github.com/acme/shop with ghp_abcdefghijklmnop1234",
        status="success",
    )
    audit_log.record_event(
        "deploy_up",
        str(tmp_path / "workspace"),
        "docker compose up -d -> exit code 0",
        files_count=3,
    )

    raw = _audit_path().read_text(encoding="utf-8")
    assert "ghp_abcdefghijklmnop1234" not in raw
    assert "[redacted]" in raw
    assert len(raw.strip().splitlines()) == 2

    first = json.loads(raw.splitlines()[0])
    assert set(first) == {"timestamp", "action", "rootPath", "summary", "filesCount", "status"}
    assert first["rootPath"] == str(tmp_path)

    response = client.get("/api/v1/audit-log", params={"limit": 10})
    assert response.status_code == 200
    entries = response.json()["entries"]
    assert [entry["action"] for entry in entries] == ["deploy_up", "git_clone"]
    assert entries[0]["filesCount"] == 3
    assert entries[1]["summary"].startswith("Cloned")

    assert client.get("/api/v1/audit-log", params={"limit": 0}).status_code == 422


def test_audit_log_never_breaks_the_caller(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    blocked = tmp_path / "blocked"
    blocked.mkdir()
    monkeypatch.setenv("KODO_AUDIT_LOG_PATH", str(blocked))  # a directory, not a file

    audit_log.record_event("apply", str(tmp_path), "should be swallowed")
    assert audit_log.read_events(5) == []


# ------------------------------------------------------------------------------- git adapter


@pytest.mark.parametrize(
    "repo_url",
    [
        "file:///C:/repos/shop",
        "git@github.com:acme/shop.git",
        "ssh://git@github.com/acme/shop.git",
        "http://github.com/acme/shop",
        "https://github.com/acme/shop; rm -rf /",
        "https://github.com/acme/../shop",
        "https://user:pass@github.com/acme/shop",
        "https://evil.example.com/acme/shop",
        "https://github.com/acme",
        "",
    ],
)
def test_clone_rejects_unsafe_urls(client: TestClient, repo_url: str) -> None:
    response = client.post("/api/v1/git/clone", json={"repoUrl": repo_url})

    expected = 422 if not repo_url else 400
    assert response.status_code == expected
    if expected == 400:
        assert response.json()["detail"]["code"] == "INVALID_REPO_URL"


def test_clone_is_shallow_and_keeps_the_token_transient(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KODO_WORKSPACES_DIR", str(tmp_path / "workspaces"))
    calls: list[list[str]] = []
    token = "ghp_secrettoken1234567890"

    def fake(args: list[str], *, cwd: Path, timeout: int) -> subprocess.CompletedProcess[str]:
        calls.append(list(args))
        if args[1:3] == ["rev-parse", "--abbrev-ref"]:
            return _completed("main\n")
        target = Path(args[-1])
        (target / ".git").mkdir(parents=True, exist_ok=True)
        return _completed("Cloning into ...\n")

    monkeypatch.setattr(git_remote, "_run", fake)

    response = client.post(
        "/api/v1/git/clone",
        json={"repoUrl": "https://github.com/acme/shop.git", "branch": "develop", "token": token},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["repoUrl"] == "https://github.com/acme/shop"
    assert body["branch"] == "main"
    local = Path(body["localPath"])
    assert local.parent == (tmp_path / "workspaces").resolve()
    assert local.name.startswith("shop-")

    clone = calls[0]
    assert clone[0] == "git"
    assert clone[1] == "-c"
    assert "--depth" in clone and clone[clone.index("--depth") + 1] == "1"
    assert clone[clone.index("--branch") + 1] == "develop"
    assert clone[-2] == "https://github.com/acme/shop"  # URL never carries the token
    header = clone[2]
    assert header.startswith("http.extraHeader=Authorization: Basic ")
    decoded = base64.b64decode(header.split("Basic ", 1)[1]).decode()
    assert decoded == f"x-access-token:{token}"
    assert not any(token in argument for argument in clone)

    log_text = _audit_path().read_text(encoding="utf-8")
    assert token not in log_text
    assert json.loads(log_text.splitlines()[0])["action"] == "git_clone"


def test_clone_reports_missing_git(client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KODO_WORKSPACES_DIR", str(tmp_path / "workspaces"))
    monkeypatch.setattr(git_remote, "_run", lambda *args, **kwargs: None)

    response = client.post("/api/v1/git/clone", json={"repoUrl": "https://gitlab.com/acme/shop"})

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "GIT_UNAVAILABLE"


@pytest.mark.parametrize(
    "branch",
    ["-x", "feature..main", "feature/../x", "refs/heads/main", "bad branch", "feature/", "x.lock", ""],
)
def test_git_export_rejects_unsafe_branches(client: TestClient, tmp_path: Path, branch: str) -> None:
    root = _workspace(tmp_path, {"README.md": "hello\n"})
    response = client.post(
        "/api/v1/git/export",
        json={"rootPath": str(root), "branchName": branch, "commitMessage": "msg"},
    )
    assert response.status_code in (400, 422)
    if response.status_code == 400:
        assert response.json()["detail"]["code"] == "INVALID_BRANCH"


def test_git_export_requires_a_repository(client: TestClient, tmp_path: Path) -> None:
    root = _workspace(tmp_path, {"README.md": "hello\n"})

    response = client.post(
        "/api/v1/git/export",
        json={"rootPath": str(root), "branchName": "kodo/deploy", "commitMessage": "msg"},
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "NOT_A_GIT_REPO"


@requires_git
def test_git_export_commits_and_opens_a_mocked_pull_request(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _workspace(tmp_path, {"README.md": "hello\n"})
    _init_repo(root)
    (root / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8", newline="\n")
    _git(root, "remote", "add", "origin", "https://github.com/acme/shop.git")

    token = "ghp_pat1234567890abcdef"
    pushes: list[list[str]] = []
    real_run = git_remote._run

    def fake_run(args: list[str], *, cwd: Path, timeout: int) -> subprocess.CompletedProcess[str] | None:
        if "push" in args:
            pushes.append(list(args))
            return _completed("branch pushed\n")
        return real_run(args, cwd=cwd, timeout=timeout)

    monkeypatch.setattr(git_remote, "_run", fake_run)

    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("Authorization")
        captured["payload"] = json.loads(request.content)
        return httpx.Response(201, json={"html_url": "https://github.com/acme/shop/pull/7"})

    git_remote.set_transport_override(httpx.MockTransport(handler))
    try:
        response = client.post(
            "/api/v1/git/export",
            json={
                "rootPath": str(root),
                "branchName": "kodo/deploy-studio",
                "commitMessage": "Add generated container artifacts",
                "createPr": True,
                "prTitle": "Deploy Studio artifacts",
                "prBody": "Generated Dockerfile + compose",
                "token": token,
            },
        )
    finally:
        git_remote.set_transport_override(None)

    assert response.status_code == 200
    body = response.json()
    assert body["branch"] == "kodo/deploy-studio"
    assert body["pushed"] is True
    assert body["prUrl"] == "https://github.com/acme/shop/pull/7"
    assert len(body["commitSha"]) == 40
    assert body["warnings"] == []

    assert captured["url"] == "https://api.github.com/repos/acme/shop/pulls"
    assert captured["auth"] == f"Bearer {token}"
    payload = captured["payload"]
    assert payload["head"] == "kodo/deploy-studio"
    assert payload["base"] == "main"
    assert payload["title"] == "Deploy Studio artifacts"

    committed = subprocess.run(
        ["git", "show", "--name-only", "--pretty=", body["commitSha"]],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "docker-compose.yml" in committed

    assert len(pushes) == 1
    assert not any(token in argument for argument in pushes[0])
    assert token not in (root / ".git" / "config").read_text(encoding="utf-8")
    assert token not in _audit_path().read_text(encoding="utf-8")
    assert (root / "README.md").is_file()


@requires_git
def test_git_export_stays_local_without_a_token(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _workspace(tmp_path, {"README.md": "hello\n"})
    _init_repo(root)
    _git(root, "remote", "add", "origin", "https://github.com/acme/shop.git")
    (root / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8", newline="\n")

    def no_pr(request: httpx.Request) -> httpx.Response:  # pragma: no cover - must never run
        raise AssertionError("no pull request may be opened without a token")

    git_remote.set_transport_override(httpx.MockTransport(no_pr))
    try:
        response = client.post(
            "/api/v1/git/export",
            json={
                "rootPath": str(root),
                "branchName": "kodo/local-export",
                "commitMessage": "Local container artifacts",
                "createPr": True,
            },
        )
    finally:
        git_remote.set_transport_override(None)

    assert response.status_code == 200
    body = response.json()
    assert body["pushed"] is False
    assert body["prUrl"] is None
    assert any("token is required" in warning for warning in body["warnings"])

    events = audit_log.read_events(5)
    assert events[0].action == "git_export"
    assert events[0].status == "success"
