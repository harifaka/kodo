"""Local ``stdio`` bridge for the Kodo MCP server.

Run from ``services/api-python``::

    python -m app.mcp.stdio_server

It speaks newline-delimited JSON-RPC 2.0 on stdin/stdout and reuses the exact same tool registry,
argument validation and containment gates as the HTTP transport (always in local-user context, since
a local editor process is the user). Diagnostics, warnings and tracebacks go to **stderr only**:
stdout carries nothing but JSON-RPC responses.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from typing import IO

from app.auth.context import reset_current_user_id, set_current_user_id
from app.db import repository
from app.db.engine import init_db
from app.db.repository import LOCAL_USER_ID, UserRecord
from app.mcp.server import McpServer, parse_payload
from app.mcp.tools import TOOL_SPECS, ToolContext

logger = logging.getLogger("kodo.mcp.stdio")


def local_context() -> ToolContext:
    """Resolve the seeded local user; a missing database degrades to an in-memory identity."""
    try:
        init_db()
    except Exception as exc:
        logger.warning("Database bootstrap failed (%s). ADR-persisting tools will report an error.", exc)

    user: UserRecord | None = None
    try:
        user = repository.get_user(LOCAL_USER_ID)
    except Exception:
        user = None
    return ToolContext(
        user=user or UserRecord(id=LOCAL_USER_ID, username=LOCAL_USER_ID, display_name="Local User")
    )


async def serve(stdin: IO[bytes], stdout: IO[bytes], ctx: ToolContext) -> None:
    """Read one JSON-RPC message per line and write one response per line until EOF."""
    server = McpServer()
    token = set_current_user_id(ctx.user.id)
    try:
        while True:
            line = await asyncio.to_thread(stdin.readline)
            if not line:
                return
            if not line.strip():
                continue

            payload, parse_error = parse_payload(line)
            response: object
            if parse_error is not None:
                response = parse_error
            else:
                response = await server.handle_payload(payload, ctx)

            if response is None:
                continue
            stdout.write(
                (json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
            )
            stdout.flush()
    finally:
        reset_current_user_id(token)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        stream=sys.stderr,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logger.info(
        "Kodo MCP stdio bridge ready (%d read-only tools). stdout carries JSON-RPC only.",
        len(TOOL_SPECS),
    )
    try:
        asyncio.run(serve(sys.stdin.buffer, sys.stdout.buffer, local_context()))
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
