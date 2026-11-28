"""The seven read-only MCP tools plus their registry.

Every tool reuses the very same services as the HTTP API â€” the workspace builder, the deterministic
audit engine, the Phase 10 System 1 decision layer, the Phase 3b patchers and the Phase 9 ephemeral
builder â€” so the MCP surface can never drift from the UI. Nothing here writes to a workspace: the
only mutations are tenant-scoped ADR rows (System 1 advice) and an audit-log entry for a build.

Payloads are deliberately compact (bounded lists, short messages, no raw source dumps) so a coding
agent can hold the whole answer in context.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from pydantic.alias_generators import to_camel

from app.builders.models import BuildError, BuildPatchInput, BuildResult
from app.builders.runner import detect_build_stack, run_ephemeral_build
from app.config import BUILDER_STACKS, MAX_PATCH_BYTES
from app.db import repository
from app.db.repository import UserRecord
from app.decision.service import route_task, screen_diff, triage_audit
from app.mcp.protocol import ToolError
from app.models.ir import AuditFinding, AuditRuleId, ComponentNode, WorkspaceIR
from app.patching.models import PatchOperation
from app.patching.paths import PatchRejected, resolve_member
from app.services.audit_log import AUDIT_ACTION_VERIFY_BUILD, record_event
from app.services.dry_run import compute_dry_run
from app.services.mermaid import generate_class_diagram
from app.services.paths import enforce_workspace_access
from app.services.workspace import WorkspaceNotFoundError, build_workspace

MAX_COMPONENTS = 400
MAX_FINDINGS = 200
MAX_WARNINGS = 12
MAX_DIAGNOSTICS = 50
MAX_OUTPUT_CHARS = 8_000
MAX_MESSAGE_CHARS = 600
MAX_SUGGESTIONS = 10
MAX_CANDIDATES = 10

SAAS_FORBIDDEN_CODE = "SAAS_PATH_FORBIDDEN"
WORKSPACE_UNAVAILABLE_CODE = "WORKSPACE_UNAVAILABLE"
PATCH_REJECTED_CODE = "PATCH_REJECTED"
UNKNOWN_STACK_CODE = "UNKNOWN_STACK"


class McpArgs(BaseModel):
    """Strict camelCase argument contract shared by every tool."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


class ScanArgs(McpArgs):
    root_path: str = Field(..., min_length=1, description="Absolute path of the workspace to inspect.")
    include_mermaid: bool = Field(
        default=False, description="Include a Mermaid classDiagram for the workspace."
    )
    group_by_layer: bool = Field(
        default=True, description="Group the diagram into layer namespaces (Phase 14 layout)."
    )
    direction: Literal["TB", "LR"] = Field(default="TB", description="Diagram layout direction.")
    member_detail: Literal["compact", "names_only", "full"] = Field(
        default="compact", description="How much class detail the diagram renders."
    )


class AuditArgs(McpArgs):
    root_path: str = Field(..., min_length=1, description="Absolute path of the workspace to audit.")
    include_laya_triage: bool = Field(
        default=False,
        description="Annotate findings with advisory System 1 (Laya) triage. Never blocks the audit.",
    )


class ComponentArgs(McpArgs):
    root_path: str = Field(..., min_length=1, description="Absolute path of the workspace to inspect.")
    component_query: str = Field(
        ...,
        min_length=1,
        max_length=300,
        description="Exact component id, exact name, or a case-insensitive substring of either.",
    )


class RouteTaskArgs(McpArgs):
    root_path: str = Field(..., min_length=1, description="Absolute path of the workspace.")
    intent: str = Field(..., min_length=3, max_length=4_000, description="The engineering request.")
    target_node_id: str | None = Field(
        default=None, max_length=300, description="Optional Core IR component id the task targets."
    )


class ScreenPatchInput(McpArgs):
    file_path: str = Field(..., min_length=1, max_length=1_024, description="Path relative to the root.")
    proposed_content: str = Field(..., max_length=400_000, description="Proposed file text.")
    is_new_file: bool = Field(default=False, description="True when the change creates a new file.")


