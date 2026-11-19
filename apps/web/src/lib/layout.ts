import { MarkerType, type Edge, type Node } from '@xyflow/react';
import { LAYER_META, LAYER_ORDER, RELATION_META } from './layers';
import type { ComponentNode, ComponentRelation, Layer } from '../types/core-ir';

export type ComponentNodeData = { component: ComponentNode; relationCount: number };
export type LayerHeaderData = { label: string; color: string; count: number };

export const NODE_WIDTH = 248;
const NODE_HEIGHT = 96;
const COLUMN_GAP = 84;
const SUBCOLUMN_GAP = 28;
const ROW_GAP = 26;
const TOP_OFFSET = 28;
const MAX_ROWS_PER_SUBCOLUMN = 8;

export function buildGraph(
  nodes: ComponentNode[],
  relations: ComponentRelation[],
): { nodes: Node[]; edges: Edge[] } {
  const byLayer = new Map<Layer, ComponentNode[]>();
  for (const layer of LAYER_ORDER) {
    byLayer.set(layer, []);
  }
  for (const node of nodes) {
    byLayer.get(node.layer)?.push(node);
  }

  const degree = new Map<string, number>();
  for (const relation of relations) {
    degree.set(relation.sourceId, (degree.get(relation.sourceId) ?? 0) + 1);
    degree.set(relation.targetId, (degree.get(relation.targetId) ?? 0) + 1);
  }

  const flowNodes: Node[] = [];
  let cursorX = 0;

  for (const layer of LAYER_ORDER) {
    const layerNodes = (byLayer.get(layer) ?? []).slice().sort((a, b) => a.name.localeCompare(b.name));
    if (layerNodes.length === 0) {
      continue;
    }

    // Large layers wrap into sub-columns so the graph stays roughly viewport-shaped.
    const subColumns = Math.ceil(layerNodes.length / MAX_ROWS_PER_SUBCOLUMN);
    const layerWidth = subColumns * NODE_WIDTH + (subColumns - 1) * SUBCOLUMN_GAP;
    const meta = LAYER_META[layer];

    flowNodes.push({
      id: `layer:${layer}`,
      type: 'layerHeader',
      position: { x: cursorX, y: -52 },
      data: {
        label: meta.label,
        color: meta.color,
        count: layerNodes.length,
      } satisfies LayerHeaderData,
      selectable: false,
      draggable: false,
      focusable: false,
    });

    layerNodes.forEach((component, index) => {
      const subColumn = Math.floor(index / MAX_ROWS_PER_SUBCOLUMN);
      const row = index % MAX_ROWS_PER_SUBCOLUMN;
      flowNodes.push({
        id: component.id,
        type: 'component',
        position: {
          x: cursorX + subColumn * (NODE_WIDTH + SUBCOLUMN_GAP),
          y: TOP_OFFSET + row * (NODE_HEIGHT + ROW_GAP),
        },
        data: {
          component,
          relationCount: degree.get(component.id) ?? 0,
        } satisfies ComponentNodeData,
        width: NODE_WIDTH,
      });
    });

    cursorX += layerWidth + COLUMN_GAP;
  }

  const edges: Edge[] = relations.map((relation) => {
    const meta = RELATION_META[relation.type];
    return {
      id: `${relation.sourceId}->${relation.targetId}:${relation.type}`,
      source: relation.sourceId,
      target: relation.targetId,
      type: 'smoothstep',
      data: { relation: relation.type },
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
