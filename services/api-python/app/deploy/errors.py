"""Structured Deploy Studio errors surfaced as ``{code, message}`` HTTP details."""

from __future__ import annotations


class DeployError(Exception):
    """A rejected deploy/docker operation. Messages never contain tokens or file contents."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code

    def payload(self) -> dict[str, str]:
        return {"code": self.code, "message": str(self)}


__all__ = ["DeployError"]
