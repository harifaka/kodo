"""Engine/session bootstrap for SQLite (local) and PostgreSQL (SaaS).

The engine is cached per ``KODO_DATABASE_URL`` and rebuilt when the environment changes, so tests
can point each case at a fresh temporary SQLite file without restarting the process.

Schema creation goes through **Alembic** (``alembic upgrade head``). Databases bootstrapped by the
Phase 8/10 ``Base.metadata.create_all()`` have the tables but no ``alembic_version`` row; they are
stamped at the baseline revision first and then upgraded, so an existing instance upgrades cleanly.
Set ``KODO_DB_AUTO_MIGRATE=false`` to fall back to the legacy ``create_all`` bootstrap.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from alembic.config import Config
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker

from alembic import command
from app.config import MODE_LOCAL, db_auto_migrate, get_settings
from app.db.models import Base

# Revision that matches the Phase 8/10 create_all schema; legacy databases are stamped here.
INITIAL_REVISION = "0001_initial_schema"
ALEMBIC_INI_PATH = Path(__file__).resolve().parents[2] / "alembic.ini"

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


def alembic_config(url: str | None = None) -> Config:
    """Alembic config pinned to this repository's script folder and the live database URL."""
    config = Config(str(ALEMBIC_INI_PATH))
    config.set_main_option("script_location", str(ALEMBIC_INI_PATH.parent / "alembic"))
    if url:
        config.set_main_option("sqlalchemy.url", url)
    return config


def run_migrations(engine: Engine) -> None:
    """Upgrade the database to ``head``, stamping a legacy create_all database at the baseline.

    Fresh databases run ``upgrade`` directly. Existing Phase 8/10 databases (tables present, no
    ``alembic_version``) are stamped at ``0001_initial_schema`` first, so the additive Phase 13
    migration applies without hitting ``table already exists``. Any baseline table the legacy
    database predates (for example a Phase 8 install without the Phase 10 ADR table) is created
    before stamping, because ``create_all`` only adds missing tables and never alters existing ones.
    """
    url = engine.url.render_as_string(hide_password=False)
    config = alembic_config(url)
    with engine.connect() as connection:
        tables = set(inspect(connection).get_table_names())
        legacy = "users" in tables and "alembic_version" not in tables
        # End the implicit read transaction so Alembic owns (and commits) its own transaction.
        connection.rollback()
        config.attributes["connection"] = connection
        if legacy:
            Base.metadata.create_all(connection)
            connection.commit()
            command.stamp(config, INITIAL_REVISION)
        command.upgrade(config, "head")
        connection.commit()


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
            if db_auto_migrate():
                run_migrations(_engine)
            else:
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


__all__ = ["init_db", "reset_engine", "run_migrations", "session_scope"]
