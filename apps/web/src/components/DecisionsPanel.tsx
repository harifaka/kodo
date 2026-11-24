import { useCallback, useEffect, useMemo, useState } from 'react';
import { api } from '../lib/api';
import { toSystemOneOverride } from '../lib/decisionSettings';
import { useSystemOneSettings } from '../hooks/useSystemOneSettings';
import {
  confidencePercent,
  decisionTypeMeta,
  diffStatusMeta,
  riskMeta,
  routeMeta,
} from '../lib/decision';
import type {
  DecisionRecordSummary,
  DecisionType,
  RouteTaskResponse,
} from '../types/decision';
import type { WorkspaceIR } from '../types/core-ir';
import { AlertIcon, CheckIcon, DecisionIcon, Spinner } from './icons';

interface DecisionsPanelProps {
  rootPath: string;
  workspace: WorkspaceIR;
}

const OVERRIDE_ROUTES = [
  'deterministic_ast',
  'template_builder',
  'deepseek_code',
  'deepseek_reasoning',
  'human_review',
];

const FILTERS: Array<{ id: 'all' | DecisionType; label: string }> = [
  { id: 'all', label: 'All' },
  { id: 'audit_triage', label: 'Audit triage' },
  { id: 'task_route', label: 'Task route' },
  { id: 'diff_safety', label: 'Diff safety' },
];

