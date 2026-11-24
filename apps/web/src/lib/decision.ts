/** Shared presentation helpers for the System 1 (Laya) decision layer. */

export interface BadgeMeta {
  label: string;
  color: string;
  className: string;
  hint: string;
}

export const RISK_META: Record<string, BadgeMeta> = {
  critical_arch_risk: {
    label: 'Critical Risk',
    color: '#f87171',
    className: 'border-rose-400/40 bg-rose-400/10 text-rose-200',
    hint: 'Breaks a layer boundary, cycle or data exposure a user can reach.',
  },
  moderate_maintainability: {
    label: 'Moderate',
    color: '#fbbf24',
    className: 'border-amber-400/40 bg-amber-400/10 text-amber-200',
    hint: 'Real drift, contained and safe to schedule.',
  },
  low_boilerplate: {
    label: 'Low Boilerplate',
    color: '#34d399',
    className: 'border-emerald-400/40 bg-emerald-400/10 text-emerald-200',
    hint: 'Cosmetic or boilerplate-only; no behavioural risk.',
  },
  uncertain: {
    label: 'Uncertain',
    color: '#94a3b8',
    className: 'border-slate-400/40 bg-slate-400/10 text-slate-300',
    hint: 'System 1 could not judge safely.',
  },
};

export const ROUTE_META: Record<string, BadgeMeta> = {
  deterministic_ast: {
    label: 'AST Fix',
    color: '#34d399',
    className: 'border-emerald-400/40 bg-emerald-400/10 text-emerald-200',
    hint: 'A guarded deterministic AST patch can fix this with no model call.',
  },
  template_builder: {
    label: 'Builder',
    color: '#38bdf8',
    className: 'border-sky-400/40 bg-sky-400/10 text-sky-200',
    hint: 'Re-scaffold the slice through the deterministic Builder.',
  },
  deepseek_refactor: {
    label: 'DeepSeek S2',
    color: '#a78bfa',
    className: 'border-violet-400/40 bg-violet-400/10 text-violet-200',
    hint: 'Escalate to the DeepSeek System 2 reasoning model.',
  },
  deepseek_code: {
    label: 'DeepSeek S2',
    color: '#a78bfa',
    className: 'border-violet-400/40 bg-violet-400/10 text-violet-200',
    hint: 'Small code generation through the DeepSeek System 2 code model.',
  },
  deepseek_reasoning: {
    label: 'DeepSeek S2',
    color: '#a78bfa',
    className: 'border-violet-400/40 bg-violet-400/10 text-violet-200',
    hint: 'Cross-cutting reasoning through the DeepSeek System 2 reasoning model.',
  },
  human_review: {
    label: 'Human Review',
    color: '#fbbf24',
    className: 'border-amber-400/40 bg-amber-400/10 text-amber-200',
    hint: 'An architect should decide; nothing is applied automatically.',
  },
  ignore_benign: {
    label: 'Ignore',
    color: '#94a3b8',
    className: 'border-slate-400/40 bg-slate-400/10 text-slate-300',
    hint: 'Benign finding; leave the code untouched.',
  },
  uncertain: {
    label: 'Uncertain',
    color: '#94a3b8',
    className: 'border-slate-400/40 bg-slate-400/10 text-slate-300',
    hint: 'System 1 abstained; treat this as manual review.',
  },
  act_system1_deterministic: {
    label: 'Act now',
    color: '#34d399',
    className: 'border-emerald-400/40 bg-emerald-400/10 text-emerald-200',
    hint: 'Deterministic tools can act without any cloud tokens.',
  },
  escalate_system2_deepseek: {
    label: 'Escalate S2',
    color: '#a78bfa',
    className: 'border-violet-400/40 bg-violet-400/10 text-violet-200',
    hint: 'Escalate to the DeepSeek System 2 model.',
  },
  escalate_human_review: {
    label: 'Human Review',
    color: '#fbbf24',
    className: 'border-amber-400/40 bg-amber-400/10 text-amber-200',
    hint: 'Escalate to a human architect.',
  },
};

export const DIFF_STATUS_META: Record<string, BadgeMeta> = {
  pass: {
    label: 'Pass',
    color: '#34d399',
    className: 'border-emerald-400/35 bg-emerald-400/10 text-emerald-200',
    hint: 'No logic-loss or layer-boundary signal detected in this diff.',
  },
  caution: {
    label: 'Caution',
    color: '#fbbf24',
    className: 'border-amber-400/40 bg-amber-400/10 text-amber-200',
    hint: 'Review every hunk carefully before applying.',
  },
  high_risk: {
    label: 'High Risk — Review Carefully',
    color: '#f87171',
    className: 'border-rose-400/45 bg-rose-400/10 text-rose-200',
    hint: 'Possible business-logic loss or layer violation; block the apply until reviewed.',
  },
};

export function riskMeta(risk: string): BadgeMeta {
  return RISK_META[risk] ?? RISK_META.uncertain;
}

export function routeMeta(route: string): BadgeMeta {
  return ROUTE_META[route] ?? ROUTE_META.uncertain;
}

export function diffStatusMeta(status: string): BadgeMeta {
  return DIFF_STATUS_META[status] ?? DIFF_STATUS_META.caution;
}

export function confidencePercent(value: number): string {
  return `${Math.round(Math.max(0, Math.min(1, value)) * 100)}%`;
}

export const DECISION_TYPE_META: Record<string, { label: string; className: string }> = {
  audit_triage: { label: 'Audit triage', className: 'border-sky-400/35 bg-sky-400/10 text-sky-200' },
  task_route: {
    label: 'Task route',
    className: 'border-violet-400/35 bg-violet-400/10 text-violet-200',
  },
  diff_safety: {
    label: 'Diff safety',
    className: 'border-amber-400/35 bg-amber-400/10 text-amber-200',
  },
};

export function decisionTypeMeta(type: string): { label: string; className: string } {
  return DECISION_TYPE_META[type] ?? { label: type, className: 'border-ink-600 bg-ink-800 text-slate-300' };
}
