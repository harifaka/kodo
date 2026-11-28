# Kodo - Roadmap

This roadmap tracks the delivery of **Kodo** from a read-only architecture visualizer to a full
Blueprint -> Audit -> Edit -> Deploy platform.

- **Phases 1–6** are shipped as **v0.1.0 (MVP)** — the original, Tauri-era feature set.
- **Phase 7** is shipped as **v0.2.0 (Docker-first)** — one Compose stack for local and SaaS.
- **Phase 8** is shipped as **v0.3.0 (SaaS Foundation)** — GitHub OAuth, multi-tenancy, persistent
  SQLite/PostgreSQL storage and fail-closed `KODO_MODE=saas` isolation.
- **Phase 9** is shipped as **v0.4.0 (Ephemeral Builder Images)** — network-isolated, disposable
  builder containers verify proposed patches before they reach disk or a PR.
- **Phase 10** is shipped as **v0.5.0 (Laya Decision Layer)** — an advisory local System 1 that
  triages findings, routes work between deterministic tools and DeepSeek, pre-screens diffs and records
  every decision as a tenant-scoped ADR.
- **Phase 11** is shipped as **v0.6.0 (Local UX & Large-Repo Ergonomics)** — a local-only,
  zero-copy folder browser for both Docker and native runtimes, plus Macro Graph / UML search,
  filters, Issues Only and 1-hop focus for 100+ component repositories.
- **Phase 12** is shipped as **v0.7.0 (Full Python Stack Support)** — Tree-sitter Python Core IR,
  Python-aware audit, byte-offset patching, a FastAPI/Pydantic/SQLAlchemy generator, a Python deploy
  template and the offline `kodo-builder-python` image.
- **Phase 13** is shipped as **v0.8.0 (Production SaaS Hardening)** — Alembic migrations with safe
  legacy-DB upgrades, per-user disk quotas / clone caps / TTL cleanup, per-bucket API rate limiting and
  a Caddy TLS + PostgreSQL VPS deployment overlay.
- **Phase 14** is shipped as **v0.9.0 (Structured Layered Diagrams & Image Export)** — layer-grouped
  Mermaid `classDiagram` namespaces, layered swimlane Macro Graph auto-arrange and one-click
  SVG / high-DPI PNG / `.mmd` export for both diagrams.
- **Phase 15** is shipped as **v1.0.0 (Kodo MCP Server)** — a standards-compliant, strictly read-only
  **Model Context Protocol** server (stateless Streamable HTTP `/mcp` plus a local `stdio` bridge) with
  seven read-only tools behind the Phase 8 auth model and Phase 13 rate limits.

> **All fifteen phases are complete — Kodo is v1.0.0.** Phase 15 is recorded at the end of this file
> with its Definition-of-Done evidence, next to the Phase 14 delivery.

> **Architectural pivot (post-MVP, delivered in Phase 7).** Kodo is a **Docker-first web
> application**. The **Tauri desktop wrapper has been deleted** (`apps/web/src-tauri/` is gone, no
> `@tauri-apps/*` dependencies, no desktop origins) in favour of one unified container deployment shared
> by local and SaaS. Phases 8–15 are delivered (v0.3.0–v1.0.0); **all fifteen phases of the
> roadmap are complete**. Phases 1–15 below stay as delivered history.

---

## Delivered — v0.1.0 MVP (Phases 1–6)

## Phase 1: Vibe-Code X-Ray (Read-Only Visualizer) ✅
**Goal:** Open any existing multi-stack repository and immediately visualize its architecture with zero risk of modifying source files.

**Status:** Delivered — see [DEV_SETUP.md](DEV_SETUP.md) to run it locally.

- [x] Define canonical **Core IR** schema (`WorkspaceIR`, `ComponentNode`, `ComponentRelation`) shared across Python, C#, and TypeScript.
- [x] Build **C# Semantic Analyzer** microservice (ASP.NET Core + Roslyn) for deep `.cs` / WPF / .NET parsing.
- [x] Build **Python FastAPI Orchestrator** with **Tree-sitter** analyzers for Java (Spring Boot) and TypeScript/JavaScript (Node.js).
- [x] Build shared **React + TypeScript** frontend with:
  - [x] **React Flow** interactive Macro Graph (layer-grouped, color-coded).
  - [x] **Mermaid** (`classDiagram`) zoomable UML preview.
  - [x] **Monaco Editor** read-only Code Inspector.
- [x] Configure minimal **Tauri v2** desktop wrapper for local builds and GitHub Actions CI/CD. *(Removed in Phase 7 — Kodo is Docker-first.)*
- **Definition of Done:** Point Kodo at a real Spring Boot, C#, or Node.js folder and render the interactive graph, UML diagram, and source code inspector in under 3 seconds.

---

## Phase 2: Pattern & Vibe-Audit Engine ✅
**Goal:** Detect architectural drift and common AI-generated ("vibe-code") anti-patterns deterministically on the Core IR (no LLM required).

**Status:** Delivered — read-only and fully deterministic on the Core IR.

- [x] Implement pluggable **IR Rule Engine** in FastAPI (`app/audit`, `@audit_rule` registry).
- [x] Add core architectural rules:
  - [x] Layer violations (e.g., Controller directly calling Repository).
  - [x] Circular dependencies between services or modules.
  - [x] God Classes (excessive fields/methods) and orphan components.
  - [x] Missing DTOs or validation annotations on exposed entities.
- [x] Highlight violations directly on the React Flow graph (red/yellow nodes and edges).
- [x] Add an **Audit Panel** with file jump-to-line links and an overall **Architecture Health Score**.
- **Definition of Done:** Scanning a messy codebase surfaces actionable pattern violations visually on the canvas and in the audit list.

---

## Phase 3: Real-Life Business Field Editor & Safe Round-Trip ✅
**Goal:** Safely edit real business models (fields, types, validations, relations) without overwriting hand-written business logic.

**Status:** Delivered — macro editing, micro field/annotation editing, stateless AST dry-run patching, the Monaco diff, and guarded apply-to-disk with Git safety, SHA-256 optimism and rollback.

- [x] Enable interactive Macro editing (connect/disconnect services and dependencies on the React Flow canvas).
  - [x] Client-side **relation draft** (add/cut) with per-workspace reset and an unsaved-changes indicator.
  - [x] **Live audit preview** via stateless `POST /api/v1/audit`, so the health score and findings react to draft edits instantly.
- [x] Build Micro Inspector for editing business fields, types, and stack-specific annotations (`@Entity`, `@Column`, `@NotNull`, `[Required]`, etc.).
  - [x] Per-node field draft (add/update/remove) plus node annotations, with stack-aware type datalists and annotation presets.
  - [x] Added / modified / removed states are colour-coded, and the same debounced `POST /api/v1/audit` re-scores `GOD_CLASS` / `MISSING_VALIDATION` on field edits.
- [x] Implement **AST Patching** (Roslyn / Tree-sitter targeted edits) to preserve custom methods and business logic.
  - [x] Tree-sitter byte-offset edits for Java fields/annotations/imports and TS/JS properties/decorators.
  - [x] Trivia-preserving Roslyn rewrites behind a stateless C# `POST /patch` endpoint.
- [x] Implement **Dry-Run Engine** paired with **Monaco Side-by-Side Diff** approval before any disk write.
  - [x] `POST /api/v1/dry-run` groups operations by file and returns `originalContent` / `proposedContent` plus an `originalSha256` token without touching disk.
  - [x] Diff Preview tab with per-file change counts, patcher warnings, side-by-side/inline toggle and per-file apply selection.
- [x] Add Git dirty-working-tree safety checks, disk apply and rollback (Phase 3c).
  - [x] Read-only `GET /api/v1/git/status` (`isGitRepo`, `branch`, `isDirty`, `dirtyFiles`, `untrackedCount`, `gitAvailable`, `warning`); never mutates the repository.
  - [x] `POST /api/v1/apply` pre-flight: strict path containment, existing regular file under 2 MB, Git gate (`GIT_DIRTY` / `NOT_A_GIT_REPO` 409 unless explicitly overridden) and SHA-256 optimistic concurrency (`STALE_FILE` 409 aborts the whole batch).
  - [x] Atomic writes (sibling temp file + `os.replace`, UTF-8 without newline translation) with a mid-batch restore, plus a bounded in-memory rollback snapshot of the last 10 applies.
  - [x] `POST /api/v1/apply/rollback` restores the previous bytes, verifying `writtenSha256` first (`force: true` to override).
  - [x] Frontend **Git Safety & Apply bar** (clean/dirty/non-Git pills), per-file checkboxes, risk confirmation modal for dirty/non-Git applies, `STALE_FILE` recovery, and an **Undo / Rollback Last Apply** banner that re-scans automatically.
- **Definition of Done:** Add 3 new business fields and validations via the UI, review and approve the diff in Monaco, apply it safely, and confirm the target project still compiles cleanly. ✅ verified on a git-initialised Spring Boot project: apply changed the file on disk, the re-scan showed the new health score, and rollback restored the exact original bytes with a clean `git status`.

---

## Phase 4: Multi-Stack Builder & Pattern Blueprints ✅
**Goal:** Scaffold new projects and standardized vertical slices across all three target stacks.

