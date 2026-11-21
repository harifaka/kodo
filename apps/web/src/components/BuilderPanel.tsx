import { useCallback, useEffect, useState } from 'react';
import { useAiSettings } from '../hooks/useAiSettings';
import { api } from '../lib/api';
import { providerLabel, toLlmOverride } from '../lib/aiSettings';
import {
  STACK_OPTIONS,
  blankSlice,
  defaultBlueprint,
  demoSlices,
  stackOption,
  uniqueSliceName,
  validateBlueprint,
} from '../lib/blueprint';
import type { Blueprint, BlueprintSlice, BlueprintStack } from '../types/blueprint';
import type { PlanPreview } from '../types/ai';
import {
  AlertIcon,
  BuilderIcon,
  ChevronIcon,
  DiffIcon,
  FolderIcon,
  PlusIcon,
  SparkIcon,
  Spinner,
  TrashIcon,
} from './icons';
import { SliceEditor } from './SliceEditor';

const INPUT_CLASS =
  'min-w-0 rounded-md border border-ink-700 bg-ink-950/70 px-2 py-1 text-[11px] text-slate-200 outline-none transition placeholder:text-slate-600 focus:border-sky-500/60';

interface BuilderPanelProps {
  rootPath: string;
  /** Bumped on every re-scan so a regenerate/rollback refreshes kodo.blueprint.json state. */
  revision?: number;
  onPreviewReady: (preview: PlanPreview) => void;
  /** AI Copilot availability (browser settings or server-side environment). */
  aiConfigured: boolean;
  onOpenAiSettings: () => void;
}

interface FileState {
  exists: boolean;
  status: 'idle' | 'loading' | 'loaded' | 'invalid';
  message: string | null;
}

