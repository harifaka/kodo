import { useCallback, useMemo, useState } from 'react';
import { api } from '../lib/api';
import { toSystemOneOverride } from '../lib/decisionSettings';
import { useSystemOneSettings } from './useSystemOneSettings';
import type { TriageItem, TriageState } from '../types/decision';
import type { WorkspaceIR } from '../types/core-ir';

const EMPTY: TriageState = {
  pending: false,
  available: null,
  items: {},
};

/** Runs the advisory System 1 audit triage for the scanned workspace. */
export function useAuditTriage(workspace: WorkspaceIR | null) {
  const [state, setState] = useState<TriageState>(EMPTY);
  const systemOneSettings = useSystemOneSettings();
  const systemOneConfig = useMemo(
    () => toSystemOneOverride(systemOneSettings),
    [systemOneSettings],
  );

  const run = useCallback(async () => {
    if (!workspace || state.pending) {
      return;
    }
    setState((current) => ({ ...current, pending: true, error: null }));
    try {
      const result = await api.decisionTriageAudit({
        rootPath: workspace.rootPath,
        workspaceIr: workspace,
        systemOneConfig,
      });
      const items: Record<string, TriageItem> = {};
      for (const item of result.items) {
        items[item.findingId] = item;
      }
      setState({
        pending: false,
        available: result.available,
        model: result.model,
        latencyMs: result.latencyMs,
        warning: result.warning,
        error: null,
        items,
      });
    } catch (reason) {
      setState((current) => ({
        ...current,
        pending: false,
        error: reason instanceof Error ? reason.message : String(reason),
      }));
    }
  }, [state.pending, systemOneConfig, workspace]);

  const reset = useCallback(() => setState(EMPTY), []);

  return { triage: state, runTriage: run, resetTriage: reset };
}
