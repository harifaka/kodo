"""HTTP surface of the ephemeral builder (Phase 9).

Both verify routes enforce the Phase 8 workspace gate (local containment / SaaS tenant sandbox),
pick only allow-listed stacks and images, run through :mod:`app.builders.runner`, and record a
``verify_build`` audit event for the authenticated user.
"""

from __future__ import annotations

import json
import queue
import threading
from collections.abc import Iterator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.auth.dependencies import CurrentUser
from app.builders.models import (
    BuildError,
    BuilderStatus,
    BuildResult,
    BuildVerifyRequest,
)
from app.builders.runner import (
    detect_build_stack,
    inspect_builder_status,
    run_ephemeral_build,
)
from app.services.audit_log import AUDIT_ACTION_VERIFY_BUILD, record_event
from app.services.paths import enforce_workspace_access

router = APIRouter()

_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    # Nginx must not buffer an event stream.
    "X-Accel-Buffering": "no",
}


@router.get("/api/v1/build/status", response_model=BuilderStatus, tags=["build"])
def build_status(user: CurrentUser) -> BuilderStatus:
    """Report builder enablement, Docker reachability and local image readiness. Never raises."""
    return inspect_builder_status()


@router.post("/api/v1/build/verify", response_model=BuildResult, tags=["build"])
def verify_build(request: BuildVerifyRequest, user: CurrentUser) -> BuildResult:
    """Compile (and optionally test) the staged workspace in a disposable sandbox container."""
    root = enforce_workspace_access(request.root_path, user)
    stack = _resolve_stack(root, request)
    try:
        result = run_ephemeral_build(root, stack, request.patches, run_tests=request.run_tests)
    except BuildError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc

    _record(root, result, len(request.patches))
    return result


@router.post("/api/v1/build/verify/stream", tags=["build"])
def verify_build_stream(request: BuildVerifyRequest, user: CurrentUser) -> StreamingResponse:
    """Same verification with Server-Sent Events: ``event: log`` lines then one ``event: result``."""
    root = enforce_workspace_access(request.root_path, user)
    stack = _resolve_stack(root, request)
    patch_count = len(request.patches)

    def event_stream() -> Iterator[str]:
        events: queue.Queue[tuple[str, object]] = queue.Queue()
        holder: dict[str, BuildResult] = {}
        failure: dict[str, dict[str, str]] = {}

        def on_line(line: str) -> None:
            events.put(("log", line))

        def work() -> None:
            try:
                holder["result"] = run_ephemeral_build(
                    root,
                    stack,
                    request.patches,
                    run_tests=request.run_tests,
                    on_line_callback=on_line,
                )
            except BuildError as exc:
                failure["error"] = exc.payload()
            except Exception as exc:  # pragma: no cover - defensive: stream must always close
                failure["error"] = {"code": "BUILD_FAILED", "message": str(exc)}
            finally:
                events.put(("done", None))

        worker = threading.Thread(target=work, name="kodo-build-stream", daemon=True)
        worker.start()
        try:
            while True:
                kind, value = events.get()
                if kind == "done":
                    break
                yield _sse("log", {"line": value})
        finally:
            worker.join(timeout=5)

        if "error" in failure:
            yield _sse("error", failure["error"])
            return

        result = holder.get("result")
        if result is None:  # pragma: no cover - defensive
            yield _sse("error", {"code": "BUILD_FAILED", "message": "The builder stopped without a result."})
            return

        _record(root, result, patch_count)
        yield _sse("result", result.model_dump(mode="json", by_alias=True))

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers=_SSE_HEADERS)


def _resolve_stack(root, request: BuildVerifyRequest) -> str:
    if request.stack:
        return request.stack
    detected = detect_build_stack(root, request.patches)
    if detected is None:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "UNKNOWN_STACK",
                "message": (
                    "Kodo could not detect a build stack (pom.xml, *.csproj/*.sln, "
                    "package.json/tsconfig.json or pyproject.toml/requirements.txt). Pick a stack "
                    "explicitly or add a project file."
                ),
            },
        )
    return detected


def _record(root, result: BuildResult, patch_count: int) -> None:
    error_count = sum(1 for item in result.diagnostics if item.severity == "error")
    summary = (
        f"{result.stack} sandbox build {result.status} "
        f"({error_count} error(s), exit {result.exit_code}, network={result.network_mode})"
    )
    record_event(
        AUDIT_ACTION_VERIFY_BUILD,
        str(root),
        f"{summary} · {patch_count} proposed file(s) staged",
        files_count=patch_count,
        status=result.status,
    )


def _sse(event: str, payload: dict) -> str:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event}\ndata: {body}\n\n"


__all__ = ["router"]
