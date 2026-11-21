"""Deploy Studio constants shared by the generator, templates and runner."""

from __future__ import annotations

SPRING_BOOT = "spring-boot"
NODEJS = "nodejs"
CSHARP_DOTNET = "csharp-dotnet"
CSHARP_WPF = "csharp-wpf"

STACKS: tuple[str, ...] = (SPRING_BOOT, NODEJS, CSHARP_DOTNET, CSHARP_WPF)
BACKING_SERVICES: tuple[str, ...] = ("postgres", "redis", "rabbitmq")

DOCKERFILE = "Dockerfile"
SIDECAR_DOCKERFILE = "Dockerfile.sidecar"
DOCKERIGNORE = ".dockerignore"
COMPOSE_FILE = "docker-compose.yml"
ENV_EXAMPLE = ".env.example"

STACK_LABELS = {
    SPRING_BOOT: "Spring Boot (Java 21)",
    NODEJS: "Node.js (TypeScript)",
    CSHARP_DOTNET: "C# / .NET 8",
    CSHARP_WPF: "C# WPF (.NET 8, desktop)",
}

DEFAULT_PORTS = {SPRING_BOOT: 8080, NODEJS: 3000, CSHARP_DOTNET: 8080, CSHARP_WPF: 8080}
HEALTH_PATHS = {SPRING_BOOT: "/actuator/health", NODEJS: "/health", CSHARP_DOTNET: "/health"}

# Placeholders only. Real credentials belong in a local, git-ignored .env file.
PASSWORD_PLACEHOLDER = "change-me-local-only"
PASSWORD_FALLBACK = "change-me"

__all__ = [
    "BACKING_SERVICES",
    "COMPOSE_FILE",
    "CSHARP_DOTNET",
    "CSHARP_WPF",
    "DEFAULT_PORTS",
    "DOCKERFILE",
    "DOCKERIGNORE",
    "ENV_EXAMPLE",
    "HEALTH_PATHS",
    "NODEJS",
    "PASSWORD_FALLBACK",
    "PASSWORD_PLACEHOLDER",
    "SIDECAR_DOCKERFILE",
    "SPRING_BOOT",
    "STACKS",
    "STACK_LABELS",
]
