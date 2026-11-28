"""Two lightweight read-only MCP resources: ``kodo://health`` and ``kodo://stacks``.

They give an agent a cheap way to discover what the server can do (stacks, audit rules, builder and
System 1 availability) before spending a tool call on a full workspace scan.
"""

from __future__ import annotations

import json
from typing import Any

from app import __version__
from app.builders.models import BuilderStatus
from app.builders.runner import inspect_builder_status
from app.config import (
    BUILDER_STACKS,
    ConfigurationError,
    builder_image,
    builders_enabled,
    csharp_analyzer_url,
    get_settings,
    systemone_enabled,
)
from app.decision.config import resolve_config
from app.mcp import MCP_PROTOCOL
from app.mcp.protocol import INVALID_PARAMS, PROTOCOL_VERSIONS, RpcError
from app.mcp.tools import TOOL_SPECS, audit_rule_catalog
from app.models.ir import Stack
from app.services.csharp_client import check_health

HEALTH_URI = "kodo://health"
STACKS_URI = "kodo://stacks"
JSON_MIME = "application/json"

RESOURCE_DEFINITIONS: tuple[dict[str, str], ...] = (
    {
        "uri": HEALTH_URI,
        "name": "kodo-health",
        "title": "Kodo health",
        "description": (
            "Kodo version and mode, Roslyn reachability, builder image readiness and the local "
            "System 1 (Laya) configuration status."
        ),
        "mimeType": JSON_MIME,
    },
    {
        "uri": STACKS_URI,
        "name": "kodo-stacks",
        "title": "Supported stacks and audit rules",
        "description": "Supported stacks (java, csharp, nodejs, python) and the deterministic audit rule catalog.",
        "mimeType": JSON_MIME,
    },
)

_STACK_META: tuple[dict[str, Any], ...] = (
    {
        "id": "java",
        "framework": "Spring Boot",
        "irStack": str(Stack.SPRING_BOOT),
        "markers": ["pom.xml"],
        "extensions": [".java"],
    },
    {
        "id": "csharp",
        "framework": ".NET / WPF",
        "irStack": str(Stack.CSHARP_DOTNET),
        "markers": ["*.csproj", "*.sln"],
        "extensions": [".cs"],
    },
    {
        "id": "nodejs",
        "framework": "Node.js / TypeScript",
        "irStack": str(Stack.NODEJS),
        "markers": ["package.json", "tsconfig.json"],
        "extensions": [".ts", ".tsx", ".js", ".jsx"],
    },
    {
        "id": "python",
        "framework": "FastAPI / Django / Flask",
        "irStack": str(Stack.PYTHON),
        "markers": ["pyproject.toml", "requirements.txt", "setup.py"],
        "extensions": [".py"],
    },
)


def list_resources() -> list[dict[str, str]]:
    return [dict(definition) for definition in RESOURCE_DEFINITIONS]


def _mode() -> str:
    try:
        return get_settings().mode
    except ConfigurationError:
        return "misconfigured"


def _builders_payload() -> dict[str, Any]:
    status: BuilderStatus = inspect_builder_status()
    return {
        "enabled": status.enabled,
        "dockerAvailable": status.docker_available,
        "daemonRunning": status.daemon_running,
        "images": dict(status.images),
        "warning": status.warning,
    }


def _system_one_payload() -> dict[str, Any]:
    cfg = resolve_config(None)
    return {
        "enabled": systemone_enabled(),
        "baseUrl": cfg.base_url,
        "model": cfg.model,
        "autoThreshold": cfg.auto_threshold,
        "provider": cfg.provider_hint,
    }


async def _health_payload() -> dict[str, Any]:
    reachable = await check_health()
    return {
        "service": "kodo",
        "version": __version__,
        "mode": _mode(),
        "analyzers": {
            "csharp": {"url": csharp_analyzer_url(), "reachable": reachable},
        },
        "builders": _builders_payload(),
        "systemOne": _system_one_payload(),
        "mcp": {
            "protocol": MCP_PROTOCOL,
            "protocolVersions": list(PROTOCOL_VERSIONS),
            "transports": ["streamable-http", "stdio"],
            "toolCount": len(TOOL_SPECS),
            "readOnly": True,
        },
    }


def _stacks_payload() -> dict[str, Any]:
    builder_images = {stack: builder_image(stack) for stack in BUILDER_STACKS}
    return {
        "stacks": [
            {
                **meta,
                "builderImage": builder_images.get(meta["id"], ""),
                "builderEnabled": builders_enabled(),
            }
            for meta in _STACK_META
        ],
        "auditRules": audit_rule_catalog(),
    }


async def read_resource(uri: str) -> dict[str, Any]:
    """MCP ``resources/read`` payload for a known ``kodo://`` URI."""
    if uri == HEALTH_URI:
        payload = await _health_payload()
    elif uri == STACKS_URI:
        payload = _stacks_payload()
    else:
        raise RpcError(INVALID_PARAMS, f"Unknown resource: {uri}", {"available": [HEALTH_URI, STACKS_URI]})

    return {
        "contents": [
            {
                "uri": uri,
                "mimeType": JSON_MIME,
                "text": json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            }
        ]
    }


__all__ = [
    "HEALTH_URI",
    "RESOURCE_DEFINITIONS",
    "STACKS_URI",
    "list_resources",
    "read_resource",
]
