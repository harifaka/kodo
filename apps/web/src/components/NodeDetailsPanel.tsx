import { useMemo, useState, type FormEvent, type ReactNode } from 'react';
import { LAYER_META, LAYER_ORDER, STACK_META, KIND_LABEL } from '../lib/layers';
import { findingsForNode } from '../lib/audit';
import {
  hasNodeDraft,
  removedFieldsFor,
  type Draft,
  type FieldDraftStatus,
  type NodeDraft,
} from '../lib/draft';
import type {
  AuditFinding,
  ComponentField,
  ComponentNode,
  ComponentRelation,
  Stack,
  WorkspaceIR,
} from '../types/core-ir';
import type { TriageState } from '../types/decision';
import { CodeIcon, CopyIcon, ExternalIcon } from './icons';
import { AuditPanel, FindingRow } from './AuditPanel';
import { HealthScoreCard } from './HealthScore';
import { MethodsSection } from './MethodsSection';

interface NodeDetailsPanelProps {
  workspace: WorkspaceIR;
  baseNode: ComponentNode | null;
  selected: ComponentNode | null;
  draft: Draft;
  onSelect: (node: ComponentNode | null) => void;
  onSelectNodeId: (nodeId: string) => void;
  onOpenInInspector: () => void;
  onOpenFinding: (finding: AuditFinding) => void;
  onDisconnectRelation: (relation: ComponentRelation) => void;
  onAddField: (nodeId: string, field: ComponentField) => void;
  onUpdateField: (nodeId: string, originalName: string, field: ComponentField) => void;
  onRemoveField: (nodeId: string, fieldName: string) => void;
  onAddAnnotation: (nodeId: string, annotation: string) => void;
  onRemoveAnnotation: (nodeId: string, annotation: string) => void;
  aiConfigured: boolean;
  /** Finding id currently being fixed by the AI Copilot, if any. */
  aiFixingId: string | null;
  onFixWithAi: (finding: AuditFinding) => void;
  onImplementMethod: (node: ComponentNode, methodName: string, instruction: string) => Promise<void>;
  onOpenAiSettings: () => void;
  /** Phase 10 advisory System 1 triage shared with the Audit panel and finding rows. */
  triage: TriageState;
  onTriage: () => void;
}

interface MicroEditHandlers {
  onAddField: (nodeId: string, field: ComponentField) => void;
  onUpdateField: (nodeId: string, originalName: string, field: ComponentField) => void;
  onRemoveField: (nodeId: string, fieldName: string) => void;
  onAddAnnotation: (nodeId: string, annotation: string) => void;
  onRemoveAnnotation: (nodeId: string, annotation: string) => void;
}

const FIELD_TYPES: Record<Stack, string[]> = {
  'spring-boot': ['String', 'Long', 'Integer', 'BigDecimal', 'UUID', 'LocalDateTime', 'LocalDate', 'Boolean', 'Double'],
  'csharp-dotnet': ['string', 'int', 'long', 'decimal', 'Guid', 'DateTime', 'bool', 'double'],
  nodejs: ['string', 'number', 'boolean', 'Date', 'Record<string, unknown>'],
  unknown: ['string', 'number', 'boolean'],
};

const VISIBILITIES: Record<Stack, string[]> = {
  'spring-boot': ['private', 'public', 'protected', 'package'],
  'csharp-dotnet': ['public', 'private', 'protected', 'internal', 'private readonly'],
  nodejs: ['public', 'private', 'protected', 'readonly'],
  unknown: ['public', 'private'],
};

const ANNOTATION_PRESETS: Record<Stack, string[]> = {
  'spring-boot': ['@NotNull', '@NotBlank', '@Valid', '@Column(nullable = false)', '@Column(unique = true)', '@ManyToOne'],
  'csharp-dotnet': ['[Required]', '[StringLength(100)]', '[Key]', '[JsonPropertyName("...")]'],
  nodejs: ['@IsNotEmpty()', '@IsString()', '@IsNumber()', '@Column()'],
  unknown: [],
};

