"""Deterministic, compact state builders for `/v1/systemone`.

Laya is sensitive to field order and has a tight per-question token budget, so every payload here is
built with an explicit insertion order (never `sort_keys=True`) and clamped to a hard byte ceiling.
Nothing is read from or written to disk: states are projections of the Core IR and in-memory patches.
"""

from __future__ import annotations

import copy
import difflib
import json
import re
from collections.abc import Iterable, Iterator, Sequence
from typing import Any

from app.models.ir import AuditFinding, WorkspaceIR

# Hard ceiling for the `state` object of one `/v1/systemone` request.
MAX_STATE_BYTES = 12 * 1024
_MIN_STRING_CHARS = 24
_MAX_PATCHES = 20
_MAX_HUNK_CHARS = 1_800
_MAX_REMOVED_SIGNATURES = 10
_MAX_FINDING_NODES = 3

_SIGNATURE_LINE = re.compile(
    r"^\s*(?:[\w@.]+\s+)*"
    r"(?:public|private|protected|internal|static|final|abstract|virtual|override|async|sealed|export|default|function)\b"
    r"[^=;]*?\([^;]*\)",
    re.IGNORECASE,
)
_IDENTIFIER_BEFORE_PAREN = re.compile(r"([A-Za-z_$][\w$]*)\s*\(")


class StateBudgetError(ValueError):
    """Raised when a state cannot be shrunk below :data:`MAX_STATE_BYTES`."""


def dumps_state(state: dict[str, Any]) -> str:
    """Serialize with the builder's key order preserved (deterministic wire bytes)."""
    return json.dumps(state, ensure_ascii=False, separators=(",", ":"), sort_keys=False)


def state_size(state: dict[str, Any]) -> int:
    return len(dumps_state(state).encode("utf-8"))


def _clip(text: str | None, limit: int) -> str:
    if not text:
        return ""
    collapsed = " ".join(str(text).split())
    return collapsed if len(collapsed) <= limit else collapsed[: limit - 1] + "…"


