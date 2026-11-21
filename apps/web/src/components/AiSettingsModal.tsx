import { useEffect, useState } from 'react';
import { useAiSettings } from '../hooks/useAiSettings';
import { api } from '../lib/api';
import {
  AI_PRESETS,
  EMPTY_AI_SETTINGS,
  clearAiSettings,
  providerLabel,
  saveAiSettings,
  toLlmOverride,
} from '../lib/aiSettings';
import type { AiSettings } from '../types/ai';
import { AlertIcon, CheckIcon, CloseIcon, SparkIcon, Spinner } from './icons';

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
  const [draft, setDraft] = useState<AiSettings>(settings);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<TestResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) {
      return;
    }
    setDraft(settings);
    setTestResult(null);
    setError(null);
    setTesting(false);
  }, [open, settings]);

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
    saveAiSettings(draft);
    onClose();
  };

  const reset = () => {
    clearAiSettings();
    setDraft({ ...EMPTY_AI_SETTINGS });
    setTestResult(null);
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
              AI Copilot settings
            </h2>
            <p className="mt-0.5 text-[10.5px] leading-relaxed text-slate-500">
              DeepSeek Cloud or any OpenAI-compatible server (Ollama, vLLM). Current provider:{' '}
              <span className="text-slate-300">{providerLabel(draft)}</span>
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

          <p className="rounded-md border border-ink-700/70 bg-ink-950/50 px-2.5 py-2 text-[9.5px] leading-relaxed text-slate-500">
            The API key stays in this browser tab&apos;s <span className="text-slate-300">sessionStorage</span>{' '}
            (or memory). Kodo never writes it to disk, never logs it and never sends it to the scanned
            repository. Server operators can also set <span className="font-mono text-slate-400">KODO_LLM_API_KEY</span>{' '}
            in the environment.
          </p>

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
              {testing ? 'Testing…' : 'Test Connection'}
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