const STATUS_STYLES: Record<FieldDraftStatus, string> = {
  added: 'border-emerald-400/40 bg-emerald-400/[0.06]',
  modified: 'border-amber-400/40 bg-amber-400/[0.06]',
  removed: 'border-rose-400/25 bg-rose-400/[0.04] opacity-70',
};

const STATUS_TEXT: Record<FieldDraftStatus, string> = {
  added: 'text-emerald-300',
  modified: 'text-amber-300',
  removed: 'text-rose-300',
};

const INPUT_CLASS =
  'w-full rounded border border-ink-700 bg-ink-950/80 px-1.5 py-1 font-mono text-[10.5px] text-slate-200 outline-none transition placeholder:text-slate-600 focus:border-sky-500/60';

const SMALL_BUTTON_CLASS =
  'rounded border border-ink-700 px-1.5 py-0.5 text-[9.5px] text-slate-400 transition hover:border-ink-600 hover:text-slate-200';

export function NodeDetailsPanel({
  workspace,
  baseNode,
  selected,
  draft,
  onSelect,
  onSelectNodeId,
  onOpenInInspector,
  onOpenFinding,
  onDisconnectRelation,
  onAddField,
  onUpdateField,
  onRemoveField,
  onAddAnnotation,
  onRemoveAnnotation,
  aiConfigured,
  aiFixingId,
  onFixWithAi,
  onImplementMethod,
  onOpenAiSettings,
  triage,
  onTriage,
}: NodeDetailsPanelProps) {
  const micro: MicroEditHandlers = {
    onAddField,
    onUpdateField,
    onRemoveField,
    onAddAnnotation,
    onRemoveAnnotation,
  };

  return (
    <aside className="flex w-[372px] shrink-0 flex-col border-l border-ink-700/70 bg-ink-900/60">
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
            baseNode={baseNode}
            draft={draft}
            micro={micro}
            onSelect={onSelect}
            onOpenInInspector={onOpenInInspector}
            onSelectNodeId={onSelectNodeId}
            onOpenFinding={onOpenFinding}
            onDisconnectRelation={onDisconnectRelation}
            aiConfigured={aiConfigured}
            aiFixingId={aiFixingId}
            onFixWithAi={onFixWithAi}
            onImplementMethod={onImplementMethod}
            onOpenAiSettings={onOpenAiSettings}
            triage={triage}
          />
        ) : (
          <WorkspaceOverview
            workspace={workspace}
            onSelectNodeId={onSelectNodeId}
            onOpenFinding={onOpenFinding}
            aiConfigured={aiConfigured}
            aiFixingId={aiFixingId}
            onFixWithAi={onFixWithAi}
            triage={triage}
            onTriage={onTriage}
          />
        )}
      </div>
    </aside>
  );
}

