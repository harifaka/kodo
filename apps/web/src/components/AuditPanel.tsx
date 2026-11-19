import { useMemo, useState } from 'react';
import { SEVERITY_META, SEVERITY_ORDER, findingNames, type NodeAudit } from '../lib/audit';
import type { AuditFinding, AuditReport, ComponentNode, Severity } from '../types/core-ir';
import { AlertIcon, CodeIcon } from './icons';

type Filter = 'all' | Severity;

interface AuditPanelProps {
  report: AuditReport;
  nodesById: Map<string, ComponentNode>;
  onSelectNode: (nodeId: string) => void;
  onOpenFile: (finding: AuditFinding) => void;
}

export function AuditPanel({ report, nodesById, onSelectNode, onOpenFile }: AuditPanelProps) {
  const [filter, setFilter] = useState<Filter>('all');

  const counts = useMemo(
    () => ({
      all: report.findings.length,
      error: report.summary.errors,
      warning: report.summary.warnings,
      info: report.summary.info,
    }),
    [report],
  );

  const findings = useMemo(
    () => (filter === 'all' ? report.findings : report.findings.filter((item) => item.severity === filter)),
    [report.findings, filter],
  );

  return (
    <div className="mt-5">
      <div className="flex items-center justify-between">
        <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">Audit findings</p>
        <span className="font-mono text-[10px] text-slate-600">{report.findings.length}</span>
      </div>

      <div className="mt-2 flex flex-wrap gap-1">
        <FilterButton active={filter === 'all'} onClick={() => setFilter('all')} label="All" count={counts.all} />
        {SEVERITY_ORDER.map((severity) => (
          <FilterButton
            key={severity}
            active={filter === severity}
            onClick={() => setFilter(severity)}
            label={SEVERITY_META[severity].label}
            count={counts[severity]}
            color={SEVERITY_META[severity].color}
          />
        ))}
      </div>

      {findings.length === 0 ? (
        <p className="mt-3 text-[10.5px] leading-relaxed text-slate-600">
          {report.findings.length === 0
            ? 'No architectural drift detected. The graph is clean.'
            : 'No findings at this severity.'}
        </p>
      ) : (
        <ul className="mt-2 space-y-1.5">
          {findings.map((finding) => (
            <FindingRow
              key={finding.id}
              finding={finding}
              nodesById={nodesById}
              onSelectNode={onSelectNode}
              onOpenFile={onOpenFile}
            />
          ))}
        </ul>
      )}
    </div>
  );
}

export function FindingRow({
  finding,
  nodesById,
  onSelectNode,
  onOpenFile,
}: {
  finding: AuditFinding;
  nodesById: Map<string, ComponentNode>;
  onSelectNode: (nodeId: string) => void;
  onOpenFile: (finding: AuditFinding) => void;
}) {
  const meta = SEVERITY_META[finding.severity];
  const primary = finding.nodeIds[0];
  const names = findingNames(finding, nodesById);
  const rule = finding.ruleId;

  return (
    <li
      className="rounded-md border px-2.5 py-2"
      style={{ borderColor: `${meta.color}2e`, backgroundColor: meta.soft }}
    >
      <div className="flex items-start gap-2">
        <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full" style={{ backgroundColor: meta.color }} />
        <div className="min-w-0 flex-1">
          <button
            type="button"
            disabled={!primary}
            onClick={() => primary && onSelectNode(primary)}
            className="block w-full text-left disabled:cursor-default"
          >
            <p className="text-[11px] font-medium leading-snug text-slate-200">{finding.title}</p>
            <p className="mt-0.5 text-[10px] leading-relaxed text-slate-400">{finding.message}</p>
            <p className="mt-1 text-[9.5px] leading-relaxed text-slate-500">
              <span className="font-medium text-slate-400">Fix:</span> {finding.suggestion}
            </p>
          </button>

          <div className="mt-1.5 flex items-center gap-1.5">
            <span className="rounded bg-ink-950/70 px-1 py-0.5 font-mono text-[8.5px] uppercase tracking-wide text-slate-500">
              {rule.replaceAll('_', ' ')}
            </span>
            {names.length > 0 && (
              <span className="truncate font-mono text-[8.5px] text-slate-600">{names.join(' · ')}</span>
            )}
          </div>
        </div>

        {finding.filePath && (
          <button
            type="button"
            title={`Open ${finding.filePath} in the Code Inspector`}
            onClick={() => onOpenFile(finding)}
            className="mt-0.5 shrink-0 rounded p-1 text-slate-500 transition hover:bg-ink-700/60 hover:text-sky-300"
          >
            <CodeIcon className="h-3.5 w-3.5" />
          </button>
        )}
      </div>
    </li>
  );
}

function FilterButton({
  active,
  onClick,
  label,
  count,
  color,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
  count: number;
  color?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded border px-1.5 py-0.5 text-[9.5px] transition ${
        active
          ? 'border-sky-500/40 bg-sky-500/15 text-sky-200'
          : 'border-ink-700/60 bg-ink-950/40 text-slate-500 hover:text-slate-300'
      }`}
    >
      {color && <span className="mr-1 inline-block h-1.5 w-1.5 rounded-full align-middle" style={{ backgroundColor: color }} />}
      {label}
      <span className="ml-1 font-mono text-[8.5px] opacity-70">{count}</span>
    </button>
  );
}

export function AlertBadge({ nodeAudit }: { nodeAudit: NodeAudit }) {
  const meta = SEVERITY_META[nodeAudit.severity];
  return (
    <span
      title={`${nodeAudit.count} audit finding${nodeAudit.count === 1 ? '' : 's'}`}
      className="inline-flex items-center gap-0.5 rounded px-1 py-0.5 font-mono text-[8.5px] font-semibold"
      style={{ color: meta.color, backgroundColor: `${meta.color}1f` }}
    >
      <AlertIcon className="h-2.5 w-2.5" />
      {nodeAudit.count}
    </span>
  );
}
