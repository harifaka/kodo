"""Local Docker control panel (Phase 6).

Every Docker command is a list-argument ``subprocess.run`` with ``shell=False``, an explicit
working directory inside the validated workspace root and a hard timeout. Kodo only ever runs
read-only inspection (``version``/``info``/``ps``/``logs``) plus ``docker compose up``/``down``
against a ``docker-compose.yml`` that lives inside the requested root — never against an arbitrary
folder and never through a shell.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

from app.deploy.errors import DeployError
from app.deploy.generator import COMPOSE_FILE
from app.deploy.models import (
    DEFAULT_LOG_TAIL,
    MAX_LOG_TAIL,
    ComposeLogs,
    ComposeResult,
    ContainerInfo,
    DockerStatus,
)
from app.patching.paths import PatchRejected, resolve_root
from app.services.audit_log import (
    AUDIT_ACTION_DEPLOY_DOWN,
    AUDIT_ACTION_DEPLOY_UP,
    record_event,
)

STATUS_TIMEOUT_SECONDS = 25
UP_TIMEOUT_SECONDS = 900
DOWN_TIMEOUT_SECONDS = 180
LOGS_TIMEOUT_SECONDS = 60

MAX_CLI_OUTPUT_CHARS = 20_000
MAX_LOG_CHARS = 200_000

_SERVICE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,62}$")
_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def docker_status(root_path: str) -> DockerStatus:
    """Report CLI/daemon reachability, compose presence and the parsed ``compose ps`` table."""
    root = _root(root_path)
    has_compose = has_compose_file(root)

    version = _run_cli(["docker", "--version"], cwd=root, timeout=STATUS_TIMEOUT_SECONDS)
    if version is None or version.returncode != 0:
        return DockerStatus(
            docker_available=False,
            daemon_running=False,
            has_compose_file=has_compose,
            warning="Docker CLI is not installed or not on PATH, so containers cannot be managed here.",
        )

    info = _run_cli(
        ["docker", "info", "--format", "{{.ServerVersion}}"], cwd=root, timeout=STATUS_TIMEOUT_SECONDS
    )
    if info is None or info.returncode != 0:
        detail = _sanitize(_stderr(info)) if info is not None else ""
        return DockerStatus(
            docker_available=True,
            daemon_running=False,
            has_compose_file=has_compose,
            warning=(
                "Docker is installed but the daemon is not reachable. Start Docker Desktop "
                "(or the docker service) and refresh." + (f" {detail}" if detail else "")
            ),
        )

    if not has_compose:
        return DockerStatus(
            docker_available=True,
            daemon_running=True,
            has_compose_file=False,
            warning=(
                f"No {COMPOSE_FILE} exists in this workspace root yet — generate and apply the Docker "
                "files first."
            ),
        )

    ps = _run_cli(
        ["docker", "compose", "ps", "--format", "json"], cwd=root, timeout=STATUS_TIMEOUT_SECONDS
    )
    if ps is None or ps.returncode != 0:
        detail = _sanitize(_stderr(ps)) if ps is not None else ""
        return DockerStatus(
            docker_available=True,
            daemon_running=True,
            has_compose_file=True,
            warning="Could not read container state from `docker compose ps`." + (f" {detail}" if detail else ""),
        )

    return DockerStatus(
        docker_available=True,
        daemon_running=True,
        has_compose_file=True,
        containers=parse_compose_ps(ps.stdout),
    )


def compose_up(root_path: str, *, build: bool) -> ComposeResult:
    """Run ``docker compose up -d [--build]`` inside the validated root and return its status."""
    root = _root(root_path)
    _require_compose_file(root)

    args = ["docker", "compose", "up", "-d"]
    if build:
        args.append("--build")

    result = _run_cli(args, cwd=root, timeout=UP_TIMEOUT_SECONDS)
    success = result is not None and result.returncode == 0
    command = "docker compose " + " ".join(args[2:])
    stderr = _sanitize(_stderr(result)) if result is not None else "Docker CLI is not installed or not on PATH."
    stdout = _clip(_stdout(result)) if result is not None else ""

    record_event(
        AUDIT_ACTION_DEPLOY_UP,
        str(root),
        f"{command} -> exit code {result.returncode if result is not None else 'unavailable'}",
        status="success" if success else "failed",
    )

    return ComposeResult(
        success=success,
        command=command,
        stdout=stdout,
        stderr=stderr,
        status=docker_status(str(root)),
        warning=None if success else (stderr or "docker compose up did not complete successfully."),
    )


def compose_down(root_path: str, *, remove_volumes: bool) -> ComposeResult:
    """Run ``docker compose down [--volumes]`` inside the validated root."""
    root = _root(root_path)
    _require_compose_file(root)

    args = ["docker", "compose", "down"]
    if remove_volumes:
        args.append("--volumes")

    result = _run_cli(args, cwd=root, timeout=DOWN_TIMEOUT_SECONDS)
    success = result is not None and result.returncode == 0
    command = "docker compose " + " ".join(args[2:])
    stderr = _sanitize(_stderr(result)) if result is not None else "Docker CLI is not installed or not on PATH."
    stdout = _clip(_stdout(result)) if result is not None else ""

    record_event(
        AUDIT_ACTION_DEPLOY_DOWN,
        str(root),
        f"{command} -> exit code {result.returncode if result is not None else 'unavailable'}",
        status="success" if success else "failed",
    )

    return ComposeResult(
        success=success,
        command=command,
        stdout=stdout,
        stderr=stderr,
        status=docker_status(str(root)),
        warning=None if success else (stderr or "docker compose down did not complete successfully."),
    )


def compose_logs(
    root_path: str, *, service: str | None = None, tail: int = DEFAULT_LOG_TAIL
) -> ComposeLogs:
    """Return recent, colour-free logs (``tail`` clamped to 1000) for one service or all of them."""
    root = _root(root_path)

    clamped = max(1, min(int(tail), MAX_LOG_TAIL))
    sanitized_service = _validate_service(service)
    _require_compose_file(root)

    args = ["docker", "compose", "logs", "--no-color", "--tail", str(clamped)]
    if sanitized_service:
        args.append(sanitized_service)

    result = _run_cli(args, cwd=root, timeout=LOGS_TIMEOUT_SECONDS)
    if result is None:
        return ComposeLogs(
            service=sanitized_service,
            tail=clamped,
            warning="Docker CLI is not installed or not on PATH.",
        )

    text = _ANSI.sub("", result.stdout or "")
    if len(text) > MAX_LOG_CHARS:
        text = "… (truncated)\n" + text[-MAX_LOG_CHARS:]

    warning = None
    if result.returncode != 0:
        detail = _sanitize(_stderr(result))
        warning = detail or "docker compose logs failed; are the containers running?"

    return ComposeLogs(service=sanitized_service, tail=clamped, logs=text, warning=warning)


def has_compose_file(root: Path) -> bool:
    """True only when ``docker-compose.yml`` is a regular file that resolves inside ``root``."""
    candidate = root / COMPOSE_FILE
    if candidate.is_symlink():
        try:
            resolved = candidate.resolve(strict=True)
        except OSError:
            return False
        return resolved.is_relative_to(root) and resolved.is_file()
    return candidate.is_file()


def parse_compose_ps(raw: str) -> list[ContainerInfo]:
    """Parse ``docker compose ps --format json`` (JSON array, single object or JSON lines)."""
    documents: list[object] = []
    text = (raw or "").strip()
    if not text:
        return []

    try:
        parsed = json.loads(text)
        documents = parsed if isinstance(parsed, list) else [parsed]
    except json.JSONDecodeError:
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                documents.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    containers: list[ContainerInfo] = []
    for document in documents:
        if not isinstance(document, dict):
            continue
        containers.append(
            ContainerInfo(
                name=str(_pick(document, "Name", "Names") or ""),
                service=str(_pick(document, "Service") or ""),
                state=str(_pick(document, "State") or "unknown"),
                status=str(_pick(document, "Status") or ""),
                health=_normalize_health(_pick(document, "Health")),
                ports=_format_ports(document),
            )
        )
    return containers


def _pick(document: dict, *keys: str) -> object:
    for key in keys:
        if key in document and document[key] not in (None, ""):
            return document[key]
    return None


def _normalize_health(value: object) -> str:
    text = str(value or "").strip().lower()
    if text in ("healthy", "unhealthy", "starting"):
        return text
    return "none" if not text or text == "none" else text


def _format_ports(document: dict) -> list[str]:
    ports: list[str] = []
    publishers = document.get("Publishers")
    if isinstance(publishers, list):
        for entry in publishers:
            if not isinstance(entry, dict):
                continue
            target = entry.get("TargetPort")
            published = entry.get("PublishedPort")
            protocol = entry.get("Protocol") or "tcp"
            if not target:
                continue
            if published:
                ports.append(f"{published}->{target}/{protocol}")
            else:
                ports.append(f"{target}/{protocol}")
    if not ports:
        raw_ports = document.get("Ports")
        if isinstance(raw_ports, str) and raw_ports.strip():
            ports.extend(part.strip() for part in raw_ports.split(",") if part.strip())
    return ports


def _validate_service(service: str | None) -> str | None:
    if service is None:
        return None
    value = service.strip()
    if not value:
        return None
    if not _SERVICE_NAME.fullmatch(value):
        raise DeployError(
            400,
            "INVALID_SERVICE",
            "service must contain only letters, digits, '.', '_' or '-' (max 63 characters).",
        )
    return value


def _root(root_path: str) -> Path:
    try:
        return resolve_root(root_path)
    except PatchRejected as exc:
        raise DeployError(exc.status_code, "PATH_REJECTED", str(exc)) from exc


def _require_compose_file(root: Path) -> None:
    if not has_compose_file(root):
        raise DeployError(
            400,
            "NO_COMPOSE_FILE",
            f"{COMPOSE_FILE} does not exist in the workspace root. Generate and apply the Docker "
            "files first.",
        )


def _run_cli(
    args: list[str], *, cwd: Path, timeout: int
) -> subprocess.CompletedProcess[str] | None:
    """Single subprocess seam: list args, ``shell=False``, timeout, no interactive prompts."""
    try:
        return subprocess.run(
            args,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            shell=False,
            env=_cli_env(),
        )
    except FileNotFoundError:
        return None
    except subprocess.TimeoutExpired as exc:
        raise DeployError(
            504,
            "DOCKER_TIMEOUT",
            f"`{' '.join(args)}` did not finish within {timeout}s. Check Docker Desktop and retry.",
        ) from exc
    except OSError as exc:
        raise DeployError(502, "DOCKER_FAILED", f"Could not run Docker: {exc}") from exc


def _cli_env() -> dict[str, str]:
    env = os.environ.copy()
    env["COMPOSE_ANSI"] = "never"
    env["DOCKER_CLI_HINTS"] = "false"
    env["COMPOSE_INTERACTIVE_NO_CLI"] = "1"
    return env


def _stdout(result: subprocess.CompletedProcess[str] | None) -> str:
    return (result.stdout if result is not None else "") or ""


def _stderr(result: subprocess.CompletedProcess[str] | None) -> str:
    return (result.stderr if result is not None else "") or ""


def _sanitize(text: str, limit: int = MAX_CLI_OUTPUT_CHARS) -> str:
    cleaned = _ANSI.sub("", text or "").strip()
    if len(cleaned) > limit:
        cleaned = cleaned[:limit] + " …"
    return cleaned


def _clip(text: str) -> str:
    return _sanitize(text)


__all__ = [
    "ComposeLogs",
    "ComposeResult",
    "ContainerInfo",
    "DockerStatus",
    "compose_down",
    "compose_logs",
    "compose_up",
    "docker_status",
    "has_compose_file",
    "parse_compose_ps",
]