class ScreenDiffArgs(McpArgs):
    root_path: str = Field(..., min_length=1, description="Absolute path of the workspace.")
    patches: list[ScreenPatchInput] = Field(
        ..., min_length=1, max_length=50, description="Proposed patches to pre-screen (advisory)."
    )


class DryRunArgs(McpArgs):
    root_path: str = Field(..., min_length=1, description="Absolute path of the workspace.")
    operations: list[dict[str, Any]] = Field(
        ...,
        min_length=1,
        max_length=500,
        description="AST patch operations, same contract as POST /api/v1/dry-run.",
    )


class VerifyBuildArgs(McpArgs):
    root_path: str = Field(..., min_length=1, description="Absolute path of the workspace.")
    stack: Literal["java", "csharp", "nodejs", "python"] | None = Field(
        default=None, description="Build stack; detected from project markers when omitted."
    )
    patches: list[BuildPatchInput] | None = Field(
        default=None, max_length=200, description="In-memory patches overlaid on the staged snapshot."
    )
    run_tests: bool = Field(default=False, description="Run the stack's test command after compiling.")


@dataclass(frozen=True)
class ToolContext:
    """The authenticated caller. Every workspace root is checked against this tenant."""

    user: UserRecord


ToolHandler = Callable[[ToolContext, Any], Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    title: str
    description: str
    input_model: type[McpArgs]
    handler: ToolHandler


def tool_annotations() -> dict[str, Any]:
    """The zero-write contract every Kodo tool advertises to the client."""
    return {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    }


def _clip(text: str | None, limit: int) -> str:
    if not text:
        return ""
    collapsed = " ".join(str(text).split())
    return collapsed if len(collapsed) <= limit else collapsed[: limit - 1] + "â€¦"


def _warnings(workspace: WorkspaceIR) -> list[str]:
    return [_clip(warning, 300) for warning in workspace.warnings[:MAX_WARNINGS]]


def _component_brief(node: ComponentNode) -> dict[str, Any]:
    return {
        "id": node.id,
        "name": node.name,
        "layer": str(node.layer),
        "kind": str(node.kind),
        "stack": str(node.stack),
        "filePath": node.file_path,
    }


def _finding_brief(finding: AuditFinding) -> dict[str, Any]:
    return {
        "id": finding.id,
        "ruleId": str(finding.rule_id),
        "severity": str(finding.severity),
        "title": _clip(finding.title, 200),
        "message": _clip(finding.message, MAX_MESSAGE_CHARS),
        "suggestion": _clip(finding.suggestion, 400),
        "nodeIds": list(finding.node_ids),
        "filePath": finding.file_path,
    }


def _workspace_root(ctx: ToolContext, raw_root: str) -> Path:
    """Apply the Phase 8 containment gate, mapping rejections onto agent-readable tool errors."""
    try:
        return enforce_workspace_access(raw_root, ctx.user)
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        code = str(detail.get("code") or PATCH_REJECTED_CODE)
        message = str(detail.get("message") or raw_root)
        raise ToolError(code, message, details={"rootPath": raw_root}) from exc


async def _load_workspace(ctx: ToolContext, raw_root: str) -> tuple[Path, WorkspaceIR]:
    root = _workspace_root(ctx, raw_root)
    try:
        workspace = await build_workspace(str(root))
    except WorkspaceNotFoundError as exc:
        raise ToolError(WORKSPACE_UNAVAILABLE_CODE, str(exc), details={"rootPath": str(root)}) from exc
    _remember_scan(ctx, workspace)
    return root, workspace


def _remember_scan(ctx: ToolContext, workspace: WorkspaceIR) -> None:
    """Record read activity so the SaaS TTL sweep keeps workspaces an agent is actively using."""
    try:
        repository.record_workspace_scan(
            ctx.user.id,
            name=workspace.name,
            local_path=workspace.root_path,
            health_score=workspace.audit.score,
        )
        repository.touch_workspace(ctx.user.id, workspace.root_path)
    except Exception:
        # Workspace bookkeeping is a convenience; it must never fail a read-only tool call.
        return


# ------------------------------------------------------------------------------- tools


async def scan_workspace(ctx: ToolContext, args: ScanArgs) -> dict[str, Any]:
    _, workspace = await _load_workspace(ctx, args.root_path)

    layer_counts = Counter(str(node.layer) for node in workspace.nodes)
    stack_counts = Counter(str(node.stack) for node in workspace.nodes)
    components = [_component_brief(node) for node in workspace.nodes]
    truncated = len(components) > MAX_COMPONENTS

    result: dict[str, Any] = {
        "name": workspace.name,
        "rootPath": workspace.root_path,
        "stacks": [str(stack) for stack in workspace.detected_stacks],
        "healthScore": workspace.audit.score,
        "auditSummary": {
            "errors": workspace.audit.summary.errors,
            "warnings": workspace.audit.summary.warnings,
            "info": workspace.audit.summary.info,
        },
        "layerCounts": dict(sorted(layer_counts.items())),
        "stackCounts": dict(sorted(stack_counts.items())),
        "componentCount": len(workspace.nodes),
        "relationCount": len(workspace.relations),
        "components": components[:MAX_COMPONENTS],
        "componentsTruncated": truncated,
        "warnings": _warnings(workspace),
    }
    if args.include_mermaid:
        result["mermaidClassDiagram"] = generate_class_diagram(
            workspace.nodes,
            workspace.relations,
            group_by_layer=args.group_by_layer,
            direction=args.direction,
            member_detail=args.member_detail,
        )
    return result


async def audit_workspace(ctx: ToolContext, args: AuditArgs) -> dict[str, Any]:
    root, workspace = await _load_workspace(ctx, args.root_path)
    findings = workspace.audit.findings

    result: dict[str, Any] = {
        "score": workspace.audit.score,
        "summary": {
            "errors": workspace.audit.summary.errors,
            "warnings": workspace.audit.summary.warnings,
            "info": workspace.audit.summary.info,
        },
        "findingCount": len(findings),
        "findings": [_finding_brief(finding) for finding in findings[:MAX_FINDINGS]],
        "findingsTruncated": len(findings) > MAX_FINDINGS,
        "warnings": _warnings(workspace),
    }

    if args.include_laya_triage:
        triage = await triage_audit(
            user_id=ctx.user.id,
            root_path=str(root),
            workspace_ir=workspace,
        )
        result["layaAvailable"] = triage.available
        result["layaTriage"] = {
            "model": triage.model,
            "latencyMs": triage.latency_ms,
            "items": [
                {
                    "adrId": item.adr_id,
                    "findingId": item.finding_id,
                    "riskLevel": item.risk_level,
                    "recommendedRoute": item.recommended_route,
                    "confidence": item.confidence,
                    "escalatedToSystem2": item.escalated_to_system2,
                    "priority": item.priority,
                }
                for item in triage.items
            ],
        }
        if triage.warning:
            result["layaWarning"] = _clip(triage.warning, 400)
    return result


def _matches(node: ComponentNode, query: str) -> str | None:
    """Return the match kind for one component, preferring the most precise match."""
    if node.id == query:
        return "exact_id"
    if node.name == query:
        return "exact_name"
    lowered = query.lower()
    if node.name.lower() == lowered:
        return "exact_name"
    if lowered in node.name.lower() or lowered in node.id.lower():
        return "substring"
    return None


async def get_component(ctx: ToolContext, args: ComponentArgs) -> dict[str, Any]:
    _, workspace = await _load_workspace(ctx, args.root_path)
    query = args.component_query.strip()

    ranked: list[tuple[int, ComponentNode, str]] = []
    for node in workspace.nodes:
        kind = _matches(node, query)
        if kind is not None:
            rank = {"exact_id": 0, "exact_name": 1, "substring": 2}[kind]
            ranked.append((rank, node, kind))
    ranked.sort(key=lambda item: (item[0], item[1].name.lower(), item[1].id))

    if not ranked:
        return {
            "found": False,
            "query": query,
            "suggestions": [node.name for node in workspace.nodes[:MAX_SUGGESTIONS]],
            "componentCount": len(workspace.nodes),
            "warnings": _warnings(workspace),
        }

    _, node, match_kind = ranked[0]
    nodes_by_id = {candidate.id: candidate for candidate in workspace.nodes}
    nodes_by_id.setdefault(node.id, node)

    incoming = [
        {
            "type": str(relation.type),
            "source": _component_brief(nodes_by_id[relation.source_id]),
        }
        for relation in workspace.relations
        if relation.target_id == node.id and relation.source_id in nodes_by_id
    ]
    outgoing = [
        {
            "type": str(relation.type),
            "target": _component_brief(nodes_by_id[relation.target_id]),
        }
        for relation in workspace.relations
        if relation.source_id == node.id and relation.target_id in nodes_by_id
    ]

    return {
        "found": True,
        "match": match_kind,
        "ambiguous": len(ranked) > 1,
        "candidates": [candidate[1].name for candidate in ranked[1:MAX_CANDIDATES]],
        "component": node.model_dump(by_alias=True),
        "neighborhood": {"incoming": incoming, "outgoing": outgoing},
        "auditFindings": [
            _finding_brief(finding)
            for finding in workspace.audit.findings
            if node.id in finding.node_ids
        ][:MAX_FINDINGS],
        "warnings": _warnings(workspace),
    }


async def route_task_tool(ctx: ToolContext, args: RouteTaskArgs) -> dict[str, Any]:
    root, workspace = await _load_workspace(ctx, args.root_path)
    decision = await route_task(
        user_id=ctx.user.id,
        root_path=str(root),
        intent=args.intent,
        workspace_ir=workspace,
        target_node_id=args.target_node_id,
    )
    return {
        "available": decision.available,
        "adrId": decision.adr_id,
        "recommendedRoute": decision.recommended_route,
        "blastRadius": decision.blast_radius,
        "confidence": decision.confidence,
        "escalateToSystem2": decision.escalate_to_system2,
        "rationale": _clip(decision.rationale, 1_200),
        "warning": _clip(decision.warning, 400) or None,
    }


def _existing_content(root: Path, rel_path: str, is_new_file: bool) -> str:
    """Read the current file text (bounded, read-only) so the safety screen can diff it."""
    if is_new_file:
        return ""
    try:
        target = resolve_member(root, rel_path)
        if target.stat().st_size > MAX_PATCH_BYTES:
            return ""
        return target.read_bytes().decode("utf-8", errors="replace")
    except (PatchRejected, OSError):
        return ""


async def screen_diff_tool(ctx: ToolContext, args: ScreenDiffArgs) -> dict[str, Any]:
    root, workspace = await _load_workspace(ctx, args.root_path)
    patches = [
        {
            "file_path": patch.file_path,
            "original_content": _existing_content(root, patch.file_path, patch.is_new_file),
            "proposed_content": patch.proposed_content,
            "is_new_file": patch.is_new_file,
        }
        for patch in args.patches
    ]
    decision = await screen_diff(
        user_id=ctx.user.id,
        root_path=str(root),
        patches=patches,
        workspace_ir=workspace,
    )
    return {
        "available": decision.available,
        "adrId": decision.adr_id,
        "status": decision.status,
        "confidence": decision.confidence,
        "flags": decision.flags,
        "advisoryNote": decision.advisory_note,
        "warning": _clip(decision.warning, 400) or None,
    }


async def dry_run_patch(ctx: ToolContext, args: DryRunArgs) -> dict[str, Any]:
    root = _workspace_root(ctx, args.root_path)
    try:
        operations = [PatchOperation.model_validate(operation) for operation in args.operations]
    except ValidationError as exc:
        raise ToolError(
            "INVALID_OPERATIONS",
            f"Operation contract rejected: {exc.error_count()} invalid field(s).",
            details={"errors": [
                {"path": ".".join(str(part) for part in error["loc"]), "message": error["msg"]}
                for error in exc.errors()[:10]
            ]},
        ) from exc

    try:
        response = await compute_dry_run(root, operations)
    except PatchRejected as exc:
        raise ToolError(PATCH_REJECTED_CODE, str(exc)) from exc

    return {
        "patches": [
            {
                "filePath": patch.file_path,
                "language": patch.language,
                "summary": patch.summary,
                "originalSha256": patch.original_sha256,
                "proposedContent": patch.proposed_content,
                "warnings": patch.warnings,
                "isNewFile": patch.is_new_file,
                "conflict": patch.conflict,
            }
            for patch in response.patches
        ],
        "warnings": response.warnings,
        "applied": False,
    }


def _bounded_output(output: str) -> str:
    if len(output) <= MAX_OUTPUT_CHARS:
        return output
    head = output[: MAX_OUTPUT_CHARS // 4]
    tail = output[-(MAX_OUTPUT_CHARS - len(head) - 40):]
    return f"{head}\nâ€¦[output truncated]â€¦\n{tail}"


def _build_payload(result: BuildResult) -> dict[str, Any]:
    diagnostics = [
        {
            "filePath": item.file_path,
            "line": item.line,
            "column": item.column,
            "severity": item.severity,
            "code": item.code,
            "message": _clip(item.message, 300),
        }
        for item in result.diagnostics[:MAX_DIAGNOSTICS]
    ]
    return {
        "status": result.status,
        "stack": result.stack,
        "exitCode": result.exit_code,
        "durationMs": result.duration_ms,
        "networkMode": result.network_mode,
        "diagnostics": diagnostics,
        "diagnosticsTruncated": len(result.diagnostics) > MAX_DIAGNOSTICS,
        "output": _bounded_output(result.output),
        "warnings": [_clip(warning, 400) for warning in result.warnings[:MAX_WARNINGS]],
    }


async def verify_build(ctx: ToolContext, args: VerifyBuildArgs) -> dict[str, Any]:
    root = _workspace_root(ctx, args.root_path)
    patches = list(args.patches or [])

    stack = args.stack or detect_build_stack(root, patches)
    if stack is None or stack not in BUILDER_STACKS:
        raise ToolError(
            UNKNOWN_STACK_CODE,
            "Kodo could not detect a build stack (pom.xml, *.csproj/*.sln, package.json/tsconfig.json "
            "or pyproject.toml/requirements.txt). Pass `stack` explicitly or add a project file.",
            details={"rootPath": str(root)},
        )

    try:
        result = run_ephemeral_build(root, stack, patches, run_tests=args.run_tests)
    except BuildError as exc:
        raise ToolError(exc.code, exc.message) from exc

    _record_build(ctx, root, result, len(patches))
    return _build_payload(result)


def _record_build(ctx: ToolContext, root: Path, result: BuildResult, patch_count: int) -> None:
    error_count = sum(1 for item in result.diagnostics if item.severity == "error")
    summary = (
        f"{result.stack} sandbox build {result.status} via MCP "
        f"({error_count} error(s), exit {result.exit_code}, network={result.network_mode})"
    )
    try:
        record_event(
            AUDIT_ACTION_VERIFY_BUILD,
            str(root),
            f"{summary} Â· {patch_count} proposed file(s) staged",
            files_count=patch_count,
            status=result.status,
            user_id=ctx.user.id,
        )
    except Exception:
        # Audit logging is best-effort and must never fail a verification result.
        return


TOOL_SPECS: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="kodo_scan_workspace",
        title="Scan workspace architecture",
        description=(
            "Read-only. Analyzes a workspace into Kodo's Core IR and returns stacks, the architecture "
            "health score, audit counts, layer counts and a compact component list. Set "
            "includeMermaid=true for a layer-grouped Mermaid classDiagram. Nothing is written."
        ),
        input_model=ScanArgs,
        handler=scan_workspace,
    ),
    ToolSpec(
        name="kodo_audit_workspace",
        title="Audit workspace architecture",
        description=(
            "Read-only. Runs the deterministic audit engine (layer violations, cycles, god classes, "
            "orphan components, exposed entities, missing validation) and returns the score, summary "
            "and findings. includeLayaTriage=true adds advisory System 1 triage, degrading to "
            "layaAvailable=false when local Laya is offline."
        ),
        input_model=AuditArgs,
        handler=audit_workspace,
    ),
    ToolSpec(
        name="kodo_get_component",
        title="Inspect one component",
        description=(
            "Read-only. Matches a component by exact id, exact name or case-insensitive substring and "
            "returns its fields, methods, annotations, file path, its 1-hop incoming/outgoing "
            "neighbourhood and any audit findings that reference it."
        ),
        input_model=ComponentArgs,
        handler=get_component,
    ),
    ToolSpec(
        name="kodo_route_task",
        title="Route an engineering task",
        description=(
            "Advisory. Asks the local System 1 (Laya) router whether a request belongs to "
            "deterministic AST/builder tools, System 2 DeepSeek reasoning or human review. Persists a "
            "tenant-scoped ADR and returns blastRadius, confidence and escalateToSystem2. Never applies "
            "anything."
        ),
        input_model=RouteTaskArgs,
        handler=route_task_tool,
    ),
    ToolSpec(
        name="kodo_screen_diff",
        title="Pre-screen a proposed diff",
        description=(
            "Advisory, read-only. Screens proposed file contents for logic-loss, layer-boundary and "
            "removed-signature risk and returns pass / caution / high_risk with flags. The "
            "deterministic dry-run, diff review and sandbox build remain authoritative."
        ),
        input_model=ScreenDiffArgs,
        handler=screen_diff_tool,
    ),
    ToolSpec(
        name="kodo_dry_run_patch",
        title="Preview AST patches",
        description=(
            "Read-only, zero-write. Computes proposed file contents in memory for java/ts/js/python/csharp "
            "AST operations (same contract as POST /api/v1/dry-run) and returns the proposed text plus "
            "the originalSha256 needed by the guarded apply. No file is created, modified or deleted and "
            "no apply token is issued here."
        ),
        input_model=DryRunArgs,
        handler=dry_run_patch,
    ),
    ToolSpec(
        name="kodo_verify_build",
        title="Sandbox build verification",
        description=(
            "Sandbox-only. Compiles (and optionally tests) a staged in-memory snapshot of the workspace "
            "in a disposable, network-isolated builder container and returns status, exit code, parsed "
            "diagnostics and a bounded log tail. The workspace is never mounted or written. Requires "
            "KODO_BUILDERS_ENABLED and local builder images."
        ),
        input_model=VerifyBuildArgs,
        handler=verify_build,
    ),
)

