"""C# dry-run patching: POST the file content to the stateless Roslyn container.

The orchestrator reads the file, sends it to :5050/patch, and receives proposed text back. If the
container is offline the original content is returned unchanged with a human-readable warning.
"""

from __future__ import annotations

import httpx

from app.config import csharp_analyzer_url
from app.patching.models import PatchOperation, PatchOutcome

_PATCH_TIMEOUT = 30.0


async def patch_csharp(
    file_path: str,
    content: str,
    operations: list[PatchOperation],
) -> PatchOutcome:
    payload = {
        "filePath": file_path,
        "content": content,
        "operations": [_operation_payload(operation) for operation in operations],
    }
    url = f"{csharp_analyzer_url()}/patch"

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(_PATCH_TIMEOUT, connect=2.0)) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()
    except (TimeoutError, httpx.HTTPError, ValueError) as exc:
        return PatchOutcome(
            content=content,
            applied=[],
            warnings=[
                (
                    f"C# Roslyn analyzer unreachable at {csharp_analyzer_url()} ({type(exc).__name__}); "
                    "the .cs patch was skipped. Start services/analyzer-csharp and retry."
                )
            ],
        )

    if not isinstance(data, dict):
        return PatchOutcome(
            content=content,
            applied=[],
            warnings=["C# Roslyn analyzer returned an unexpected response; the .cs patch was skipped."],
        )

    proposed = data.get("proposedContent")
    if not isinstance(proposed, str):
        return PatchOutcome(
            content=content,
            applied=[],
            warnings=["C# Roslyn analyzer returned no proposedContent; the .cs patch was skipped."],
        )

    raw_applied = data.get("appliedOps")
    raw_warnings = data.get("warnings")
    applied = [str(item) for item in raw_applied] if isinstance(raw_applied, list) else []
    warnings = [str(item) for item in raw_warnings] if isinstance(raw_warnings, list) else []
    return PatchOutcome(content=proposed, applied=applied, warnings=warnings)


def _operation_payload(operation: PatchOperation) -> dict[str, object]:
    field = operation.field
    return {
        "op": operation.op,
        "typeName": operation.type_name,
        "fieldName": operation.field_name,
        "originalName": operation.original_name,
        "field": (
            {
                "name": field.name,
                "type": field.type,
                "visibility": field.visibility,
                "annotations": field.annotations,
            }
            if field is not None
            else None
        ),
        "annotation": operation.annotation,
    }
