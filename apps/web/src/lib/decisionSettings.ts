/**
 * System 1 (Laya) settings store.
 *
 * The optional API key lives only in this browser tab's sessionStorage (or in memory when storage is
 * unavailable). It is never written to disk, never logged and never sent to the scanned repository.
 */

import type { SystemOneOverride, SystemOnePreset, SystemOneSettings } from '../types/decision';

const STORAGE_KEY = 'kodo:systemone-settings';

export const DEFAULT_SYSTEMONE_SETTINGS: SystemOneSettings = {
  enabled: true,
  baseUrl: '',
  model: 'laya',
  apiKey: '',
  autoThreshold: 0.78,
};

export const SYSTEMONE_PRESETS: SystemOnePreset[] = [
  {
    id: 'ollama',
    label: 'Local Ollama',
    short: 'localhost:11434 · laya',
    baseUrl: 'http://localhost:11434',
    model: 'laya',
    hint: 'Start Ollama and run `ollama pull laya`. Millisecond decisions, nothing leaves the machine.',
  },
  {
    id: 'laya-serve',
    label: 'Local laya-serve',
    short: 'localhost:8000 · laya',
    baseUrl: 'http://localhost:8000',
    model: 'laya',
    hint: 'The standalone Laya runtime exposing the same /v1/systemone protocol.',
  },
];

function readStored(): SystemOneSettings {
  try {
    const raw = window.sessionStorage.getItem(STORAGE_KEY);
    if (!raw) {
      return { ...DEFAULT_SYSTEMONE_SETTINGS };
    }
    const parsed = JSON.parse(raw) as Partial<SystemOneSettings>;
    const threshold =
      typeof parsed.autoThreshold === 'number' && Number.isFinite(parsed.autoThreshold)
        ? Math.min(1, Math.max(0, parsed.autoThreshold))
        : DEFAULT_SYSTEMONE_SETTINGS.autoThreshold;
    return {
      enabled: typeof parsed.enabled === 'boolean' ? parsed.enabled : DEFAULT_SYSTEMONE_SETTINGS.enabled,
      baseUrl: typeof parsed.baseUrl === 'string' ? parsed.baseUrl : '',
      model:
        typeof parsed.model === 'string' && parsed.model.trim()
          ? parsed.model
          : DEFAULT_SYSTEMONE_SETTINGS.model,
      apiKey: typeof parsed.apiKey === 'string' ? parsed.apiKey : '',
      autoThreshold: threshold,
    };
  } catch {
    return { ...DEFAULT_SYSTEMONE_SETTINGS };
  }
}

let current: SystemOneSettings = readStored();
const listeners = new Set<() => void>();

function emit(): void {
  listeners.forEach((listener) => listener());
}

export function getSystemOneSettings(): SystemOneSettings {
  return current;
}

export function subscribeSystemOneSettings(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function saveSystemOneSettings(next: SystemOneSettings): void {
  current = {
    enabled: next.enabled,
    baseUrl: next.baseUrl.trim().replace(/\/+$/, ''),
    model: next.model.trim() || DEFAULT_SYSTEMONE_SETTINGS.model,
    apiKey: next.apiKey.trim(),
    autoThreshold: Math.min(1, Math.max(0, next.autoThreshold)),
  };
  try {
    window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(current));
  } catch {
    // Private mode / storage disabled: the in-memory store still works for this tab.
  }
  emit();
}

export function clearSystemOneSettings(): void {
  current = { ...DEFAULT_SYSTEMONE_SETTINGS };
  try {
    window.sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    // ignore unavailable storage
  }
  emit();
}

export function isSystemOneConfigured(settings: SystemOneSettings): boolean {
  return settings.enabled && settings.baseUrl.trim().length > 0;
}

export function systemOneLabel(settings: SystemOneSettings): string {
  if (!settings.enabled) {
    return 'Disabled';
  }
  if (!settings.baseUrl.trim()) {
    return 'Server env';
  }
  return settings.baseUrl.includes(':8000') ? 'laya-serve' : 'Laya';
}

/** Build the per-request override. An empty Base URL leaves URL/model/threshold to server env. */
export function toSystemOneOverride(settings: SystemOneSettings): SystemOneOverride {
  if (!settings.baseUrl.trim()) {
    // Not configured in this browser: respect the server's KODO_SYSTEMONE_* defaults, but honour
    // an explicit local disable.
    return settings.enabled ? {} : { enabled: false };
  }
  return {
    enabled: settings.enabled,
    baseUrl: settings.baseUrl.trim(),
    model: settings.model.trim() || DEFAULT_SYSTEMONE_SETTINGS.model,
    autoThreshold: settings.autoThreshold,
    ...(settings.apiKey.trim() ? { apiKey: settings.apiKey.trim() } : {}),
  };
}
