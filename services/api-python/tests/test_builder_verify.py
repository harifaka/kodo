"""Phase 9 ephemeral builder tests: staging, diagnostics, runner, routes and the AI build fix.

Everything is deterministic: Docker CLI subprocesses and LLM HTTP calls are mocked, so the suite
never needs a Docker daemon, network access or a host compiler.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import tarfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app import config
from app.auth.jwt_utils import create_session_token
from app.builders import runner
from app.builders.diagnostics import normalize_output, normalize_path, parse_diagnostics
from app.builders.models import (
    BuilderStatus,
    BuildPatchInput,
    BuildResult,
    StagingError,
)
from app.builders.staging import build_workspace_tar
from app.db import repository
from app.db.engine import reset_engine
from app.llm.client import set_transport_override
from app.main import app
from app.services.audit_log import AUDIT_ACTION_VERIFY_BUILD, read_user_events

BUILDER_ENV = (
    "KODO_BUILDERS_ENABLED",
    "KODO_BUILDER_IMAGE_JAVA",
    "KODO_BUILDER_IMAGE_CSHARP",
    "KODO_BUILDER_IMAGE_NODEJS",
    "KODO_BUILDER_NETWORK_MODE",
    "KODO_BUILDER_TIMEOUT_SECONDS",
    "KODO_BUILDER_MEMORY",
    "KODO_BUILDER_CPUS",
    "KODO_BUILDER_PIDS_LIMIT",
)


@pytest.fixture(autouse=True)
def _builder_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in BUILDER_ENV:
        monkeypatch.delenv(key, raising=False)


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def _workspace(tmp_path: Path, files: dict[str, str]) -> Path:
    root = tmp_path / "workspace"
    for rel_path, content in files.items():
        target = root / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")
    return root


def _completed(stdout: str = "", stderr: str = "", returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=["docker"], returncode=returncode, stdout=stdout, stderr=stderr)


def _tar_members(payload: bytes) -> dict[str, bytes]:
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r") as archive:
        return {
            member.name: archive.extractfile(member).read()  # type: ignore[union-attr]
            for member in archive.getmembers()
            if member.isfile()
        }


# ------------------------------------------------------------------------------- staging


def test_staging_overlays_patches_in_memory_and_never_touches_disk(tmp_path: Path) -> None:
    root = _workspace(
        tmp_path,
        {
            "pom.xml": "<project/>",
            "src/main/java/App.java": "class App { int value; }\n",
            "target/classes/App.class": "binary-output",
            "node_modules/pkg/index.js": "module.exports = 1;\n",
        },
    )
    app_file = root / "src/main/java/App.java"
    before_bytes = app_file.read_bytes()
    before_mtime = os.stat(app_file).st_mtime_ns

    payload = build_workspace_tar(
        root,
        [
            BuildPatchInput(filePath="src/main/java/App.java", proposedContent="class App { String value; }\n"),
            BuildPatchInput(filePath="src/main/java/Extra.java", proposedContent="class Extra {}\n", isNewFile=True),
        ],
    )

    members = _tar_members(payload)
    assert members["src/main/java/App.java"] == b"class App { String value; }\n"
    assert members["src/main/java/Extra.java"] == b"class Extra {}\n"
    assert members["pom.xml"] == b"<project/>"
    # Build/cache folders never enter the snapshot.
    assert not any(name.startswith(("target/", "node_modules/")) for name in members)

    # Zero workspace mutation: same bytes, same mtime, and the new file was not created.
    assert app_file.read_bytes() == before_bytes
    assert os.stat(app_file).st_mtime_ns == before_mtime
    assert not (root / "src/main/java/Extra.java").exists()


@pytest.mark.parametrize(
    "file_path",
    ["../escape.java", "/etc/passwd", "C:/windows/system32/drivers/etc/hosts", "src/../../../escape.java"],
)
def test_staging_rejects_path_traversal(tmp_path: Path, file_path: str) -> None:
    root = _workspace(tmp_path, {"src/App.java": "class App {}\n"})

    with pytest.raises(StagingError) as error:
        build_workspace_tar(root, [BuildPatchInput(filePath=file_path, proposedContent="x")])

    assert error.value.status_code == 400
    assert error.value.code == "PATH_REJECTED"


def test_staging_rejects_patches_inside_skipped_folders(tmp_path: Path) -> None:
    root = _workspace(tmp_path, {"package.json": "{}", "node_modules/pkg/index.js": "1"})

    with pytest.raises(StagingError):
        build_workspace_tar(
            root,
            [BuildPatchInput(filePath="node_modules/pkg/index.js", proposedContent="2")],
        )


def test_staging_skips_symlinks_that_escape_the_root(tmp_path: Path) -> None:
    root = _workspace(tmp_path, {"src/App.java": "class App {}\n"})
    secret = tmp_path / "secret.txt"
    secret.write_text("top secret", encoding="utf-8")
    link = root / "src/leak.txt"
    try:
        link.symlink_to(secret)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are not available in this environment")

    members = _tar_members(build_workspace_tar(root, []))

    assert "src/leak.txt" not in members
    assert members["src/App.java"] == b"class App {}\n"


def test_staging_enforces_the_snapshot_size_cap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.builders.staging.MAX_BUILDER_SNAPSHOT_BYTES", 64)
    root = _workspace(tmp_path, {"big.txt": "x" * 256})

    with pytest.raises(StagingError) as error:
        build_workspace_tar(root, [])

    assert error.value.status_code == 413


def test_staging_caps_the_proposed_patch_payload(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.builders.staging.MAX_BUILDER_SNAPSHOT_BYTES", 16)
    root = _workspace(tmp_path, {"src/App.java": "class App {}\n"})

    with pytest.raises(StagingError) as error:
        build_workspace_tar(
            root,
            [BuildPatchInput(filePath="src/App.java", proposedContent="x" * 64)],
        )

    assert error.value.status_code == 413


# ------------------------------------------------------------------------------- diagnostics


def test_maven_diagnostics_are_parsed_and_normalized() -> None:
    output = (
        "\x1b[31m[ERROR] /workspace/src/main/java/com/acme/Foo.java:[12,34] cannot find symbol\x1b[0m\n"
        "[WARNING] /workspace/src/main/java/com/acme/Foo.java:[20,5] unchecked conversion\n"
    )

    diagnostics = parse_diagnostics(output, "java")

    assert [(d.file_path, d.line, d.column, d.severity) for d in diagnostics] == [
        ("src/main/java/com/acme/Foo.java", 12, 34, "error"),
        ("src/main/java/com/acme/Foo.java", 20, 5, "warning"),
    ]
    assert diagnostics[0].message == "cannot find symbol"


def test_msbuild_diagnostics_are_parsed() -> None:
    output = (
        "  Determining projects to restore...\n"
        "/workspace/src/Services/OrderService.cs(42,17): error CS0103: The name 'Total' does not "
        "exist in the current context [/workspace/src/App.csproj]\n"
        "/workspace/src/Models/Order.cs(8,9): warning CS8618: Non-nullable property must contain a "
        "non-null value\n"
    )

    diagnostics = parse_diagnostics(output, "csharp")

    assert [(d.file_path, d.line, d.column, d.severity, d.code) for d in diagnostics] == [
        ("src/Services/OrderService.cs", 42, 17, "error", "CS0103"),
        ("src/Models/Order.cs", 8, 9, "warning", "CS8618"),
    ]
    assert "The name 'Total'" in diagnostics[0].message


def test_tsc_diagnostics_support_both_output_shapes() -> None:
    output = (
        "src/services/order.ts(14,9): error TS2304: Cannot find name 'total'.\n"
        "src/controllers/order.controller.ts:7:3 - warning TS6133: 'req' is declared but never read.\n"
    )

    diagnostics = parse_diagnostics(output, "nodejs")

    assert [(d.file_path, d.line, d.column, d.severity, d.code) for d in diagnostics] == [
        ("src/services/order.ts", 14, 9, "error", "TS2304"),
        ("src/controllers/order.controller.ts", 7, 3, "warning", "TS6133"),
    ]


def test_diagnostic_parsers_deduplicate_and_normalize_paths() -> None:
    line = "[ERROR] /workspace/src/App.java:[1,2] boom\n"
    assert normalize_path("/workspace//src/App.java") == "/src/App.java"
    assert len(parse_diagnostics(line + line, "java")) == 1
    assert normalize_output("\x1b[32mok\x1b[0m\r\n") == "ok"


# ------------------------------------------------------------------------------- runner


class FakeDocker:
    """Records every ``docker`` invocation and answers the runner's inspection calls."""

    def __init__(self, *, images: set[str] | None = None, create_id: str = "cid123") -> None:
        self.images = images if images is not None else {
            config.DEFAULT_BUILDER_IMAGE_JAVA,
            config.DEFAULT_BUILDER_IMAGE_CSHARP,
            config.DEFAULT_BUILDER_IMAGE_NODEJS,
        }
        self.create_id = create_id
        self.calls: list[list[str]] = []
        self.inputs: list[bytes | None] = []

    def __call__(self, args: list[str], *, timeout: int, data: bytes | None = None) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(args))
        self.inputs.append(data)
        if args[:2] == ["docker", "--version"]:
            return _completed("Docker version 28.4.0\n")
        if args[:2] == ["docker", "info"]:
            return _completed("28.4.0\n")
        if args[:3] == ["docker", "image", "inspect"]:
            found = args[-1] in self.images
            return _completed("[]" if found else "", "" if found else "No such image", 0 if found else 1)
        if args[:2] == ["docker", "create"]:
            return _completed(f"{self.create_id}\n")
        return _completed("")

    def find(self, *prefix: str) -> list[list[str]]:
        return [call for call in self.calls if call[: len(prefix)] == list(prefix)]


