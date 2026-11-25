import { edgeKey } from './audit';
import type { AuditReport, ComponentNode, ComponentRelation, Layer, Stack } from '../types/core-ir';

/** Coarse architectural buckets offered as filter pills (Core IR layers rolled up for humans). */
export type LayerGroup = 'controller' | 'service' | 'repository' | 'entity' | 'dto' | 'ui' | 'other';

export interface LayerGroupMeta {
  id: LayerGroup;
  label: string;
  layers: Layer[];
  hint: string;
}

export const LAYER_GROUPS: LayerGroupMeta[] = [
  { id: 'controller', label: 'Controller', layers: ['controller'], hint: 'HTTP / request boundary' },
  { id: 'service', label: 'Service', layers: ['service'], hint: 'Business logic' },
  { id: 'repository', label: 'Repository', layers: ['repository'], hint: 'Persistence boundary' },
  { id: 'entity', label: 'Entity', layers: ['entity'], hint: 'Domain data' },
  {
    id: 'dto',
    label: 'DTO',
    layers: [],
    hint: 'Components named *Dto / *DTO / *Request / *Response',
  },
  {
    id: 'ui',
    label: 'UI',
    layers: ['view', 'viewmodel', 'component'],
    hint: 'Views, ViewModels and UI components',
  },
  { id: 'other', label: 'Other', layers: ['other'], hint: 'Unclassified components' },
];

const DTO_NAME = /(?:Dto|DTO|Request|Response)$/;

export function layerGroupOf(node: ComponentNode): LayerGroup {
  if (DTO_NAME.test(node.name)) {
    return 'dto';
  }
  const match = LAYER_GROUPS.find((group) => group.layers.includes(node.layer));
  return match?.id ?? 'other';
}

export interface GraphFilter {
  query: string;
  layers: LayerGroup[];
  stacks: Stack[];
  issuesOnly: boolean;
  /** 1-hop neighborhood around the selected component; inert without a selection. */
  focusOneHop: boolean;
}

export const EMPTY_GRAPH_FILTER: GraphFilter = {
  query: '',
  layers: [],
  stacks: [],
  issuesOnly: false,
  focusOneHop: false,
};

export function isFilterActive(filter: GraphFilter): boolean {
  return (
    filter.query.trim().length > 0 ||
    filter.layers.length > 0 ||
    filter.stacks.length > 0 ||
    filter.issuesOnly ||
    filter.focusOneHop
  );
}

export interface FilterOutcome {
  nodes: ComponentNode[];
  relations: ComponentRelation[];
  /** True when the visible set differs from the workspace (any effective filter). */
  active: boolean;
  focusActive: boolean;
  issuesActive: boolean;
  queryActive: boolean;
}

/** Search matches component name, source file path and annotations (case-insensitive). */
export function matchesQuery(node: ComponentNode, query: string): boolean {
  const needle = query.trim().toLowerCase();
  if (!needle) {
    return true;
  }
  return (
    node.name.toLowerCase().includes(needle) ||
    node.filePath.toLowerCase().includes(needle) ||
    node.annotations.some((annotation) => annotation.toLowerCase().includes(needle))
  );
}

export function searchComponents(nodes: ComponentNode[], query: string, limit = 8): ComponentNode[] {
  const needle = query.trim();
  if (!needle) {
    return [];
  }
  return nodes.filter((node) => matchesQuery(node, needle)).slice(0, limit);
}

/**
 * Restrict the workspace IR for the Macro Graph / UML without touching the underlying data: the
 * draft editor and the guarded apply pipeline keep operating on the full IR.
 */
export function applyGraphFilter(
  nodes: ComponentNode[],
  relations: ComponentRelation[],
  audit: AuditReport | undefined,
  filter: GraphFilter,
  selectedId: string | null,
): FilterOutcome {
  const findingNodeIds = new Set<string>();
  const findingEdgeKeys = new Set<string>();
  for (const finding of audit?.findings ?? []) {
    for (const nodeId of finding.nodeIds) {
      findingNodeIds.add(nodeId);
    }
    for (const key of finding.edgeKeys) {
      findingEdgeKeys.add(key);
    }
  }

  const focusActive =
    filter.focusOneHop && selectedId !== null && nodes.some((node) => node.id === selectedId);
  let focusIds: Set<string> | null = null;
  if (focusActive && selectedId !== null) {
    focusIds = new Set([selectedId]);
    for (const relation of relations) {
      if (relation.sourceId === selectedId) {
        focusIds.add(relation.targetId);
      }
      if (relation.targetId === selectedId) {
        focusIds.add(relation.sourceId);
      }
    }
  }

  const layerSet = new Set(filter.layers);
  const stackSet = new Set(filter.stacks);
  const queryActive = filter.query.trim().length > 0;

  const keptNodes = nodes.filter((node) => {
    if (focusIds && !focusIds.has(node.id)) {
      return false;
    }
    if (filter.issuesOnly && !findingNodeIds.has(node.id)) {
      return false;
    }
    if (layerSet.size > 0 && !layerSet.has(layerGroupOf(node))) {
      return false;
    }
    if (stackSet.size > 0 && !stackSet.has(node.stack)) {
      return false;
    }
    return matchesQuery(node, filter.query);
  });

  const keptIds = new Set(keptNodes.map((node) => node.id));
  const keptRelations = relations.filter((relation) => {
    if (!keptIds.has(relation.sourceId) || !keptIds.has(relation.targetId)) {
      return false;
    }
    // Issues Only: show the relations the audit actually complains about.
    return !filter.issuesOnly || findingEdgeKeys.has(edgeKey(relation.sourceId, relation.targetId));
  });

  return {
    nodes: keptNodes,
    relations: keptRelations,
    active:
      focusActive ||
      filter.issuesOnly ||
      queryActive ||
      filter.layers.length > 0 ||
      filter.stacks.length > 0,
    focusActive,
    issuesActive: filter.issuesOnly,
    queryActive,
  };
}
