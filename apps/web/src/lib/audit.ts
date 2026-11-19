import type { AuditFinding, AuditReport, Severity } from '../types/core-ir';

export const SEVERITY_ORDER: Severity[] = ['error', 'warning', 'info'];

export interface SeverityMeta {
  label: string;
  color: string;
  soft: string;
}

export const SEVERITY_META: Record<Severity, SeverityMeta> = {
  error: { label: 'Error', color: '#f43f5e', soft: 'rgba(244,63,94,0.10)' },
  warning: { label: 'Warning', color: '#fbbf24', soft: 'rgba(251,191,36,0.10)' },
  info: { label: 'Info', color: '#38bdf8', soft: 'rgba(56,189,248,0.10)' },
};

export function scoreTone(score: number): { color: string; label: string } {
  if (score >= 90) return { color: '#34d399', label: 'Healthy' };
  if (score >= 70) return { color: '#fbbf24', label: 'Needs attention' };
  return { color: '#f43f5e', label: 'At risk' };
}

export function edgeKey(sourceId: string, targetId: string): string {
  return `${sourceId}->${targetId}`;
}

export interface NodeAudit {
  severity: Severity;
  count: number;
}

/** Highest severity + finding count per affected component. */
export function nodeAuditIndex(report: AuditReport | undefined): Map<string, NodeAudit> {
  const index = new Map<string, NodeAudit>();
  if (!report) {
    return index;
  }

  for (const finding of report.findings) {
    for (const nodeId of finding.nodeIds) {
      const existing = index.get(nodeId);
      if (!existing) {
        index.set(nodeId, { severity: finding.severity, count: 1 });
        continue;
      }
      const severity =
        SEVERITY_ORDER.indexOf(finding.severity) < SEVERITY_ORDER.indexOf(existing.severity)
          ? finding.severity
          : existing.severity;
      index.set(nodeId, { severity, count: existing.count + 1 });
    }
  }

  return index;
}

export function auditedEdgeKeys(report: AuditReport | undefined): Set<string> {
  const keys = new Set<string>();
  for (const finding of report?.findings ?? []) {
    for (const key of finding.edgeKeys) {
      keys.add(key);
    }
  }
  return keys;
}

export function findingsForNode(report: AuditReport | undefined, nodeId: string): AuditFinding[] {
  return report?.findings.filter((finding) => finding.nodeIds.includes(nodeId)) ?? [];
}

export function findingNames(finding: AuditFinding, nodesById: Map<string, { name: string }>): string[] {
  return finding.nodeIds.map((id) => nodesById.get(id)?.name ?? id);
}