def _install_docker(monkeypatch: pytest.MonkeyPatch, docker: FakeDocker) -> FakeDocker:
    monkeypatch.setattr(runner, "_run_cli", docker)
    return docker


def test_run_ephemeral_build_uses_hardened_sandbox_flags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _workspace(tmp_path, {"pom.xml": "<project/>", "src/main/java/App.java": "class App {}\n"})
    staged: dict[str, Any] = {}

    def fake_stream(container_id: str, timeout_seconds: int, on_line: Any) -> tuple[int, str, bool, bool]:
        staged["container_id"] = container_id
        staged["timeout"] = timeout_seconds
        if on_line is not None:
            on_line("compiling\n")
        return 0, "BUILD SUCCESS\n[ERROR] /workspace/src/main/java/App.java:[1,1] broken\n", False, False

    docker = _install_docker(monkeypatch, FakeDocker())
    monkeypatch.setattr(runner, "_stream_container", fake_stream)

    result = runner.run_ephemeral_build(root, "java", [], run_tests=False)

    create = docker.find("docker", "create")
    assert len(create) == 1
    args = create[0]
    assert args[args.index("--network") + 1] == "none"
    assert args[args.index("--cap-drop") + 1] == "ALL"
    assert args[args.index("--security-opt") + 1] == "no-new-privileges:true"
    assert args[args.index("--memory") + 1] == "1g"
    assert args[args.index("--cpus") + 1] == "1"
    assert args[args.index("--pids-limit") + 1] == "256"
    assert args[args.index("--user") + 1] == "10001:10001"
    assert args[args.index("-w") + 1] == "/workspace"
    assert "mvn" in args and "-o" in args and args[-1] == "test-compile"

    copy = docker.find("docker", "cp")
    assert copy == [["docker", "cp", "-", "cid123:/workspace"]]
    payload = docker.inputs[docker.calls.index(copy[0])]
    assert payload is not None
    assert "src/main/java/App.java" in _tar_members(payload)

    assert docker.find("docker", "rm", "-f") == [["docker", "rm", "-f", "cid123"]]
    assert result.status == "passed"
    assert result.image == config.DEFAULT_BUILDER_IMAGE_JAVA
    assert result.network_mode == "none"
    assert result.exit_code == 0
    assert [item.file_path for item in result.diagnostics] == ["src/main/java/App.java"]
    assert staged["container_id"] == "cid123"
    assert staged["timeout"] == config.DEFAULT_BUILDER_TIMEOUT_SECONDS


