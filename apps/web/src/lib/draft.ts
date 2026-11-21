import type { ComponentField, ComponentRelation, RelationType, WorkspaceIR } from '../types/core-ir';
import type { PatchOperation } from '../types/patching';

/** Stable identity of a relation, used for diffing the draft against the scanned IR. */
export function relationKey(sourceId: string, targetId: string, type: RelationType): string {
  return `${sourceId}->${targetId}:${type}`;
}

export function keyOf(relation: ComponentRelation): string {
  return relationKey(relation.sourceId, relation.targetId, relation.type);
}

export interface RelationDraft {
  /** Relations created on the canvas that do not exist in the scanned IR. */
  added: ComponentRelation[];
  /** Relations from the scanned IR that the draft disconnected. */
  removed: ComponentRelation[];
}

export interface UpdatedField {
  originalName: string;
  field: ComponentField;
}

export interface NodeDraft {
  fields: {
    added: ComponentField[];
    updated: UpdatedField[];
    removed: string[];
  };
  addedAnnotations: string[];
  removedAnnotations: string[];
}

/** Browser-only edits: macro relations plus per-node micro field/annotation changes. */
export interface Draft {
  relations: RelationDraft;
  nodes: Record<string, NodeDraft>;
}

export interface DraftEditCount {
  relations: number;
  fields: number;
  annotations: number;
  total: number;
}

export function emptyDraft(): Draft {
  return { relations: { added: [], removed: [] }, nodes: {} };
}

export function emptyNodeDraft(): NodeDraft {
  return {
    fields: { added: [], updated: [], removed: [] },
    addedAnnotations: [],
    removedAnnotations: [],
  };
}

export function nodeDraftOf(draft: Draft, nodeId: string): NodeDraft | undefined {
  return draft.nodes[nodeId];
}

export function hasNodeDraft(draft: Draft, nodeId: string): boolean {
  const node = draft.nodes[nodeId];
  return node !== undefined && !isNodeDraftEmpty(node);
}

function isNodeDraftEmpty(node: NodeDraft): boolean {
  return (
    node.fields.added.length === 0 &&
    node.fields.updated.length === 0 &&
    node.fields.removed.length === 0 &&
    node.addedAnnotations.length === 0 &&
    node.removedAnnotations.length === 0
  );
}

export function isDraftEmpty(draft: Draft): boolean {
  return draftEditCount(draft).total === 0;
}

export function draftEditCount(draft: Draft): DraftEditCount {
  let fields = 0;
  let annotations = 0;

  for (const node of Object.values(draft.nodes)) {
    fields += node.fields.added.length + node.fields.updated.length + node.fields.removed.length;
    annotations += node.addedAnnotations.length + node.removedAnnotations.length;
  }

  const relations = draft.relations.added.length + draft.relations.removed.length;
  return { relations, fields, annotations, total: relations + fields + annotations };
}

function withNodeDraft(draft: Draft, nodeId: string, node: NodeDraft): Draft {
  if (isNodeDraftEmpty(node)) {
    const nodes = { ...draft.nodes };
    delete nodes[nodeId];
    return { ...draft, nodes };
  }
  return { ...draft, nodes: { ...draft.nodes, [nodeId]: node } };
}

function mutateNodeDraft(draft: Draft, nodeId: string, mutate: (node: NodeDraft) => NodeDraft): Draft {
  return withNodeDraft(draft, nodeId, mutate(draft.nodes[nodeId] ?? emptyNodeDraft()));
}

export function addField(draft: Draft, nodeId: string, field: ComponentField): Draft {
  if (!field.name.trim()) {
    return draft;
  }
  return mutateNodeDraft(draft, nodeId, (node) => {
    const added = node.fields.added.some((item) => item.name === field.name)
      ? node.fields.added.map((item) => (item.name === field.name ? field : item))
      : [...node.fields.added, field];
    return { ...node, fields: { ...node.fields, added } };
  });
}

export function updateField(
  draft: Draft,
  nodeId: string,
  originalName: string,
  field: ComponentField,
): Draft {
  return mutateNodeDraft(draft, nodeId, (node) => {
    if (node.fields.added.some((item) => item.name === originalName)) {
      const added = node.fields.added.map((item) => (item.name === originalName ? field : item));
      return { ...node, fields: { ...node.fields, added } };
    }

    const updated = node.fields.updated.filter((item) => item.originalName !== originalName);
    updated.push({ originalName, field });
    const removed = node.fields.removed.filter((name) => name !== originalName);
    return { ...node, fields: { ...node.fields, updated, removed } };
  });
}

