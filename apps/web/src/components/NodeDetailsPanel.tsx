import { useMemo, useState, type ReactNode } from 'react';
import { LAYER_META, LAYER_ORDER, STACK_META, KIND_LABEL } from '../lib/layers';
import { findingsForNode } from '../lib/audit';
import type { AuditFinding, ComponentNode, ComponentRelation, WorkspaceIR } from '../types/core-ir';
import { CodeIcon, CopyIcon, ExternalIcon } from './icons';
import { AuditPanel, FindingRow } from './AuditPanel';
import { HealthScoreCard } from './HealthScore';

interface NodeDetailsPanelProps {
  workspace: WorkspaceIR;
  selected: ComponentNode | null;
  onSelect: (node: ComponentNode | null) => void;
  onSelectNodeId: (nodeId: string) => void;
  onOpenInInspector: () => void;
  onOpenFinding: (finding: AuditFinding) => void;
}

export function NodeDetailsPanel({
  workspace,
  selected,
  onSelect,
  onSelectNodeId,
  onOpenInInspector,
  onOpenFinding,
}: NodeDetailsPanelProps) {
  return (
    <aside className="flex w-[344px] shrink-0 flex-col border-l border-ink-700/70 bg-ink-900/60">
      <div className="flex items-center justify-between border-b border-ink-700/70 px-4 py-2.5">
        <span className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-500">
          {selected ? 'Component' : 'Workspace'}
        </span>
        {selected && (
          <button
            type="button"
            onClick={() => onSelect(null)}
            className="rounded px-1.5 py-0.5 text-[10px] text-slate-500 transition hover:bg-ink-700 hover:text-slate-300"
          >
            clear
          </button>
        )}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {selected ? (
          <SelectedDetails
            workspace={workspace}
            node={selected}
            onSelect={onSelect}
            onOpenInInspector={onOpenInInspector}
            onSelectNodeId={onSelectNodeId}
            onOpenFinding={onOpenFinding}
          />
        ) : (
          <WorkspaceOverview
            workspace={workspace}
            onSelectNodeId={onSelectNodeId}
            onOpenFinding={onOpenFinding}
          />
        )}
      </div>
    </aside>
  );
}

