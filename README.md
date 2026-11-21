# Kodo

**Architecture Control Center for the Vibe-Coding Era.**
Visualize, audit, safely edit, and containerize modern multi-stack codebases (Spring Boot, C# WPF/ASP.NET, Node.js) — locally via desktop app or self-hosted/SaaS via Docker.

![License: AGPL-3.0](https://img.shields.io/badge/License-AGPL--3.0-blue.svg)
![Status: Phase 3](https://img.shields.io/badge/Status-Phase%203%20delivered-brightgreen.svg)

---

## Why Kodo?

AI-assisted ("vibe") coding makes generating code trivial, but keeping architectures clean, understandable, and production-ready is harder than ever. Kodo sits between your codebase and deployment as a **Blueprint -> Audit -> Edit -> Deploy** platform:

- **Single Source of Truth (Core IR):** Stack-agnostic Intermediate Representation of services, classes, business fields, relations, and annotations.
- **Local-First & SaaS-Ready:** One shared React + TypeScript UI packaged as a native desktop app with **Tauri** (built via GitHub Actions) and deployable as a **Dockerized web app**.
- **Deep AST Analysis:** Uses **Tree-sitter** (Java, TypeScript/JavaScript) via Python FastAPI and **Roslyn** via a dedicated C# ASP.NET Core microservice for accurate C# analysis.
- **Deterministic Pattern Audit:** Six Core-IR rules (layer violations, circular dependencies, god classes, orphans, entities leaked through controllers, missing validation) produce an **Architecture Health Score** with actionable findings — still 100% read-only and zero LLM.

---

## Architecture Overview

    Shared Frontend (React + TypeScript + Vite)
    React Flow (Macro) | Mermaid (UML) | Monaco (Code/Diff)
            |                                 |
            | Desktop (Tauri v2)              | Web / SaaS (Docker)
            v                                 v
    Orchestrator API (Python FastAPI)
    Core IR | Tree-sitter (Java/TS/JS) | DeepSeek | Docker
            |
            | Internal HTTP (JSON)
            v
    C# Semantic Analyzer (ASP.NET Core + Roslyn)
    Deep C# / .NET AST extraction + stateless dry-run patching

---

## Quick Start (Phases 1–3)

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

Paste an absolute project path, hit **Scan Project**, and explore the Macro Graph, UML diagram and
read-only Code Inspector. Select a component to draft business-field and annotation edits, then click
**Preview Diff (Dry-Run)** to review the surgical AST patch in a Monaco side-by-side diff. The
**Git Safety & Apply** bar shows whether the working tree is clean, lets you pick which files to write,
and applies them atomically after a SHA-256 freshness check — with a one-click **Undo / Rollback** and
an automatic re-scan. Dirty or non-Git workspaces require an explicit risk confirmation. Desktop mode:
`npm run tauri dev` (requires Rust).

Full instructions, configuration and troubleshooting: [DEV_SETUP.md](DEV_SETUP.md).

---

## 6-Phase MVP Roadmap

### Phase 1: Vibe-Code X-Ray (Read-Only Visualizer) - Delivered
- Stack-agnostic **Core IR** schema (Pydantic + TypeScript + C#).
- Directory scanner with **Tree-sitter** (Java/Spring Boot, TS/JS/Node.js) and **Roslyn** (C#/.NET) microservice.
- Interactive **React Flow** service/layer map, **Mermaid** (`classDiagram`) zoomable UML view, and read-only **Monaco Editor** file inspector.
- Tauri v2 desktop wrapper + local dev orchestration.

### Phase 2: Pattern & Vibe-Audit Engine - Delivered
- Deterministic rule engine running on the Core IR (zero LLM required).
- Detects architectural drift and vibe-code anti-patterns: layer violations (e.g., Controller -> Repository), circular dependencies, God Classes, exposed entities, missing validation and orphan components.
- Visual error highlighting on the graph + **Architecture Health Score** panel with file jump-to-line links.

### Phase 3: Real-Life Business Field Editor & Safe Round-Trip - Delivered
- Macro/Micro editing: connect/disconnect relations on the canvas and edit real business fields, types, and annotations (`@Entity`, `@Column`, `[Required]`, etc.) in a keyboard-friendly inspector with stack-aware presets.
- **Dry-Run Monaco Side-by-Side Diff** for every draft edit, computed in memory with **Tree-sitter byte-offset patching** (Java/TS/JS) and **trivia-preserving Roslyn rewriting** (C#). Hand-written methods and comments stay verbatim.
- **Guarded apply to disk**: read-only Git status inspection, a dirty-tree / non-Git confirmation gate, SHA-256 optimistic concurrency (stale files abort the whole batch), atomic writes that preserve CRLF/LF, and an in-memory rollback snapshot with one-click undo. Applying re-scans the workspace so the graph, UML and health score immediately reflect the saved code.

### Phase 4: Multi-Stack Builder & Pattern Blueprints
- Full stack plugin generators for **Spring Boot**, **C# WPF (MVVM)**, and **Node.js (Express/NestJS)**.
- One-click vertical slice scaffolding (Entity + DTO + Repo + Service + Controller + Tests).
- Versionable `kodo.blueprint.json` committed alongside the repo for team PR reviews.

### Phase 5: DeepSeek Architecture Copilot
- OpenAI-compatible **DeepSeek** client (supports cloud API and air-gapped on-prem Ollama/vLLM).
- Context-efficient prompting powered by the **Core IR** + Audit findings (no raw codebase dumps).
- Workflows: *Business Spec -> Blueprint*, *Audit Error -> Diff Fix*, and *Targeted Method Implementation*.

### Phase 6: Ready-to-Deploy Docker Studio
- Auto-generated multi-stage `Dockerfile`s, `docker-compose.yml` (wiring databases, queues, networks, healthchecks), and `.env.example`.
- Built-in Docker lifecycle controls (`up --build`, live container status, filterable log viewer).
- Local audit logging and Git commit/tag export.

---

## License

This project is licensed under the **GNU Affero General Public License v3.0 (AGPL-3.0)** — see the [LICENSE](LICENSE) file for details.