**Status:** Delivered — plugin generators, versioned blueprints and create-only scaffolding through the
existing guarded apply pipeline. Every generated project is verified to score **100/100** with 0 errors,
0 warnings and 0 info findings on Kodo's own Phase 2 audit engine.

- [x] Implement stack generator plugins for **Spring Boot 3 / Java 21**, **C# WPF (.NET 8, MVVM)** and **Node.js (TypeScript, layered Express)**.
  - [x] Jinja2 template plugins behind a `StackGeneratorPlugin` protocol + registry (`app/generators/`).
  - [x] Vertical slices: Entity/Model, DTO with validation, Mapper, Repository, Service (constructor DI incl. `dependsOnSlices`), Controller exposing DTOs only, and a unit-test skeleton (`includeTests`).
  - [x] Minimal project skeleton per stack (`includeProjectSkeleton`): `pom.xml` + `Application.java` + `application.yml`, `<Name>.csproj` + `App.xaml(.cs)`, `package.json` + `tsconfig.json` + `src/index.ts`.
- [x] Add one-click **Vertical Slice** templates (e.g., Entity + DTO + Mapper + Repository + Service + Controller + Test skeleton).
  - [x] `POST /api/v1/scaffold/dry-run` renders the whole blueprint into in-memory patches (`isNewFile`, `conflict`, warnings) — nothing is written.
- [x] Support saving and loading versionable `kodo.blueprint.json` files inside the target repository for PR reviews.
  - [x] Versioned schema (`schemaVersion: "1.0"`) in `packages/core-ir/blueprint.schema.json`, Pydantic models and TypeScript types.
  - [x] `GET /api/v1/blueprint?root=…` returns `{ exists, blueprint }` and degrades malformed files to warnings.
  - [x] Saving the blueprint is just another patch in the same guarded apply, so an existing file is updated through the SHA-256 overwrite path.
- [x] Frontend **Builder** tab with stack selector, project/base metadata, slice designer (dependencies, fields, stack-aware types + validation presets), the 3-service demo preset, and a Monaco Diff preview with **NEW** badges.
- [x] Extend guarded apply for create-only patches: `409 FILE_EXISTS` aborts the whole batch, nested folders are created inside the root, rollback deletes created files and prunes the empty folders.
- **Definition of Done:** Design a 3-service architecture visually from scratch and generate a compiling, pattern-compliant multi-stack skeleton. ✅ verified live in the UI: Builder → 25 new files in the Monaco diff → Apply → auto re-scan shows the 3 controller/service/repository/entity graph at 100/100 → Rollback removes all files and folders.

---

## Phase 5: DeepSeek Architecture Copilot ✅
**Goal:** Integrate AI assistance constrained by the Core IR and Audit rules so generated code stays structurally clean.

**Status:** Delivered — OpenAI-compatible client (DeepSeek Cloud + air-gapped Ollama/vLLM), IR context
packing with a hard character budget, and three read-only workflows that all land in the Monaco diff /
Builder for human approval. Zero AI writes: the only writer remains the Phase 3c guarded apply.

- [x] Build an OpenAI-compatible **DeepSeek** client (`deepseek-chat` for code, `deepseek-reasoner` for
      architecture/blueprint) with a configurable Base URL for air-gapped on-prem **Ollama / vLLM**.
  - [x] `app/llm/config.py`: `KODO_LLM_BASE_URL`, `KODO_LLM_API_KEY` (optional for local servers),
        `KODO_LLM_CODE_MODEL`, `KODO_LLM_REASONING_MODEL`, `KODO_LLM_TIMEOUT_SECONDS`, plus per-request
        `llmConfig` overrides from the UI drawer (never persisted or logged).
  - [x] `app/llm/client.py`: async `httpx` `/chat/completions`, JSON-mode with a keyless retry for servers
        that reject `response_format`, strict JSON extraction that strips `<think>…</think>` blocks and
        markdown fences, and structured errors for missing key, 401, 429, timeout and unreachable servers.
  - [x] `POST /api/v1/ai/test-connection` (`GET /models`) drives the settings drawer "Test Connection".
- [x] Implement **IR-based context packing** (compact Core IR + audit findings instead of raw file dumps).
  - [x] `app/llm/context_packer.py`: stacks, health, findings, field/method signatures and relations in a
        deterministic document that never exceeds the character budget (default 24 000, truncated with a
        warning flag), plus a 1-hop focus packer for method implementation.
- [x] Ship 3 core AI workflows:
  - [x] *Business Spec -> Blueprint*: `POST /api/v1/ai/spec-to-blueprint` validates the model output against
        the Phase 4 Pydantic `Blueprint` (slice/field/dependency rules), performs exactly one automatic
        repair retry with the validation error, then returns `422 INVALID_BLUEPRINT` with details.
  - [x] *Audit Error -> Refactor Patch*: `POST /api/v1/ai/audit-fix` reads at most three affected files
        behind the dry-run path containment + 2 MB cap and returns a standard `DryRunResponse` with
        `originalSha256` and an `explanation`.
  - [x] *Targeted Method Implementation*: `POST /api/v1/ai/implement-method` packs the component + direct
        neighbours and returns a single-file `DryRunResponse` for the diff preview.
- [x] Frontend Copilot UX:
  - [x] AI Copilot status pill in the top bar (DeepSeek Cloud / Local On-Prem / Custom / Not Configured)
        and a settings drawer with presets, password-masked API key (sessionStorage only) and Test Connection.
  - [x] Builder "AI Generate from Spec" card that loads the blueprint (plus rationale) for review before any dry-run.
  - [x] "Fix with AI" on every audit finding, and per-method "AI Implement" with an inline instruction box.
  - [x] Every AI proposal opens in the existing Diff Preview (Monaco side-by-side, Git dirty-tree gate,
        SHA-256 optimism, Apply + Rollback) — AI never writes to disk.
- [x] `tests/test_ai_copilot.py` runs the whole surface on `httpx.MockTransport` (no network): packing
      budget/compaction, `<think>`/fence parsing, blueprint validation + repair, audit-fix and
      implement-method dry-runs with exact SHA-256 and untouched disk, path-traversal rejection and
      structured 401/429/timeout/unreachable errors.
- **Definition of Done:** Generate a blueprint from a short business spec and resolve a Phase 2 audit
  violation via DeepSeek + Monaco Diff approval. ✅ verified live against a local OpenAI-compatible
  (Ollama) server: Test Connection listed models, a three-slice blueprint was generated and previewed
  as a 25-file create-only diff, and a "Fix with AI" proposal applied through the guarded pipeline took
  the workspace from 90/100 to 100/100 — rollback restored the original bytes.

---

## Phase 6: Ready-to-Deploy Docker Studio ✅
**Goal:** Package audited, edited projects into production-ready containerized deployments.

**Status:** Delivered — the Deploy Studio generates non-root multi-stage Dockerfiles, a
healthchecked compose stack and a placeholder-only `.env.example` through the same dry-run → Monaco
diff → guarded apply → rollback pipeline, controls local Docker Compose, clones/exports Git branches
and PRs, and records every action in an append-only local audit log.

- [x] Auto-generate optimized multi-stage `Dockerfile`s per stack (non-root users, minimal runtime images).
  - [x] Spring Boot 3 / Java 21: `maven:3.9-eclipse-temurin-21` build → `eclipse-temurin:21-jre-alpine`
        runtime, `EXPOSE 8080`, `HEALTHCHECK` on `/actuator/health`.
  - [x] Node.js / TypeScript: `node:22-alpine` build (`npm run build`) → slim non-root runtime,
        `EXPOSE 3000`, `HEALTHCHECK` on `/health`.
  - [x] C# / .NET 8: `dotnet/sdk:8.0` build → `aspnet:8.0-alpine` runtime, `EXPOSE 8080`,
        `HEALTHCHECK` on `/health`, published-assembly entrypoint.
  - [x] WPF desktop apps: explicit "cannot run in a Linux container" warning plus an optional
        sidecar/API `Dockerfile.sidecar` + compose profile template.
  - [x] Every image creates a `kodo` user/group and drops privileges with `USER kodo`.
- [x] Auto-generate `docker-compose.yml` wiring services, databases (PostgreSQL, Redis, etc.), internal networks, healthchecks, and `.env.example`.
  - [x] Selectable `postgres:16-alpine`, `redis:7-alpine`, `rabbitmq:3.13-alpine` with healthchecks,
        `depends_on: condition: service_healthy`, named volumes and `${VAR}` interpolation.
  - [x] Internal `kodo-net` bridge network and a `.env.example` holding placeholders only.
  - [x] Stack-appropriate `.dockerignore` (VCS, `.env`, `target/`, `node_modules/`, `bin/`, `obj/`, …).
  - [x] `POST /api/v1/deploy/dry-run` returns the standard `DryRunResponse` (`isNewFile`, SHA-256
        overwrite when `overwriteExisting=true`, warnings).
