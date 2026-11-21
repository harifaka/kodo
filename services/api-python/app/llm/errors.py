"""Structured errors raised by the AI Copilot.

Every failure carries a stable ``code`` so the UI can react without parsing prose, and a message
that is safe to display. API keys never appear in these messages.
"""

from __future__ import annotations


class LlmError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 502,
        details: list[str] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or []

    def payload(self) -> dict[str, object]:
        detail: dict[str, object] = {"code": self.code, "message": self.message}
        if self.details:
            detail["details"] = self.details
        return detail


__all__ = ["LlmError"]
