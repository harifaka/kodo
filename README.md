# Kodo

**Architecture Control Center for the Vibe-Coding Era.**
Visualize, audit, safely edit, and containerize modern multi-stack codebases (Spring Boot, C# WPF/ASP.NET, Node.js) — self-hosted locally with `docker compose up --build` or as a cloud SaaS. Kodo is **Docker-first**: one Nginx + React UI, one FastAPI orchestrator and one Roslyn analyzer image.

![License: AGPL-3.0](https://img.shields.io/badge/License-AGPL--3.0-blue.svg)
![Status: Docker-First](https://img.shields.io/badge/Status%20v0.2%20%C2%B7%20Phases%201--7%20delivered-brightgreen.svg)
![Deployment: Docker-First](https://img.shields.io/badge/Deployment-Docker--First%20%C2%B7%20Local%20%2B%20SaaS-blue.svg)

---

## Why Kodo?

AI-assisted ("vibe") coding makes generating code trivial, but keeping architectures clean, understandable, and production-ready is harder than ever. Kodo sits between your codebase and deployment as a **Blueprint -> Audit -> Edit -> Deploy** platform:

- **Single Source of Truth (Core IR):** Stack-agnostic Intermediate Representation of services, classes, business fields, relations, and annotations.
- **Docker-First (Local & SaaS):** One shared React + TypeScript UI served by Nginx alongside the FastAPI orchestrator and the Roslyn analyzer on a single Docker network — the same stack for local self-hosting (`docker compose up --build`) and cloud SaaS. The desktop shell was removed in Phase 7 and versioned images are published to GHCR.
- **Deep AST Analysis:** Uses **Tree-sitter** (Java, TypeScript/JavaScript) via Python FastAPI and **Roslyn** via a dedicated C# ASP.NET Core microservice for accurate C# analysis.
- **Deterministic Pattern Audit:** Six Core-IR rules (layer violations, circular dependencies, god classes, orphans, entities leaked through controllers, missing validation) produce an **Architecture Health Score** with actionable findings — still 100% read-only and zero LLM.
- **Multi-Stack Builder:** Versioned `kodo.blueprint.json` plans render production-shaped vertical slices for **Spring Boot**, **C# WPF (MVVM)** and **Node.js**, self-audited to a 100/100 health score and written through the same guarded, create-only apply pipeline.
- **DeepSeek Architecture Copilot:** OpenAI-compatible client for **DeepSeek Cloud** or air-gapped **Ollama / vLLM** that turns a business spec into a blueprint, proposes fixes for audit findings and implements single methods — always as IR-aware proposals reviewed in the Monaco diff. The LLM never writes to disk.
- **Deploy Studio:** Generates non-root multi-stage `Dockerfile`s, a healthchecked `docker-compose.yml` (PostgreSQL / Redis / RabbitMQ on a `kodo-net` bridge) and a placeholder-only `.env.example` — then controls local Docker (compose up/down, live health, filterable logs), exports Git branches and GitHub PRs, and records every apply/rollback/deploy/Git action in a local append-only audit log.

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
    Core IR | Tree-sitter (Java/TS/JS) | DeepSeek / Ollama (OpenAI-compatible) | Docker
            |
            | Internal HTTP (JSON)
            v
    C# Semantic Analyzer (ASP.NET Core + Roslyn, :5050)
    Deep C# / .NET AST extraction + stateless dry-run patching

    All three images (web + Nginx, api-python, analyzer-csharp) run on one Compose network —
    local and production profiles differ only in configuration, never in architecture.

---

## Quick Start (Phases 1–7, Docker-first)

```powershell
# One command: builds and starts web (Nginx) + api-python + analyzer-csharp
docker compose up --build
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

Scan `/projects` (or `/projects/<subfolder>`) in the UI. `docker-compose.override.yml.example` shows
the extra host mounts and how to expose FastAPI on `:8088` for `/docs`. Production hosts pull the
prebuilt GHCR images instead of building:

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
export all work against a local uvicorn too.

Paste an absolute project path, hit **Scan Project**, and explore the Macro Graph, UML diagram and
read-only Code Inspector. Select a component to draft business-field and annotation edits, then click
**Preview Diff (Dry-Run)** to review the surgical AST patch in a Monaco side-by-side diff. The
**Git Safety & Apply** bar shows whether the working tree is clean, lets you pick which files to write,
and applies them atomically after a SHA-256 freshness check — with a one-click **Undo / Rollback** and
an automatic re-scan. Dirty or non-Git workspaces require an explicit risk confirmation.

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
`~/.kodo/audit.jsonl` and shown in the audit table.

Full instructions, configuration and troubleshooting: [DEV_SETUP.md](DEV_SETUP.md).

---

## Delivered Roadmap (v0.1.0 MVP + Phase 7)

**Phases 1–6 are the v0.1.0 MVP and Phase 7 is the Docker-first delivery** — Kodo now covers the full
**Blueprint → Audit → Safe Edit → Deploy** loop and ships as one container stack.

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
- **Dry-Run Monaco Side-by-Side Diff** for every draft edit, computed in memory with **Tree-sitter byte-offset patching** (Java/TS/JS) and **trivia-preserving Roslyn rewriting** (C#). Hand-written methods and comments stay verbatim.
- **Guarded apply to disk**: read-only Git status inspection, a dirty-tree / non-Git confirmation gate, SHA-256 optimistic concurrency (stale files abort the whole batch), atomic writes that preserve CRLF/LF, and an in-memory rollback snapshot with one-click undo. Applying re-scans the workspace so the graph, UML and health score immediately reflect the saved code.

### Phase 4: Multi-Stack Builder & Pattern Blueprints - Delivered
- Full stack plugin generators for **Spring Boot 3 / Java 21**, **C# WPF (.NET 8, MVVM)** and **Node.js (TypeScript, layered Express)**.
- One-click vertical slice scaffolding: Entity/Model + DTO + Mapper + Repository + Service + Controller (+ unit-test skeleton), with constructor-injected service-to-service dependencies.
- Versionable `kodo.blueprint.json` (schema `1.0`) committed alongside the repo for team PR reviews, loaded back into the Builder.
- Generated files are **self-audited to 100/100** and land on disk only through the guarded apply pipeline: dry-run → Monaco diff → create-only apply (`409 FILE_EXISTS` instead of silent overwrite) → rollback that also prunes the folders it created.

### Phase 5: DeepSeek Architecture Copilot - Delivered
- OpenAI-compatible **DeepSeek** client (cloud API or air-gapped on-prem **Ollama / vLLM**) with a configurable Base URL and optional API key.
- Context-efficient prompting powered by **Core IR** + Audit findings, packed into a hard character budget (no raw codebase dumps, no `node_modules` scraping).
- Workflows: *Business Spec -> Blueprint* (schema-validated with one repair retry), *Audit Error -> Diff Fix*, and *Targeted Method Implementation* — each one returns a normal dry-run plan for the Monaco diff; the LLM has no write access.

### Phase 6: Ready-to-Deploy Docker Studio - Delivered
- Stack-aware, **non-root multi-stage Dockerfiles** (Maven/Temurin 21 JRE, `node:22-alpine`, .NET 8 SDK → `aspnet:8.0-alpine`) with `EXPOSE` and `HEALTHCHECK`; WPF projects get an explicit "desktop app cannot run in Linux" warning plus an optional sidecar/API compose template.
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

## What's Next (v0.2+ Roadmap: Phases 8–10)

Phases 1–7 are delivered. The next chapter is the **multi-tenant, sandbox-verified, hybrid System 1 +
System 2** platform. Phase 7 shipped the Docker-first packaging that everything else builds on. Full
detail and definitions of done: [ROADMAP.md](ROADMAP.md).

| Phase | Focus | Headline |
|---|---|---|
| **8** | SaaS Foundation | GitHub OAuth + JWT sessions, persistent SQLite (local) / PostgreSQL (SaaS) for rollback history, blueprints and user settings, per-user isolated workspaces and audit logs, and a `KODO_MODE=saas` flag that disables arbitrary host-path scanning. |
| **9** | Ephemeral Builder Images | Network-restricted, disposable builder containers (Maven/JDK 21, .NET 8 SDK, Node 22) that compile and unit-test AI-proposed patches before apply or PR export — zero host toolchains. |
| **10** | Laya Decision Layer (System 1 + System 2) | **Laya** — Convai Innovations' Apache-2.0 421M non-autoregressive decision model — runs locally (`/v1/systemone`) to triage audit findings, route work between deterministic AST/Builder paths and DeepSeek, and pre-screen AI diffs; every decision becomes an inspectable ADR. Falls back cleanly to deterministic rules when Laya is offline. |

---

## License

This project is licensed under the **GNU Affero General Public License v3.0 (AGPL-3.0)** — see the [LICENSE](LICENSE) file for details.