# syntax=docker/dockerfile:1

# ---- build -------------------------------------------------------------------
# Tree-sitter and the HTTP stack ship manylinux wheels for CPython 3.12; build-essential is only
# there so a missing wheel degrades to a compile instead of failing the image build.
FROM python:3.12-slim AS build

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# ---- docker cli --------------------------------------------------------------
# The Phase 9 builder drives the host daemon through the CLI (mounted socket). Only the static
# client binary is copied — no daemon, no root privileges, no socket by default.
FROM docker:27-cli AS dockercli

# ---- runtime -----------------------------------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    KODO_CSHARP_URL=http://analyzer-csharp:5050 \
    KODO_AUDIT_LOG_PATH=/data/kodo/audit.jsonl \
    KODO_WORKSPACES_DIR=/data/kodo/workspaces

# git backs the read-only working-tree check and the clone/export adapter; curl backs HEALTHCHECK.
# /projects is the optional host bind mount, which may be owned by a different host uid, so it is
# trusted explicitly for the read-only git status inspection.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 kodo \
    && useradd --system --uid 10001 --gid kodo --create-home --home-dir /home/kodo kodo \
    && mkdir -p /data/kodo/workspaces /projects \
    && chown -R kodo:kodo /data/kodo \
    && git config --system --add safe.directory /projects

WORKDIR /app

COPY --from=build --chown=kodo:kodo /opt/venv /opt/venv
COPY --from=dockercli /usr/local/bin/docker /usr/local/bin/docker
# Alembic migrations ship with the image so `docker compose exec api-python alembic upgrade head`
# (and the startup KODO_DB_AUTO_MIGRATE path) works inside the container.
COPY --chown=kodo:kodo alembic.ini ./
COPY --chown=kodo:kodo alembic ./alembic
COPY --chown=kodo:kodo app ./app

# Nothing in the runtime reads packages/core-ir; the schema copies are only used by the test suite.
USER kodo

EXPOSE 8088

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=10 \
    CMD curl -fsS http://127.0.0.1:8088/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8088"]
