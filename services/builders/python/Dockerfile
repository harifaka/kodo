# syntax=docker/dockerfile:1
# Kodo ephemeral Python builder (Phase 12).
# Non-root, offline-capable: ruff, mypy, pytest and the FastAPI/Pydantic/SQLAlchemy dependency set
# are pre-installed so `ruff check` / `mypy` / `pytest -q` run with --network=none.
FROM python:3.12-slim

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MYPY_CACHE_DIR=/tmp/.mypy_cache \
    RUFF_CACHE_DIR=/tmp/.ruff_cache

RUN python -m pip install --no-cache-dir \
        ruff==0.8.6 \
        mypy==1.13.0 \
        pytest==8.3.4 \
        httpx==0.28.1 \
        fastapi==0.115.6 \
        uvicorn==0.32.1 \
        pydantic==2.10.4 \
        sqlalchemy==2.0.36

RUN groupadd --system --gid 10001 builder \
    && useradd --system --uid 10001 --gid builder --create-home builder \
    && mkdir -p /workspace /tmp/.mypy_cache /tmp/.ruff_cache \
    && chown -R 10001:10001 /workspace /tmp/.mypy_cache /tmp/.ruff_cache /home/builder

USER builder
WORKDIR /workspace

CMD ["sh", "-c", "ruff check . --output-format concise && mypy --ignore-missing-imports --no-error-summary ."]
