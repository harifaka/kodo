# Kodo SaaS Deployment (VPS + TLS + PostgreSQL)

Production runbook for a single-VPS `KODO_MODE=saas` deployment: automatic HTTPS through Caddy,
PostgreSQL storage upgraded by Alembic, per-user quotas, TTL cleanup and API rate limiting.

> **Local self-hosting needs none of this.** `docker compose up --build` stays zero-configuration:
> quotas and rate limiting are off, TTL cleanup never runs, and no folder outside
> `KODO_WORKSPACES_DIR` is ever touched.

---

## 1. Prerequisites

| Requirement | Notes |
| --- | --- |
| VPS with Docker Engine 24+ and Docker Compose **2.24+** | `!reset` in the overlays requires 2.24. |
| Public IPv4 (and IPv6 for AAAA) | Ports **80** and **443** must be reachable from the internet. |
| Domain or subdomain | Resolves to the VPS; used for the Let's Encrypt certificate. |
| GitHub OAuth App | Created per deployment (step 3). |

### DNS

Create the records at your DNS provider and wait for propagation (`dig +short kodo.example.com`):

```
A     kodo.example.com   <VPS IPv4>
AAAA  kodo.example.com   <VPS IPv6>   # optional but recommended
```

Caddy needs both 80 (HTTP-01 validation / redirect) and 443 (HTTPS).

---

## 2. Configure `.env`

```bash
git clone https://github.com/harifaka/kodo.git && cd kodo
cp .env.example .env
```

Generate the session secret — **mandatory**, minimum 32 characters, `KODO_MODE=saas` refuses to start
without it:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
# or
openssl rand -hex 32
```

Then set at least these keys in `.env`:

```dotenv
KODO_DOMAIN=kodo.example.com
KODO_PUBLIC_URL=https://kodo.example.com

KODO_MODE=saas
KODO_JWT_SECRET=<paste the generated secret>
KODO_COOKIE_SECURE=true

# Bundled PostgreSQL (docker-compose.saas.yml builds the URL from these).
KODO_POSTGRES_DB=kodo
KODO_POSTGRES_USER=kodo
KODO_POSTGRES_PASSWORD=<strong password>

# GitHub OAuth app (step 3).
KODO_GITHUB_CLIENT_ID=<client id>
KODO_GITHUB_CLIENT_SECRET=<client secret>

# Governance (defaults shown; all optional).
KODO_USER_QUOTA_MB=500
KODO_MAX_CLONE_SIZE_MB=200
KODO_MAX_WORKSPACES_PER_USER=10
KODO_WORKSPACE_TTL_HOURS=72
KODO_CLEANUP_INTERVAL_MINUTES=30
KODO_RL_SCAN_PER_MIN=30
KODO_RL_CLONE_PER_MIN=10
KODO_RL_BUILD_PER_MIN=10
KODO_RL_AI_PER_MIN=20
KODO_RL_AUTH_PER_MIN=20
KODO_RL_MCP_PER_MIN=60
# Phase 15 MCP server: set to false to remove /mcp entirely (answers 404 MCP_DISABLED).
KODO_MCP_ENABLED=true
```

`.env` is git-ignored; never commit real secrets. `.env.example` stays placeholder-only.

---

## 3. GitHub OAuth App

GitHub → **Settings → Developer settings → OAuth Apps → New OAuth App**:

| Field | Value |
| --- | --- |
| Application name | Kodo (or your instance name) |
| Homepage URL | `https://kodo.example.com` |
| Authorization callback URL | `https://kodo.example.com/api/v1/auth/github/callback` |

Copy the client id/secret into `.env` (`KODO_GITHUB_CLIENT_ID`, `KODO_GITHUB_CLIENT_SECRET`). The
callback is derived from `KODO_PUBLIC_URL`, so changing the domain means updating both.

---

## 4. Launch

```bash
# Shorthand used for the rest of this guide — re-declare it after opening a new shell.
COMPOSE="docker compose -f docker-compose.yml -f docker-compose.prod.yml -f docker-compose.saas.yml"
$COMPOSE up -d
```

What the three files do together:

* `docker-compose.yml` — base stack (analyzer-csharp, api-python, web) and local-only extras.
* `docker-compose.prod.yml` — pulls prebuilt GHCR images instead of building locally.
* `docker-compose.saas.yml` — adds **caddy** (TLS ingress) and **postgres**, unpublishes the web port,
  and sets `KODO_MODE=saas` with quotas/rate limiting/migrations enabled.

