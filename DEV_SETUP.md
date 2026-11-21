# Kodo — Developer Setup (Phases 1–6: X-Ray, Audit, Draft Editing, Guarded Apply, Multi-Stack Builder, AI Copilot, Docker Studio)

Phases 1–3b are **zero-write** with respect to the scanned project. Kodo scans a folder, maps Java,
TypeScript, JavaScript and C# sources onto the Core IR, runs a deterministic audit over that IR, and
renders a layer graph, a Mermaid UML diagram, an architecture health score with findings, and a
read-only Monaco source inspector.

Phase 3a adds **macro draft editing**: connect and cut relations on the Macro Graph, with the audit
re-scoring the draft through a stateless API call. Phase 3b adds the **Micro field editor** (business
fields, types, annotations and stack-aware presets) and a **stateless AST dry-run** that returns
proposed file contents for a Monaco side-by-side diff. Draft edits live in the browser; proposed
contents live in API memory.

Phase 3c adds the only write path in Kodo: a **guarded apply** that writes reviewed patches to disk
behind strict path containment, a Git working-tree check, SHA-256 optimistic concurrency, atomic
writes and an in-memory rollback. Every write is explicitly confirmed by a human.

Phase 4 adds the **Multi-Stack Builder**: Jinja2 stack generators turn a versioned
`kodo.blueprint.json` into vertical slices for Spring Boot, C# WPF (MVVM) and Node.js, and expose them
as a scaffold dry-run that reuses the Phase 3c guarded apply. New files are **create-only** — an
existing path aborts the batch with `409 FILE_EXISTS` instead of being overwritten.

Phase 5 adds the **DeepSeek Architecture Copilot**: an OpenAI-compatible client for DeepSeek Cloud or
air-gapped Ollama/vLLM, IR context packing with a hard character budget, and three read-only AI
workflows (spec → blueprint, audit finding → patch, method → implementation). AI output is always a
dry-run plan reviewed in the Monaco diff; the model has no write access.

Phase 6 adds the **Deploy Studio**: deterministic non-root multi-stage Dockerfiles, a compose stack
with healthchecks/`depends_on`/`kodo-net`, a placeholder-only `.env.example`, a local Docker control
panel (`compose up --build`, container health, filterable logs), a Git clone/export adapter with
optional GitHub pull requests, and an append-only local audit log. Generated container files flow
through the same dry-run → Monaco diff → guarded apply → rollback pipeline.

```
apps/web (Vite :5173, or Tauri desktop)
        │  HTTP/JSON
        ▼
services/api-python (FastAPI :8088)      ← Core IR, audit, dry-run + scaffold orchestrator,
        │  HTTP/JSON                         blueprint store, AI Copilot, Deploy Studio, guarded apply
        │  HTTPS/JSON (OpenAI-compatible)    (the only writer)
        ├──▶ DeepSeek Cloud or local Ollama / vLLM (optional, :11434 / :8000)
        ├──▶ Docker CLI + daemon (compose up/down/ps/logs, list args, shell=False)
        ├──▶ GitHub API (pull requests, only when you provide a session token)
        ▼
services/analyzer-csharp (Roslyn :5050)  ← stateless C# / .NET analysis + trivia-preserving /patch
                                            (also re-audits generated WPF slices)
```

---

## 1. Prerequisites

