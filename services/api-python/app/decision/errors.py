"""Structured errors raised by the System 1 (Laya) decision layer.

The codes are stable so the UI can react without parsing prose. Messages are safe to display and
never contain an API key, a prompt or a state payload.
"""

from __future__ import annotations

SYSTEMONE_DISABLED = "SYSTEMONE_DISABLED"
SYSTEMONE_UNREACHABLE = "SYSTEMONE_UNREACHABLE"
SYSTEMONE_TIMEOUT = "SYSTEMONE_TIMEOUT"
SYSTEMONE_UNAUTHORIZED = "SYSTEMONE_UNAUTHORIZED"
SYSTEMONE_INVALID_RESPONSE = "SYSTEMONE_INVALID_RESPONSE"


class SystemOneError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code

    def payload(self) -> dict[str, object]:
        return {"code": self.code, "message": self.message}

    def warning(self) -> str:
        return f"{self.code}: {self.message}"


__all__ = [
    "SYSTEMONE_DISABLED",
    "SYSTEMONE_INVALID_RESPONSE",
    "SYSTEMONE_TIMEOUT",
    "SYSTEMONE_UNAUTHORIZED",
    "SYSTEMONE_UNREACHABLE",
    "SystemOneError",
]
