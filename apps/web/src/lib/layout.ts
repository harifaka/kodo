import { MarkerType, type Edge, type Node } from '@xyflow/react';
import { RELATION_META } from './layers';
import { computeSwimlaneLayout, NODE_WIDTH, type GraphDirection } from './graphLayout';
import type { ComponentNode, ComponentRelation, RelationType, Severity } from '../types/core-ir';

export type ComponentNodeData = {
  component: ComponentNode;
  relationCount: number;
  audit?: { severity: Severity; count: number };
};
/** Non-interactive swimlane background for one architectural band (Phase 14). */
export type LayerBandData = {
  label: string;
  color: string;
  count: number;
  direction: GraphDirection;
};

export { NODE_WIDTH, type GraphDirection };

export interface RelationEdgeData extends Record<string, unknown> {
  relation: RelationType;
  onCut?: () => void;
}

export interface BuildGraphOptions {
  direction?: GraphDirection;
}

/**
 * Build the Macro Graph: layered swimlane bands (fixed architectural order, alphabetical inside a
 * band, wide bands wrapped into a grid) plus the Core IR relations as edges.
 */
export function buildGraph(
  nodes: ComponentNode[],
  relations: ComponentRelation[],
  options: BuildGraphOptions = {},
): { nodes: Node[]; edges: Edge[] } {
  const direction = options.direction ?? 'TB';
  const layout = computeSwimlaneLayout(nodes, direction);

  const degree = new Map<string, number>();
  for (const relation of relations) {
    degree.set(relation.sourceId, (degree.get(relation.sourceId) ?? 0) + 1);
    degree.set(relation.targetId, (degree.get(relation.targetId) ?? 0) + 1);
  }

  const flowNodes: Node[] = [];

  // Band guides first so they paint behind the component cards.
  for (const band of layout.bands) {
    flowNodes.push({
      id: `band:${band.id}`,
      type: 'layerBand',
      position: { x: band.x, y: band.y },
      data: {
        label: band.label,
        color: band.color,
        count: band.count,
        direction,
      } satisfies LayerBandData,
      width: band.width,
      height: band.height,
      style: { width: band.width, height: band.height, pointerEvents: 'none' },
      selectable: false,
      draggable: false,
      connectable: false,
      deletable: false,
      focusable: false,
      zIndex: 0,
    });
  }

  for (const component of nodes) {
    const position = layout.positions.get(component.id);
    if (!position) {
      continue;
    }
    flowNodes.push({
      id: component.id,
      type: 'component',
      position,
      data: {
        component,
        relationCount: degree.get(component.id) ?? 0,
      } satisfies ComponentNodeData,
      width: NODE_WIDTH,
      selectable: true,
      // Phase 3a edits relations only: components are never added or removed from the draft.
      deletable: false,
    });
  }

  const edges: Edge[] = relations.map((relation) => {
    const meta = RELATION_META[relation.type];
    return {
      id: `${relation.sourceId}->${relation.targetId}:${relation.type}`,
      source: relation.sourceId,
      target: relation.targetId,
      type: 'relation',
      data: { relation: relation.type } satisfies RelationEdgeData,
      style: {
        stroke: meta.color,
        strokeWidth: 1.4,
        strokeDasharray: meta.dashed ? '5 4' : undefined,
      },
      markerEnd: { type: MarkerType.ArrowClosed, color: meta.color, width: 16, height: 16 },
    };
  });

  return { nodes: flowNodes, edges };
}

export function edgeTouchesNode(edge: Edge, nodeId: string | null): boolean {
  return nodeId !== null && (edge.source === nodeId || edge.target === nodeId);
}