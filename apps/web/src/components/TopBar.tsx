import type { FormEvent } from 'react';
import { api } from '../lib/api';
import { STACK_META } from '../lib/layers';
import type { AuthUser, WorkspaceStorage, WorkspaceSummary } from '../types/account';
import type { WorkspaceIR } from '../types/core-ir';
import type { HealthState } from '../hooks/useHealth';
import { FolderIcon, LogoMark, ScanIcon, SparkIcon, Spinner, DecisionIcon, ShieldIcon } from './icons';
import { HealthChip } from './HealthScore';
import { WorkspaceSwitcher } from './WorkspaceSwitcher';

interface TopBarProps {
  path: string;
  onPathChange: (value: string) => void;
  onScan: () => void;
  scanning: boolean;
  /** Opens the local-only, zero-copy folder browser (never rendered in SaaS mode). */
  onBrowse: () => void;
  health: HealthState;
  workspace: WorkspaceIR | null;
  /** Provider label shown on the AI Copilot pill (DeepSeek Cloud / Local On-Prem / Not Configured). */
  aiLabel: string;
  aiConfigured: boolean;
  /** Phase 10 System 1 (Laya) advisory layer status. */
  systemOneLabel: string;
  systemOneEnabled: boolean;
  onOpenAiSettings: () => void;
  /** Opens the Phase 15 MCP setup drawer (read-only server for AI coding agents). */
  onOpenMcp: () => void;
  mode: string;
  authenticated: boolean;
  authUser: AuthUser | null;
  githubOAuthConfigured: boolean;
  onSignOut: () => void;
  workspaces: WorkspaceSummary[];
  workspaceStorage: WorkspaceStorage | null;
  onSelectWorkspace: (workspace: WorkspaceSummary) => void;
  onDeleteWorkspace: (workspace: WorkspaceSummary) => void;
  onWorkspaceCloned: (localPath: string) => void;
  onRefreshWorkspaces: () => void;
}

