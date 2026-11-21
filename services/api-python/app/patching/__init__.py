"""Stateless, in-memory AST patching for the Phase 3b dry-run pipeline.

Every patcher receives source text, returns proposed text, and never touches the filesystem.
"""

from app.patching.models import (
    DryRunRequest,
    DryRunResponse,
    PatchOperation,
    PatchOutcome,
    PatchResult,
)

__all__ = [
    "DryRunRequest",
    "DryRunResponse",
    "PatchOperation",
    "PatchOutcome",
    "PatchResult",
]
