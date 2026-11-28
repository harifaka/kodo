"""Stateless in-memory AST dry-run shared by ``POST /api/v1/dry-run`` and the MCP server.

Nothing here writes to disk: files are read once, patched in memory and returned with the SHA-256 of
the exact bytes read, so a later guarded apply can detect a stale file. Java, TypeScript/JavaScript,
Python and C# are handled by their Tree-sitter / Roslyn patchers.
"""

from __future__ import annotations

from pathlib import Path

from app.patching.csharp_patcher import patch_csharp
from app.patching.java_patcher import patch_java
from app.patching.models import (
    DryRunResponse,
    PatchOperation,
    PatchResult,
    sha256_hex,
    summarize,
)
from app.patching.paths import build_targets
from app.patching.python_patcher import patch_python
from app.patching.ts_patcher import patch_script


async def compute_dry_run(root: Path, operations: list[PatchOperation]) -> DryRunResponse:
    """Resolve, read and patch the target files in memory. Raises ``PatchRejected`` on bad paths."""
    targets = build_targets(str(root), operations)

    patches: list[PatchResult] = []
    for target in targets:
        if target.language == "java":
            outcome = patch_java(target.content, target.operations)
        elif target.language in {"typescript", "javascript"}:
            outcome = patch_script(target.content, target.operations, target.file_path)
        elif target.language == "python":
            outcome = patch_python(target.content, target.operations)
        else:
            outcome = await patch_csharp(target.file_path, target.content, target.operations)

        patches.append(
            PatchResult(
                file_path=target.file_path,
                language=target.language,
                original_content=target.content,
                original_sha256=sha256_hex(target.raw),
                proposed_content=outcome.content,
                summary=summarize(outcome),
                warnings=outcome.warnings,
            )
        )

    return DryRunResponse(patches=patches, warnings=[])


__all__ = ["compute_dry_run"]
