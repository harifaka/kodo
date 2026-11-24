"""System prompts and user-prompt builders for the AI Copilot workflows.

Prompts are deterministic text: compact IR projections only, never a directory tree or raw dump.
"""

from __future__ import annotations

import json

from app.llm.sources import SourceFile
from app.models.blueprint import BlueprintStack
from app.models.ir import AuditFinding

_STACK_GUIDANCE = {
    "spring-boot": (
        "Spring Boot 3 / Java 21. Canonical field types: string, text, email, int, long, decimal, "
        "boolean, date, datetime, uuid. Allowed annotations: @NotNull, @NotBlank, @Email, @Positive, "
        "@Size(max = 200), @Column(nullable = false), @Column(unique = true)."
    ),
    "csharp-wpf": (
        ".NET 8 WPF (MVVM). Canonical field types: string, text, email, int, long, decimal, double, "
        "boolean, date, datetime, uuid. Allowed annotations: [Required], [StringLength(200)], "
        "[Range(0, 999999)], [EmailAddress], [Key]."
    ),
    "nodejs": (
        "Node.js + TypeScript (Express). Canonical field types: string, text, email, int, long, "
        "number, decimal, boolean, date, datetime, uuid. Allowed annotations: @IsNotEmpty(), "
        "@IsString(), @IsNumber(), @IsEmail(), @Min(0), @Max(100), @Length(1, 200)."
    ),
}

_BLUEPRINT_CONTRACT = """Return exactly one JSON object:
{
  "blueprint": {
    "schemaVersion": "1.0",
    "projectName": "Human readable project name",
    "stack": "spring-boot" | "csharp-wpf" | "nodejs",
    "basePackageOrNamespace": "com.acme.billing",
    "slices": [
      {
        "name": "PascalCaseSlice",
        "fields": [
          {"name": "camelCaseField", "type": "string", "required": true, "annotations": ["@NotNull"]}
        ],
        "dependsOnSlices": ["AnotherSlice"],
        "includeTests": true
      }
    ]
  },
  "rationale": "Two to four sentences explaining the decomposition."
}
Blueprint rules:
- Slice names are unique PascalCase identifiers; field names are unique identifiers inside a slice.
- dependsOnSlices may only reference slices defined in the same blueprint, must be acyclic, and a
  slice may never depend on itself.
- Model real business domain changes as separate slices; never invent infrastructure slices.
- Keep fields lean (typically 2-6 per slice) and always type them with the canonical stack types."""

SYSTEM_BLUEPRINT = (
    "You are Kodo's architecture copilot. You turn a business spec written by a developer into a "
    "Kodo blueprint for vertical-slice code generation. Reply with JSON only, no prose, no markdown "
    "fences.\n\n"
    + _BLUEPRINT_CONTRACT
)

SYSTEM_AUDIT_FIX = """You are Kodo's architecture copilot. You fix exactly one deterministic audit finding.
Return JSON only:
{
  "explanation": "One short paragraph: what was wrong and how the change removes the violation.",
  "files": [
    {"filePath": "src/path/As/Given.cs", "proposedContent": "the COMPLETE new file text", "summary": ["short bullet"]}
  ]
}
Rules:
- Only edit files that are present in the prompt; use their filePath verbatim (forward slashes).
- proposedContent must be the complete file, never a diff, snippet or placeholder like "...".
- Preserve every unrelated method, field, comment, import and the file's original indentation and
  line endings. Change only what the finding requires.
- Do not introduce new dependencies outside the stack's standard libraries.
- If the finding cannot be fixed without violating these rules, return an empty files array."""

SYSTEM_IMPLEMENT = """You are Kodo's architecture copilot. You implement exactly one method.
Return JSON only:
{
  "explanation": "One short paragraph describing the implementation.",
  "proposedContent": "the COMPLETE new file text"
}
Rules:
- Return the complete file, never a diff or snippet.
- Modify only the requested method (plus the private helpers it strictly needs).
- Preserve every other method, field, constructor, annotation, import, comment, indentation and
  line ending byte for byte.
- Respect the component's layer: controllers delegate to services, services use repositories,
  entities stay inside the persistence boundary."""


