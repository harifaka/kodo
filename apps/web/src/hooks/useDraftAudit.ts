import { useEffect, useState } from 'react';
import { api } from '../lib/api';
import type { AuditReport, ComponentNode, ComponentRelation, WorkspaceIR } from '../types/core-ir';

export interface DraftAuditState {
  /** Preview report for the draft IR; null while no draft exists or the preview failed. */
  report: AuditReport | null;
  pending: boolean;
  error: string | null;
}

const DEBOUNCE_MS = 220;

/** Re-runs the deterministic audit on the draft IR (relations, fields, annotations), debounced. */
export function useDraftAudit(
  workspace: WorkspaceIR | null,
  nodes: ComponentNode[],
  relations: ComponentRelation[],
  enabled: boolean,
): DraftAuditState {
  const [state, setState] = useState<DraftAuditState>({ report: null, pending: false, error: null });

  useEffect(() => {
    if (!workspace || !enabled) {
      setState((current) =>
        current.report === null && !current.pending && current.error === null
          ? current
          : { report: null, pending: false, error: null },
      );
      return;
    }

    const controller = new AbortController();
    setState((current) => ({ ...current, pending: true, error: null }));

    const timer = window.setTimeout(() => {
      api
        .previewAudit(nodes, relations, controller.signal)
        .then((report) => setState({ report, pending: false, error: null }))
        .catch((reason: unknown) => {
          if (controller.signal.aborted) {
            return;
          }
          setState({
            report: null,
            pending: false,
            error: reason instanceof Error ? reason.message : String(reason),
          });
        });
    }, DEBOUNCE_MS);

    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [workspace, nodes, relations, enabled]);

  return state;
}
