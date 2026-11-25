import { useState } from 'react';
import { api } from '../lib/api';
import type { WorkspaceStorage, WorkspaceSummary } from '../types/account';
import { AlertIcon, CheckIcon, FolderIcon, Spinner } from './icons';

interface WorkspaceSwitcherProps {
  workspaces: WorkspaceSummary[];
  activePath: string;
  /** Per-user quota snapshot; the usage bar only renders when `enabled` (SaaS). */
  storage: WorkspaceStorage | null;
  onSelect: (workspace: WorkspaceSummary) => void;
  onDelete: (workspace: WorkspaceSummary) => void;
  onCloned: (localPath: string) => void;
  onRefresh: () => void;
}

export function WorkspaceSwitcher({
  workspaces,
  activePath,
  storage,
  onSelect,
  onDelete,
  onCloned,
  onRefresh,
}: WorkspaceSwitcherProps) {
  const [open, setOpen] = useState(false);
  const [repoUrl, setRepoUrl] = useState('');
  const [branch, setBranch] = useState('');
  const [token, setToken] = useState('');
  const [cloning, setCloning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const requestDelete = (workspace: WorkspaceSummary) => {
    const confirmed = window.confirm(
      `Delete "${workspace.name}"?\n\nThis removes the cloned files from your Kodo sandbox (${formatMb(
        workspace.sizeBytes,
      )} MB) and frees the quota. It cannot be undone.`,
    );
    if (confirmed) {
      onDelete(workspace);
    }
  };

  const clone = async () => {
    setCloning(true);
    setError(null);
    try {
      const result = await api.gitClone({
        repoUrl: repoUrl.trim(),
        branch: branch.trim() || undefined,
        token: token.trim() || undefined,
      });
      setRepoUrl('');
      setBranch('');
      setToken('');
      onRefresh();
      onCloned(result.localPath);
      setOpen(false);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setCloning(false);
    }
  };

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="flex items-center gap-2 rounded-lg border border-ink-600 bg-ink-950/80 px-3 py-2 text-[12px] text-slate-200 transition hover:border-sky-500/60"
      >
        <FolderIcon className="h-4 w-4 text-sky-300" />
        <span className="font-medium">My Workspaces</span>
        <span className="rounded bg-ink-700 px-1 font-mono text-[9px] text-slate-300">
          {workspaces.length}
        </span>
        <span className="text-[9px] text-slate-500">{open ? '▴' : '▾'}</span>
      </button>

      {open && (
        <div className="absolute right-0 z-40 mt-2 w-[420px] rounded-xl border border-ink-600 bg-ink-900 p-3 shadow-2xl">
          {storage?.enabled && <StorageBar storage={storage} />}
          <div className="max-h-64 space-y-1 overflow-y-auto">
            {workspaces.length === 0 ? (
              <p className="px-1 py-3 text-[11px] text-slate-500">
                No workspaces yet — clone a repository below to get started.
              </p>
            ) : (
              workspaces.map((workspace) => {
                const active = workspace.localPath === activePath;
                return (
                  <div
                    key={workspace.id}
                    className={`flex items-center gap-2 rounded-lg border px-2 py-1.5 ${
                      active
                        ? 'border-sky-400/40 bg-sky-400/[0.08]'
                        : 'border-transparent hover:border-ink-600 hover:bg-ink-850/60'
                    }`}
                  >
                    <button
                      type="button"
                      onClick={() => {
                        onSelect(workspace);
                        setOpen(false);
                      }}
                      className="min-w-0 flex-1 text-left"
                    >
                      <span className="flex items-center gap-1.5">
                        <span className="truncate text-[11.5px] font-medium text-slate-100">
                          {workspace.name}
                        </span>
                        {workspace.lastHealthScore !== null && (
                          <span
                            className={`rounded px-1 font-mono text-[9px] ${
                              workspace.lastHealthScore >= 80
                                ? 'bg-emerald-400/10 text-emerald-300'
                                : 'bg-amber-400/10 text-amber-300'
                            }`}
                          >
                            {workspace.lastHealthScore}
                          </span>
                        )}
                      </span>
                      <span className="mt-0.5 flex items-center gap-2 text-[9.5px] text-slate-500">
                        <span className="truncate">{workspace.repoUrl ?? workspace.localPath}</span>
                        {workspace.branch && <span className="shrink-0">· {workspace.branch}</span>}
                        {storage?.enabled && workspace.sizeBytes > 0 && (
                          <span className="shrink-0 font-mono">· {formatMb(workspace.sizeBytes)} MB</span>
                        )}
                      </span>
                    </button>
                    <button
                      type="button"
                      title="Delete this workspace and free its disk quota"
                      onClick={() => requestDelete(workspace)}
                      className="shrink-0 rounded px-1.5 py-0.5 text-[10px] text-rose-300/70 transition hover:bg-rose-500/10 hover:text-rose-200"
                    >
                      ✕
                    </button>
                  </div>
                );
              })
            )}
          </div>

          <div className="mt-3 space-y-1.5 border-t border-ink-700/70 pt-3">
            <p className="text-[9px] font-semibold uppercase tracking-[0.14em] text-slate-500">
              Clone repo
            </p>
            <input
              value={repoUrl}
              onChange={(event) => setRepoUrl(event.target.value)}
              placeholder="https://github.com/owner/repo"
              spellCheck={false}
              className={INPUT_CLASS}
              aria-label="Repository URL"
            />
            <div className="flex gap-1.5">
              <input
                value={branch}
                onChange={(event) => setBranch(event.target.value)}
                placeholder="branch (optional)"
                spellCheck={false}
                className={INPUT_CLASS + ' flex-1'}
                aria-label="Clone branch"
              />
              <input
                value={token}
                onChange={(event) => setToken(event.target.value)}
                type="password"
                autoComplete="off"
                placeholder="token (optional)"
                className={INPUT_CLASS + ' flex-1'}
                aria-label="Git token"
              />
            </div>
            <button
              type="button"
              onClick={() => void clone()}
              disabled={cloning || repoUrl.trim().length === 0}
              className="flex w-full items-center justify-center gap-1.5 rounded-md border border-sky-400/50 bg-sky-400/10 px-2 py-1.5 text-[10.5px] font-medium text-sky-100 transition enabled:hover:bg-sky-400/20 disabled:opacity-40"
            >
              {cloning ? <Spinner className="h-3 w-3" /> : <CheckIcon className="h-3 w-3" />}
              {cloning ? 'Cloning…' : 'Clone into my sandbox'}
            </button>
            <p className="text-[9px] leading-relaxed text-slate-600">
              HTTPS GitHub/GitLab only. The token stays in memory for one clone and is never stored.
            </p>
            {error && (
              <p className="flex items-start gap-1 rounded border border-rose-400/25 bg-rose-400/[0.06] px-2 py-1 text-[9.5px] text-rose-200">
                <AlertIcon className="mt-0.5 h-3 w-3 shrink-0" />
                {error}
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

const INPUT_CLASS =
  'w-full rounded-md border border-ink-700 bg-ink-950/80 px-2 py-1 text-[11px] text-slate-200 outline-none transition placeholder:text-slate-600 focus:border-sky-500/60';

function formatMb(bytes: number): number {
  return Math.round(Math.max(0, bytes) / (1024 * 1024));
}

function StorageBar({ storage }: { storage: WorkspaceStorage }) {
  const percent =
    storage.quotaBytes > 0
      ? Math.min(100, Math.round((storage.usedBytes / storage.quotaBytes) * 100))
      : 0;
  const bar =
    percent >= 90 ? 'bg-rose-400' : percent >= 70 ? 'bg-amber-400' : 'bg-emerald-400';

  return (
    <div
      className="mb-2 space-y-1 rounded-lg border border-ink-700/70 bg-ink-950/60 px-2 py-1.5"
      title={`${formatMb(storage.usedBytes)} MB used of ${formatMb(
        storage.quotaBytes,
      )} MB · workspaces older than ${storage.ttlHours}h are cleaned up automatically`}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="text-[9px] font-semibold uppercase tracking-[0.14em] text-slate-500">
          Storage
        </span>
        <span className="font-mono text-[9.5px] text-slate-400">
          {formatMb(storage.usedBytes)} / {formatMb(storage.quotaBytes)} MB ·{' '}
          {storage.workspaceCount}/{storage.maxWorkspaces} repos
        </span>
      </div>
      <div className="h-1 overflow-hidden rounded-full bg-ink-700">
        <div
          className={`h-full rounded-full ${bar} transition-[width]`}
          style={{ width: `${percent}%` }}
        />
      </div>
    </div>
  );
}