| Tool | Version | Needed for |
| --- | --- | --- |
| Docker Desktop | 4.x+ (Compose v2) | Roslyn analyzer container (recommended) and the Deploy Studio Docker control panel |
| Python | 3.12+ | FastAPI orchestrator, tree-sitter analyzers |
| .NET SDK | 8.0+ | Building/testing the Roslyn analyzer (`net8.0`, rolls forward to newer runtimes) |
| Node.js | 20+ | React / Vite frontend |
| Rust | 1.77+ | **only** for the Tauri desktop build (`rustup`, platform toolchain) |
| Git | any | cloning the repo, the guarded apply safety check and the Git clone/export adapter |

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
     sidebar lists every file the draft would change with line counts, patcher warnings and an apply
     checkbox; the main pane shows the original vs proposed content in a Monaco `DiffEditor`
     (side-by-side or inline).
   - **Git Safety & Apply bar** — above the diff, a pill reports `Git clean (branch: main)`,
     `Git dirty (N modified files)` (click for the file list) or `Not a Git repository`. Choose the
     files to write, press **Apply N Files to Disk**, and confirm the risk dialog if the tree is dirty
     or the folder is not a Git repo. On success Kodo clears the draft, re-scans automatically and
     shows an **Undo / Rollback Last Apply** banner.
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

Nothing in the dry-run pipeline opens a file for writing. Apply-on-disk is Phase 3c and goes through
a separate, guarded endpoint (below).

### Guarded apply & rollback (Phase 3c)

Every disk write goes through `services/api-python/app/services/apply_service.py`. It is the only
module allowed to write workspace files, and it refuses to write anything that has not been reviewed.

**Read-only Git inspection.**

```powershell
curl "http://127.0.0.1:8088/api/v1/git/status?root=C:/work/my-spring-shop"
# {"isGitRepo":true,"branch":"main","isDirty":false,"dirtyFiles":[],"untrackedCount":0,
#  "gitAvailable":true,"warning":null}
```

`git` is invoked with `capture_output=True`, a 5 s timeout, `GIT_TERMINAL_PROMPT=0` and
`GIT_OPTIONAL_LOCKS=0`, so inspection never refreshes `.git/index` and no mutating subcommand is ever
run. A missing `git` binary or a non-repo folder returns `isGitRepo: false` plus a `warning` instead of
an error.

**Apply.** Send the exact `filePath` / `originalSha256` / `proposedContent` triples the dry-run
returned:

```json
{
  "rootPath": "C:/work/my-spring-shop",
  "patches": [
    {
      "filePath": "src/main/java/com/acme/shop/entity/Order.java",
      "expectedSha256": "<originalSha256 from /api/v1/dry-run>",
      "proposedContent": "<proposedContent from /api/v1/dry-run>"
    }
  ],
  "allowDirty": false,
  "allowNonGit": false
}
```

Pre-flight runs **before any byte is written**, in this order:

1. Every path is resolved and must stay inside `rootPath` (no absolute paths, no `..`, no symlink
   escape), must be an existing regular file, and must be ≤ 2 MB (`PATH_REJECTED`, `FILE_TOO_LARGE`,
   `NOT_UTF8`). The proposed content is size-capped too, and duplicate targets are rejected.
2. Git status is inspected. A dirty tree without `allowDirty` → HTTP 409 `GIT_DIRTY` (+ `dirtyFiles`).
   Not a Git repo (or no `git` binary) without `allowNonGit` → HTTP 409 `NOT_A_GIT_REPO`.
3. Every file's current SHA-256 is compared with `expectedSha256`. A single mismatch aborts the whole
   batch with HTTP 409 `STALE_FILE` (+ `paths`) and **nothing** is written.

Writes are atomic (sibling temp file → `fsync` → `os.replace`), keep UTF-8 bytes exactly as produced
(no CRLF/LF translation), and a failure mid-batch restores everything already written. A successful
response is:

```json
{ "applyId": "9f2c…", "appliedFiles": ["src/…/Order.java"], "gitStatus": { … }, "warnings": [] }
```

```powershell
curl -X POST http://127.0.0.1:8088/api/v1/apply -H "Content-Type: application/json" -d "@apply.json"
```

**Rollback.** The last 10 apply batches are kept **in API memory** (`applyId`, `rootPath`, timestamp,
`{filePath, previousContent, writtenSha256}`):

```json
{ "applyId": "9f2c…", "force": false }
```

