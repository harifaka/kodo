import { useEffect, useState } from 'react';
import { useAiSettings } from '../hooks/useAiSettings';
import { useSystemOneSettings } from '../hooks/useSystemOneSettings';
import { api } from '../lib/api';
import {
  AI_PRESETS,
  CODE_MODEL_LABELS,
  EMPTY_AI_SETTINGS,
  clearAiSettings,
  providerLabel,
  saveAiSettings,
  toLlmOverride,
} from '../lib/aiSettings';
import {
  DEFAULT_SYSTEMONE_SETTINGS,
  SYSTEMONE_PRESETS,
  clearSystemOneSettings,
  saveSystemOneSettings,
  toSystemOneOverride,
} from '../lib/decisionSettings';
import type { AiSettings } from '../types/ai';
import type { SystemOneSettings } from '../types/decision';
import { AlertIcon, CheckIcon, CloseIcon, DecisionIcon, SparkIcon, Spinner } from './icons';

const INPUT_CLASS =
  'w-full rounded-md border border-ink-600 bg-ink-950/80 px-2.5 py-1.5 font-mono text-[11.5px] text-slate-200 outline-none transition placeholder:text-slate-600 focus:border-sky-500/60 focus:ring-2 focus:ring-sky-500/10';

interface AiSettingsModalProps {
  open: boolean;
  onClose: () => void;
}

interface TestResult {
  ok: boolean;
  message: string;
  models: string[];
}

