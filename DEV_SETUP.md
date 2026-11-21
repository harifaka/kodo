# Kodo — Developer Setup (Phases 1–3b: X-Ray, Audit, Draft Editing, Dry-Run Diff)

Phases 1–3b are **zero-write** with respect to the scanned project. Kodo scans a folder, maps Java,
TypeScript, JavaScript and C# sources onto the Core IR, runs a deterministic audit over that IR, and
renders a layer graph, a Mermaid UML diagram, an architecture health score with findings, and a
read-only Monaco source inspector. Nothing is ever written to the scanned project.

Phase 3a adds **macro draft editing**: connect and cut relations on the Macro Graph, with the audit
re-scoring the draft through a stateless API call. Phase 3b adds the **Micro field editor** (business
fields, types, annotations and stack-aware presets) and a **stateless AST dry-run** that returns
proposed file contents for a Monaco side-by-side diff. Draft edits live in the browser; proposed
contents live in API memory. There is still no disk write.

```
apps/web (Vite :5173, or Tauri desktop)
        │  HTTP/JSON
        ▼
services/api-python (FastAPI :8088)      ← Core IR, audit, /api/v1/dry-run orchestrator
        │  HTTP/JSON                         (Tree-sitter patchers for Java/TS/JS)
        ▼
services/analyzer-csharp (Roslyn :5050)  ← stateless C# / .NET analysis + trivia-preserving /patch
```

---

## 1. Prerequisites

| Tool | Version | Needed for |
| --- | --- | --- |
| Docker Desktop | 4.x+ (Compose v2) | Roslyn analyzer container (recommended) |
| Python | 3.12+ | FastAPI orchestrator, tree-sitter analyzers |
| .NET SDK | 8.0+ | Building/testing the Roslyn analyzer (`net8.0`, rolls forward to newer runtimes) |
| Node.js | 20+ | React / Vite frontend |
| Rust | 1.77+ | **only** for the Tauri desktop build (`rustup`, platform toolchain) |
| Git | any | cloning the repo |

Windows commands are shown; macOS/Linux equivalents are noted where they differ.

---

## 2. Start the three processes

### Terminal 1 — C# Roslyn analyzer (:5050, Docker)

The analyzer is **stateless**: FastAPI reads each `.cs` file and POSTs its content, so the container
needs no workspace volume mount.

```powershell
docker compose up -d --build analyzer-csharp
```

Verify:

```powershell
curl http://localhost:5050/health      # {"status":"ok"}
```

Container status and logs:

```powershell
docker compose ps
docker compose logs -f analyzer-csharp
```

No Docker? Run it directly with `cd services/analyzer-csharp ; dotnet run` (same `:5050` port — stop
one of the two before starting the other).

### Terminal 2 — Python FastAPI orchestrator (:8088)

```powershell
cd services/api-python
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 8088
```

macOS/Linux: `source .venv/bin/activate`.

Verify:

```powershell
curl http://127.0.0.1:8088/health
# {"status":"ok", "analyzers":{"csharp":{"url":"http://localhost:5050","reachable":true}}, ...}
```

Interactive API docs: <http://127.0.0.1:8088/docs>

### Terminal 3 — React frontend (:5173)

```powershell
cd apps/web
npm install
npm run dev
```

Open <http://127.0.0.1:5173>.

---

## 3. Run the first scan

1. Paste an **absolute path** into the folder field, e.g. `C:\work\my-spring-shop` or
   `C:\work\MyWpfApp`.