SYSTEM_FIX_BUILD_ERRORS = """You are Kodo's build doctor. A sandboxed compiler/test run rejected code that a
developer is about to apply. Fix ONLY the reported compile/test errors.
Return JSON only:
{
  "explanation": "One short paragraph: the root cause and the minimal fix.",
  "files": [
    {"filePath": "src/path/As/Given.cs", "proposedContent": "the COMPLETE corrected file text", "summary": ["short bullet"]}
  ]
}
Rules:
- Only edit files present in the prompt; use their filePath verbatim (forward slashes).
- proposedContent must be the complete file, never a diff, snippet or placeholder.
- Preserve all business logic, public APIs, comments, formatting and line endings outside the fix.
- Fix missing imports/usings, type mismatches, nullability, signatures and test expectations first.
- Do not silence errors by deleting code or disabling tests unless the diagnostic proves the code is
  dead; never add new third-party dependencies.
- If the diagnostics cannot be fixed without violating these rules, return an empty files array."""


def fix_build_prompt(
    stack: str,
    diagnostics: list[dict],
    compiler_output: str,
    sources: list[tuple[str, str]],
    *,
    packed_ir: str = "",
) -> str:
    lines = [
        f"## Build stack\n{stack}",
        "",
        "## Compiler / test diagnostics",
        json.dumps(diagnostics[:60], indent=2, ensure_ascii=False),
        "",
        "## Build log excerpt (truncated, ANSI-free)",
        "```",
        compiler_output.strip(),
        "```",
    ]
    if packed_ir:
        lines += ["", "## Compact workspace IR", packed_ir]
    lines += ["", "## Files you may edit (complete content)"]
    for file_path, content in sources:
        lines += [f"### {file_path}", "```", content, "```", ""]
    return "\n".join(lines)


def spec_prompt(spec: str, stack: BlueprintStack, project_name: str | None, base_package: str | None) -> str:
    lines = [f"Target stack: {stack}", _STACK_GUIDANCE[str(stack)]]
    if project_name:
        lines.append(f"Project name: {project_name}")
    if base_package:
        lines.append(f"Base package / namespace / source root: {base_package}")
    lines += ["", "Business specification:", spec.strip()]
    return "\n".join(lines)


def audit_fix_prompt(finding: AuditFinding, packed_ir: str, sources: list[SourceFile]) -> str:
    blocks = [
        "## Audit finding to fix",
        json.dumps(finding.model_dump(by_alias=True, mode="json"), indent=2, ensure_ascii=False),
        "",
        "## Compact workspace IR",
        packed_ir,
        "",
        "## Files you may edit (complete current content)",
    ]
    for source in sources:
        blocks += [f"### {source.file_path}", "```", source.content, "```", ""]
    return "\n".join(blocks)


def implement_prompt(
    node_id: str,
    node_name: str,
    method_name: str,
    instruction: str,
    packed_ir: str,
    source: SourceFile,
) -> str:
    return "\n".join(
        [
            f"## Component\n{node_name} (`{node_id}`)",
            f"## Method to implement or update\n{method_name}",
            "## Developer instruction",
            instruction.strip(),
            "",
            "## Compact IR context (component + direct neighbours)",
            packed_ir,
            "",
            f"## Current content of {source.file_path}",
            "```",
            source.content,
            "```",
        ]
    )


__all__ = [
    "SYSTEM_AUDIT_FIX",
    "SYSTEM_BLUEPRINT",
    "SYSTEM_FIX_BUILD_ERRORS",
    "SYSTEM_IMPLEMENT",
    "audit_fix_prompt",
    "fix_build_prompt",
    "implement_prompt",
    "spec_prompt",
]
