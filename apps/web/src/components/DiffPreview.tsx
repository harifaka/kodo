import { useCallback, useEffect, useMemo, useState } from 'react';
import { DiffEditor } from '@monaco-editor/react';
import { ApiError, api } from '../lib/api';
import { countLineChanges } from '../lib/diff';
import { buildPatchOperations, isDraftEmpty, type Draft } from '../lib/draft';
import type { WorkspaceIR } from '../types/core-ir';
import type { PlanPreview } from '../types/ai';
import type { DryRunResponse, GitStatus } from '../types/patching';
import { AlertIcon, BuilderIcon, CheckIcon, DiffIcon, ShieldIcon, SparkIcon, Spinner } from './icons';

interface DiffPreviewProps {
  workspace: WorkspaceIR;
  draft: Draft;
  requestId: number;
  /** Generated or AI-proposed plan; replaces the draft-derived dry-run while present. */
  plan?: PlanPreview | null;
  onPlanDismiss?: () => void;
  onApplied: (applyId: string, appliedFiles: string[]) => void;
}

interface DryRunState {
  response: DryRunResponse | null;
  planWarnings: string[];
  pending: boolean;
  error: string | null;
}

interface GitState {
  status: GitStatus | null;
  pending: boolean;
  error: string | null;
}

interface ApplyFailure {
  message: string;
  code?: string;
  paths: string[];
  dirtyFiles: string[];
}

