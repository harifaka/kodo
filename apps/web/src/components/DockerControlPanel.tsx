import { useCallback, useEffect, useMemo, useState } from 'react';
import { api } from '../lib/api';
import { HEALTH_TONE_CLASS, containerTone } from '../lib/deploy';
import type { ComposeLogs, DockerStatus } from '../types/deploy';
import { AlertIcon, CheckIcon, DeployIcon, Spinner } from './icons';

interface DockerControlPanelProps {
  rootPath: string;
  /** Bumped after an apply/rollback so the panel re-reads container state. */
  revision?: number;
  /** Notifies the parent that an audited action (up/down) completed. */
  onChanged: () => void;
}

type Action = 'up' | 'down';

const REFRESH_INTERVAL_MS = 10_000;
const TAIL_OPTIONS = [200, 500, 1000];

export function DockerControlPanel({ rootPath, revision = 0, onChanged }: DockerControlPanelProps) {
  const [status, setStatus] = useState<DockerStatus | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [action, setAction] = useState<Action | null>(null);
  const [actionNotice, setActionNotice] = useState<{ tone: 'ok' | 'error'; text: string } | null>(null);
  const [removeVolumes, setRemoveVolumes] = useState(false);
  const [logs, setLogs] = useState<ComposeLogs | null>(null);
  const [logsError, setLogsError] = useState<string | null>(null);
  const [logsBusy, setLogsBusy] = useState(false);
  const [logService, setLogService] = useState('');
  const [logFilter, setLogFilter] = useState('');
  const [logTail, setLogTail] = useState(200);

  const loadStatus = useCallback(
    async (signal?: AbortSignal) => {
      setStatusError(null);
      try {
        const next = await api.dockerStatus(rootPath, signal);
        if (!signal?.aborted) {
          setStatus(next);
        }
      } catch (reason) {
        if (!signal?.aborted) {
          setStatusError(reason instanceof Error ? reason.message : String(reason));
        }
      } finally {
        if (!signal?.aborted) {
          setLoading(false);
        }
      }
    },
    [rootPath],
  );

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    void loadStatus(controller.signal);
    return () => controller.abort();
  }, [loadStatus, revision]);

  useEffect(() => {
    if (!status?.daemonRunning || !status.hasComposeFile) {
      return;
    }
    const timer = window.setInterval(() => {
      void loadStatus();
    }, REFRESH_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [loadStatus, status?.daemonRunning, status?.hasComposeFile]);

  const loadLogs = useCallback(
    async (service: string, tail: number, signal?: AbortSignal) => {
      setLogsBusy(true);
      setLogsError(null);
      try {
        const next = await api.dockerLogs(rootPath, service || null, tail, signal);
        if (!signal?.aborted) {
          setLogs(next);
        }
      } catch (reason) {
        if (!signal?.aborted) {
          setLogsError(reason instanceof Error ? reason.message : String(reason));
        }
      } finally {
        if (!signal?.aborted) {
          setLogsBusy(false);
        }
      }
    },
    [rootPath],
  );

  const runAction = async (kind: Action) => {
    if (action) {
      return;
    }
    setAction(kind);
    setActionNotice(null);
    try {
      const result =
        kind === 'up'
          ? await api.dockerUp(rootPath, true)
          : await api.dockerDown(rootPath, removeVolumes);
      setStatus(result.status);
      setActionNotice(
        result.success
          ? { tone: 'ok', text: `${result.command} completed${result.stdout ? ` · ${firstLine(result.stdout)}` : ''}` }
          : { tone: 'error', text: result.warning ?? `${result.command} failed.` },
      );
      onChanged();
      if (kind === 'up') {
        void loadLogs(logService, logTail);
      }
    } catch (reason) {
      setActionNotice({
        tone: 'error',
        text: reason instanceof Error ? reason.message : String(reason),
      });
    } finally {
      setAction(null);
    }
  };

  const services = useMemo(
    () => Array.from(new Set((status?.containers ?? []).map((container) => container.service).filter(Boolean))),
    [status],
  );

  const filteredLogs = useMemo(() => {
    const needle = logFilter.trim().toLowerCase();
    const lines = (logs?.logs ?? '').split(/\r?\n/);
    const kept = needle ? lines.filter((line) => line.toLowerCase().includes(needle)) : lines;
    return kept.join('\n').trim() || 'No log output yet.';
  }, [logs, logFilter]);

  const daemonReady = Boolean(status?.daemonRunning);
  const composeReady = Boolean(status?.hasComposeFile);
  const busy = action !== null;

  return (
    <section className="rounded-lg border border-ink-700/70 bg-ink-900/40">
      <header className="flex flex-wrap items-center gap-2 border-b border-ink-700/60 px-3 py-2">
        <DeployIcon className="h-3.5 w-3.5 text-sky-400" />
        <p className="text-[11.5px] font-semibold text-slate-100">Container Control</p>
        <DockerPill status={status} loading={loading} />
        <div className="ml-auto flex items-center gap-1.5">
          <button
            type="button"
            onClick={() => void loadStatus()}
            disabled={loading || busy}
            className="flex items-center gap-1 rounded-md border border-ink-600 px-2 py-1 text-[10px] text-slate-300 transition enabled:hover:border-sky-500/50 enabled:hover:text-sky-200 disabled:opacity-50"
          >
            {loading ? <Spinner className="h-3 w-3" /> : <RefreshGlyph />}
            Refresh
          </button>
          <button
            type="button"
            onClick={() => void runAction('up')}
            disabled={busy || !daemonReady || !composeReady}
            className="flex items-center gap-1 rounded-md border border-emerald-400/45 bg-emerald-400/10 px-2 py-1 text-[10px] font-medium text-emerald-100 transition enabled:hover:bg-emerald-400/20 disabled:opacity-40"
          >
            {action === 'up' ? <Spinner className="h-3 w-3" /> : <CheckIcon className="h-3 w-3" />}
            Compose Up (--build)
          </button>
          <button
            type="button"
            onClick={() => void runAction('down')}
            disabled={busy || !daemonReady || !composeReady}
            className="flex items-center gap-1 rounded-md border border-rose-400/40 px-2 py-1 text-[10px] text-rose-200 transition enabled:hover:bg-rose-400/10 disabled:opacity-40"
          >
            {action === 'down' ? <Spinner className="h-3 w-3" /> : null}
            Compose Down
          </button>
        </div>
      </header>

      <div className="space-y-2 px-3 py-2">
        {(statusError || status?.warning) && (
          <p className="flex items-start gap-1.5 rounded-md border border-amber-400/25 bg-amber-400/[0.06] px-2 py-1.5 text-[10px] leading-relaxed text-amber-200">
            <AlertIcon className="mt-0.5 h-3 w-3 shrink-0" />
            {statusError ?? status?.warning}
          </p>
        )}

        {actionNotice && (
          <p
            className={`rounded-md border px-2 py-1.5 text-[10px] leading-relaxed ${
              actionNotice.tone === 'ok'
                ? 'border-emerald-400/25 bg-emerald-400/[0.06] text-emerald-200'
                : 'border-rose-400/25 bg-rose-400/[0.06] text-rose-200'
            }`}
          >
            {actionNotice.text}
          </p>
        )}

        <label className="flex items-center gap-1.5 text-[10px] text-slate-400">
          <input
            type="checkbox"
            checked={removeVolumes}
            onChange={(event) => setRemoveVolumes(event.target.checked)}
            className="h-3 w-3 rounded border-ink-600 bg-ink-950 accent-rose-400"
          />
          Remove named volumes on <span className="font-mono text-slate-300">compose down</span>
        </label>

        <div className="overflow-hidden rounded-md border border-ink-700/70">
          <table className="w-full border-collapse text-left">
            <thead>
              <tr className="bg-ink-850/70 text-[9px] uppercase tracking-[0.12em] text-slate-500">
                <th className="px-2 py-1.5 font-medium">Service</th>
                <th className="px-2 py-1.5 font-medium">Container</th>
                <th className="px-2 py-1.5 font-medium">State</th>
                <th className="px-2 py-1.5 font-medium">Health</th>
                <th className="px-2 py-1.5 font-medium">Ports</th>
              </tr>
            </thead>
            <tbody>
              {(status?.containers ?? []).map((container) => {
                const tone = containerTone(container.health, container.state);
                return (
                  <tr key={`${container.name}-${container.service}`} className="border-t border-ink-700/50">
                    <td className="px-2 py-1 font-mono text-[10px] text-sky-200">{container.service || '—'}</td>
                    <td className="max-w-[180px] truncate px-2 py-1 font-mono text-[10px] text-slate-300">
                      {container.name}
                    </td>
                    <td className="px-2 py-1 text-[10px] text-slate-400">{container.state}</td>
                    <td className="px-2 py-1">
                      <span
                        className={`inline-flex rounded border px-1.5 py-0.5 text-[9px] uppercase tracking-wide ${HEALTH_TONE_CLASS[tone]}`}
                      >
                        {container.health === 'none' ? container.state : container.health}
                      </span>
                    </td>
                    <td className="px-2 py-1 font-mono text-[9.5px] text-slate-500">
                      {container.ports.length > 0 ? container.ports.join(', ') : '—'}
                    </td>
                  </tr>
                );
              })}
              {!loading && (status?.containers ?? []).length === 0 && (
                <tr>
                  <td colSpan={5} className="px-2 py-3 text-center text-[10px] text-slate-500">
                    {composeReady
                      ? 'No containers running for this compose project.'
                      : 'No docker-compose.yml in this workspace yet — generate and apply the Docker files first.'}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        <div className="rounded-md border border-ink-700/70 bg-ink-950/60">
          <div className="flex flex-wrap items-center gap-1.5 border-b border-ink-700/60 px-2 py-1.5">
            <span className="text-[9px] font-semibold uppercase tracking-[0.14em] text-slate-500">Logs</span>
            <select
              value={logService}
              onChange={(event) => setLogService(event.target.value)}
              className="rounded border border-ink-700 bg-ink-950 px-1.5 py-0.5 text-[10px] text-slate-300 outline-none focus:border-sky-500/60"
              aria-label="Log service filter"
            >
              <option value="">All services</option>
              {services.map((service) => (
                <option key={service} value={service}>
                  {service}
                </option>
              ))}
            </select>
            <select
              value={logTail}
              onChange={(event) => setLogTail(Number(event.target.value))}
              className="rounded border border-ink-700 bg-ink-950 px-1.5 py-0.5 text-[10px] text-slate-300 outline-none focus:border-sky-500/60"
              aria-label="Log tail length"
            >
              {TAIL_OPTIONS.map((value) => (
                <option key={value} value={value}>
                  tail {value}
                </option>
              ))}
            </select>
            <input
              value={logFilter}
              onChange={(event) => setLogFilter(event.target.value)}
              placeholder="filter lines…"
              spellCheck={false}
              className="min-w-[110px] flex-1 rounded border border-ink-700 bg-ink-950 px-1.5 py-0.5 font-mono text-[10px] text-slate-200 outline-none placeholder:text-slate-600 focus:border-sky-500/60"
              aria-label="Log text filter"
            />
            <button
              type="button"
              onClick={() => void loadLogs(logService, logTail)}
              disabled={logsBusy || !composeReady}
              className="flex items-center gap-1 rounded border border-ink-600 px-1.5 py-0.5 text-[10px] text-slate-300 transition enabled:hover:border-sky-500/50 enabled:hover:text-sky-200 disabled:opacity-40"
            >
              {logsBusy ? <Spinner className="h-3 w-3" /> : <RefreshGlyph />}
              Load
            </button>
          </div>
          {logsError && <p className="px-2 py-1 text-[10px] text-rose-300">{logsError}</p>}
          {logs?.warning && <p className="px-2 py-1 text-[10px] text-amber-300">{logs.warning}</p>}
          <pre className="max-h-[190px] overflow-auto px-2 py-1.5 font-mono text-[9.5px] leading-relaxed text-slate-300">
            {filteredLogs}
          </pre>
        </div>
      </div>
    </section>
  );
}

function DockerPill({ status, loading }: { status: DockerStatus | null; loading: boolean }) {
  const state = loading
    ? { label: 'Checking Docker…', className: 'border-ink-600 bg-ink-850 text-slate-400', dot: 'bg-amber-400 animate-pulse' }
    : !status?.dockerAvailable
      ? { label: 'Docker CLI missing', className: 'border-rose-400/40 bg-rose-400/10 text-rose-200', dot: 'bg-rose-400' }
      : !status.daemonRunning
        ? { label: 'Daemon offline', className: 'border-rose-400/40 bg-rose-400/10 text-rose-200', dot: 'bg-rose-400' }
        : { label: 'Daemon running', className: 'border-emerald-400/40 bg-emerald-400/10 text-emerald-200', dot: 'bg-emerald-400' };

  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[9.5px] ${state.className}`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${state.dot}`} />
      {state.label}
      {status?.hasComposeFile ? <span className="text-slate-500">· compose</span> : null}
    </span>
  );
}

function RefreshGlyph() {
  return (
    <svg viewBox="0 0 24 24" className="h-3 w-3" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden>
      <path d="M20 12a8 8 0 1 1-2.34-5.66" strokeLinecap="round" />
      <path d="M20 4.5V10h-5.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function firstLine(text: string): string {
  return text.split(/\r?\n/).find((line) => line.trim().length > 0)?.trim() ?? '';
}
