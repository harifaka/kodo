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

# The analyzer is stateless: it only sees what we send, so the cap is enforced here too.
MAX_ANALYZER_FILE_BYTES = 2_000_000


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

    # Reading happens on the orchestrator: the Roslyn container mounts no workspace volume.
    payload_files = await asyncio.to_thread(_read_sources, root, files, result.warnings)
    if not payload_files:
        return result

    url = f"{csharp_analyzer_url()}/analyze"
    payload = {"rootPath": str(root), "files": payload_files}

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(_ANALYZE_TIMEOUT, connect=3.0)) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()
    except (httpx.HTTPError, ValueError, asyncio.TimeoutError) as exc:
        result.warnings.append(
            f"C# analyzer unreachable at {csharp_analyzer_url()} ({type(exc).__name__}). "
            f"{len(payload_files)} .cs file(s) were skipped — start services/analyzer-csharp and rescan."
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


def _read_sources(root: Path, files: list[str], warnings: list[str]) -> list[dict[str, str]]:
    payload: list[dict[str, str]] = []

    for rel_path in files:
        target = root / rel_path
        try:
            size = target.stat().st_size
        except OSError as exc:
            warnings.append(f"Could not read {rel_path}: {exc}")
            continue

        if size > MAX_ANALYZER_FILE_BYTES:
            warnings.append(
                f"Skipped oversized C# file ({MAX_ANALYZER_FILE_BYTES // 1_000_000} MB limit): {rel_path}."
            )
            continue

        try:
            content = target.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            warnings.append(f"Could not read {rel_path}: {exc}")
            continue

        payload.append({"path": rel_path.replace("\\", "/"), "content": content})

    if files and not payload:
        warnings.append(
            f"C# analyzer: none of the {len(files)} discovered .cs file(s) could be read; nothing was analyzed."
        )

    return payload
