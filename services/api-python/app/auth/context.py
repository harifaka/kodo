"""Request-scoped current user id.

Audit logging and persistence helpers can be called from deep inside services, so the authenticated
user travels in a context variable instead of being threaded through every function signature.
"""

from __future__ import annotations

from contextvars import ContextVar, Token

from app.db.repository import LOCAL_USER_ID

_current_user_id: ContextVar[str] = ContextVar("kodo_current_user_id", default=LOCAL_USER_ID)


def set_current_user_id(user_id: str) -> Token[str]:
    return _current_user_id.set(user_id)


def reset_current_user_id(token: Token[str]) -> None:
    _current_user_id.reset(token)


def current_user_id() -> str:
    return _current_user_id.get()


__all__ = ["current_user_id", "reset_current_user_id", "set_current_user_id"]
