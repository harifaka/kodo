"""Workspace orchestration: scan -> per-language analysis -> Core IR."""

from __future__ import annotations

import asyncio
from pathlib import Path

from app.analyzers.common import ReferenceCandidate
from app.analyzers.java import parse_java
from app.analyzers.scanner import ScanFiles, collect_files, detect_stacks
from app.analyzers.typescript import parse_script
from app.models.ir import ComponentNode, ComponentRelation, WorkspaceIR
from app.services.csharp_client import analyze_workspace
from app.services.mermaid import generate_class_diagram
from app.services.relations import drop_dangling_relations, merge_relations, resolve_relations


class WorkspaceNotFoundError(ValueError):
    """Raised when the requested scan root cannot be read."""


async def build_workspace(raw_path: str) -> WorkspaceIR:
    root = Path(raw_path).expanduser()
    try:
        root = root.resolve(strict=True)
    except OSError as exc:
        raise WorkspaceNotFoundError(f"Path does not exist or is not accessible: {raw_path}") from exc

    if not root.is_dir():
        raise WorkspaceNotFoundError(f"Path is not a directory: {root}")

    scan = collect_files(root)
    nodes, references, parse_warnings = await asyncio.to_thread(_parse_local_sources, root, scan)

    csharp_nodes: list[ComponentNode] = []
    csharp_relations: list[ComponentRelation] = []
    csharp_warnings: list[str] = []
    if scan.csharp:
        csharp = await analyze_workspace(root, scan.csharp)
        csharp_nodes = csharp.nodes
        csharp_relations = csharp.relations
        csharp_warnings = csharp.warnings

    nodes, duplicate_warnings = _dedupe_nodes([*nodes, *csharp_nodes])

    relations = merge_relations(
        [
            *resolve_relations(nodes, references),
            *csharp_relations,
        ]
    )
    relations = drop_dangling_relations(relations, nodes)

    warnings = [*scan.warnings, *parse_warnings, *csharp_warnings, *duplicate_warnings]
    if not nodes:
        warnings.append(
            "No supported components were discovered. "
            "Kodo currently analyzes .java, .ts, .tsx, .js, .jsx and .cs files."
        )

    return WorkspaceIR(
        name=root.name or str(root),
        root_path=str(root),
        detected_stacks=detect_stacks(scan),
        nodes=nodes,
        relations=relations,
        mermaid_class_diagram=generate_class_diagram(nodes, relations),
        warnings=warnings,
    )


def _parse_local_sources(
    root: Path,
    scan: ScanFiles,
) -> tuple[list[ComponentNode], list[ReferenceCandidate], list[str]]:
    nodes: list[ComponentNode] = []
    references: list[ReferenceCandidate] = []
    warnings: list[str] = []

    for rel_path in scan.java:
        source = _read_source(root, rel_path, warnings)
        if source is None:
            continue
        result = parse_java(rel_path, source)
        nodes.extend(result.nodes)
        references.extend(result.references)
        warnings.extend(result.warnings)

    known_scripts = set(scan.scripts)
    for rel_path in scan.scripts:
        source = _read_source(root, rel_path, warnings)
        if source is None:
            continue
        result = parse_script(rel_path, source, known_scripts)
        nodes.extend(result.nodes)
        references.extend(result.references)
        warnings.extend(result.warnings)

    return _dedupe_nodes(nodes)[0], references, warnings


def _read_source(root: Path, rel_path: str, warnings: list[str]) -> bytes | None:
    try:
        return (root / rel_path).read_bytes()
    except OSError as exc:
        warnings.append(f"Could not read {rel_path}: {exc}")
        return None


def _dedupe_nodes(nodes: list[ComponentNode]) -> tuple[list[ComponentNode], list[str]]:
    unique: dict[str, ComponentNode] = {}
    warnings: list[str] = []

    for node in nodes:
        if node.id in unique:
            warnings.append(f"Duplicate component id '{node.id}' ignored ({node.file_path}).")
            continue
        unique[node.id] = node

    ordered = sorted(unique.values(), key=lambda n: (str(n.stack), n.file_path, n.name, n.id))
    return ordered, warnings
