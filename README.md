# Kodo

**Architecture Control Center for the Vibe-Coding Era.**
Visualize, audit, safely edit, verify in a sandbox, and containerize modern multi-stack codebases (Spring Boot, C# WPF/ASP.NET, Node.js, Python/FastAPI) — self-hosted locally with `docker compose up --build` or as a cloud SaaS. Kodo is **Docker-first**: one Nginx + React UI, one FastAPI orchestrator, one Roslyn analyzer image and four optional ephemeral builder images.

![License: AGPL-3.0](https://img.shields.io/badge/License-AGPL--3.0-blue.svg)
![Status: SaaS Hardening](https://img.shields.io/badge/Status%20v0.8%20%C2%B7%20Phases%201--13%20delivered-brightgreen.svg)
![Deployment: Docker-First](https://img.shields.io/badge/Deployment-Docker--First%20%C2%B7%20Local%20%2B%20SaaS-blue.svg)

---

## Why Kodo?

AI-assisted ("vibe") coding makes generating code trivial, but keeping architectures clean, understandable, and production-ready is harder than ever. Kodo sits between your codebase and deployment as a **Blueprint -> Audit -> Edit -> Deploy** platform:

- **Single Source of Truth (Core IR):** Stack-agnostic Intermediate Representation of services, classes, business fields, relations, and annotations.
- **Docker-First (Local & SaaS):** One shared React + TypeScript UI served by Nginx alongside the FastAPI orchestrator and the Roslyn analyzer on a single Docker network — the same stack for local self-hosting (`docker compose up --build`) and cloud SaaS. The desktop shell was removed in Phase 7 and versioned images are published to GHCR.
- **Deep AST Analysis:** Uses **Tree-sitter** (Java, TypeScript/JavaScript, **Python**) via Python FastAPI and **Roslyn** via a dedicated C# ASP.NET Core microservice for accurate C# analysis.
- **Deterministic Pattern Audit:** Six Core-IR rules (layer violations, circular dependencies, god classes, orphans, entities leaked through controllers, missing validation) produce an **Architecture Health Score** with actionable findings — still 100% read-only and zero LLM.
- **Multi-Stack Builder:** Versioned `kodo.blueprint.json` plans render production-shaped vertical slices for **Spring Boot**, **C# WPF (MVVM)**, **Node.js** and **Python (FastAPI + Pydantic + SQLAlchemy)**, self-audited to a 100/100 health score and written through the same guarded, create-only apply pipeline.
- **DeepSeek Architecture Copilot:** OpenAI-compatible client for **DeepSeek Cloud** or air-gapped **Ollama / vLLM** that turns a business spec into a blueprint, proposes fixes for audit findings and implements single methods — always as IR-aware proposals reviewed in the Monaco diff. The LLM never writes to disk.
- **Deploy Studio:** Generates non-root multi-stage `Dockerfile`s, a healthchecked `docker-compose.yml` (PostgreSQL / Redis / RabbitMQ on a `kodo-net` bridge) and a placeholder-only `.env.example` — then controls local Docker (compose up/down, live health, filterable logs), exports Git branches and GitHub PRs, and records every apply/rollback/deploy/Git action in a local append-only audit log.
- **Ephemeral Build Verification (Phase 9):** **Verify Build (Sandbox)** compiles — and optionally unit-tests — the exact proposed patches before they reach disk, inside a disposable, non-root, `--network=none` container built from pre-warmed Maven 3.9/JDK 21, .NET 8 SDK, Node 22 or Python 3.12 (ruff/mypy/pytest) images. The workspace is streamed in as an in-memory tar snapshot (never mounted), output streams live into the UI, diagnostics are parsed per compiler, and a failing build can hand its errors to the AI Copilot for a reviewed fix.
- **System 1 Decision Layer (Phase 10):** **Laya** — a local, non-autoregressive 421M decision model — runs over `/v1/systemone` (Ollama or `laya-serve`) to triage audit findings, route work between deterministic AST/Builder paths and DeepSeek (System 2), and pre-screen proposed diffs in milliseconds. Every decision becomes an inspectable, tenant-scoped **ADR** with accept/override feedback and a JSONL training export. It is **advisory only**: it never writes to disk and degrades cleanly to deterministic rules + manual DeepSeek triggers when offline.
- **Dual-Mode Folder Browser & Large-Repo Ergonomics (Phase 11):** a **Browse…** modal lists your real host folders **in place — zero uploads, zero copies** — whether Kodo runs natively (Windows drives, `~`, `/`) or in Docker (the `/projects` mount, with an actionable hint when the mount is still the empty `.kodo-empty` placeholder). Immediate child folders are badged by marker files (`Spring Boot / Java`, `C# / .NET`, `Node.js`, `Python`) with monorepo drill-down. The Macro Graph gains `Ctrl+K` search, layer/stack filter pills, **Issues Only**, and a **1-Hop Focus** mode; the Mermaid UML view renders the same filtered subset and guards diagrams over 60 classes. Browsing is **local-only — always `403` in `KODO_MODE=saas`**.
- **Full Python Stack Support (Phase 12):** Python web apps are a first-class stack end to end. The **Tree-sitter Python** analyzer maps FastAPI `APIRouter`/`FastAPI`, Flask `Blueprint` and Django `APIView`/`views.py` modules onto the Macro Graph as `router` components, plus Pydantic v2 DTOs, SQLAlchemy 2 / Django ORM entities, repositories and services with package-root-aware `import` relations. The deterministic audit recognises Pydantic `Field(...)` validation, Python layer leaks and circular imports; the byte-offset patcher edits attributes and decorators while preserving docstrings and methods; the Builder renders a **FastAPI + Pydantic + SQLAlchemy** vertical slice; Deploy Studio and the pre-warmed `kodo-builder-python` image complete the loop. Verified by scanning Kodo's own `services/api-python`.
- **Production SaaS Hardening (Phase 13):** the database is now **Alembic-managed** — `alembic upgrade head` runs at startup, legacy `create_all()` databases are stamped at the baseline revision and upgraded in place, and `render_as_batch` keeps SQLite `ALTER TABLE` migrations safe. Tenants get **per-user disk quotas** (`500 MB` default), a **per-repo clone cap** (`200 MB`, oversized clones deleted immediately), a **workspace count cap** and **TTL cleanup** of untouched cloned repos with `workspace_ttl_cleanup` audit events. Expensive endpoints (`/scan`, `/git/clone`, `/git/export`, `/build/verify`, `/ai/*`, `/auth/github/*`) are protected by a **sliding-window rate limiter** returning `429 RATE_LIMITED` with `Retry-After` and `X-RateLimit-*` headers, and `docker-compose.saas.yml` adds a **Caddy** TLS ingress plus PostgreSQL for one-command VPS deployment ([docs/SAAS_DEPLOYMENT.md](docs/SAAS_DEPLOYMENT.md)). All of it is **off by default in `KODO_MODE=local`**.

---

## Architecture Overview

Kodo is **Docker-first**: one unified container stack serves both local self-hosting and cloud SaaS.

    Browser  ->  http://localhost:3000  (or your SaaS domain)
            |
            v
    Web image: Nginx + static React/TypeScript bundle (non-root nginx, :8080)
    React Flow (Macro) | Mermaid (UML) | Monaco (Code/Diff)
            |
            | same-origin proxy: /api/ and /health
            v
    Orchestrator API (Python FastAPI, :8088)
    Core IR | Tree-sitter (Java/TS/JS/Python) | DeepSeek / Ollama (OpenAI-compatible) | Docker
    SQLAlchemy (SQLite / PostgreSQL) | GitHub OAuth + JWT sessions (KODO_MODE=saas)
            |
            | Internal HTTP (JSON)
            v
    C# Semantic Analyzer (ASP.NET Core + Roslyn, :5050)
    Deep C# / .NET AST extraction + stateless dry-run patching

    All three images (web + Nginx, api-python, analyzer-csharp) run on one Compose network —
    local and production profiles differ only in configuration, never in architecture.

    Phase 9 adds four optional builder images (java, csharp, nodejs, python) that never join the
    stack: the orchestrator creates a disposable, non-root, --network=none container per verification
    and feeds it an in-memory tar snapshot, so the host workspace is never mounted.

    System 1 / System 2 lane (Phase 10, optional):
      Kodo UI -> POST /api/v1/decision/{triage-audit,route-task,screen-diff}
              -> app/decision (compact <=12 KiB deterministic state + typed questions)
              -> Laya over POST /v1/systemone (ollama | laya-serve, `--profile ai-local`)
              -> advisory answer + ArchitectureDecisionRecord (per user)
              -> System 2 DeepSeek only when Laya's calibrated confidence says so
      Laya never generates text, never writes to disk and never replaces the deterministic gates.

    Local UX lane (Phase 11, local modes only):
      Kodo UI "Browse…" -> GET /api/v1/fs/browse?path=...&showHidden=...
                        -> app/services/fs_browser.py (scandir only; zero-copy, in place)
                        -> roots: KODO_BROWSE_ROOTS | Docker /projects + workspaces | host drives
      Always 403 FS_BROWSE_DISABLED_IN_SAAS in KODO_MODE=saas (gated before authentication).
      Filtered/1-hop IR subsets -> POST /api/v1/mermaid (pure, in-memory) -> UML view.

    SaaS edge lane (Phase 13, `docker-compose.saas.yml`):
      Internet -> Caddy :443 (Let's Encrypt, HSTS, 32 MB bodies, SSE flush_interval -1)
               -> web:8080 (Nginx) -> api-python:8088 -> postgres:5432
      api-python startup: validate config -> `alembic upgrade head` -> seed -> TTL cleanup loop
      Middleware order: auth gate (tenant) -> sliding-window rate limiter -> routes.

---

## Quick Start (Phases 1–13, local + SaaS)

```powershell
# One command: builds and starts web (Nginx) + api-python + analyzer-csharp
docker compose up --build

# Optional: build the four ephemeral builder images (Verify Build)
docker compose --profile builders build

# Optional: run local Laya (System 1) alongside the stack, then pull the model once
docker compose --profile ai-local up -d ollama
docker compose exec ollama ollama pull laya
```

Open **<http://localhost:3000>** — the Nginx image serves the UI and proxies `/api/` and `/health` to
FastAPI on the internal `kodo-net` network, so there is no CORS setup and the same stack works on any
SaaS domain. A green **FastAPI** pill with *Roslyn reachable* confirms the whole chain.

To scan code that lives on the host, point the optional bind mount at it (the container can only see
mounted folders) and restart:

```powershell
# .env next to docker-compose.yml
KODO_LOCAL_PROJECTS_DIR=C:/work
KODO_WEB_PORT=3000
```

Then press **Browse…** in the top bar: it lists `/projects` in place (zero-copy — nothing is uploaded
or copied) with stack badges and monorepo drill-down, and **Select & Scan Current Folder** fills the
path and scans immediately. If `/projects` is still the committed empty placeholder, the modal tells
you exactly which `KODO_LOCAL_PROJECTS_DIR` line to add and to run `docker compose up -d`. Need more
than one mount? Set `KODO_BROWSE_ROOTS=/projects,/mnt/other` (comma-separated, absolute container
paths). `docker-compose.override.yml.example` shows the extra host mounts and how to expose FastAPI on
`:8088` for `/docs`. Production hosts pull the prebuilt GHCR images instead of building:

```powershell
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

### Non-Docker developer workflow (still supported)

```powershell
# 1. C# Roslyn analyzer (stateless container) -> http://localhost:5050
docker compose up -d --build analyzer-csharp

# 2. FastAPI orchestrator -> http://localhost:8088
cd services/api-python
python -m venv .venv ; .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8088

# 3. Web UI -> http://127.0.0.1:5173
cd apps/web ; npm install ; npm run dev
```

In dev the UI defaults to `http://localhost:8088` (override with `VITE_API_BASE_URL`); production
bundles default to same-origin relative paths behind Nginx. Docker Desktop is only needed for the
Roslyn container, the whole-stack mode and the **Deploy** tab; scanning, auditing, editing and Git
export all work against a local uvicorn too. A natively running API can **Browse…** your real
filesystem in place — Windows drive roots (`C:\`, `D:\`, …) or `~` / `/` on POSIX — with no bind
mounts and no copying.

Paste an absolute project path, hit **Scan Project**, and explore the Macro Graph, UML diagram and
read-only Code Inspector. Select a component to draft business-field and annotation edits, then click
**Preview Diff (Dry-Run)** to review the surgical AST patch in a Monaco side-by-side diff. The
**Git Safety & Apply** bar shows whether the working tree is clean, lets you pick which files to write,
and applies them atomically after a SHA-256 freshness check — with a one-click **Undo / Rollback** and
an automatic re-scan. Dirty or non-Git workspaces require an explicit risk confirmation.

Large repositories stay readable: **Ctrl+K** (⌘K) searches components by name, file path and
annotations and centers the canvas on the match, layer/stack pills narrow the view with a live
`Showing N / M components` badge, **Issues Only** keeps just what the audit flagged, and **Focus 1-Hop**
restricts the graph to the selected component plus its direct neighbours. The **UML** tab renders the
same filtered subset (server-side `POST /api/v1/mermaid`) and, above 60 classes, offers 1-hop focus,
issues-only or an explicit **Render Full Diagram Anyway**.

The **Builder** tab scaffolds whole projects: pick a stack, describe slices and business fields (or load
the *Order + Customer + Payment* demo), then **Preview Generated Files (Dry-Run)**. Every generated file
appears in the Monaco diff with a green **NEW** badge and flows through the same guarded apply —
existing paths are never overwritten (`409 FILE_EXISTS`) and rollback deletes the created files and
folders. Toggle **Save kodo.blueprint.json** to commit the versioned plan next to the code; the Builder
reloads it on demand for review.

The **AI Copilot** pill in the top bar configures the provider: **DeepSeek Cloud**
(`https://api.deepseek.com/v1`) or a local OpenAI-compatible server such as **Ollama**
(`http://localhost:11434/v1`) or **vLLM**. The API key lives only in the browser tab's
`sessionStorage` (or server-side `KODO_LLM_*` env vars) and is never written to the repository.
From there: **AI Generate from Spec** in the Builder turns a business description into a blueprint
(validated against the Phase 4 schema, one automatic repair retry), **Fix with AI** on an audit finding
proposes a patch, and **AI Implement** on a method fills in a single method. Every AI result is a normal
dry-run plan — reviewed in the Monaco side-by-side diff and applied (or rolled back) only by you.

The **Deploy** tab packages a workspace for production. Pick the detected (or an explicit) stack, the
app port and any backing services, then **Preview Docker Files (Dry-Run)**. The multi-stage, non-root
`Dockerfile`, `.dockerignore`, healthchecked `docker-compose.yml` and placeholder-only `.env.example`
appear in the same Monaco diff and reach disk only through the guarded apply (existing files require
the **Overwrite existing** toggle and its SHA-256 check; a WPF desktop project gets a warning plus an
optional sidecar/API compose template instead of an unusable Linux image). **Container Control** then
drives `docker compose up -d --build` / `down` with live health badges and a filterable log viewer, and
**Git Export** clones HTTPS GitHub/GitLab repositories into Kodo's own workspaces folder, or branches,
commits and (optionally) opens a pull request with a session-only token. Every action is recorded in
the per-user audit trail (SQLite/PostgreSQL; local mode also mirrors `~/.kodo/audit.jsonl`) and shown
in the audit table.

**Verify before you apply.** The Diff preview and Deploy Studio both carry a **Verify Build
(Sandbox)** bar. It stages the workspace (plus every selected in-memory patch) into a tar stream,
streams it into a disposable container and runs the stack's fixed build command — `mvn -o test-compile`,
`dotnet build -p:EnableWindowsTargeting=true`, `tsc --noEmit` or `ruff check … && mypy …` (add
`Run unit tests` for `mvn test` / `dotnet test` / `vitest run` / `pytest -q`). Containers run as uid
10001 with every capability dropped, `--network=none`, `1g`/`1 CPU`/`256 PIDs` limits and a 120 s
timeout, and are always removed afterwards. The host workspace is never mounted or modified; parsed
diagnostics jump straight to the file, and a failing build can be sent to **Fix Build Errors with AI**,
which returns a normal dry-run patch for the Monaco diff. Build them once with
`docker compose --profile builders build`; see
[DEV_SETUP.md](DEV_SETUP.md#9-ephemeral-builders-phase-9) for the Docker-outside-of-Docker setup.

**Two modes, one stack.** `KODO_MODE=local` (default) is zero-configuration: SQLite on the
`kodo-data` volume and a seeded local user, no OAuth needed. `KODO_MODE=saas` is fail-closed: set a
≥32-character `KODO_JWT_SECRET`, sign in with GitHub, and every workspace is confined to
`KODO_WORKSPACES_DIR/<user_id>/` while host Docker control is disabled. The database is just an env
var — `KODO_DATABASE_URL` accepts SQLite or any PostgreSQL URL (bundled profile or a managed service
such as Supabase/Neon/RDS) so you can choose local or third-party storage later in `.env`.
Host-filesystem browsing is **local-only**: `GET /api/v1/fs/browse` always answers
`403 FS_BROWSE_DISABLED_IN_SAAS` and SaaS keeps the Workspace Switcher / Clone Repo flow.

Schema upgrades are owned by **Alembic** (`KODO_DB_AUTO_MIGRATE=true` by default), so an existing
Phase 8–12 database — SQLite or PostgreSQL — is stamped and upgraded in place on the next start:

```powershell
docker compose exec api-python alembic current      # -> 0002_workspace_size_and_activity (head)
```

SaaS governance defaults (`KODO_QUOTA_ENABLED`, `KODO_RATE_LIMIT_ENABLED`, `KODO_WORKSPACE_TTL_HOURS`,
`KODO_RL_*`) are **off or inert in local mode** and enabled by `docker-compose.saas.yml`:

```powershell
docker compose -f docker-compose.yml -f docker-compose.prod.yml -f docker-compose.saas.yml up -d
```

Production VPS runbook (DNS, secrets, GitHub OAuth, TLS, managed PostgreSQL, backups, Traefik
alternative): [docs/SAAS_DEPLOYMENT.md](docs/SAAS_DEPLOYMENT.md).

Full instructions, configuration and troubleshooting: [DEV_SETUP.md](DEV_SETUP.md).

---

## Delivered Roadmap (v0.1.0 MVP + Phases 7–13)

**Phases 1–6 are the v0.1.0 MVP, Phase 7 is the Docker-first delivery, Phase 8 is the SaaS foundation
(v0.3.0), Phase 9 is the sandbox-verified build loop (v0.4.0), Phase 10 is the advisory System 1
decision layer (v0.5.0), Phase 11 is the local UX / large-repo ergonomics pass (v0.6.0), Phase 12 is
the full Python stack (v0.7.0) and Phase 13 is production SaaS hardening (v0.8.0)** — Kodo now covers
the full **Blueprint → Audit → Safe Edit → Sandbox Verify → Deploy** loop for Java, C#, Node.js
**and Python**, plus a **System 1 → System 2** AI decision path, ships as one container stack for both
local self-hosting and multi-tenant SaaS, can browse your real folders in place from either runtime,
and runs a hardened multi-tenant service behind automatic HTTPS.

### Phase 1: Vibe-Code X-Ray (Read-Only Visualizer) - Delivered
- Stack-agnostic **Core IR** schema (Pydantic + TypeScript + C#).
- Directory scanner with **Tree-sitter** (Java/Spring Boot, TS/JS/Node.js) and **Roslyn** (C#/.NET) microservice.
- Interactive **React Flow** service/layer map, **Mermaid** (`classDiagram`) zoomable UML view, and read-only **Monaco Editor** file inspector.
- Tauri v2 desktop wrapper + local dev orchestration. *(Removed in Phase 7 — Kodo is Docker-first.)*

### Phase 2: Pattern & Vibe-Audit Engine - Delivered
- Deterministic rule engine running on the Core IR (zero LLM required).
- Detects architectural drift and vibe-code anti-patterns: layer violations (e.g., Controller -> Repository), circular dependencies, God Classes, exposed entities, missing validation and orphan components.
- Visual error highlighting on the graph + **Architecture Health Score** panel with file jump-to-line links.

### Phase 3: Real-Life Business Field Editor & Safe Round-Trip - Delivered
- Macro/Micro editing: connect/disconnect relations on the canvas and edit real business fields, types, and annotations (`@Entity`, `@Column`, `[Required]`, etc.) in a keyboard-friendly inspector with stack-aware presets.
- **Dry-Run Monaco Side-by-Side Diff** for every draft edit, computed in memory with **Tree-sitter byte-offset patching** (Java/TS/JS/Python) and **trivia-preserving Roslyn rewriting** (C#). Hand-written methods and comments stay verbatim.
- **Guarded apply to disk**: read-only Git status inspection, a dirty-tree / non-Git confirmation gate, SHA-256 optimistic concurrency (stale files abort the whole batch), atomic writes that preserve CRLF/LF, and an in-memory rollback snapshot with one-click undo. Applying re-scans the workspace so the graph, UML and health score immediately reflect the saved code.

### Phase 4: Multi-Stack Builder & Pattern Blueprints - Delivered
- Full stack plugin generators for **Spring Boot 3 / Java 21**, **C# WPF (.NET 8, MVVM)**, **Node.js (TypeScript, layered Express)** and **Python (FastAPI + Pydantic v2 + SQLAlchemy 2)**.
- One-click vertical slice scaffolding: Entity/Model + DTO + Mapper + Repository + Service + Controller (+ unit-test skeleton), with constructor-injected service-to-service dependencies.
- Versionable `kodo.blueprint.json` (schema `1.0`) committed alongside the repo for team PR reviews, loaded back into the Builder.
- Generated files are **self-audited to 100/100** and land on disk only through the guarded apply pipeline: dry-run → Monaco diff → create-only apply (`409 FILE_EXISTS` instead of silent overwrite) → rollback that also prunes the folders it created.

### Phase 5: DeepSeek Architecture Copilot - Delivered
- OpenAI-compatible **DeepSeek** client (cloud API or air-gapped on-prem **Ollama / vLLM**) with a configurable Base URL and optional API key.
- Context-efficient prompting powered by **Core IR** + Audit findings, packed into a hard character budget (no raw codebase dumps, no `node_modules` scraping).
- Workflows: *Business Spec -> Blueprint* (schema-validated with one repair retry), *Audit Error -> Diff Fix*, and *Targeted Method Implementation* — each one returns a normal dry-run plan for the Monaco diff; the LLM has no write access.

### Phase 6: Ready-to-Deploy Docker Studio - Delivered
- Stack-aware, **non-root multi-stage Dockerfiles** (Maven/Temurin 21 JRE, `node:22-alpine`, `python:3.12-slim`, .NET 8 SDK → `aspnet:8.0-alpine`) with `EXPOSE` and `HEALTHCHECK`; WPF projects get an explicit "desktop app cannot run in Linux" warning plus an optional sidecar/API compose template.
- **`docker-compose.yml`** with selectable PostgreSQL / Redis / RabbitMQ, pinned Alpine images, healthchecks, `depends_on: condition: service_healthy`, a `kodo-net` bridge, named volumes and `${VAR}` interpolation — plus a `.env.example` that only ever holds placeholders.
- **Local Docker control panel:** daemon/CLI status, `compose up -d --build`, `compose down [--volumes]`, container health table and a filterable log viewer (tail clamped, service name validated, `shell=False`, strict root containment and timeouts).
- **SaaS / Git adapter:** shallow clone of HTTPS GitHub/GitLab repositories into `~/.kodo/workspaces` (token passed as a transient `http.extraHeader`, never stored), branch + commit export, and optional GitHub Pull Request creation.
- **Local audit log:** append-only JSONL at `~/.kodo/audit.jsonl` (configurable) recording `apply`, `rollback`, `deploy_up`, `deploy_down`, `git_clone` and `git_export` with redacted summaries — no file contents, no tokens.
- All generated container artifacts ride the Phase 3c pipeline: **Dry-Run → Monaco Diff → guarded Apply → atomic Rollback**.

### Phase 7: Docker-First Packaging & CI/CD - Delivered
- **Tauri wrapper removed** — `apps/web/src-tauri/` and every `@tauri-apps/*` dependency are gone; the browser build is the only frontend.
- **Three multi-stage, non-root images:** `web` (`node:22-alpine` build → `nginxinc/nginx-unprivileged` on :8080 serving the SPA and reverse-proxying `/api/` + `/health`), `api-python` (`python:3.12-slim` build → `/opt/venv` runtime as user `kodo`, with `git`, `curl` and the writable `/data/kodo` volume) and `analyzer-csharp` (`dotnet/sdk:8.0` → `aspnet:8.0-alpine`, non-root).
- **One-command local stack:** `docker compose up --build` starts all three services on `kodo-net` with healthchecks and `depends_on: condition: service_healthy`; `docker-compose.prod.yml` pulls the same images from GHCR and publishes only the web port. `docker-compose.override.yml.example` documents extra host mounts.
- **Same-origin by default:** production bundles use relative `/api/v1/...` paths through Nginx (no CORS, works on any SaaS domain), while `npm run dev` still defaults to `http://localhost:8088`.
- **GitHub Actions:** `ci.yml` runs `pytest` + `ruff`, `dotnet build`, `npm run build` and a matrix Docker build (GHA layer cache) on every push/PR; `docker-publish.yml` publishes semver + `latest` + sha tags for all three images to GHCR on `v*` tags.

---

### Phase 8: SaaS Foundation (GitHub OAuth, Multi-Tenancy & Persistence) - Delivered (v0.3.0)
- **GitHub OAuth + JWT sessions:** `/api/v1/auth/{me,github/login,github/callback,logout}` with signed OAuth `state`, HttpOnly `kodo_session` cookies, and startup rejection of a missing/short `KODO_JWT_SECRET` in SaaS mode.
- **Persistent, configurable database:** SQLAlchemy 2.0 with SQLite (WAL, local default) or PostgreSQL. `KODO_DATABASE_URL` lets you point Kodo at the bundled `--profile saas` Postgres or any managed third-party PostgreSQL later in `.env`.
- **Durable state:** rollback snapshots now persist per user (and survive restarts), plus `workspaces`, `saved_blueprints`, `audit_events` (per-user isolation) and non-secret `user_settings` (API keys are rejected server-side).
- **Fail-closed multi-tenancy:** every workspace route resolves strictly inside `KODO_WORKSPACES_DIR/<user_id>/` (`403 SAAS_PATH_FORBIDDEN` otherwise); Git clones land in the user sandbox; `GET /api/v1/workspaces` + a Workspace Switcher/Clone Repo replace raw host paths; `/deploy/docker/*` returns `403 DOCKER_CONTROL_DISABLED_IN_SAAS` while Docker artifact generation and Git PR export stay active.
- **Tests:** `tests/test_saas_foundation.py` (15 hermetic tests) covers restart-safe rollback, tenant isolation, sandbox deletion, SaaS 401/403 gates and a fully mocked OAuth round-trip.

---

### Phase 9: Ephemeral Builder Images (Sandboxed Compile & Test Verification) - Delivered (v0.4.0)
- **Four pre-warmed, non-root (uid 10001) builder images** in `services/builders/`: Maven 3.9/JDK 21 with a seeded `.m2`, .NET 8 SDK with the NuGet cache (incl. the Windows desktop targeting pack), Node 22 with a shared `typescript`/`vitest`/`express` cache, and Python 3.12 with `ruff`/`mypy`/`pytest` plus FastAPI/Pydantic/SQLAlchemy. Built with `docker compose --profile builders build`; they never run as part of the stack.
- **Zero workspace mutation:** the workspace (plus every selected in-memory patch) is staged into a deterministic tar — `.git`, `node_modules`, `target`, `bin`, `obj`, `.venv`, `__pycache__` skipped, escaping symlinks dropped, 50 MB cap — and streamed into the container with `docker cp -`. The host folder is never mounted and its bytes/mtimes never change.
- **Hardened sandbox:** `--network=none` by default (`KODO_BUILDER_NETWORK_MODE` opt-in), `--cap-drop=ALL`, `--security-opt=no-new-privileges:true`, `--memory=1g`, `--cpus=1`, `--pids-limit=256`, a strict timeout and a guaranteed `docker rm -f` in a `finally` block. Only list-argument subprocesses; the fixed stack commands are the only shell strings.
- **API + streaming UI:** `GET /api/v1/build/status`, `POST /api/v1/build/verify` and an SSE `POST /api/v1/build/verify/stream`; parsed Maven/MSBuild/`tsc` diagnostics; a `verify_build` audit event per user; the `BuildVerificationPanel` in the Diff preview (verify patches before Apply) and Deploy Studio (verify before Git export).
- **AI build-fix loop:** `POST /api/v1/ai/fix-build-errors` reads at most three affected files, sends bounded diagnostics plus an ANSI-free log excerpt, and returns a normal `DryRunResponse` for the Monaco diff — still zero disk writes.
- **Tests + evidence:** `tests/test_builder_verify.py` (39 hermetic cases, Docker CLI and LLM mocked), `pytest` 206 passed / 1 skipped, `ruff`, `npm run build`, `docker compose config`, plus live smoke runs of generated Spring Boot and Node.js projects compiling and unit-testing inside `--network=none` (missing cross-slice DTO imports and strict-property errors in the Phase 4 templates were found and fixed), and the expected Linux-side WPF/XAML warning for the C# image.

---

### Phase 10: Laya Decision Layer (System 1 Triage + System 2 DeepSeek Routing) - Delivered (v0.5.0)
- **Advisory local System 1:** `app/decision/` speaks the standard `/v1/systemone` protocol
  (`{ model, state, questions }` → `{ model, answers, usage }`) against Ollama (`laya`) or
  `laya-serve`, with defensive parsing of the optional `abstain`, `route` and `prediction_set`
  fields. Laya never generates text and never writes to disk.
- **Deterministic, budgeted state:** `state_packer.py` projects the Core IR / patches into a fixed-key
  order state with a hard **12 KiB** ceiling (and a **64 KiB** request ceiling), so Laya's token budget
  and field-order sensitivity are respected. Every `choice` question has <= 12 options with an explicit
  neutral fallback.
- **Three workflows:** **Audit triage** (risk level + suggested route + confidence, up to 15
  deduplicated/prioritised findings), **Task routing** (deterministic AST/Builder vs. DeepSeek
  code/reasoning vs. human review, with abstain/low-confidence escalation) and a **pre-diff safety
  gate** (`pass` / `caution` / `high_risk`, logic-deletion and layer-boundary flags).
- **ADRs + continuous learning:** `architecture_decision_records` stores the compact state, the full
  typed answer distribution, recommendation, confidence and latency per user. The **Decisions (ADR)**
  tab lists them with confidence meters, expandable probability distributions and inline Accept/Override
  feedback; `GET /api/v1/decisions/export-training` emits JSONL for local Laya calibration.
- **Graceful degradation + safety:** when Laya is disabled/offline the routes return HTTP 200 with
  `available: false` and a `SYSTEMONE_*` warning — the deterministic audit, Monaco diff, SHA-256 guarded
  apply and Phase 9 builder verification remain the only gates. Tests:
  `tests/test_decision_layer.py` (34 hermetic cases, `httpx.MockTransport` only); `pytest` 240 passed /
  1 skipped, `ruff`, `npm run build` and `docker compose --profile ai-local config` green.

---

### Phase 11: Local UX, Dual-Mode Folder Browser & Large-Repo Ergonomics - Delivered (v0.6.0)
- **Zero-copy, in-place browsing:** `GET /api/v1/fs/browse?path=…&showHidden=…` lists one directory
  level with `scandir` only — no uploads, no copies, no writes. Roots resolve from an explicit
  `KODO_BROWSE_ROOTS` allow-list, or auto-detect: Docker uses the `/projects` mount (from
  `KODO_LOCAL_PROJECTS_DIR`) plus `KODO_WORKSPACES_DIR`; native runs expose Windows drive roots or
  `~` / `/`. Strict containment rejects `..` and escaping symlinks with
  `403 BROWSE_PATH_OUTSIDE_ROOTS`.
- **SaaS lockout:** `KODO_MODE=saas` answers `403 FS_BROWSE_DISABLED_IN_SAAS` for every browse request —
  gated in the auth middleware *before* authentication — and the Browse button is never rendered.
- **Project badges without an AST:** immediate-child marker detection only (`pom.xml` /
  `build.gradle[.kts]`, `*.csproj` / `*.sln`, `package.json`, `pyproject.toml` / `requirements.txt` /
  `setup.py`, `.git`) plus `hasSubdirectories` for monorepo drill-down. Badges stay marker-only; the
  real Python analyzer arrived in Phase 12. Noise folders (`.git`, `node_modules`, `target`, `bin`, `obj`,
  `.venv`, `venv`, `__pycache__`, `.idea`, `.vscode`, recycle-bin/system folders) are skipped unless
  `showHidden` is set, and listings cap at 500 entries with `truncated: true`.
- **Empty Docker mount helper:** browsing `/projects` while it still holds only the `.kodo-empty` →
  `.gitkeep` placeholder returns `emptyMountHint: true` plus copyable `.env` lines
  (`KODO_LOCAL_PROJECTS_DIR=C:\Projects` / `~/projects`) and the `docker compose up -d` command.
- **Browse modal:** runtime badge (`Docker Mount` / `Local Filesystem`), root pills, Up + breadcrumbs,
  instant folder filter, `Show hidden`, current-folder banner with **Select & Scan Current Folder**, and
  a per-row hover **Scan**. Picking a folder fills the path input and immediately runs `Scan Project`.
- **Large-repo ergonomics:** `Ctrl+K` / `⌘K` search over name, file path and annotations with
  smooth `setCenter` navigation; layer pills (Controller, Service, Repository, Entity, DTO, UI, Other)
  and detected-stack pills; a live `Showing N / M components` badge; **Issues Only**; **Focus 1-Hop**;
  and **Reset Filters**. The UML tab renders the same subset via the stateless
  `POST /api/v1/mermaid` and shows a filtered/1-hop indicator, with a >60-class guard offering 1-hop
  focus, issues-only or **Render Full Diagram Anyway**.
- **Evidence:** `tests/test_fs_browser.py` (12 hermetic cases: SaaS 403 anonymous + authenticated,
  sorted listings/noise skipping, `showHidden`, marker/monorepo detection, drill-down, `..` and
  escaping-link containment via a Windows junction fallback, empty-mount hint, unreadable-child
  tolerance, missing-root 409) plus the subset Mermaid case in `tests/test_mermaid.py`; `pytest`
  **249 passed / 5 skipped**, `ruff check app tests`, `npm run build` and all three
  `docker compose config` variants green.

---

### Phase 12: Full Python Stack Support (FastAPI / Django / Flask) - Delivered (v0.7.0)
- **Tree-sitter Python analyzer** (`services/api-python/app/analyzers/python_analyzer.py`): classes,
  base classes, decorators, typed class attributes (`name: str = Field(...)`,
  `id: Mapped[int] = mapped_column(...)`, Django `models.CharField(...)`), `__init__` dependencies and
  `async def` methods; package-root-aware `import`/`from … import` resolution in `python_imports.py`;
  deterministic layer classification in `python_layers.py`.
- **Routers become first-class graph components.** Module-level `APIRouter`, `FastAPI` and `Blueprint`
  route modules emit a synthetic `router` node (layer `controller`, handlers as methods, route
  decorators as annotations) and `include_router`/`register_blueprint` composition edges — so Kodo's
  own FastAPI app self-scans as **204 components / 252 relations** with 10 router modules and no parse
  warnings.
- **Noise-aware scanning.** `pyproject.toml` / `requirements.txt` / `setup.py` / `*.py` detection;
  `.venv`, `venv`, `__pycache__`, `.pytest_cache`, `.mypy_cache`, `.ruff_cache`, `build`, `dist`,
  `*.egg-info` and `site-packages` are skipped, and `tests/`, `test_*.py`, `*_test.py` and
  `conftest.py` stay out of the architecture graph.
- **Python-aware audit.** `MISSING_VALIDATION` recognises Pydantic `Field(...)`,
  `@field_validator`, `EmailStr` and `constr`; router→repository leakage is `LAYER_VIOLATION`;
  circular imports and god classes reuse the deterministic engine. No new rule ids, no schema churn.
- **Byte-offset Python patching.** `app/patching/python_patcher.py` adds/updates/removes class
  attributes, type hints and decorators, inserts only known imports (`Field`, `mapped_column`,
  `relationship`, `dataclass`, …) and preserves docstrings, methods, comments and line endings. Every
  edit still flows dry-run → Monaco diff → SHA-256 guarded apply → rollback; module-level routers are
  reported as unsupported instead of being rewritten.
- **`python-fastapi` blueprints.** SQLAlchemy 2 model → Pydantic v2 request/response → repository →
  service → `APIRouter` (+ pytest skeleton) plus `pyproject.toml`, `app/db.py` and `app/main.py`;
  generated projects self-audit at **100/100**.
- **Deploy + builder.** A `python:3.12-slim` multi-stage Dockerfile (uid 10001 `kodo`,
  `uvicorn app.main:app`, `urllib` `/health` healthcheck, compose `DATABASE_URL`/`PYTHONUNBUFFERED`)
  and a pre-warmed `kodo-builder-python` image whose fixed commands are
  `ruff check … && mypy …[ && pytest -q]`, with structured ruff/mypy diagnostics in the UI.
- **Evidence:** `tests/test_python_stack.py` (19 hermetic cases), `pytest` **271 passed / 5 skipped**
  (only the environment-dependent Roslyn-container skips), `ruff check app tests`, `npm run build`,
  `dotnet build services/analyzer-csharp` and every `docker compose config` variant green.

---

### Phase 13: Production SaaS Hardening (Migrations, Quotas & Rate Limiting) - Delivered (v0.8.0)
- **Alembic owns the schema.** `services/api-python/alembic.ini` + `alembic/env.py` read
  `KODO_DATABASE_URL` dynamically (or accept the API's live connection), import
  `Base.metadata` from `app.db.models` and enable `render_as_batch` on SQLite. The baseline
  `0001_initial_schema` covers all seven Phase 8/10 tables and `0002_workspace_size_and_activity` adds
  `workspaces.size_bytes` + `workspaces.last_accessed_at` — a real, additive schema evolution.
- **Legacy databases upgrade safely.** `app/db/engine.py::run_migrations` inspects the connection: if
  `users` exists without `alembic_version` (a Phase 8/10 `create_all` database) it stamps
  `0001_initial_schema` first, then runs `upgrade head`. Fresh databases upgrade directly.
  `KODO_DB_AUTO_MIGRATE=false` falls back to `create_all` for exotic setups. The Docker image ships
  `alembic.ini` + `alembic/` so `docker compose exec api-python alembic upgrade head` works.
- **Per-user storage governance.** `app/services/quota.py` measures `<KODO_WORKSPACES_DIR>/<user_id>/`
  with `os.scandir(follow_symlinks=False)`, enforces `KODO_USER_QUOTA_MB` (500),
  `KODO_MAX_CLONE_SIZE_MB` (200), `KODO_MAX_WORKSPACES_PER_USER` (10) and deletes an oversized clone
  immediately (`413 CLONE_SIZE_LIMIT_EXCEEDED` / `WORKSPACE_QUOTA_EXCEEDED`). New endpoints:
  `GET /api/v1/workspaces/storage` and an extended `DELETE /api/v1/workspaces/{id}` that returns the
  updated usage, logs `workspace_delete`, and **only ever removes folders strictly inside the caller's
  sandbox** (local host folders are just forgotten).
- **TTL cleanup.** A cancellable `asyncio` task in the FastAPI lifespan runs
  `cleanup_stale_workspaces` every `KODO_CLEANUP_INTERVAL_MINUTES` (30) in SaaS mode only, removing
  workspaces untouched for `KODO_WORKSPACE_TTL_HOURS` (72) and auditing each removal. Scan, file read,
  apply and Git export all refresh `last_accessed_at`.
- **Sliding-window rate limiting.** `app/middleware/rate_limit.py` adds a thread-safe
  `SlidingWindowRateLimiter` (injectable on `app.state.rate_limiter`) wired inside the auth gate for
  buckets `scan`/`clone`/`build`/`ai`/`auth` with `KODO_RL_*_PER_MIN` defaults, per-user keys (client
  IP for auth), `429 RATE_LIMITED` + `Retry-After`, and `X-RateLimit-Limit/Remaining/Reset` on every
  limited response.
- **TLS deployment.** `deploy/caddy/Caddyfile` (automatic Let's Encrypt, HSTS/nosniff/frame-deny/
  referrer-policy headers, 32 MB bodies, `flush_interval -1` for the SSE build stream),
  `docker-compose.saas.yml` (Caddy + healthchecked PostgreSQL + SaaS defaults, `web` port unpublished)
  and `docs/SAAS_DEPLOYMENT.md` (DNS, secrets, OAuth callback, migrations, managed PostgreSQL,
  backup/restore, Traefik alternative, future GitHub App token flow).
- **Frontend UX.** The Workspace Switcher shows a compact usage bar (`120 / 500 MB · 3/10 repos`),
  per-workspace size and a confirmed trash action; `api.ts` maps `429` and `413`/`507` to readable
  messages.
- **Evidence:** `tests/test_saas_hardening.py` (24 hermetic cases: fresh + legacy Alembic upgrade,
  partial Phase 8 schema convergence, `init_db` migration bootstrap, storage/quota/clone-cap/delete
  isolation, TTL cleanup with host-folder safety, the cancellable cleanup loop, and rate-limit headers,
  per-user buckets, CORS on `429` and the local-mode default). `pytest` **295 passed / 5 skipped**,
  `ruff check app tests`, `npm run build`, `dotnet build services/analyzer-csharp`, and all
  `docker compose config` variants (including the new SaaS overlay) are green.

---

## Roadmap Complete (Phases 1–13 delivered)

All thirteen phases are shipped: the original X-Ray visualizer, deterministic audit, guarded
AST edit/apply/rollback, multi-stack builder, DeepSeek Copilot, Deploy Studio, Docker-first packaging,
SaaS foundation, ephemeral builders, the Laya System 1 decision layer, the local dual-mode folder
browser with large-repo graph ergonomics, full Python stack support (FastAPI / Django / Flask), and
production SaaS hardening (Alembic, quotas, TTL cleanup, rate limiting, TLS deployment).
Full detail and DoD evidence: [ROADMAP.md](ROADMAP.md).

## What's Next (v0.9+ Roadmap: Phases 14–15)

The next evolution track is **planned, not shipped** — it is recorded in [ROADMAP.md](ROADMAP.md) with
unchecked sub-tasks and Definitions of Done, and nothing from it is available in this release.
**Phases 1–13 (v0.8.0) remain the active delivered contract.**

| Phase | Track | What it adds | Status |
| --- | --- | --- | --- |
| **14** | Structured Layered UML/Graph Layout & Diagram Image Export | Layer-grouped Mermaid `classDiagram` `namespace` blocks (Controllers / Services / Repositories / Entities / DTOs / UI / Other) with deterministic ordering inside each group, a compact-vs-full member-density toggle and `TB`/`LR` layout direction; layer-aligned React Flow swimlanes with an **Auto-Arrange** button; one-click **SVG** / high-DPI **PNG** / raw `.mmd` export for both the UML diagram and the Macro Graph, respecting active filters and **1-Hop Focus**, with a light/dark export background. | 📋 Planned |
| **15** | Kodo MCP Server | A standards-compliant **MCP Server** (Streamable HTTP `/mcp` in FastAPI plus an optional local `stdio` bridge) exposing read-only, zero-write tools — `kodo_scan_workspace`, `kodo_audit_workspace`, `kodo_get_component`, `kodo_route_task`, `kodo_screen_diff`, `kodo_dry_run_patch`, `kodo_verify_build` — behind the Phase 8 auth model and Phase 13 rate limits, with copy-paste Cursor / Claude Code setup snippets in the UI and `DEV_SETUP.md`. | 📋 Planned |

Full scope, sub-tasks and Definitions of Done:
[ROADMAP.md → Next Evolution (v0.9+)](ROADMAP.md#next-evolution-v09--structured-diagrams-image-export--mcp-server).

## License

This project is licensed under the **GNU Affero General Public License v3.0 (AGPL-3.0)** — see the [LICENSE](LICENSE) file for details.