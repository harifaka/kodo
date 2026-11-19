"""Runtime configuration (environment driven, no external settings dependency)."""

from __future__ import annotations

import os

DEFAULT_CORS_ORIGINS = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "tauri://localhost",
    "https://tauri.localhost",
    "http://tauri.localhost",
)

MAX_INSPECT_BYTES = 2_000_000


def csharp_analyzer_url() -> str:
    return os.getenv("KODO_CSHARP_URL", "http://localhost:5050").rstrip("/")


def cors_origins() -> list[str]:
    configured = os.getenv("KODO_CORS_ORIGINS")
    if not configured:
        return list(DEFAULT_CORS_ORIGINS)
    return [origin.strip() for origin in configured.split(",") if origin.strip()]