function SelectedDetails({
  workspace,
  node,
  baseNode,
  draft,
  micro,
  onSelect,
  onOpenInInspector,
  onSelectNodeId,
  onOpenFinding,
  onDisconnectRelation,
  aiConfigured,
  aiFixingId,
  onFixWithAi,
  onImplementMethod,
  onOpenAiSettings,
  triage,
}: {
  workspace: WorkspaceIR;
  node: ComponentNode;
  baseNode: ComponentNode | null;
  draft: Draft;
  micro: MicroEditHandlers;
  onSelect: (node: ComponentNode | null) => void;
  onOpenInInspector: () => void;
  onSelectNodeId: (nodeId: string) => void;
  onOpenFinding: (finding: AuditFinding) => void;
  onDisconnectRelation: (relation: ComponentRelation) => void;
  aiConfigured: boolean;
  aiFixingId: string | null;
  onFixWithAi: (finding: AuditFinding) => void;
  onImplementMethod: (node: ComponentNode, methodName: string, instruction: string) => Promise<void>;
  onOpenAiSettings: () => void;
  triage: TriageState;
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
  const nodeDraft = draft.nodes[node.id];

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
          {hasNodeDraft(draft, node.id) && (
            <span className="rounded border border-amber-400/30 bg-amber-400/10 px-1.5 py-0.5 text-[9.5px] font-medium text-amber-200">
              draft edits
            </span>
          )}
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
                aiConfigured={aiConfigured}
                aiFixing={aiFixingId === finding.id}
                onFixWithAi={onFixWithAi}
                triage={triage.items[finding.id]}
              />
            ))}
          </ul>
        </Section>
      )}

      <AnnotationEditor
        key={`annotations-${node.id}`}
        node={node}
        baseNode={baseNode}
        nodeDraft={nodeDraft}
        onAdd={(annotation) => micro.onAddAnnotation(node.id, annotation)}
        onRemove={(annotation) => micro.onRemoveAnnotation(node.id, annotation)}
      />

      <FieldsEditor
        key={`fields-${node.id}`}
        node={node}
        baseNode={baseNode}
        nodeDraft={nodeDraft}
        onAdd={(field) => micro.onAddField(node.id, field)}
        onUpdate={(originalName, field) => micro.onUpdateField(node.id, originalName, field)}
        onRemove={(fieldName) => micro.onRemoveField(node.id, fieldName)}
      />

      <MethodsSection
        key={`methods-${node.id}`}
        node={node}
        aiConfigured={aiConfigured}
        onConfigureAi={onOpenAiSettings}
        onImplement={(methodName, instruction) => onImplementMethod(node, methodName, instruction)}
      />

      {outgoing.length > 0 && (
        <Section title={`Depends on · ${outgoing.length}`}>
          <RelationList
            relations={outgoing}
            byId={byId}
            side="target"
            onSelect={onSelect}
            onRemove={onDisconnectRelation}
          />
        </Section>
      )}

      {incoming.length > 0 && (
        <Section title={`Used by · ${incoming.length}`}>
          <RelationList
            relations={incoming}
            byId={byId}
            side="source"
            onSelect={onSelect}
            onRemove={onDisconnectRelation}
          />
        </Section>
      )}
    </div>
  );
}

