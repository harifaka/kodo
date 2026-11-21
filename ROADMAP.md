# Kodo - 6-Phase MVP Roadmap

This roadmap tracks the iterative delivery of **Kodo** from a read-only architecture visualizer to a full Blueprint -> Audit -> Edit -> Deploy platform (Local Desktop via Tauri + Self-Hosted/SaaS via Docker).

---

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
- [x] Configure minimal **Tauri v2** desktop wrapper for local builds and GitHub Actions CI/CD.
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

## Phase 6: Ready-to-Deploy Docker Studio
**Goal:** Package audited, edited projects into production-ready containerized deployments.

- [ ] Auto-generate optimized multi-stage `Dockerfile`s per stack (non-root users, minimal runtime images).
- [ ] Auto-generate `docker-compose.yml` wiring services, databases (PostgreSQL, Redis, etc.), internal networks, healthchecks, and `.env.example`.
- [ ] Add local **Docker Control Panel** (`compose up --build`, live container status, filterable log streaming).
- [ ] Add SaaS/Git adapter mode (GitHub/GitLab clone -> analyze -> open Pull Request) and local audit logging.
- **Definition of Done:** Launch a visually built multi-service project in local Docker with one click and verify green healthchecks across all services.