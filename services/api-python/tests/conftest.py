"""Shared pytest configuration.

The local audit log writes to ``~/.kodo/audit.jsonl`` in production; every test run redirects it to
an isolated temporary file so the suite never touches the developer's real audit history.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest


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
