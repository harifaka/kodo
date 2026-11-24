"""Ephemeral builder runner (Phase 9).

A build is one disposable container created from an allow-listed, pre-warmed image. The workspace is
never mounted: a tar snapshot (proposed patches overlaid in memory) is streamed in with
``docker cp -``, the container runs offline as uid 10001 with every capability dropped, and cleanup
always runs ``docker rm -f`` in a ``finally`` block. Only list-argument subprocesses are used
(``shell=False``); the one ``sh -c`` string is a fixed constant executed *inside* the container.
"""

from __future__ import annotations

import os
import queue
import subprocess
import threading
import time
import uuid
from collections.abc import Callable
from pathlib import Path

from app.builders.diagnostics import normalize_output, parse_diagnostics, strip_ansi
from app.builders.models import (
    BuildDiagnostic,
    BuildError,
    BuilderStatus,
    BuildPatchInput,
    BuildResult,
    BuildStatusId,
)
from app.builders.staging import SKIP_DIRECTORIES, build_workspace_tar
from app.config import (
    BUILDER_STACKS,
    MAX_BUILDER_LOG_BYTES,
    builder_cpus,
    builder_image,
    builder_memory,
    builder_network_mode,
    builder_pids_limit,
    builder_timeout_seconds,
    builders_enabled,
)

BUILDER_USER = "10001:10001"
WORKSPACE_PATH = "/workspace"
CLI_TIMEOUT_SECONDS = 60
STREAM_POLL_SECONDS = 0.25
MAX_CALLBACK_LINE_CHARS = 4_000

# Fixed commands per stack. Anything else is rejected by the allow-list, so no user input ever
# reaches a command line.
_NODE_COMMANDS = {
    False: "tsc --noEmit",
    True: "tsc --noEmit && vitest run",
}
# A staged snapshot deliberately excludes obj/, so `--no-restore` alone would fail with NETSDK1004.
# Restore first (resolved from the pre-warmed NuGet cache with --network=none), then build/test.
_CSHARP_COMMANDS = {
    False: (
        "dotnet restore --ignore-failed-sources -p:EnableWindowsTargeting=true && "
        "dotnet build --no-restore -p:EnableWindowsTargeting=true"
    ),
    True: (
        "dotnet restore --ignore-failed-sources -p:EnableWindowsTargeting=true && "
        "dotnet test --no-restore -p:EnableWindowsTargeting=true"
    ),
}


