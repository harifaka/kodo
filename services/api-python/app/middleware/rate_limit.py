"""In-memory sliding-window rate limiting for the expensive Kodo endpoints.

Single-instance VPS SaaS does not need Redis: one thread-safe limiter per process enforces each
bucket. The interface (``SlidingWindowRateLimiter.check``) is deliberately small so a shared Redis
backend can be swapped in later without touching the route code.

Buckets (requests per 60s window, all configurable through ``KODO_RL_*`` env vars):

================  ===============================================
``scan``          ``/api/v1/scan``
``clone``         ``/api/v1/git/clone``, ``/api/v1/git/export``
``build``         ``/api/v1/build/verify`` (+ ``/stream``)
``ai``            ``/api/v1/ai/*``, ``/api/v1/decision/*``
``auth``          ``/api/v1/auth/github/*`` (keyed by client IP)
``mcp``           ``/mcp`` (Phase 15 MCP server)
================  ===============================================

Limiting is on by default in ``KODO_MODE=saas`` and off in ``KODO_MODE=local`` unless
``KODO_RATE_LIMIT_ENABLED`` says otherwise.
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.config import (
    RATE_LIMIT_WINDOW_SECONDS,
    rate_limit_enabled,
    rate_limit_per_minute,
    trust_proxy_headers,
)

RATE_LIMITED_CODE = "RATE_LIMITED"

_BUCKET_PREFIXES: tuple[tuple[str, str], ...] = (
    ("/api/v1/scan", "scan"),
    ("/api/v1/git/clone", "clone"),
    ("/api/v1/git/export", "clone"),
    ("/api/v1/build/verify", "build"),
    ("/api/v1/ai", "ai"),
    ("/api/v1/decision", "ai"),
    ("/api/v1/auth/github", "auth"),
    ("/mcp", "mcp"),
)
# Auth routes are unauthenticated by design, so they are keyed by client IP instead of user id.
_IP_BUCKETS = frozenset({"auth"})
_MAX_TRACKED_KEYS = 1024


@dataclass(frozen=True)
class RateLimitDecision:
    """Outcome of one ``check``; allowed requests still expose the remaining budget."""

    bucket: str
    limit: int
    remaining: int
    reset_after: int
    retry_after: int = 0

    @property
    def allowed(self) -> bool:
        return self.retry_after == 0

    def header_pairs(self) -> list[tuple[bytes, bytes]]:
        pairs = [
            (b"x-ratelimit-limit", str(self.limit).encode("ascii")),
            (b"x-ratelimit-remaining", str(max(0, self.remaining)).encode("ascii")),
            (b"x-ratelimit-reset", str(self.reset_epoch()).encode("ascii")),
        ]
        if not self.allowed:
            pairs.append((b"retry-after", str(self.retry_after).encode("ascii")))
        return pairs

    def locked_body(self) -> dict[str, object]:
        return {
            "code": RATE_LIMITED_CODE,
            "message": f"Rate limit exceeded. Try again in {self.retry_after}s.",
            "retryAfterSeconds": self.retry_after,
        }

    def reset_epoch(self) -> int:
        return int(time.time()) + max(0, self.reset_after)


class SlidingWindowRateLimiter:
    """Thread-safe sliding-window counter keyed by ``(bucket, subject)``."""

    def __init__(
        self,
        window_seconds: float = RATE_LIMIT_WINDOW_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.window_seconds = float(window_seconds)
        self._clock = clock
        self._hits: dict[tuple[str, str], deque[float]] = {}
        self._lock = threading.Lock()

    def check(self, bucket: str, subject: str, limit: int) -> RateLimitDecision:
        now = self._clock()
        window_start = now - self.window_seconds
        with self._lock:
            self._sweep(window_start)
            hits = self._hits.get((bucket, subject))
            if hits is None:
                hits = deque()
                self._hits[(bucket, subject)] = hits
            while hits and hits[0] <= window_start:
                hits.popleft()
            if len(hits) >= limit:
                retry_after = max(1, math.ceil(hits[0] + self.window_seconds - now))
                return RateLimitDecision(bucket, limit, 0, retry_after, retry_after)
            hits.append(now)
            reset_after = max(1, math.ceil(hits[0] + self.window_seconds - now))
            return RateLimitDecision(bucket, limit, max(0, limit - len(hits)), reset_after)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()

    def tracked_keys(self) -> int:
        with self._lock:
            return len(self._hits)

    def _sweep(self, window_start: float) -> None:
        if len(self._hits) < _MAX_TRACKED_KEYS:
            return
        stale = [key for key, hits in self._hits.items() if not hits or hits[-1] <= window_start]
        for key in stale:
            self._hits.pop(key, None)


def bucket_for_path(path: str) -> str | None:
    """Map a request path to its rate-limit bucket (or ``None`` when the route is unlimited)."""
    for prefix, bucket in _BUCKET_PREFIXES:
        if path == prefix or path.startswith(prefix + "/"):
            return bucket
    return None


def client_ip(scope: Scope) -> str:
    """Client address, honouring ``X-Forwarded-For`` only when a trusted proxy is configured."""
    if trust_proxy_headers():
        forwarded = _header(scope, b"x-forwarded-for")
        if forwarded:
            first = forwarded.split(",")[0].strip()
            if first:
                return first
    client = scope.get("client")
    return client[0] if client else "unknown"


def rate_limit_subject(scope: Scope, bucket: str) -> str:
    """Authenticated user id where available, client IP for auth routes and anonymous calls."""
    if bucket not in _IP_BUCKETS:
        state = scope.get("state") or {}
        user = state.get("user")
        user_id = getattr(user, "id", None)
        if isinstance(user_id, str) and user_id:
            return f"user:{user_id}"
    return f"ip:{client_ip(scope)}"


def _header(scope: Scope, name: bytes) -> str:
    for key, value in scope.get("headers") or ():
        if key.lower() == name:
            return value.decode("latin-1")
    return ""


class RateLimitMiddleware:
    """ASGI middleware enforcing the buckets above.

    Registered *inside* Kodo's authentication gate, so ``scope["state"]["user"]`` is already
    populated. The limiter instance lives on ``app.state.rate_limiter`` and is replaceable for
    deterministic tests.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http" or not rate_limit_enabled():
            await self.app(scope, receive, send)
            return

        bucket = bucket_for_path(scope.get("path", ""))
        if bucket is None:
            await self.app(scope, receive, send)
            return
        limit = rate_limit_per_minute(bucket)
        if limit <= 0:
            await self.app(scope, receive, send)
            return

        decision = _limiter_for(scope).check(bucket, rate_limit_subject(scope, bucket), limit)
        if not decision.allowed:
            response = JSONResponse(
                status_code=429,
                content=decision.locked_body(),
                headers={key.decode(): value.decode() for key, value in decision.header_pairs()},
            )
            await response(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                forwarded = dict(message)
                forwarded["headers"] = [
                    *(message.get("headers") or []),
                    *decision.header_pairs(),
                ]
                await send(forwarded)
                return
            await send(message)

        await self.app(scope, receive, send_with_headers)


_default_limiter = SlidingWindowRateLimiter()


def _limiter_for(scope: Scope) -> SlidingWindowRateLimiter:
    app = scope.get("app")
    limiter = getattr(getattr(app, "state", None), "rate_limiter", None)
    return limiter if isinstance(limiter, SlidingWindowRateLimiter) else _default_limiter


__all__ = [
    "RATE_LIMITED_CODE",
    "RateLimitDecision",
    "RateLimitMiddleware",
    "SlidingWindowRateLimiter",
    "bucket_for_path",
    "client_ip",
    "rate_limit_subject",
]
