"""Alembic environment for Kodo (SQLite locally, PostgreSQL for SaaS).

The connection string is never stored in ``alembic.ini``: it is read from ``KODO_DATABASE_URL`` via
``app.config`` so the CLI and the API process always agree. When the API migrates at startup it
injects its live ``Connection`` through ``config.attributes["connection"]``, which keeps Alembic on
the exact engine (and SQLite pragmas) the application uses.

``render_as_batch`` is enabled on SQLite so operations that need a native ``ALTER TABLE`` (adding or
dropping columns, changing constraints) are emitted as safe table-copy batches.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool
from sqlalchemy.engine import Connection

from app.config import get_settings
from app.db.models import Base

config = context.config
target_metadata = Base.metadata


def _configure_logging() -> None:
    """Honour the ini logging config for CLI runs without touching the API's loggers."""
    if config.config_file_name is None:
        return
    try:
        fileConfig(config.config_file_name, disable_existing_loggers=False)
    except Exception:
        # Logging config must never be the reason a migration fails.
        pass


def _database_url() -> str:
    """Live ``KODO_DATABASE_URL`` (SQLite default, any managed PostgreSQL URL otherwise)."""
    configured = (config.get_main_option("sqlalchemy.url") or "").strip()
    return configured or get_settings().database_url


def _configure(connection: Connection | None = None, url: str | None = None) -> None:
    dialect = connection.dialect.name if connection is not None else _dialect_name(url or "")
    options: dict[str, object] = {
        "target_metadata": target_metadata,
        "compare_type": True,
        "compare_server_default": True,
        "render_as_batch": dialect == "sqlite",
    }
    if connection is not None:
        options["connection"] = connection
    else:
        options["url"] = url
    context.configure(**options)


def _dialect_name(url: str) -> str:
    return url.split(":", 1)[0].split("+", 1)[0].strip().lower()


def run_migrations_offline() -> None:
    """Emit SQL instead of executing it (``alembic upgrade head --sql``)."""
    _configure_logging()
    _configure(url=_database_url())
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations on the injected connection, or build one from ``KODO_DATABASE_URL``."""
    _configure_logging()
    injected = config.attributes.get("connection")
    if isinstance(injected, Connection):
        _configure(connection=injected)
        with context.begin_transaction():
            context.run_migrations()
        return

    section = config.get_section(config.config_ini_section) or {}
    section["sqlalchemy.url"] = _database_url()
    engine = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    try:
        with engine.connect() as connection:
            _configure(connection=connection)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