Rollback re-verifies each file against `writtenSha256` and aborts the entire restore on a mismatch with
HTTP 409 `STALE_FILE` unless `force: true`; it then restores the previous bytes atomically and returns
`{ "restoredFiles": [...] }`. Batches are single-use and are lost when the API restarts — that is why
the UI warns before applying to a non-Git folder.

Error responses always carry a structured `detail` object, which the UI maps to a message:

| HTTP | `code` | Meaning |
| --- | --- | --- |
| 400/404 | `PATH_REJECTED` | Outside `rootPath`, absolute path, missing file or deleted parent. |
| 400 | `DUPLICATE_TARGET` | The same file appears twice in one batch. |
| 400 | `NOT_UTF8` | The file is not valid UTF-8, so a text patch cannot be applied safely. |
| 409 | `GIT_DIRTY` | Uncommitted changes; retry with `allowDirty: true` after explicit confirmation. |
| 409 | `NOT_A_GIT_REPO` | Not a Git repo (or no `git`); retry with `allowNonGit: true`. |
| 409 | `STALE_FILE` | A file changed since the dry-run; re-run the dry-run and review again. |
| 409 | `FILE_EXISTS` | A create-only scaffold patch targets a path that already exists (never overwritten). |
| 413 | `FILE_TOO_LARGE` | Current or proposed content exceeds the 2 MB apply limit. |
| 500 | `WRITE_FAILED` | Disk error; the batch was restored, nothing is half-written. |

### Blueprint & scaffolding (Phase 4)

A blueprint describes a project the same way Kodo thinks about it: a stack, a base package/namespace
and a list of vertical slices. The canonical format lives in
`packages/core-ir/blueprint.schema.json` (`schemaVersion: "1.0"`); Pydantic mirrors it in
`app/models/blueprint.py` and the UI in `apps/web/src/types/blueprint.ts`.

```json
{
  "schemaVersion": "1.0",
  "projectName": "Acme Billing",
  "stack": "spring-boot",
  "basePackageOrNamespace": "com.acme.billing",
  "slices": [
    {
      "name": "Order",
      "fields": [
        { "name": "number", "type": "string", "required": true, "annotations": [] },
        { "name": "total", "type": "decimal", "required": true, "annotations": [] }
      ],
      "dependsOnSlices": ["Customer"],
      "includeTests": true
    }
  ]
}
```

`GET /api/v1/blueprint?root=…` returns `{ "exists": true, "blueprint": { … }, "warnings": [] }` or
`{ "exists": false, "blueprint": null }`. A malformed file degrades to `blueprint: null` plus a
warning — never a 500.

`POST /api/v1/scaffold/dry-run` runs the stack plugin and returns the **standard `DryRunResponse`**
with `isNewFile: true`, `originalContent: ""`, `originalSha256: null` and a `conflict` flag when the
path already exists:

```json
{
  "rootPath": "C:/work/new-shop",
  "blueprint": { "schemaVersion": "1.0", "…": "…" },
  "includeProjectSkeleton": true,
  "saveBlueprint": true
}
```

Apply it exactly like a Phase 3c patch batch, adding `isNewFile` (and `expectedSha256: null`):

```json
{
  "rootPath": "C:/work/new-shop",
  "patches": [
    { "filePath": "src/main/java/com/acme/billing/entity/OrderEntity.java",
      "expectedSha256": null, "proposedContent": "<from the dry-run>", "isNewFile": true }
  ],
  "allowDirty": false,
  "allowNonGit": false
}
```

Create-only pre-flight: the path must stay inside `rootPath` (no `..`, no absolute paths, no symlink
folders), **must not exist** (otherwise the whole batch is rejected with `409 FILE_EXISTS` + `paths`),
and missing parent folders are created one level at a time inside the root. Rollback deletes the files
this batch created (verifying `writtenSha256` unless `force: true`) and prunes folders the batch
created when they are empty — never `rootPath` itself. `kodo.blueprint.json` is the one exception: when
it already exists it is an ordinary SHA-256-verified overwrite.

