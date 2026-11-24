import { useSyncExternalStore } from 'react';
import { getSystemOneSettings, subscribeSystemOneSettings } from '../lib/decisionSettings';
import type { SystemOneSettings } from '../types/decision';

/** Subscribe to the shared System 1 (Laya) settings (sessionStorage backed). */
export function useSystemOneSettings(): SystemOneSettings {
  return useSyncExternalStore(
    subscribeSystemOneSettings,
    getSystemOneSettings,
    getSystemOneSettings,
  );
}
