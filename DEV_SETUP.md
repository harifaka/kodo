# Kodo — Developer Setup (Phase 1: Vibe-Code X-Ray)

Phase 1 is a **read-only** architecture visualizer. It scans a folder, maps Java, TypeScript,
JavaScript and C# sources onto the Core IR, and renders a layer graph, a Mermaid UML diagram and a
read-only Monaco source inspector. Nothing is ever written to the scanned project.

```
apps/web (Vite :5173, or Tauri desktop)
        │  HTTP/JSON
        ▼
services/api-python (FastAPI :8000)      ← owner of the Core IR
        │  HTTP/JSON
        ▼
services/analyzer-csharp (Roslyn :5050)  ← C# / WPF / .NET AST extraction
```

---

## 1. Prerequisites

| Tool | Version | Needed for |
| --- | --- | --- |
| Python | 3.12+ | FastAPI orchestrator, tree-sitter analyzers |
| .NET SDK | 8.0+ | Roslyn analyzer (`net8.0` target, rolls forward to newer runtimes) |
| Node.js | 20+ | React / Vite frontend |
| Rust | 1.77+ | **only** for the Tauri desktop build (`rustup`, platform toolchain) |
| Git | any | cloning the repo |

Windows commands are shown; macOS/Linux equivalents are noted where they differ.

---

## 2. Start the three processes

### Terminal 1 — C# Roslyn analyzer (:5050)

```powershell
cd services/analyzer-csharp
dotnet run
```

Verify:

```powershell
curl http://localhost:5050/health      # {"status":"ok"}
```

### Terminal 2 — Python FastAPI orchestrator (:8000)

```powershell
cd services/api-python
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

macOS/Linux: `source .venv/bin/activate`.

Verify:

```powershell
curl http://127.0.0.1:8000/health
# {"status":"ok", "analyzers":{"csharp":{"url":"http://localhost:5050","reachable":true}}, ...}
```

Interactive API docs: <http://127.0.0.1:8000/docs>

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
     double-click to zoom to it.
   - **UML Diagram** — server-generated Mermaid `classDiagram`. Drag to pan, `Ctrl` + scroll to zoom,
     **Fit** to see everything.
   - **Code Inspector** — read-only Monaco view of the selected component's file.
   - **Open in Code Inspector** — jumps from the side panel to the source view.

Notes:

- Start with a single service/module folder. Limits are 6000 files and 2 MB per file; anything
  skipped is reported in the amber **diagnostics** bar rather than failing the scan.
- If the Roslyn service is not running, the scan still succeeds for Java/TS/JS and adds a warning.
- Use the health pills in the top bar to confirm FastAPI and Roslyn reachability.

---

## 4. Desktop app (Tauri v2)

The desktop shell wraps the same frontend. The API and Roslyn services remain separate local
processes in Phase 1.

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
| `VITE_API_BASE_URL` | `apps/web/.env.local` | `http://127.0.0.1:8000` | Orchestrator base URL |
| `KODO_CSHARP_URL` | FastAPI process | `http://localhost:5050` | Roslyn analyzer base URL |
| `KODO_CORS_ORIGINS` | FastAPI process | Vite + Tauri origins | Comma-separated allow-list |
| `KODO_CSHARP_URL` | Roslyn process | `http://localhost:5050` | Kestrel bind address |

---

## 6. Tests & validation

```powershell
# Python: parsers, relation resolver, Mermaid generator, security, Core IR schema conformance
cd services/api-python
pip install -r requirements-dev.txt
python -m pytest

# C#: build the Roslyn service
dotnet build services/analyzer-csharp

# Web: type-check + production bundle
cd apps/web
npm run build
```

---

## 7. Troubleshooting

**Port 8000 is already in use / health pill flaps red-green.**
Docker Desktop's backend commonly listens on `0.0.0.0:8000`. Check with
`Get-NetTCPConnection -LocalPort 8000 -State Listen`. Stop the conflicting service, or run the API
elsewhere (`--port 8010`) and set `VITE_API_BASE_URL=http://127.0.0.1:8010` in `apps/web/.env.local`.

**`Roslyn` pill is red.** Start `dotnet run` in `services/analyzer-csharp`. Scans still work; `.cs`
files are skipped with a warning.

**Graph or UML is empty.** Check the diagnostics bar. Files must be `.java`, `.ts`, `.tsx`, `.js`,
`.jsx`, `.mjs`, `.cjs` or `.cs`; generated `.g.cs` / `.Designer.cs` files are intentionally ignored.

**Mermaid shows a render error.** The raw diagram is available via the **Source** toggle, and the
scan response contains the same string under `mermaidClassDiagram` — useful for bug reports.

**Tauri build fails immediately.** Rust/toolchain prerequisites are missing; the browser workflow
(`npm run dev`) does not require Rust.

**Python 3.14 + tree-sitter.** Wheels exist for 3.12–3.14; on an unsupported interpreter pip may
attempt a source build and require a C compiler.

---

## 8. Repository layout

```
.cursorrules                      Architecture rules (Core IR, layers, read-only Phase 1)
packages/core-ir/schema.json      Canonical JSON Schema contract
services/analyzer-csharp/         .NET 8 Minimal API + Roslyn (port 5050)
services/api-python/              FastAPI orchestrator, tree-sitter analyzers (port 8000)
  app/analyzers/                  java.py, typescript.py, scanner.py, common.py
  app/services/                   csharp_client.py, relations.py, mermaid.py, workspace.py
  tests/                          pytest suite incl. schema conformance
apps/web/                         React + TypeScript + Vite + Tailwind UI
  src/components/                 MacroGraph, UmlDiagram, CodeInspector, NodeDetailsPanel, TopBar
  src-tauri/                      Minimal Tauri v2 desktop shell (icons, config, capabilities)
```

Contract changes must be applied to `packages/core-ir/schema.json`, `app/models/ir.py`,
`apps/web/src/types/core-ir.ts` and `services/analyzer-csharp/Models/CoreIr.cs` together — see
[.cursorrules](/C:/source/kodo/.cursorrules).