export function TopBar({
  path,
  onPathChange,
  onScan,
  scanning,
  onBrowse,
  health,
  workspace,
  aiLabel,
  aiConfigured,
  systemOneLabel,
  systemOneEnabled,
  onOpenAiSettings,
  onOpenMcp,
  mode,
  authenticated,
  authUser,
  githubOAuthConfigured,
  onSignOut,
  workspaces,
  workspaceStorage,
  onSelectWorkspace,
  onDeleteWorkspace,
  onWorkspaceCloned,
  onRefreshWorkspaces,
}: TopBarProps) {
  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (!scanning && path.trim()) {
      onScan();
    }
  };

  const roslynReachable = health.data?.analyzers?.csharp?.reachable ?? false;

  return (
    <header className="z-20 flex flex-wrap items-center gap-x-5 gap-y-3 border-b border-ink-700/70 bg-ink-900/90 px-4 py-3 backdrop-blur">
      <div className="flex items-center gap-3">
        <LogoMark />
        <div className="leading-tight">
          <div className="flex items-baseline gap-1.5 text-[15px] font-semibold tracking-tight text-white">
            Kodo
            <span className="text-slate-600">/</span>
            <span className="text-xs font-medium uppercase tracking-[0.14em] text-sky-300/90">X-Ray</span>
          </div>
          <div className="text-[10px] uppercase tracking-[0.2em] text-slate-500">Architecture Control Center</div>
        </div>
      </div>

      {mode === 'saas' ? (
        <div className="flex min-w-[320px] flex-1 items-center gap-3">
          <WorkspaceSwitcher
            workspaces={workspaces}
            activePath={path}
            storage={workspaceStorage}
            onSelect={onSelectWorkspace}
            onDelete={onDeleteWorkspace}
            onCloned={onWorkspaceCloned}
            onRefresh={onRefreshWorkspaces}
          />
          <span
            className="truncate font-mono text-[10px] text-slate-600"
            title={path || undefined}
          >
            {path || 'No workspace selected — clone a repo or pick one above'}
          </span>
          {scanning && <Spinner className="h-4 w-4 shrink-0 text-sky-300" />}
        </div>
      ) : (
        <form onSubmit={handleSubmit} className="flex min-w-[320px] flex-1 items-center gap-2">
          <div className="relative max-w-2xl flex-1">
            <FolderIcon className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500" />
            <input
              value={path}
              onChange={(event) => onPathChange(event.target.value)}
              spellCheck={false}
              placeholder="C:\path\to\your\project"
              aria-label="Workspace folder path"
              className="w-full rounded-lg border border-ink-600 bg-ink-950/80 py-2 pl-9 pr-3 font-mono text-[12px] text-slate-200 shadow-inner outline-none transition placeholder:text-slate-600 focus:border-sky-500/70 focus:ring-2 focus:ring-sky-500/15"
            />
          </div>
          <button
            type="button"
            onClick={onBrowse}
            disabled={scanning}
            title="Browse folders on the API host or Docker mount — read in place, nothing is copied"
            className="inline-flex items-center gap-1.5 rounded-lg border border-ink-600 bg-ink-850/70 px-3 py-2 text-[12px] font-medium text-slate-300 transition enabled:hover:border-sky-500/60 enabled:hover:text-white disabled:cursor-not-allowed disabled:opacity-50"
          >
            <FolderIcon className="h-4 w-4" />
            Browse…
          </button>
          <button
            type="submit"
            disabled={scanning || !path.trim()}
            className="inline-flex items-center gap-2 rounded-lg bg-sky-500 px-3.5 py-2 text-[12px] font-semibold text-ink-950 transition hover:bg-sky-400 disabled:cursor-not-allowed disabled:bg-ink-600 disabled:text-slate-400"
          >
            {scanning ? <Spinner className="h-4 w-4" /> : <ScanIcon className="h-4 w-4" />}
            {scanning ? 'Scanning…' : 'Scan Project'}
          </button>
        </form>
      )}

      <div className="flex items-center gap-3">
        {mode === 'saas' ? (
          authenticated && authUser ? (
            <UserPill user={authUser} onSignOut={onSignOut} />
          ) : null
        ) : (
          <LocalModeBadge showGithubLink={githubOAuthConfigured} />
        )}
        {workspace && <HealthChip report={workspace.audit} />}
        {workspace && workspace.detectedStacks.length > 0 && (
          <div className="flex items-center gap-1.5">
            {workspace.detectedStacks.map((stack) => (
              <span
                key={stack}
                className="inline-flex items-center gap-1.5 rounded-md border border-ink-600/80 bg-ink-850/80 px-2 py-1 text-[10.5px] font-medium text-slate-300"
              >
                <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: STACK_META[stack].color }} />
                {STACK_META[stack].label}
              </span>
            ))}
          </div>
        )}

        <div className="flex items-center gap-1.5">
          <button
            type="button"
            onClick={onOpenAiSettings}
            title={
              aiConfigured
                ? `AI Copilot · ${aiLabel} — click to change provider, models or API key`
                : 'AI Copilot is not configured — click to choose DeepSeek Cloud or a local Ollama/vLLM server'
            }
            className="flex items-center gap-1.5 rounded-full border border-violet-400/30 bg-violet-400/[0.07] px-2.5 py-1 transition hover:border-violet-400/60 hover:bg-violet-400/[0.14]"
          >
            <SparkIcon className="h-3 w-3 text-violet-300" />
            <span className="text-[10.5px] font-medium text-slate-300">AI Copilot</span>
            <span
              className={`h-1.5 w-1.5 rounded-full ${
                aiConfigured ? 'bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.7)]' : 'bg-slate-500'
              }`}
            />
            <span className="text-[10px] text-violet-200/80">{aiLabel}</span>
          </button>
          <button
            type="button"
            onClick={onOpenAiSettings}
            title={
              systemOneEnabled
                ? 'System 1 (Laya) is advisory: triage, routing and pre-diff screening only — the deterministic gates still decide.'
                : 'System 1 (Laya) is disabled — Kodo uses deterministic rules and manual DeepSeek triggers.'
            }
            className="flex items-center gap-1.5 rounded-full border border-sky-400/25 bg-sky-400/[0.06] px-2.5 py-1 transition hover:border-sky-400/60 hover:bg-sky-400/[0.12]"
          >
            <DecisionIcon className="h-3 w-3 text-sky-300" />
            <span className="text-[10.5px] font-medium text-slate-300">System 1</span>
            <span
              className={`h-1.5 w-1.5 rounded-full ${
                systemOneEnabled ? 'bg-sky-400 shadow-[0_0_8px_rgba(56,189,248,0.7)]' : 'bg-slate-500'
              }`}
            />
            <span className="text-[10px] text-sky-200/80">{systemOneLabel}</span>
          </button>
          <button
            type="button"
            onClick={onOpenMcp}
            title="MCP server — connect Cursor, Claude Code or Windsurf to Kodo's read-only architecture tools"
            className="flex items-center gap-1.5 rounded-full border border-emerald-400/25 bg-emerald-400/[0.06] px-2.5 py-1 transition hover:border-emerald-400/60 hover:bg-emerald-400/[0.12]"
          >
            <ShieldIcon className="h-3 w-3 text-emerald-300" />
            <span className="text-[10.5px] font-medium text-slate-300">MCP</span>
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.7)]" />
          </button>
          <StatusPill
            label="FastAPI"
            state={health.status}
            detail={
              health.status === 'online'
                ? `${health.data?.service} v${health.data?.version} · ${api.baseUrlLabel}`
                : `Unreachable at ${api.baseUrlLabel}`
            }
          />
          <StatusPill
            label="Roslyn"
            state={health.status === 'offline' ? 'loading' : roslynReachable ? 'online' : 'offline'}
            detail={
              health.data?.analyzers?.csharp
                ? `${health.data.analyzers.csharp.url} · ${roslynReachable ? 'reachable' : 'offline — C# files will be skipped'}`
                : 'Analyzer status unknown'
            }
          />
        </div>
      </div>
    </header>
  );
}

