"""Token-efficient Core IR context packing for the AI Copilot.

The LLM never receives source trees: it receives a compact, deterministic projection of the
``WorkspaceIR`` (stacks, health, signatures, relations, audit findings) that fits a hard character
budget. Nothing here reads or writes the filesystem.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from app.llm.config import max_context_chars
from app.models.ir import AuditFinding, ComponentNode, WorkspaceIR

MAX_FIELDS_PER_NODE = 60
MAX_METHODS_PER_NODE = 60
MAX_FINDINGS = 40
MAX_TEXT_CHARS = 240


@dataclass(frozen=True)
class PackedContext:
    document: dict[str, Any]
    text: str
    truncated: bool
    warnings: list[str]


def _serialize(document: dict[str, Any]) -> str:
    return json.dumps(document, separators=(",", ":"), ensure_ascii=False)


def _size(value: Any) -> int:
    return len(json.dumps(value, separators=(",", ":"), ensure_ascii=False)) + 1


def _clip(text: str, limit: int = MAX_TEXT_CHARS) -> str:
    return text if len(text) <= limit else f"{text[: limit - 1]}…"


def _compact_node(node: ComponentNode) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "id": node.id,
        "name": node.name,
        "stack": str(node.stack),
        "layer": str(node.layer),
        "kind": str(node.kind),
        "filePath": node.file_path,
    }
    if node.annotations:
        entry["annotations"] = list(node.annotations)

    if node.fields:
        signatures = []
        for field in node.fields[:MAX_FIELDS_PER_NODE]:
            signature = f"{field.name}:{field.type}"
            if field.annotations:
                signature = f"{signature} {' '.join(field.annotations)}"
            signatures.append(signature)
        if len(node.fields) > MAX_FIELDS_PER_NODE:
            signatures.append(f"+{len(node.fields) - MAX_FIELDS_PER_NODE} more fields")
        entry["fields"] = signatures

    if node.methods:
        signatures = []
        for method in node.methods[:MAX_METHODS_PER_NODE]:
            signature = f"{method.name}({', '.join(method.parameters)})"
            if method.return_type:
                signature = f"{signature}:{method.return_type}"
            signatures.append(signature)
        if len(node.methods) > MAX_METHODS_PER_NODE:
            signatures.append(f"+{len(node.methods) - MAX_METHODS_PER_NODE} more methods")
        entry["methods"] = signatures

    return entry


def _compact_finding(finding: AuditFinding) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "id": finding.id,
        "ruleId": str(finding.rule_id),
        "severity": str(finding.severity),
        "title": _clip(finding.title, 160),
        "message": _clip(finding.message),
        "suggestion": _clip(finding.suggestion),
        "nodeIds": list(finding.node_ids),
    }
    if finding.file_path:
        entry["filePath"] = finding.file_path
    return entry


def _relation_key(source_id: str, target_id: str, relation_type: str) -> str:
    return f"{source_id}->{target_id}:{relation_type}"


def _header(ir: WorkspaceIR) -> dict[str, Any]:
    audit = ir.audit
    return {
        "workspace": ir.name,
        "stacks": [str(stack) for stack in ir.detected_stacks],
        "health": {
            "score": audit.score,
            "errors": audit.summary.errors,
            "warnings": audit.summary.warnings,
            "info": audit.summary.info,
        },
        "counts": {
            "nodes": len(ir.nodes),
            "relations": len(ir.relations),
            "findings": len(audit.findings),
        },
    }


def pack_workspace(
    ir: WorkspaceIR,
    *,
    budget: int | None = None,
    include_findings: bool = True,
    max_findings: int = MAX_FINDINGS,
) -> PackedContext:
    """Compact the whole IR, truncating deterministically (findings first, then nodes, then edges)."""
    limit = budget or max_context_chars()
    truncated = False
    document = _header(ir)
    used = _size(document)

    if include_findings and ir.audit.findings:
        findings: list[dict[str, Any]] = []
        for finding in ir.audit.findings[:max_findings]:
            entry = _compact_finding(finding)
            size = _size(entry)
            if used + size > limit:
                truncated = True
                break
            findings.append(entry)
            used += size
        document["findings"] = findings
        if len(findings) < len(ir.audit.findings):
            truncated = True

    nodes: list[dict[str, Any]] = []
    included: list[str] = []
    for node in ir.nodes:
        entry = _compact_node(node)
        size = _size(entry)
        if used + size > limit:
            truncated = True
            break
        nodes.append(entry)
        included.append(node.id)
        used += size
    document["nodes"] = nodes
    if len(nodes) < len(ir.nodes):
        truncated = True

    allowed = set(included)
    relations: list[str] = []
    for relation in ir.relations:
        if relation.source_id not in allowed or relation.target_id not in allowed:
            continue
        key = _relation_key(relation.source_id, relation.target_id, str(relation.type))
        size = len(key) + 4
        if used + size > limit:
            truncated = True
            break
        relations.append(key)
        used += size
    document["relations"] = relations

    warnings: list[str] = []
    truncated = _shrink(document, limit, truncated)
    if truncated:
        warnings.append(
            f"IR context was truncated to fit the {limit} character budget; "
            "only part of the workspace was sent to the model."
        )

    return PackedContext(document=document, text=_serialize(document), truncated=truncated, warnings=warnings)


def pack_node_focus(
    ir: WorkspaceIR,
    node_id: str,
    *,
    hop: int = 1,
    budget: int | None = None,
) -> PackedContext:
    """Pack one component plus its direct neighbours — used by targeted method implementation."""
    limit = budget or max_context_chars()
    truncated = False
    document = _header(ir)
    document["focusNodeId"] = node_id
    used = _size(document)

    by_id = {node.id: node for node in ir.nodes}
    focus = by_id.get(node_id)
    if focus is None:
        raise KeyError(node_id)

    focus_entry = _compact_node(focus)
    used += _size(focus_entry)

    neighbour_ids: list[str] = []
    if hop > 0:
        for relation in ir.relations:
            if relation.source_id == node_id and relation.target_id not in neighbour_ids:
                neighbour_ids.append(relation.target_id)
            elif relation.target_id == node_id and relation.source_id not in neighbour_ids:
                neighbour_ids.append(relation.source_id)

    relations: list[str] = []
    for relation in ir.relations:
        if relation.source_id == node_id or relation.target_id == node_id:
            relations.append(_relation_key(relation.source_id, relation.target_id, str(relation.type)))

    neighbours: list[dict[str, Any]] = []
    for neighbour_id in neighbour_ids:
        neighbour = by_id.get(neighbour_id)
        if neighbour is None:
            continue
        entry = _compact_node(neighbour)
        size = _size(entry)
        if used + size > limit:
            truncated = True
            break
        neighbours.append(entry)
        used += size

    document["focus"] = focus_entry
    document["neighbors"] = neighbours
    document["relations"] = relations

    warnings: list[str] = []
    truncated = _shrink(document, limit, truncated)
    if truncated:
        warnings.append(
            f"IR context for {node_id} was truncated to fit the {limit} character budget."
        )

    return PackedContext(document=document, text=_serialize(document), truncated=truncated, warnings=warnings)


def _shrink(document: dict[str, Any], limit: int, truncated: bool) -> bool:
    """Final hard guarantee: the serialized document never exceeds the budget."""
    for key in ("neighbors", "relations", "nodes", "findings"):
        entries = document.get(key)
        while isinstance(entries, list) and entries and len(_serialize(document)) > limit:
            entries.pop()
            truncated = True
    return truncated


__all__ = ["PackedContext", "pack_node_focus", "pack_workspace"]
