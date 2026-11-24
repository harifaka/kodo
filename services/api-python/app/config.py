"""Runtime configuration (environment driven, no external settings dependency).

Kodo runs in two modes:

* ``KODO_MODE=local`` (default) — zero-friction self-hosting: SQLite on the ``kodo-data`` volume (or
  ``~/.kodo/kodo.db`` outside Docker), a seeded ``local`` user and no OAuth credentials required.
* ``KODO_MODE=saas`` — fail-closed multi-tenancy: a strong ``KODO_JWT_SECRET`` is mandatory, every
  API call needs a session JWT, workspaces are confined to per-user sandboxes and host Docker
  control is disabled.

The database is fully configurable through ``KODO_DATABASE_URL``: SQLite stays the zero-setup
default while any SQLAlchemy URL (for example a managed PostgreSQL such as Supabase, Neon, RDS or
Railway) can be supplied later in ``.env`` without code changes.
"""

from __future__ import annotations

import os
import re
import secrets
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.engine import make_url

MODE_LOCAL = "local"
MODE_SAAS = "saas"
VALID_MODES = (MODE_LOCAL, MODE_SAAS)
MIN_JWT_SECRET_LENGTH = 32

DEFAULT_PUBLIC_URL = "http://localhost:3000"
DEFAULT_JWT_TTL_HOURS = 24
DEFAULT_GITHUB_SCOPES = "read:user user:email"

# Vite dev server origins only. The Docker stack serves the UI same-origin through Nginx, so it
# never needs CORS; extend or replace this list with KODO_CORS_ORIGINS for custom deployments.
DEFAULT_CORS_ORIGINS = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
)

DEFAULT_API_PORT = 8088
MAX_INSPECT_BYTES = 2_000_000
MAX_AUDIT_NODES = 20_000
MAX_AUDIT_RELATIONS = 50_000
# Dry-run patching reads one file into memory and returns proposed text; nothing is written.
MAX_PATCH_BYTES = 2_000_000
# Guarded apply writes at most this many files per atomic batch.
MAX_APPLY_FILES = 200

# Phase 9 ephemeral builders. The images are pre-warmed, non-root and only ever consume a staged
# tar stream: the host workspace is never mounted and the container never sees the real files.
BUILDER_STACKS = ("java", "csharp", "nodejs")
BUILDER_NETWORK_MODES = ("none", "bridge", "host")
DEFAULT_BUILDER_IMAGE_JAVA = "kodo-builder-java:local"
DEFAULT_BUILDER_IMAGE_CSHARP = "kodo-builder-csharp:local"
DEFAULT_BUILDER_IMAGE_NODEJS = "kodo-builder-nodejs:local"
DEFAULT_BUILDER_NETWORK_MODE = "none"
DEFAULT_BUILDER_TIMEOUT_SECONDS = 120
DEFAULT_BUILDER_MEMORY = "1g"
DEFAULT_BUILDER_CPUS = "1"
DEFAULT_BUILDER_PIDS_LIMIT = 256
# Staged snapshot ceiling: a tar stream comfortably above any hand-written project, far below RAM.
MAX_BUILDER_SNAPSHOT_BYTES = 50 * 1024 * 1024
MAX_BUILDER_LOG_BYTES = 256 * 1024


class ConfigurationError(RuntimeError):
    """Raised when the process is configured in a way that cannot be served safely."""


def csharp_analyzer_url() -> str:
    return os.getenv("KODO_CSHARP_URL", "http://localhost:5050").rstrip("/")


def cors_origins() -> list[str]:
    configured = os.getenv("KODO_CORS_ORIGINS")
    if not configured:
        return list(DEFAULT_CORS_ORIGINS)
    return [origin.strip() for origin in configured.split(",") if origin.strip()]


def data_dir() -> Path:
    """Directory that holds the database outside Docker (inside Docker it is ``/data/kodo``)."""
    configured = os.getenv("KODO_DATA_DIR", "").strip()
    if configured:
        return Path(configured).expanduser()
    docker_volume = Path("/data/kodo")
    if docker_volume.is_dir():
        return docker_volume
    return Path.home() / ".kodo"


def _default_database_url() -> str:
    database = data_dir() / "kodo.db"
    # ``sqlite:///`` + absolute POSIX path yields the required four slashes; Windows drive paths
    # (``C:/...``) work with three.
    return f"sqlite:///{database.as_posix()}"


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value >= minimum else default


def _mode() -> str:
    raw = os.getenv("KODO_MODE", MODE_LOCAL).strip().lower()
    return raw if raw in VALID_MODES else MODE_LOCAL


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return default


def builders_enabled() -> bool:
    """Local self-hosting verifies builds by default; SaaS stays opt-in (builder daemon access)."""
    return _env_flag("KODO_BUILDERS_ENABLED", _mode() != MODE_SAAS)


_BUILDER_ENV = {
    "java": ("KODO_BUILDER_IMAGE_JAVA", DEFAULT_BUILDER_IMAGE_JAVA),
    "csharp": ("KODO_BUILDER_IMAGE_CSHARP", DEFAULT_BUILDER_IMAGE_CSHARP),
    "nodejs": ("KODO_BUILDER_IMAGE_NODEJS", DEFAULT_BUILDER_IMAGE_NODEJS),
}