export function AiSettingsModal({ open, onClose }: AiSettingsModalProps) {
  const settings = useAiSettings();
  const systemOneSettings = useSystemOneSettings();
  const [draft, setDraft] = useState<AiSettings>(settings);
  const [systemOneDraft, setSystemOneDraft] = useState<SystemOneSettings>(systemOneSettings);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<TestResult | null>(null);
  const [testingSystemOne, setTestingSystemOne] = useState(false);
  const [systemOneResult, setSystemOneResult] = useState<TestResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) {
      return;
    }
    setDraft(settings);
    setSystemOneDraft(systemOneSettings);
    setTestResult(null);
    setSystemOneResult(null);
    setError(null);
    setTesting(false);
    setTestingSystemOne(false);
  }, [open, settings, systemOneSettings]);

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

  if (!open) {
    return null;
  }

  const update = (patch: Partial<AiSettings>) => setDraft((current) => ({ ...current, ...patch }));
  const codeModelOptions =
    AI_PRESETS.find((preset) => preset.baseUrl === draft.baseUrl.trim())?.codeModelOptions ?? [];
  const updateSystemOne = (patch: Partial<SystemOneSettings>) =>
    setSystemOneDraft((current) => ({ ...current, ...patch }));

  const runTest = async () => {
    if (!draft.baseUrl.trim()) {
      setTestResult({ ok: false, message: 'Set a Base URL first (or pick a preset).', models: [] });
      return;
    }
    setTesting(true);
    setTestResult(null);
    try {
      const result = await api.aiTestConnection(toLlmOverride(draft));
      setTestResult({
        ok: true,
        message: `Connected · ${result.provider === 'local' ? 'local server' : 'cloud API'} · ${result.baseUrl}`,
        models: result.models,
      });
    } catch (reason) {
      setTestResult({
        ok: false,
        message: reason instanceof Error ? reason.message : String(reason),
        models: [],
      });
    } finally {
      setTesting(false);
    }
  };

  const runSystemOneTest = async () => {
    setTestingSystemOne(true);
    setSystemOneResult(null);
    try {
      const result = await api.systemOneTestConnection(toSystemOneOverride(systemOneDraft));
      if (result.reachable) {
        setSystemOneResult({
          ok: true,
          message: `Reachable · ${result.providerHint} · ${result.model} · ${result.latencyMs} ms${
            result.warning ? ` · ${result.warning}` : ''
          }`,
          models: [],
        });
      } else {
        setSystemOneResult({
          ok: false,
          message: result.warning ?? 'System 1 is unreachable.',
          models: [],
        });
      }
    } catch (reason) {
      setSystemOneResult({
        ok: false,
        message: reason instanceof Error ? reason.message : String(reason),
        models: [],
      });
    } finally {
      setTestingSystemOne(false);
    }
  };

  const save = () => {
    const baseUrl = draft.baseUrl.trim();
    if (!baseUrl) {
      setError('Base URL is required. Pick a preset or paste an OpenAI-compatible endpoint.');
      return;
    }
    if (!/^https?:\/\//i.test(baseUrl)) {
      setError('Base URL must start with http:// or https://.');
      return;
    }
    if (!draft.codeModel.trim() || !draft.reasoningModel.trim()) {
      setError('Configure both the code model and the reasoning model.');
      return;
    }
    if (
      systemOneDraft.enabled &&
      systemOneDraft.baseUrl.trim() &&
      !/^https?:\/\//i.test(systemOneDraft.baseUrl.trim())
    ) {
      setError('System 1 Base URL must start with http:// or https://.');
      return;
    }
    saveAiSettings(draft);
    saveSystemOneSettings(systemOneDraft);
    onClose();
  };

  const reset = () => {
    clearAiSettings();
    clearSystemOneSettings();
    setDraft({ ...EMPTY_AI_SETTINGS });
    setSystemOneDraft({ ...DEFAULT_SYSTEMONE_SETTINGS });
    setTestResult(null);
    setSystemOneResult(null);
    setError(null);
  };

  return (
    <div
      role="presentation"
      onClick={onClose}
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink-950/80 p-4 backdrop-blur-sm"
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="ai-settings-title"
        onClick={(event) => event.stopPropagation()}
        className="max-h-[90vh] w-full max-w-[560px] overflow-y-auto rounded-xl border border-ink-600 bg-ink-900 shadow-2xl"
      >
        <div className="flex items-start gap-3 border-b border-ink-700/70 px-4 py-3">
          <SparkIcon className="mt-0.5 h-4 w-4 shrink-0 text-violet-300" />
          <div className="min-w-0 flex-1">
            <h2 id="ai-settings-title" className="text-[13px] font-semibold text-white">
              AI settings · System 2 + System 1
            </h2>
            <p className="mt-0.5 text-[10.5px] leading-relaxed text-slate-500">
              System 2: DeepSeek Cloud or any OpenAI-compatible server ({' '}
              <span className="text-slate-300">{providerLabel(draft)}</span>). System 1: local Laya
              for fast, advisory decisions.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close AI settings"
            className="rounded p-1 text-slate-500 transition hover:bg-ink-700/60 hover:text-slate-200"
          >
            <CloseIcon className="h-4 w-4" />
          </button>
        </div>

        <div className="space-y-3 px-4 py-3">
          <div className="grid grid-cols-2 gap-2">
            {AI_PRESETS.map((preset) => {
              const active = draft.baseUrl.trim() === preset.baseUrl;
              return (
                <button
                  key={preset.id}
                  type="button"
                  onClick={() =>
                    update({
                      baseUrl: preset.baseUrl,
                      codeModel: preset.codeModel,
                      reasoningModel: preset.reasoningModel,
                    })
                  }
                  className={`rounded-lg border px-2.5 py-2 text-left transition ${
                    active
                      ? 'border-violet-400/60 bg-violet-400/10'
                      : 'border-ink-600 bg-ink-950/50 hover:border-violet-400/40 hover:bg-ink-850'
                  }`}
                >
                  <span className="block text-[11px] font-semibold text-slate-100">{preset.label}</span>
                  <span className="mt-0.5 block font-mono text-[9px] text-slate-500">{preset.short}</span>
                  <span className="mt-1 block text-[9px] leading-relaxed text-slate-500">{preset.hint}</span>
                </button>
              );
            })}
          </div>

          <label className="block">
            <span className="mb-1 block text-[9.5px] font-semibold uppercase tracking-[0.14em] text-slate-500">
              Base URL
            </span>
            <input
              value={draft.baseUrl}
              onChange={(event) => update({ baseUrl: event.target.value })}
              spellCheck={false}
              placeholder="https://api.deepseek.com/v1"
              className={INPUT_CLASS}
            />
          </label>

          <label className="block">
            <span className="mb-1 flex items-center justify-between text-[9.5px] font-semibold uppercase tracking-[0.14em] text-slate-500">
              API key
              <span className="font-normal normal-case tracking-normal text-slate-600">
                optional for local server
              </span>
            </span>
            <input
              type="password"
              value={draft.apiKey}
              onChange={(event) => update({ apiKey: event.target.value })}
              spellCheck={false}
              autoComplete="off"
              placeholder="sk-…"
              className={INPUT_CLASS}
            />
          </label>

          <div className="grid grid-cols-2 gap-2">
            <label className="block">
              <span className="mb-1 block text-[9.5px] font-semibold uppercase tracking-[0.14em] text-slate-500">
                Code model
              </span>
              <input
                value={draft.codeModel}
                onChange={(event) => update({ codeModel: event.target.value })}
                spellCheck={false}
                placeholder="deepseek-chat"
                className={INPUT_CLASS}
              />
            </label>
            <label className="block">
              <span className="mb-1 block text-[9.5px] font-semibold uppercase tracking-[0.14em] text-slate-500">
                Reasoning model
              </span>
              <input
                value={draft.reasoningModel}
                onChange={(event) => update({ reasoningModel: event.target.value })}
                spellCheck={false}
                placeholder="deepseek-reasoner"
                className={INPUT_CLASS}
              />
            </label>
          </div>

          {codeModelOptions.length > 0 && (
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="text-[9.5px] font-semibold uppercase tracking-[0.14em] text-slate-500">
                Suggested
              </span>
              {codeModelOptions.map((model) => {
                const active = draft.codeModel.trim() === model;
                return (
                  <button
                    key={model}
                    type="button"
                    onClick={() => update({ codeModel: model })}
                    title={model}
                    className={`rounded-full border px-2 py-0.5 text-[10px] font-medium transition ${
                      active
                        ? 'border-violet-400/60 bg-violet-400/10 text-violet-100'
                        : 'border-ink-600 bg-ink-950/50 text-slate-400 hover:border-violet-400/40 hover:text-slate-200'
                    }`}
                  >
                    {CODE_MODEL_LABELS[model] ?? model}
                  </button>
                );
              })}
            </div>
          )}

          <p className="rounded-md border border-ink-700/70 bg-ink-950/50 px-2.5 py-2 text-[9.5px] leading-relaxed text-slate-500">
            The API key stays in this browser tab&apos;s <span className="text-slate-300">sessionStorage</span>{' '}
            (or memory). Kodo never writes it to disk, never logs it and never sends it to the scanned
            repository. Server operators can also set <span className="font-mono text-slate-400">KODO_LLM_API_KEY</span>{' '}
            in the environment.
          </p>

          <div className="rounded-lg border border-sky-400/25 bg-sky-400/[0.04] px-3 py-3">
            <div className="flex items-start gap-2">
              <DecisionIcon className="mt-0.5 h-4 w-4 shrink-0 text-sky-300" />
              <div className="min-w-0 flex-1">
                <p className="text-[11.5px] font-semibold text-slate-100">
                  System 1 · Laya Decision Layer
                </p>
                <p className="mt-0.5 text-[9.5px] leading-relaxed text-slate-500">
                  Advisory only: triages findings, routes work and pre-screens diffs in milliseconds.
                  The deterministic audit, Monaco diff, SHA-256 apply and builder verification always
                  remain the gate.
                </p>
              </div>
              <label className="flex shrink-0 items-center gap-1.5 text-[9.5px] text-slate-400">
                <input
                  type="checkbox"
                  checked={systemOneDraft.enabled}
                  onChange={(event) => updateSystemOne({ enabled: event.target.checked })}
                  className="h-3 w-3 accent-sky-500"
                />
                Enabled
              </label>
            </div>

            <div className="mt-2 grid grid-cols-2 gap-2">
              {SYSTEMONE_PRESETS.map((preset) => {
                const active = systemOneDraft.baseUrl.trim() === preset.baseUrl;
                return (
                  <button
                    key={preset.id}
                    type="button"
                    onClick={() =>
                      updateSystemOne({
                        enabled: true,
                        baseUrl: preset.baseUrl,
                        model: preset.model,
                      })
                    }
                    className={`rounded-lg border px-2.5 py-2 text-left transition ${
                      active
                        ? 'border-sky-400/60 bg-sky-400/10'
                        : 'border-ink-600 bg-ink-950/50 hover:border-sky-400/40 hover:bg-ink-850'
                    }`}
                  >
                    <span className="block text-[11px] font-semibold text-slate-100">
                      {preset.label}
                    </span>
                    <span className="mt-0.5 block font-mono text-[9px] text-slate-500">
                      {preset.short}
                    </span>
                    <span className="mt-1 block text-[9px] leading-relaxed text-slate-500">
                      {preset.hint}
                    </span>
                  </button>
                );
              })}
            </div>

            <div className="mt-2 grid grid-cols-2 gap-2">
              <label className="block">
                <span className="mb-1 block text-[9.5px] font-semibold uppercase tracking-[0.14em] text-slate-500">
                  System 1 Base URL
                </span>
                <input
                  value={systemOneDraft.baseUrl}
                  onChange={(event) => updateSystemOne({ baseUrl: event.target.value })}
                  spellCheck={false}
                  placeholder="http://localhost:11434"
                  className={INPUT_CLASS}
                />
              </label>
              <label className="block">
                <span className="mb-1 block text-[9.5px] font-semibold uppercase tracking-[0.14em] text-slate-500">
                  Model
                </span>
                <input
                  value={systemOneDraft.model}
                  onChange={(event) => updateSystemOne({ model: event.target.value })}
                  spellCheck={false}
                  placeholder="laya"
                  className={INPUT_CLASS}
                />
              </label>
            </div>

            <label className="mt-2 block">
              <span className="mb-1 flex items-center justify-between text-[9.5px] font-semibold uppercase tracking-[0.14em] text-slate-500">
                API key
                <span className="font-normal normal-case tracking-normal text-slate-600">
                  optional for local Ollama / laya-serve
                </span>
              </span>
              <input
                type="password"
                value={systemOneDraft.apiKey}
                onChange={(event) => updateSystemOne({ apiKey: event.target.value })}
                spellCheck={false}
                autoComplete="off"
                placeholder="(none for local)"
                className={INPUT_CLASS}
              />
            </label>

            <label className="mt-2 block">
              <span className="mb-1 flex items-center justify-between text-[9.5px] font-semibold uppercase tracking-[0.14em] text-slate-500">
                Auto-route confidence threshold
                <span className="font-mono normal-case tracking-normal text-sky-300">
                  {systemOneDraft.autoThreshold.toFixed(2)}
                </span>
              </span>
              <input
                type="range"
                min={0.5}
                max={0.95}
                step={0.01}
                value={systemOneDraft.autoThreshold}
                onChange={(event) => updateSystemOne({ autoThreshold: Number(event.target.value) })}
                className="w-full accent-sky-500"
              />
              <span className="mt-0.5 block text-[9px] leading-relaxed text-slate-600">
                Below this calibrated confidence Kodo escalates to System 2 or human review instead of
                acting automatically.
              </span>
            </label>

            <div className="mt-2 flex items-center gap-2">
              <button
                type="button"
                onClick={() => void runSystemOneTest()}
                disabled={testingSystemOne || !systemOneDraft.enabled}
                className="flex items-center gap-1.5 rounded-md border border-sky-400/50 bg-sky-400/10 px-2.5 py-1.5 text-[10.5px] font-medium text-sky-100 transition enabled:hover:bg-sky-400/20 disabled:opacity-50"
              >
                {testingSystemOne ? <Spinner className="h-3 w-3" /> : <DecisionIcon className="h-3 w-3" />}
                {testingSystemOne ? 'Testing System 1…' : 'Test System 1'}
              </button>
              <span className="text-[9px] leading-relaxed text-slate-600">
                localhost:11434 · nothing leaves this machine
              </span>
            </div>

            {systemOneResult && (
              <div
                className={`mt-2 rounded-md border px-2.5 py-2 ${
                  systemOneResult.ok
                    ? 'border-emerald-400/30 bg-emerald-400/[0.07]'
                    : 'border-rose-400/30 bg-rose-400/[0.07]'
                }`}
              >
                <p
                  className={`flex items-start gap-1.5 text-[10.5px] leading-relaxed ${
                    systemOneResult.ok ? 'text-emerald-200' : 'text-rose-200'
                  }`}
                >
                  {systemOneResult.ok ? (
                    <CheckIcon className="mt-0.5 h-3 w-3 shrink-0" />
                  ) : (
                    <AlertIcon className="mt-0.5 h-3 w-3 shrink-0" />
                  )}
                  {systemOneResult.message}
                </p>
              </div>
            )}
          </div>

          {error && (
            <p className="flex items-start gap-1.5 text-[10.5px] leading-relaxed text-rose-300">
              <AlertIcon className="mt-0.5 h-3 w-3 shrink-0" />
              {error}
            </p>
          )}

          {testResult && (
            <div
              className={`rounded-md border px-2.5 py-2 ${
                testResult.ok
                  ? 'border-emerald-400/30 bg-emerald-400/[0.07]'
                  : 'border-rose-400/30 bg-rose-400/[0.07]'
              }`}
            >
              <p
                className={`flex items-start gap-1.5 text-[10.5px] leading-relaxed ${
                  testResult.ok ? 'text-emerald-200' : 'text-rose-200'
                }`}
              >
                {testResult.ok ? (
                  <CheckIcon className="mt-0.5 h-3 w-3 shrink-0" />
                ) : (
                  <AlertIcon className="mt-0.5 h-3 w-3 shrink-0" />
                )}
                {testResult.message}
              </p>
              {testResult.models.length > 0 && (
                <div className="mt-1.5 flex flex-wrap gap-1">
                  {testResult.models.slice(0, 12).map((model) => (
                    <span
                      key={model}
                      className="rounded border border-ink-600 bg-ink-950/60 px-1.5 py-0.5 font-mono text-[9px] text-slate-400"
                    >
                      {model}
                    </span>
                  ))}
                </div>
              )}
            </div>
          )}

          <div className="flex flex-wrap items-center gap-2 border-t border-ink-700/60 pt-3">
            <button
              type="button"
              onClick={() => void runTest()}
              disabled={testing}
              className="flex items-center gap-1.5 rounded-md border border-sky-400/50 bg-sky-400/10 px-2.5 py-1.5 text-[10.5px] font-medium text-sky-100 transition enabled:hover:bg-sky-400/20 disabled:opacity-50"
            >
              {testing ? <Spinner className="h-3 w-3" /> : <SparkIcon className="h-3 w-3" />}
              {testing ? 'Testing…' : 'Test System 2'}
            </button>
            <button
              type="button"
              onClick={reset}
              className="rounded-md border border-ink-600 px-2.5 py-1.5 text-[10.5px] text-slate-300 transition hover:border-rose-400/50 hover:text-rose-200"
            >
              Clear
            </button>
            <div className="ml-auto flex items-center gap-2">
              <button
                type="button"
                onClick={onClose}
                className="rounded-md px-2.5 py-1.5 text-[10.5px] text-slate-400 transition hover:text-slate-200"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={save}
                className="rounded-md bg-sky-500 px-3 py-1.5 text-[10.5px] font-semibold text-ink-950 transition hover:bg-sky-400"
              >
                Save
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
