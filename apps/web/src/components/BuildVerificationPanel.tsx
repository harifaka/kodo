import { useEffect, useMemo, useRef, useState } from 'react';
import { api } from '../lib/api';
import type { LlmOverride, PlanPreview } from '../types/ai';
import type {
  BuildDiagnostic,
  BuildPatchInput,
  BuildResult,
  BuildStack,
  BuilderStatus,
} from '../types/build';
import { AlertIcon, BuilderIcon, CheckIcon, CopyIcon, Spinner } from './icons';

interface BuildVerificationPanelProps {
  rootPath: string;
  /** In-memory proposals verified inside the sandbox; nothing is written to the workspace. */
  patches?: BuildPatchInput[];
  /** Explicit stack override; omitted lets the server detect it (workspace + proposed files). */
  stack?: BuildStack;
  /** Jump to a diagnostic's file in the parent (Diff preview selection or Code Inspector). */
  onOpenFile?: (filePath: string, line?: number) => void;
  /** Load an AI build fix into the parent's Diff preview for review and re-verification. */
  onFixReady?: (preview: PlanPreview) => void;
  aiConfigured?: boolean;
  llmConfig?: LlmOverride;
  onVerified?: (result: BuildResult) => void;
  className?: string;
}

type Tone = 'idle' | 'ok' | 'warn' | 'error';

const TONE_CLASS: Record<Tone, string> = {
  idle: 'border-ink-600 bg-ink-800 text-slate-400',
  ok: 'border-emerald-400/40 bg-emerald-400/10 text-emerald-200',
  warn: 'border-amber-400/40 bg-amber-400/10 text-amber-200',
  error: 'border-rose-400/40 bg-rose-400/10 text-rose-200',
};

const MAX_LOG_LINES = 800;

