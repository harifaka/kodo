import type { AuditReport } from '../types/core-ir';
import { SEVERITY_META, scoreTone } from '../lib/audit';
import { ShieldIcon } from './icons';

export function HealthChip({ report }: { report: AuditReport }) {
  const tone = scoreTone(report.score);
  const total = report.summary.errors + report.summary.warnings + report.summary.info;

  return (
    <div
      title={`Architecture health ${report.score}/100 — ${report.summary.errors} error(s), ${report.summary.warnings} warning(s), ${report.summary.info} info`}
      className="flex cursor-default items-center gap-1.5 rounded-md border px-2 py-1"
      style={{ borderColor: `${tone.color}44`, backgroundColor: `${tone.color}12` }}
    >
      <span style={{ color: tone.color }}>
        <ShieldIcon className="h-3.5 w-3.5" />
      </span>
      <span className="text-[10.5px] font-medium text-slate-300">Audit</span>
      <span className="font-mono text-[11px] font-semibold" style={{ color: tone.color }}>
        {report.score}
      </span>
      {total > 0 && (
        <span className="font-mono text-[9px] text-slate-500">
          {report.summary.errors}E · {report.summary.warnings}W · {report.summary.info}I
        </span>
      )}
    </div>
  );
}

export function HealthScoreCard({ report }: { report: AuditReport }) {
  const tone = scoreTone(report.score);
  const summary = report.summary;

  return (
    <div className="rounded-lg border border-ink-700/60 bg-ink-950/40 px-3 py-2.5">
      <div className="flex items-center justify-between">
        <span className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">
          Architecture health
        </span>
        <span className="text-[9.5px] font-medium" style={{ color: tone.color }}>
          {tone.label}
        </span>
      </div>

      <div className="mt-1.5 flex items-baseline gap-1.5">
        <span className="font-mono text-[26px] font-semibold leading-none" style={{ color: tone.color }}>
          {report.score}
        </span>
        <span className="text-[10px] text-slate-600">/ 100</span>
        <span className="ml-auto text-[9.5px] text-slate-500">
          {summary.errors + summary.warnings + summary.info} finding
          {summary.errors + summary.warnings + summary.info === 1 ? '' : 's'}
        </span>
      </div>

      <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-ink-800">
        <span
          className="block h-full rounded-full transition-all"
          style={{ width: `${report.score}%`, backgroundColor: tone.color }}
        />
      </div>

      <div className="mt-2 grid grid-cols-3 gap-1.5">
        <SeverityCount label="Errors" value={summary.errors} severity="error" />
        <SeverityCount label="Warnings" value={summary.warnings} severity="warning" />
        <SeverityCount label="Info" value={summary.info} severity="info" />
      </div>
    </div>
  );
}

function SeverityCount({
  label,
  value,
  severity,
}: {
  label: string;
  value: number;
  severity: keyof typeof SEVERITY_META;
}) {
  const meta = SEVERITY_META[severity];
  return (
    <div className="rounded-md border border-ink-700/50 bg-ink-900/50 px-1.5 py-1">
      <div className="font-mono text-[13px] font-semibold" style={{ color: value > 0 ? meta.color : '#475569' }}>
        {value}
      </div>
      <div className="text-[8.5px] uppercase tracking-[0.1em] text-slate-500">{label}</div>
    </div>
  );
}