function FieldsEditor({
  node,
  baseNode,
  nodeDraft,
  onAdd,
  onUpdate,
  onRemove,
}: {
  node: ComponentNode;
  baseNode: ComponentNode | null;
  nodeDraft: NodeDraft | undefined;
  onAdd: (field: ComponentField) => void;
  onUpdate: (originalName: string, field: ComponentField) => void;
  onRemove: (fieldName: string) => void;
}) {
  const [editing, setEditing] = useState<{ originalName: string; field: ComponentField } | null>(null);
  const [adding, setAdding] = useState(false);

  const removed = removedFieldsFor(baseNode?.fields ?? [], nodeDraft);
  const addedNames = new Set(nodeDraft?.fields.added.map((field) => field.name) ?? []);
  const modifiedByName = new Map(nodeDraft?.fields.updated.map((item) => [item.field.name, item.originalName]) ?? []);
  const listId = `kodo-field-types-${node.id.replace(/[^a-zA-Z0-9_-]/g, '-')}`;

  const originalNameFor = (field: ComponentField): string => modifiedByName.get(field.name) ?? field.name;

  return (
    <Section title={`Fields · ${node.fields.length}${removed.length > 0 ? ` · −${removed.length} pending` : ''}`}>
      <datalist id={listId}>
        {FIELD_TYPES[node.stack].map((type) => (
          <option key={type} value={type} />
        ))}
      </datalist>

      {node.fields.length === 0 && removed.length === 0 ? (
        <Empty text="No fields discovered — add the first business field below." />
      ) : (
        <ul className="space-y-1">
          {node.fields.map((field) => {
            const status: FieldDraftStatus | undefined = addedNames.has(field.name)
              ? 'added'
              : modifiedByName.has(field.name)
                ? 'modified'
                : undefined;
            const isEditing = editing?.field.name === field.name;

            return (
              <li
                key={field.name}
                className={`rounded-md border px-2.5 py-1.5 ${
                  status ? STATUS_STYLES[status] : 'border-ink-700/50 bg-ink-950/50'
                }`}
              >
                {isEditing && editing ? (
                  <FieldForm
                    key={`edit-${field.name}`}
                    initial={editing.field}
                    stack={node.stack}
                    listId={listId}
                    submitLabel="Save"
                    taken={node.fields.map((item) => item.name)}
                    onSubmit={(next) => {
                      onUpdate(editing.originalName, next);
                      setEditing(null);
                    }}
                    onCancel={() => setEditing(null)}
                  />
                ) : (
                  <>
                    <div className="flex items-baseline gap-1.5">
                      <span className="font-mono text-[10px] text-slate-500">{field.visibility ?? ''}</span>
                      <span className="font-mono text-[10.5px] text-sky-200/90">{field.type || '—'}</span>
                      <span className="break-all font-mono text-[11px] text-slate-200">{field.name}</span>
                      <span className="ml-auto flex shrink-0 items-center gap-1">
                        {status && (
                          <span className={`font-mono text-[8.5px] uppercase tracking-wide ${STATUS_TEXT[status]}`}>
                            {status}
                          </span>
                        )}
                        <button
                          type="button"
                          title="Edit field"
                          aria-label={`Edit field ${field.name}`}
                          onClick={() => setEditing({ originalName: originalNameFor(field), field })}
                          className="rounded px-1 text-[10px] text-slate-500 transition hover:bg-ink-700 hover:text-sky-300"
                        >
                          ✎
                        </button>
                        <button
                          type="button"
                          title="Remove field in the draft"
                          aria-label={`Remove field ${field.name}`}
                          onClick={() => onRemove(field.name)}
                          className="rounded px-1 text-[11px] leading-none text-slate-500 transition hover:bg-rose-500/10 hover:text-rose-300"
                        >
                          ×
                        </button>
                      </span>
                    </div>
                    {field.annotations.length > 0 && (
                      <div className="mt-0.5 font-mono text-[9.5px] text-violet-300/80">
                        {field.annotations.join(' ')}
                      </div>
                    )}
                  </>
                )}
              </li>
            );
          })}

          {removed.map((field) => (
            <li key={`removed-${field.name}`} className={`rounded-md border px-2.5 py-1.5 ${STATUS_STYLES.removed}`}>
              <div className="flex items-baseline gap-1.5 line-through">
                <span className="font-mono text-[10px] text-slate-500">{field.visibility ?? ''}</span>
                <span className="font-mono text-[10.5px] text-sky-200/70">{field.type || '—'}</span>
                <span className="break-all font-mono text-[11px] text-slate-400">{field.name}</span>
                <span className="ml-auto font-mono text-[8.5px] uppercase tracking-wide text-rose-300">removed</span>
              </div>
              <p className="mt-0.5 text-[9px] text-slate-500">Reset draft to restore this field.</p>
            </li>
          ))}
        </ul>
      )}

      <div className="mt-2">
        {adding ? (
          <div className="rounded-md border border-emerald-400/30 bg-emerald-400/[0.04] p-2">
            <FieldForm
              key="add-field"
              initial={{ name: '', type: FIELD_TYPES[node.stack][0] ?? 'string', visibility: defaultVisibility(node.stack), annotations: [] }}
              stack={node.stack}
              listId={listId}
              submitLabel="Add field"
              taken={node.fields.map((item) => item.name)}
              onSubmit={(field) => {
                onAdd(field);
                setAdding(false);
              }}
              onCancel={() => setAdding(false)}
            />
          </div>
        ) : (
          <button
            type="button"
            onClick={() => setAdding(true)}
            className="w-full rounded-md border border-dashed border-ink-600 px-2 py-1.5 text-[10.5px] text-slate-400 transition hover:border-emerald-400/50 hover:text-emerald-200"
          >
            + Quick add field
          </button>
        )}
      </div>
      <p className="mt-1.5 text-[9px] leading-relaxed text-slate-600">
        Field edits are in-memory only. Use <span className="text-slate-400">Preview Diff</span> to see the
        surgical AST patch before anything touches disk.
      </p>
    </Section>
  );
}

