import { useEffect, useMemo, useState } from 'react';
import { DiffEditor } from '@monaco-editor/react';
import { api } from '../lib/api';
import { countLineChanges } from '../lib/diff';
import { buildPatchOperations, isDraftEmpty, type Draft } from '../lib/draft';
import type { WorkspaceIR } from '../types/core-ir';
import type { DryRunResponse } from '../types/patching';
import { AlertIcon, DiffIcon, ShieldIcon, Spinner } from './icons';

interface DiffPreviewProps {
  workspace: WorkspaceIR;
  draft: Draft;
  requestId: number;
}

interface DryRunState {
  response: DryRunResponse | null;
  planWarnings: string[];
  pending: boolean;
  error: string | null;
}

const DIFF_OPTIONS_BASE = {
  readOnly: true,
  originalEditable: false,
  automaticLayout: true,
  minimap: { enabled: false },
  fontSize: 12.5,
  fontFamily: '"JetBrains Mono", Consolas, "Cascadia Code", monospace',
  lineHeight: 20,
  scrollBeyondLastLine: false,
  renderOverviewRuler: false,
  overviewRulerLanes: 0,
  scrollbar: { verticalScrollbarSize: 10, horizontalScrollbarSize: 10 },
  padding: { top: 12, bottom: 12 },
  lineNumbersMinChars: 4,
};

const DEBOUNCE_MS = 220;