- [x] Add local **Docker Control Panel** (`compose up --build`, live container status, filterable log streaming).
  - [x] `GET /api/v1/deploy/docker/status` (CLI + daemon + compose presence + parsed `compose ps`).
  - [x] `POST /api/v1/deploy/docker/up` / `down` and `GET /api/v1/deploy/docker/logs` (tail clamped to
        1000, service name validated, `shell=False`, timeouts, strict `rootPath` containment).
- [x] Add SaaS/Git adapter mode (GitHub/GitLab clone -> analyze -> open Pull Request) and local audit logging.
  - [x] `POST /api/v1/git/clone`: HTTPS-only URL validation, `--depth 1` clone into
        `KODO_WORKSPACES_DIR`, token passed as a transient `http.extraHeader` (never persisted).
  - [x] `POST /api/v1/git/export`: branch + commit, optional push and GitHub Pull Request via `httpx`.
  - [x] Append-only JSONL audit log (`~/.kodo/audit.jsonl`, `KODO_AUDIT_LOG_PATH`) recording apply,
        rollback, deploy and git actions; `GET /api/v1/audit-log?limit=100` newest first.
- [x] `tests/test_deploy_studio.py`: Dockerfile/compose generation (including the WPF warning), the
      dry-run → apply → rollback cycle, mocked Docker CLI (status/up/down/logs + sanitization), audit
      log recording/retrieval without token leakage, and mocked Git clone URL validation plus export
      with a mocked GitHub PR. All Docker and GitHub calls are mocked — no daemon or network needed.
- **Definition of Done:** Launch a visually built multi-service project in local Docker with one click
  and verify green healthchecks across all services. ✅ Generated stacks validate with
  `docker compose config` (zero syntax errors) on this machine; the Deploy tab previews the files in
  the Monaco diff, applies them atomically and shows live container health/logs with one click.

---

## Post-MVP Roadmap (Docker-First ✅, SaaS Foundation ✅, Ephemeral Builders ✅, System 1/2 AI ✅)

**Direction:** drop the desktop shell, ship one unified Docker stack for both local self-hosting and
cloud SaaS, guarantee build correctness with sandboxed builder images, and add a fast local
**System 1** decision layer (**Laya**) in front of the DeepSeek **System 2** reasoning model.
Phases 7 (Docker-first packaging & CI/CD), 8 (SaaS foundation), 9 (ephemeral builders) and 10 (Laya
decision layer) are delivered.

## Phase 7: Docker-First Packaging & Multi-Stage GitHub Actions CI/CD ✅
**Goal:** One command runs the whole Kodo stack locally, and CI builds/tests/publishes every image.

**Status:** Delivered — `docker compose up --build` starts the full stack behind Nginx on `kodo-net`,
and GitHub Actions verifies every layer and publishes all three images to GHCR.

- [x] Deprecate/remove the Tauri wrapper (`apps/web/src-tauri/`).
  - [x] `apps/web/src-tauri/` deleted, `@tauri-apps/cli` and the `tauri` script removed from
        `apps/web/package.json`, `package-lock.json` regenerated with zero Tauri entries.
  - [x] Tauri origins dropped from `app/config.py` (`KODO_CORS_ORIGINS` still overrides; Vite dev
        origins remain); `vite.config.ts` no longer declares `TAURI_` env prefixes.
- [x] Containerize `api-python` and `apps/web` (Nginx reverse proxy) alongside `analyzer-csharp` into a
      unified `docker-compose.yml` (local & production profiles).
  - [x] `services/api-python/Dockerfile`: `python:3.12-slim` build → non-root `kodo` (uid 10001)
        runtime with `/opt/venv`, `git`, `curl` healthcheck, writable `/data/kodo` volume and
        `KODO_CSHARP_URL` / `KODO_AUDIT_LOG_PATH` / `KODO_WORKSPACES_DIR` defaults; `:8088`.
  - [x] `apps/web/Dockerfile`: `node:22-alpine` (`npm ci` + `npm run build`) →
        `nginxinc/nginx-unprivileged:1.27-alpine` (user `nginx`, :8080) serving `dist/` with SPA
        fallback and proxying `/api/` + `/health` to `api-python:8088` (120 s read timeout, 32 MB
        body limit, `X-Forwarded-*`).
  - [x] `apps/web/src/lib/api.ts` defaults to same-origin relative paths in production builds and keeps
        `http://localhost:8088` for `npm run dev`.
  - [x] `docker-compose.yml`: three services on `kodo-net`, health-gated `depends_on`, `kodo-data`
        volume, `${KODO_LOCAL_PROJECTS_DIR:-./.kodo-empty}:/projects` bind mount and
        `${KODO_WEB_PORT:-3000}`.
  - [x] `docker-compose.prod.yml` pulls `ghcr.io/<owner>/kodo-{web,api-python,analyzer-csharp}:${KODO_TAG}`,
        unpublishes internal ports and sets `restart: unless-stopped`; `docker-compose.override.yml.example`
        and `.env.example` document the local knobs.
- [x] Add GitHub Actions workflows: CI verification (`pytest`, `ruff`, `dotnet build`, `npm run build`)
      and multi-stage Docker builds pushing versioned images to GHCR.
  - [x] `ci.yml`: `python-test` (3.12 + `ruff check app tests` + `pytest`), `csharp-build`,
        `web-build` and a `docker-build-verify` matrix with GHA layer caching (`push: false`).
  - [x] `docker-publish.yml`: `v*` tags + `workflow_dispatch`, `contents: read` / `packages: write`,
        GHCR login with `secrets.GITHUB_TOKEN`, lowercase owner, `docker/metadata-action` semver +
        `latest` + sha tags, `linux/amd64`.
  - [x] Ruff made green: seven pre-existing violations fixed (`B033`, `UP041` ×2, `I001` ×4) and a
        `services/api-python/ruff.toml` pins the lint surface so CI is deterministic.
- **Definition of Done:** Single-command `docker compose up` launches the full Kodo stack locally, and
  GitHub Actions builds and publishes all 3 container images cleanly.
  ✅ Verified on this machine: `pytest` → **153 passed** (the 4 Roslyn conformance tests ran against the
  live analyzer container; they skip when it is offline), `ruff check app tests` → clean,
  `dotnet build services/analyzer-csharp -c Release` → 0 warnings / 0 errors; `npm run build` →
  type-check + bundle OK. `docker compose config` and the `docker-compose.prod.yml` merge validate with
  zero errors; `docker compose up -d --build` built all three images and reported
  `analyzer-csharp`, `api-python` and `web` **healthy** (non-root `app`/`kodo`/`nginx` verified).
  `/health` through Nginx proxies to FastAPI with `csharp.reachable: true`, `/` serves the Kodo UI,
  unknown client routes fall back to `index.html`, and a scan of a mounted Java sample returned the
  expected 3 nodes / 1 relation / 1 `LAYER_VIOLATION` (90/100). *(On the verification host an unrelated
  container already owned `:3000`, so the stack was exercised via `KODO_WEB_PORT=13000` — the default
  remains `3000`.)*

---

## Phase 8: SaaS Foundation (GitHub OAuth, Multi-Tenancy & Persistence) ✅
**Goal:** Real users, real isolation, persistent history — the SaaS foundation.

**Status:** Delivered as **v0.3.0**. `KODO_MODE=local` stays zero-configuration (SQLite + seeded
local user); `KODO_MODE=saas` is fail-closed (JWT required, sandboxed workspaces, no host Docker).

- [x] Implement GitHub OAuth authentication and session/JWT handling.
  - [x] `GET /api/v1/auth/me`, `/auth/github/login` (signed `state` + HttpOnly cookie),
        `/auth/github/callback` (async `httpx` code exchange + user upsert) and `/auth/logout`.
  - [x] HS256 session JWT in an HttpOnly `kodo_session` cookie (or `Authorization: Bearer`);
        `KODO_JWT_SECRET` mandatory (≥32 chars) and startup-rejected when missing in SaaS mode.
  - [x] `LoginScreen` + TopBar user pill (`@username`, avatar, Sign out) and a Local Mode badge.
- [x] Add persistent database storage (SQLite for local / PostgreSQL for SaaS) for rollback history,
      saved blueprints, workspace metadata, and user settings (replacing the in-memory rollback deque).
  - [x] SQLAlchemy 2.0 `app/db/` package with `users`, `workspaces`, `rollback_batches`,
        `audit_events`, `saved_blueprints` and `user_settings` tables; SQLite WAL + PostgreSQL.
  - [x] `KODO_DATABASE_URL` is fully configurable in `.env` — bundled `postgres` Compose profile plus
        any managed PostgreSQL URL (Supabase/Neon/RDS/Railway/Azure) without code changes.
  - [x] Rollback snapshots persist per user (latest 20) and survive container restarts.
  - [x] `GET /api/v1/blueprints`, `GET/PUT /api/v1/user/settings` (API keys rejected).
- [x] Add per-user isolated audit logs (replacing the single shared `~/.kodo/audit.jsonl`) and isolated
      per-user workspace sandboxes.
  - [x] `audit_events` rows are read only by their owner (`GET /api/v1/audit-log`); local mode also
        mirrors to JSONL for self-hosted tooling compatibility.
  - [x] `user_sandbox_root()` + `enforce_workspace_access()` gate every workspace route; symlink/`..`
        escapes and cross-tenant access return `403 SAAS_PATH_FORBIDDEN`.
  - [x] `GET /api/v1/workspaces`, `DELETE /api/v1/workspaces/{id}`, workspace switcher + Clone Repo.