function FieldForm({
  initial,
  stack,
  listId,
  submitLabel,
  taken,
  onSubmit,
  onCancel,
}: {
  initial: ComponentField;
  stack: Stack;
  listId: string;
  submitLabel: string;
  taken?: string[];
  onSubmit: (field: ComponentField) => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState(initial.name);
  const [type, setType] = useState(initial.type);
  const [visibility, setVisibility] = useState(initial.visibility ?? defaultVisibility(stack));
  const [annotations, setAnnotations] = useState(initial.annotations.join(', '));
  const [error, setError] = useState<string | null>(null);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const trimmedName = name.trim();
    const trimmedType = type.trim();
    if (!trimmedName || !trimmedType) {
      setError('Name and type are required.');
      return;
    }
    if (taken && trimmedName !== initial.name && taken.includes(trimmedName)) {
      setError(`A field named "${trimmedName}" already exists.`);
      return;
    }
    setError(null);
    onSubmit({
      name: trimmedName,
      type: trimmedType,
      visibility: visibility || undefined,
      annotations: splitAnnotations(annotations),
    });
  };

  const options = VISIBILITIES[stack].includes(visibility)
    ? VISIBILITIES[stack]
    : [visibility, ...VISIBILITIES[stack]];

  return (
    <form onSubmit={submit} className="space-y-1.5">
      <div className="grid grid-cols-[1.15fr_1fr] gap-1.5">
        <input
          autoFocus
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder="fieldName"
          aria-label="Field name"
          spellCheck={false}
          className={INPUT_CLASS}
        />
        <input
          value={type}
          onChange={(event) => setType(event.target.value)}
          placeholder="Type"
          aria-label="Field type"
          list={listId}
          spellCheck={false}
          className={INPUT_CLASS}
        />
      </div>
      <div className="grid grid-cols-[1fr_1.4fr] gap-1.5">
        <select
          value={visibility}
          onChange={(event) => setVisibility(event.target.value)}
          aria-label="Field visibility"
          className={INPUT_CLASS}
        >
          {options.map((option) => (
            <option key={option} value={option}>
              {option}
            </option>
          ))}
        </select>
        <input
          value={annotations}
          onChange={(event) => setAnnotations(event.target.value)}
          placeholder="@NotNull, @Column"
          aria-label="Field annotations"
          spellCheck={false}
          className={INPUT_CLASS}
        />
      </div>

      <PresetChips onPick={(preset) => setAnnotations((current) => toggleAnnotation(current, preset))} stack={stack} />
      {error && <p className="text-[9px] text-rose-300">{error}</p>}

      <div className="flex items-center gap-1.5">
        <button
          type="submit"
          className="rounded bg-emerald-500 px-2 py-1 text-[10px] font-semibold text-ink-950 transition hover:bg-emerald-400"
        >
          {submitLabel}
        </button>
        <button type="button" onClick={onCancel} className={SMALL_BUTTON_CLASS}>
          Cancel
        </button>
      </div>
    </form>
  );
}