def test_run_ephemeral_build_reports_timeout_and_still_removes_the_container(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _workspace(tmp_path, {"package.json": "{}"})
    docker = _install_docker(monkeypatch, FakeDocker())
    monkeypatch.setattr(
        runner, "_stream_container", lambda *args, **kwargs: (None, "still compiling\n", True, False)
    )

    result = runner.run_ephemeral_build(root, "nodejs", [], run_tests=True)

    assert result.status == "timeout"
    assert docker.find("docker", "rm", "-f") == [["docker", "rm", "-f", "cid123"]]
    assert any("timeout" in warning.lower() for warning in result.warnings)


def test_run_ephemeral_build_removes_the_container_when_the_run_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _workspace(tmp_path, {"package.json": "{}"})
    docker = _install_docker(monkeypatch, FakeDocker())

    def explode(*args: Any, **kwargs: Any) -> tuple[int, str, bool, bool]:
        raise RuntimeError("stream died")

    monkeypatch.setattr(runner, "_stream_container", explode)

    with pytest.raises(RuntimeError):
        runner.run_ephemeral_build(root, "nodejs", [])

    assert docker.find("docker", "rm", "-f") == [["docker", "rm", "-f", "cid123"]]


def test_run_ephemeral_build_removes_the_container_when_copying_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _workspace(tmp_path, {"package.json": "{}"})
    docker = FakeDocker()

    def failing(args: list[str], *, timeout: int, data: bytes | None = None) -> subprocess.CompletedProcess[str]:
        if args[:2] == ["docker", "cp"]:
            docker.calls.append(list(args))
            return _completed("", "copy failed", 1)
        return docker(args, timeout=timeout, data=data)

    monkeypatch.setattr(runner, "_run_cli", failing)

    with pytest.raises(runner.BuildError) as error:
        runner.run_ephemeral_build(root, "nodejs", [])

    assert error.value.code == "BUILDER_COPY_FAILED"
    assert docker.find("docker", "rm", "-f") == [["docker", "rm", "-f", "cid123"]]


def test_run_ephemeral_build_is_unavailable_without_the_image(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _workspace(tmp_path, {"package.json": "{}"})
    docker = _install_docker(monkeypatch, FakeDocker(images=set()))

    result = runner.run_ephemeral_build(root, "nodejs", [])

    assert result.status == "unavailable"
    assert docker.find("docker", "create") == []
    assert any("docker compose --profile builders build" in warning for warning in result.warnings)


def test_run_ephemeral_build_rejects_unknown_stacks(tmp_path: Path) -> None:
    with pytest.raises(runner.BuildError) as error:
        runner.run_ephemeral_build(tmp_path, "ruby", [])
    assert error.value.code == "UNKNOWN_STACK"


def test_cli_timeout_is_a_structured_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(cmd="docker", timeout=1)

    monkeypatch.setattr(runner.subprocess, "run", fake_run)

    with pytest.raises(runner.BuildError) as error:
        runner._run_cli(["docker", "info"], timeout=1)

    assert error.value.status_code == 504
    assert error.value.code == "BUILDER_TIMEOUT"


def test_stream_container_captures_output_and_streams_lines(monkeypatch: pytest.MonkeyPatch) -> None:
    lines = ["line one\n", "\x1b[31mline two\x1b[0m\n"]

    class FakePopen:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.stdout = iter(lines)
            self.returncode = 0

        def poll(self) -> int:
            return 0

        def kill(self) -> None:  # pragma: no cover - the happy path never kills
            raise AssertionError("kill must not be called")

        def wait(self, timeout: int | None = None) -> int:
            return 0

    monkeypatch.setattr(runner.subprocess, "Popen", FakePopen)
    seen: list[str] = []

    exit_code, output, timed_out, truncated = runner._stream_container("cid", 5, seen.append)

    assert exit_code == 0
    assert timed_out is False and truncated is False
    assert "line one" in output and "line two" in output
    assert seen == ["line one", "line two"]


def test_csharp_command_targets_windows_refs_on_both_restore_and_build() -> None:
    build = runner._command_for("csharp", run_tests=False, network_mode="none")
    assert build[:2] == ["sh", "-c"]
    assert "dotnet restore --ignore-failed-sources -p:EnableWindowsTargeting=true" in build[2]
    assert "dotnet build --no-restore -p:EnableWindowsTargeting=true" in build[2]

    tested = runner._command_for("csharp", run_tests=True, network_mode="none")
    assert "dotnet test --no-restore -p:EnableWindowsTargeting=true" in tested[2]


def test_node_commands_match_the_allow_listed_stack() -> None:
    assert runner._command_for("nodejs", run_tests=False, network_mode="none") == ["sh", "-c", "tsc --noEmit"]
    assert runner._command_for("nodejs", run_tests=True, network_mode="none") == [
        "sh",
        "-c",
        "tsc --noEmit && vitest run",
    ]


def test_detect_build_stack_prefers_markers_from_patches_or_tree(tmp_path: Path) -> None:
    java_root = _workspace(tmp_path / "java", {"pom.xml": "<project/>"})
    assert runner.detect_build_stack(java_root) == "java"

    dotnet_root = tmp_path / "dotnet"
    (dotnet_root / "src/App").mkdir(parents=True)
    (dotnet_root / "src/App/App.csproj").write_text("<Project/>", encoding="utf-8")
    assert runner.detect_build_stack(dotnet_root) == "csharp"

    empty = tmp_path / "empty"
    empty.mkdir()
    assert runner.detect_build_stack(empty) is None
    assert (
        runner.detect_build_stack(
            empty, [BuildPatchInput(filePath="tsconfig.json", proposedContent="{}", isNewFile=True)]
        )
        == "nodejs"
    )


def test_builder_config_defaults_and_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    assert config.builders_enabled() is True
    monkeypatch.setenv("KODO_MODE", "saas")
    assert config.builders_enabled() is False
    monkeypatch.setenv("KODO_BUILDERS_ENABLED", "true")
    assert config.builders_enabled() is True

    monkeypatch.setenv("KODO_BUILDER_NETWORK_MODE", "bridge")
    assert config.builder_network_mode() == "bridge"
    monkeypatch.setenv("KODO_BUILDER_NETWORK_MODE", "host-network")
    assert config.builder_network_mode() == "none"

    monkeypatch.setenv("KODO_BUILDER_MEMORY", "2g")
    assert config.builder_memory() == "2g"
    monkeypatch.setenv("KODO_BUILDER_MEMORY", "lots")
    assert config.builder_memory() == config.DEFAULT_BUILDER_MEMORY

    monkeypatch.setenv("KODO_BUILDER_CPUS", "2.5")
    assert config.builder_cpus() == "2.5"
    monkeypatch.setenv("KODO_BUILDER_CPUS", "many")
    assert config.builder_cpus() == config.DEFAULT_BUILDER_CPUS

    assert config.builder_pids_limit() == config.DEFAULT_BUILDER_PIDS_LIMIT
    monkeypatch.setenv("KODO_BUILDER_PIDS_LIMIT", "512")
    assert config.builder_pids_limit() == 512
    monkeypatch.setenv("KODO_BUILDER_PIDS_LIMIT", "1")
    assert config.builder_pids_limit() == config.DEFAULT_BUILDER_PIDS_LIMIT


# ------------------------------------------------------------------------------- routes


def _fake_result(status: str = "passed", diagnostics: list[dict[str, Any]] | None = None) -> BuildResult:
    return BuildResult(
        buildId="build123",
        stack="java",
        status=status,  # type: ignore[arg-type]
        exitCode=0 if status == "passed" else 1,
        durationMs=1234,
        image=config.DEFAULT_BUILDER_IMAGE_JAVA,
        networkMode="none",
        diagnostics=diagnostics or [],
        output="BUILD SUCCESS",
        warnings=[],
    )


def test_build_status_route_reports_images(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.builders.routes.inspect_builder_status",
        lambda: BuilderStatus(
            enabled=True,
            dockerAvailable=True,
            daemonRunning=True,
            images={"java": True, "csharp": False, "nodejs": True},
            warning="Missing builder image(s): csharp",
        ),
    )

    response = client.get("/api/v1/build/status")

    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is True
    assert body["dockerAvailable"] is True
    assert body["images"] == {"java": True, "csharp": False, "nodejs": True}


def test_verify_build_returns_result_and_records_audit(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _workspace(tmp_path, {"pom.xml": "<project/>"})
    captured: dict[str, Any] = {}

    def fake_build(root_path: Any, stack: str, patches: Any, *, run_tests: bool = False, **_: Any) -> BuildResult:
        captured.update(root_path=str(root_path), stack=stack, patches=list(patches), run_tests=run_tests)
        return _fake_result(
            diagnostics=[
                {
                    "filePath": "src/main/java/App.java",
                    "line": 4,
                    "column": 9,
                    "severity": "error",
                    "code": "",
                    "message": "cannot find symbol",
                }
            ]
        )

    monkeypatch.setattr("app.builders.routes.run_ephemeral_build", fake_build)

    response = client.post(
        "/api/v1/build/verify",
        json={
            "rootPath": str(root),
            "patches": [{"filePath": "src/main/java/App.java", "proposedContent": "class App {}\n"}],
            "runTests": True,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["buildId"] == "build123"
    assert body["status"] == "passed"
    assert body["diagnostics"][0]["filePath"] == "src/main/java/App.java"
    assert body["diagnostics"][0]["column"] == 9
    assert captured["stack"] == "java"
    assert captured["run_tests"] is True
    assert captured["patches"][0].file_path == "src/main/java/App.java"

    entries = [entry for entry in read_user_events("local", 10) if entry.action == AUDIT_ACTION_VERIFY_BUILD]
    assert entries, "verify_build must be recorded in the per-user audit log"
    assert entries[0].status == "passed"
    assert "java" in entries[0].summary


def test_verify_build_detects_stack_from_a_new_project_file(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "generated"
    root.mkdir()
    captured: dict[str, str] = {}

    def fake_build(root_path: Any, stack: str, patches: Any, **_: Any) -> BuildResult:
        captured["stack"] = stack
        return _fake_result()

    monkeypatch.setattr("app.builders.routes.run_ephemeral_build", fake_build)

    response = client.post(
        "/api/v1/build/verify",
        json={
            "rootPath": str(root),
            "patches": [{"filePath": "pom.xml", "proposedContent": "<project/>", "isNewFile": True}],
            "runTests": False,
        },
    )

    assert response.status_code == 200
    assert captured["stack"] == "java"


def test_verify_build_rejects_unknown_stacks(client: TestClient, tmp_path: Path) -> None:
    root = tmp_path / "plain"
    root.mkdir()

    response = client.post("/api/v1/build/verify", json={"rootPath": str(root), "runTests": False})

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "UNKNOWN_STACK"


def test_verify_build_stream_emits_logs_then_result(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _workspace(tmp_path, {"package.json": "{}"})

    def fake_build(root_path: Any, stack: str, patches: Any, *, on_line_callback: Any = None, **_: Any) -> BuildResult:
        if on_line_callback is not None:
            on_line_callback("tsc: compiling")
            on_line_callback("src/index.ts(1,1): error TS1005: ';' expected.")
        return _fake_result(status="failed")

    monkeypatch.setattr("app.builders.routes.run_ephemeral_build", fake_build)

    response = client.post(
        "/api/v1/build/verify/stream",
        json={"rootPath": str(root), "stack": "nodejs", "runTests": False},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    text = response.text
    assert "event: log" in text
    assert "tsc: compiling" in text
    assert "event: result" in text
    result_payload = next(
        line[len("data: ") :] for line in text.splitlines() if line.startswith("data: ") and "buildId" in line
    )
    assert json.loads(result_payload)["status"] == "failed"


def test_verify_build_stream_reports_structured_errors(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _workspace(tmp_path, {"package.json": "{}"})

    def explode(*args: Any, **kwargs: Any) -> BuildResult:
        raise runner.BuildError(502, "BUILDER_CREATE_FAILED", "no daemon")

    monkeypatch.setattr("app.builders.routes.run_ephemeral_build", explode)

    response = client.post(
        "/api/v1/build/verify/stream",
        json={"rootPath": str(root), "stack": "nodejs", "runTests": False},
    )

    assert "event: error" in response.text
    assert "BUILDER_CREATE_FAILED" in response.text


@pytest.fixture()
def saas_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Path]:
    monkeypatch.setenv("KODO_MODE", "saas")
    monkeypatch.setenv("KODO_JWT_SECRET", "s" * 48)
    workspaces = tmp_path / "workspaces"
    monkeypatch.setenv("KODO_WORKSPACES_DIR", str(workspaces))
    monkeypatch.setenv("KODO_DATABASE_URL", f"sqlite:///{(tmp_path / 'saas.db').as_posix()}")
    reset_engine()
    try:
        yield workspaces
    finally:
        reset_engine()


def test_saas_build_verify_rejects_host_paths(
    client: TestClient, tmp_path: Path, saas_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = repository.upsert_github_user(
        github_id="42", username="octo", display_name="Octo", avatar_url=None, email=None
    )
    token = create_session_token(user.id, user.username)
    headers = {"Authorization": f"Bearer {token}"}
    host_root = _workspace(tmp_path, {"package.json": "{}"})

    response = client.post(
        "/api/v1/build/verify",
        json={"rootPath": str(host_root), "stack": "nodejs", "runTests": False},
        headers=headers,
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "SAAS_PATH_FORBIDDEN"

    stream = client.post(
        "/api/v1/build/verify/stream",
        json={"rootPath": str(host_root), "stack": "nodejs", "runTests": False},
        headers=headers,
    )
    assert stream.status_code == 403


def test_saas_build_verify_allows_the_tenant_sandbox(
    client: TestClient, saas_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = repository.upsert_github_user(
        github_id="43", username="octo2", display_name="Octo", avatar_url=None, email=None
    )
    token = create_session_token(user.id, user.username)
    sandbox = saas_env / user.id / "shop"
    sandbox.mkdir(parents=True)
    (sandbox / "pom.xml").write_text("<project/>", encoding="utf-8")

    monkeypatch.setattr(
        "app.builders.routes.run_ephemeral_build", lambda *args, **kwargs: _fake_result()
    )

    response = client.post(
        "/api/v1/build/verify",
        json={"rootPath": str(sandbox), "stack": "java", "runTests": False},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "passed"


# ------------------------------------------------------------------------------- AI build fix


@contextmanager
def mock_llm(payload: Any) -> Iterator[list[httpx.Request]]:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": json.dumps(payload)}}]},
        )

    set_transport_override(httpx.MockTransport(handler))
    try:
        yield calls
    finally:
        set_transport_override(None)


LOCAL_LLM = {"baseUrl": "http://127.0.0.1:11434/v1", "codeModel": "deepseek-coder-v2"}


def _java_diagnostic(file_path: str = "src/main/java/com/acme/Foo.java") -> dict[str, Any]:
    return {
        "filePath": file_path,
        "line": 7,
        "column": 12,
        "severity": "error",
        "code": "",
        "message": "cannot find symbol: class Bar",
    }


def test_fix_build_errors_returns_dry_run_patch_with_accurate_sha_and_no_writes(
    client: TestClient, tmp_path: Path
) -> None:
    original = "package com.acme;\n\nclass Foo {\n    Bar bar;\n}\n"
    fixed = "package com.acme;\n\nclass Foo {\n    Baz bar;\n}\n"
    root = _workspace(tmp_path, {"src/main/java/com/acme/Foo.java": original})
    source = root / "src/main/java/com/acme/Foo.java"
    before = source.read_bytes()

    payload = {
        "explanation": "Bar does not exist; Baz is the type imported in this package.",
        "files": [
            {
                "filePath": "src/main/java/com/acme/Foo.java",
                "proposedContent": fixed,
                "summary": ["use the existing Baz type"],
            }
        ],
    }

    with mock_llm(payload) as calls:
        response = client.post(
            "/api/v1/ai/fix-build-errors",
            json={
                "rootPath": str(root),
                "stack": "java",
                "diagnostics": [_java_diagnostic()],
                "compilerOutput": "[ERROR] /workspace/src/main/java/com/acme/Foo.java:[7,12] cannot find symbol",
                "patches": [],
                "llmConfig": LOCAL_LLM,
            },
        )

    assert response.status_code == 200
    body = response.json()
    patch = body["patches"][0]
    assert patch["filePath"] == "src/main/java/com/acme/Foo.java"
    assert patch["originalContent"] == original
    assert patch["originalSha256"] == hashlib.sha256(before).hexdigest()
    assert patch["proposedContent"] == fixed
    assert patch["isNewFile"] is False
    assert body["explanation"].startswith("Bar does not exist")
    assert body["modelUsed"] == "deepseek-coder-v2"

    prompt = json.loads(calls[0].content)["messages"][1]["content"]
    assert "cannot find symbol" in prompt
    assert "src/main/java/com/acme/Foo.java" in prompt
    assert original.splitlines()[-2] in prompt

    # Zero disk writes.
    assert source.read_bytes() == before


def test_fix_build_errors_prefers_the_in_flight_patch_content(
    client: TestClient, tmp_path: Path
) -> None:
    original = "class Foo { int value; }\n"
    proposed = "class Foo { string value; }\n"
    fixed = "class Foo { String value; }\n"
    root = _workspace(tmp_path, {"src/main/java/Foo.java": original})

    payload = {
        "explanation": "Use the boxed String type.",
        "files": [{"filePath": "src/main/java/Foo.java", "proposedContent": fixed}],
    }

    with mock_llm(payload) as calls:
        response = client.post(
            "/api/v1/ai/fix-build-errors",
            json={
                "rootPath": str(root),
                "stack": "java",
                "diagnostics": [_java_diagnostic("src/main/java/Foo.java")],
                "compilerOutput": "[ERROR] /workspace/src/main/java/Foo.java:[1,13] cannot find symbol",
                "patches": [
                    {"filePath": "src/main/java/Foo.java", "proposedContent": proposed, "isNewFile": False}
                ],
                "llmConfig": LOCAL_LLM,
            },
        )

    assert response.status_code == 200
    patch = response.json()["patches"][0]
    assert patch["originalContent"] == original
    assert patch["proposedContent"] == fixed
    prompt = json.loads(calls[0].content)["messages"][1]["content"]
    # The model fixes the patch already in flight, not the stale on-disk text.
    assert proposed.strip() in prompt


def test_fix_build_errors_drops_model_paths_kodo_did_not_send(
    client: TestClient, tmp_path: Path
) -> None:
    root = _workspace(tmp_path, {"src/main/java/Foo.java": "class Foo {}\n"})

    payload = {
        "explanation": "fix",
        "files": [
            {"filePath": "src/main/java/Foo.java", "proposedContent": "class Foo { int x; }\n"},
            {"filePath": "../../etc/passwd", "proposedContent": "root:x:0:0\n"},
        ],
    }

    with mock_llm(payload):
        response = client.post(
            "/api/v1/ai/fix-build-errors",
            json={
                "rootPath": str(root),
                "stack": "java",
                "diagnostics": [_java_diagnostic("src/main/java/Foo.java")],
                "compilerOutput": "boom",
                "llmConfig": LOCAL_LLM,
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert len(body["patches"]) == 1
    assert any("did not send" in warning for warning in body["warnings"])


def test_fix_build_errors_rejects_diagnostic_traversal(client: TestClient, tmp_path: Path) -> None:
    root = _workspace(tmp_path, {"src/main/java/Foo.java": "class Foo {}\n"})
    secret = tmp_path / "secret.java"
    secret.write_text("class Secret {}\n", encoding="utf-8")

    with mock_llm({"explanation": "", "files": []}):
        response = client.post(
            "/api/v1/ai/fix-build-errors",
            json={
                "rootPath": str(root),
                "stack": "java",
                "diagnostics": [_java_diagnostic("../secret.java")],
                "compilerOutput": "boom",
                "llmConfig": LOCAL_LLM,
            },
        )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "PATH_REJECTED"


def test_fix_build_errors_422_when_the_model_changes_nothing(
    client: TestClient, tmp_path: Path
) -> None:
    root = _workspace(tmp_path, {"src/main/java/Foo.java": "class Foo {}\n"})

    with mock_llm({"explanation": "nothing to do", "files": []}):
        response = client.post(
            "/api/v1/ai/fix-build-errors",
            json={
                "rootPath": str(root),
                "stack": "java",
                "diagnostics": [_java_diagnostic("src/main/java/Foo.java")],
                "compilerOutput": "boom",
                "llmConfig": LOCAL_LLM,
            },
        )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "INVALID_PATCH"


def test_fix_build_errors_is_read_only_for_new_files(client: TestClient, tmp_path: Path) -> None:
    root = _workspace(tmp_path, {"pom.xml": "<project/>"})
    relative = "src/main/java/com/acme/NewType.java"
    payload = {
        "explanation": "create the missing type",
        "files": [{"filePath": relative, "proposedContent": "package com.acme;\nclass NewType {}\n"}],
    }

    with mock_llm(payload):
        response = client.post(
            "/api/v1/ai/fix-build-errors",
            json={
                "rootPath": str(root),
                "stack": "java",
                "diagnostics": [_java_diagnostic(relative)],
                "compilerOutput": "cannot find symbol",
                "patches": [{"filePath": relative, "proposedContent": "package com.acme;\n", "isNewFile": True}],
                "llmConfig": LOCAL_LLM,
            },
        )

    assert response.status_code == 200
    patch = response.json()["patches"][0]
    assert patch["isNewFile"] is True
    assert patch["originalSha256"] is None
    assert patch["originalContent"] == ""
    assert not (root / relative).exists()
