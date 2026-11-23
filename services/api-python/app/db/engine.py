"""Engine/session bootstrap for SQLite (local) and PostgreSQL (SaaS).

The engine is cached per ``KODO_DATABASE_URL`` and rebuilt when the environment changes, so tests
can point each case at a fresh temporary SQLite file without restarting the process.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker

from app.config import MODE_LOCAL, get_settings
from app.db.models import Base

_engine: Engine | None = None
_engine_url: str | None = None
_session_factory: sessionmaker[Session] | None = None
_schema_ready = False
_seeded = False
_lock = threading.RLock()


def _sqlite_database_path(url: str) -> Path | None:
    database = make_url(url).database
    if not database or database == ":memory:":
        return None
    return Path(database)


def _build_engine(url: str) -> Engine:
    if url.startswith("sqlite"):
        database_path = _sqlite_database_path(url)
        if database_path is not None:
            database_path.parent.mkdir(parents=True, exist_ok=True)
        engine = create_engine(
            url,
            connect_args={"check_same_thread": False},
            pool_pre_ping=True,
            future=True,
        )

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_connection: object, _record: object) -> None:
            cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
            try:
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.execute("PRAGMA busy_timeout=5000")
            finally:
                cursor.close()

        return engine
    return create_engine(url, pool_pre_ping=True, future=True)


def _ensure_schema() -> sessionmaker[Session]:
    global _engine, _engine_url, _session_factory, _schema_ready, _seeded
    with _lock:
        url = get_settings().database_url
        if _engine is None or _engine_url != url:
            if _engine is not None:
                _engine.dispose()
            _engine = _build_engine(url)
            _engine_url = url
            _session_factory = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
            _schema_ready = False
            _seeded = False

        if not _schema_ready:
            Base.metadata.create_all(_engine)
            _schema_ready = True

        assert _session_factory is not None
        return _session_factory


def _ensure_seeded() -> None:
    global _seeded
    with _lock:
        factory = _ensure_schema()
        if _seeded:
            return
        if get_settings().mode == MODE_LOCAL:
            from app.db.repository import seed_local_user

            with factory() as session:
                seed_local_user(session)
                session.commit()
        _seeded = True


def init_db() -> None:
    """Create tables and seed the local user. Safe to call on every startup."""
    _ensure_seeded()


@contextmanager
def session_scope() -> Iterator[Session]:
    _ensure_seeded()
    factory = _ensure_schema()
    session = factory()
    try:
        yield session
        session.commit()
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()


def reset_engine() -> None:
    """Drop cached connections; used by tests when ``KODO_DATABASE_URL`` changes."""
    global _engine, _engine_url, _session_factory, _schema_ready, _seeded
    with _lock:
        if _engine is not None:
            _engine.dispose()
        _engine = None
        _engine_url = None
        _session_factory = None
        _schema_ready = False
        _seeded = False


__all__ = ["init_db", "reset_engine", "session_scope"]
