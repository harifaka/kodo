"""Kodo MCP server (Phase 15).

A standards-compliant **Model Context Protocol** surface that exposes Kodo's architecture
intelligence to AI coding agents. Every tool is strictly read-only, dry-run or sandbox-only: there is
no ``apply``, ``rollback``, ``deploy``, ``git/export`` or any other disk-mutating operation here.
Writes still flow exclusively through the guarded apply pipeline in the web UI.

Two transports share one tool registry (:mod:`app.mcp.tools`):

* **Streamable HTTP** at ``/mcp`` (stateless JSON-RPC 2.0, JSON or SSE responses) mounted on the
  FastAPI app, so it inherits the Phase 8 auth gate and the Phase 13 rate limiter.
* **stdio** through ``python -m app.mcp.stdio_server`` for local, non-Docker IDE setups.
"""

from __future__ import annotations

__all__ = ["MCP_ENDPOINT_PATH", "MCP_PROTOCOL"]

MCP_ENDPOINT_PATH = "/mcp"
MCP_PROTOCOL = "streamable-http"