- [x] Enforce `KODO_MODE=saas` vs `local` flag: in SaaS mode, disable arbitrary host-filesystem path
      scanning and allow Git-cloned workspaces only.
  - [x] `/api/v1/deploy/docker/*` returns `403 DOCKER_CONTROL_DISABLED_IN_SAAS`; `/deploy/dry-run`
        keeps generating Docker artifacts inside the user's sandbox.
- **Definition of Done:** Multiple real users can log in with GitHub, scan/edit their own repos in
  strict isolation, and keep rollback/audit history across restarts. ✅ Verified by
  `tests/test_saas_foundation.py` (15 hermetic tests: restart-safe rollback, audit/rollback/workspace
  isolation, sandbox deletion, startup rejection, 401/403 gates, mocked OAuth round-trip,
  blueprint/settings round-trip) with `pytest` (168 passed) and `ruff check app tests` green.

---

## Phase 9: Ephemeral Builder Images (Sandboxed Compile & Test Verification) ✅
**Goal:** Never hand a user code that does not compile — verify inside disposable, network-restricted
containers instead of the host toolchain.

**Status:** Delivered as **v0.4.0**. `POST /api/v1/build/verify` (and the SSE variant) compiles and
optionally unit-tests an in-memory snapshot of the workspace — with proposed patches overlaid — inside a
disposable non-root container. The user's files are never mounted and never modified.

- [x] Three non-root (uid 10001) builder images in `services/builders/` with pre-warmed offline caches:
  - [x] `java/Dockerfile` — `maven:3.9-eclipse-temurin-21-alpine`; `/home/builder/.m2` warmed from a seed
        `pom.xml` that mirrors the Phase 4 Spring Boot 3 template (web, data-jpa, validation, h2, test)
        plus the compiler/surefire/spring-boot plugin artifacts.
  - [x] `csharp/Dockerfile` — `mcr.microsoft.com/dotnet/sdk:8.0-alpine`; NuGet cache warmed with
        `CommunityToolkit.Mvvm`, `xunit`, `Microsoft.NET.Test.Sdk`, `xunit.runner.visualstudio` and the
        Windows desktop targeting pack WPF restore needs (`DOTNET_CLI_TELEMETRY_OPTOUT=1`).
  - [x] `nodejs/Dockerfile` — `node:22-alpine`; `typescript`, `vitest`, `express`, `@types/*`,
        `class-validator`, `class-transformer`, `reflect-metadata` in `/opt/kodo-node-cache`, with
        `NODE_PATH`/`PATH` and an entrypoint that links the cache into a snapshot that has no
        `node_modules`, so `tsc --noEmit` resolves types offline.
  - [x] `docker compose --profile builders build` builds all three (build-only services, `restart: "no"`).
- [x] Hardened sandbox runner (`app/builders/runner.py`): `--network=none` by default, `--cap-drop=ALL`,
      `--security-opt=no-new-privileges:true`, `--memory=1g`, `--cpus=1`, `--pids-limit=256`,
      `--user 10001:10001`, strict `KODO_BUILDER_TIMEOUT_SECONDS` enforcement, and a guaranteed
      `docker rm -f` in a `finally` block. Only list-argument subprocesses (`shell=False`); the only
      `sh -c` strings are fixed constants executed inside the container.
- [x] Zero-mutation staging (`app/builders/staging.py`): deterministic tar of the workspace with
      `node_modules`/`target`/`bin`/`obj`/`.git`/`.venv`/`__pycache__` skipped, escaping symlinks dropped,
      50 MB cap, and patches overlaid in memory behind `resolve_member`/`resolve_new_member`.
- [x] Diagnostic parsing (`app/builders/diagnostics.py`) for Maven (`[ERROR] /workspace/...:[l,c]`),
      MSBuild (`...Foo.cs(l,c): error CS0103: ...`) and `tsc` (both `(l,c)` and `:l:c - error` shapes),
      ANSI-stripped and normalized to workspace-relative paths.
- [x] API surface behind the Phase 8 auth/tenant gate: `GET /api/v1/build/status`,
      `POST /api/v1/build/verify`, `POST /api/v1/build/verify/stream` (SSE `event: log` / `event: result`),
      with `verify_build` events in the per-user `audit_events` table.
- [x] `POST /api/v1/ai/fix-build-errors` — reads at most three affected files (preferring in-flight patch
      content), feeds bounded diagnostics + ANSI-free log excerpt to the configured code model, and
      returns a standard `DryRunResponse` with accurate `originalSha256` and zero disk writes.
- [x] UI: `BuildVerificationPanel` (sandbox verify button, Run-unit-tests toggle, live streaming terminal,
      parsed diagnostics with file jump, AI fix button) embedded in the Diff preview (verify proposed
      patches before Apply) and Deploy Studio (verify the workspace before Git export).
- [x] Deterministic tests (`services/api-python/tests/test_builder_verify.py`, 39 cases): tar overlay with
      unchanged bytes/mtime, traversal rejection, Maven/MSBuild/tsc parsers, hardened flags + tar
      streaming + cleanup on failure/timeout, status/verify/SSE routes, `verify_build` audit rows, SaaS
      403 isolation, and the mocked AI fix workflow.
- **Definition of Done (evidence):** Generated/patched projects compile inside the sandbox with no host
  toolchain. `pytest` 206 passed / 1 skipped and `ruff check app tests` are green, `npm run build` passes,
  `docker compose config` and the prod overlay validate, and live smoke runs verify generated projects
  with `--network=none` while leaving every workspace byte and mtime unchanged:
  - `kodo-builder-nodejs`: Phase 4 TypeScript project → `tsc --noEmit` + `vitest run` (2 tests passed).
  - `kodo-builder-java`: Phase 4 Spring Boot project → `mvn -o test` (2 tests passed).
  - `kodo-builder-csharp`: Phase 4 WPF project → offline restore succeeds, XAML compilation fails on Linux
    exactly as documented, and Kodo reports the explicit WPF/Windows warning instead of a false pass.
  - Docker-first mode: the `api-python` image (shipped Docker CLI + mounted socket) runs the same
    verification from inside Compose and streams a passing result while the mounted workspace stays
    byte- and mtime-identical.
  The live runs also exposed and fixed two real generator defects (missing cross-slice DTO imports in the
  Spring Boot and Node.js service templates, and `strictPropertyInitialization` errors in the Node entity/DTO).

---

## Phase 10: Laya Decision Layer (System 1 Triage + System 2 DeepSeek Routing) ✅
**Goal:** Cheap local intuition (System 1) decides **what** to do and **how risky** it is; DeepSeek
(System 2) is spent only where real reasoning is required.

**Status:** Delivered as **v0.5.0** — advisory System 1 (Laya) over `/v1/systemone`, persisted ADRs with
accept/override feedback, JSONL training export and a documented degradation path when Laya is offline.

- [x] Integrate **Laya** (Convai Innovations, Apache-2.0, 421M non-autoregressive decision model,
      RLCD-calibrated probabilities, zero text generation) via Ollama (`laya`, `/v1/systemone`) or the
      `laya` Python/Ollama runtime as an optional `docker compose --profile ai-local` service.
  - [x] `app/decision/client.py`: async `/v1/systemone` client (`{ model, state, questions }` ->
        `{ model, answers, usage }`) that also reads the optional `laya-serve` fields (`abstain`,
        `route`, `prediction_set`) and maps `SYSTEMONE_DISABLED` / `_UNREACHABLE` / `_TIMEOUT` /
        `_UNAUTHORIZED` / `_INVALID_RESPONSE`.
  - [x] `docker-compose.yml` gains an `ollama/ollama:latest` service under `profiles: ["ai-local"]`
        with a `kodo-ollama` model volume, healthcheck and `kodo-net` networking; the API reads
        `KODO_SYSTEMONE_BASE_URL` (default `http://ollama:11434` in Compose, `http://localhost:11434`
        outside Docker).
- [x] Design strict typed decision schemas (`choice` <= 20 options, `yes/no`, `score` rubrics) operating
      on compact Core IR + Audit state in a single forward pass (~10–33 ms):
  - [x] **Audit Triage & Risk Scoring:** rank findings by real architectural risk vs. benign boilerplate.
  - [x] **System 1 -> System 2 Router:** use Laya's calibrated probabilities and confidence thresholds to
        route tasks between deterministic AST/Builder paths (zero cloud tokens) vs. escalating complex
        refactors to DeepSeek (System 2) or human review.
  - [x] **Pre-Diff Safety Gate:** fast multi-question check on AI-proposed patches (layer boundary check,
        business-logic deletion risk, pattern conformance) before presenting to the user — always
        advisory alongside deterministic audit and Monaco Diff, never the sole gate.
  - [x] Every `choice` question has <= 12 options (well under the ceiling) with an explicit neutral
        fallback; `state_packer.py` builds a fixed-key-order state (finding/task/diff projections) and
        clamps it to **12 KiB**, with the whole request capped at **64 KiB** and never sorted by key.
