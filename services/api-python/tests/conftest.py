"""Shared pytest configuration.

Every test gets a throwaway SQLite database (``tmp_path/kodo.db``) and a throwaway local audit log,
so the suite never touches the developer's real ``~/.kodo`` state and cases cannot leak rows or
events into each other.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from app.db.engine import reset_engine


@pytest.fixture(autouse=True)
def _isolated_audit_log(tmp_path: Path) -> Iterator[None]:
    previous = os.environ.get("KODO_AUDIT_LOG_PATH")
    os.environ["KODO_AUDIT_LOG_PATH"] = str(tmp_path / "audit.jsonl")
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("KODO_AUDIT_LOG_PATH", None)
        else:
            os.environ["KODO_AUDIT_LOG_PATH"] = previous


@pytest.fixture(autouse=True)
def _isolated_database(tmp_path: Path) -> Iterator[None]:
    keys = (
        "KODO_DATABASE_URL",
        "KODO_MODE",
        "KODO_JWT_SECRET",
        "KODO_JWT_TTL_HOURS",
        "KODO_WORKSPACES_DIR",
        "KODO_COOKIE_SECURE",
        "KODO_PUBLIC_URL",
        "KODO_GITHUB_CLIENT_ID",
        "KODO_GITHUB_CLIENT_SECRET",
    )
    previous = {key: os.environ.get(key) for key in keys}
    os.environ["KODO_DATABASE_URL"] = f"sqlite:///{(tmp_path / 'kodo.db').as_posix()}"
    os.environ["KODO_MODE"] = "local"
    for key in (
        "KODO_JWT_SECRET",
        "KODO_JWT_TTL_HOURS",
        "KODO_COOKIE_SECURE",
        "KODO_PUBLIC_URL",
        "KODO_GITHUB_CLIENT_ID",
        "KODO_GITHUB_CLIENT_SECRET",
    ):
        os.environ.pop(key, None)
    reset_engine()
    try:
        yield
    finally:
        reset_engine()
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