TOOLS_BY_NAME: dict[str, ToolSpec] = {spec.name: spec for spec in TOOL_SPECS}


def list_tool_definitions() -> list[dict[str, Any]]:
    """MCP ``tools/list`` payload: name, description, JSON Schema and the zero-write annotations."""
    return [
        {
            "name": spec.name,
            "title": spec.title,
            "description": spec.description,
            "inputSchema": spec.input_model.model_json_schema(by_alias=True),
            "annotations": tool_annotations(),
        }
        for spec in TOOL_SPECS
    ]


_RULE_SEVERITY = {
    "LAYER_VIOLATION": "error",
    "CIRCULAR_DEPENDENCY": "error",
    "ENTITY_EXPOSED_IN_CONTROLLER": "error",
    "GOD_CLASS": "warning",
    "ORPHAN_COMPONENT": "info",
    "MISSING_VALIDATION": "warning",
}


def audit_rule_catalog() -> list[dict[str, str]]:
    """The deterministic rule ids an agent can expect from :func:`audit_workspace`."""
    return [
        {"ruleId": str(rule.value), "severityHint": _RULE_SEVERITY.get(str(rule.value), "mixed")}
        for rule in AuditRuleId
    ]


__all__ = [
    "AuditArgs",
    "ComponentArgs",
    "DryRunArgs",
    "RouteTaskArgs",
    "ScanArgs",
    "ScreenDiffArgs",
    "ScreenPatchInput",
    "TOOLS_BY_NAME",
    "TOOL_SPECS",
    "ToolContext",
    "ToolSpec",
    "VerifyBuildArgs",
    "audit_rule_catalog",
    "audit_workspace",
    "dry_run_patch",
    "get_component",
    "list_tool_definitions",
    "route_task_tool",
    "scan_workspace",
    "screen_diff_tool",
    "tool_annotations",
    "verify_build",
]
