"""Streamable HTTP transport for the Kodo MCP server (``POST /mcp``) plus ``GET /api/v1/mcp/info``.

Sessions are stateless: no ``Mcp-Session-Id`` is ever issued, so the endpoint is safe behind Nginx,
Caddy and any number of replicas. Responses are plain JSON unless the client explicitly prefers
``text/event-stream``, in which case a single SSE ``message`` event carries the JSON-RPC response.
``GET``/``DELETE`` answer ``405`` because this server offers no server-initiated stream and keeps no
session to terminate.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from app.auth.dependencies import CurrentUser, authenticate_request
from app.config import get_settings, mcp_enabled, rate_limit_per_minute
from app.db.repository import UserRecord
from app.mcp import MCP_ENDPOINT_PATH, MCP_PROTOCOL
from app.mcp.protocol import (
    MCP_DISABLED_CODE,
    MCP_METHOD_NOT_ALLOWED_CODE,
    MCP_UNAUTHORIZED_CODE,
    PROTOCOL_VERSIONS,
)
from app.mcp.server import McpServer, parse_payload
from app.mcp.tools import TOOL_SPECS, ToolContext

logger = logging.getLogger("kodo.mcp")

MAX_REQUEST_BYTES = 4 * 1024 * 1024

router = APIRouter()
info_router = APIRouter()

_BASE_HEADERS = {"Cache-Control": "no-store"}
_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
    "Connection": "keep-alive",
}
_METHOD_NOT_ALLOWED_MESSAGE = (
    "Kodo's MCP server is stateless Streamable HTTP: send JSON-RPC messages with POST /mcp. "
    "There is no server-initiated SSE stream to GET and no session to DELETE."
)


def _disabled_response() -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content={
            "detail": {
                "code": MCP_DISABLED_CODE,
                "message": "The Kodo MCP server is disabled (KODO_MCP_ENABLED=false).",
            }
        },
        headers=_BASE_HEADERS,
    )


def _unauthorized_response() -> JSONResponse:
    return JSONResponse(
        status_code=401,
        content={
            "detail": {
                "code": MCP_UNAUTHORIZED_CODE,
                "message": "MCP requires an authenticated session or Bearer token in SaaS mode.",
            }
        },
        headers=_BASE_HEADERS,
    )


def _method_not_allowed_response() -> JSONResponse:
    return JSONResponse(
        status_code=405,
        content={"detail": {"code": MCP_METHOD_NOT_ALLOWED_CODE, "message": _METHOD_NOT_ALLOWED_MESSAGE}},
        headers={**_BASE_HEADERS, "Allow": "POST"},
    )


def _current_user(request: Request) -> UserRecord | None:
    """The user resolved by ``tenant_guard``; falls back to a direct token lookup."""
    user = getattr(request.state, "user", None)
    if isinstance(user, UserRecord):
        return user
    return authenticate_request(request)


def _response_headers(request: Request, extra: dict[str, str] | None = None) -> dict[str, str]:
    headers = dict(extra or {})
    # Echo the negotiated protocol version so clients can pin it on subsequent stateless requests.
    negotiated = request.headers.get("mcp-protocol-version", "").strip()
    if negotiated:
        headers["Mcp-Protocol-Version"] = negotiated
    return headers


def _prefers_event_stream(request: Request) -> bool:
    accept = request.headers.get("accept", "").lower()
    return "text/event-stream" in accept and "application/json" not in accept


def _sse_body(payload: Any) -> str:
    messages = payload if isinstance(payload, list) else [payload]
    return "".join(
        f"event: message\ndata: {json.dumps(message, ensure_ascii=False, separators=(',', ':'))}\n\n"
        for message in messages
    )


@router.post(MCP_ENDPOINT_PATH, include_in_schema=False)
async def mcp_endpoint(request: Request) -> Response:
    """Stateless Streamable HTTP JSON-RPC endpoint (MCP ``2026-07-28``/``2025-06-18``/``2025-03-26``)."""
    if not mcp_enabled():
        return _disabled_response()

    user = _current_user(request)
    if user is None:
        return _unauthorized_response()

    raw = await request.body()
    if len(raw) > MAX_REQUEST_BYTES:
        return JSONResponse(
            status_code=413,
            content={
                "detail": {
                    "code": "PAYLOAD_TOO_LARGE",
                    "message": f"MCP requests are limited to {MAX_REQUEST_BYTES // (1024 * 1024)} MB.",
                }
            },
            headers=_BASE_HEADERS,
        )

    payload, parse_error = parse_payload(raw)
    if parse_error is not None:
        return JSONResponse(
            status_code=400,
            content=parse_error,
            headers=_response_headers(request, _BASE_HEADERS),
        )

    # Observability only: agents may announce the JSON-RPC method/tool they are about to call.
    announced_method = request.headers.get("mcp-method", "").strip()
    announced_name = request.headers.get("mcp-name", "").strip()
    if announced_method or announced_name:
        logger.debug("MCP request hint method=%r name=%r", announced_method, announced_name)

    response_payload = await McpServer().handle_payload(payload, ToolContext(user=user))
    if response_payload is None:
        # Notifications are acknowledged without a body, exactly as the transport spec requires.
        return Response(status_code=202, headers=_response_headers(request, _BASE_HEADERS))

    if _prefers_event_stream(request):
        return Response(
            content=_sse_body(response_payload),
            media_type="text/event-stream",
            headers=_response_headers(request, _SSE_HEADERS),
        )

    return JSONResponse(
        content=response_payload,
        headers=_response_headers(request, _BASE_HEADERS),
    )


@router.get(MCP_ENDPOINT_PATH, include_in_schema=False)
async def mcp_get() -> Response:
    """No server-initiated stream: stateless servers answer ``405`` (allowed by the spec)."""
    if not mcp_enabled():
        return _disabled_response()
    return _method_not_allowed_response()


@router.delete(MCP_ENDPOINT_PATH, include_in_schema=False)
async def mcp_delete() -> Response:
    """No session to terminate: stateless servers answer ``405`` (allowed by the spec)."""
    if not mcp_enabled():
        return _disabled_response()
    return _method_not_allowed_response()


class McpInfoModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class McpToolInfo(McpInfoModel):
    name: str
    description: str
    read_only: bool = Field(default=True)


class McpInfoResponse(McpInfoModel):
    enabled: bool
    endpoint_path: str
    protocol: str
    tool_count: int
    tools: list[McpToolInfo] = Field(default_factory=list)
    transports: list[str] = Field(default_factory=list)
    protocol_versions: list[str] = Field(default_factory=list)
    mode: str
    saas_requires_auth: bool
    rate_limit_per_minute: int


@info_router.get("/api/v1/mcp/info", response_model=McpInfoResponse, tags=["mcp"])
def mcp_info(_user: CurrentUser) -> McpInfoResponse:
    """Live MCP status for the setup drawer: enablement, endpoint, tool catalog and SaaS posture."""
    settings = get_settings()
    return McpInfoResponse(
        enabled=mcp_enabled(),
        endpoint_path=MCP_ENDPOINT_PATH,
        protocol=MCP_PROTOCOL,
        tool_count=len(TOOL_SPECS),
        tools=[
            McpToolInfo(name=spec.name, description=spec.description, read_only=True)
            for spec in TOOL_SPECS
        ],
        transports=["streamable-http", "stdio"],
        protocol_versions=list(PROTOCOL_VERSIONS),
        mode=settings.mode,
        saas_requires_auth=settings.is_saas,
        rate_limit_per_minute=rate_limit_per_minute("mcp"),
    )


__all__ = ["info_router", "router"]
