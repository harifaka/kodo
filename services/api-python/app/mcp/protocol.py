"""JSON-RPC 2.0 / MCP wire primitives for the stateless Streamable HTTP server.

The server speaks plain JSON-RPC 2.0 over HTTP with the MCP method set. Sessions are never sticky:
no state is kept between requests, so any replica behind Nginx or Caddy can answer any call.
"""

from __future__ import annotations

from typing import Any, Final

SERVER_NAME = "kodo"

# Newest first. `initialize` echoes the client's version when it is one of these, so older agents
# stay connected instead of being forced through a downgrade handshake.
PROTOCOL_VERSIONS: Final[tuple[str, ...]] = ("2026-07-28", "2025-06-18", "2025-03-26")
DEFAULT_PROTOCOL_VERSION: Final[str] = "2025-06-18"

PARSE_ERROR: Final[int] = -32700
INVALID_REQUEST: Final[int] = -32600
METHOD_NOT_FOUND: Final[int] = -32601
INVALID_PARAMS: Final[int] = -32602
INTERNAL_ERROR: Final[int] = -32603
# Implementation-defined server errors (-32000 .. -32099).
SERVER_ERROR: Final[int] = -32000
UNAUTHORIZED: Final[int] = -32001

MCP_DISABLED_CODE = "MCP_DISABLED"
MCP_UNAUTHORIZED_CODE = "UNAUTHORIZED"
MCP_METHOD_NOT_ALLOWED_CODE = "METHOD_NOT_ALLOWED"

NOTIFICATION_PREFIX: Final[str] = "notifications/"


def result_envelope(request_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def error_envelope(
    request_id: Any,
    code: int,
    message: str,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": request_id, "error": error}


class RpcError(Exception):
    """Protocol-level JSON-RPC failure (unknown method, invalid params, …)."""

    def __init__(self, code: int, message: str, data: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data

    def envelope(self, request_id: Any) -> dict[str, Any]:
        return error_envelope(request_id, self.code, self.message, self.data)


class ToolError(Exception):
    """Tool-execution failure, reported to the agent as ``isError: true`` tool content.

    Authorization and containment rejections are business outcomes, not protocol violations, so they
    travel inside a successful JSON-RPC result where every MCP client can read them.
    """

    def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}

    def payload(self) -> dict[str, Any]:
        return {"error": {"code": self.code, "message": self.message, **self.details}}


def negotiate_protocol_version(requested: Any) -> str:
    """Echo a supported version, otherwise answer with Kodo's newest implemented revision."""
    if isinstance(requested, str) and requested in PROTOCOL_VERSIONS:
        return requested
    return DEFAULT_PROTOCOL_VERSION


__all__ = [
    "DEFAULT_PROTOCOL_VERSION",
    "INTERNAL_ERROR",
    "INVALID_PARAMS",
    "INVALID_REQUEST",
    "MCP_DISABLED_CODE",
    "MCP_METHOD_NOT_ALLOWED_CODE",
    "MCP_UNAUTHORIZED_CODE",
    "METHOD_NOT_FOUND",
    "NOTIFICATION_PREFIX",
    "PARSE_ERROR",
    "PROTOCOL_VERSIONS",
    "RpcError",
    "SERVER_ERROR",
    "SERVER_NAME",
    "ToolError",
    "UNAUTHORIZED",
    "error_envelope",
    "negotiate_protocol_version",
    "result_envelope",
]