Generator plugins live in `app/generators/` (`base.py` protocol + registry, `spring_boot.py`,
`csharp_wpf.py`, `nodejs.py`, Jinja2 templates under `templates/<stack>/`). Each plugin is pure: text
in, text out. The test suite writes the 3-service demo for every stack into a temp folder, re-scans it
with the full pipeline and asserts **0 findings and 100/100**.

### AI Copilot (Phase 5)

Configure the provider from the **AI Copilot** pill in the top bar (or with environment variables):

| Mode | Base URL | Suggested models | API key |
| --- | --- | --- | --- |
| DeepSeek Cloud | `https://api.deepseek.com/v1` | `deepseek-chat` / `deepseek-reasoner` | required |
| Local Ollama | `http://localhost:11434/v1` | `deepseek-coder-v2` / `deepseek-r1:8b` | not required |
| Local vLLM / other | `http://localhost:8000/v1` | your served model id | not required |

The API key is stored in the browser tab's `sessionStorage` only. Kodo never writes it to disk, never
logs it and never sends it to the scanned repository. Server operators can instead export
`KODO_LLM_API_KEY` (the UI then shows the provider as *Server env*).

Ollama quick start:

```powershell
ollama pull deepseek-coder-v2
ollama pull deepseek-r1:8b
ollama serve
```

Press **Test Connection** in the drawer — it calls `GET {baseUrl}/models` and lists the reachable
models. Use the exact model id Ollama reports (e.g. `qwen2.5:3b`); a mismatched id returns HTTP 404 from
the provider as a structured `PROVIDER_ERROR`.

The three workflows are read-only and always land in the existing review surfaces:

| Endpoint | UI entry point | Result |
| --- | --- | --- |
| `POST /api/v1/ai/spec-to-blueprint` | Builder → **AI Generate from Spec** | validated `Blueprint` + rationale, loaded into the Builder for editing |
| `POST /api/v1/ai/audit-fix` | **Fix with AI** on an audit finding | `DryRunResponse` patches + `explanation` → Diff Preview |
| `POST /api/v1/ai/implement-method` | **AI Implement** next to a method | one-file `DryRunResponse` → Diff Preview |
| `POST /api/v1/ai/test-connection` | **Test Connection** in the drawer | `{ ok, provider, baseUrl, models }` |

Request shape (`llmConfig` is optional and overrides the environment for that request only):

```json
{
  "rootPath": "C:/work/my-shop",
  "finding": { "id": "LAYER_VIOLATION:…", "ruleId": "LAYER_VIOLATION", "…": "…" },
  "workspaceIr": { "nodes": [], "relations": [], "…": "…" },
  "llmConfig": {
    "baseUrl": "https://api.deepseek.com/v1",
    "apiKey": "sk-…",
    "codeModel": "deepseek-chat",
    "reasoningModel": "deepseek-reasoner",
    "timeoutSeconds": 90
  }
}
```

Guardrails:

- The model only sees compact Core IR context (stacks, health, findings, signatures, relations — capped
  at `KODO_LLM_MAX_CONTEXT_CHARS`, default 24 000) plus at most three affected files (2 MB cap, path
  containment enforced). It never receives the whole workspace.
- Blueprint output is validated against the Phase 4 Pydantic model with exactly one automatic repair
  retry; a second failure returns `422 INVALID_BLUEPRINT` with field-level details. Patches may only
  touch files Kodo provided, otherwise `422 INVALID_PATCH` — no new files, no traversal.
- `originalContent` / `originalSha256` are computed from disk, so the Git dirty-tree gate, SHA-256
  optimism and rollback behave exactly like the deterministic dry-run. **The AI endpoints never write.**
- Structured errors: `MISSING_API_KEY` / `UNAUTHORIZED` (401), `RATE_LIMITED` (429), `TIMEOUT` (504),
  `UNREACHABLE` (502), `INVALID_JSON` / `INVALID_BLUEPRINT` / `INVALID_PATCH` (422).

Notes:

