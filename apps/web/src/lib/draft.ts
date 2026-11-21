import type { ComponentRelation, RelationType } from '../types/core-ir';

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

export function emptyDraft(): RelationDraft {
  return { added: [], removed: [] };
}

export function isDraftEmpty(draft: RelationDraft): boolean {
  return draft.added.length === 0 && draft.removed.length === 0;
}

/** The relations the canvas should show: scanned IR minus disconnects plus draft connections. */
export function applyDraft(base: ComponentRelation[], draft: RelationDraft): ComponentRelation[] {
  const dropped = new Set(draft.removed.map(keyOf));
  const scanned = new Set(base.map(keyOf));

  return [
    ...base.filter((relation) => !dropped.has(keyOf(relation))),
    ...draft.added.filter((relation) => !scanned.has(keyOf(relation))),
  ];
}

export function connectRelation(
  draft: RelationDraft,
  base: ComponentRelation[],
  relation: ComponentRelation,
): RelationDraft {
  const key = keyOf(relation);
  const alreadyScanned =
    base.some((item) => keyOf(item) === key) && !draft.removed.some((item) => keyOf(item) === key);

  if (relation.sourceId === relation.targetId || alreadyScanned) {
    return draft;
  }

  return {
    added: draft.added.some((item) => keyOf(item) === key) ? draft.added : [...draft.added, relation],
    removed: draft.removed.filter((item) => keyOf(item) !== key),
  };
}

export function disconnectRelation(
  draft: RelationDraft,
  base: ComponentRelation[],
  relation: ComponentRelation,
): RelationDraft {
  const key = keyOf(relation);
  const added = draft.added.filter((item) => keyOf(item) !== key);
  const wasScanned = base.some((item) => keyOf(item) === key);

  if (!wasScanned || draft.removed.some((item) => keyOf(item) === key)) {
    return { added, removed: draft.removed };
  }

  return { added, removed: [...draft.removed, relation] };
}
