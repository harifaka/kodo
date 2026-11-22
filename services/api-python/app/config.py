"""Runtime configuration (environment driven, no external settings dependency)."""

from __future__ import annotations

import os

# Vite dev server origins only. The Docker stack serves the UI same-origin through Nginx, so it
# never needs CORS; extend or replace this list with KODO_CORS_ORIGINS for custom deployments.
DEFAULT_CORS_ORIGINS = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
)

DEFAULT_API_PORT = 8088
MAX_INSPECT_BYTES = 2_000_000
MAX_AUDIT_NODES = 20_000
MAX_AUDIT_RELATIONS = 50_000
# Dry-run patching reads one file into memory and returns proposed text; nothing is written.
MAX_PATCH_BYTES = 2_000_000
# Guarded apply writes at most this many files per atomic batch.
MAX_APPLY_FILES = 200


def csharp_analyzer_url() -> str:
    return os.getenv("KODO_CSHARP_URL", "http://localhost:5050").rstrip("/")


def cors_origins() -> list[str]:
    configured = os.getenv("KODO_CORS_ORIGINS")
    if not configured:
        return list(DEFAULT_CORS_ORIGINS)
    return [origin.strip() for origin in configured.split(",") if origin.strip()]