function AnnotationEditor({
  node,
  baseNode,
  nodeDraft,
  onAdd,
  onRemove,
}: {
  node: ComponentNode;
  baseNode: ComponentNode | null;
  nodeDraft: NodeDraft | undefined;
  onAdd: (annotation: string) => void;
  onRemove: (annotation: string) => void;
}) {
  const [value, setValue] = useState('');
  const added = new Set(nodeDraft?.addedAnnotations ?? []);
  const removed = (baseNode?.annotations ?? []).filter(
    (annotation) =>
      nodeDraft?.removedAnnotations.includes(annotation) && !node.annotations.includes(annotation),
  );

  const add = (raw: string) => {
    const annotation = raw.trim();
    if (!annotation) {
      return;
    }
    const name = annotationName(annotation);
    const isRemoved =
      nodeDraft?.removedAnnotations.some((item) => annotationName(item) === name) ?? false;
    if (node.annotations.some((item) => annotationName(item) === name) && !isRemoved) {
      return;
    }
    onAdd(annotation);
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    add(value);
    setValue('');
  };

  return (
    <Section title={`Annotations · ${node.annotations.length}${removed.length > 0 ? ` · −${removed.length} pending` : ''}`}>
      <div className="flex flex-wrap gap-1.5">
        {node.annotations.map((annotation) => (
          <span
            key={annotation}
            className={`inline-flex items-center gap-1 rounded border px-1.5 py-0.5 font-mono text-[10px] ${
              added.has(annotation)
                ? 'border-emerald-400/40 bg-emerald-400/10 text-emerald-200'
                : 'border-violet-400/20 bg-violet-400/10 text-violet-200'
            }`}
          >
            {annotation}
            <button
              type="button"
              onClick={() => onRemove(annotation)}
              title="Remove annotation in the draft"
              aria-label={`Remove annotation ${annotation}`}
              className="text-[11px] leading-none text-slate-500 transition hover:text-rose-300"
            >
              ×
            </button>
          </span>
        ))}
        {removed.map((annotation) => (
          <span
            key={`removed-${annotation}`}
            className="inline-flex items-center gap-1 rounded border border-rose-400/30 bg-rose-400/[0.06] px-1.5 py-0.5 font-mono text-[10px] text-rose-300 line-through"
          >
            {annotation}
          </span>
        ))}
        {node.annotations.length === 0 && removed.length === 0 && <Empty text="No annotations discovered." />}
      </div>

      <form onSubmit={submit} className="mt-2 flex items-center gap-1.5">
        <input
          value={value}
          onChange={(event) => setValue(event.target.value)}
          placeholder={node.stack === 'csharp-dotnet' ? '[Required]' : '@NotNull'}
          aria-label="Annotation to add"
          spellCheck={false}
          className={INPUT_CLASS}
        />
        <button type="submit" className="shrink-0 rounded bg-violet-500 px-2 py-1 text-[10px] font-semibold text-ink-950 transition hover:bg-violet-400">
          Add
        </button>
      </form>
      <div className="mt-1.5">
        <PresetChips onPick={add} stack={node.stack} />
      </div>
    </Section>
  );
}

function PresetChips({ stack, onPick }: { stack: Stack; onPick: (annotation: string) => void }) {
  const presets = ANNOTATION_PRESETS[stack];
  if (presets.length === 0) {
    return null;
  }

  return (
    <div className="flex flex-wrap gap-1">
      {presets.map((preset) => (
        <button
          key={preset}
          type="button"
          onClick={() => onPick(preset)}
          title={`Add ${preset}`}
          className="rounded border border-violet-400/20 bg-violet-400/[0.07] px-1.5 py-0.5 font-mono text-[9px] text-violet-200 transition hover:border-violet-300/50 hover:bg-violet-400/15"
        >
          + {preset}
        </button>
      ))}
    </div>
  );
}