- Start with a single service/module folder. Limits are 6000 files and 2 MB per file; anything
  skipped is reported in the amber **diagnostics** bar rather than failing the scan.
- Applying needs `git` on PATH for the safety check unless you explicitly override a non-Git folder;
  rollback snapshots live in API memory (last 10 applies) and disappear on restart.
- If the Roslyn service is not running, the scan still succeeds for Java/TS/JS and adds a warning.
- Use the health pills in the top bar to confirm FastAPI and Roslyn reachability.

---

### Deploy Studio, Docker control & Git adapter (Phase 6)

The **Deploy** tab turns an audited workspace into a containerised deployment. Nothing is written
outside the Phase 3c guarded apply: the Docker artifacts are a normal dry-run plan and are reviewed in
the Monaco diff before Apply/Rollback.

**1. Docker Generator**

| Field | Notes |
| --- | --- |
| Stack | `Auto` detects from marker files (`pom.xml`/`build.gradle`, `package.json`, `*.csproj`/`*.sln`/`*.xaml`) |
| Project name | Becomes the compose project, image and container names |
| App port | Host/app port used in `EXPOSE`, the healthcheck URL and the compose mapping |
| Backing services | `PostgreSQL`, `Redis`, `RabbitMQ` — each adds a pinned Alpine image, healthcheck and `depends_on: condition: service_healthy` |
| Overwrite existing | Off: create-only patches (apply returns `409 FILE_EXISTS`). On: SHA-256 verified replacement |

Generated files:

| File | Contents |
| --- | --- |
| `Dockerfile` | Multi-stage, non-root (`USER kodo`), `EXPOSE`, `HEALTHCHECK` — Maven/Temurin 21 JRE Alpine, `node:22-alpine`, or `dotnet/sdk:8.0` → `aspnet:8.0-alpine` |
| `Dockerfile.sidecar` | WPF only: the WPF UI cannot run in Linux containers, so Kodo emits a warning plus an optional Linux sidecar/API template |
| `.dockerignore` | VCS, `.env` (keeping `.env.example`), build output and dependency folders |
| `docker-compose.yml` | App + selected services, `kodo-net` bridge, healthchecks, `${VAR}` interpolation, named volumes |
| `.env.example` | Placeholders only (`change-me-local-only`) — never real credentials |

`POST /api/v1/deploy/dry-run` accepts
`{ rootPath, projectName, stack, appPort, backingServices, overwriteExisting }` and returns the standard
`DryRunResponse` (`isNewFile`, `originalSha256` for overwrites, `warnings`).

**2. Container Control** (`GET /api/v1/deploy/docker/status`, `POST …/up`, `POST …/down`, `GET …/logs`)

- Every Docker command is a list-argument `subprocess.run` with `shell=False`, a validated
  `rootPath` working directory and a timeout; `docker-compose.yml` must exist inside that root.
- `status` reports CLI/daemon reachability, compose presence and a parsed `docker compose ps --format
  json` table; `up` runs `docker compose up -d [--build]`, `down` runs `docker compose down
  [--volumes]`, `logs` clamps `tail` to 1000 and validates the service name (`[A-Za-z0-9_.-]{1,63}`).
- The UI shows a daemon status pill, health badges (green/amber/red), a service dropdown, a text
  filter and a 10-second auto-refresh while the panel is open.

**3. Git & SaaS adapter** (`POST /api/v1/git/clone`, `POST /api/v1/git/export`)

- Clone accepts **HTTPS GitHub/GitLab URLs only** (no `file://`, no `ssh`, no credentials in the URL,
  no shell metacharacters), shallow-clones (`--depth 1 --single-branch`) into
  `KODO_WORKSPACES_DIR` (default `~/.kodo/workspaces/<slug>-<shortid>`) and returns
  `{ localPath, repoUrl, branch }` so the UI scans it immediately.
- The token is passed as a transient `-c http.extraHeader=Authorization: Basic <base64>` argument for
  that one Git invocation — never in the URL, never in `.git/config`, never in logs or responses.
