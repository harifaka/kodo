/**
 * AI Copilot settings store.
 *
 * The API key lives only in this browser tab's sessionStorage (or in memory when storage is
 * unavailable). It is never written to disk, never logged, and never sent to the target repository.
 */

import type { AiProviderKind, AiSettings, LlmOverride } from '../types/ai';

const STORAGE_KEY = 'kodo:ai-settings';

export const EMPTY_AI_SETTINGS: AiSettings = {
  baseUrl: '',
  apiKey: '',
  codeModel: 'deepseek-chat',
  reasoningModel: 'deepseek-reasoner',
};

export interface AiPreset {
  id: AiProviderKind;
  label: string;
  short: string;
  baseUrl: string;
  codeModel: string;
  reasoningModel: string;
  requiresKey: boolean;
  hint: string;
}

export const AI_PRESETS: AiPreset[] = [
  {
    id: 'cloud',
    label: 'DeepSeek Cloud',
    short: 'api.deepseek.com',
    baseUrl: 'https://api.deepseek.com/v1',
    codeModel: 'deepseek-chat',
    reasoningModel: 'deepseek-reasoner',
    requiresKey: true,
    hint: 'Needs a DeepSeek API key. Prompts leave this machine for DeepSeek.',
  },
  {
    id: 'local',
    label: 'Local On-Prem (Ollama)',
    short: 'localhost:11434',
    baseUrl: 'http://localhost:11434/v1',
    codeModel: 'deepseek-coder-v2',
    reasoningModel: 'deepseek-r1:8b',
    requiresKey: false,
    hint: 'Air-gapped: nothing leaves your network. Start Ollama with OLLAMA_HOST=0.0.0.0 and pull the models first.',
  },
];

function readStored(): AiSettings {
  try {
    const raw = window.sessionStorage.getItem(STORAGE_KEY);
    if (!raw) {
      return { ...EMPTY_AI_SETTINGS };
    }
    const parsed = JSON.parse(raw) as Partial<AiSettings>;
    return {
      baseUrl: typeof parsed.baseUrl === 'string' ? parsed.baseUrl : '',
      apiKey: typeof parsed.apiKey === 'string' ? parsed.apiKey : '',
      codeModel: typeof parsed.codeModel === 'string' && parsed.codeModel ? parsed.codeModel : EMPTY_AI_SETTINGS.codeModel,
      reasoningModel:
        typeof parsed.reasoningModel === 'string' && parsed.reasoningModel
          ? parsed.reasoningModel
          : EMPTY_AI_SETTINGS.reasoningModel,
    };
  } catch {
    return { ...EMPTY_AI_SETTINGS };
  }
}

let current: AiSettings = readStored();
const listeners = new Set<() => void>();

function emit(): void {
  listeners.forEach((listener) => listener());
}

export function getAiSettings(): AiSettings {
  return current;
}

export function subscribeAiSettings(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function saveAiSettings(next: AiSettings): void {
  current = {
    baseUrl: next.baseUrl.trim(),
    apiKey: next.apiKey.trim(),
    codeModel: next.codeModel.trim() || EMPTY_AI_SETTINGS.codeModel,
    reasoningModel: next.reasoningModel.trim() || EMPTY_AI_SETTINGS.reasoningModel,
  };
  try {
    window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(current));
  } catch {
    // Private mode / storage disabled: the in-memory store still works for this tab.
  }
  emit();
}

export function clearAiSettings(): void {
  current = { ...EMPTY_AI_SETTINGS };
  try {
    window.sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    // ignore unavailable storage
  }
  emit();
}

export function isAiConfigured(settings: AiSettings): boolean {
  return settings.baseUrl.trim().length > 0;
}

export function providerLabel(settings: AiSettings): string {
  const base = settings.baseUrl.trim().toLowerCase();
  if (!base) {
    return 'Not Configured';
  }
  if (base.includes('api.deepseek.com')) {
    return 'DeepSeek Cloud';
  }
  if (/localhost|127\.0\.0\.1|\[::1\]|host\.docker\.internal/.test(base)) {
    return 'Local On-Prem';
  }
  return 'Custom OpenAI';
}

/** Build the per-request override. Never include an empty key so a server-side env key still works. */
export function toLlmOverride(settings: AiSettings): LlmOverride | undefined {
  if (!isAiConfigured(settings)) {
    return undefined;
  }
  return {
    baseUrl: settings.baseUrl.trim(),
    ...(settings.apiKey.trim() ? { apiKey: settings.apiKey.trim() } : {}),
    codeModel: settings.codeModel.trim() || undefined,
    reasoningModel: settings.reasoningModel.trim() || undefined,
  };
}
