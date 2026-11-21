"""Structured Git/GitHub rejection surfaced as ``{code, message}`` HTTP details."""

from __future__ import annotations


class GitRemoteError(Exception):
    """A rejected Git/GitHub operation. Messages never contain tokens."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code

    def payload(self) -> dict[str, str]:
        return {"code": self.code, "message": str(self)}


__all__ = ["GitRemoteError"]