export function removeField(draft: Draft, nodeId: string, fieldName: string): Draft {
  return mutateNodeDraft(draft, nodeId, (node) => {
    if (node.fields.added.some((item) => item.name === fieldName)) {
      return {
        ...node,
        fields: { ...node.fields, added: node.fields.added.filter((item) => item.name !== fieldName) },
      };
    }

    const removed = node.fields.removed.includes(fieldName)
      ? node.fields.removed
      : [...node.fields.removed, fieldName];
    const updated = node.fields.updated.filter((item) => item.originalName !== fieldName);
    return { ...node, fields: { ...node.fields, removed, updated } };
  });
}

export function addNodeAnnotation(draft: Draft, nodeId: string, annotation: string): Draft {
  const value = annotation.trim();
  if (!value) {
    return draft;
  }
  return mutateNodeDraft(draft, nodeId, (node) => {
    if (node.removedAnnotations.includes(value)) {
      return {
        ...node,
        removedAnnotations: node.removedAnnotations.filter((item) => item !== value),
      };
    }
    if (node.addedAnnotations.includes(value)) {
      return node;
    }
    return { ...node, addedAnnotations: [...node.addedAnnotations, value] };
  });
}

export function removeNodeAnnotation(draft: Draft, nodeId: string, annotation: string): Draft {
  return mutateNodeDraft(draft, nodeId, (node) => {
    if (node.addedAnnotations.includes(annotation)) {
      return { ...node, addedAnnotations: node.addedAnnotations.filter((item) => item !== annotation) };
    }
    if (node.removedAnnotations.includes(annotation)) {
      return node;
    }
    return { ...node, removedAnnotations: [...node.removedAnnotations, annotation] };
  });
}

function applyNodeDraft(
  node: WorkspaceIR['nodes'][number],
  draft: NodeDraft | undefined,
): WorkspaceIR['nodes'][number] {
  if (!draft) {
    return node;
  }

  const removed = new Set(draft.fields.removed);
  const updates = new Map(draft.fields.updated.map((item) => [item.originalName, item.field]));

  const fields = node.fields
    .filter((field) => !removed.has(field.name))
    .map((field) => updates.get(field.name) ?? field);

  for (const added of draft.fields.added) {
    if (!fields.some((field) => field.name === added.name)) {
      fields.push(added);
    }
  }

  const droppedAnnotations = new Set(draft.removedAnnotations);
  const annotations = node.annotations.filter((annotation) => !droppedAnnotations.has(annotation));
  for (const annotation of draft.addedAnnotations) {
    if (!annotations.includes(annotation)) {
      annotations.push(annotation);
    }
  }

  return { ...node, fields, annotations };
}

export function applyDraft(base: WorkspaceIR, draft: Draft): WorkspaceIR {
  return {
    ...base,
    nodes: base.nodes.map((node) => applyNodeDraft(node, draft.nodes[node.id])),
    relations: applyRelationDraft(base.relations, draft.relations),
  };
}

/** The relations the canvas should show: scanned IR minus disconnects plus draft connections. */
export function applyRelationDraft(
  base: ComponentRelation[],
  draft: RelationDraft,
): ComponentRelation[] {
  const dropped = new Set(draft.removed.map(keyOf));
  const scanned = new Set(base.map(keyOf));

  return [
    ...base.filter((relation) => !dropped.has(keyOf(relation))),
    ...draft.added.filter((relation) => !scanned.has(keyOf(relation))),
  ];
}

export function connectRelation(
  draft: Draft,
  base: ComponentRelation[],
  relation: ComponentRelation,
): Draft {
  const key = keyOf(relation);
  const alreadyScanned =
    base.some((item) => keyOf(item) === key) &&
    !draft.relations.removed.some((item) => keyOf(item) === key);

  if (relation.sourceId === relation.targetId || alreadyScanned) {
    return draft;
  }

  return {
    ...draft,
    relations: {
      added: draft.relations.added.some((item) => keyOf(item) === key)
        ? draft.relations.added
        : [...draft.relations.added, relation],
      removed: draft.relations.removed.filter((item) => keyOf(item) !== key),
    },
  };
}