function SelectedDetails({
  workspace,
  node,
  onSelect,
  onOpenInInspector,
  onSelectNodeId,
  onOpenFinding,
}: {
  workspace: WorkspaceIR;
  node: ComponentNode;
  onSelect: (node: ComponentNode | null) => void;
  onOpenInInspector: () => void;
  onSelectNodeId: (nodeId: string) => void;
  onOpenFinding: (finding: AuditFinding) => void;
}) {
  const [copied, setCopied] = useState(false);
  const meta = LAYER_META[node.layer];
  const byId = useMemo(() => new Map(workspace.nodes.map((item) => [item.id, item])), [workspace.nodes]);
  const findings = useMemo(
    () => findingsForNode(workspace.audit, node.id),
    [workspace.audit, node.id],
  );

  const outgoing = workspace.relations.filter((relation) => relation.sourceId === node.id);
  const incoming = workspace.relations.filter((relation) => relation.targetId === node.id);

  const copyId = async () => {
    try {
      await navigator.clipboard.writeText(node.id);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1400);
    } catch {
      setCopied(false);
    }
  };

  return (
    <div className="pb-5">
      <div className="border-b border-ink-700/60 px-4 py-3" style={{ boxShadow: `inset 3px 0 0 ${meta.color}` }}>
        <h2 className="break-words text-[15px] font-semibold leading-snug text-white">{node.name}</h2>
        <button
          type="button"
          onClick={copyId}
          title="Copy component id"
          className="mt-1 flex w-full items-start gap-1.5 text-left font-mono text-[10px] leading-relaxed text-slate-500 transition hover:text-slate-300"
        >
          <span className="break-all">{node.id}</span>
          <CopyIcon className="mt-0.5 h-3 w-3 shrink-0" />
        </button>
        {copied && <p className="mt-1 text-[10px] text-emerald-400">id copied</p>}

        <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
          <Badge color={meta.color}>{meta.label}</Badge>
          <Badge color="#94a3b8">{KIND_LABEL[node.kind] ?? node.kind}</Badge>
          <Badge color={STACK_META[node.stack].color}>{STACK_META[node.stack].label}</Badge>
        </div>
      </div>

      <Section title="Source file">
        <button
          type="button"
          onClick={onOpenInInspector}
          className="group flex w-full items-center gap-2 rounded-md border border-ink-700/70 bg-ink-950/60 px-2.5 py-2 text-left transition hover:border-sky-500/50 hover:bg-ink-850"
        >
          <CodeIcon className="h-3.5 w-3.5 shrink-0 text-sky-400" />
          <span className="min-w-0 flex-1 break-all font-mono text-[10.5px] leading-relaxed text-slate-300">
            {node.filePath}
          </span>
          <ExternalIcon className="h-3 w-3 shrink-0 text-slate-500 transition group-hover:text-sky-300" />
        </button>
        <button
          type="button"
          onClick={onOpenInInspector}
          className="mt-2 w-full rounded-md bg-sky-500 px-3 py-2 text-[11.5px] font-semibold text-ink-950 transition hover:bg-sky-400"
        >
          Open in Code Inspector
        </button>
      </Section>

      {findings.length > 0 && (
        <Section title={`Audit findings · ${findings.length}`}>
          <ul className="space-y-1.5">
            {findings.map((finding) => (
              <FindingRow
                key={finding.id}
                finding={finding}
                nodesById={byId}
                onSelectNode={onSelectNodeId}
                onOpenFile={onOpenFinding}
              />
            ))}
          </ul>
        </Section>
      )}

      {node.annotations.length > 0 && (
        <Section title={`Annotations · ${node.annotations.length}`}>
          <div className="flex flex-wrap gap-1.5">
            {node.annotations.map((annotation) => (
              <span
                key={annotation}
                className="rounded border border-violet-400/20 bg-violet-400/10 px-1.5 py-0.5 font-mono text-[10px] text-violet-200"
              >
                {annotation}
              </span>
            ))}
          </div>
        </Section>
      )}

      <Section title={`Fields · ${node.fields.length}`}>
        {node.fields.length === 0 ? (
          <Empty text="No fields discovered." />
        ) : (
          <ul className="space-y-1">
            {node.fields.map((field) => (
              <li
                key={field.name}
                className="rounded-md border border-ink-700/50 bg-ink-950/50 px-2.5 py-1.5"
              >
                <div className="flex items-baseline gap-1.5">
                  <span className="font-mono text-[10px] text-slate-500">{field.visibility ?? ''}</span>
                  <span className="font-mono text-[10.5px] text-sky-200/90">{field.type || '—'}</span>
                  <span className="break-all font-mono text-[11px] text-slate-200">{field.name}</span>
                </div>
                {field.annotations.length > 0 && (
                  <div className="mt-0.5 font-mono text-[9.5px] text-violet-300/80">
                    {field.annotations.join(' ')}
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section title={`Methods · ${node.methods.length}`}>
        {node.methods.length === 0 ? (
          <Empty text="No methods discovered." />
        ) : (
          <ul className="space-y-1">
            {node.methods.map((method) => (
              <li
                key={`${method.name}(${method.parameters.join(',')})`}
                className="rounded-md border border-ink-700/50 bg-ink-950/50 px-2.5 py-1.5"
              >
                <div className="break-all font-mono text-[10.5px] leading-relaxed">
                  <span className="text-emerald-300">{method.name}</span>
                  <span className="text-slate-500">({method.parameters.join(', ')})</span>
                  {method.returnType && <span className="text-slate-400"> : {method.returnType}</span>}
                </div>
              </li>
            ))}
          </ul>
        )}
      </Section>

      {outgoing.length > 0 && (
        <Section title={`Depends on · ${outgoing.length}`}>
          <RelationList relations={outgoing} byId={byId} side="target" onSelect={onSelect} />
        </Section>
      )}

      {incoming.length > 0 && (
        <Section title={`Used by · ${incoming.length}`}>
          <RelationList relations={incoming} byId={byId} side="source" onSelect={onSelect} />
        </Section>
      )}
    </div>
  );
}

function RelationList({
  relations,
  byId,
  side,
  onSelect,
}: {
  relations: ComponentRelation[];
  byId: Map<string, ComponentNode>;
  side: 'source' | 'target';
  onSelect: (node: ComponentNode | null) => void;
}) {
  return (
    <ul className="space-y-1">
      {relations.map((relation) => {
        const related = byId.get(side === 'target' ? relation.targetId : relation.sourceId);
        if (!related) {
          return null;
        }
        return (
          <li key={`${relation.sourceId}-${relation.targetId}-${relation.type}`}>
            <button
              type="button"
              onClick={() => onSelect(related)}
              className="flex w-full items-center gap-2 rounded-md border border-transparent px-2 py-1 text-left transition hover:border-ink-600 hover:bg-ink-850"
            >
              <span
                className="h-1.5 w-1.5 shrink-0 rounded-full"
                style={{ backgroundColor: LAYER_META[related.layer].color }}
              />
              <span className="truncate text-[11px] text-slate-300">{related.name}</span>
              <span className="ml-auto shrink-0 font-mono text-[9px] uppercase tracking-wide text-slate-600">
                {relation.type.replace('_', ' ')}
              </span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}

function WorkspaceOverview({
  workspace,
  onSelectNodeId,
  onOpenFinding,
}: {
  workspace: WorkspaceIR;
  onSelectNodeId: (nodeId: string) => void;
  onOpenFinding: (finding: AuditFinding) => void;
}) {
  const counts = LAYER_ORDER.map((layer) => ({
    layer,
    count: workspace.nodes.filter((node) => node.layer === layer).length,
  })).filter((entry) => entry.count > 0);
  const max = Math.max(1, ...counts.map((entry) => entry.count));
  const nodesById = useMemo(() => new Map(workspace.nodes.map((node) => [node.id, node])), [workspace.nodes]);

  return (
    <div className="px-4 py-3">
      <h2 className="truncate text-[14px] font-semibold text-white">{workspace.name}</h2>
      <p className="mt-0.5 break-all font-mono text-[10px] leading-relaxed text-slate-500">{workspace.rootPath}</p>

      <div className="mt-3">
        <HealthScoreCard report={workspace.audit} />
      </div>

      <div className="mt-3 grid grid-cols-3 gap-2">
        <Stat label="Components" value={workspace.nodes.length} />
        <Stat label="Relations" value={workspace.relations.length} />
        <Stat label="Warnings" value={workspace.warnings.length} tone={workspace.warnings.length > 0 ? '#fbbf24' : undefined} />
      </div>

      <div className="mt-4">
        <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">Layer distribution</p>
        <ul className="mt-2 space-y-1.5">
          {counts.map(({ layer, count }) => (
            <li key={layer} className="flex items-center gap-2">
              <span className="w-[74px] shrink-0 text-[10px] text-slate-400">{LAYER_META[layer].label}</span>
              <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-ink-800">
                <span
                  className="block h-full rounded-full"
                  style={{ width: `${(count / max) * 100}%`, backgroundColor: LAYER_META[layer].color }}
                />
              </span>
              <span className="w-5 text-right font-mono text-[10px] text-slate-400">{count}</span>
            </li>
          ))}
        </ul>
      </div>

      <AuditPanel
        report={workspace.audit}
        nodesById={nodesById}
        onSelectNode={onSelectNodeId}
        onOpenFile={onOpenFinding}
      />

      <div className="mt-5 rounded-lg border border-ink-700/60 bg-ink-950/40 px-3 py-2.5">
        <p className="text-[11px] font-medium text-slate-300">Inspect a component</p>
        <p className="mt-1 text-[10.5px] leading-relaxed text-slate-500">
          Click any node in the Macro Graph or UML view to see its annotations, fields, methods and
          dependencies here.
        </p>
      </div>
    </div>
  );
}

function Stat({ label, value, tone }: { label: string; value: number; tone?: string }) {
  return (
    <div className="rounded-lg border border-ink-700/60 bg-ink-950/40 px-2 py-1.5">
      <div className="font-mono text-[15px] font-semibold" style={{ color: tone ?? '#e2e8f0' }}>
        {value}
      </div>
      <div className="text-[9px] uppercase tracking-[0.12em] text-slate-500">{label}</div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="border-b border-ink-700/40 px-4 py-3 last:border-b-0">
      <h3 className="mb-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">{title}</h3>
      {children}
    </section>
  );
}

function Badge({ color, children }: { color: string; children: ReactNode }) {
  return (
    <span
      className="rounded border px-1.5 py-0.5 text-[9.5px] font-medium"
      style={{ color, borderColor: `${color}33`, backgroundColor: `${color}12` }}
    >
      {children}
    </span>
  );
}

function Empty({ text }: { text: string }) {
  return <p className="text-[10.5px] text-slate-600">{text}</p>;
}