def builder_image(stack: str) -> str:
    entry = _BUILDER_ENV.get(stack)
    if entry is None:
        return ""
    env_name, default = entry
    return os.getenv(env_name, "").strip() or default


def builder_network_mode() -> str:
    """Hardened default is ``none``; only an explicit environment override changes it."""
    raw = os.getenv("KODO_BUILDER_NETWORK_MODE", "").strip().lower()
    return raw if raw in BUILDER_NETWORK_MODES else DEFAULT_BUILDER_NETWORK_MODE


def builder_timeout_seconds() -> int:
    return _env_int("KODO_BUILDER_TIMEOUT_SECONDS", DEFAULT_BUILDER_TIMEOUT_SECONDS, minimum=5)


def builder_memory() -> str:
    """Docker memory limit; validated so a bad env value cannot break ``docker create``."""
    raw = os.getenv("KODO_BUILDER_MEMORY", "").strip().lower()
    return raw if re.fullmatch(r"\d+(?:\.\d+)?[bkmg]?", raw) else DEFAULT_BUILDER_MEMORY


def builder_cpus() -> str:
    raw = os.getenv("KODO_BUILDER_CPUS", "").strip()
    return raw if re.fullmatch(r"\d+(?:\.\d+)?", raw) else DEFAULT_BUILDER_CPUS


def builder_pids_limit() -> int:
    return _env_int("KODO_BUILDER_PIDS_LIMIT", DEFAULT_BUILDER_PIDS_LIMIT, minimum=16)


_ephemeral_jwt_secret: str | None = None


def _ephemeral_secret() -> str:
    """Local mode runs without configuration; the generated secret only lives in this process."""
    global _ephemeral_jwt_secret
    if _ephemeral_jwt_secret is None:
        _ephemeral_jwt_secret = secrets.token_urlsafe(48)
    return _ephemeral_jwt_secret


@dataclass(frozen=True)
class Settings:
    mode: str
    database_url: str
    jwt_secret: str
    jwt_ttl_hours: int
    cookie_secure: bool
    public_url: str
    github_client_id: str
    github_client_secret: str
    github_scopes: str

    @property
    def is_saas(self) -> bool:
        return self.mode == MODE_SAAS

    @property
    def github_oauth_configured(self) -> bool:
        return bool(self.github_client_id and self.github_client_secret)

    @property
    def session_cookie_max_age(self) -> int:
        return self.jwt_ttl_hours * 3600

    @property
    def oauth_redirect_uri(self) -> str:
        return f"{self.public_url}/api/v1/auth/github/callback"


def get_settings() -> Settings:
    """Read the environment on every call so tests and restarts can flip modes without a cache."""
    mode = _mode()
    configured_secret = os.getenv("KODO_JWT_SECRET", "").strip()
    if configured_secret:
        jwt_secret = configured_secret
    elif mode == MODE_SAAS:
        raise ConfigurationError(
            f"KODO_MODE=saas requires KODO_JWT_SECRET with at least {MIN_JWT_SECRET_LENGTH} characters."
        )
    else:
        jwt_secret = _ephemeral_secret()

    public_url = os.getenv("KODO_PUBLIC_URL", DEFAULT_PUBLIC_URL).strip().rstrip("/") or DEFAULT_PUBLIC_URL
    cookie_secure_setting = os.getenv("KODO_COOKIE_SECURE", "auto").strip().lower()
    if cookie_secure_setting in {"true", "1", "yes", "on"}:
        cookie_secure = True
    elif cookie_secure_setting in {"false", "0", "no", "off"}:
        cookie_secure = False
    else:
        cookie_secure = public_url.startswith("https://")

    return Settings(
        mode=mode,
        database_url=os.getenv("KODO_DATABASE_URL", "").strip() or _default_database_url(),
        jwt_secret=jwt_secret,
        jwt_ttl_hours=_env_int("KODO_JWT_TTL_HOURS", DEFAULT_JWT_TTL_HOURS),
        cookie_secure=cookie_secure,
        public_url=public_url,
        github_client_id=os.getenv("KODO_GITHUB_CLIENT_ID", "").strip(),
        github_client_secret=os.getenv("KODO_GITHUB_CLIENT_SECRET", "").strip(),
        github_scopes=os.getenv("KODO_GITHUB_SCOPES", DEFAULT_GITHUB_SCOPES).strip() or DEFAULT_GITHUB_SCOPES,
    )


def validate_startup() -> Settings:
    """Fail fast on unsafe SaaS configuration before the first request is served."""
    settings = get_settings()
    if settings.is_saas and len(settings.jwt_secret) < MIN_JWT_SECRET_LENGTH:
        raise ConfigurationError(
            f"KODO_MODE=saas requires KODO_JWT_SECRET with at least {MIN_JWT_SECRET_LENGTH} characters."
        )
    if not settings.database_url:
        raise ConfigurationError("KODO_DATABASE_URL must not be empty.")
    try:
        make_url(settings.database_url)
    except Exception as exc:
        raise ConfigurationError(f"KODO_DATABASE_URL is not a valid SQLAlchemy URL: {exc}") from exc
    return settings
