import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api } from '../lib/api';
import type { BrowseEntry, BrowseResponse, BrowseRoot } from '../types/fs';
import {
  AlertIcon,
  ChevronIcon,
  CloseIcon,
  CopyIcon,
  FolderIcon,
  ScanIcon,
  Spinner,
} from './icons';
import { ProjectStackBadges } from './ProjectStackBadges';

interface FolderBrowserModalProps {
  open: boolean;
  onClose: () => void;
  /** Fills the workspace path input and immediately runs Scan Project. */
  onSelect: (path: string) => void;
}

const ENV_SNIPPETS = {
  windows: 'KODO_LOCAL_PROJECTS_DIR=C:\\Projects',
  posix: 'KODO_LOCAL_PROJECTS_DIR=~/projects',
} as const;

function normalize(path: string): string {
  return path.replace(/[\\/]+/g, '/').replace(/\/+$/, '').toLowerCase();
}

function isSameOrInside(candidate: string, parent: string): boolean {
  const child = normalize(candidate);
  const base = normalize(parent);
  return child === base || child.startsWith(`${base}/`);
}

/** Breadcrumb segments relative to the active root, so the UI never walks above a browse root. */
function breadcrumbs(currentPath: string, roots: BrowseRoot[]): BrowseRoot[] {
  if (!currentPath || roots.length === 0) {
    return [];
  }
  const root = roots.find((entry) => isSameOrInside(currentPath, entry.path)) ?? roots[0];
  const separator = root.path.includes('\\') ? '\\' : '/';
  const base = root.path.replace(/[\\/]+$/, '');
  const remainder = currentPath.toLowerCase().startsWith(base.toLowerCase())
    ? currentPath.slice(base.length)
    : '';
  const segments = remainder.split(/[\\/]+/).filter(Boolean);

  const items: BrowseRoot[] = [{ label: root.label, path: root.path }];
  let accumulated = base;
  for (const segment of segments) {
    accumulated = `${accumulated}${separator}${segment}`;
    items.push({ label: segment, path: accumulated });
  }
  return items;
}