- Export validates the branch name (`[A-Za-z0-9][A-Za-z0-9._/-]*`, no `..`, no `@{`, no `refs/`),
  checks out/creates the branch, stages and commits, and — only with `createPr` + a GitHub `origin`
  + a session token — pushes and opens a pull request through `https://api.github.com`. Without a
  token it completes cleanly as a local branch + commit (`pushed: false`, `prUrl: null`).
- Point self-hosted Git at the allow-list with `KODO_GIT_ALLOWED_HOSTS=git.mycorp.example`.

**4. Local audit log** (`GET /api/v1/audit-log?limit=100`)

- Append-only JSONL at `KODO_AUDIT_LOG_PATH` (default `~/.kodo/audit.jsonl`) — deliberately outside the
  analysed repository.
- Records `apply`, `rollback`, `deploy_up`, `deploy_down`, `git_clone` and `git_export` with
  `{ timestamp, action, rootPath, summary, filesCount, status }`. Never file contents, never tokens
  (credential-shaped fragments are redacted before the line is written).

---

## 4. Desktop app (Tauri v2)

The desktop shell wraps the same frontend. The API and Roslyn services remain separate local
processes through Phase 4.

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
| `KODO_LLM_BASE_URL` | FastAPI process | `https://api.deepseek.com/v1` | OpenAI-compatible endpoint (Ollama/vLLM) |
| `KODO_LLM_API_KEY` | FastAPI process | *(empty)* | DeepSeek key; optional for local servers, never logged |
| `KODO_LLM_CODE_MODEL` | FastAPI process | `deepseek-chat` | Code model for audit fixes / method implementation |
| `KODO_LLM_REASONING_MODEL` | FastAPI process | `deepseek-reasoner` | Reasoning model for spec → blueprint |
| `KODO_LLM_TIMEOUT_SECONDS` | FastAPI process | `90` | Per-request LLM timeout (raise for slow local models) |
| `KODO_LLM_MAX_CONTEXT_CHARS` | FastAPI process | `24000` | Hard IR prompt budget (clamped 2 000–200 000) |
| `KODO_AUDIT_LOG_PATH` | FastAPI process | `~/.kodo/audit.jsonl` | Append-only local audit log (outside the analysed repo) |
| `KODO_WORKSPACES_DIR` | FastAPI process | `~/.kodo/workspaces` | Destination folder for `POST /api/v1/git/clone` |
| `KODO_GIT_ALLOWED_HOSTS` | FastAPI process | GitHub + GitLab only | Extra comma-separated hosts allowed for clone/export |
| `KODO_CSHARP_URL` | Roslyn process | `http://localhost:5050` | Kestrel bind address (overrides `ASPNETCORE_URLS`) |
| `ASPNETCORE_URLS` | Roslyn container | `http://+:5050` | Container bind address |

---

## 6. Tests & validation

