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

## Phase 4: Multi-Stack Builder & Pattern Blueprints
**Goal:** Scaffold new projects and standardized vertical slices across all three target stacks.

- [ ] Implement stack generator plugins for **Spring Boot**, **C# WPF (MVVM)**, and **Node.js (Express/NestJS)**.
- [ ] Add one-click **Vertical Slice** templates (e.g., Entity + DTO + Mapper + Repository + Service + Controller + Test skeleton).
- [ ] Support saving and loading versionable `kodo.blueprint.json` files inside the target repository for PR reviews.
- **Definition of Done:** Design a 3-service architecture visually from scratch and generate a compiling, pattern-compliant multi-stack skeleton.

---

## Phase 5: DeepSeek Architecture Copilot
**Goal:** Integrate AI assistance constrained by the Core IR and Audit rules so generated code stays structurally clean.

- [ ] Build OpenAI-compatible **DeepSeek** client (`DeepSeek-V3` for code, `DeepSeek-R1` for architecture/audit) with configurable Base URL for air-gapped on-prem **Ollama / vLLM**.
- [ ] Implement **IR-based context packing** (send compact Core IR JSON + Audit findings instead of raw file dumps).
- [ ] Ship 3 core AI workflows:
  - [ ] *Business Spec -> Blueprint* (natural language to structured Core IR for human review).
  - [ ] *Audit Error -> Refactor Patch* (one-click fix previewed in Monaco Diff).
  - [ ] *Targeted Method Implementation* inside the on-code editor.
- **Definition of Done:** Generate a blueprint from a short business spec and resolve a Phase 2 audit violation via DeepSeek + Monaco Diff approval.

---

## Phase 6: Ready-to-Deploy Docker Studio
**Goal:** Package audited, edited projects into production-ready containerized deployments.

- [ ] Auto-generate optimized multi-stage `Dockerfile`s per stack (non-root users, minimal runtime images).
- [ ] Auto-generate `docker-compose.yml` wiring services, databases (PostgreSQL, Redis, etc.), internal networks, healthchecks, and `.env.example`.
- [ ] Add local **Docker Control Panel** (`compose up --build`, live container status, filterable log streaming).
- [ ] Add SaaS/Git adapter mode (GitHub/GitLab clone -> analyze -> open Pull Request) and local audit logging.
- **Definition of Done:** Launch a visually built multi-service project in local Docker with one click and verify green healthchecks across all services.