def run_ephemeral_build(
    root_path: str | Path,
    stack: str,
    patches: list[BuildPatchInput],
    *,
    run_tests: bool = False,
    on_line_callback: Callable[[str], None] | None = None,
) -> BuildResult:
    """Stage the workspace and verify it in a disposable, network-isolated builder container."""
    if stack not in BUILDER_STACKS:
        raise BuildError(
            400, "UNKNOWN_STACK", f"Stack '{stack}' is not one of the allow-listed builders: Java, C#, Node.js."
        )

    build_id = uuid.uuid4().hex[:12]
    started = time.monotonic()
    image = builder_image(stack)
    network_mode = builder_network_mode()
    timeout_seconds = builder_timeout_seconds()

    if not builders_enabled():
        return _result(
            build_id,
            stack,
            status="unavailable",
            image=image,
            network_mode=network_mode,
            started=started,
            warnings=["Builder verification is disabled (KODO_BUILDERS_ENABLED=false)."],
        )

    warnings: list[str] = []
    skipped: list[str] = []
    staged = build_workspace_tar(Path(root_path), patches, skipped=skipped)
    warnings.extend(f"Skipped while staging: {entry}" for entry in skipped)

    if stack == "csharp" and _has_xaml(Path(root_path)):
        warnings.append(
            "WPF project detected: XAML compilation needs Windows, so Kodo verifies the C# compile here "
            "and a XAML-only failure is reported as a warning rather than a binary error."
        )

    if not _docker_available():
        return _result(
            build_id,
            stack,
            status="unavailable",
            image=image,
            network_mode=network_mode,
            started=started,
            warnings=[
                *warnings,
                "Docker CLI/daemon is unavailable, so the ephemeral builder cannot run on this host.",
            ],
        )

    if not _image_exists(image):
        return _result(
            build_id,
            stack,
            status="unavailable",
            image=image,
            network_mode=network_mode,
            started=started,
            warnings=[
                *warnings,
                f"Builder image '{image}' is not present locally. Build it with "
                "`docker compose --profile builders build` (Kodo never pulls at verify time).",
            ],
        )

    command = _command_for(stack, run_tests=run_tests, network_mode=network_mode)
    container_id: str | None = None
    try:
        container_id = _create_container(build_id, image, network_mode, command)
        _copy_snapshot(container_id, staged)
        exit_code, raw_output, timed_out, truncated = _stream_container(
            container_id, timeout_seconds, on_line_callback
        )
    finally:
        if container_id:
            _remove_container(container_id)

    output = normalize_output(raw_output)
    if truncated:
        warnings.append(
            f"Build output was truncated to {MAX_BUILDER_LOG_BYTES // 1024} KB; the full log stayed in "
            "the disposed container."
        )

    if timed_out:
        status = "timeout"
        warnings.append(
            f"The build exceeded the {timeout_seconds}s sandbox timeout and the container was killed."
        )
    elif exit_code == 0:
        status = "passed"
    else:
        status = "failed"

    diagnostics = parse_diagnostics(output, stack)
    if status != "passed" and stack == "csharp" and _looks_like_xaml_failure(output):
        warnings.append(
            "The failure came from the Linux-only .NET SDK refusing WPF/XAML targets. Build the desktop "
            "UI on Windows and use Kodo's sidecar template for the containerized API."
        )

    return _result(
        build_id,
        stack,
        status=status,
        image=image,
        network_mode=network_mode,
        started=started,
        exit_code=exit_code,
        diagnostics=diagnostics,
        output=output,
        warnings=warnings,
    )


def detect_build_stack(
    root_path: str | Path, patches: list[BuildPatchInput] | None = None
) -> str | None:
    """Resolve the build stack from the workspace tree and any files a patch proposes to create."""
    names = {_basename(patch.file_path) for patch in patches or []}
    names.update(_tree_markers(Path(root_path)))

    if "pom.xml" in names:
        return "java"
    if any(name.endswith((".csproj", ".sln")) for name in names):
        return "csharp"
    if "package.json" in names or "tsconfig.json" in names:
        return "nodejs"
    return None


def inspect_builder_status() -> BuilderStatus:
    """Report builder enablement, Docker reachability and which allow-listed images exist locally."""
    images = {stack: False for stack in BUILDER_STACKS}
    if not builders_enabled():
        return BuilderStatus(
            enabled=False,
            docker_available=False,
            daemon_running=False,
            images=images,
            warning="Builder verification is disabled (KODO_BUILDERS_ENABLED=false).",
        )

    version = _run_cli(["docker", "--version"], timeout=15)
    if version is None or version.returncode != 0:
        return BuilderStatus(
            enabled=True,
            docker_available=False,
            daemon_running=False,
            images=images,
            warning="Docker CLI is not installed or not on PATH, so the ephemeral builder is offline.",
        )

    info = _run_cli(["docker", "info", "--format", "{{.ServerVersion}}"], timeout=20)
    if info is None or info.returncode != 0:
        return BuilderStatus(
            enabled=True,
            docker_available=True,
            daemon_running=False,
            images=images,
            warning=(
                "Docker is installed but the daemon is not reachable. Start Docker Desktop "
                "(or the docker service) and refresh."
            ),
        )

    for stack in BUILDER_STACKS:
        images[stack] = _image_exists(builder_image(stack))

    missing = [f"{stack} ({builder_image(stack)})" for stack, ready in images.items() if not ready]
    warning = None
    if missing:
        warning = (
            "Missing builder image(s): "
            + ", ".join(missing)
            + ". Build them with `docker compose --profile builders build`."
        )

    return BuilderStatus(
        enabled=True,
        docker_available=True,
        daemon_running=True,
        images=images,
        warning=warning,
    )