Caddy obtains the certificate on first boot (a few seconds after DNS resolves). Follow it with:

```bash
$COMPOSE logs -f caddy
$COMPOSE ps
```

### Verify migrations

The API runs `alembic upgrade head` at startup (`KODO_DB_AUTO_MIGRATE=true`). Confirm the schema
revision and that both Phase 13 columns exist:

```bash
$COMPOSE exec api-python alembic current
# -> 0002_workspace_size_and_activity (head)

$COMPOSE exec postgres psql -U kodo -d kodo -c "\d workspaces"
# -> ... size_bytes integer DEFAULT 0, last_accessed_at timestamptz

# Re-run manually after an image upgrade:
$COMPOSE exec api-python alembic upgrade head
```

Existing databases created by Phase 8/10 (`create_all`, no `alembic_version` table) are stamped at
`0001_initial_schema` before upgrading, so the first start on an existing instance is safe.

### Smoke test

```bash
curl -fsS https://kodo.example.com/health | jq
curl -sI https://kodo.example.com | grep -i strict-transport-security
```

---

## 5. Managed PostgreSQL (Supabase / Neon / RDS / Azure)

Point `KODO_DATABASE_URL` at the managed instance and (optionally) stop the bundled `postgres`:

```dotenv
KODO_DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST:5432/DBNAME?sslmode=require
```

Keep `?sslmode=require` — psycopg honours it. Then:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml -f docker-compose.saas.yml up -d
$COMPOSE exec api-python alembic upgrade head
```

The URL is the only thing that changes: every SQLAlchemy/Alembic call reads it dynamically, and
`render_as_batch` is only enabled for SQLite, so PostgreSQL uses native `ALTER TABLE`.

Migrating from the bundled container to managed Postgres:

```bash
# dump (from the VPS)
$COMPOSE exec -T postgres pg_dump -U kodo -Fc kodo > kodo.dump
# restore into the managed instance
pg_restore --no-owner --no-acl -d "postgresql://USER:PASSWORD@HOST:5432/DBNAME?sslmode=require" kodo.dump
```

---

## 6. Backups and restore (bundled PostgreSQL)

Reuse the `$COMPOSE` shorthand from section 4 (or re-declare it) — every command below is then
copy-pasteable:

```bash
cd /opt/kodo
COMPOSE="docker compose -f docker-compose.yml -f docker-compose.prod.yml -f docker-compose.saas.yml"
```

Nightly logical backup via cron on the VPS:

```bash
#!/usr/bin/env bash
# /etc/cron.daily/kodo-backup
set -euo pipefail
cd /opt/kodo
COMPOSE="docker compose -f docker-compose.yml -f docker-compose.prod.yml -f docker-compose.saas.yml"
STAMP="$(date +%F)"
$COMPOSE exec -T postgres pg_dump -U kodo -Fc kodo > "/var/backups/kodo-${STAMP}.dump"
find /var/backups -name 'kodo-*.dump' -mtime +14 -delete
```

Restore:

```bash
$COMPOSE stop api-python
$COMPOSE exec -T postgres dropdb -U kodo --if-exists kodo
$COMPOSE exec -T postgres createdb -U kodo kodo
$COMPOSE exec -T postgres pg_restore -U kodo -d kodo --no-owner < /var/backups/kodo-2026-11-25.dump
$COMPOSE start api-python     # runs `alembic upgrade head` again on boot
```

Also back up the `kodo-data` volume (audit JSONL mirror and, if you stayed on SQLite, the database)
and the `caddy_data` volume only if you must preserve issued certificates.

---

## 7. Traefik alternative

Replace the `caddy` service with Traefik (Caddy is only the default because its Caddyfile is four
lines). The important bits — TLS termination, security headers, SSE without buffering, 32 MB bodies —
map to:

```yaml
  traefik:
    image: traefik:v3.1
    command:
      - --providers.docker=true
      - --providers.docker.exposedbydefault=false
      - --entrypoints.web.address=:80
      - --entrypoints.websecure.address=:443
      - --entrypoints.web.http.redirections.entrypoint.to=websecure
      - --certificatesresolvers.le.acme.email=you@example.com
      - --certificatesresolvers.le.acme.storage=/letsencrypt/acme.json
      - --certificatesresolvers.le.acme.tlschallenge=true
    ports: ["80:80", "443:443"]
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - traefik_data:/letsencrypt
  web:
    labels:
      - traefik.enable=true
      - traefik.http.routers.kodo.rule=Host(`${KODO_DOMAIN}`)
      - traefik.http.routers.kodo.entrypoints=websecure
      - traefik.http.routers.kodo.tls.certresolver=le
      - traefik.http.services.kodo.loadbalancer.server.port=8080
      # Security headers middleware
      - traefik.http.middlewares.kodo-headers.headers.stsSeconds=31536000
      - traefik.http.middlewares.kodo-headers.headers.contentTypeNosniff=true
      - traefik.http.middlewares.kodo-headers.headers.frameDeny=true
      - traefik.http.middlewares.kodo-headers.headers.referrerPolicy=strict-origin-when-cross-origin
      # 32 MB request cap
      - traefik.http.middlewares.kodo-body.buffering.maxRequestBodyBytes=33554432
      - traefik.http.routers.kodo.middlewares=kodo-headers,kodo-body