export function DecisionsPanel({ rootPath, workspace }: DecisionsPanelProps) {
  const [decisions, setDecisions] = useState<DecisionRecordSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [filter, setFilter] = useState<'all' | DecisionType>('all');
  const [refreshToken, setRefreshToken] = useState(0);

  const [intent, setIntent] = useState('');
  const [routing, setRouting] = useState(false);
  const [routeResult, setRouteResult] = useState<RouteTaskResponse | null>(null);
  const systemOneSettings = useSystemOneSettings();

  const refresh = useCallback(() => setRefreshToken((value) => value + 1), []);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    api
      .decisions(
        {
          rootPath,
          limit: 60,
          ...(filter === 'all' ? {} : { decisionType: filter }),
        },
        controller.signal,
      )
      .then((result) => {
        if (!controller.signal.aborted) {
          setDecisions(result.decisions);
        }
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setError(reason instanceof Error ? reason.message : String(reason));
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setLoading(false);
        }
      });
    return () => controller.abort();
  }, [filter, refreshToken, rootPath]);

  const routeTask = async () => {
    const goal = intent.trim();
    if (!goal || routing) {
      return;
    }
    setRouting(true);
    setError(null);
    setRouteResult(null);
    try {
      const result = await api.decisionRouteTask({
        rootPath,
        intent: goal,
        workspaceIr: workspace,
        systemOneConfig: toSystemOneOverride(systemOneSettings),
      });
      setRouteResult(result);
      setIntent('');
      refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setRouting(false);
    }
  };

  const exportTraining = async () => {
    setError(null);
    try {
      const text = await api.decisionExportTraining();
      const lines = text.split('\n').filter((line) => line.trim()).length;
      if (lines === 0) {
        setNotice('No confirmed ADRs yet — accept or override a decision first.');
        return;
      }
      const blob = new Blob([text], { type: 'application/x-ndjson' });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = 'kodo-laya-training.jsonl';
      anchor.click();
      URL.revokeObjectURL(url);
      setNotice(`Exported ${lines} confirmed ADR(s) as JSONL.`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  };

  const confirmed = decisions.filter((decision) => decision.feedbackStatus !== 'pending').length;
  const accepted = useMemo(
    () => decisions.filter((decision) => decision.feedbackStatus === 'accepted').length,
    [decisions],
  );

  return (
    <div className="flex h-full flex-col overflow-y-auto bg-ink-950">
      <div className="border-b border-ink-700/70 bg-ink-900/50 px-4 py-3">
        <div className="flex flex-wrap items-center gap-2">
          <DecisionIcon className="h-4 w-4 text-sky-300" />
          <h2 className="text-[12.5px] font-semibold text-white">Decisions (ADR)</h2>
          <span className="rounded border border-sky-400/25 bg-sky-400/[0.07] px-1.5 py-0.5 text-[9px] text-sky-200">
            System 1 advisory
          </span>
          <span className="text-[9.5px] text-slate-500">
            {decisions.length} record{decisions.length === 1 ? '' : 's'} · {accepted} accepted ·{' '}
            {confirmed - accepted} overridden
          </span>
          <div className="ml-auto flex items-center gap-2">
            <button
              type="button"
              onClick={refresh}
              className="rounded-md border border-ink-600 px-2 py-1 text-[10px] text-slate-300 transition hover:border-sky-500/50 hover:text-sky-200"
            >
              Refresh
            </button>
            <button
              type="button"
              onClick={() => void exportTraining()}
              className="rounded-md border border-emerald-400/40 bg-emerald-400/10 px-2 py-1 text-[10px] font-medium text-emerald-200 transition hover:bg-emerald-400/20"
            >
              Export Training JSONL
            </button>
          </div>
        </div>
        <p className="mt-1 text-[9.5px] leading-relaxed text-slate-500">
          Every System 1 decision is recorded for your account only. Accept/override feedback feeds
          Laya&apos;s local continuous learning and never changes the deterministic gates.
        </p>
      </div>

      <div className="border-b border-ink-700/70 px-4 py-3">
        <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
          Route a task (S1 → S2)
        </p>
        <div className="mt-1.5 flex flex-wrap items-center gap-2">
          <input
            value={intent}
            onChange={(event) => setIntent(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') {
                void routeTask();
              }
            }}
            spellCheck={false}
            placeholder="Add email validation to OrderDto — or: split billing into two services"
            className="min-w-[280px] flex-1 rounded-md border border-ink-600 bg-ink-950/80 px-2.5 py-1.5 font-mono text-[11px] text-slate-200 outline-none transition placeholder:text-slate-600 focus:border-sky-500/60"
          />
          <button
            type="button"
            onClick={() => void routeTask()}
            disabled={routing || !intent.trim()}
            className="flex items-center gap-1.5 rounded-md border border-sky-400/40 bg-sky-400/10 px-2.5 py-1.5 text-[10.5px] font-medium text-sky-100 transition enabled:hover:bg-sky-400/20 disabled:opacity-50"
          >
            {routing ? <Spinner className="h-3 w-3" /> : <DecisionIcon className="h-3 w-3" />}
            {routing ? 'Routing…' : 'Recommend route'}
          </button>
        </div>
        {routeResult && <RouteCard result={routeResult} />}
      </div>

      <div className="flex items-center gap-1 border-b border-ink-700/70 px-4 py-1.5">
        {FILTERS.map((entry) => (
          <button
            key={entry.id}
            type="button"
            onClick={() => setFilter(entry.id)}
            className={`rounded border px-1.5 py-0.5 text-[9.5px] transition ${
              filter === entry.id
                ? 'border-sky-500/40 bg-sky-500/15 text-sky-200'
                : 'border-ink-700/60 bg-ink-950/40 text-slate-500 hover:text-slate-300'
            }`}
          >
            {entry.label}
          </button>
        ))}
        {loading && <Spinner className="ml-2 h-3 w-3 text-slate-500" />}
      </div>

      {(error || notice) && (
        <div className="px-4 py-1.5">
          {error && (
            <p className="flex items-start gap-1.5 text-[10px] leading-relaxed text-rose-300">
              <AlertIcon className="mt-0.5 h-3 w-3 shrink-0" />
              {error}
            </p>
          )}
          {notice && (
            <p className="flex items-start gap-1.5 text-[10px] leading-relaxed text-emerald-300">
              <CheckIcon className="mt-0.5 h-3 w-3 shrink-0" />
              {notice}
            </p>
          )}
        </div>
      )}

      <div className="min-h-0 flex-1 px-4 py-3">
        {decisions.length === 0 && !loading ? (
          <div className="rounded-lg border border-ink-700/60 bg-ink-900/40 px-4 py-6 text-center">
            <DecisionIcon className="mx-auto h-6 w-6 text-slate-600" />
            <p className="mt-2 text-[11.5px] font-medium text-slate-300">No ADRs yet</p>
            <p className="mt-1 text-[10px] leading-relaxed text-slate-500">
              Triage findings in the Audit panel, route a task above, or screen a diff — each advisory
              decision is recorded here.
            </p>
          </div>
        ) : (
          <ul className="space-y-2">
            {decisions.map((decision) => (
              <DecisionRow
                key={decision.id}
                decision={decision}
                onFeedback={refresh}
                onError={(message) => setError(message)}
              />
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function RouteCard({ result }: { result: RouteTaskResponse }) {
  const meta = routeMeta(result.recommendedRoute);
  return (
    <div className="mt-2 rounded-lg border border-sky-400/25 bg-sky-400/[0.05] px-3 py-2">
      <div className="flex flex-wrap items-center gap-2">
        <span className={`rounded border px-1.5 py-0.5 text-[9.5px] font-medium ${meta.className}`}>
          {meta.label}
        </span>
        <span className="font-mono text-[9.5px] text-slate-400">
          {confidencePercent(result.confidence)} confidence · blast radius {result.blastRadius}
        </span>
        {result.escalateToSystem2 && (
          <span className="rounded bg-violet-400/15 px-1.5 py-0.5 text-[9px] text-violet-200">
            escalate to System 2
          </span>
        )}
        {!result.available && (
          <span className="rounded bg-amber-400/15 px-1.5 py-0.5 text-[9px] text-amber-200">
            System 1 offline
          </span>
        )}
      </div>
      <p className="mt-1 text-[10px] leading-relaxed text-slate-300">{result.rationale}</p>
      {result.warning && (
        <p className="mt-1 text-[9.5px] leading-relaxed text-amber-300/80">{result.warning}</p>
      )}
      <AnswerDetails answers={result.answers} />
    </div>
  );
}

function DecisionRow({
  decision,
  onFeedback,
  onError,
}: {
  decision: DecisionRecordSummary;
  onFeedback: () => void;
  onError: (message: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [overriding, setOverriding] = useState(false);
  const [overrideRoute, setOverrideRoute] = useState(OVERRIDE_ROUTES[0]);
  const [note, setNote] = useState('');
  const typeMeta = decisionTypeMeta(decision.decisionType);
  const routeBadge =
    decision.decisionType === 'diff_safety'
      ? diffStatusMeta(decision.recommendedRoute)
      : routeMeta(decision.recommendedRoute);

  const send = async (status: 'accepted' | 'overridden') => {
    setBusy(true);
    onError('');
    try {
      await api.decisionFeedback(decision.id, {
        status,
        ...(status === 'overridden' ? { overrideRoute, note: note.trim() || undefined } : {}),
      });
      setOverriding(false);
      setNote('');
      onFeedback();
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  };

  return (
    <li className="rounded-lg border border-ink-700/70 bg-ink-900/40 px-3 py-2">
      <div className="flex flex-wrap items-center gap-2">
        <span className={`rounded border px-1.5 py-0.5 text-[9px] ${typeMeta.className}`}>
          {typeMeta.label}
        </span>
        <span className="min-w-0 flex-1 truncate text-[11px] font-medium text-slate-200">
          {decision.subject}
        </span>
        <span className={`rounded border px-1.5 py-0.5 text-[9px] ${routeBadge.className}`}>
          {routeBadge.label}
        </span>
        <span className="font-mono text-[9px] text-slate-500">{decision.latencyMs} ms</span>
      </div>

      <div className="mt-1 flex flex-wrap items-center gap-2">
        <ConfidenceMeter value={decision.confidence} />
        <span className="font-mono text-[9px] text-slate-500">{decision.model}</span>
        <span className="text-[9px] text-slate-600">
          {new Date(decision.createdAt).toLocaleString()}
        </span>
        <span
          className={`ml-auto rounded px-1.5 py-0.5 text-[9px] ${
            decision.feedbackStatus === 'accepted'
              ? 'bg-emerald-500/15 text-emerald-200'
              : decision.feedbackStatus === 'overridden'
                ? 'bg-amber-400/15 text-amber-200'
                : 'bg-ink-800 text-slate-500'
          }`}
        >
          {decision.feedbackStatus}
          {decision.overrideRoute ? ` → ${decision.overrideRoute}` : ''}
        </span>
        {decision.feedbackStatus === 'pending' && (
          <div className="flex items-center gap-1">
            <button
              type="button"
              disabled={busy}
              onClick={() => void send('accepted')}
              className="rounded border border-emerald-400/40 bg-emerald-400/10 px-1.5 py-0.5 text-[9px] text-emerald-200 transition enabled:hover:bg-emerald-400/20 disabled:opacity-50"
            >
              Accept
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => setOverriding((value) => !value)}
              className="rounded border border-amber-400/40 bg-amber-400/10 px-1.5 py-0.5 text-[9px] text-amber-200 transition enabled:hover:bg-amber-400/20 disabled:opacity-50"
            >
              Override
            </button>
          </div>
        )}
      </div>

      {overriding && decision.feedbackStatus === 'pending' && (
        <div className="mt-1.5 flex flex-wrap items-center gap-1.5 rounded-md border border-ink-700 bg-ink-950/60 px-2 py-1.5">
          <span className="text-[9px] text-slate-500">Route</span>
          <select
            value={overrideRoute}
            onChange={(event) => setOverrideRoute(event.target.value)}
            className="rounded border border-ink-600 bg-ink-950 px-1.5 py-0.5 font-mono text-[9.5px] text-slate-200"
          >
            {OVERRIDE_ROUTES.map((route) => (
              <option key={route} value={route}>
                {route}
              </option>
            ))}
          </select>
          <input
            value={note}
            onChange={(event) => setNote(event.target.value)}
            placeholder="Why? (optional, exported for calibration)"
            className="min-w-[180px] flex-1 rounded border border-ink-600 bg-ink-950 px-1.5 py-0.5 text-[9.5px] text-slate-200 placeholder:text-slate-600"
          />
          <button
            type="button"
            disabled={busy}
            onClick={() => void send('overridden')}
            className="rounded border border-amber-400/50 bg-amber-400/15 px-2 py-0.5 text-[9px] font-medium text-amber-100 transition enabled:hover:bg-amber-400/25 disabled:opacity-50"
          >
            Save override
          </button>
        </div>
      )}

      <AnswerDetails answers={decision.answers} />
    </li>
  );
}

function ConfidenceMeter({ value }: { value: number }) {
  const percent = Math.round(Math.max(0, Math.min(1, value)) * 100);
  const color = percent >= 78 ? 'bg-emerald-400' : percent >= 55 ? 'bg-amber-400' : 'bg-rose-400';
  return (
    <span
      className="flex items-center gap-1"
      title={`Calibrated System 1 confidence: ${percent}%`}
    >
      <span className="h-1 w-16 overflow-hidden rounded-full bg-ink-700">
        <span className={`block h-full ${color}`} style={{ width: `${percent}%` }} />
      </span>
      <span className="font-mono text-[9px] text-slate-400">{percent}%</span>
    </span>
  );
}

function AnswerDetails({ answers }: { answers: Record<string, { answer: string | null; probabilities: Record<string, number>; confidence: number }> }) {
  const entries = Object.entries(answers);
  if (entries.length === 0) {
    return null;
  }
  return (
    <details className="mt-1.5">
      <summary className="cursor-pointer text-[9px] text-slate-500 transition hover:text-slate-300">
        probability distribution
      </summary>
      <div className="mt-1 grid gap-1 md:grid-cols-2">
        {entries.map(([questionId, answer]) => {
          const sorted = Object.entries(answer.probabilities).sort((left, right) => right[1] - left[1]);
          const risk = riskMeta(answer.answer ?? 'uncertain');
          return (
            <div key={questionId} className="rounded border border-ink-700/60 bg-ink-950/50 px-2 py-1">
              <div className="flex items-center justify-between gap-2">
                <span className="font-mono text-[9px] text-slate-500">{questionId}</span>
                <span className="font-mono text-[9px]" style={{ color: risk.color }}>
                  {answer.answer ?? 'n/a'} · {confidencePercent(answer.confidence)}
                </span>
              </div>
              {sorted.length > 0 && (
                <div className="mt-1 space-y-0.5">
                  {sorted.slice(0, 4).map(([option, probability]) => (
                    <div key={option} className="flex items-center gap-1.5">
                      <span className="w-[140px] shrink-0 truncate font-mono text-[8.5px] text-slate-500">
                        {option}
                      </span>
                      <span className="h-1 flex-1 overflow-hidden rounded-full bg-ink-800">
                        <span
                          className="block h-full bg-sky-400/70"
                          style={{ width: `${Math.round(probability * 100)}%` }}
                        />
                      </span>
                      <span className="w-8 shrink-0 text-right font-mono text-[8.5px] text-slate-500">
                        {Math.round(probability * 100)}%
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </details>
  );
}
