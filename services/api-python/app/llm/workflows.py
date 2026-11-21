"""The three constrained AI workflows of the DeepSeek Architecture Copilot.

Every workflow is read-only with respect to the user's source tree: it reads a bounded set of
files, packs compact Core IR context, asks the model for a proposal, and returns that proposal as
normal ``DryRunResponse`` patches. The only writer in Kodo remains the guarded apply service.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.llm.client import ChatMessage, LlmClient, parse_llm_json
from app.llm.context_packer import pack_node_focus, pack_workspace
from app.llm.errors import LlmError
from app.llm.prompts import (
    SYSTEM_AUDIT_FIX,
    SYSTEM_BLUEPRINT,
    SYSTEM_IMPLEMENT,
    audit_fix_prompt,
    implement_prompt,
    spec_prompt,
)
from app.llm.sources import MAX_PATCH_FILES, SourceFile, read_sources
from app.models.blueprint import BLUEPRINT_SCHEMA_VERSION, Blueprint, BlueprintStack
from app.models.ir import AuditFinding, WorkspaceIR
from app.patching.models import DryRunResponse, PatchResult, sha256_hex


@dataclass(frozen=True)
class SpecBlueprintResult:
    blueprint: Blueprint
    rationale: str
    model_used: str
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class AiPatchResult:
    response: DryRunResponse
    explanation: str
    model_used: str


async def spec_to_blueprint(
    *,
    spec: str,
    stack: BlueprintStack,
    project_name: str | None,
    base_package: str | None,
    client: LlmClient,
) -> SpecBlueprintResult:
    model = client.config.reasoning_model
    warnings: list[str] = []
    messages = [
        ChatMessage("system", SYSTEM_BLUEPRINT),
        ChatMessage("user", spec_prompt(spec, stack, project_name, base_package)),
    ]

    completion = await client.chat(messages, model=model, temperature=0.2)
    payload, rationale = _blueprint_payload(completion.content)
    payload = _apply_target(payload, stack, project_name, base_package, warnings)

    try:
        blueprint = Blueprint.model_validate(payload)
    except ValueError as exc:
        problems = _validation_details(exc)
        repair_messages = messages + [
            ChatMessage("assistant", completion.content),
            ChatMessage(
                "user",
                "That JSON is invalid for the Kodo blueprint schema:\n- "
                + "\n- ".join(problems)
                + "\n\nReturn the corrected JSON object only, using the exact contract keys.",
            ),
        ]
        repair = await client.chat(repair_messages, model=model, temperature=0.0)
        repaired_payload, repaired_rationale = _blueprint_payload(repair.content)
        repaired_payload = _apply_target(repaired_payload, stack, project_name, base_package, warnings)
        try:
            blueprint = Blueprint.model_validate(repaired_payload)
        except ValueError as second:
            raise LlmError(
                "INVALID_BLUEPRINT",
                "The model returned a blueprint that does not satisfy the Kodo schema, even after one "
                "automatic repair retry.",
                422,
                details=_validation_details(second),
            ) from second
        rationale = repaired_rationale or rationale
        warnings.append("The first blueprint failed validation and was repaired with one automatic retry.")

    if not blueprint.slices:
        warnings.append("The generated blueprint has no slices; add at least one before generating files.")

    return SpecBlueprintResult(
        blueprint=blueprint,
        rationale=rationale,
        model_used=model,
        warnings=warnings,
    )


async def audit_fix(
    *,
    root_path: str,
    finding: AuditFinding,
    workspace_ir: WorkspaceIR,
    client: LlmClient,
) -> AiPatchResult:
    candidates = _finding_files(finding, workspace_ir)
    if not candidates:
        raise LlmError(
            "NO_SOURCE_FILE",
            "This audit finding has no source file attached, so Kodo cannot build an AI patch for it.",
            422,
        )

    read_warnings: list[str] = []
    sources = read_sources(root_path, candidates, skipped=read_warnings)
    if not sources:
        raise LlmError(
            "NO_SOURCE_FILE",
            "None of the files attached to this audit finding could be read.",
            422,
            details=read_warnings,
        )

    packed = pack_workspace(workspace_ir)
    model = client.config.code_model
    completion = await client.chat(
        [
            ChatMessage("system", SYSTEM_AUDIT_FIX),
            ChatMessage("user", audit_fix_prompt(finding, packed.text, sources)),
        ],
        model=model,
        temperature=0.1,
    )

    data = parse_llm_json(completion.content)
    explanation, edits = _edits_payload(data)
    patches, warnings = _build_patches(sources, edits)
    warnings = [*read_warnings, *packed.warnings, *warnings]

    return AiPatchResult(
        response=DryRunResponse(patches=patches, warnings=warnings),
        explanation=explanation,
        model_used=model,
    )


async def implement_method(
    *,
    root_path: str,
    file_path: str,
    node_id: str,
    method_name: str,
    instruction: str,
    workspace_ir: WorkspaceIR,
    client: LlmClient,
) -> AiPatchResult:
    node = next((item for item in workspace_ir.nodes if item.id == node_id), None)
    if node is None:
        raise LlmError("UNKNOWN_NODE", f"Component '{node_id}' is not part of the scanned workspace.", 422)

    source = read_sources(root_path, [file_path], limit=1)
    if not source:
        raise LlmError("NO_SOURCE_FILE", f"Source file '{file_path}' could not be read.", 422)

    packed = pack_node_focus(workspace_ir, node_id)
    model = client.config.code_model
    completion = await client.chat(
        [
            ChatMessage("system", SYSTEM_IMPLEMENT),
            ChatMessage(
                "user",
                implement_prompt(node_id, node.name, method_name, instruction, packed.text, source[0]),
            ),
        ],
        model=model,
        temperature=0.2,
    )

    data = parse_llm_json(completion.content)
    if not isinstance(data, dict):
        raise LlmError("INVALID_PATCH", "The model did not return a patch object.", 422)

    explanation = str(data.get("explanation") or "")
    proposed = data.get("proposedContent")
    if not isinstance(proposed, str):
        nested = data.get("file")
        proposed = nested.get("proposedContent") if isinstance(nested, dict) else None
    if not isinstance(proposed, str):
        raise LlmError("INVALID_PATCH", "The model returned no proposedContent for the file.", 422)

    target = source[0]
    warnings = list(packed.warnings)
    if proposed == target.content:
        warnings.append(f"{target.file_path}: the model returned the file unchanged.")

    patch = PatchResult(
        file_path=target.file_path,
        language=target.language,
        original_content=target.content,
        original_sha256=sha256_hex(target.raw),
        proposed_content=proposed,
        summary=f"AI implemented {method_name}" if proposed != target.content else "No changes proposed",
        warnings=[],
    )

    return AiPatchResult(
        response=DryRunResponse(patches=[patch], warnings=warnings),
        explanation=explanation,
        model_used=model,
    )


def _blueprint_payload(content: str) -> tuple[dict[str, Any], str]:
    data = parse_llm_json(content)
    if isinstance(data, dict) and isinstance(data.get("blueprint"), dict):
        return dict(data["blueprint"]), str(data.get("rationale") or "")
    if isinstance(data, dict):
        return dict(data), ""
    raise LlmError(
        "INVALID_BLUEPRINT",
        "The model did not return a blueprint JSON object.",
        422,
    )


def _apply_target(
    payload: dict[str, Any],
    stack: BlueprintStack,
    project_name: str | None,
    base_package: str | None,
    warnings: list[str],
) -> dict[str, Any]:
    payload = dict(payload)
    payload["schemaVersion"] = BLUEPRINT_SCHEMA_VERSION

    if str(payload.get("stack") or "") != str(stack):
        warnings.append(f"The target stack was pinned to {stack} instead of the model's suggestion.")
    payload["stack"] = str(stack)

    if project_name and str(payload.get("projectName") or "") != project_name:
        payload["projectName"] = project_name
    if base_package and str(payload.get("basePackageOrNamespace") or "") != base_package:
        payload["basePackageOrNamespace"] = base_package

    return payload


def _validation_details(exc: Exception) -> list[str]:
    errors = getattr(exc, "errors", None)
    if not callable(errors):
        return [str(exc)]
    details: list[str] = []
    for item in errors()[:12]:
        location = ".".join(str(part) for part in item.get("loc", ())) or "(root)"
        details.append(f"{location}: {item.get('msg', 'invalid value')}")
    return details or [str(exc)]


def _finding_files(finding: AuditFinding, workspace_ir: WorkspaceIR) -> list[str]:
    by_id = {node.id: node for node in workspace_ir.nodes}
    ordered: list[str] = []
    if finding.file_path:
        ordered.append(finding.file_path)
    for node_id in finding.node_ids:
        node = by_id.get(node_id)
        if node is not None:
            ordered.append(node.file_path)

    unique: list[str] = []
    for path in ordered:
        normalized = path.replace("\\", "/").strip()
        if normalized and normalized not in unique:
            unique.append(normalized)
    return unique[:MAX_PATCH_FILES]


def _edits_payload(data: Any) -> tuple[str, list[Any]]:
    if isinstance(data, list):
        return "", data
    if isinstance(data, dict):
        explanation = str(data.get("explanation") or "")
        for key in ("files", "patches", "edits"):
            value = data.get(key)
            if isinstance(value, list):
                return explanation, value
        if "filePath" in data and "proposedContent" in data:
            return explanation, [data]
    raise LlmError("INVALID_PATCH", "The model did not return a list of file edits.", 422)


def _build_patches(sources: list[SourceFile], edits: list[Any]) -> tuple[list[PatchResult], list[str]]:
    by_path = {source.file_path: source for source in sources}
    by_lower = {source.file_path.lower(): source for source in sources}
    patches: list[PatchResult] = []
    warnings: list[str] = []
    seen: set[str] = set()

    for edit in edits:
        if not isinstance(edit, dict):
            raise LlmError("INVALID_PATCH", "The model returned a malformed file edit.", 422)

        requested = str(edit.get("filePath") or "").replace("\\", "/").strip()
        while requested.startswith("./"):
            requested = requested[2:]
        proposed = edit.get("proposedContent")
        if not isinstance(proposed, str):
            raise LlmError("INVALID_PATCH", f"The edit for '{requested}' has no proposedContent string.", 422)

        source = by_path.get(requested) or by_lower.get(requested.lower())
        if source is None:
            # Never trust model-supplied paths: drop the edit instead of resolving it on disk.
            warnings.append(
                f"The model also proposed edits to '{requested or '(no path)'}', which Kodo did not send; "
                "those edits were dropped."
            )
            continue
        file_path = source.file_path
        if file_path in seen:
            continue
        seen.add(file_path)

        summary = edit.get("summary")
        if isinstance(summary, str):
            summary_text = summary
        elif isinstance(summary, list):
            summary_text = "; ".join(str(item) for item in summary if str(item).strip())
        else:
            summary_text = ""

        if proposed == source.content:
            warnings.append(f"{file_path}: the model returned no changes for this file.")

        patches.append(
            PatchResult(
                file_path=file_path,
                language=source.language,
                original_content=source.content,
                original_sha256=sha256_hex(source.raw),
                proposed_content=proposed,
                summary=summary_text or "AI proposed an edit",
                warnings=[],
            )
        )

    if not patches:
        raise LlmError(
            "INVALID_PATCH",
            "The model did not propose any change to the files Kodo provided, so no patch was produced.",
            422,
        )

    return patches, warnings


__all__ = [
    "AiPatchResult",
    "SpecBlueprintResult",
    "audit_fix",
    "implement_method",
    "spec_to_blueprint",
]
