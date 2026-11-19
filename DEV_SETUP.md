# Kodo — Developer Setup (Phase 1: Vibe-Code X-Ray)

Phase 1 is a **read-only** architecture visualizer. It scans a folder, maps Java, TypeScript,
JavaScript and C# sources onto the Core IR, and renders a layer graph, a Mermaid UML diagram and a
read-only Monaco source inspector. Nothing is ever written to the scanned project.

```
apps/web (Vite :5173, or Tauri desktop)
        │  HTTP/JSON
        ▼
services/api-python (FastAPI :8088)      ← owner of the Core IR
        │  HTTP/JSON
        ▼
services/analyzer-csharp (Roslyn :5050)  ← stateless C# / WPF / .NET AST extraction (Docker)
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
| `VITE_API_BASE_URL` | `apps/web/.env.local` | `http://localhost:8088` | Orchestrator base URL |
| `KODO_CSHARP_URL` | FastAPI process | `http://localhost:5050` | Roslyn analyzer base URL |
| `KODO_CORS_ORIGINS` | FastAPI process | Vite + Tauri origins | Comma-separated allow-list |
| `KODO_CSHARP_URL` | Roslyn process | `http://localhost:5050` | Kestrel bind address (overrides `ASPNETCORE_URLS`) |
| `ASPNETCORE_URLS` | Roslyn container | `http://+:5050` | Container bind address |

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

**Tauri build fails immediately.** Rust/toolchain prerequisites are missing; the browser workflow
(`npm run dev`) does not require Rust.

**Python 3.14 + tree-sitter.** Wheels exist for 3.12–3.14; on an unsupported interpreter pip may
attempt a source build and require a C compiler.

---

## 8. Repository layout

```
.cursorrules                      Architecture rules (Core IR, layers, read-only Phase 1)
docker-compose.yml                Local Docker stack (analyzer-csharp on :5050)
packages/core-ir/schema.json      Canonical JSON Schema contract
services/analyzer-csharp/         .NET 8 Minimal API + Roslyn, stateless (port 5050, Dockerfile)
services/api-python/              FastAPI orchestrator, tree-sitter analyzers (port 8088)
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