export function BuilderPanel({
  rootPath,
  revision = 0,
  onPreviewReady,
  aiConfigured,
  onOpenAiSettings,
}: BuilderPanelProps) {
  const aiSettings = useAiSettings();
  const [blueprint, setBlueprint] = useState<Blueprint>(() => defaultBlueprint());
  const [activeIndex, setActiveIndex] = useState(0);
  const [includeSkeleton, setIncludeSkeleton] = useState(true);
  const [saveBlueprint, setSaveBlueprint] = useState(true);
  const [file, setFile] = useState<FileState>({ exists: false, status: 'idle', message: null });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [aiOpen, setAiOpen] = useState(false);
  const [spec, setSpec] = useState('');
  const [aiBusy, setAiBusy] = useState(false);
  const [aiError, setAiError] = useState<string | null>(null);
  const [aiRationale, setAiRationale] = useState<{ text: string; model: string; warnings: string[] } | null>(
    null,
  );

  const loadBlueprint = useCallback(async () => {
    setFile((current) => ({ ...current, status: 'loading', message: null }));
    try {
      const result = await api.blueprint(rootPath);
      if (result.blueprint) {
        setBlueprint(result.blueprint);
        setActiveIndex(0);
        setFile({
          exists: true,
          status: 'loaded',
          message: result.warnings[0] ?? null,
        });
        return;
      }
      setFile({
        exists: result.exists,
        status: result.exists ? 'invalid' : 'idle',
        message: result.warnings[0] ?? null,
      });
    } catch (reason) {
      setFile({
        exists: false,
        status: 'invalid',
        message: reason instanceof Error ? reason.message : String(reason),
      });
    }
  }, [rootPath]);

  useEffect(() => {
    setBlueprint(defaultBlueprint());
    setActiveIndex(0);
    setError(null);
    setAiRationale(null);
    setAiError(null);
    void loadBlueprint();
  }, [loadBlueprint, revision, rootPath]);

  const patchBlueprint = (patch: Partial<Blueprint>) => {
    setBlueprint((current) => ({ ...current, ...patch }));
  };

  const changeStack = (stack: BlueprintStack) => {
    const previous = stackOption(blueprint.stack);
    const next = stackOption(stack);
    setBlueprint((current) => ({
      ...current,
      stack,
      projectName:
        current.projectName.trim() === previous.defaultProject || !current.projectName.trim()
          ? next.defaultProject
          : current.projectName,
      basePackageOrNamespace:
        current.basePackageOrNamespace.trim() === previous.defaultBase ||
        !current.basePackageOrNamespace.trim()
          ? next.defaultBase
          : current.basePackageOrNamespace,
    }));
  };

  const updateSlice = (index: number, patch: Partial<BlueprintSlice>) => {
    setBlueprint((current) => ({
      ...current,
      slices: current.slices.map((slice, position) => (position === index ? { ...slice, ...patch } : slice)),
    }));
  };

  const renameSlice = (index: number, name: string) => {
    setBlueprint((current) => {
      const previousName = current.slices[index]?.name;
      return {
        ...current,
        slices: current.slices.map((slice, position) => {
          if (position === index) {
            return { ...slice, name };
          }
          if (previousName && slice.dependsOnSlices.includes(previousName)) {
            return {
              ...slice,
              dependsOnSlices: slice.dependsOnSlices.map((entry) => (entry === previousName ? name : entry)),
            };
          }
          return slice;
        }),
      };
    });
  };

  const addSlice = () => {
    const slices = [...blueprint.slices, blankSlice(uniqueSliceName(blueprint.slices))];
    setBlueprint({ ...blueprint, slices });
    setActiveIndex(slices.length - 1);
  };

  const removeSlice = (index: number) => {
    const removed = blueprint.slices[index]?.name;
    const slices = blueprint.slices
      .filter((_, position) => position !== index)
      .map((slice) => ({
        ...slice,
        dependsOnSlices: removed
          ? slice.dependsOnSlices.filter((entry) => entry !== removed)
          : slice.dependsOnSlices,
      }));
    setBlueprint({ ...blueprint, slices });
    setActiveIndex(Math.max(0, Math.min(activeIndex, slices.length - 1)));
  };

  const applyDemoPreset = () => {
    setBlueprint({ ...blueprint, slices: demoSlices(blueprint.stack) });
    setActiveIndex(0);
  };

  const generateFromSpec = async () => {
    const prompt = spec.trim();
    if (!prompt) {
      setAiError('Describe the business domain first.');
      return;
    }
    if (!aiConfigured) {
      setAiError('Configure the AI Copilot (DeepSeek Cloud or a local Ollama/vLLM server) first.');
      return;
    }
    setAiBusy(true);
    setAiError(null);
    try {
      const result = await api.aiSpecToBlueprint({
        spec: prompt,
        stack: blueprint.stack,
        projectName: blueprint.projectName.trim() || undefined,
        basePackageOrNamespace: blueprint.basePackageOrNamespace.trim() || undefined,
        llmConfig: toLlmOverride(aiSettings),
      });
      setBlueprint(result.blueprint);
      setActiveIndex(0);
      setAiRationale({ text: result.rationale, model: result.modelUsed, warnings: result.warnings });
    } catch (reason) {
      setAiError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setAiBusy(false);
    }
  };

  const preview = async () => {
    const problems = validateBlueprint(blueprint);
    if (problems.length > 0) {
      setError(problems.join(' '));
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const response = await api.scaffoldDryRun({
        rootPath,
        blueprint,
        includeProjectSkeleton: includeSkeleton,
        saveBlueprint,
      });
      const option = stackOption(blueprint.stack);
      onPreviewReady({
        response,
        label: `${option.label} · ${blueprint.slices.length} slice${blueprint.slices.length === 1 ? '' : 's'} · ${blueprint.projectName.trim()}`,
        kind: 'scaffold',
      });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  };

  const active = blueprint.slices[activeIndex] ?? null;
  const option = stackOption(blueprint.stack);

  return (
    <div className="flex h-full min-h-0 flex-col bg-ink-950">
      <div className="border-b border-ink-700/70 bg-ink-900/40 px-4 py-3">
        <div className="flex flex-wrap items-center gap-2">
          <BuilderIcon className="h-4 w-4 text-sky-400" />
          <p className="text-[12px] font-semibold text-slate-100">Blueprint Builder</p>
          <span className="rounded border border-ink-600 bg-ink-850 px-1.5 py-0.5 font-mono text-[9px] text-slate-400">
            {option.short}
          </span>
          {file.status === 'loaded' && (
            <span className="rounded border border-emerald-400/30 bg-emerald-400/10 px-1.5 py-0.5 text-[9.5px] text-emerald-200">
              kodo.blueprint.json loaded
            </span>
          )}
          <div className="ml-auto flex items-center gap-1.5">
            {file.exists && (
              <button
                type="button"
                onClick={() => void loadBlueprint()}
                disabled={file.status === 'loading'}
                className="flex items-center gap-1 rounded-md border border-ink-600 px-2 py-1 text-[10px] text-slate-300 transition enabled:hover:border-sky-500/50 enabled:hover:text-sky-200 disabled:opacity-50"
              >
                {file.status === 'loading' ? <Spinner className="h-3 w-3" /> : <FolderIcon className="h-3 w-3" />}
                Load Blueprint
              </button>
            )}
            <button
              type="button"
              onClick={() => void preview()}
              disabled={busy}
              className="flex items-center gap-1.5 rounded-md border border-sky-400/50 bg-sky-400/10 px-2.5 py-1 text-[10.5px] font-medium text-sky-100 transition enabled:hover:bg-sky-400/20 disabled:opacity-50"
            >
              {busy ? <Spinner className="h-3 w-3" /> : <DiffIcon className="h-3 w-3" />}
              {busy ? 'Generating…' : 'Preview Generated Files (Dry-Run)'}
            </button>
          </div>
        </div>

        <div className="mt-2.5 flex flex-wrap items-end gap-2">
          <div className="flex items-center gap-0.5 rounded-md border border-ink-700 p-0.5">
            {STACK_OPTIONS.map((entry) => (
              <button
                key={entry.id}
                type="button"
                onClick={() => changeStack(entry.id)}
                className={`rounded px-2 py-1 text-[10px] transition ${
                  blueprint.stack === entry.id
                    ? 'bg-sky-500/15 text-sky-200'
                    : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                {entry.label}
              </button>
            ))}
          </div>

          <label className="flex min-w-[150px] flex-col gap-0.5">
            <span className="text-[9px] font-semibold uppercase tracking-[0.14em] text-slate-500">
              Project name
            </span>
            <input
              value={blueprint.projectName}
              onChange={(event) => patchBlueprint({ projectName: event.target.value })}
              spellCheck={false}
              className={INPUT_CLASS}
            />
          </label>

          <label className="flex min-w-[180px] flex-col gap-0.5">
            <span className="text-[9px] font-semibold uppercase tracking-[0.14em] text-slate-500">
              {option.baseLabel}
            </span>
            <input
              value={blueprint.basePackageOrNamespace}
              onChange={(event) => patchBlueprint({ basePackageOrNamespace: event.target.value })}
              placeholder={option.basePlaceholder}
              spellCheck={false}
              className={`${INPUT_CLASS} font-mono`}
            />
          </label>

          <label
            title="Emit the build file and application entry point — use this for empty/new folders."
            className="flex items-center gap-1.5 rounded-md border border-ink-700 bg-ink-900/60 px-2 py-1"
          >
            <input
              type="checkbox"
              checked={includeSkeleton}
              onChange={(event) => setIncludeSkeleton(event.target.checked)}
              className="h-3 w-3 accent-sky-500"
            />
            <span className="text-[10px] text-slate-300">Include project skeleton</span>
          </label>

          <label
            title="Save the versioned blueprint next to the generated code for pull-request review."
            className="flex items-center gap-1.5 rounded-md border border-ink-700 bg-ink-900/60 px-2 py-1"
          >
            <input
              type="checkbox"
              checked={saveBlueprint}
              onChange={(event) => setSaveBlueprint(event.target.checked)}
              className="h-3 w-3 accent-sky-500"
            />
            <span className="text-[10px] text-slate-300">Save kodo.blueprint.json</span>
          </label>
        </div>

        <p className="mt-1.5 text-[9.5px] leading-relaxed text-slate-600">{option.description}</p>

        {file.message && (
          <p className="mt-1.5 flex items-start gap-1.5 text-[9.5px] leading-relaxed text-amber-300/80">
            <AlertIcon className="mt-0.5 h-3 w-3 shrink-0" />
            {file.message}
          </p>
        )}
        {error && (
          <p className="mt-1.5 flex items-start gap-1.5 text-[9.5px] leading-relaxed text-rose-300">
            <AlertIcon className="mt-0.5 h-3 w-3 shrink-0" />
            {error}
          </p>
        )}
      </div>

      <div className="border-b border-ink-700/70 bg-violet-400/[0.04] px-4 py-2">
        <button
          type="button"
          onClick={() => setAiOpen((value) => !value)}
          aria-expanded={aiOpen}
          className="flex w-full items-center gap-2 text-left"
        >
          <SparkIcon className="h-3.5 w-3.5 shrink-0 text-violet-300" />
          <span className="text-[11.5px] font-semibold text-slate-100">AI Generate from Spec</span>
          <span
            className={`rounded border px-1.5 py-0.5 text-[8.5px] uppercase tracking-wide ${
              aiConfigured
                ? 'border-emerald-400/30 bg-emerald-400/10 text-emerald-200'
                : 'border-ink-600 bg-ink-850 text-slate-500'
            }`}
          >
            {aiConfigured ? providerLabel(aiSettings) : 'not configured'}
          </span>
          <span className="hidden text-[9px] text-slate-600 sm:block">
            natural language → reviewable blueprint (nothing is written)
          </span>
          <ChevronIcon className={`ml-auto h-3.5 w-3.5 shrink-0 text-slate-500 transition ${aiOpen ? 'rotate-180' : ''}`} />
        </button>

        {aiOpen && (
          <div className="mt-2">
            <textarea
              value={spec}
              onChange={(event) => setSpec(event.target.value)}
              rows={4}
              spellCheck={false}
              placeholder="An invoice and payment system with customers, invoices and payments. Invoices belong to a customer, payments settle an invoice."
              className="w-full resize-y rounded-md border border-ink-700 bg-ink-950/70 px-2.5 py-2 text-[11px] leading-relaxed text-slate-200 outline-none transition placeholder:text-slate-600 focus:border-violet-400/60"
            />
            <div className="mt-1.5 flex flex-wrap items-center gap-2">
              <button
                type="button"
                onClick={() => void generateFromSpec()}
                disabled={aiBusy || !spec.trim()}
                className="flex items-center gap-1.5 rounded-md border border-violet-400/50 bg-violet-400/10 px-2.5 py-1 text-[10.5px] font-medium text-violet-100 transition enabled:hover:bg-violet-400/20 disabled:opacity-50"
              >
                {aiBusy ? <Spinner className="h-3 w-3" /> : <SparkIcon className="h-3 w-3" />}
                {aiBusy ? 'Generating…' : 'Generate Blueprint'}
              </button>
              {!aiConfigured && (
                <button
                  type="button"
                  onClick={onOpenAiSettings}
                  className="text-[10px] text-violet-200 underline decoration-violet-400/40 underline-offset-2 transition hover:text-violet-100"
                >
                  Configure AI Copilot
                </button>
              )}
              <span className="text-[9px] leading-relaxed text-slate-500">
                Target stack: {option.label} · the blueprint loads below for review before any dry-run.
              </span>
            </div>

            {aiError && (
              <p className="mt-1.5 flex items-start gap-1.5 text-[9.5px] leading-relaxed text-rose-300">
                <AlertIcon className="mt-0.5 h-3 w-3 shrink-0" />
                {aiError}
              </p>
            )}

            {aiRationale && (
              <div className="mt-2 rounded-md border border-violet-400/25 bg-violet-400/[0.06] px-2.5 py-2">
                <p className="text-[9px] font-semibold uppercase tracking-[0.14em] text-violet-300/80">
                  AI rationale · {aiRationale.model}
                </p>
                <p className="mt-1 whitespace-pre-wrap text-[10.5px] leading-relaxed text-slate-300">
                  {aiRationale.text || 'No rationale returned.'}
                </p>
                {aiRationale.warnings.map((warning) => (
                  <p key={warning} className="mt-1 flex items-start gap-1.5 text-[9.5px] leading-relaxed text-amber-200/90">
                    <AlertIcon className="mt-0.5 h-3 w-3 shrink-0" />
                    {warning}
                  </p>
                ))}
                <p className="mt-1.5 text-[9px] leading-relaxed text-slate-500">
                  Review and edit the slices, then generate the files in the Monaco diff — the AI never
                  writes to disk.
                </p>
              </div>
            )}
          </div>
        )}
      </div>

      <div className="flex min-h-0 flex-1">
        <aside className="flex w-[236px] shrink-0 flex-col border-r border-ink-700/70 bg-ink-900/50">
          <div className="flex items-center justify-between border-b border-ink-700/60 px-3 py-1.5">
            <span className="text-[9.5px] font-semibold uppercase tracking-[0.16em] text-slate-500">
              Slices · {blueprint.slices.length}
            </span>
            <button
              type="button"
              onClick={addSlice}
              className="flex items-center gap-1 rounded-md border border-emerald-400/40 px-1.5 py-0.5 text-[9.5px] text-emerald-200 transition hover:bg-emerald-400/10"
            >
              <PlusIcon className="h-3 w-3" /> Add Slice
            </button>
          </div>

          <ul className="min-h-0 flex-1 space-y-1 overflow-y-auto p-2">
            {blueprint.slices.map((slice, index) => {
              const selected = index === activeIndex;
              return (
                <li key={`${slice.name}-${index}`} className="flex items-start gap-1">
                  <button
                    type="button"
                    onClick={() => setActiveIndex(index)}
                    className={`min-w-0 flex-1 rounded-md border px-2 py-1.5 text-left transition ${
                      selected
                        ? 'border-sky-500/50 bg-sky-500/10'
                        : 'border-transparent hover:border-ink-600 hover:bg-ink-850'
                    }`}
                  >
                    <span className="block truncate font-mono text-[10.5px] text-slate-200">
                      {slice.name || '(unnamed)'}
                    </span>
                    <span className="mt-0.5 block font-mono text-[9px] text-slate-500">
                      {slice.fields.length} field{slice.fields.length === 1 ? '' : 's'}
                      {slice.dependsOnSlices.length > 0 ? ` · ${slice.dependsOnSlices.length} dep` : ''}
                    </span>
                  </button>
                  <button
                    type="button"
                    onClick={() => removeSlice(index)}
                    aria-label={`Remove slice ${slice.name || index + 1}`}
                    className="mt-1 rounded p-1 text-slate-600 transition hover:bg-rose-500/10 hover:text-rose-300"
                  >
                    <TrashIcon className="h-3 w-3" />
                  </button>
                </li>
              );
            })}
          </ul>

          <div className="border-t border-ink-700/60 p-2">
            <p className="mb-1 text-[9px] font-semibold uppercase tracking-[0.14em] text-slate-500">
              Quick presets
            </p>
            <button
              type="button"
              onClick={applyDemoPreset}
              className="w-full rounded-md border border-violet-400/40 px-2 py-1 text-left text-[10px] text-violet-200 transition hover:bg-violet-400/10"
            >
              Order + Customer + Payment
              <span className="mt-0.5 block text-[9px] text-violet-300/60">
                replaces the slices with a 3-service demo
              </span>
            </button>
          </div>
        </aside>

        {active ? (
          <SliceEditor
            slice={active}
            slices={blueprint.slices}
            index={activeIndex}
            stack={blueprint.stack}
            onChange={(index, patch) => {
              if (patch.name !== undefined) {
                renameSlice(index, patch.name);
                const { name: _name, ...rest } = patch;
                if (Object.keys(rest).length > 0) {
                  updateSlice(index, rest);
                }
                return;
              }
              updateSlice(index, patch);
            }}
          />
        ) : (
          <div className="flex flex-1 items-center justify-center px-8">
            <div className="max-w-sm text-center">
              <BuilderIcon className="mx-auto h-5 w-5 text-slate-600" />
              <p className="mt-2 text-xs text-slate-400">No slices yet</p>
              <p className="mt-1 text-[10.5px] leading-relaxed text-slate-600">
                Add a slice, or load the Order + Customer + Payment preset, then preview the generated
                files in the Monaco diff.
              </p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
