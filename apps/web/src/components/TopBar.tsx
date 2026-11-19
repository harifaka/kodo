import type { FormEvent } from 'react';
import { api } from '../lib/api';
import { STACK_META } from '../lib/layers';
import type { WorkspaceIR } from '../types/core-ir';
import type { HealthState } from '../hooks/useHealth';
import { FolderIcon, LogoMark, ScanIcon, Spinner } from './icons';
import { HealthChip } from './HealthScore';

interface TopBarProps {
  path: string;
  onPathChange: (value: string) => void;
  onScan: () => void;
  scanning: boolean;
  health: HealthState;
  workspace: WorkspaceIR | null;
}

export function TopBar({ path, onPathChange, onScan, scanning, health, workspace }: TopBarProps) {
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
          type="submit"
          disabled={scanning || !path.trim()}
          className="inline-flex items-center gap-2 rounded-lg bg-sky-500 px-3.5 py-2 text-[12px] font-semibold text-ink-950 transition hover:bg-sky-400 disabled:cursor-not-allowed disabled:bg-ink-600 disabled:text-slate-400"
        >
          {scanning ? <Spinner className="h-4 w-4" /> : <ScanIcon className="h-4 w-4" />}
          {scanning ? 'Scanning…' : 'Scan Project'}
        </button>
      </form>

      <div className="flex items-center gap-3">
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
          <StatusPill
            label="FastAPI"
            state={health.status}
            detail={
              health.status === 'online'
                ? `${health.data?.service} v${health.data?.version} · ${api.baseUrl}`
                : `Unreachable at ${api.baseUrl}`
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