def _command_for(stack: str, *, run_tests: bool, network_mode: str) -> list[str]:
    if stack == "java":
        goal = "test" if run_tests else "test-compile"
        # The pre-warmed local repository is only guaranteed to satisfy the build offline; when the
        # operator explicitly allows network access Maven may resolve anything it is missing.
        args = ["mvn", "-B"]
        if network_mode == "none":
            args.append("-o")
        return [*args, goal]

    if stack == "csharp":
        return ["sh", "-c", _CSHARP_COMMANDS[run_tests]]

    return ["sh", "-c", _NODE_COMMANDS[run_tests]]


def _create_container(build_id: str, image: str, network_mode: str, command: list[str]) -> str:
    args = [
        "docker",
        "create",
        "--name",
        f"kodo-build-{build_id}",
        "--label",
        "kodo.role=builder",
        "-w",
        WORKSPACE_PATH,
        "--user",
        BUILDER_USER,
        "--network",
        network_mode,
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges:true",
        "--memory",
        builder_memory(),
        "--cpus",
        builder_cpus(),
        "--pids-limit",
        str(builder_pids_limit()),
        image,
        *command,
    ]
    result = _run_cli(args, timeout=CLI_TIMEOUT_SECONDS)
    if result is None:
        raise BuildError(502, "BUILDER_UNAVAILABLE", "Docker CLI is not installed or not on PATH.")
    if result.returncode != 0:
        raise BuildError(
            502,
            "BUILDER_CREATE_FAILED",
            f"Could not create the builder container: {_sanitize(result.stderr) or 'unknown Docker error'}",
        )
    container_id = (result.stdout or "").strip().splitlines()
    if not container_id:
        raise BuildError(502, "BUILDER_CREATE_FAILED", "Docker did not return a container id.")
    return container_id[-1]


def _copy_snapshot(container_id: str, staged: bytes) -> None:
    result = _run_cli(
        ["docker", "cp", "-", f"{container_id}:{WORKSPACE_PATH}"],
        timeout=CLI_TIMEOUT_SECONDS,
        data=staged,
    )
    if result is None:
        raise BuildError(502, "BUILDER_UNAVAILABLE", "Docker CLI is not installed or not on PATH.")
    if result.returncode != 0:
        raise BuildError(
            502,
            "BUILDER_COPY_FAILED",
            f"Could not stream the staged workspace into the container: "
            f"{_sanitize(result.stderr) or 'unknown Docker error'}",
        )


def _stream_container(
    container_id: str,
    timeout_seconds: int,
    on_line: Callable[[str], None] | None,
) -> tuple[int | None, str, bool, bool]:
    """Run ``docker start -a``, streaming lines until exit or timeout. Returns collected output."""
    proc = subprocess.Popen(
        ["docker", "start", "-a", container_id],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        shell=False,
        env=_cli_env(),
    )

    lines: queue.Queue[str | None] = queue.Queue()

    def _reader() -> None:
        try:
            if proc.stdout is not None:
                for line in proc.stdout:
                    lines.put(line)
        finally:
            lines.put(None)

    reader = threading.Thread(target=_reader, name="kodo-build-log", daemon=True)
    reader.start()

    collected: list[str] = []
    size = 0
    truncated = False
    timed_out = False
    deadline = time.monotonic() + timeout_seconds

    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                proc.kill()
                break
            try:
                item = lines.get(timeout=min(remaining, STREAM_POLL_SECONDS))
            except queue.Empty:
                continue
            if item is None:
                break

            if size < MAX_BUILDER_LOG_BYTES:
                encoded = item.encode("utf-8", errors="replace")
                kept_bytes = encoded[: MAX_BUILDER_LOG_BYTES - size]
                collected.append(kept_bytes.decode("utf-8", errors="replace"))
                size += len(kept_bytes)
                if len(kept_bytes) < len(encoded):
                    truncated = True
            else:
                truncated = True

            if on_line is not None:
                _emit(on_line, strip_ansi(item))
    finally:
        if proc.poll() is None:
            proc.kill()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
        reader.join(timeout=5)

    return proc.returncode, "".join(collected), timed_out, truncated


def _remove_container(container_id: str) -> None:
    """Guaranteed cleanup: force-remove the container and ignore an already-gone id."""
    try:
        _run_cli(["docker", "rm", "-f", container_id], timeout=CLI_TIMEOUT_SECONDS)
    except Exception:
        return