```

Traefik does not buffer SSE responses by default, so `/api/v1/build/verify/stream` keeps streaming.

---

## 8. Security architecture and private repositories

```
Internet ──TLS──► caddy:443 ──► web:8080 (Nginx, SPA + same-origin /api proxy) ──► api-python:8088
                                                                                     │
                                                        analyzer-csharp:5050 ◄────────┘
                                                                                     │
                                                        postgres:5432 ◄──────────────┘
```

* **Tenant isolation.** In SaaS mode every API call needs a session JWT, workspaces must resolve inside
  `<KODO_WORKSPACES_DIR>/<user_id>/`, and host Docker control plus filesystem browsing are disabled.
* **Storage governance.** Quotas are measured on disk under the user's sandbox, oversized clones are
  deleted immediately (`CLONE_SIZE_LIMIT_EXCEEDED`), and a background sweep removes workspaces
  untouched for `KODO_WORKSPACE_TTL_HOURS`, writing a `workspace_ttl_cleanup` audit event.
* **Abuse protection.** Sliding-window rate limits per bucket (`scan`, `clone`, `build`, `ai`, `auth`,
  `mcp`) return `429 RATE_LIMITED` with `Retry-After` and `X-RateLimit-*` headers.
  `KODO_TRUST_PROXY=true` (set by the SaaS overlay) makes the limiter key auth attempts on the real
  client IP from `X-Forwarded-For`.
* **MCP surface.** The Phase 15 read-only MCP server (`/mcp`) is behind the same authentication gate and
  confined to the caller's sandbox (`SAAS_PATH_FORBIDDEN` for host/foreign paths); it is metered by
  `KODO_RL_MCP_PER_MIN` and can be removed entirely with `KODO_MCP_ENABLED=false`.
* **Secrets.** Git tokens supplied to `/git/clone` and `/git/export` live only in the request: they are
  passed as transient `git -c http.extraHeader=…` arguments, never written to `.git/config`, never
  logged and never stored.

### Private repositories today

Private clones work by pasting a **fine-grained personal access token** into the Workspace Switcher.
It is used for exactly one `git clone` (or push/PR) and then discarded.

### Optional future: GitHub App + encrypted short-lived tokens

The current design deliberately keeps tokens out of the database. A future increment can add
first-class private-repo support without weakening that rule:

1. Register a **GitHub App** with `contents:read`/`contents:write` and `pull_requests:write`, and store
   its private key as a container secret (`app_secret`), never in the database.
2. On demand, mint an **installation token** valid for ~60 minutes for the repositories the user can
   access; cache it in memory keyed by `(installation_id)`.
3. If it must outlive a request, persist only the *encrypted* token with an explicit expiry, using a
   key from `KODO_TOKEN_ENCRYPTION_KEY` (AES-GCM/Fernet); delete on expiry or sign-out.
4. Keep the same audit contract: `git_clone` / `git_export` events record the action, never the token.

Until then, self-hosted SaaS operators can mint installation tokens out of band and paste them as
short-lived PATs.

---

## 9. Upgrades

```bash
git pull
docker compose -f docker-compose.yml -f docker-compose.prod.yml -f docker-compose.saas.yml pull
docker compose -f docker-compose.yml -f docker-compose.prod.yml -f docker-compose.saas.yml up -d
docker compose ... exec api-python alembic current   # expect the newest revision
```

Migrations run automatically on container start; the explicit `alembic current` is the verification
step. Roll back an image with `docker compose ... up -d --force-recreate` after pinning `KODO_TAG`.
