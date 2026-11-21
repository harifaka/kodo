import { useEffect, useRef, useState } from 'react';
import { EdgeLabelRenderer, getSmoothStepPath, type EdgeProps, type EdgeTypes } from '@xyflow/react';
import type { RelationEdgeData } from '../lib/layout';

/** Smoothstep edge with a cut hotspot; keeps canvas editing independent of edge selection. */
function RelationEdge({
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  markerEnd,
  style,
  data,
}: EdgeProps) {
  const [path, labelX, labelY] = getSmoothStepPath({
    sourceX,
    sourceY,
    sourcePosition,
    targetX,
    targetY,
    targetPosition,
  });
  const pathRef = useRef<SVGPathElement | null>(null);
  const [cutPosition, setCutPosition] = useState({ x: labelX, y: labelY });
  const edgeData = data as RelationEdgeData | undefined;

  useEffect(() => {
    const element = pathRef.current;
    if (!element) {
      return;
    }
    // Offset from the midpoint: the middle of a layer-to-layer edge often sits under a component card.
    const point = element.getPointAtLength(element.getTotalLength() * 0.3);
    setCutPosition({ x: point.x, y: point.y });
  }, [path]);

  return (
    <>
      <path ref={pathRef} d={path} className="react-flow__edge-path" style={style} markerEnd={markerEnd} />
      <EdgeLabelRenderer>
        <button
          type="button"
          onClick={(event) => {
            event.stopPropagation();
            edgeData?.onCut?.();
          }}
          title="Cut this relation in the draft"
          aria-label="Cut this relation in the draft"
          style={{
            transform: `translate(-50%, -50%) translate(${cutPosition.x}px, ${cutPosition.y}px)`,
            zIndex: 5,
          }}
          className="nodrag nopan pointer-events-auto absolute flex h-[18px] w-[18px] items-center justify-center rounded-full border border-ink-600 bg-ink-900 text-[11px] leading-none text-slate-500 opacity-30 shadow transition hover:border-rose-500/70 hover:text-rose-300 hover:opacity-100"
        >
          ×
        </button>
      </EdgeLabelRenderer>
    </>
  );
}

export const edgeTypes = {
  relation: RelationEdge,
} satisfies EdgeTypes;