function RelationList({
  relations,
  byId,
  side,
  onSelect,
  onRemove,
}: {
  relations: ComponentRelation[];
  byId: Map<string, ComponentNode>;
  side: 'source' | 'target';
  onSelect: (node: ComponentNode | null) => void;
  onRemove: (relation: ComponentRelation) => void;
}) {
  return (
    <ul className="space-y-1">
      {relations.map((relation) => {
        const related = byId.get(side === 'target' ? relation.targetId : relation.sourceId);
        if (!related) {
          return null;
        }
        return (
          <li key={`${relation.sourceId}-${relation.targetId}-${relation.type}`} className="flex items-center gap-1">
            <button
              type="button"
              onClick={() => onSelect(related)}
              className="flex min-w-0 flex-1 items-center gap-2 rounded-md border border-transparent px-2 py-1 text-left transition hover:border-ink-600 hover:bg-ink-850"
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
            <button
              type="button"
              onClick={() => onRemove(relation)}
              title="Cut this relation in the draft"
              aria-label={`Cut relation to ${related.name}`}
              className="shrink-0 rounded px-1 text-[12px] leading-none text-slate-600 transition hover:bg-rose-500/10 hover:text-rose-300"
            >
              ×
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
  aiConfigured,
  aiFixingId,
  onFixWithAi,
  triage,
  onTriage,
}: {
  workspace: WorkspaceIR;
  onSelectNodeId: (nodeId: string) => void;
  onOpenFinding: (finding: AuditFinding) => void;
  aiConfigured: boolean;
  aiFixingId: string | null;
  onFixWithAi: (finding: AuditFinding) => void;
  triage: TriageState;
  onTriage: () => void;
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
        aiConfigured={aiConfigured}
        aiFixingId={aiFixingId}
        onFixWithAi={onFixWithAi}
        triage={triage}
        onTriage={onTriage}
      />

      <div className="mt-5 rounded-lg border border-ink-700/60 bg-ink-950/40 px-3 py-2.5">
        <p className="text-[11px] font-medium text-slate-300">Inspect a component</p>
        <p className="mt-1 text-[10.5px] leading-relaxed text-slate-500">
          Click any node in the Macro Graph or UML view to see and edit its annotations, fields, methods
          and dependencies here.
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

function defaultVisibility(stack: Stack): string {
  if (stack === 'csharp-dotnet') {
    return 'public';
  }
  return 'private';
}

function splitAnnotations(value: string): string[] {
  const items: string[] = [];
  let current = '';
  let depth = 0;
  let quote: string | null = null;

  for (const char of value) {
    if (quote) {
      current += char;
      if (char === quote) {
        quote = null;
      }
      continue;
    }
    if (char === '"' || char === "'") {
      quote = char;
      current += char;
      continue;
    }
    if (char === '(' || char === '[') {
      depth += 1;
    } else if (char === ')' || char === ']') {
      depth = Math.max(0, depth - 1);
    }

    if (char === ',' && depth === 0) {
      if (current.trim()) {
        items.push(current.trim());
      }
      current = '';
      continue;
    }
    current += char;
  }

  if (current.trim()) {
    items.push(current.trim());
  }

  const seen = new Set<string>();
  return items.filter((item) => {
    const key = annotationName(item);
    if (seen.has(key)) {
      return false;
    }
    seen.add(key);
    return true;
  });
}

function normalizeAnnotation(annotation: string): string {
  return annotation.replace(/\s+/g, '').replace(/["']/g, '').toLowerCase();
}

function annotationName(annotation: string): string {
  const text = annotation
    .trim()
    .replace(/^\[/, '')
    .split('(', 1)[0]
    .replace(/^@/, '')
    .replace(/\]$/, '')
    .trim();
  return (text.split('.').pop() ?? '').toLowerCase();
}

function toggleAnnotation(current: string, preset: string): string {
  const items = splitAnnotations(current);
  const name = annotationName(preset);
  const index = items.findIndex((item) => annotationName(item) === name);
  if (index < 0) {
    items.push(preset);
  } else if (normalizeAnnotation(items[index]) === normalizeAnnotation(preset)) {
    items.splice(index, 1);
  } else {
    items[index] = preset;
  }
  return items.join(', ');
}
