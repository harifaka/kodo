"""HS256 JWTs for Kodo sessions and the short-lived GitHub OAuth ``state`` cookie."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt

from app.config import get_settings

ALGORITHM = "HS256"
SESSION_TOKEN_TYPE = "session"
OAUTH_STATE_TOKEN_TYPE = "oauth_state"


def _encode(payload: dict[str, Any], *, ttl: timedelta) -> str:
    now = datetime.now(UTC)
    document = {
        **payload,
        "iat": int(now.timestamp()),
        "exp": int((now + ttl).timestamp()),
    }
    return jwt.encode(document, get_settings().jwt_secret, algorithm=ALGORITHM)


def create_session_token(user_id: str, username: str, *, ttl_hours: int | None = None) -> str:
    settings = get_settings()
    hours = ttl_hours if ttl_hours is not None else settings.jwt_ttl_hours
    return _encode(
        {"sub": user_id, "username": username, "typ": SESSION_TOKEN_TYPE},
        ttl=timedelta(hours=max(1, hours)),
    )


def create_state_token(*, ttl_minutes: int = 10) -> str:
    return _encode(
        {"nonce": secrets.token_urlsafe(24), "typ": OAUTH_STATE_TOKEN_TYPE},
        ttl=timedelta(minutes=max(1, ttl_minutes)),
    )


def decode_token(token: str, *, expected_type: str) -> dict[str, Any] | None:
    """Return validated claims, or ``None`` for any malformed/expired/wrong-type token."""
    if not token:
        return None
    try:
        claims = jwt.decode(
            token,
            get_settings().jwt_secret,
            algorithms=[ALGORITHM],
            options={"require": ["exp", "iat"]},
        )
    except (jwt.InvalidTokenError, ValueError, TypeError):
        return None
    if claims.get("typ") != expected_type:
        return None
    return claims


__all__ = [
    "ALGORITHM",
    "OAUTH_STATE_TOKEN_TYPE",
    "SESSION_TOKEN_TYPE",
    "create_session_token",
    "create_state_token",
    "decode_token",
]
