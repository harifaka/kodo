"""GitHub OAuth login, session cookie issuance and ``/auth/me``.

Secrets never leave the server: the OAuth client secret and the GitHub access token are used for
one exchange and never logged, persisted or returned. Sessions are HS256 JWTs in an HttpOnly,
SameSite=Lax cookie; API clients may send ``Authorization: Bearer <token>`` instead.
"""

from __future__ import annotations

import hmac
from typing import Any
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from app.auth.dependencies import authenticate_request
from app.auth.jwt_utils import (
    OAUTH_STATE_TOKEN_TYPE,
    create_session_token,
    create_state_token,
    decode_token,
)
from app.config import get_settings
from app.db import repository

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

STATE_COOKIE = "kodo_oauth_state"
SESSION_COOKIE = "kodo_session"
STATE_COOKIE_MAX_AGE = 600

GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_USER_URL = "https://api.github.com/user"
GITHUB_TIMEOUT_SECONDS = 20

# Test seam: pytest swaps this for an ``httpx.MockTransport`` so the suite never touches the network.
_transport: httpx.AsyncBaseTransport | None = None


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=GITHUB_TIMEOUT_SECONDS, transport=_transport)


class AuthModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class AuthUser(AuthModel):
    id: str
    username: str
    display_name: str | None = None
    avatar_url: str | None = None


class AuthMeResponse(AuthModel):
    mode: str
    authenticated: bool
    user: AuthUser | None = None
    # Explicit alias: the default camel generator would produce ``githubOauthConfigured``.
    github_oauth_configured: bool = Field(default=False, alias="githubOAuthConfigured")


class LogoutResponse(AuthModel):
    ok: bool = True


def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


@router.get("/me", response_model=AuthMeResponse)
def auth_me(request: Request) -> AuthMeResponse:
    settings = get_settings()
    user = authenticate_request(request)
    return AuthMeResponse(
        mode=settings.mode,
        authenticated=user is not None,
        user=(
            AuthUser(
                id=user.id,
                username=user.username,
                display_name=user.display_name,
                avatar_url=user.avatar_url,
            )
            if user is not None
            else None
        ),
        github_oauth_configured=settings.github_oauth_configured,
    )


@router.get("/github/login")
def github_login() -> RedirectResponse:
    settings = get_settings()
    if not settings.github_oauth_configured:
        raise _error(
            503,
            "OAUTH_NOT_CONFIGURED",
            "GitHub login is not configured on this server (KODO_GITHUB_CLIENT_ID / "
            "KODO_GITHUB_CLIENT_SECRET are unset).",
        )

    state = create_state_token()
    query = urlencode(
        {
            "client_id": settings.github_client_id,
            "redirect_uri": settings.oauth_redirect_uri,
            "scope": settings.github_scopes,
            "state": state,
            "allow_signup": "true",
        }
    )
    response = RedirectResponse(url=f"{GITHUB_AUTHORIZE_URL}?{query}", status_code=302)
    response.set_cookie(
        STATE_COOKIE,
        state,
        max_age=STATE_COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
    )
    return response


@router.get("/github/callback")
async def github_callback(
    request: Request,
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
) -> RedirectResponse:
    settings = get_settings()
    if not settings.github_oauth_configured:
        raise _error(503, "OAUTH_NOT_CONFIGURED", "GitHub login is not configured on this server.")

    cookie_state = request.cookies.get(STATE_COOKIE, "")
    if not state or not cookie_state or not hmac.compare_digest(state, cookie_state):
        raise _error(
            400,
            "OAUTH_STATE_MISMATCH",
            "The GitHub OAuth state did not match this browser session. Start sign-in again.",
        )
    if decode_token(state, expected_type=OAUTH_STATE_TOKEN_TYPE) is None:
        raise _error(
            400,
            "OAUTH_STATE_MISMATCH",
            "The GitHub OAuth state expired or was tampered with. Start sign-in again.",
        )
    if not code:
        raise _error(400, "OAUTH_MISSING_CODE", "GitHub did not return an authorization code.")

    profile = await _exchange_code(code)
    user = repository.upsert_github_user(
        github_id=str(profile.get("id")),
        username=str(profile.get("login") or "github-user"),
        display_name=_optional_str(profile.get("name")),
        avatar_url=_optional_str(profile.get("avatar_url")),
        email=_optional_str(profile.get("email")),
    )

    token = create_session_token(user.id, user.username)
    response = RedirectResponse(url="/", status_code=302)
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=settings.session_cookie_max_age,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
    )
    response.delete_cookie(STATE_COOKIE, samesite="lax", secure=settings.cookie_secure)
    return response


@router.post("/logout", response_model=LogoutResponse)
def logout() -> JSONResponse:
    settings = get_settings()
    response = JSONResponse(content=LogoutResponse().model_dump(by_alias=True))
    response.delete_cookie(SESSION_COOKIE, samesite="lax", secure=settings.cookie_secure)
    response.delete_cookie(STATE_COOKIE, samesite="lax", secure=settings.cookie_secure)
    return response


async def _exchange_code(code: str) -> dict[str, Any]:
    settings = get_settings()
    try:
        async with _client() as client:
            token_response = await client.post(
                GITHUB_TOKEN_URL,
                headers={"Accept": "application/json"},
                data={
                    "client_id": settings.github_client_id,
                    "client_secret": settings.github_client_secret,
                    "code": code,
                    "redirect_uri": settings.oauth_redirect_uri,
                },
            )
            if token_response.status_code >= 400:
                raise _error(
                    502,
                    "OAUTH_EXCHANGE_FAILED",
                    "GitHub rejected the OAuth code exchange. Try signing in again.",
                )
            try:
                token_payload = token_response.json()
            except ValueError as exc:
                raise _error(
                    502,
                    "OAUTH_EXCHANGE_FAILED",
                    "GitHub returned an unreadable token response. Try signing in again.",
                ) from exc
            access_token = token_payload.get("access_token") if isinstance(token_payload, dict) else None
            if not access_token:
                raise _error(
                    502,
                    "OAUTH_EXCHANGE_FAILED",
                    "GitHub did not return an access token. Try signing in again.",
                )

            user_response = await client.get(
                GITHUB_USER_URL,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/vnd.github+json",
                },
            )
            if user_response.status_code >= 400:
                raise _error(
                    502,
                    "OAUTH_PROFILE_FAILED",
                    "Signed in with GitHub, but the profile could not be read. Try again.",
                )
            try:
                profile = user_response.json()
            except ValueError as exc:
                raise _error(
                    502,
                    "OAUTH_PROFILE_FAILED",
                    "GitHub returned an unreadable profile payload.",
                ) from exc
            if not isinstance(profile, dict) or not profile.get("id"):
                raise _error(
                    502,
                    "OAUTH_PROFILE_FAILED",
                    "GitHub returned an unexpected profile payload.",
                )
            return profile
    except HTTPException:
        raise
    except httpx.HTTPError as exc:
        raise _error(
            502,
            "OAUTH_UPSTREAM_ERROR",
            f"GitHub is unreachable right now ({exc.__class__.__name__}). Try again shortly.",
        ) from exc


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


__all__ = ["router", "AuthMeResponse", "SESSION_COOKIE", "STATE_COOKIE"]
