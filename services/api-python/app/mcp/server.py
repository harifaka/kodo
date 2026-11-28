"""MCP request dispatcher shared by the Streamable HTTP route and the stdio bridge.

The dispatcher is transport-agnostic: it takes a parsed JSON-RPC payload plus the authenticated
:class:`~app.mcp.tools.ToolContext` and returns a JSON-RPC response (or ``None`` for a notification).
No session state is stored, so every request is independent and any replica can serve it.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import ValidationError

from app import __version__
from app.mcp.protocol import (
    DEFAULT_PROTOCOL_VERSION,
    INTERNAL_ERROR,
    INVALID_PARAMS,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    NOTIFICATION_PREFIX,
    PARSE_ERROR,
    PROTOCOL_VERSIONS,
    SERVER_NAME,
    RpcError,
    ToolError,
    error_envelope,
    negotiate_protocol_version,
    result_envelope,
)
from app.mcp.resources import list_resources, read_resource
from app.mcp.tools import TOOLS_BY_NAME, ToolContext, list_tool_definitions

logger = logging.getLogger("kodo.mcp")

INSTRUCTIONS = (
    "Kodo is an Architecture Control Center. Every tool here is read-only, dry-run or sandbox-only: "
    "no tool can write, apply, roll back, deploy or export anything. Use kodo_scan_workspace for a "
    "compact architecture overview, kodo_audit_workspace for deterministic findings, "
    "kodo_get_component for one component plus its 1-hop neighbourhood, kodo_route_task and "
    "kodo_screen_diff for advisory System 1 guidance, kodo_dry_run_patch to preview AST edits in "
    "memory, and kodo_verify_build to compile a staged snapshot in an isolated sandbox. Any change "
    "still has to go through Kodo's diff review and SHA-256 guarded apply in the web UI."
)


def tool_error_result(error: ToolError) -> dict[str, Any]:
    """Represent a tool-execution failure as ``isError: true`` content (MCP convention)."""
    return {
        "content": [
            {"type": "text", "text": json.dumps(error.payload(), ensure_ascii=False, separators=(",", ":"))}
        ],
        "isError": True,
    }


class McpServer:
    """Stateless JSON-RPC 2.0 dispatcher for the Kodo MCP tool registry."""

    async def handle_payload(self, payload: Any, ctx: ToolContext) -> Any | None:
        """Handle one parsed payload: a single JSON-RPC message or a legacy batch array."""
        if isinstance(payload, list):
            if not payload:
                return error_envelope(None, INVALID_REQUEST, "Empty JSON-RPC batch.")
            responses = [response for message in payload if (response := await self.handle_message(message, ctx))]
            return responses or None
        return await self.handle_message(payload, ctx)

    async def handle_message(self, message: Any, ctx: ToolContext) -> dict[str, Any] | None:
        if not isinstance(message, dict):
            return error_envelope(None, INVALID_REQUEST, "A JSON-RPC message must be an object.")

        request_id = message.get("id")
        is_notification = "id" not in message

        if message.get("jsonrpc") != "2.0":
            return error_envelope(request_id, INVALID_REQUEST, 'jsonrpc must be "2.0".')

        method = message.get("method")
        if not isinstance(method, str) or not method:
            return error_envelope(request_id, INVALID_REQUEST, "method must be a non-empty string.")

        params = message.get("params")
        if params is None:
            params = {}
        if not isinstance(params, dict):
            return error_envelope(request_id, INVALID_PARAMS, "params must be an object.")

        if method.startswith(NOTIFICATION_PREFIX):
            # notifications/initialized, notifications/cancelled, … are acknowledged with no body.
            return None

        try:
            result = await self._dispatch(method, params, ctx)
        except RpcError as exc:
            logger.debug("MCP protocol error on %s: %s", method, exc.message)
            return None if is_notification else exc.envelope(request_id)
        except Exception:  # pragma: no cover - defensive: a bug must not kill the transport
            logger.exception("MCP method %s failed unexpectedly", method)
            return (
                None
                if is_notification
                else error_envelope(request_id, INTERNAL_ERROR, "Internal MCP server error.")
            )

        if is_notification:
            return None
        return result_envelope(request_id, result)

    async def _dispatch(self, method: str, params: dict[str, Any], ctx: ToolContext) -> Any:
        if method == "initialize":
            return self._initialize(params)
        if method == "ping":
            return {}
        if method == "tools/list":
            return {"tools": list_tool_definitions()}
        if method == "tools/call":
            return await self._call_tool(params, ctx)
        if method == "resources/list":
            return {"resources": list_resources()}
        if method == "resources/read":
            return await self._read_resource(params)
        raise RpcError(
            METHOD_NOT_FOUND,
            f"Unknown MCP method: {method}",
            {
                "supported": [
                    "initialize",
                    "ping",
                    "tools/list",
                    "tools/call",
                    "resources/list",
                    "resources/read",
                ]
            },
        )

    def _initialize(self, params: dict[str, Any]) -> dict[str, Any]:
        return {
            "protocolVersion": negotiate_protocol_version(params.get("protocolVersion")),
            "capabilities": {
                "tools": {"listChanged": False},
                "resources": {"subscribe": False, "listChanged": False},
            },
            "serverInfo": {
                "name": SERVER_NAME,
                "title": "Kodo Architecture Control Center",
                "version": __version__,
            },
            "instructions": INSTRUCTIONS,
        }

    async def _call_tool(self, params: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
        name = params.get("name")
        if not isinstance(name, str) or not name:
            raise RpcError(INVALID_PARAMS, "tools/call requires a tool `name`.")

        spec = TOOLS_BY_NAME.get(name)
        if spec is None:
            raise RpcError(
                INVALID_PARAMS,
                f"Unknown tool: {name}",
                {"available": sorted(TOOLS_BY_NAME)},
            )

        arguments = params.get("arguments")
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, dict):
            raise RpcError(INVALID_PARAMS, "`arguments` must be an object.")

        try:
            parsed = spec.input_model.model_validate(arguments)
        except ValidationError as exc:
            raise RpcError(
                INVALID_PARAMS,
                f"Invalid arguments for {name}.",
                {
                    "errors": [
                        {
                            "path": ".".join(str(part) for part in error["loc"]),
                            "message": error["msg"],
                        }
                        for error in exc.errors()[:10]
                    ]
                },
            ) from exc

        try:
            result = await spec.handler(ctx, parsed)
        except ToolError as exc:
            logger.info("MCP tool %s rejected: %s", name, exc.code)
            return tool_error_result(exc)

        return {
            "content": [
                {"type": "text", "text": json.dumps(result, ensure_ascii=False, separators=(",", ":"))}
            ],
            "structuredContent": result,
            "isError": False,
        }

    async def _read_resource(self, params: dict[str, Any]) -> dict[str, Any]:
        uri = params.get("uri")
        if not isinstance(uri, str) or not uri:
            raise RpcError(INVALID_PARAMS, "resources/read requires a `uri`.")
        return await read_resource(uri)


def parse_payload(raw: bytes) -> tuple[Any | None, dict[str, Any] | None]:
    """Decode a request body; returns ``(payload, error_envelope)`` with exactly one populated."""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None, error_envelope(None, PARSE_ERROR, "Request body must be UTF-8 encoded JSON.")
    if not text.strip():
        return None, error_envelope(None, PARSE_ERROR, "Request body is empty.")
    try:
        return json.loads(text), None
    except json.JSONDecodeError as exc:
        return None, error_envelope(None, PARSE_ERROR, f"Invalid JSON: {exc.msg}")


__all__ = [
    "DEFAULT_PROTOCOL_VERSION",
    "INSTRUCTIONS",
    "McpServer",
    "PROTOCOL_VERSIONS",
    "parse_payload",
    "tool_error_result",
]