export function FolderBrowserModal({ open, onClose, onSelect }: FolderBrowserModalProps) {
  const [data, setData] = useState<BrowseResponse | null>(null);
  const [currentPath, setCurrentPath] = useState<string | null>(null);
  const [showHidden, setShowHidden] = useState(false);
  const [filter, setFilter] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState<string | null>(null);
  const copyTimer = useRef<number | null>(null);

  const load = useCallback(
    async (path: string | null, hidden: boolean, signal: AbortSignal) => {
      setLoading(true);
      setError(null);
      try {
        const result = await api.browseFilesystem(path, hidden, signal);
        if (!signal.aborted) {
          setData(result);
        }
      } catch (reason) {
        if (!signal.aborted) {
          setError(reason instanceof Error ? reason.message : String(reason));
        }
      } finally {
        if (!signal.aborted) {
          setLoading(false);
        }
      }
    },
    [],
  );

  useEffect(() => {
    if (!open) {
      return;
    }
    setFilter('');
    setError(null);
    setCopied(null);
    setCurrentPath(null);
    setShowHidden(false);
  }, [open]);

  useEffect(() => {
    if (!open) {
      return;
    }
    const controller = new AbortController();
    void load(currentPath, showHidden, controller.signal);
    return () => controller.abort();
  }, [open, currentPath, showHidden, load]);

  useEffect(() => {
    if (!open) {
      return;
    }
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        onClose();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  useEffect(
    () => () => {
      if (copyTimer.current !== null) {
        window.clearTimeout(copyTimer.current);
      }
    },
    [],
  );

  const entries = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    const list: BrowseEntry[] = data?.entries ?? [];
    return needle ? list.filter((entry) => entry.name.toLowerCase().includes(needle)) : list;
  }, [data?.entries, filter]);

  const crumbs = useMemo(
    () => breadcrumbs(data?.currentPath ?? '', data?.roots ?? []),
    [data?.currentPath, data?.roots],
  );

  if (!open) {
    return null;
  }

  const copy = async (text: string, key: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(key);
      if (copyTimer.current !== null) {
        window.clearTimeout(copyTimer.current);
      }
      copyTimer.current = window.setTimeout(() => setCopied(null), 1600);
    } catch {
      setCopied(null);
    }
  };

  const runtimeLabel = data?.runtime === 'docker' ? 'Docker Mount' : 'Local Filesystem';

  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center bg-ink-950/80 p-4 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="folder-browser-title"
        onClick={(event) => event.stopPropagation()}
        className="flex max-h-[88vh] w-full max-w-[920px] flex-col overflow-hidden rounded-xl border border-ink-600 bg-ink-900 shadow-2xl"
      >
        <div className="flex items-start gap-3 border-b border-ink-700/70 px-4 py-3">
          <FolderIcon className="mt-0.5 h-4 w-4 shrink-0 text-sky-300" />
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <h2 id="folder-browser-title" className="text-[13px] font-semibold text-white">
                Browse folders
              </h2>
              {data && (
                <span className="rounded-full border border-sky-400/30 bg-sky-400/10 px-2 py-0.5 text-[9.5px] font-medium uppercase tracking-wide text-sky-200">
                  {runtimeLabel}
                </span>
              )}
            </div>
            <p className="mt-0.5 text-[10.5px] leading-relaxed text-slate-500">
              Zero-copy: Kodo reads this folder in place on the API host — nothing is uploaded or copied.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close folder browser"
            className="rounded-md p-1 text-slate-500 transition hover:bg-ink-700 hover:text-slate-200"
          >
            <CloseIcon className="h-4 w-4" />
          </button>
        </div>

        {data && data.roots.length > 0 && (
          <div className="flex flex-wrap items-center gap-1.5 border-b border-ink-700/50 px-4 py-2">
            <span className="mr-1 text-[9.5px] uppercase tracking-[0.14em] text-slate-500">Roots</span>
            {data.roots.map((root) => {
              const active = isSameOrInside(data.currentPath, root.path);
              return (
                <button
                  key={root.path}
                  type="button"
                  title={root.path}
                  onClick={() => setCurrentPath(root.path)}
                  className={`max-w-[260px] truncate rounded-full border px-2.5 py-1 text-[10.5px] transition ${
                    active
                      ? 'border-sky-400/60 bg-sky-400/10 text-sky-200'
                      : 'border-ink-600 bg-ink-850/70 text-slate-400 hover:border-ink-500 hover:text-slate-200'
                  }`}
                >
                  {root.label}
                </button>
              );
            })}
          </div>
        )}

        <div className="flex flex-wrap items-center gap-2 border-b border-ink-700/50 px-4 py-2">
          <button
            type="button"
            onClick={() => data?.parentPath && setCurrentPath(data.parentPath)}
            disabled={!data?.parentPath || loading}
            className="inline-flex items-center gap-1 rounded-md border border-ink-600 bg-ink-950/60 px-2 py-1 text-[10.5px] text-slate-300 transition enabled:hover:border-sky-500/60 enabled:hover:text-white disabled:cursor-not-allowed disabled:opacity-40"
          >
            <ChevronIcon className="h-3 w-3 rotate-90" />
            Up
          </button>

          <nav className="flex min-w-0 flex-1 flex-wrap items-center gap-0.5 font-mono text-[10.5px] text-slate-500">
            {crumbs.map((crumb, index) => (
              <span key={`${crumb.path}-${index}`} className="flex min-w-0 items-center gap-0.5">
                {index > 0 && <span className="text-slate-700">/</span>}
                <button
                  type="button"
                  onClick={() => setCurrentPath(crumb.path)}
                  className="max-w-[180px] truncate rounded px-1 py-0.5 transition hover:bg-ink-800 hover:text-slate-200"
                  title={crumb.path}
                >
                  {crumb.label}
                </button>
              </span>
            ))}
          </nav>

          <input
            value={filter}
            onChange={(event) => setFilter(event.target.value)}
            placeholder="Filter folders…"
            spellCheck={false}
            aria-label="Filter folders in this directory"
            className="w-[170px] rounded-md border border-ink-600 bg-ink-950/80 px-2.5 py-1 text-[11px] text-slate-200 outline-none transition placeholder:text-slate-600 focus:border-sky-500/60 focus:ring-2 focus:ring-sky-500/10"
          />
          <label className="flex cursor-pointer select-none items-center gap-1.5 text-[10.5px] text-slate-400">
            <input
              type="checkbox"
              checked={showHidden}
              onChange={(event) => setShowHidden(event.target.checked)}
              className="h-3 w-3 accent-sky-500"
            />
            Show hidden
          </label>
          {loading && <Spinner className="h-3.5 w-3.5 text-sky-300" />}
        </div>

        {data && (
          <div className="flex flex-wrap items-center gap-2 border-b border-ink-700/50 bg-ink-850/40 px-4 py-2">
            <div className="min-w-0 flex-1">
              <p className="truncate font-mono text-[11px] text-slate-300" title={data.currentPath}>
                {data.currentPath}
              </p>
              <div className="mt-1 flex items-center gap-2">
                <ProjectStackBadges
                  stacks={data.currentMarkers.stacks}
                  isGitRepo={data.currentMarkers.isGitRepo}
                />
                {data.currentMarkers.stacks.length === 0 && !data.currentMarkers.isGitRepo && (
                  <span className="text-[10px] text-slate-600">No project markers in this folder</span>
                )}
              </div>
            </div>
            <button
              type="button"
              onClick={() => onSelect(data.currentPath)}
              className="inline-flex shrink-0 items-center gap-1.5 rounded-lg bg-sky-500 px-3 py-1.5 text-[11.5px] font-semibold text-ink-950 transition hover:bg-sky-400"
            >
              <ScanIcon className="h-3.5 w-3.5" />
              Select &amp; Scan Current Folder
            </button>
          </div>
        )}

        {error && (
          <div className="mx-4 mt-3 flex items-start gap-2 rounded-lg border border-rose-500/40 bg-rose-500/[0.08] px-3 py-2">
            <AlertIcon className="mt-0.5 h-3.5 w-3.5 shrink-0 text-rose-400" />
            <p className="text-[11px] leading-relaxed text-rose-200">{error}</p>
          </div>
        )}

        {data?.emptyMountHint && (
          <div className="mx-4 mt-3 rounded-lg border border-amber-400/40 bg-amber-400/[0.07] px-3 py-2.5">
            <div className="flex items-start gap-2">
              <AlertIcon className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-300" />
              <p className="text-[11px] leading-relaxed text-amber-100">{data.hintMessage}</p>
            </div>
            <div className="mt-2 space-y-1.5">
              {(['windows', 'posix'] as const).map((key) => (
                <div
                  key={key}
                  className="flex items-center gap-2 rounded-md border border-ink-700/70 bg-ink-950/70 px-2 py-1"
                >
                  <code className="min-w-0 flex-1 truncate font-mono text-[10.5px] text-slate-300">
                    {ENV_SNIPPETS[key]}
                  </code>
                  <button
                    type="button"
                    onClick={() => void copy(ENV_SNIPPETS[key], key)}
                    className="inline-flex shrink-0 items-center gap-1 rounded border border-ink-600 px-1.5 py-0.5 text-[9.5px] text-slate-400 transition hover:border-sky-500/60 hover:text-slate-100"
                  >
                    <CopyIcon className="h-3 w-3" />
                    {copied === key ? 'Copied' : 'Copy'}
                  </button>
                </div>
              ))}
              <div className="flex items-center gap-2 rounded-md border border-ink-700/70 bg-ink-950/70 px-2 py-1">
                <code className="min-w-0 flex-1 truncate font-mono text-[10.5px] text-slate-300">
                  docker compose up -d
                </code>
                <button
                  type="button"
                  onClick={() => void copy('docker compose up -d', 'compose')}
                  className="inline-flex shrink-0 items-center gap-1 rounded border border-ink-600 px-1.5 py-0.5 text-[9.5px] text-slate-400 transition hover:border-sky-500/60 hover:text-slate-100"
                >
                  <CopyIcon className="h-3 w-3" />
                  {copied === 'compose' ? 'Copied' : 'Copy'}
                </button>
              </div>
            </div>
          </div>
        )}

        <div className="min-h-0 flex-1 overflow-y-auto px-2 py-2">
          {entries.length === 0 && !loading && !error && (
            <p className="px-3 py-6 text-center text-[11px] text-slate-500">
              {data?.emptyMountHint
                ? 'Nothing to browse yet — mount a host folder first.'
                : filter.trim()
                  ? 'No folder matches this filter.'
                  : 'No subfolders here. You can still select this folder.'}
            </p>
          )}
          <ul>
            {entries.map((entry) => (
              <li key={entry.path}>
                <div
                  role="button"
                  tabIndex={0}
                  onClick={() => setCurrentPath(entry.path)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' || event.key === ' ') {
                      event.preventDefault();
                      setCurrentPath(entry.path);
                    }
                  }}
                  className="group flex cursor-pointer items-center gap-2.5 rounded-lg px-2 py-1.5 transition hover:bg-ink-850/80"
                >
                  <FolderIcon className="h-4 w-4 shrink-0 text-slate-500 group-hover:text-sky-300" />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[12px] text-slate-200">{entry.name}</span>
                    <ProjectStackBadges
                      stacks={entry.stacks}
                      isGitRepo={entry.isGitRepo}
                      className="mt-0.5"
                    />
                  </span>
                  {entry.hasSubdirectories && (
                    <ChevronIcon className="h-3 w-3 shrink-0 -rotate-90 text-slate-600" />
                  )}
                  <button
                    type="button"
                    onClick={(event) => {
                      event.stopPropagation();
                      onSelect(entry.path);
                    }}
                    className="inline-flex shrink-0 items-center gap-1 rounded-md border border-sky-500/40 bg-sky-500/[0.08] px-2 py-0.5 text-[10px] font-medium text-sky-200 opacity-0 transition group-hover:opacity-100 focus:opacity-100"
                  >
                    <ScanIcon className="h-3 w-3" />
                    Scan
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </div>

        <div className="flex items-center justify-between gap-3 border-t border-ink-700/70 px-4 py-2 text-[10px] text-slate-500">
          <span>
            {data ? `${data.entries.length} folder${data.entries.length === 1 ? '' : 's'}` : '—'}
            {data?.truncated ? ' · listing truncated, refine with the filter' : ''}
            {showHidden ? ' · hidden folders shown' : ''}
          </span>
          <span>Existing files are never uploaded, copied or modified.</span>
        </div>
      </div>
    </div>
  );
}