interface ConfirmState {
  reason: 'dirty' | 'non-git';
  ack: boolean;
  dirtyFiles: string[];
  note: string | null;
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

export function DiffPreview({
  workspace,
  draft,
  requestId,
  plan: externalPlan = null,
  onPlanDismiss,
  onApplied,
}: DiffPreviewProps) {
  const [state, setState] = useState<DryRunState>({
    response: null,
    planWarnings: [],
    pending: false,
    error: null,
  });
  const [git, setGit] = useState<GitState>({ status: null, pending: true, error: null });
  const [gitNonce, setGitNonce] = useState(0);
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [excluded, setExcluded] = useState<string[]>([]);
  const [sideBySide, setSideBySide] = useState(true);
  const [rerun, setRerun] = useState(0);
  const [monacoReady, setMonacoReady] = useState(false);
  const [applying, setApplying] = useState(false);
  const [applyFailure, setApplyFailure] = useState<ApplyFailure | null>(null);
  const [confirm, setConfirm] = useState<ConfirmState | null>(null);
  const [showDirtyList, setShowDirtyList] = useState(false);

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
    const controller = new AbortController();
    setGit((current) => ({ ...current, pending: true, error: null }));
    api
      .gitStatus(workspace.rootPath, controller.signal)
      .then((status) => setGit({ status, pending: false, error: null }))
      .catch((reason: unknown) => {
        if (controller.signal.aborted) {
          return;
        }
        setGit({
          status: null,
          pending: false,
          error: reason instanceof Error ? reason.message : String(reason),
        });
      });
    return () => controller.abort();
    // Re-inspect whenever the workspace is re-scanned or a fresh dry-run lands, so the pill never
    // shows a stale tree state.
  }, [workspace, gitNonce, state.response]);

  useEffect(() => {
    if (!dirty || externalPlan) {
      if (!externalPlan) {
        setState({ response: null, planWarnings: [], pending: false, error: null });
        setApplyFailure(null);
        setConfirm(null);
      }
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
  }, [workspace, draft, dirty, plan, requestId, rerun, externalPlan]);

  const external = externalPlan?.response ?? null;
  const patches = external ? external.patches : state.response?.patches ?? [];
  const patchPaths = useMemo(() => patches.map((patch) => patch.filePath), [patches]);
  const selectedPatches = useMemo(
    () => patches.filter((patch) => !excluded.includes(patch.filePath)),
    [patches, excluded],
  );
  const selected = patches.find((patch) => patch.filePath === selectedPath) ?? patches[0] ?? null;
  const globalWarnings = external
    ? external.warnings
    : [...state.planWarnings, ...(state.response?.warnings ?? [])];
  const waiting = external ? false : state.pending || (dirty && state.response === null && state.error === null);
  const diffError = external ? null : state.error;
  const hasDiff = external !== null || dirty;
  const allSelected = patchPaths.length > 0 && selectedPatches.length === patchPaths.length;
  const newFileCount = patches.filter((patch) => patch.isNewFile).length;
  const conflictCount = patches.filter((patch) => patch.conflict).length;

  useEffect(() => {
    setExcluded([]);
  }, [state.response, external]);

  useEffect(() => {
    if (!external || external.patches.length === 0) {
      return;
    }
    setSelectedPath(external.patches[0].filePath);
  }, [external]);

  const runApply = useCallback(
    async (override: boolean) => {
      if (selectedPatches.length === 0) {
        return;
      }
      setApplying(true);
      setApplyFailure(null);
      setConfirm(null);

      try {
        const result = await api.apply({
          rootPath: workspace.rootPath,
          patches: selectedPatches.map((patch) => ({
            filePath: patch.filePath,
            expectedSha256: patch.originalSha256 ?? null,
            proposedContent: patch.proposedContent,
            isNewFile: patch.isNewFile ?? false,
          })),
          allowDirty: override,
          allowNonGit: override,
        });
        setApplying(false);
        setExcluded([]);
        setGitNonce((value) => value + 1);
        onApplied(result.applyId, result.appliedFiles);
      } catch (reason) {
        setApplying(false);
        setGitNonce((value) => value + 1);
        const failure = toFailure(reason);
        if (failure.code === 'GIT_DIRTY' || failure.code === 'NOT_A_GIT_REPO') {
          setConfirm({
            reason: failure.code === 'GIT_DIRTY' ? 'dirty' : 'non-git',
            ack: false,
            dirtyFiles: failure.dirtyFiles,
            note: failure.message,
          });
          return;
        }
        setApplyFailure(failure);
      }
    },
    [onApplied, selectedPatches, workspace.rootPath],
  );

  const requestApply = useCallback(() => {
    if (selectedPatches.length === 0) {
      return;
    }
    if (git.status && (!git.status.isGitRepo || git.status.isDirty)) {
      setConfirm({
        reason: git.status.isGitRepo ? 'dirty' : 'non-git',
        ack: false,
        dirtyFiles: git.status.dirtyFiles,
        note: git.status.isGitRepo ? null : git.status.warning,
      });
      return;
    }
    void runApply(false);
  }, [git.status, runApply, selectedPatches.length]);

  const togglePath = (filePath: string) => {
    setExcluded((current) =>
      current.includes(filePath) ? current.filter((path) => path !== filePath) : [...current, filePath],
    );
  };

  const toggleAll = () => {
    setExcluded(allSelected ? patchPaths : []);
  };

  return (
    <div className="relative flex h-full flex-col bg-ink-950">
      <GitSafetyBar
        git={git}
        showDirtyList={showDirtyList}
        onToggleDirtyList={() => setShowDirtyList((value) => !value)}
        selectedCount={selectedPatches.length}
        pending={applying}
        disabled={waiting || selectedPatches.length === 0 || patches.length === 0}
        onApply={requestApply}
      />

      {externalPlan && (
        <div
          className={`border-b px-3 py-1.5 ${
            externalPlan.kind === 'ai'
              ? 'border-violet-400/25 bg-violet-400/[0.06]'
              : 'border-sky-500/25 bg-sky-500/[0.06]'
          }`}
        >
          <div className="flex flex-wrap items-center gap-2">
            {externalPlan.kind === 'ai' ? (
              <SparkIcon className="h-3.5 w-3.5 shrink-0 text-violet-300" />
            ) : (
              <BuilderIcon className="h-3.5 w-3.5 shrink-0 text-sky-400" />
            )}
            <p
              className={`text-[11px] leading-relaxed ${
                externalPlan.kind === 'ai' ? 'text-violet-100' : 'text-sky-100'
              }`}
            >
              {externalPlan.kind === 'ai' ? 'AI proposal' : 'Generated plan'} · {externalPlan.label} ·{' '}
              {patches.length} file
              {patches.length === 1 ? '' : 's'}
              {newFileCount > 0 ? ` · ${newFileCount} new` : ''}
              {externalPlan.modelUsed ? ` · ${externalPlan.modelUsed}` : ''}
            </p>
            {externalPlan.kind === 'scaffold' && conflictCount > 0 && (
              <span className="text-[10px] leading-relaxed text-rose-300">
                {conflictCount} path{conflictCount === 1 ? '' : 's'} already exist — applying is rejected
                with FILE_EXISTS (Kodo never overwrites while scaffolding).
              </span>
            )}
            {onPlanDismiss && (
              <button
                type="button"
                onClick={onPlanDismiss}
                className={`ml-auto shrink-0 rounded px-1.5 text-[10px] transition ${
                  externalPlan.kind === 'ai'
                    ? 'text-violet-300/70 hover:bg-violet-500/10 hover:text-violet-100'
                    : 'text-sky-300/70 hover:bg-sky-500/10 hover:text-sky-100'
                }`}
              >
                dismiss
              </button>
            )}
          </div>
          {externalPlan.kind === 'ai' && (
            <p className="mt-1 max-h-[68px] overflow-y-auto whitespace-pre-wrap text-[10px] leading-relaxed text-violet-100/70">
              {externalPlan.explanation || 'The model returned no explanation.'} — review the diff, then Apply.
              The Git dirty-tree gate, SHA-256 freshness check and rollback still apply.
            </p>
          )}
        </div>
      )}

      {applyFailure && (
        <div className="flex items-start gap-2 border-b border-rose-500/25 bg-rose-500/[0.07] px-4 py-2">
          <AlertIcon className="mt-0.5 h-3.5 w-3.5 shrink-0 text-rose-400" />
          <div className="min-w-0 flex-1">
            <p className="text-[11px] leading-relaxed text-rose-200">{applyFailure.message}</p>
            {applyFailure.paths.length > 0 && (
              <ul className="mt-1 space-y-0.5">
                {applyFailure.paths.map((path) => (
                  <li key={path} className="font-mono text-[9.5px] text-rose-300/80">
                    {path}
                  </li>
                ))}
              </ul>
            )}
          </div>
          {applyFailure.code === 'STALE_FILE' && (
            <button
              type="button"
              onClick={() => {
                setApplyFailure(null);
                setRerun((value) => value + 1);
                setGitNonce((value) => value + 1);
              }}
              className="shrink-0 rounded-md border border-rose-400/40 px-2 py-1 text-[10px] text-rose-200 transition hover:bg-rose-500/10"
            >
              Re-run Dry-Run
            </button>
          )}
          <button
            type="button"
            onClick={() => setApplyFailure(null)}
            className="shrink-0 rounded px-1.5 text-[10px] text-rose-300/70 transition hover:text-rose-200"
          >
            dismiss
          </button>
        </div>
      )}

      {!hasDiff ? (
        <EmptyDiff
          title="No pending edits"
          body="Add a field, change an annotation, or connect a relation, then review the surgical AST diff and apply it to disk — or generate a whole project in the Builder tab."
        />
      ) : waiting ? (
        <div className="flex flex-1 items-center justify-center">
          <span className="flex items-center gap-2 text-xs text-slate-400">
            <Spinner /> computing in-memory patches…
          </span>
        </div>
      ) : diffError ? (
        <EmptyDiff title="Dry-run failed" body={diffError} tone="rose" />
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
          <aside className="flex w-[286px] shrink-0 flex-col border-r border-ink-700/70 bg-ink-900/50">
            <div className="flex items-center justify-between border-b border-ink-700/60 px-3 py-2">
              <label className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">
                <input
                  type="checkbox"
                  checked={allSelected}
                  onChange={toggleAll}
                  aria-label="Select all patch files"
                  className="h-3 w-3 accent-sky-500"
                />
                Apply
              </label>
              <span className="font-mono text-[9.5px] text-slate-500">
                {selectedPatches.length}/{patches.length}
              </span>
            </div>

            <ul className="min-h-0 flex-1 space-y-1 overflow-y-auto p-2">
              {patches.map((patch) => {
                const stats = countLineChanges(patch.originalContent, patch.proposedContent);
                const active = selected?.filePath === patch.filePath;
                const checked = !excluded.includes(patch.filePath);
                return (
                  <li key={patch.filePath} className="flex items-start gap-1.5">
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() => togglePath(patch.filePath)}
                      aria-label={`Apply ${patch.filePath}`}
                      className="mt-2 h-3 w-3 shrink-0 accent-sky-500"
                    />
                    <div className="min-w-0 flex-1">
                      <button
                        type="button"
                        onClick={() => setSelectedPath(patch.filePath)}
                        className={`w-full rounded-md border px-2 py-1.5 text-left transition ${
                          active
                            ? 'border-sky-500/50 bg-sky-500/10'
                            : 'border-transparent hover:border-ink-600 hover:bg-ink-850'
                        } ${checked ? '' : 'opacity-55'}`}
                      >
                        <div className="flex items-center gap-1.5">
                          <span className="min-w-0 flex-1 truncate font-mono text-[10px] text-slate-300">
                            {patch.filePath}
                          </span>
                          {patch.isNewFile && (
                            <span
                              title="Create-only patch: the apply fails with FILE_EXISTS if this path exists"
                              className="shrink-0 rounded bg-emerald-500/15 px-1 py-px text-[8.5px] font-semibold tracking-wide text-emerald-300"
                            >
                              NEW
                            </span>
                          )}
                          {patch.conflict && (
                            <span className="shrink-0 rounded bg-rose-500/15 px-1 py-px text-[8.5px] font-semibold tracking-wide text-rose-300">
                              EXISTS
                            </span>
                          )}
                          {patch.warnings.length > 0 && !patch.conflict && (
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
                    </div>
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

            <div className="border-t border-ink-700/60 px-3 py-2 text-[9px] leading-relaxed text-slate-600">
              Writes are atomic and verified against the SHA-256 captured by the dry-run.
            </div>
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
                  <p
                    key={warning}
                    className="flex items-start gap-1.5 text-[9.5px] leading-relaxed text-amber-200/80"
                  >
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

      {confirm && (
        <ApplyConfirmDialog
          confirm={confirm}
          count={selectedPatches.length}
          onAck={(ack) => setConfirm((current) => (current ? { ...current, ack } : current))}
          onCancel={() => setConfirm(null)}
          onConfirm={() => void runApply(true)}
        />
      )}
    </div>
  );
}

function GitSafetyBar({
  git,
  showDirtyList,
  onToggleDirtyList,
  selectedCount,
  pending,
  disabled,
  onApply,
}: {
  git: GitState;
  showDirtyList: boolean;
  onToggleDirtyList: () => void;
  selectedCount: number;
  pending: boolean;
  disabled: boolean;
  onApply: () => void;
}) {
  return (
    <div className="relative flex items-center gap-2 border-b border-ink-700/70 bg-ink-900/60 px-3 py-2">
      <ShieldIcon className="h-3.5 w-3.5 shrink-0 text-emerald-300/80" />
      {git.pending && !git.status ? (
        <span className="flex items-center gap-1.5 rounded-full border border-ink-600 bg-ink-800 px-2 py-0.5 text-[10px] text-slate-400">
          <Spinner className="h-3 w-3" /> checking Git…
        </span>
      ) : git.error ? (
        <span
          title={git.error}
          className="rounded-full border border-rose-400/30 bg-rose-500/10 px-2 py-0.5 text-[10px] text-rose-200"
        >
          Git status unavailable
        </span>
      ) : git.status && !git.status.isGitRepo ? (
        <button
          type="button"
          onClick={onToggleDirtyList}
          title={git.status.warning ?? undefined}
          className="rounded-full border border-slate-500/30 bg-slate-500/10 px-2 py-0.5 text-[10px] text-slate-300 transition hover:border-slate-400/50"
        >
          Not a Git repository
        </button>
      ) : git.status && git.status.isDirty ? (
        <button
          type="button"
          onClick={onToggleDirtyList}
          title={git.status.dirtyFiles.join('\n')}
          className="rounded-full border border-amber-400/35 bg-amber-400/10 px-2 py-0.5 text-[10px] text-amber-200 transition hover:border-amber-300/60"
        >
          Git dirty ({git.status.dirtyFiles.length} modified file
          {git.status.dirtyFiles.length === 1 ? '' : 's'})
        </button>
      ) : (
        <span className="rounded-full border border-emerald-400/30 bg-emerald-400/10 px-2 py-0.5 text-[10px] text-emerald-200">
          Git clean (branch: {git.status?.branch ?? 'detached'})
        </span>
      )}

      <span className="hidden shrink-0 text-[9.5px] text-slate-600 lg:block">
        path containment · SHA-256 check · atomic write
      </span>

      <div className="ml-auto flex shrink-0 items-center gap-2">
        <button
          type="button"
          onClick={onApply}
          disabled={disabled}
          className="flex items-center gap-1.5 rounded-md border border-emerald-400/40 bg-emerald-400/10 px-2.5 py-1 text-[10.5px] font-medium text-emerald-200 transition enabled:hover:border-emerald-300/70 enabled:hover:bg-emerald-400/15 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {pending ? <Spinner className="h-3 w-3" /> : <CheckIcon className="h-3 w-3" />}
          {pending ? 'Applying…' : `Apply ${selectedCount} File${selectedCount === 1 ? '' : 's'} to Disk`}
        </button>
      </div>

      {showDirtyList && git.status && (
        <div className="absolute left-3 top-full z-10 mt-1 max-h-56 w-[380px] overflow-y-auto rounded-lg border border-ink-600 bg-ink-900 p-2 shadow-panel">
          <p className="mb-1 text-[9px] font-semibold uppercase tracking-[0.14em] text-slate-500">
            {git.status.isGitRepo ? 'Uncommitted changes' : 'Git warning'}
          </p>
          {git.status.isGitRepo ? (
            <ul className="space-y-0.5">
              {git.status.dirtyFiles.map((file) => (
                <li key={file} className="truncate font-mono text-[9.5px] text-amber-200/80">
                  {file}
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-[10px] leading-relaxed text-slate-400">{git.status.warning}</p>
          )}
        </div>
      )}
    </div>
  );
}

function ApplyConfirmDialog({
  confirm,
  count,
  onAck,
  onCancel,
  onConfirm,
}: {
  confirm: ConfirmState;
  count: number;
  onAck: (ack: boolean) => void;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const dirtyLabel = confirm.reason === 'dirty';

  return (
    <div className="absolute inset-0 z-20 flex items-center justify-center bg-black/60 p-6">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="kodo-apply-confirm-title"
        className="w-full max-w-lg rounded-xl border border-amber-400/30 bg-ink-900 p-4 shadow-panel"
      >
        <div className="flex items-start gap-2">
          <AlertIcon className="mt-0.5 h-4 w-4 shrink-0 text-amber-300" />
          <div className="min-w-0">
            <p id="kodo-apply-confirm-title" className="text-[12.5px] font-semibold text-amber-100">
              {dirtyLabel ? 'Apply on top of uncommitted changes?' : 'Apply to a non-Git folder?'}
            </p>
            <p className="mt-1 text-[10.5px] leading-relaxed text-slate-400">
              {dirtyLabel
                ? 'The Git working tree already has uncommitted changes. Kodo writes only the reviewed files, but those writes will be mixed into your current diff.'
                : 'This folder is not a Git repository, so Git cannot revert the apply. Kodo keeps an in-memory rollback snapshot for the last 10 applies, but a server restart loses it.'}
            </p>
          </div>
        </div>

        {dirtyLabel && confirm.dirtyFiles.length > 0 && (
          <ul className="mt-2 max-h-28 overflow-y-auto rounded-md border border-ink-700 bg-ink-950/60 p-2">
            {confirm.dirtyFiles.slice(0, 12).map((file) => (
              <li key={file} className="truncate font-mono text-[9.5px] text-amber-200/80">
                {file}
              </li>
            ))}
            {confirm.dirtyFiles.length > 12 && (
              <li className="text-[9px] text-slate-500">+{confirm.dirtyFiles.length - 12} more</li>
            )}
          </ul>
        )}

        {confirm.note && (
          <p className="mt-2 text-[10px] leading-relaxed text-amber-300/70">{confirm.note}</p>
        )}

        <p className="mt-2 text-[10px] leading-relaxed text-slate-500">
          If a file changed on disk since the dry-run, the apply is rejected with{' '}
          <span className="font-mono text-slate-400">STALE_FILE</span> and nothing is written — re-run the dry-run
          instead.
        </p>

        <label className="mt-3 flex items-start gap-2 rounded-md border border-ink-700 bg-ink-850/60 px-2 py-1.5">
          <input
            type="checkbox"
            checked={confirm.ack}
            onChange={(event) => onAck(event.target.checked)}
            className="mt-0.5 h-3 w-3 shrink-0 accent-amber-400"
          />
          <span className="text-[10px] leading-relaxed text-slate-300">
            I understand the risk and want to write {count} file{count === 1 ? '' : 's'} to disk.
          </span>
        </label>

        <div className="mt-3 flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            className="rounded-md border border-ink-600 px-2.5 py-1 text-[10.5px] text-slate-300 transition hover:border-slate-500 hover:text-slate-100"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={!confirm.ack}
            className="rounded-md border border-amber-400/50 bg-amber-400/15 px-2.5 py-1 text-[10.5px] font-medium text-amber-100 transition enabled:hover:bg-amber-400/25 disabled:cursor-not-allowed disabled:opacity-40"
          >
            Apply anyway
          </button>
        </div>
      </div>
    </div>
  );
}

function toFailure(reason: unknown): ApplyFailure {
  if (reason instanceof ApiError) {
    const detail = reason.detail ?? {};
    return {
      message: reason.message,
      code: reason.code,
      paths: Array.isArray(detail.paths) ? detail.paths.map(String) : [],
      dirtyFiles: Array.isArray(detail.dirtyFiles) ? detail.dirtyFiles.map(String) : [],
    };
  }
  return {
    message: reason instanceof Error ? reason.message : String(reason),
    paths: [],
    dirtyFiles: [],
  };
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
    case 'json':
    case 'xml':
    case 'yaml':
    case 'html':
    case 'css':
    case 'markdown':
    case 'python':
    case 'shell':
    case 'sql':
      return language;
    default:
      return 'plaintext';
  }
}