export function disconnectRelation(
  draft: Draft,
  base: ComponentRelation[],
  relation: ComponentRelation,
): Draft {
  const key = keyOf(relation);
  const added = draft.relations.added.filter((item) => keyOf(item) !== key);
  const wasScanned = base.some((item) => keyOf(item) === key);

  if (!wasScanned || draft.relations.removed.some((item) => keyOf(item) === key)) {
    return { ...draft, relations: { added, removed: draft.relations.removed } };
  }

  return { ...draft, relations: { added, removed: [...draft.relations.removed, relation] } };
}

export type FieldDraftStatus = 'added' | 'modified' | 'removed';

export function fieldDraftStatus(
  draft: Draft,
  nodeId: string,
  fieldName: string,
  baseName = fieldName,
): FieldDraftStatus | undefined {
  const node = draft.nodes[nodeId];
  if (!node) {
    return undefined;
  }
  if (node.fields.added.some((item) => item.name === fieldName)) {
    return 'added';
  }
  if (node.fields.removed.includes(baseName)) {
    return 'removed';
  }
  if (node.fields.updated.some((item) => item.originalName === baseName)) {
    return 'modified';
  }
  return undefined;
}

export function removedFieldsFor(
  baseFields: ComponentField[],
  node: NodeDraft | undefined,
): ComponentField[] {
  if (!node || node.fields.removed.length === 0) {
    return [];
  }
  const removed = new Set(node.fields.removed);
  return baseFields.filter((field) => removed.has(field.name));
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function typeMentions(type: string, name: string): boolean {
  return new RegExp(`\\b${escapeRegExp(name)}\\b`).test(type);
}

export interface PatchPlan {
  operations: PatchOperation[];
  warnings: string[];
}

/** Translate the browser draft into stack-agnostic patch operations for POST /api/v1/dry-run. */
export function buildPatchOperations(base: WorkspaceIR, draft: Draft): PatchPlan {
  const operations: PatchOperation[] = [];
  const warnings: string[] = [];

  for (const node of base.nodes) {
    const nodeDraft = draft.nodes[node.id];
    if (!nodeDraft) {
      continue;
    }

    for (const field of nodeDraft.fields.added) {
      operations.push({ op: 'add_field', filePath: node.filePath, typeName: node.name, field });
    }
    for (const update of nodeDraft.fields.updated) {
      operations.push({
        op: 'update_field',
        filePath: node.filePath,
        typeName: node.name,
        originalName: update.originalName,
        field: update.field,
      });
    }
    for (const fieldName of nodeDraft.fields.removed) {
      operations.push({ op: 'remove_field', filePath: node.filePath, typeName: node.name, fieldName });
    }
    for (const annotation of nodeDraft.addedAnnotations) {
      operations.push({
        op: 'add_annotation',
        filePath: node.filePath,
        typeName: node.name,
        annotation,
      });
    }
    for (const annotation of nodeDraft.removedAnnotations) {
      operations.push({
        op: 'remove_annotation',
        filePath: node.filePath,
        typeName: node.name,
        annotation,
      });
    }
  }

  const byId = new Map(base.nodes.map((node) => [node.id, node]));

  for (const relation of draft.relations.added) {
    const source = byId.get(relation.sourceId);
    const target = byId.get(relation.targetId);
    if (!source || !target) {
      continue;
    }
    operations.push({
      op: 'add_dependency',
      filePath: source.filePath,
      typeName: source.name,
      field: {
        name: `${target.name.charAt(0).toLowerCase()}${target.name.slice(1)}`,
        type: target.name,
        visibility: 'private',
        annotations: [],
      },
    });
  }

  for (const relation of draft.relations.removed) {
    const source = byId.get(relation.sourceId);
    const target = byId.get(relation.targetId);
    if (!source || !target) {
      continue;
    }
    const field = source.fields.find((item) => typeMentions(item.type, target.name));
    if (!field) {
      warnings.push(
        `Cannot preview removal of ${source.name} → ${target.name}: no field of type ${target.name} exists in the source file (constructor/method dependencies must be edited by hand).`,
      );
      continue;
    }
    operations.push({
      op: 'remove_dependency',
      filePath: source.filePath,
      typeName: source.name,
      fieldName: field.name,
    });
  }

  return { operations, warnings };
}