2. Click **Scan Project** (or press Enter).
3. Explore:
   - **Macro Graph** — layer-grouped React Flow map. Click a node to inspect it in the right panel;
     double-click to zoom to it. Nodes and edges with audit findings are outlined in red (error) or
     amber (warning) and carry a finding count badge.
   - **Draft edits** — drag from a card's right handle onto another card to add a relation (choose the
     relation type in the **Draft edits** panel first), or click the `×` on an edge / in the side
     panel's relation list to cut one. Each edit re-runs the deterministic audit, so the health score
     and findings update immediately; **Reset draft** discards the changes. Draft edits stay in the
     browser and are never written to disk.
   - **Micro field editor** — with a component selected, use **+ Quick add field**, inline edit (`✎`),
     and `×` in the right panel. Type suggestions and annotation presets follow the component's stack
     (Spring Boot, C#/.NET or Node.js/TS). Node annotations can be added/removed the same way.
   - **Preview Diff (Dry-Run)** — in the **Draft edits** panel opens the **Diff Preview** tab. The left
     sidebar lists every file the draft would change with line counts and patcher warnings; the main
     pane shows the original vs proposed content in a Monaco `DiffEditor` (side-by-side or inline).
     **No file is modified on disk.**
   - **UML Diagram** — server-generated Mermaid `classDiagram`. Drag to pan, `Ctrl` + scroll to zoom,
     **Fit** to see everything.
   - **Code Inspector** — read-only Monaco view of the selected component's file.
   - **Open in Code Inspector** — jumps from the side panel to the source view, including from an
     audit finding's file button.
4. Read the **audit**: the workspace panel shows the Architecture Health Score plus every finding
   (filterable by severity). Selecting a component lists the findings that mention it.

### Audit rules (Phase 2)

| Rule | Severity | Detects |
| --- | --- | --- |
| `LAYER_VIOLATION` | error | A dependency that skips or inverts a layer boundary (e.g. Controller → Repository). |
| `CIRCULAR_DEPENDENCY` | error | Cycles in the dependency graph (Tarjan SCC, shortest cycle reported). |
| `GOD_CLASS` | warning | Classes/records/modules with >15 fields, >20 methods or >30 members. |
| `ORPHAN_COMPONENT` | info | Controller/service/repository/view-model components with no relations at all. |
| `ENTITY_EXPOSED_IN_CONTROLLER` | warning | A controller whose signature or relations expose a persistence entity. |
| `MISSING_VALIDATION` | warning | A controller accepting a DTO-ish payload with no validation annotations. |

The score starts at 100 and subtracts 10 per error, 4 per warning and 1 per info finding (clamped at
0). Rules are pure functions of the Core IR — no filesystem, network, clock or LLM — and findings are
ordered deterministically so repeated scans are diffable. The report is returned as
`WorkspaceIR.audit` (`score`, `summary`, `findings`).

### Audit preview for drafts (Phase 3a)

`POST /api/v1/audit` scores an arbitrary draft Core IR without touching the workspace:

```json
{ "nodes": [...], "relations": [{ "sourceId": "a", "targetId": "b", "type": "depends_on" }] }
```

It returns the same `AuditReport` shape as `WorkspaceIR.audit`, ignores relations that point at
unknown node ids, and is pure (no filesystem access). The UI debounces it after every macro draft edit
so the health score always reflects the graph on screen. Micro field/annotation edits are applied to
the draft nodes before the same call, so rules such as `GOD_CLASS` and `MISSING_VALIDATION` re-score
immediately.

### Dry-run AST patching (Phase 3b)

`POST /api/v1/dry-run` turns a draft into proposed file contents **in memory**. Example:

```json
{
  "rootPath": "C:/work/my-spring-shop",
  "operations": [
    {
      "op": "add_field",
      "filePath": "src/main/java/com/acme/shop/entity/Order.java",
      "typeName": "Order",
      "field": {
        "name": "total",
        "type": "BigDecimal",
        "visibility": "private",
        "annotations": ["@NotNull", "@Column(nullable = false)"]
      }
    }
  ]
}
```

It returns `{ patches: [{ filePath, language, originalContent, proposedContent, summary, warnings }], warnings }`.
Operations are grouped by `filePath`; every path is resolved and must stay inside `rootPath` (traversal
is rejected with HTTP 400) and each file is capped at 2 MB. The UI sends node field/annotation edits
plus best-effort relation edits (`add_dependency` / `remove_dependency`).

- **Java** — `app/patching/java_patcher.py`: Tree-sitter byte offsets target the class body; inserts
  fields, rewrites annotations/visibility, and adds missing imports (`jakarta.validation.constraints.*`,
  `jakarta.persistence.*`, `java.math.BigDecimal`, …).
- **TypeScript / JavaScript** — `app/patching/ts_patcher.py`: Tree-sitter byte offsets for class
  properties, decorators and interface fields.
- **C#** — `app/patching/csharp_patcher.py` POSTs `{ filePath, content, operations }` to the Roslyn
  container's `POST /patch`. `RoslynPatcher` parses with `CSharpSyntaxTree.ParseText` and rewrites only
  the target members/attributes, preserving trivia (comments and hand-written methods stay verbatim).
  If the container is offline the original content is returned unchanged with a warning.

Nothing in this pipeline opens a file for writing. Apply-on-disk, Git dirty-tree checks and rollback
warnings are intentionally deferred to Phase 3c.

Notes:

- Start with a single service/module folder. Limits are 6000 files and 2 MB per file; anything
  skipped is reported in the amber **diagnostics** bar rather than failing the scan.
- If the Roslyn service is not running, the scan still succeeds for Java/TS/JS and adds a warning.
- Use the health pills in the top bar to confirm FastAPI and Roslyn reachability.

---

## 4. Desktop app (Tauri v2)

The desktop shell wraps the same frontend. The API and Roslyn services remain separate local
processes through Phase 3b.

```powershell
cd apps/web
npm run tauri dev      # opens a native window pointed at http://127.0.0.1:5173
npm run tauri build    # produces platform installers/bundles
```

Install the [Tauri prerequisites](https://tauri.app/start/prerequisites/) for your OS first (Rust,
WebView2 on Windows, `libwebkit2gtk` on Linux). Icons and bundle metadata are already checked in at
[apps/web/src-tauri](/C:/source/kodo/apps/web/src-tauri), and the configuration is ready for
GitHub Actions runners (`npm ci` → `npm run tauri build`).

CORS already allows the Tauri origins: `tauri://localhost`, `https://tauri.localhost`,
`http://tauri.localhost`.

---

## 5. Configuration

| Variable | Where | Default | Purpose |
| --- | --- | --- | --- |
| `VITE_API_BASE_URL` | `apps/web/.env.local` | `http://localhost:8088` | Orchestrator base URL |
| `KODO_CSHARP_URL` | FastAPI process | `http://localhost:5050` | Roslyn analyzer base URL |
| `KODO_CORS_ORIGINS` | FastAPI process | Vite + Tauri origins | Comma-separated allow-list |
| `KODO_CSHARP_URL` | Roslyn process | `http://localhost:5050` | Kestrel bind address (overrides `ASPNETCORE_URLS`) |
| `ASPNETCORE_URLS` | Roslyn container | `http://+:5050` | Container bind address |

---

## 6. Tests & validation

```powershell
# Python: parsers, relation resolver, Mermaid generator, audit rules, security,
# Core IR schema conformance and dry-run patchers (Java/TS always; C# when the container is up)
cd services/api-python
pip install -r requirements-dev.txt
python -m pytest
python -m ruff check app tests

# C#: build the Roslyn service
dotnet build services/analyzer-csharp

# Web: type-check + production bundle
cd apps/web
npm run build
```

---

## 7. Troubleshooting

**Port 8000 was taken, so FastAPI moved to 8088.** Docker Desktop's backend commonly listens on
`0.0.0.0:8000`, which is why Kodo now defaults to `:8088`. If `8088` is also busy, run the API on
another port (`--port 8090`) and set `VITE_API_BASE_URL=http://localhost:8090` in
`apps/web/.env.local`.

**`Roslyn` pill is red.** Start the container with `docker compose up -d --build analyzer-csharp` and
check `docker compose ps` / `docker compose logs analyzer-csharp`. A local `dotnet run` on `:5050`
conflicts with the published container port — run only one of them. Scans still work without it;
`.cs` files are skipped with a warning.

**Graph or UML is empty.** Check the diagnostics bar. Files must be `.java`, `.ts`, `.tsx`, `.js`,
`.jsx`, `.mjs`, `.cjs` or `.cs`; generated `.g.cs` / `.Designer.cs` files are intentionally ignored.

**Mermaid shows a render error.** The raw diagram is available via the **Source** toggle, and the
scan response contains the same string under `mermaidClassDiagram` — useful for bug reports.

**The Diff Preview shows a C# warning that the Roslyn analyzer is unreachable.** Start the container
with `docker compose up -d --build analyzer-csharp`; Java/TS/JS diffs still work without it and the
`.cs` patch returns the original content unchanged.

**The Diff Preview says no file-level patches were proposed.** A relation cut only becomes a patch
when the source component has a matching field for that dependency. Constructor/method-level
dependencies are reported as a draft note and must be edited by hand.

**The audit score is 100 but the code feels messy.** Rules only see components and relations that
the analyzers actually discovered. Unresolved references, primitives and files outside the scan scope
produce no edges, so the audit cannot flag them. Narrow the scan to the service/module you care
about and check the diagnostics bar for skipped or unparsable files.

**A finding seems wrong.** Findings are deterministic: the same tree always produces the same ids.
Compare `workspace.audit.findings[].nodeIds` / `edgeKeys` with the graph, and adjust the rule
thresholds in `services/api-python/app/audit/rules/` if the guideline is too strict for your project.

**Tauri build fails immediately.** Rust/toolchain prerequisites are missing; the browser workflow
(`npm run dev`) does not require Rust.

**Python 3.14 + tree-sitter.** Wheels exist for 3.12–3.14; on an unsupported interpreter pip may
attempt a source build and require a C compiler.

---

## 8. Repository layout

```
.cursorrules                      Architecture rules (Core IR, layers, zero-write Phases 1-3b)
docker-compose.yml                Local Docker stack (analyzer-csharp on :5050)
packages/core-ir/schema.json      Canonical JSON Schema contract
services/analyzer-csharp/         .NET 8 Minimal API + Roslyn, stateless (port 5050, Dockerfile)
  Analysis/                       Roslyn Core IR extraction
  Patching/                       trivia-preserving /patch rewriter (dry-run only)
services/api-python/              FastAPI orchestrator, tree-sitter analyzers (port 8088)
  app/analyzers/                  java.py, typescript.py, scanner.py, common.py
  app/audit/                      engine.py, context.py + rules/ (one file per audit rule)
  app/patching/                   java_patcher.py, ts_patcher.py, csharp_patcher.py, paths.py, models.py
  app/services/                   csharp_client.py, relations.py, mermaid.py, workspace.py
  tests/                          pytest suite incl. audit rules, schema conformance, dry-run patching
apps/web/                         React + TypeScript + Vite + Tailwind UI
  src/components/                 MacroGraph, UmlDiagram, CodeInspector, NodeDetailsPanel, DiffPreview, DraftToolbar, AuditPanel, HealthScore
  src-tauri/                      Minimal Tauri v2 desktop shell (icons, config, capabilities)
```

Contract changes must be applied to `packages/core-ir/schema.json`, `app/models/ir.py`,
`apps/web/src/types/core-ir.ts` and — for node/relation shapes — `services/analyzer-csharp/Models/CoreIr.cs`,
together. See [.cursorrules](/C:/source/kodo/.cursorrules).
