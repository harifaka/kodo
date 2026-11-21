"""LLM configuration for the DeepSeek Architecture Copilot.

Defaults come from the environment; the UI settings drawer can override the Base URL, models, the
API key and the timeout per request. Overrides travel in the request body only and are never
persisted server-side or written to logs.
"""

from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

DEFAULT_LLM_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_CODE_MODEL = "deepseek-chat"
DEFAULT_REASONING_MODEL = "deepseek-reasoner"
DEFAULT_TIMEOUT_SECONDS = 90.0
DEFAULT_MAX_CONTEXT_CHARS = 24_000
MAX_CONTEXT_CHARS_FLOOR = 2_000
MAX_CONTEXT_CHARS_CEILING = 200_000

_LOCAL_ALIASES = {"localhost", "host.docker.internal"}


class LlmOverride(BaseModel):
    """Per-request settings from the AI Copilot drawer (kept in the browser, never on disk)."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")

    base_url: str | None = Field(default=None, max_length=2048)
    api_key: str | None = Field(default=None, max_length=4096)
    code_model: str | None = Field(default=None, max_length=200)
    reasoning_model: str | None = Field(default=None, max_length=200)
    timeout_seconds: float | None = Field(default=None, gt=0, le=600)


@dataclass(frozen=True)
class LlmConfig:
    base_url: str
    api_key: str
    code_model: str
    reasoning_model: str
    timeout_seconds: float

    @property
    def has_api_key(self) -> bool:
        return bool(self.api_key)

    @property
    def is_local(self) -> bool:
        return is_local_base_url(self.base_url)


def _env(name: str, fallback: str) -> str:
    return (os.getenv(name) or "").strip() or fallback


def _env_timeout() -> float:
    raw = (os.getenv("KODO_LLM_TIMEOUT_SECONDS") or "").strip()
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_TIMEOUT_SECONDS
    return value if value > 0 else DEFAULT_TIMEOUT_SECONDS


def normalize_base_url(base_url: str) -> str:
    return base_url.strip().rstrip("/")


def resolve_config(override: LlmOverride | None = None) -> LlmConfig:
    """Merge request overrides over environment defaults. Never raises; validated per call."""
    override = override or LlmOverride()
    return LlmConfig(
        base_url=normalize_base_url(override.base_url or _env("KODO_LLM_BASE_URL", DEFAULT_LLM_BASE_URL)),
        api_key=(override.api_key if override.api_key is not None else os.getenv("KODO_LLM_API_KEY") or "").strip(),
        code_model=(override.code_model or _env("KODO_LLM_CODE_MODEL", DEFAULT_CODE_MODEL)).strip(),
        reasoning_model=(
            override.reasoning_model or _env("KODO_LLM_REASONING_MODEL", DEFAULT_REASONING_MODEL)
        ).strip(),
        timeout_seconds=override.timeout_seconds or _env_timeout(),
    )


def is_local_base_url(base_url: str) -> bool:
    """True for loopback / private-network servers (Ollama, vLLM) that accept keyless requests."""
    try:
        host = (urlsplit(base_url).hostname or "").strip().lower()
    except ValueError:
        return False
    if not host:
        return False
    if host in _LOCAL_ALIASES:
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address.is_loopback or address.is_private


def max_context_chars() -> int:
    """IR prompt budget; clamped so a bad env value can never blow up a request."""
    raw = (os.getenv("KODO_LLM_MAX_CONTEXT_CHARS") or "").strip()
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_MAX_CONTEXT_CHARS
    return max(MAX_CONTEXT_CHARS_FLOOR, min(MAX_CONTEXT_CHARS_CEILING, value))


__all__ = [
    "DEFAULT_CODE_MODEL",
    "DEFAULT_LLM_BASE_URL",
    "DEFAULT_MAX_CONTEXT_CHARS",
    "DEFAULT_REASONING_MODEL",
    "DEFAULT_TIMEOUT_SECONDS",
    "LlmConfig",
    "LlmOverride",
    "is_local_base_url",
    "max_context_chars",
    "normalize_base_url",
    "resolve_config",
]
