"""Deterministic Docker artifact generation for the Deploy Studio (Phase 6).

Pure by design: the stack, project name, port and selected backing services go in; file text comes
out. Nothing here reads or writes the filesystem, spawns Docker or needs network access — the
artifacts are returned as ``DryRunResponse`` patches and reach disk only through the guarded
``POST /api/v1/apply`` pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.deploy.compose import compose_yaml, dockerignore, env_example
from app.deploy.dockerfiles import dockerfile_for, sidecar_dockerfile
from app.deploy.errors import DeployError
from app.deploy.spec import (
    BACKING_SERVICES,
    COMPOSE_FILE,
    CSHARP_DOTNET,
    CSHARP_WPF,
    DEFAULT_PORTS,
    DOCKERFILE,
    DOCKERIGNORE,
    ENV_EXAMPLE,
    NODEJS,
    SIDECAR_DOCKERFILE,
    SPRING_BOOT,
    STACK_LABELS,
    STACKS,
)
from app.generators.base import GeneratedFile, kebab_case

_ALIASES = {
    SPRING_BOOT: SPRING_BOOT,
    "spring": SPRING_BOOT,
    "java": SPRING_BOOT,
    NODEJS: NODEJS,
    "node": NODEJS,
    "typescript": NODEJS,
    CSHARP_DOTNET: CSHARP_DOTNET,
    "dotnet": CSHARP_DOTNET,
    "csharp": CSHARP_DOTNET,
    "aspnet": CSHARP_DOTNET,
    CSHARP_WPF: CSHARP_WPF,
    "wpf": CSHARP_WPF,
}


@dataclass(frozen=True, slots=True)
class DeployArtifacts:
    """Generated container artifacts plus human-readable warnings for the dry-run response."""

    stack: str
    files: list[GeneratedFile]
    warnings: list[str]


def normalize_stack(raw: str) -> str:
    value = (raw or "").strip().lower()
    stack = _ALIASES.get(value)
    if stack is None:
        raise DeployError(
            400,
            "UNKNOWN_STACK",
            f"Unknown stack '{raw}'. Use one of: {', '.join(STACKS)}.",
        )
    return stack


def detect_stack(root: Path) -> str | None:
    """Best-effort stack detection from marker files at the repository root (bounded, read-only)."""
    try:
        entries = list(root.iterdir())
    except OSError:
        return None

    names = {entry.name.lower() for entry in entries}
    has_wpf_marker = any(name.endswith(".xaml") for name in names)

    if {"pom.xml", "build.gradle", "build.gradle.kts"} & names:
        return SPRING_BOOT
    if "package.json" in names:
        return NODEJS
    if any(name.endswith((".csproj", ".sln", ".fsproj")) for name in names) or has_wpf_marker:
        return CSHARP_WPF if has_wpf_marker else CSHARP_DOTNET
    return None


def normalize_backing_services(values: list[str] | tuple[str, ...] | None) -> tuple[str, ...]:
    requested = {str(value).strip().lower() for value in (values or ())}
    unknown = sorted(requested - set(BACKING_SERVICES))
    if unknown:
        raise DeployError(
            400,
            "UNKNOWN_BACKING_SERVICE",
            f"Unsupported backing service(s): {', '.join(unknown)}. "
            f"Choose from: {', '.join(BACKING_SERVICES)}.",
        )
    return tuple(service for service in BACKING_SERVICES if service in requested)


def generate_artifacts(
    *,
    stack: str,
    project_name: str,
    app_port: int | None,
    backing_services: list[str] | tuple[str, ...] | None,
    root: Path,
) -> DeployArtifacts:
    """Render ``Dockerfile`` (+ sidecar for WPF), ``.dockerignore``, compose and ``.env.example``."""
    stack_id = normalize_stack(stack)
    name = (project_name or "").strip()
    if not name:
        raise DeployError(400, "INVALID_PROJECT_NAME", "projectName is required.")
    if len(name) > 80:
        raise DeployError(400, "INVALID_PROJECT_NAME", "projectName must be 80 characters or fewer.")

    slug = kebab_case(name)
    port = _validate_port(app_port if app_port is not None else DEFAULT_PORTS[stack_id])
    services = normalize_backing_services(backing_services)
    wpf = stack_id == CSHARP_WPF

    files: list[GeneratedFile] = []
    warnings: list[str] = []

    if wpf:
        files.append(
            GeneratedFile(
                file_path=SIDECAR_DOCKERFILE,
                content=sidecar_dockerfile(port),
                summary="Optional Linux sidecar/API container (the WPF desktop UI itself stays Windows-only)",
            )
        )
        warnings.append(
            "WPF cannot run in a Linux container: the generated compose file only starts the backing "
            "services plus an optional sidecar/API container. Publish the desktop app for Windows and "
            "point it at the sidecar API."
        )
    else:
        files.append(
            GeneratedFile(
                file_path=DOCKERFILE,
                content=dockerfile_for(stack_id, name, port),
                summary=f"Multi-stage, non-root {STACK_LABELS[stack_id]} image",
            )
        )

    files.append(
        GeneratedFile(
            file_path=DOCKERIGNORE,
            content=dockerignore(stack_id),
            summary="Build-context exclusions (VCS, secrets, build output, dependencies)",
        )
    )
    files.append(
        GeneratedFile(
            file_path=COMPOSE_FILE,
            content=compose_yaml(stack=stack_id, slug=slug, port=port, services=services, sidecar_only=wpf),
            summary="Compose stack with healthchecks, depends_on and an internal kodo-net bridge",
        )
    )
    files.append(
        GeneratedFile(
            file_path=ENV_EXAMPLE,
            content=env_example(port, services),
            summary="Environment template with placeholders only (never real secrets)",
        )
    )

    warnings.extend(_root_warnings(stack_id, root))
    return DeployArtifacts(stack=stack_id, files=files, warnings=warnings)


def _validate_port(port: int) -> int:
    if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
        raise DeployError(400, "INVALID_PORT", "appPort must be an integer between 1 and 65535.")
    return port


def _root_warnings(stack: str, root: Path) -> list[str]:
    probes = {
        SPRING_BOOT: ("pom.xml", "The Maven build stage expects pom.xml at the repository root."),
        NODEJS: ("package.json", "The Node build stage expects package.json at the repository root."),
        CSHARP_DOTNET: (
            None,
            "The .NET build stage expects the solution/project files at the repository root.",
        ),
        CSHARP_WPF: (None, "The sidecar template targets a Linux ASP.NET Core API, not the WPF UI."),
    }
    marker, message = probes[stack]
    if marker is not None and not (root / marker).is_file():
        return [message]
    return []


__all__ = [
    "BACKING_SERVICES",
    "COMPOSE_FILE",
    "DOCKERFILE",
    "DOCKERIGNORE",
    "ENV_EXAMPLE",
    "SIDECAR_DOCKERFILE",
    "STACKS",
    "STACK_LABELS",
    "DeployArtifacts",
    "detect_stack",
    "generate_artifacts",
    "normalize_backing_services",
    "normalize_stack",
]
