import { useCallback, useEffect, useState } from 'react';
import { api } from '../lib/api';
import type { AuditLogEntry } from '../types/deploy';
import { AlertIcon, ShieldIcon, Spinner } from './icons';

interface AuditLogPanelProps {
  /** Bumped by the parent after any audited action so the table re-reads the JSONL log. */
  refreshToken: number;
}

const ACTION_CLASS: Record<string, string> = {
  apply: 'border-sky-400/40 bg-sky-400/10 text-sky-200',
  rollback: 'border-amber-400/40 bg-amber-400/10 text-amber-200',
  deploy_up: 'border-emerald-400/40 bg-emerald-400/10 text-emerald-200',
  deploy_down: 'border-rose-400/40 bg-rose-400/10 text-rose-200',
  git_clone: 'border-violet-400/40 bg-violet-400/10 text-violet-200',
  git_export: 'border-cyan-400/40 bg-cyan-400/10 text-cyan-200',
  verify_build: 'border-sky-400/40 bg-sky-400/10 text-sky-200',
  decision_feedback: 'border-violet-400/40 bg-violet-400/10 text-violet-200',
};

const ACTION_LABEL: Record<string, string> = {
  apply: 'apply',
  rollback: 'rollback',
  deploy_up: 'deploy up',
  deploy_down: 'deploy down',
  git_clone: 'git clone',
  git_export: 'git export',
  verify_build: 'verify build',
  decision_feedback: 'decision feedback',
};

export function AuditLogPanel({ refreshToken }: AuditLogPanelProps) {
  const [entries, setEntries] = useState<AuditLogEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (signal?: AbortSignal) => {
    setError(null);
    try {
      const result = await api.auditLog(100, signal);
      if (!signal?.aborted) {
        setEntries(result.entries);
      }
    } catch (reason) {
      if (!signal?.aborted) {
        setError(reason instanceof Error ? reason.message : String(reason));
      }
    } finally {
      if (!signal?.aborted) {
        setLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    void load(controller.signal);
    return () => controller.abort();
  }, [load, refreshToken]);

  return (
    <section className="rounded-lg border border-ink-700/70 bg-ink-900/40">
      <header className="flex items-center gap-2 border-b border-ink-700/60 px-3 py-2">
        <ShieldIcon className="h-3.5 w-3.5 text-emerald-400" />
        <p className="text-[11.5px] font-semibold text-slate-100">Local Audit Log</p>
        <span className="rounded border border-ink-600 bg-ink-850 px-1.5 py-0.5 text-[9px] text-slate-400">
          default ~/.kodo/audit.jsonl
        </span>
        <button
          type="button"
          onClick={() => void load()}
          disabled={loading}
          className="ml-auto flex items-center gap-1 rounded-md border border-ink-600 px-2 py-1 text-[10px] text-slate-300 transition enabled:hover:border-emerald-400/50 enabled:hover:text-emerald-200 disabled:opacity-50"
        >
          {loading ? <Spinner className="h-3 w-3" /> : null}
          Refresh
        </button>
      </header>

      <div className="px-3 py-2">
        {error && (
          <p className="flex items-start gap-1.5 rounded-md border border-rose-400/25 bg-rose-400/[0.06] px-2 py-1 text-[10px] text-rose-200">
            <AlertIcon className="mt-0.5 h-3 w-3 shrink-0" />
            {error}
          </p>
        )}

        <div className="max-h-[240px] overflow-auto rounded-md border border-ink-700/70">
          <table className="w-full border-collapse text-left">
            <thead className="sticky top-0 bg-ink-850/95 text-[9px] uppercase tracking-[0.12em] text-slate-500 backdrop-blur">
              <tr>
                <th className="px-2 py-1.5 font-medium">When</th>
                <th className="px-2 py-1.5 font-medium">Action</th>
                <th className="px-2 py-1.5 font-medium">Summary</th>
                <th className="px-2 py-1.5 font-medium">Files</th>
                <th className="px-2 py-1.5 font-medium">Status</th>
              </tr>
            </thead>
            <tbody>
              {entries.map((entry, index) => (
                <tr
                  key={`${entry.timestamp}-${entry.action}-${index}`}
                  className="border-t border-ink-700/50 align-top"
                >
                  <td className="whitespace-nowrap px-2 py-1 font-mono text-[9.5px] text-slate-500">
                    {formatTimestamp(entry.timestamp)}
                  </td>
                  <td className="px-2 py-1">
                    <span
                      className={`inline-flex whitespace-nowrap rounded border px-1.5 py-0.5 text-[9px] ${
                        ACTION_CLASS[entry.action] ?? 'border-ink-600 bg-ink-850 text-slate-300'
                      }`}
                    >
                      {ACTION_LABEL[entry.action] ?? entry.action}
                    </span>
                  </td>
                  <td className="max-w-[320px] px-2 py-1 text-[10px] leading-relaxed text-slate-300">
                    <span className="line-clamp-2" title={`${entry.summary}\n${entry.rootPath}`}>
                      {entry.summary || '—'}
                    </span>
                  </td>
                  <td className="px-2 py-1 font-mono text-[9.5px] text-slate-500">{entry.filesCount}</td>
                  <td className="px-2 py-1">
                    <span
                      className={`text-[9px] uppercase tracking-wide ${
                        entry.status === 'success' ? 'text-emerald-300' : 'text-rose-300'
                      }`}
                    >
                      {entry.status}
                    </span>
                  </td>
                </tr>
              ))}
              {!loading && entries.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-2 py-3 text-center text-[10px] text-slate-500">
                    No audit entries yet — applies, rollbacks, Docker and Git actions are recorded here.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        <p className="mt-1 text-[9px] leading-relaxed text-slate-600">
          Append-only JSONL outside the repository. Metadata only: no file contents and no tokens.
        </p>
      </div>
    </section>
  );
}

function formatTimestamp(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value.slice(0, 19).replace('T', ' ');
  }
  return parsed.toLocaleString(undefined, {
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}
