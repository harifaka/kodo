"""FastAPI dependencies that resolve the authenticated user from a session JWT."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request

from app.auth.jwt_utils import SESSION_TOKEN_TYPE, decode_token
from app.config import get_settings
from app.db import repository
from app.db.repository import LOCAL_USER_ID, UserRecord

SESSION_COOKIE = "kodo_session"


def _token_from_request(request: Request) -> str | None:
    cookie = request.cookies.get(SESSION_COOKIE)
    if cookie and cookie.strip():
        return cookie.strip()
    header = request.headers.get("Authorization", "")
    if header.lower().startswith("bearer "):
        value = header[7:].strip()
        return value or None
    return None


def authenticate_request(request: Request) -> UserRecord | None:
    """Resolve the request user without raising; used by middleware and ``/auth/me``."""
    token = _token_from_request(request)
    if token:
        claims = decode_token(token, expected_type=SESSION_TOKEN_TYPE)
        subject = claims.get("sub") if claims else None
        if isinstance(subject, str) and subject:
            try:
                user = repository.get_user(subject)
            except Exception:
                user = None
            if user is not None:
                return user

    if get_settings().is_saas:
        return None
    try:
        return repository.get_user(LOCAL_USER_ID)
    except Exception:
        # An unavailable database must not take down local read-only scanning.
        return UserRecord(id=LOCAL_USER_ID, username=LOCAL_USER_ID, display_name="Local User")


def get_current_user(request: Request) -> UserRecord:
    cached = getattr(request.state, "user", None)
    if isinstance(cached, UserRecord):
        return cached

    user = authenticate_request(request)
    if user is None:
        raise HTTPException(
            status_code=401,
            detail={"code": "UNAUTHORIZED", "message": "Sign in with GitHub to use this Kodo instance."},
        )
    request.state.user = user
    return user


CurrentUser = Annotated[UserRecord, Depends(get_current_user)]

__all__ = ["CurrentUser", "SESSION_COOKIE", "authenticate_request", "get_current_user"]
