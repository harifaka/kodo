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

> **Next evolution (v0.6+) is planned, not delivered.** Phases 11–13 — Local UX / Dual-Mode Browse
> Folder, Full Python Stack Support and Production SaaS Hardening — are recorded in the
> [Next Evolution](#next-evolution-v06--local-ux-python-stack--saas-hardening) section below. They are
> **not** part of the v0.5.0 contract and are not active implementation scope until a future session
> starts them.

> **Architectural pivot (post-MVP, delivered in Phase 7).** Kodo is a **Docker-first web
> application**. The **Tauri desktop wrapper has been deleted** (`apps/web/src-tauri/` is gone, no
> `@tauri-apps/*` dependencies, no desktop origins) in favour of one unified container deployment shared
> by local and SaaS. Phases 8, 9 and 10 are delivered (v0.3.0, v0.4.0 and v0.5.0); **all ten phases of
> the roadmap are complete**. Phases 1–10 stay below as delivered history, and the planned v0.6+ tracks
> (Phases 11–13) are recorded at the end under *Next Evolution*.

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

## Next Evolution (v0.6+ — Local UX, Python Stack & SaaS Hardening)

**Status: planned — not delivered.** Phases 1–10 above remain the active delivered contract
(v0.1.0–v0.5.0). The three phases below are recorded for future sessions; implementation starts only
when a session explicitly takes them on.

### Phase 11: Local UX, Dual-Mode Folder Browser & Large-Repo Ergonomics ⬜
**Goal:** Make pointing Kodo at a real workspace on the user's own machine a one-click, zero-copy
experience in **both** local runtimes (Docker and native), and keep the Macro Graph / UML readable on
large repositories.

- [ ] Add a local-only, **zero-copy (in-place)** server-side directory browser API
      (`GET /api/v1/fs/browse`) that operates directly on real workspace directories without uploading
      or copying files — strictly disabled in `KODO_MODE=saas` (`403`).
- [ ] Support both local runtimes seamlessly via configurable `KODO_BROWSE_ROOTS`:
  - [ ] **Docker local mode:** auto-detects mounted host folders (defaulting to `/projects` mapped from
        `KODO_LOCAL_PROJECTS_DIR`, with support for multiple mounted roots); if `/projects` is empty
        (default `.kodo-empty`), return a clear setup hint showing how to point
        `KODO_LOCAL_PROJECTS_DIR` in `.env` to the user's host projects directory.
  - [ ] **Native (bare-metal) mode:** lists real host roots (Windows drive letters `C:\`, `D:\`, or
        POSIX `~` / `/`) for direct local filesystem navigation.
- [ ] Build a **Browse Folder** modal in the Web UI with root/drive switcher, breadcrumb navigation,
      automatic project/stack detection badges (`Spring Boot`, `C#/.NET`, `Node.js`, `Python`), and
      monorepo sub-project selection.
- [ ] Improve large-codebase ergonomics in Macro Graph & UML: quick node search (`Ctrl+K`), layer/stack
      filters, an **"Issues Only"** toggle, and a **1-hop Neighborhood Focus** mode so Mermaid diagrams
      stay readable on 100+ component repos.
- **Definition of Done:** In both local Docker (`KODO_LOCAL_PROJECTS_DIR` -> `/projects`) and native
  mode, a user can click **Browse**, navigate host folders without copying files, pick a detected
  project or monorepo subfolder with one click, and smoothly filter/focus a 100+ node graph.

---

### Phase 12: Full Python Stack Support (FastAPI / Django / Flask) ⬜
**Goal:** Elevate Python web applications from "visible in the graph" to a first-class stack across the
whole Blueprint -> Audit -> Edit -> Verify -> Deploy loop.

- [ ] Extend Core IR extraction in `services/api-python` with **Tree-sitter Python**
      (`tree-sitter-python`) to detect routers/views, services, repositories, Pydantic/SQLAlchemy/Django
      models, type-annotated fields, decorators, and cross-module relations.
- [ ] Extend the Phase 2 deterministic Audit Engine rules for Python architectural conventions (e.g.,
      router-to-DB leakage, missing Pydantic validation, god classes, circular imports).
- [ ] Add Tree-sitter byte-offset **AST Patching** for Python fields, type hints, and decorators
      (preserving hand-written methods and docstrings).
- [ ] Add a **Python (FastAPI + Pydantic + SQLAlchemy)** vertical-slice plugin to the Phase 4
      Multi-Stack Builder, a non-root multi-stage Python template to Phase 6 Deploy Studio, and a
      pre-warmed offline `kodo-builder-python` (`ruff` + `mypy` + `pytest`) image to Phase 9 Ephemeral
      Builders.
- **Definition of Done:** Kodo can scan, audit, safely edit, scaffold, compile/test-verify
  (`--network=none`), and containerize Python web apps — verified by self-scanning Kodo's own
  `services/api-python` codebase.

---

### Phase 13: Production SaaS Hardening (Migrations, Quotas & Rate Limiting) ⬜
**Goal:** Make `KODO_MODE=saas` safe to operate for real tenants: upgradeable schemas, bounded storage
and abuse-resistant endpoints.

- [ ] Introduce **Alembic** database migrations alongside SQLAlchemy (replacing bare `create_all()` for
      safe schema upgrades on existing SQLite/PostgreSQL instances).
- [ ] Add per-user workspace disk quotas, clone size caps, and automatic TTL cleanup for stale cloned
      workspaces in `KODO_MODE=saas`.
- [ ] Add API rate limiting on expensive endpoints (`/scan`, `/git/clone`, `/build/verify`, `/ai/*`) and
      document TLS reverse-proxy deployment (Caddy/Traefik) + optional GitHub App / encrypted
      short-lived token flow for private repo operations.
- **Definition of Done:** Existing SQLite/PostgreSQL databases upgrade cleanly via
  `alembic upgrade head`, SaaS mode enforces per-user storage quotas and rate limits, and a production
  VPS deployment guide is verified end-to-end.