export function BuildVerificationPanel({
  rootPath,
  patches = [],
  stack,
  onOpenFile,
  onFixReady,
  aiConfigured = false,
  llmConfig,
  onVerified,
  className = '',
}: BuildVerificationPanelProps) {
  const [status, setStatus] = useState<BuilderStatus | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [runTests, setRunTests] = useState(false);
  const [logs, setLogs] = useState<string[]>([]);
  const [result, setResult] = useState<BuildResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [terminalOpen, setTerminalOpen] = useState(true);
  const [fixing, setFixing] = useState(false);
  const [copied, setCopied] = useState(false);
  const logRef = useRef<HTMLPreElement | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    api
      .buildStatus(controller.signal)
      .then((value) => {
        setStatus(value);
        setStatusError(null);
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setStatusError(reason instanceof Error ? reason.message : String(reason));
        }
      });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const node = logRef.current;
    if (node) {
      node.scrollTop = node.scrollHeight;
    }
  }, [logs, terminalOpen]);

  const errors = useMemo(
    () => (result ? result.diagnostics.filter((item) => item.severity === 'error').length : 0),
    [result],
  );
  const warnings = useMemo(
    () => (result ? result.diagnostics.filter((item) => item.severity === 'warning').length : 0),
    [result],
  );

  const badge = describeBadge({ status, statusError, result, running, stack });
  const unavailable = Boolean(
    status && (!status.enabled || !status.dockerAvailable || !status.daemonRunning),
  );

  const verify = async () => {
    setRunning(true);
    setError(null);
    setLogs([]);
    setResult(null);
    setTerminalOpen(true);
    try {
      const outcome = await api.buildVerifyStream(
        { rootPath, stack: stack ?? null, patches, runTests },
        {
          onLog: (line) =>
            setLogs((current) => {
              const next = current.length >= MAX_LOG_LINES ? current.slice(-(MAX_LOG_LINES - 1)) : current;
              return [...next, line];
            }),
        },
      );
      setResult(outcome);
      onVerified?.(outcome);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setRunning(false);
    }
  };

  const fixWithAi = async () => {
    if (!result || result.diagnostics.length === 0) {
      return;
    }
    setFixing(true);
    setError(null);
    try {
      const fix = await api.aiFixBuildErrors({
        rootPath,
        stack: result.stack,
        diagnostics: result.diagnostics,
        compilerOutput: result.output,
        patches,
        llmConfig,
      });
      onFixReady?.({
        response: { patches: fix.patches, warnings: fix.warnings },
        label: `Build fix · ${result.stack}`,
        kind: 'ai',
        explanation: fix.explanation,
        modelUsed: fix.modelUsed,
      });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setFixing(false);
    }
  };

  const copyLog = async () => {
    try {
      await navigator.clipboard.writeText(logs.join('\n'));
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard may be unavailable (permissions, insecure context); the log stays selectable.
    }
  };

  return (
    <section
      className={`border-b border-ink-700/70 bg-ink-900/40 px-3 py-2 ${className}`}
      aria-label="Sandboxed build verification"
    >
      <div className="flex flex-wrap items-center gap-2">
        <BuilderIcon className="h-3.5 w-3.5 shrink-0 text-sky-400" />
        <span className="text-[11px] font-semibold text-slate-100">Build Verify</span>
        <span className="rounded border border-ink-600 bg-ink-850 px-1.5 py-0.5 text-[9px] text-slate-400">
          ephemeral · no-network · non-root
        </span>

        <span
          className={`flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[10px] ${TONE_CLASS[badge.tone]}`}
          title={status?.warning ?? statusError ?? undefined}
        >
          {running ? <Spinner className="h-3 w-3" /> : null}
          {badge.label}
        </span>

        <label className="flex items-center gap-1.5 text-[10px] text-slate-300">
          <input
            type="checkbox"
            checked={runTests}
            onChange={(event) => setRunTests(event.target.checked)}
            disabled={running}
            className="h-3 w-3 accent-sky-500"
          />
          Run unit tests
        </label>

        <button
          type="button"
          onClick={() => void verify()}
          disabled={running || unavailable}
          title={
            unavailable
              ? 'The builder image or Docker daemon is unavailable on this host.'
              : 'Compile the staged snapshot in a disposable container'
          }
          className="flex items-center gap-1.5 rounded-md border border-sky-400/50 bg-sky-400/10 px-2.5 py-1 text-[10.5px] font-medium text-sky-100 transition enabled:hover:bg-sky-400/20 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {running ? <Spinner className="h-3 w-3" /> : <CheckIcon className="h-3 w-3" />}
          {running ? 'Verifying…' : 'Verify Build (Sandbox)'}
        </button>

        {patches.length > 0 && (
          <span className="text-[9.5px] text-slate-500">
            {patches.length} proposed file{patches.length === 1 ? '' : 's'} staged in memory
          </span>
        )}

        {result && result.status !== 'unavailable' && (
          <button
            type="button"
            onClick={() => setTerminalOpen((value) => !value)}
            className="ml-auto rounded border border-ink-600 px-1.5 py-0.5 text-[9.5px] text-slate-400 transition hover:border-sky-500/50 hover:text-sky-200"
          >
            {terminalOpen ? 'hide log' : 'show log'}
          </button>
        )}
      </div>

      {status?.warning && !result && (
        <p className="mt-1.5 flex items-start gap-1.5 text-[9.5px] leading-relaxed text-amber-300/80">
          <AlertIcon className="mt-0.5 h-3 w-3 shrink-0" />
          {status.warning}
        </p>
      )}

      {error && (
        <p className="mt-1.5 flex items-start gap-1.5 rounded-md border border-rose-400/25 bg-rose-400/[0.06] px-2 py-1 text-[10px] leading-relaxed text-rose-200">
          <AlertIcon className="mt-0.5 h-3 w-3 shrink-0" />
          {error}
        </p>
      )}

      {(result?.warnings.length ?? 0) > 0 && (
        <ul className="mt-1.5 space-y-0.5">
          {result?.warnings.map((warning) => (
            <li
              key={warning}
              className="flex items-start gap-1.5 text-[9.5px] leading-relaxed text-amber-300/80"
            >
              <AlertIcon className="mt-0.5 h-3 w-3 shrink-0" />
              {warning}
            </li>
          ))}
        </ul>
      )}

      {terminalOpen && (running || logs.length > 0 || (result?.output?.length ?? 0) > 0) && (
        <div className="mt-1.5 overflow-hidden rounded-md border border-ink-700 bg-black/70">
          <div className="flex items-center gap-2 border-b border-ink-700/70 px-2 py-1">
            <span className="font-mono text-[9px] uppercase tracking-[0.12em] text-slate-500">build log</span>
            <span className="font-mono text-[9px] text-slate-600">
              {result ? `${result.image} · network=${result.networkMode}` : 'staging snapshot…'}
            </span>
            <button
              type="button"
              onClick={() => void copyLog()}
              className="ml-auto flex items-center gap-1 rounded px-1.5 py-0.5 text-[9px] text-slate-400 transition hover:text-slate-100"
            >
              <CopyIcon className="h-3 w-3" />
              {copied ? 'copied' : 'copy'}
            </button>
          </div>
          <pre
            ref={logRef}
            className="max-h-[180px] overflow-auto whitespace-pre-wrap break-words px-2 py-1.5 font-mono text-[9.5px] leading-relaxed text-slate-300"
          >
            {logs.length > 0 ? logs.join('\n') : result?.output || '(waiting for output…)'}
          </pre>
        </div>
      )}

      {result && (result.diagnostics.length > 0 || result.status === 'passed') && (
        <div className="mt-1.5">
          <div className="flex flex-wrap items-center gap-2 text-[9.5px] text-slate-500">
            <span>
              {errors} error{errors === 1 ? '' : 's'} · {warnings} warning{warnings === 1 ? '' : 's'}
            </span>
            <span className="font-mono">
              exit {result.exitCode ?? '—'} · {formatDuration(result.durationMs)}
            </span>
            {result.status === 'failed' && aiConfigured && onFixReady && result.diagnostics.length > 0 && (
              <button
                type="button"
                onClick={() => void fixWithAi()}
                disabled={fixing}
                className="ml-auto flex items-center gap-1.5 rounded-md border border-violet-400/50 bg-violet-400/10 px-2 py-0.5 text-[10px] font-medium text-violet-100 transition enabled:hover:bg-violet-400/20 disabled:opacity-50"
              >
                {fixing ? <Spinner className="h-3 w-3" /> : null}
                {fixing ? 'Proposing fix…' : 'Fix Build Errors with AI'}
              </button>
            )}
          </div>

          {result.diagnostics.length > 0 && (
            <ul className="mt-1 max-h-[168px] space-y-0.5 overflow-y-auto rounded-md border border-ink-700/70 bg-ink-950/50 p-1">
              {result.diagnostics.map((diagnostic) => (
                <DiagnosticRow
                  key={`${diagnostic.filePath}:${diagnostic.line}:${diagnostic.column}:${diagnostic.code}:${diagnostic.message}`}
                  diagnostic={diagnostic}
                  onOpenFile={onOpenFile}
                />
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}

function DiagnosticRow({
  diagnostic,
  onOpenFile,
}: {
  diagnostic: BuildDiagnostic;
  onOpenFile?: (filePath: string, line?: number) => void;
}) {
  const isError = diagnostic.severity === 'error';
  const location = diagnostic.line > 0 ? `${diagnostic.line}:${diagnostic.column}` : '—';
  const content = (
    <>
      <span
        className={`shrink-0 rounded px-1 text-[8.5px] font-semibold uppercase tracking-wide ${
          isError ? 'bg-rose-500/15 text-rose-300' : 'bg-amber-400/15 text-amber-200'
        }`}
      >
        {isError ? 'error' : 'warn'}
      </span>
      <span className="min-w-0 flex-1 truncate font-mono text-[9.5px] text-slate-300">
        {diagnostic.filePath}
      </span>
      <span className="shrink-0 font-mono text-[9px] text-slate-500">{location}</span>
      {diagnostic.code && (
        <span className="shrink-0 rounded bg-ink-800 px-1 font-mono text-[8.5px] text-slate-400">
          {diagnostic.code}
        </span>
      )}
      <span className="min-w-0 flex-1 truncate text-[9.5px] text-slate-400" title={diagnostic.message}>
        {diagnostic.message}
      </span>
    </>
  );

  if (!onOpenFile) {
    return <li className="flex items-center gap-1.5 px-1 py-0.5">{content}</li>;
  }

  return (
    <li>
      <button
        type="button"
        onClick={() => onOpenFile(diagnostic.filePath, diagnostic.line)}
        title="Open this file"
        className="flex w-full items-center gap-1.5 rounded px-1 py-0.5 text-left transition hover:bg-ink-800"
      >
        {content}
      </button>
    </li>
  );
}

function describeBadge({
  status,
  statusError,
  result,
  running,
  stack,
}: {
  status: BuilderStatus | null;
  statusError: string | null;
  result: BuildResult | null;
  running: boolean;
  stack?: BuildStack;
}): { label: string; tone: Tone } {
  if (running) {
    return { label: 'Verifying…', tone: 'warn' };
  }
  if (result) {
    if (result.status === 'passed') {
      return { label: `Passed · ${formatDuration(result.durationMs)}`, tone: 'ok' };
    }
    if (result.status === 'failed') {
      const count = result.diagnostics.filter((item) => item.severity === 'error').length;
      return { label: `Failed · ${count} error${count === 1 ? '' : 's'}`, tone: 'error' };
    }
    if (result.status === 'timeout') {
      return { label: 'Timeout', tone: 'error' };
    }
    return { label: 'Builder Offline', tone: 'warn' };
  }
  if (statusError) {
    return { label: 'Builder status unavailable', tone: 'warn' };
  }
  if (!status) {
    return { label: 'Checking builder…', tone: 'idle' };
  }
  if (!status.enabled) {
    return { label: 'Builder Disabled', tone: 'warn' };
  }
  if (!status.dockerAvailable || !status.daemonRunning) {
    return { label: 'Builder Offline', tone: 'warn' };
  }
  if (stack && status.images[stack] === false) {
    return { label: `Image Missing · ${stack}`, tone: 'warn' };
  }
  return { label: 'Builder Ready', tone: 'idle' };
}

function formatDuration(ms: number): string {
  if (!Number.isFinite(ms) || ms <= 0) {
    return '0.0s';
  }
  return `${(ms / 1000).toFixed(1)}s`;
}