```powershell
# Python: parsers, relation resolver, Mermaid generator, audit rules, security,
# Core IR schema conformance, dry-run patchers (Java/TS always; C# when the container is up),
# the guarded apply/rollback suite (needs `git` on PATH), the Phase 4 generator suite
# (generated Spring Boot / Node.js projects must score 100/100; the C# check runs when Roslyn is up),
# the Phase 5 AI Copilot suite (httpx.MockTransport only — no network or API key needed)
# and the Phase 6 Deploy Studio suite (Docker CLI + GitHub API mocked; only local `git` runs)
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

**The apply button is disabled.** Nothing is selected, the dry-run is still running, or there are no
file-level patches. Pick at least one file in the diff sidebar.

**Apply is rejected with `GIT_DIRTY` / `NOT_A_GIT_REPO`.** Commit or stash your changes (or work in a
git-initialised folder) and retry. Kodo only continues if you confirm the risk dialog, which resends
the request with `allowDirty` / `allowNonGit`.

**Apply is rejected with `STALE_FILE`.** A file changed on disk between the dry-run and the apply, so
the whole batch was aborted and nothing was written. Press **Re-run Dry-Run**, review the new diff and
apply again.

**Rollback is rejected with `STALE_FILE`.** A file changed after the apply. Re-scan the workspace, or
use the **Force rollback** action (the API's `force: true`) if you really want to restore the snapshot.

**Rollback says `UNKNOWN_APPLY`.** The API keeps only the last 10 applies in memory and loses them on
restart. Anything not covered by a snapshot must be reverted with Git.

**A finding seems wrong.** Findings are deterministic: the same tree always produces the same ids.
Compare `workspace.audit.findings[].nodeIds` / `edgeKeys` with the graph, and adjust the rule
thresholds in `services/api-python/app/audit/rules/` if the guideline is too strict for your project.

**The AI Copilot pill says "Not Configured".** Click it and pick a preset, or set `KODO_LLM_BASE_URL`
(+ `KODO_LLM_API_KEY` for the cloud) on the FastAPI process. The pill reads *Local On-Prem*,
*DeepSeek Cloud* or *Custom OpenAI* once a Base URL is saved.

**Test Connection returns 401 `MISSING_API_KEY` / `UNAUTHORIZED`.** DeepSeek Cloud needs a key; paste it
in the drawer. Local Ollama/vLLM must use a loopback or private-IP Base URL to be treated as keyless.

**Test Connection returns 502 `UNREACHABLE`.** The server is not running or the Base URL is wrong. For
Ollama: `ollama serve`, and confirm `http://localhost:11434/v1/models` answers in a browser. Inside
Docker use `http://host.docker.internal:11434/v1`.

**`Fix with AI` returns 504 `TIMEOUT`.** Large files + a slow CPU-only model can exceed the default 90 s.
Raise `KODO_LLM_TIMEOUT_SECONDS` (e.g. `300`) and restart the API, or pick a faster/smaller model.