- [x] Record decisions as inspectable **Architecture Decision Records (ADRs)** in the Phase 8 DB, with
      user accept/override feedback to support Laya's local continuous learning on team architectural
      preferences.
  - [x] `architecture_decision_records` table (user-scoped) storing the compact state, full typed answer
        distribution, recommendation, confidence, latency and feedback.
  - [x] `GET /api/v1/decisions`, `POST /api/v1/decisions/{id}/feedback` (with a `decision_feedback`
        audit event) and `GET /api/v1/decisions/export-training` (JSONL ready for local calibration).
  - [x] UI: `Decisions (ADR)` tab with the **Route a Task (S1 -> S2)** quick input, confidence meters,
        expandable probability distributions, inline Accept/Override and the training export button.
- [x] Graceful degradation: if local Laya/Ollama is offline, Kodo falls back cleanly to deterministic
      rules + manual DeepSeek triggers.
  - [x] Triage/screen routes answer HTTP 200 with `available: false`, an empty item list and a
        `SYSTEMONE_*` warning; the router returns a safe `human_review` recommendation. No scan, audit
        or diff is ever blocked by System 1.
- **Definition of Done (evidence):** Local Laya runs alongside Kodo via `/v1/systemone`, triages real
  repo scans in milliseconds with calibrated confidence scores, routes tasks between deterministic tools
  and DeepSeek, and logs explainable ADRs.
  - `tests/test_decision_layer.py` (34 hermetic cases, `httpx.MockTransport` only): deterministic state
    key order + 12 KiB clamping, client parsing/abstain/timeout/unreachable/unauthorized parsing,
    all three workflows persisting tenant-scoped ADRs with zero workspace byte changes, <= 15-finding
    triage cap and finding filters, low-confidence/abstain escalation, the advisory `pass`/`caution`/
    `high_risk` verdicts, accept/override feedback + audit event, JSONL training export, cross-tenant
    404/empty-list isolation and the SaaS sandbox 403 gate. `pytest` **240 passed / 1 skipped** and
    `ruff check app tests` are green, `npm run build` passes, and
    `docker compose --profile ai-local config` validates.
  - Security posture unchanged: System 1 is advisory, never writes to disk, and every ADR is scoped by
    `user_id`; the deterministic audit, Monaco diff, SHA-256 apply and Phase 9 builder verification
    remain the only gates.

---

## Phase 11: Local UX, Dual-Mode Folder Browser & Large-Repo Ergonomics ✅

**Status:** Delivered — v0.6.0. Local-only zero-copy browsing in both local runtimes, plus Macro Graph
and UML ergonomics that keep 100+ component repositories usable.

**Goal:** Make pointing Kodo at a real workspace on the user's own machine a one-click, zero-copy
experience in **both** local runtimes (Docker and native), and keep the Macro Graph / UML readable on
large repositories.

- [x] Add a local-only, **zero-copy (in-place)** server-side directory browser API
      (`GET /api/v1/fs/browse`) that operates directly on real workspace directories without uploading
      or copying files — strictly disabled in `KODO_MODE=saas` (`403`).
  - [x] `app/services/fs_browser.py` + `app/api/fs_routes.py`: one `scandir` level per request, no
        file bytes read, no writes. The UI only fills the existing path input and reuses `/scan`.
  - [x] SaaS lockout is enforced twice: the `tenant_guard` middleware answers `403`
        `FS_BROWSE_DISABLED_IN_SAAS` **before** authentication (so an anonymous SaaS request never sees
        `401`), and the route re-checks `get_settings().is_saas`.