export function DiffPreview({ workspace, draft, requestId }: DiffPreviewProps) {
  const [state, setState] = useState<DryRunState>({
    response: null,
    planWarnings: [],
    pending: false,
    error: null,
  });
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [sideBySide, setSideBySide] = useState(true);
  const [rerun, setRerun] = useState(0);
  const [monacoReady, setMonacoReady] = useState(false);

  const dirty = !isDraftEmpty(draft);
  const plan = useMemo(() => buildPatchOperations(workspace, draft), [workspace, draft]);

  useEffect(() => {
    let alive = true;
    void import('../lib/monaco-setup').then(() => {
      if (alive) {
        setMonacoReady(true);
      }
    });
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    if (!dirty) {
      setState({ response: null, planWarnings: [], pending: false, error: null });
      return;
    }

    if (plan.operations.length === 0) {
      setState({
        response: { patches: [], warnings: [] },
        planWarnings: plan.warnings,
        pending: false,
        error: null,
      });
      return;
    }

    const controller = new AbortController();
    setState({ response: null, planWarnings: plan.warnings, pending: true, error: null });

    const timer = window.setTimeout(() => {
      api
        .dryRun(workspace.rootPath, plan.operations, controller.signal)
        .then((response) => {
          setState({ response, planWarnings: plan.warnings, pending: false, error: null });
          setSelectedPath((current) => {
            if (current && response.patches.some((patch) => patch.filePath === current)) {
              return current;
            }
            return response.patches[0]?.filePath ?? null;
          });
        })
        .catch((reason: unknown) => {
          if (controller.signal.aborted) {
            return;
          }
          setState({
            response: null,
            planWarnings: plan.warnings,
            pending: false,
            error: reason instanceof Error ? reason.message : String(reason),
          });
        });
    }, DEBOUNCE_MS);

    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [workspace, draft, dirty, plan, requestId, rerun]);

  const patches = state.response?.patches ?? [];
  const selected = patches.find((patch) => patch.filePath === selectedPath) ?? patches[0] ?? null;
  const globalWarnings = [...state.planWarnings, ...(state.response?.warnings ?? [])];
  // Avoid flashing the empty state in the first paint before the debounced effect starts.
  const waiting = state.pending || (dirty && state.response === null && state.error === null);

  return (
    <div className="flex h-full flex-col bg-ink-950">
      <div className="flex items-center gap-2 border-b border-amber-400/20 bg-amber-400/[0.06] px-4 py-2">
        <ShieldIcon className="h-3.5 w-3.5 shrink-0 text-amber-300" />
        <p className="text-[11px] font-medium text-amber-200">
          Dry-Run Mode — No files modified on disk (Apply &amp; Git safety coming in Phase 3c)
        </p>
        <span className="ml-auto shrink-0 font-mono text-[9.5px] text-amber-300/60">memory only</span>
      </div>

      {!dirty ? (
        <EmptyDiff
          title="No pending edits"
          body="Add a field, change an annotation, or connect a relation, then preview the surgical AST diff here."
        />
      ) : waiting ? (
        <div className="flex flex-1 items-center justify-center">
          <span className="flex items-center gap-2 text-xs text-slate-400">
            <Spinner /> computing in-memory patches…
          </span>
        </div>
      ) : state.error ? (
        <EmptyDiff title="Dry-run failed" body={state.error} tone="rose" />
      ) : patches.length === 0 ? (
        <EmptyDiff
          title="No file-level patches proposed"
          body={
            globalWarnings.length > 0
              ? globalWarnings.join(' ')
              : 'The draft only contains edits that cannot be mapped to a source field yet.'
          }
          tone="amber"
        />
      ) : (
        <div className="flex min-h-0 flex-1">
          <aside className="flex w-[268px] shrink-0 flex-col border-r border-ink-700/70 bg-ink-900/50">
            <div className="flex items-center justify-between border-b border-ink-700/60 px-3 py-2">
              <span className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">
                Proposed patches
              </span>
              <span className="font-mono text-[9.5px] text-slate-500">{patches.length}</span>
            </div>

            <ul className="min-h-0 flex-1 space-y-1 overflow-y-auto p-2">
              {patches.map((patch) => {
                const stats = countLineChanges(patch.originalContent, patch.proposedContent);
                const active = selected?.filePath === patch.filePath;
                return (
                  <li key={patch.filePath}>
                    <button
                      type="button"
                      onClick={() => setSelectedPath(patch.filePath)}
                      className={`w-full rounded-md border px-2 py-1.5 text-left transition ${
                        active
                          ? 'border-sky-500/50 bg-sky-500/10'
                          : 'border-transparent hover:border-ink-600 hover:bg-ink-850'
                      }`}
                    >
                      <div className="flex items-center gap-1.5">
                        <span className="min-w-0 flex-1 truncate font-mono text-[10px] text-slate-300">
                          {patch.filePath}
                        </span>
                        {patch.warnings.length > 0 && (
                          <AlertIcon className="h-3 w-3 shrink-0 text-amber-300" />
                        )}
                      </div>
                      <div className="mt-1 flex items-center gap-2 font-mono text-[9px]">
                        <span className="rounded bg-ink-800 px-1 text-slate-500">{patch.language}</span>
                        <span className="text-emerald-300">+{stats.added}</span>
                        <span className="text-rose-300">−{stats.removed}</span>
                      </div>
                    </button>
                    {patch.warnings.length > 0 && (
                      <ul className="mt-1 space-y-0.5 px-2">
                        {patch.warnings.slice(0, 3).map((warning) => (
                          <li key={warning} className="text-[9px] leading-relaxed text-amber-300/80">
                            {warning}
                          </li>
                        ))}
                        {patch.warnings.length > 3 && (
                          <li className="text-[9px] text-amber-300/60">
                            +{patch.warnings.length - 3} more warning(s)
                          </li>
                        )}
                      </ul>
                    )}
                  </li>
                );
              })}
            </ul>

            {globalWarnings.length > 0 && (
              <div className="max-h-[150px] overflow-y-auto border-t border-ink-700/60 px-3 py-2">
                <p className="text-[9px] font-semibold uppercase tracking-[0.14em] text-amber-300/70">
                  Draft notes
                </p>
                <ul className="mt-1 space-y-1">
                  {globalWarnings.map((warning) => (
                    <li key={warning} className="text-[9px] leading-relaxed text-slate-500">
                      {warning}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </aside>

          <div className="flex min-w-0 flex-1 flex-col">
            <div className="flex items-center gap-3 border-b border-ink-700/70 bg-ink-900/60 px-3 py-2">
              <DiffIcon className="h-3.5 w-3.5 shrink-0 text-sky-400" />
              <span className="min-w-0 flex-1 truncate font-mono text-[11px] text-slate-300">
                {selected?.filePath}
              </span>
              {selected && (
                <span className="hidden shrink-0 text-[10px] text-slate-500 lg:block">{selected.summary}</span>
              )}

              <div className="flex shrink-0 items-center gap-1 rounded-md border border-ink-700 p-0.5">
                <ToggleButton active={sideBySide} onClick={() => setSideBySide(true)}>
                  Side-by-side
                </ToggleButton>
                <ToggleButton active={!sideBySide} onClick={() => setSideBySide(false)}>
                  Inline
                </ToggleButton>
              </div>

              <button
                type="button"
                onClick={() => setRerun((value) => value + 1)}
                className="shrink-0 rounded-md border border-ink-600 px-2 py-1 text-[10px] text-slate-300 transition hover:border-sky-500/50 hover:text-sky-200"
              >
                Re-run
              </button>
            </div>

            {selected && selected.warnings.length > 0 && (
              <div className="flex max-h-[92px] flex-col gap-1 overflow-y-auto border-b border-amber-400/15 bg-amber-400/[0.05] px-3 py-1.5">
                {selected.warnings.map((warning) => (
                  <p key={warning} className="flex items-start gap-1.5 text-[9.5px] leading-relaxed text-amber-200/80">
                    <AlertIcon className="mt-0.5 h-3 w-3 shrink-0 text-amber-300" />
                    {warning}
                  </p>
                ))}
              </div>
            )}

            <div className="min-h-0 flex-1">
              {selected && monacoReady ? (
                <DiffEditor
                  height="100%"
                  language={monacoLanguage(selected.language)}
                  original={selected.originalContent}
                  modified={selected.proposedContent}
                  originalModelPath={`file:///kodo/original/${encodeURIComponent(selected.filePath)}`}
                  modifiedModelPath={`file:///kodo/modified/${encodeURIComponent(selected.filePath)}`}
                  keepCurrentOriginalModel
                  keepCurrentModifiedModel
                  theme="kodo-dark"
                  options={{ ...DIFF_OPTIONS_BASE, renderSideBySide: sideBySide }}
                  loading={<span className="text-xs text-slate-500">initializing diff editor…</span>}
                />
              ) : (
                <div className="flex h-full items-center justify-center gap-2 text-xs text-slate-500">
                  <Spinner /> initializing diff editor…
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function ToggleButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded px-1.5 py-0.5 text-[9.5px] transition ${
        active ? 'bg-ink-700 text-slate-100' : 'text-slate-500 hover:text-slate-300'
      }`}
    >
      {children}
    </button>
  );
}

function EmptyDiff({ title, body, tone }: { title: string; body: string; tone?: 'rose' | 'amber' }) {
  const color = tone === 'rose' ? 'text-rose-300' : tone === 'amber' ? 'text-amber-300' : 'text-slate-400';
  return (
    <div className="flex flex-1 items-center justify-center px-8">
      <div className="max-w-md text-center">
        <div className="mx-auto mb-3 flex h-11 w-11 items-center justify-center rounded-xl border border-ink-700 bg-ink-900">
          <DiffIcon className="h-5 w-5 text-slate-500" />
        </div>
        <p className={`text-sm font-medium ${color}`}>{title}</p>
        <p className="mt-1 text-[11px] leading-relaxed text-slate-500">{body}</p>
      </div>
    </div>
  );
}

function monacoLanguage(language: string): string {
  switch (language) {
    case 'java':
    case 'typescript':
    case 'javascript':
    case 'csharp':
      return language;
    default:
      return 'plaintext';
  }
}
