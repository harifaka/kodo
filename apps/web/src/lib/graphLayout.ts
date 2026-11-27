/**
 * Deterministic layered swimlane geometry for the Macro Graph (Phase 14).
 *
 * Components are grouped into the same seven architectural bands the Mermaid UML namespaces use
 * (`UI` -> `Controllers` -> `Services` -> `Repositories` -> `Entities` -> `DTOs` -> `Other`), and
 * wide layers wrap into a tidy grid instead of one endless strip.
 *
 * Pure math only — no React Flow types — so the layout can be reasoned about (and tested) alone.
 */

import { layerGroupOf, type LayerGroup } from './graphFilter';
import type { ComponentNode } from '../types/core-ir';

export type GraphDirection = 'TB' | 'LR';

/** Fixed architectural order — mirrors `LAYER_BUCKETS` in `services/api-python/app/services/mermaid.py`. */
export const ARCH_BAND_ORDER: LayerGroup[] = [
  'ui',
  'controller',
  'service',
  'repository',
  'entity',
  'dto',
  'other',
];

export const ARCH_BAND_META: Record<LayerGroup, { label: string; color: string }> = {
  ui: { label: 'UI', color: '#22d3ee' },
  controller: { label: 'Controllers', color: '#38bdf8' },
  service: { label: 'Services', color: '#34d399' },
  repository: { label: 'Repositories', color: '#fbbf24' },
  entity: { label: 'Entities', color: '#f472b6' },
  dto: { label: 'DTOs', color: '#a78bfa' },
  other: { label: 'Other', color: '#94a3b8' },
};

export const NODE_WIDTH = 248;
export const NODE_HEIGHT = 96;

/** Width of a band before its nodes wrap into another row (TB orientation). */
const MAX_ROW_NODES = 5;
/** Nodes per column before wrapping into another column (LR orientation). */
const MAX_COLUMN_NODES = 8;

const NODE_GAP_X = 26;
const NODE_GAP_Y = 26;
const BAND_PADDING = 20;
const BAND_LABEL_HEIGHT = 34;
const BAND_GAP = 56;

export interface BandRect {
  id: LayerGroup;
  label: string;
  color: string;
  count: number;
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface SwimlaneLayout {
  bands: BandRect[];
  positions: Map<string, { x: number; y: number }>;
  width: number;
  height: number;
}

export function archBandOf(node: ComponentNode): LayerGroup {
  return layerGroupOf(node);
}

export function sortWithinBand(nodes: ComponentNode[]): ComponentNode[] {
  return nodes
    .slice()
    .sort((left, right) => {
      const byName = left.name.toLowerCase().localeCompare(right.name.toLowerCase());
      return byName !== 0 ? byName : left.id.localeCompare(right.id);
    });
}

export function computeSwimlaneLayout(
  nodes: ComponentNode[],
  direction: GraphDirection,
): SwimlaneLayout {
  const grouped = new Map<LayerGroup, ComponentNode[]>();
  for (const node of nodes) {
    const band = archBandOf(node);
    const bucket = grouped.get(band);
    if (bucket) {
      bucket.push(node);
    } else {
      grouped.set(band, [node]);
    }
  }

  const bands: BandRect[] = [];
  const positions = new Map<string, { x: number; y: number }>();
  const vertical = direction === 'LR';
  let cursor = 0;

  for (const id of ARCH_BAND_ORDER) {
    const members = grouped.get(id);
    if (!members || members.length === 0) {
      continue;
    }

    const ordered = sortWithinBand(members);
    const meta = ARCH_BAND_META[id];
    const perLine = vertical ? MAX_COLUMN_NODES : MAX_ROW_NODES;
    const lines = Math.ceil(ordered.length / perLine);
    const linesInLastLine = ordered.length - (lines - 1) * perLine;
    const longestLine = Math.min(ordered.length, perLine);

    // TB: `lines` = rows, each holding up to `MAX_ROW_NODES` nodes.
    // LR: `lines` = columns, each holding up to `MAX_COLUMN_NODES` nodes.
    const innerWidth = vertical
      ? lines * NODE_WIDTH + (lines - 1) * NODE_GAP_X
      : longestLine * NODE_WIDTH + (longestLine - 1) * NODE_GAP_X;
    const innerHeight = vertical
      ? longestLine * NODE_HEIGHT + (longestLine - 1) * NODE_GAP_Y
      : lines * NODE_HEIGHT + (lines - 1) * NODE_GAP_Y;

    const bandWidth = innerWidth + BAND_PADDING * 2;
    const bandHeight = innerHeight + BAND_LABEL_HEIGHT + BAND_PADDING;
    const originX = vertical ? cursor : 0;
    const originY = vertical ? 0 : cursor;

    bands.push({
      id,
      label: meta.label,
      color: meta.color,
      count: ordered.length,
      x: originX,
      y: originY,
      width: bandWidth,
      height: bandHeight,
    });

    ordered.forEach((node, index) => {
      const line = Math.floor(index / perLine);
      const slot = index % perLine;
      // Centre a short last row/column inside the band so the grid stays visually balanced.
      const isLastLine = line === lines - 1;
      const offset = isLastLine ? ((longestLine - linesInLastLine) * (NODE_WIDTH + NODE_GAP_X)) / 2 : 0;

      positions.set(node.id, vertical
        ? {
            x: originX + BAND_PADDING + line * (NODE_WIDTH + NODE_GAP_X),
            y: originY + BAND_LABEL_HEIGHT + slot * (NODE_HEIGHT + NODE_GAP_Y),
          }
        : {
            x: originX + BAND_PADDING + offset + slot * (NODE_WIDTH + NODE_GAP_X),
            y: originY + BAND_LABEL_HEIGHT + line * (NODE_HEIGHT + NODE_GAP_Y),
          });
    });

    cursor += (vertical ? bandWidth : bandHeight) + BAND_GAP;
  }

  const width = bands.reduce((max, band) => Math.max(max, band.x + band.width), 0);
  const height = bands.reduce((max, band) => Math.max(max, band.y + band.height), 0);

  return { bands, positions, width, height };
}