- [x] Support both local runtimes seamlessly via configurable `KODO_BROWSE_ROOTS`:
  - [x] **Docker local mode** (auto-detected via `/.dockerenv` or the `/projects` mount): roots default
        to `/projects` (mapped from `KODO_LOCAL_PROJECTS_DIR`) plus `KODO_WORKSPACES_DIR` when it exists;
        strict root containment is enforced.
  - [x] **Empty mount detection:** browsing `/projects` when it holds no real subdirectory (only the
        `.kodo-empty` → `.gitkeep` placeholder) returns `emptyMountHint: true` plus an actionable
        `KODO_LOCAL_PROJECTS_DIR=C:\Projects` / `~/projects` + `docker compose up -d` snippet.
  - [x] **Native (bare-metal) mode:** Windows drive roots (`C:\`, `D:\`, …) with `Path.home()` as the
        start folder; POSIX exposes `~` and `/`. No container-style containment beyond the user's own
        machine, matching the existing manual-path trust level.
  - [x] `KODO_BROWSE_ROOTS` (comma-separated, resolved, existing folders only) is the explicit
        allow-list and switches the browser to strict containment; `docker-compose.yml` and
        `.env.example` pass/document it next to `KODO_LOCAL_PROJECTS_DIR`.
- [x] Build a **Browse Folder** modal in the Web UI with root/drive switcher, breadcrumb navigation,
      automatic project/stack detection badges (`Spring Boot`, `C#/.NET`, `Node.js`, `Python`), and
      monorepo sub-project selection.
  - [x] `apps/web/src/components/FolderBrowserModal.tsx`: runtime badge (`Docker Mount` /
        `Local Filesystem`), root pills, Up button + clickable breadcrumbs, instant client-side folder
        filter, `Show hidden` toggle, current-folder banner with **Select & Scan Current Folder**, and a
        per-row hover **Scan** button. Marker badges come from `pom.xml` / `*.csproj|*.sln` /
        `package.json` / `pyproject.toml|requirements.txt|setup.py` + `.git` (badges are marker-only;
        the Phase 12 analyzer supersedes the early Python `preview` label).
  - [x] `TopBar` renders **Browse…** next to the path input in `local` mode only (never in `saas`), and
        a selection fills the input and immediately runs `Scan Project`.
- [x] Improve large-codebase ergonomics in Macro Graph & UML: quick node search (`Ctrl+K`), layer/stack
      filters, an **"Issues Only"** toggle, and a **1-hop Neighborhood Focus** mode so Mermaid diagrams
      stay readable on 100+ component repos.
  - [x] `lib/graphFilter.ts` + `hooks/useGraphFilter.ts` + `components/GraphFilterBar.tsx`: search
        across name / file path / annotations (`Ctrl+K` / `⌘K` focus, Enter or click selects and
        smoothly centers via `setCenter`), multi-select layer pills (Controller, Service, Repository,
        Entity, DTO, UI, Other) and detected-stack pills, a live `Showing N / M components` badge, and
        `Reset Filters`.
  - [x] **Issues Only** keeps only the components and relations referenced by Phase 2 Audit findings;
        **Focus 1-Hop** (enabled when a node is selected) keeps the selection, its direct in/out
        neighbours and the edges between them.
  - [x] `UmlDiagram` receives the filtered/1-hop subset — rendered server-side by the new stateless
        `POST /api/v1/mermaid` (pure reuse of `generate_class_diagram`, no disk access) — and shows a
        `filtered subset · N of M classes` / `1-hop focus` indicator. A large-graph guard intercepts
        > 60 classes when no filter is active with **Focus Selected Node (1-Hop)**,
        **Show Issues Only** and **Render Full Diagram Anyway** actions.
- **Definition of Done (evidence):** In both local Docker (`KODO_LOCAL_PROJECTS_DIR` -> `/projects`)
  and native mode, a user can click **Browse**, navigate host folders without copying files, pick a
  detected project or monorepo subfolder with one click, and smoothly filter/focus a 100+ node graph.
  - `tests/test_fs_browser.py` (12 hermetic cases): SaaS `403 FS_BROWSE_DISABLED_IN_SAAS` anonymous
    **and** authenticated, sorted subdirectories with `.git`/`node_modules`/`target`/`__pycache__`/…
    skipped, `showHidden`, stack markers + `isGitRepo` + `hasSubdirectories` (monorepo parent),
    drill-down/up, `..` traversal and escaping-symlink (Windows junction fallback) `403
    BROWSE_PATH_OUTSIDE_ROOTS`, `/projects` empty-mount hint, no-hint when a project is mounted,
    `PermissionError` on an unreadable child skipped without failing the request, and
    `409 BROWSE_NO_ROOTS` for missing configured roots.
  - `tests/test_mermaid.py` gained the filtered-subset render case. `pytest` **249 passed / 5 skipped**
    (only the environment-dependent Roslyn-container skips), `ruff check app tests`, `npm run build`,
    `docker compose config`, `docker compose --profile ai-local --profile builders config` and
    `docker compose -f docker-compose.yml -f docker-compose.prod.yml config` are green.
  - Security posture unchanged: browsing is read-only, tenant-gated and SaaS-disabled; no new write
    path was added and every apply still goes through the Phase 3c pipeline.

---

## Delivered — Python Stack (v0.7.0) & Production SaaS Hardening (v0.8.0)

**Status: Phases 12 and 13 delivered (v0.7.0, v0.8.0).** Phases 1–13 are the active delivered
contract; the v0.6+ roadmap (Phases 11–13) is complete.

### Phase 12: Full Python Stack Support (FastAPI / Django / Flask) ✅ (v0.7.0)
**Goal:** Elevate Python web applications from "visible in the graph" to a first-class stack across the
whole Blueprint -> Audit -> Edit -> Verify -> Deploy loop.

- [x] Extend Core IR extraction in `services/api-python` with **Tree-sitter Python**
      (`tree-sitter-python`) to detect routers/views, services, repositories, Pydantic/SQLAlchemy/Django
      models, type-annotated fields, decorators, and cross-module relations.
  - `app/analyzers/python_analyzer.py` (pure AST walk) + `python_imports.py` (package-root-aware
    `import`/`from … import` resolution) + `python_layers.py` (layer/kind classification).
  - `app/analyzers/scanner.py` detects `pyproject.toml` / `requirements.txt` / `setup.py` / `*.py`,
    skips `.venv`, `venv`, `__pycache__`, `.pytest_cache`, `.mypy_cache`, `.ruff_cache`, `build`,
    `dist`, `*.egg-info`, `site-packages`, and keeps `tests/`, `test_*.py`, `*_test.py` and
    `conftest.py` out of the graph.
  - Module-level `APIRouter` / `FastAPI` / `Blueprint` modules become synthetic `router` components
    (layer `controller`, handlers as methods, `include_router`/`register_blueprint` composition edges).
  - Core IR gains the `python` stack and the `router` node kind (schema + Pydantic + TypeScript + C#).
- [x] Extend the Phase 2 deterministic Audit Engine rules for Python architectural conventions (e.g.,
      router-to-DB leakage, missing Pydantic validation, god classes, circular imports).
  - `MISSING_VALIDATION` recognises `Field(...)` / `@field_validator` / `EmailStr` / `constr` markers
    and Python DTO suffixes; `LAYER_VIOLATION` suggestions now name FastAPI `Depends(...)`; entity
    exposure points at `response_model`/Django serializers. Circular imports and god classes reuse the
    generic rules over the Python graph (no new rule ids, no schema churn).
- [x] Add Tree-sitter byte-offset **AST Patching** for Python fields, type hints, and decorators
      (preserving hand-written methods and docstrings).
  - `app/patching/python_patcher.py` wired into `POST /api/v1/dry-run` and the Phase 3c guarded
    apply/rollback; `.py` joins the patch language map. Imports are only added for known symbols
    (`Field`, `mapped_column`, `relationship`, `dataclass`, `Decimal`, …). Module-level routers are
    reported as unsupported instead of being rewritten.
- [x] Add a **Python (FastAPI + Pydantic + SQLAlchemy)** vertical-slice plugin to the Phase 4
      Multi-Stack Builder, a non-root multi-stage Python template to Phase 6 Deploy Studio, and a
      pre-warmed offline `kodo-builder-python` (`ruff` + `mypy` + `pytest`) image to Phase 9 Ephemeral
      Builders.
  - `python-fastapi` blueprint stack: `app/generators/python_fastapi.py` + Jinja2 templates render
    SQLAlchemy 2 model, Pydantic v2 request/response, repository, service, `APIRouter` + pytest
    skeleton and `pyproject.toml` / `app/db.py` / `app/main.py`; generated projects self-audit 100/100.
  - Deploy Studio: `python:3.12-slim` multi-stage Dockerfile (uid 10001 `kodo`, `uvicorn
    app.main:app`, `urllib` `/health` healthcheck), compose environment/`DATABASE_URL`, Python
    `.dockerignore` and stack detection.
  - Phase 9 builder: `kodo-builder-python` image (ruff/mypy/pytest + FastAPI/Pydantic/SQLAlchemy
    preinstalled), `python` in the allow-listed stacks, structured ruff/mypy diagnostics and fixed
    `--network=none` commands.
- **Definition of Done:** Kodo can scan, audit, safely edit, scaffold, compile/test-verify
  (`--network=none`), and containerize Python web apps — verified by self-scanning Kodo's own
  `services/api-python` codebase.
  - Self-scan of `services/api-python`: **204 components / 252 relations**, 0 errors, 10 router
    components (account, fs, git, routes, auth, builders, decision, deploy, llm, audit-log) and no
    parse warnings.
  - `tests/test_python_stack.py` (19 hermetic cases) covers analyzer/layers/relations, Django/Flask,
    scanner noise, schema-valid scan output, patcher add/update/remove/decorator behaviour, dry-run
    SHA accuracy, guarded apply + byte-exact rollback, the FastAPI generator and its 100/100
    self-audit, the Python deploy artifacts and the builder configuration/diagnostics.
  - `pytest` **271 passed / 5 skipped** (only the environment-dependent Roslyn-container skips),
    `ruff check app tests`, `npm run build`, `dotnet build services/analyzer-csharp`,
    `docker compose config`, `docker compose --profile builders config` and
    `docker compose -f docker-compose.yml -f docker-compose.prod.yml config` are green.
  - Security posture unchanged: Python scanning is read-only, patching is proposal-only, and every
    Python write still flows through the Monaco diff + SHA-256 guarded apply + rollback.

---

### Phase 13: Production SaaS Hardening (Migrations, Quotas & Rate Limiting) ✅ (v0.8.0)
**Goal:** Make `KODO_MODE=saas` safe to operate for real tenants: upgradeable schemas, bounded storage
and abuse-resistant endpoints.

**Status:** Delivered — Alembic-owned schema with safe legacy upgrades, per-user storage governance with
TTL cleanup, per-bucket rate limiting, and a Caddy TLS + PostgreSQL Compose overlay with a full VPS
runbook. Every guard defaults to *off/inert* in `KODO_MODE=local`.

- [x] Introduce **Alembic** database migrations alongside SQLAlchemy (replacing bare `create_all()` for
      safe schema upgrades on existing SQLite/PostgreSQL instances).
  - `services/api-python/alembic.ini`, `alembic/env.py`, `alembic/script.py.mako`; `env.py` reads
    `KODO_DATABASE_URL` through `app.config` (or the API's injected live connection), imports
    `Base.metadata` from `app.db.models`, and enables `render_as_batch` on SQLite.
  - `alembic/versions/0001_initial_schema.py` (all Phase 8/10 tables) and
    `alembic/versions/0002_workspace_size_and_activity.py` (`workspaces.size_bytes`,
    `workspaces.last_accessed_at`).
  - `app/db/engine.py::run_migrations(engine)` replaces `create_all()` at startup
    (`KODO_DB_AUTO_MIGRATE=true` default): a legacy database (tables present, no `alembic_version`) is
    stamped at `0001_initial_schema` first, then upgraded to `head`; a fresh database upgrades directly.
  - The API Dockerfile copies `alembic.ini` + `alembic/` so `alembic upgrade head` works in-container.
- [x] Add per-user workspace disk quotas, clone size caps, and automatic TTL cleanup for stale cloned
      workspaces in `KODO_MODE=saas`.
  - `app/services/quota.py`: symlink-safe `compute_dir_size_bytes`, `get_user_storage_usage`,
    `enforce_pre_clone_quota` (`413`/`507 WORKSPACE_QUOTA_EXCEEDED`), `enforce_post_clone_size`
    (`413 CLONE_SIZE_LIMIT_EXCEEDED`, oversized clone deleted immediately) and
    `cleanup_stale_workspaces` (SaaS-only, sandbox-only, audited as `workspace_ttl_cleanup`).
  - `GET /api/v1/workspaces/storage` plus an extended `DELETE /api/v1/workspaces/{id}` returning the
    updated usage and auditing `workspace_delete`; only folders strictly inside
    `<KODO_WORKSPACES_DIR>/<user_id>/` are ever removed.
  - Cancellable `asyncio` cleanup task in the FastAPI lifespan every
    `KODO_CLEANUP_INTERVAL_MINUTES`; scan/read/apply/export refresh `last_accessed_at`.
  - Config: `KODO_QUOTA_ENABLED`, `KODO_USER_QUOTA_MB` (500), `KODO_MAX_CLONE_SIZE_MB` (200),
    `KODO_MAX_WORKSPACES_PER_USER` (10), `KODO_WORKSPACE_TTL_HOURS` (72),
    `KODO_CLEANUP_INTERVAL_MINUTES` (30).
- [x] Add API rate limiting on expensive endpoints (`/scan`, `/git/clone`, `/build/verify`, `/ai/*`) and
      document TLS reverse-proxy deployment (Caddy/Traefik) + optional GitHub App / encrypted
      short-lived token flow for private repo operations.
  - `app/middleware/rate_limit.py`: thread-safe `SlidingWindowRateLimiter` (injectable on
    `app.state.rate_limiter`), buckets `scan`/`clone`/`build`/`ai`/`auth`, per-user keys (client IP for
    auth routes, `X-Forwarded-For` only when trusted), `429 RATE_LIMITED` + `Retry-After` and
    `X-RateLimit-*` headers on limited responses. Off by default in local mode.
  - `deploy/caddy/Caddyfile` (automatic HTTPS, HSTS/nosniff/frame-deny/referrer-policy, 32 MB bodies,
    `flush_interval -1` for the SSE stream), `docker-compose.saas.yml` (Caddy + healthchecked
    PostgreSQL + SaaS defaults, `web` port unpublished) and `docs/SAAS_DEPLOYMENT.md` (DNS, secrets,
    OAuth callback, migration verification, managed PostgreSQL, backups, Traefik snippet, future GitHub
    App token flow).
  - Frontend: Workspace Switcher usage bar (`120 / 500 MB · 3/10 repos`), per-repo size, confirmed
    delete, and readable `429`/`413`/`507` messages in `apps/web/src/lib/api.ts`.
- **Definition of Done:** Existing SQLite/PostgreSQL databases upgrade cleanly via
  `alembic upgrade head`, SaaS mode enforces per-user storage quotas and rate limits, and a production
  VPS deployment guide is verified end-to-end.
  - `tests/test_saas_hardening.py` (24 hermetic cases): fresh `alembic upgrade head`, legacy
    `create_all` database stamped + upgraded with users/ADR rows preserved, a partial Phase 8 schema
    converging on the full table set, `init_db` migration bootstrap, storage/quota/clone-cap/delete
    tenant isolation, TTL cleanup (stale removed + audited, fresh kept, host folders untouched, local
    mode inert), the cancellable cleanup loop and rate limiting (429 body/headers + CORS, per-user
    buckets, local-mode default off).
  - `pytest` **295 passed / 5 skipped** (only the environment-dependent Roslyn-container skips),
    `ruff check app tests`, `npm run build`, `dotnet build services/analyzer-csharp --configuration
    Release`, and `docker compose config` for the base, prod, builders and new
    `docker-compose.saas.yml` overlay are green.
  - Alembic CLI verified end-to-end: `alembic upgrade head` → `current` = head → `downgrade
    0001_initial_schema` removes both columns on SQLite (batch mode).
  - Zero-friction local mode preserved: quotas/rate limits default off, TTL cleanup never runs, and
    deleting a workspace bookmark in local mode never removes the folder.

---

## Delivered — Structured Layered Diagrams & Image Export (v0.9.0)

### Phase 14: Structured Layered UML/Graph Layout & Diagram Image Export ✅ (v0.9.0)
**Goal:** Turn Kodo's diagrams into presentation-ready architecture artifacts — layered, deterministic and
exportable — instead of a flat class dump that has to be hand-arranged before it can be shared.

**Status:** Delivered — the Mermaid `classDiagram` is now grouped into fixed architectural namespaces,
the Macro Graph renders deterministic swimlanes with Auto-Arrange and a `TB`/`LR` toggle, and both
diagrams export to SVG, 2× PNG and `.mmd` **entirely in the browser**. Layout and export are pure
read-only operations: no new API write path, no file touched in the scanned workspace.

- [x] Upgrade Mermaid `classDiagram` generation (`services/api-python/app/services/mermaid.py`) from a
      flat class dump to **layer-grouped `namespace` blocks** (`UI`, `Controllers`, `Services`,
      `Repositories`, `Entities`, `DTOs`, `Other`), with deterministic alphabetical ordering inside each
      group.
  - `layer_bucket(node)` reuses the Core IR `layer`/`kind` taxonomy with the *same* roll-up as the
    Macro Graph colours and the Phase 11 filter pills (`graphFilter.ts::layerGroupOf`); DTOs are
    classified by name (`*Dto` / `*DTO` / `*Request` / `*Response`) **before** the layer, because
    Python/TS payloads are analysed as `other` — so DTOs always cluster together in both renderers.
  - Buckets emit in the fixed order `UI → Controllers → Services → Repositories → Entities → DTOs →
    Other`; empty buckets are omitted, classes sort by `(name.lower(), id)`, members and relations are
    emitted **after** every namespace block (one declaration per class, no duplicated nodes), and
    relations sort by `(sourceId, targetId, type)` with duplicates collapsed.
  - Optional **member-density toggle**: `full` (fields + methods, capped at 10 each), `compact`
    (top 3 fields + a `+N more fields, M methods` summary line) and `names_only` (headers and
    stereotypes only) — stereotypes render Mermaid `<<annotation>>` blocks.
  - Configurable **layout direction** (`TB` default, `LR`) emitted through the `direction` directive.
  - Phase 11 filtered-subset behaviour preserved: the UML tab still requests the visible subset from
    `POST /api/v1/mermaid` (and now also whenever a non-default layout is requested), so exports always
    follow active filters / **1-Hop Focus**, and the >60-class guard stays.
- [x] Enhance the Macro Graph (React Flow) layout with clean **layer-aligned swimlanes** and an
      **Auto-Arrange** button.
  - `apps/web/src/lib/graphLayout.ts` implements the deterministic swimlane pass: fixed band order,
    alphabetical ordering inside a band, and wide layers wrap into a compact grid (≤5 nodes per row in
    `TB`, ≤8 per column in `LR`) with short last rows centred, so 25 DTOs form a tidy grid instead of a
    10 000 px strip. `lib/layout.ts::buildGraph(nodes, relations, { direction })` turns it into React
    Flow nodes plus non-interactive `layerBand` background guides (translucent, `pointer-events: none`,
    label + count).
  - **Auto-Arrange** button clears manual drag offsets and re-applies the layered layout with a smooth
    `fitView`; a **TB/LR** toggle re-lays out the visible set. Band geometry is derived state, so
    `Ctrl+K` search, layer/stack pills, **Issues Only**, **1-Hop Focus**, relation drafting and the live
    audit preview all survive a re-layout.
- [x] Add one-click **Image Export** for both the **Mermaid UML Diagram** and the **Macro Graph**:
      `SVG` and high-DPI `PNG`, plus a raw `.mmd` download, all respecting the active filters /
      **1-Hop Focus**.
  - `apps/web/src/lib/diagramExport.ts` centralises the browser-only export: standalone SVG with
    explicit `xmlns`/`viewBox`/`width`/`height` and a solid background rect, 2× canvas rasterisation
    with blank-render and tainted-canvas detection (clear error message instead of a silent empty file),
    filename slugging and Blob downloads.
  - UML (`UmlDiagram.tsx`): **Grouped/Flat**, **TB/LR**, **Full/Compact/Names Only**, **Dark/Light**
    export background, plus **Export SVG**, **Export PNG (2x)** and **Download .mmd**. Exports
    re-render the currently displayed Mermaid source with the chosen theme (light uses a
    white/slate, PR- and wiki-friendly palette).
  - Macro Graph (`MacroGraph.tsx`): **Export PNG (2x)** / **Export SVG** with a Dark/Light background,
    captured with `getNodesBounds` + `getViewportForBounds` over **every visible node** (band guides
    included) at 2× `pixelRatio` via `html-to-image`, so the image is the full diagram rather than the
    current pan/zoom window; React Flow controls, the minimap and the app toolbars live outside
    `.react-flow__viewport` and are never captured.
  - File names carry workspace + filter hints (`api-python-uml.svg`, `api-python-graph-1hop.png`).
- [x] Backward-compatible API.
  - `POST /api/v1/mermaid` gains optional `groupByLayer` / `direction` / `memberDetail` (defaults
    `true` / `TB` / `full`): a payload with only `{ nodes, relations }` produces byte-identical output
    to the explicit defaults. `POST /api/v1/scan` uses the same defaults, so the first scan already
    renders grouped namespaces.
- **Definition of Done:** Scanning a multi-layer project renders a cleanly grouped Mermaid `classDiagram`
  (DTOs, Controllers, Services, Repositories and Entities clustered in their own namespaces), and both the
  UML diagram and the Macro Graph export cleanly to crisp SVG and PNG files.
  - `tests/test_mermaid.py` (12 cases) covers the fixed namespace order, empty-namespace omission,
    relation placement after the namespaces with one declaration per class, `LR` vs `TB`,
    `group_by_layer=False`, `compact` / `names_only` member density, DTO clustering for `other`-layer
    payloads, Python subscript/parameter sanitisation (a regression found by rendering a real scan),
    word-boundary clipping, and `POST /api/v1/mermaid` backward compatibility plus explicit overrides
    (and a `422` for an invalid direction).
  - Every generated variant (full / compact / names-only / flat / LR) was parsed with Mermaid 11 —
    including the **208-component / 255-relation** self-scan of `services/api-python` — to confirm the
    emitted `classDiagram` is valid syntax.
  - `pytest` **303 passed / 5 skipped** (only the environment-dependent Roslyn-container skips),
    `ruff check app tests`, `npm run build` (TypeScript + Vite, including `html-to-image`),
    `dotnet build services/analyzer-csharp --configuration Release` and `docker compose config`
    (base + prod + SaaS overlay) are green.
  - Browser-verified: the UML tab renders the `Controllers` / `Entities` / `DTOs` / `Other` namespaces
    for an issues-only subset and exports a 2× PNG (~577 KB), a standalone light-theme SVG (explicit
    `xmlns`, `viewBox`, white background) and the raw `.mmd`; the Macro Graph renders the band guides
    (`Controllers 10`, `Services 3`, `Entities 10`, `DTOs 50`, `Other 135`), flips `TB` ↔ `LR`, and
    exports a 2× PNG / SVG covering every visible node.
  - Zero-write posture unchanged: layout and export are 100% read-only / client-side downloads — no
    workspace file, sandbox or audit-log entry is ever created by a render or an export.

---

## Delivered — Kodo MCP Server (v1.0.0)

**Status: Phase 15 delivered (v1.0.0). All 15 phases delivered — Kodo v1.0.0.** Kodo's deterministic
architecture intelligence, the Laya System 1 layer and the sandboxed verification path are now callable
from inside an AI coding agent. The MCP surface is **strictly read-only**: no tool can write, apply,
roll back, deploy or export anything, and every tool advertises `readOnlyHint: true`,
`destructiveHint: false`.

### Phase 15: Kodo MCP Server (Model Context Protocol for AI Coding Agents) ✅ (v1.0.0)
**Goal:** Make Kodo's architecture intelligence directly callable from inside an AI coding agent, so the
editor can ask Kodo what the codebase looks like, what is wrong with it, which lane a task belongs to and
whether a change would compile — without a human context-switching to the web UI.

- [x] Expose Kodo's deterministic architecture intelligence, the Laya System 1 layer and the sandboxed
      verification path through a standards-compliant **MCP Server**.
  - **Streamable HTTP** `POST /mcp` mounted on the existing FastAPI app (same `tenant_guard`, CORS and
    rate-limit middleware chain as `/api/v1`), plus a local **`stdio` bridge**
    (`python -m app.mcp.stdio_server`) so Cursor, Claude Code and Windsurf can launch Kodo as a local
    MCP server process.
    - `app/mcp/protocol.py` — JSON-RPC 2.0 envelopes/errors and protocol negotiation for
      `2026-07-28`, `2025-06-18` (default) and `2025-03-26`.
    - `app/mcp/server.py` — stateless dispatcher for `initialize`, `notifications/initialized` (`202`
      with no body), `ping`, `tools/list`, `tools/call`, `resources/list`, `resources/read`; invalid
      arguments and unknown methods return spec-compliant `-32602`/`-32601` envelopes, tool-execution
      failures return `isError: true` content carrying the machine-readable code.
    - `app/mcp/http_routes.py` — `POST /mcp` returns plain JSON, or one SSE `event: message` when the
      client prefers `text/event-stream`; `GET`/`DELETE` answer `405` (no server-initiated stream, no
      session to terminate). No `Mcp-Session-Id` is ever issued, so the endpoint is clean behind Nginx,
      Caddy and multiple replicas; `Mcp-Protocol-Version` is echoed when sent.
    - `app/mcp/stdio_server.py` — newline-delimited JSON-RPC on stdin/stdout, always local-user
      context, logs to **stderr only** so stdout stays a clean protocol channel.
  - Both transports documented in [DEV_SETUP.md](DEV_SETUP.md#14-mcp-server-phase-15) with Cursor /
    Claude Code / stdio setup and troubleshooting.
- [x] Ship **read-only / advisory** MCP tools, strictly zero disk writes, preserving Kodo's guarded-apply
      contract (every mutation still flows through the Monaco diff + SHA-256 apply):
  - `kodo_scan_workspace` — compact Core IR: stacks, component/relation counts, layer counts,
    deterministic warnings, the Architecture Health Score, a bounded component list
    (`id, name, layer, kind, stack, filePath`) and an optional Phase 14 layered `namespace` Mermaid
    diagram (`includeMermaid`, `groupByLayer`, `direction`, `memberDetail`).
  - `kodo_audit_workspace` — deterministic Phase 2 score/summary/findings plus optional **Laya System 1**
    triage annotations (`includeLayaTriage`), degrading to `layaAvailable: false` when Laya is offline.
  - `kodo_get_component` — exact id / exact name / case-insensitive substring match, full component
    detail, its **1-hop** `incoming`/`outgoing` relations and every audit finding referencing it.
  - `kodo_route_task` & `kodo_screen_diff` — Phase 10 System 1 advisory routing (deterministic tools vs.
    DeepSeek vs. human) and a pre-diff safety pre-screen; both persist a tenant-scoped ADR and never
    apply anything.
  - `kodo_dry_run_patch` & `kodo_verify_build` — in-memory AST patch preview (Java/TS/JS/Python/C#, exact
    `originalSha256`, no SHA token issuance, no write) and `--network=none` sandboxed compile/test
    verification through the Phase 9 builders, returning parsed diagnostics and a bounded log tail.
  - Implemented once in `app/services/dry_run.py`, shared by `POST /api/v1/dry-run` and the MCP tool, so
    there is no duplicated business logic.
- [x] Enforce the Phase 8 security model and Phase 13 rate limits on the MCP surface.
  - In `KODO_MODE=saas`, `/mcp` requires an authenticated session / `Authorization: Bearer` token
    (`401 UNAUTHORIZED` otherwise; gated before the route, exactly like `/api/v1`). Every tool resolves
    its `rootPath` through `enforce_workspace_access`, so host and foreign-tenant paths are rejected
    with `SAAS_PATH_FORBIDDEN` (reported as `isError: true` content with `error.code`).
  - The Phase 13 `SlidingWindowRateLimiter` gains an `mcp` bucket: `KODO_RL_MCP_PER_MIN` (default 60)
    → `429 RATE_LIMITED` with `Retry-After` + `X-RateLimit-*`. `Mcp-Method` / `Mcp-Name` request headers
    feed the MCP log for observability.
  - In `KODO_MODE=local`, the server works out of the box against local / mounted workspaces with no
    extra configuration and no rate limiting. `KODO_MCP_ENABLED=false` answers `404 MCP_DISABLED` for
    `POST`/`GET`/`DELETE` and reports `enabled: false` on `GET /api/v1/mcp/info`.
- [x] Add a copy-paste **MCP Setup** snippet — Cursor (`.cursor/mcp.json`) and Claude Code config — in a
      UI settings/docs surface and in `DEV_SETUP.md`.
  - `apps/web/src/components/McpSetupModal.tsx` (opened by the new **MCP** pill in `TopBar.tsx`) shows
    the live `GET /api/v1/mcp/info` status (enabled, protocol, tool count, mode, rate limit), the
    endpoint built from the browser origin, one-click copies of the Cursor JSON, the
    `claude mcp add --transport http kodo <origin>/mcp` command and the local stdio JSON — plus the
    `Authorization` placeholder and sandbox note when `KODO_MODE=saas`, and the read-only tool catalog.
  - Reverse proxies: `apps/web/nginx.conf` gains a dedicated `location /mcp` (`proxy_http_version 1.1`,
    `proxy_buffering off`, `proxy_read_timeout 180s`, forwarded `Authorization`/`Mcp-*`/`X-Forwarded-*`)
    and `deploy/caddy/Caddyfile` a `handle /mcp*` block with `flush_interval -1`.
  - `AiSettingsModal.tsx` / `lib/aiSettings.ts` add **DeepSeek V4.1 Flash** (`deepseek-flash`) as a
    suggested code model next to `deepseek-chat` and `deepseek-reasoner` in the DeepSeek Cloud preset.
- **Definition of Done:** Cursor or Claude Code connects to Kodo via MCP, queries a repository's Core IR
  and audit findings, runs Laya System 1 task routing, and triggers a sandboxed build check without
  leaving the editor — with no file ever written to disk by an MCP tool.
  - `tests/test_mcp_server.py` (**37 hermetic cases**, zero network / Docker daemon): the `initialize`
    handshake across all three protocol versions, `tools/list` (all 7 tools, all `readOnlyHint: true`,
    `destructiveHint: false`, and no name containing apply/rollback/deploy/export/write/delete/scaffold/
    clone), `notifications/initialized` → `202`, `ping`, SSE + `405` transport handling, parse/
    protocol error envelopes, every `tools/call` (`kodo_scan_workspace` incl. layered `namespace`
    output and byte-identical rescans, `kodo_audit_workspace` deterministic + mocked Laya triage with
    persisted ADRs + offline degradation, `kodo_get_component` 1-hop relations, `kodo_route_task`
    mocked routing + ADR, `kodo_screen_diff` mocked screen, `kodo_dry_run_patch` exact
    `originalSha256` + zero disk mutation, `kodo_verify_build` mocked Docker CLI with hardened
    `--network none`/`--cap-drop` flags and guaranteed `rm -f`), both resources, the stdio bridge
    (shared registry, notification silence, JSON-only stdout), and SaaS hardening (`401`
    unauthenticated, `SAAS_PATH_FORBIDDEN` for host + foreign paths with the owner's own sandbox still
    working, `429 RATE_LIMITED` via `KODO_RL_MCP_PER_MIN`, `404 MCP_DISABLED`, `GET /api/v1/mcp/info`).
  - `pytest` **340 passed / 5 skipped** (only the environment-dependent Roslyn-container skips),
    `ruff check app tests`, `npm run build` (TypeScript + Vite), `dotnet build
    services/analyzer-csharp --configuration Release` and `docker compose config --quiet` for the base,
    prod, SaaS, builders and ai-local variants are green.
  - Version bumped to **1.0.0** in `services/api-python/app/__init__.py`, `apps/web/package.json` and
    the lockfile.
  - Zero-write posture unchanged: MCP tools read the workspace, return in-memory text, and the only
    persisted rows are tenant-scoped ADRs plus one `verify_build` audit event — a workspace file is
    never created, modified or deleted by any MCP call.
