"""HTTP client for the C# Roslyn analyzer. Degrades gracefully when it is offline."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from pydantic import ValidationError

from app.config import csharp_analyzer_url
from app.models.ir import ComponentNode, ComponentRelation

_HEALTH_TIMEOUT = 1.5
_ANALYZE_TIMEOUT = 90.0


@dataclass
class CSharpResult:
    nodes: list[ComponentNode] = field(default_factory=list)
    relations: list[ComponentRelation] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    reachable: bool = False


async def check_health() -> bool:
    url = f"{csharp_analyzer_url()}/health"
    try:
        async with httpx.AsyncClient(timeout=_HEALTH_TIMEOUT) as client:
            response = await client.get(url)
            return response.status_code == 200 and response.json().get("status") == "ok"
    except (httpx.HTTPError, ValueError, asyncio.TimeoutError):
        return False


async def analyze_workspace(root: Path, files: list[str]) -> CSharpResult:
    result = CSharpResult()
    if not files:
        return result

    url = f"{csharp_analyzer_url()}/analyze"
    payload = {"rootPath": str(root), "files": files}

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(_ANALYZE_TIMEOUT, connect=3.0)) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()
    except (httpx.HTTPError, ValueError, asyncio.TimeoutError) as exc:
        result.warnings.append(
            f"C# analyzer unreachable at {csharp_analyzer_url()} ({type(exc).__name__}). "
            f"{len(files)} .cs file(s) were skipped — start services/analyzer-csharp and rescan."
        )
        return result

    result.reachable = True

    for raw_node in data.get("nodes", []):
        try:
            result.nodes.append(ComponentNode.model_validate(raw_node))
        except ValidationError:
            result.warnings.append(
                "C# analyzer returned a node that does not match the Core IR contract; it was skipped."
            )

    for raw_relation in data.get("relations", []):
        try:
            result.relations.append(ComponentRelation.model_validate(raw_relation))
        except ValidationError:
            result.warnings.append(
                "C# analyzer returned a relation that does not match the Core IR contract; it was skipped."
            )

    result.warnings.extend(str(warning) for warning in data.get("warnings", []))
    return result