function UserPill({ user, onSignOut }: { user: AuthUser; onSignOut: () => void }) {
  return (
    <div className="flex items-center gap-1.5 rounded-full border border-ink-600/70 bg-ink-850/70 py-0.5 pl-0.5 pr-1.5">
      {user.avatarUrl ? (
        <img
          src={user.avatarUrl}
          alt=""
          className="h-5 w-5 rounded-full border border-ink-600 object-cover"
        />
      ) : (
        <span className="flex h-5 w-5 items-center justify-center rounded-full bg-sky-500/20 text-[9px] font-semibold uppercase text-sky-200">
          {user.username.slice(0, 1)}
        </span>
      )}
      <span className="max-w-[120px] truncate text-[11px] font-medium text-slate-200">
        @{user.username}
      </span>
      <button
        type="button"
        onClick={onSignOut}
        className="rounded px-1.5 py-0.5 text-[9.5px] text-slate-400 transition hover:bg-rose-500/10 hover:text-rose-200"
      >
        Sign out
      </button>
    </div>
  );
}

function LocalModeBadge({ showGithubLink }: { showGithubLink: boolean }) {
  return (
    <div className="flex items-center gap-1.5 rounded-full border border-emerald-400/25 bg-emerald-400/[0.06] px-2.5 py-1">
      <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
      <span className="text-[10.5px] font-medium text-emerald-200">Local Mode</span>
      {showGithubLink && (
        <a
          href={api.githubLoginUrl()}
          className="rounded px-1 text-[9.5px] text-emerald-300/80 underline-offset-2 transition hover:text-emerald-100 hover:underline"
        >
          Sign in with GitHub
        </a>
      )}
    </div>
  );
}

function StatusPill({
  label,
  state,
  detail,
}: {
  label: string;
  state: 'loading' | 'online' | 'offline';
  detail: string;
}) {
  const dot =
    state === 'online'
      ? 'bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.7)]'
      : state === 'offline'
        ? 'bg-rose-500 shadow-[0_0_8px_rgba(244,63,94,0.6)]'
        : 'bg-amber-400 animate-pulse';

  return (
    <div
      title={detail}
      className="flex cursor-default items-center gap-1.5 rounded-full border border-ink-600/70 bg-ink-850/70 px-2.5 py-1"
    >
      <span className={`h-1.5 w-1.5 rounded-full ${dot}`} />
      <span className="text-[11px] font-medium text-slate-300">{label}</span>
    </div>
  );
}
