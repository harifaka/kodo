"""System 1 (Laya) configuration.

Environment defaults come from ``app.config``; the UI drawer can override the Base URL, model, API
key, timeout and confidence threshold per request. Overrides travel in the request body only and are
never logged or persisted.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from app.config import (
    systemone_api_key,
    systemone_auto_threshold,
    systemone_base_url,
    systemone_enabled,
    systemone_model,
    systemone_timeout_seconds,
)


class SystemOneOverride(BaseModel):
    """Per-request settings from the AI settings drawer (kept in the browser, never on disk)."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")

    enabled: bool | None = None
    base_url: str | None = Field(default=None, max_length=2048)
    model: str | None = Field(default=None, max_length=200)
    api_key: str | None = Field(default=None, max_length=4096)
    timeout_seconds: float | None = Field(default=None, gt=0, le=120)
    auto_threshold: float | None = Field(default=None, ge=0, le=1)


@dataclass(frozen=True)
class SystemOneConfig:
    enabled: bool
    base_url: str
    model: str
    api_key: str
    timeout_seconds: float
    auto_threshold: float

    @property
    def has_api_key(self) -> bool:
        return bool(self.api_key)

    @property
    def provider_hint(self) -> str:
        return provider_hint(self.base_url)


def provider_hint(base_url: str) -> str:
    """Best-effort label for the settings drawer: Ollama, laya-serve or a generic endpoint."""
    try:
        parts = urlsplit(base_url)
    except ValueError:
        return "systemone"
    host = (parts.hostname or "").lower()
    netloc = (parts.netloc or "").lower()
    if "ollama" in host or netloc.endswith(":11434"):
        return "ollama"
    if "laya-serve" in host:
        return "laya-serve"
    return "systemone"


def normalize_base_url(base_url: str) -> str:
    return base_url.strip().rstrip("/")


def resolve_config(override: SystemOneOverride | None = None) -> SystemOneConfig:
    """Merge request overrides over environment defaults. Never raises; validated per call."""
    override = override or SystemOneOverride()
    enabled = override.enabled if override.enabled is not None else systemone_enabled()
    threshold = override.auto_threshold if override.auto_threshold is not None else systemone_auto_threshold()
    timeout = override.timeout_seconds if override.timeout_seconds is not None else systemone_timeout_seconds()
    return SystemOneConfig(
        enabled=bool(enabled),
        base_url=normalize_base_url(override.base_url or systemone_base_url()),
        model=(override.model or systemone_model()).strip(),
        api_key=(override.api_key if override.api_key is not None else systemone_api_key()).strip(),
        timeout_seconds=timeout,
        auto_threshold=max(0.0, min(1.0, threshold)),
    )


__all__ = [
    "SystemOneConfig",
    "SystemOneOverride",
    "normalize_base_url",
    "provider_hint",
    "resolve_config",
]