**The provider returns 404 from Ollama.** The configured model id does not exist locally. Copy an id
from Test Connection (for example `qwen2.5:3b`, not the preset's `deepseek-coder-v2`).

**`422 INVALID_BLUEPRINT` even after the repair retry.** Small local models struggle with the strict
schema. Use `deepseek-reasoner` (or another instruction-following model) as the reasoning model, and
check `detail.details` for the exact field that failed validation.

**Deploy Studio says "Docker CLI missing" or "Daemon offline".** Install Docker Desktop (or the Docker
engine + Compose v2 plugin) and start it; `docker version` and `docker info` must both succeed in the
same shell that runs FastAPI. The panel degrades gracefully — scanning, auditing and applying still work.

**`docker compose up` returns `400 NO_COMPOSE_FILE`.** Generate the Docker artifacts, review the diff and
Apply them first; Kodo only runs compose inside a `rootPath` that actually contains `docker-compose.yml`.

**Deploy apply is rejected with `409 FILE_EXISTS`.** The workspace already has a `Dockerfile`,
`docker-compose.yml`, `.dockerignore` or `.env.example`. Enable **Overwrite existing** to update them
through the SHA-256 verified overwrite path (still one atomic, reversible batch).

**Clone is rejected with `400 INVALID_REPO_URL`.** Only `https://github.com/<owner>/<repo>` and
`https://gitlab.com/<owner>/<repo>` are accepted. SSH remotes, `file://`, embedded credentials and
shell metacharacters are refused by design. Self-hosted Git needs `KODO_GIT_ALLOWED_HOSTS`.

**Export returns `502 PUSH_FAILED` / `PR_FAILED`.** The push needs a token with `repo` scope, and the
`origin` remote must be `https://github.com/<owner>/<repo>`. Private repositories and organization
SSO may require an authorized PAT. Kodo never writes the token to `.git/config`; retry with a fresh one.

**Where did the audit log go?** `~/.kodo/audit.jsonl` (or `KODO_AUDIT_LOG_PATH`). It is append-only,
outside your repository, and contains metadata only — no file contents, no tokens. If the folder is not
writable, audit writes are skipped silently rather than failing an apply or a deploy.

**Tauri build fails immediately.** Rust/toolchain prerequisites are missing; the browser workflow
(`npm run dev`) does not require Rust.

**Python 3.14 + tree-sitter.** Wheels exist for 3.12–3.14; on an unsupported interpreter pip may
attempt a source build and require a C compiler.

---

## 8. Repository layout

```
.cursorrules                      Architecture rules (Core IR, layers, guarded writes, generators)
docker-compose.yml                Local Docker stack (analyzer-csharp on :5050)
packages/core-ir/schema.json      Canonical JSON Schema contract
packages/core-ir/blueprint.schema.json  Versioned kodo.blueprint.json contract (Phase 4)
services/analyzer-csharp/         .NET 8 Minimal API + Roslyn, stateless (port 5050, Dockerfile)
  Analysis/                       Roslyn Core IR extraction
  Patching/                       trivia-preserving /patch rewriter (dry-run only)
services/api-python/              FastAPI orchestrator, tree-sitter analyzers (port 8088)
  app/analyzers/                  java.py, typescript.py, scanner.py, common.py
  app/audit/                      engine.py, context.py + rules/ (one file per audit rule)
  app/generators/                 base.py (protocol + registry), spring_boot.py, csharp_wpf.py,
                                  nodejs.py, templates/<stack>/*.j2
  app/models/                     ir.py (Core IR), blueprint.py (versioned kodo.blueprint.json)
  app/llm/                        config.py (env + per-request overrides), client.py (OpenAI-compatible
                                  httpx client), context_packer.py (budgeted IR projection),
                                  prompts.py (system prompts), sources.py (bounded file reads),
                                  workflows.py (spec→blueprint, audit-fix, implement-method), routes.py
  app/patching/                   java_patcher.py, ts_patcher.py, csharp_patcher.py, paths.py, models.py
  app/deploy/                     generator.py (orchestration + detection), spec.py (constants),
                                  dockerfiles.py (multi-stage templates), compose.py (compose/.dockerignore/
                                  .env.example), models.py (control-panel responses),
                                  studio_service.py (dry-run), runner.py (docker compose status/up/down/
                                  logs, shell=False), routes.py (/deploy/*, /audit-log)
  app/services/                   csharp_client.py, relations.py, mermaid.py, workspace.py,
                                  git_safety.py (read-only git), apply_service.py (the only writer),
                                  scaffold_service.py (blueprint → create-only dry-run),
                                  audit_log.py (append-only JSONL), git_remote.py (clone/export),
                                  github_client.py (pull requests), git_errors.py
  app/api/git_routes.py           /git/clone and /git/export endpoints
  tests/                          pytest suite incl. audit rules, schema conformance, dry-run patching,
                                  guarded apply/rollback, stack generators + 100/100 self-audit,
                                  AI Copilot (mocked httpx transport), Deploy Studio (mocked Docker CLI
                                  + GitHub API, real local git)
apps/web/                         React + TypeScript + Vite + Tailwind UI
  src/components/                 MacroGraph, UmlDiagram, CodeInspector, BuilderPanel, SliceEditor,
                                  DeployStudio, DockerControlPanel, GitExportPanel, AuditLogPanel,
                                  NodeDetailsPanel, DiffPreview, DraftToolbar, AuditPanel, HealthScore,
                                  AiSettingsModal, MethodsSection
  src-tauri/                      Minimal Tauri v2 desktop shell (icons, config, capabilities)
```

Contract changes must be applied to `packages/core-ir/schema.json`, `app/models/ir.py`,
`apps/web/src/types/core-ir.ts` and — for node/relation shapes — `services/analyzer-csharp/Models/CoreIr.cs`,
together. See [.cursorrules](/C:/source/kodo/.cursorrules).