def _value(obj: Any, snake: str, camel: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        if snake in obj:
            return obj[snake]
        return obj.get(camel, default)
    return getattr(obj, snake, default)


def _workspace_summary(workspace_ir: WorkspaceIR) -> dict[str, Any]:
    audit = workspace_ir.audit
    return {
        "name": _clip(workspace_ir.name, 120),
        "stacks": sorted({str(stack) for stack in workspace_ir.detected_stacks}),
        "healthScore": int(audit.score),
        "findings": {
            "errors": int(audit.summary.errors),
            "warnings": int(audit.summary.warnings),
            "info": int(audit.summary.info),
        },
        "components": len(workspace_ir.nodes),
        "relations": len(workspace_ir.relations),
    }


def _node_summary(node: Any, incoming: int, outgoing: int) -> dict[str, Any]:
    return {
        "id": _clip(node.id, 180),
        "name": _clip(node.name, 120),
        "layer": str(node.layer),
        "kind": str(node.kind),
        "stack": str(node.stack),
        "fields": len(node.fields),
        "methods": len(node.methods),
        "incoming": incoming,
        "outgoing": outgoing,
    }


def _relation_counts(workspace_ir: WorkspaceIR) -> dict[str, tuple[int, int]]:
    counts: dict[str, list[int]] = {}
    for relation in workspace_ir.relations:
        incoming, outgoing = counts.get(relation.source_id, [0, 0])
        counts[relation.source_id] = [incoming, outgoing + 1]
        incoming, outgoing = counts.get(relation.target_id, [0, 0])
        counts[relation.target_id] = [incoming + 1, outgoing]
    return {node_id: (pair[0], pair[1]) for node_id, pair in counts.items()}


def _fits(state: dict[str, Any]) -> dict[str, Any]:
    """Return a byte-bounded deep copy of ``state`` without changing its key order."""
    current = copy.deepcopy(state)
    while state_size(current) > MAX_STATE_BYTES:
        if not _shrink_once(current):
            raise StateBudgetError(
                f"System 1 state cannot be reduced below {MAX_STATE_BYTES} bytes."
            )
    return current


def _walk_strings(node: Any) -> Iterator[tuple[Any, Any, str]]:
    if isinstance(node, dict):
        for key, value in list(node.items()):
            if isinstance(value, str):
                yield node, key, value
            else:
                yield from _walk_strings(value)
    elif isinstance(node, list):
        for index, value in enumerate(list(node)):
            if isinstance(value, str):
                yield node, index, value
            else:
                yield from _walk_strings(value)


def _walk_lists(node: Any) -> Iterator[list[Any]]:
    if isinstance(node, dict):
        for value in node.values():
            yield from _walk_lists(value)
    elif isinstance(node, list):
        yield node
        for value in node:
            yield from _walk_lists(value)


def _remove_key(node: Any, key: str) -> bool:
    if isinstance(node, dict):
        if key in node:
            del node[key]
            return True
        return any(_remove_key(value, key) for value in node.values())
    if isinstance(node, list):
        return any(_remove_key(value, key) for value in node)
    return False


def _shrink_once(state: dict[str, Any]) -> bool:
    longest: tuple[Any, Any, str] | None = None
    for container, key, value in _walk_strings(state):
        if len(value) <= _MIN_STRING_CHARS:
            continue
        if longest is None or len(value) > len(longest[2]):
            longest = (container, key, value)
    if longest is not None:
        container, key, value = longest
        container[key] = value[: max(_MIN_STRING_CHARS // 2, len(value) // 2)] + "…"
        return True

    # No long text left: drop list tails, largest first, then optional sections.
    candidates = [items for items in _walk_lists(state) if len(items) > 1]
    if candidates:
        target = max(candidates, key=len)
        target.pop()
        return True

    for optional_key in ("diffHunks", "removedSignatures", "files", "nodes", "target", "workspace"):
        if _remove_key(state, optional_key):
            return True
    return False


def pack_finding_state(finding: AuditFinding, workspace_ir: WorkspaceIR) -> dict[str, Any]:
    """Compact audit-triage state: finding, its nodes and the workspace health summary."""
    counts = _relation_counts(workspace_ir)
    nodes_by_id = {node.id: node for node in workspace_ir.nodes}
    finding_nodes = [
        _node_summary(
            nodes_by_id[node_id],
            counts.get(node_id, (0, 0))[0],
            counts.get(node_id, (0, 0))[1],
        )
        for node_id in finding.node_ids[:_MAX_FINDING_NODES]
        if node_id in nodes_by_id
    ]
    primary_stack = finding_nodes[0]["stack"] if finding_nodes else "unknown"

    state = {
        "kind": "audit_finding",
        "stack": primary_stack,
        "workspace": _workspace_summary(workspace_ir),
        "finding": {
            "ruleId": str(finding.rule_id),
            "severity": str(finding.severity),
            "title": _clip(finding.title, 160),
            "message": _clip(finding.message, 420),
            "suggestion": _clip(finding.suggestion, 240),
            "filePath": _clip(finding.file_path, 200),
        },
        "nodes": finding_nodes,
    }
    return _fits(state)


def pack_task_state(
    intent: str,
    workspace_ir: WorkspaceIR,
    target_node_id: str | None = None,
) -> dict[str, Any]:
    """Compact task-router state: user intent, workspace health and an optional target component."""
    counts = _relation_counts(workspace_ir)
    nodes_by_id = {node.id: node for node in workspace_ir.nodes}
    target = None
    if target_node_id and target_node_id in nodes_by_id:
        node = nodes_by_id[target_node_id]
        target = _node_summary(node, counts.get(node.id, (0, 0))[0], counts.get(node.id, (0, 0))[1])

    state: dict[str, Any] = {
        "kind": "task_request",
        "intent": _clip(intent, 800),
        "workspace": _workspace_summary(workspace_ir),
    }
    if target is not None:
        state["target"] = target
    return _fits(state)


def _line_counts(diff_lines: Iterable[str]) -> tuple[int, int]:
    added = removed = 0
    for line in diff_lines:
        if line.startswith("+") and not line.startswith("+++"):
            added += 1
        elif line.startswith("-") and not line.startswith("---"):
            removed += 1
    return added, removed


def _signature_names(lines: Iterable[str]) -> list[str]:
    names: list[str] = []
    for line in lines:
        if not _SIGNATURE_LINE.match(line):
            continue
        match = _IDENTIFIER_BEFORE_PAREN.search(line)
        if match and match.group(1) not in names:
            names.append(match.group(1))
    return names


def removed_signatures(diff_text: str) -> list[str]:
    """Declarations the diff deletes without re-adding them (deterministic heuristic)."""
    removed_lines: list[str] = []
    added_lines: list[str] = []
    for line in diff_text.splitlines():
        if line.startswith("-") and not line.startswith("---"):
            removed_lines.append(line[1:])
        elif line.startswith("+") and not line.startswith("+++"):
            added_lines.append(line[1:])

    added = set(_signature_names(added_lines))
    return [name for name in _signature_names(removed_lines) if name not in added][
        :_MAX_REMOVED_SIGNATURES
    ]


def _patch_text(patch: Any) -> tuple[str, str, str, bool]:
    path = str(_value(patch, "file_path", "filePath", "") or "")
    original = str(_value(patch, "original_content", "originalContent", "") or "")
    proposed = str(_value(patch, "proposed_content", "proposedContent", "") or "")
    is_new = bool(_value(patch, "is_new_file", "isNewFile", False))
    return path, original, proposed, is_new


def pack_diff_state(
    patches: Sequence[Any],
    workspace_ir: WorkspaceIR | None = None,
) -> dict[str, Any]:
    """Compact pre-diff safety state: per-file line counts and clamped unified hunks."""
    files: list[dict[str, Any]] = []
    hunks: list[str] = []
    signatures: list[str] = []
    total_added = total_removed = 0

    for patch in list(patches)[:_MAX_PATCHES]:
        path, original, proposed, is_new = _patch_text(patch)
        diff_lines = list(
            difflib.unified_diff(
                original.splitlines(),
                proposed.splitlines(),
                fromfile=f"a/{path}",
                tofile=f"b/{path}",
                n=2,
                lineterm="",
            )
        )
        added, removed = _line_counts(diff_lines)
        total_added += added
        total_removed += removed
        files.append(
            {
                "path": _clip(path, 200),
                "added": added,
                "removed": removed,
                "isNew": is_new,
            }
        )
        diff_text = "\n".join(diff_lines)
        for name in removed_signatures(diff_text):
            if name not in signatures and len(signatures) < _MAX_REMOVED_SIGNATURES:
                signatures.append(name)
        if diff_text:
            hunks.append(
                diff_text if len(diff_text) <= _MAX_HUNK_CHARS else diff_text[:_MAX_HUNK_CHARS] + "…"
            )

    state: dict[str, Any] = {
        "kind": "proposed_diff",
        "filesChanged": len(files),
        "totalAdded": total_added,
        "totalRemoved": total_removed,
        "methodsRemoved": bool(signatures),
        "removedSignatures": signatures,
        "files": files,
        "diffHunks": hunks,
    }
    if workspace_ir is not None:
        state["workspace"] = _workspace_summary(workspace_ir)
    return _fits(state)


__all__ = [
    "MAX_STATE_BYTES",
    "StateBudgetError",
    "dumps_state",
    "pack_diff_state",
    "pack_finding_state",
    "pack_task_state",
    "removed_signatures",
    "state_size",
]
