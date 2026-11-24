"""Phase 10 System 1 (Laya) decision layer.

Advisory only: a local, non-autoregressive decision model triages findings, routes work between the
deterministic AST/Builder paths and DeepSeek, and pre-screens proposed diffs. Every decision is
persisted as a tenant-scoped ADR. Kodo keeps working with deterministic rules when Laya is offline.
"""

from app.decision.client import SystemOneClient, SystemOneResponse, test_connection
from app.decision.config import SystemOneConfig, SystemOneOverride, resolve_config
from app.decision.errors import SystemOneError
from app.decision.service import DiffScreenResult, RouteResult, TriageResult

__all__ = [
    "DiffScreenResult",
    "RouteResult",
    "SystemOneClient",
    "SystemOneConfig",
    "SystemOneError",
    "SystemOneOverride",
    "SystemOneResponse",
    "TriageResult",
    "resolve_config",
    "test_connection",
]
