import { useSyncExternalStore } from 'react';
import { getAiSettings, subscribeAiSettings } from '../lib/aiSettings';
import type { AiSettings } from '../types/ai';

/** Subscribe to the shared AI Copilot settings (sessionStorage backed). */
export function useAiSettings(): AiSettings {
  return useSyncExternalStore(subscribeAiSettings, getAiSettings, getAiSettings);
}