def _image_exists(image: str) -> bool:
    result = _run_cli(["docker", "image", "inspect", image], timeout=15)
    return result is not None and result.returncode == 0


def _docker_available() -> bool:
    version = _run_cli(["docker", "--version"], timeout=15)
    if version is None or version.returncode != 0:
        return False
    info = _run_cli(["docker", "info", "--format", "{{.ServerVersion}}"], timeout=20)
    return info is not None and info.returncode == 0


def _run_cli(
    args: list[str],
    *,
    timeout: int,
    data: bytes | None = None,
) -> subprocess.CompletedProcess[str] | None:
    """Single subprocess seam for tests: list args, ``shell=False``, explicit timeout."""
    try:
        if data is None:
            return subprocess.run(
                args,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
                shell=False,
                env=_cli_env(),
            )
        return subprocess.run(
            args,
            input=data,
            capture_output=True,
            text=False,
            timeout=timeout,
            check=False,
            shell=False,
            env=_cli_env(),
        )
    except FileNotFoundError:
        return None
    except subprocess.TimeoutExpired as exc:
        raise BuildError(
            504,
            "BUILDER_TIMEOUT",
            f"`docker {' '.join(args[1:2])}` did not finish within {timeout}s.",
        ) from exc
    except OSError as exc:
        raise BuildError(502, "BUILDER_FAILED", f"Could not run Docker: {exc}") from exc


def _cli_env() -> dict[str, str]:
    env = os.environ.copy()
    env["DOCKER_CLI_HINTS"] = "false"
    return env


def _emit(callback: Callable[[str], None], line: str) -> None:
    try:
        callback(line[:MAX_CALLBACK_LINE_CHARS].rstrip("\n"))
    except Exception:
        # A broken stream consumer must never abort the build or its cleanup.
        return


def _basename(raw: str) -> str:
    return (raw or "").replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]


def _tree_markers(root: Path, max_entries: int = 4_000) -> set[str]:
    """Top-level names plus markers up to two folders deep, skipping build/cache directories."""
    names: set[str] = set()
    if not root.is_dir():
        return names
    seen = 0
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        current = Path(dirpath)
        depth = len(current.relative_to(root).parts)
        if depth >= 2:
            dirnames[:] = []
        else:
            dirnames[:] = sorted(
                name for name in dirnames if name not in SKIP_DIRECTORIES and not (current / name).is_symlink()
            )
        for name in filenames:
            names.add(name)
            seen += 1
            if seen >= max_entries:
                return names
    return names


def _has_xaml(root: Path, max_entries: int = 4_000) -> bool:
    if not root.is_dir():
        return False
    seen = 0
    for _dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(name for name in dirnames if name not in SKIP_DIRECTORIES)
        for name in filenames:
            if name.lower().endswith(".xaml"):
                return True
            seen += 1
            if seen >= max_entries:
                return False
    return False


def _looks_like_xaml_failure(output: str) -> bool:
    lowered = output.lower()
    return any(
        marker in lowered
        for marker in ("markupcompilepass", "xaml", "presentationframework", "windowsdesktop")
    )


def _sanitize(text: str | bytes | None) -> str:
    if text is None:
        return ""
    if isinstance(text, bytes):
        text = text.decode("utf-8", errors="replace")
    return strip_ansi(text).strip()[:2_000]


def _result(
    build_id: str,
    stack: str,
    *,
    status: BuildStatusId,
    image: str,
    network_mode: str,
    started: float,
    exit_code: int | None = None,
    diagnostics: list[BuildDiagnostic] | None = None,
    output: str = "",
    warnings: list[str] | None = None,
) -> BuildResult:
    return BuildResult(
        build_id=build_id,
        stack=stack,
        status=status,
        exit_code=exit_code,
        duration_ms=int((time.monotonic() - started) * 1000),
        image=image,
        network_mode=network_mode,
        diagnostics=diagnostics or [],
        output=output,
        warnings=warnings or [],
    )


__all__ = [
    "detect_build_stack",
    "inspect_builder_status",
    "run_ephemeral_build",
]
