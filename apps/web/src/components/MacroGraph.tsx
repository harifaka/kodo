import { useEffect, useMemo } from 'react';
import {
  Background,
  BackgroundVariant,
  Controls,
  Handle,
  MiniMap,
  MarkerType,
  Position,
  ReactFlow,
  ReactFlowProvider,
  useNodesInitialized,
  useReactFlow,
  type Edge,
  type Node,
  type NodeProps,
  type NodeTypes,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { edgeTouchesNode, type ComponentNodeData, type LayerHeaderData } from '../lib/layout';
import { KIND_LABEL, LAYER_META, RELATION_META } from '../lib/layers';
import { SEVERITY_META, auditedEdgeKeys, edgeKey, nodeAuditIndex } from '../lib/audit';
import type { AuditReport, ComponentNode, ComponentRelation } from '../types/core-ir';
import { GraphIcon } from './icons';
import { AlertBadge } from './AuditPanel';

interface MacroGraphProps {
  nodes: ComponentNode[];
  relations: ComponentRelation[];
  flowNodes: Node[];
  flowEdges: Edge[];
  audit: AuditReport;
  selectedId: string | null;
  onSelect: (node: ComponentNode | null) => void;
}

export function MacroGraph({
  nodes,
  relations,
  flowNodes,
  flowEdges,
  audit,
  selectedId,
  onSelect,
}: MacroGraphProps) {
  return (
    <ReactFlowProvider>
      <MacroGraphCanvas
        nodes={nodes}
        relations={relations}
        flowNodes={flowNodes}
        flowEdges={flowEdges}
        audit={audit}
        selectedId={selectedId}
        onSelect={onSelect}
      />
    </ReactFlowProvider>
  );
}

function MacroGraphCanvas({
  nodes,
  relations,
  flowNodes,
  flowEdges,
  audit,
  selectedId,
  onSelect,
}: MacroGraphProps) {
  const { fitView } = useReactFlow();
  const initialized = useNodesInitialized();

  useEffect(() => {
    if (!initialized) {
      return;
    }
    // Fit only once the custom nodes have measured themselves, otherwise edges/labels are clipped.
    const frame = window.requestAnimationFrame(() => {
      void fitView({ padding: 0.12, maxZoom: 1.05, minZoom: 0.15, duration: 180 });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [initialized, fitView]);

  const auditByNode = useMemo(() => nodeAuditIndex(audit), [audit]);
  const flaggedEdges = useMemo(() => auditedEdgeKeys(audit), [audit]);

  const decoratedNodes = useMemo(
    () =>
      flowNodes.map((node) => ({
        ...node,
        selected: node.id === selectedId,
        data: { ...node.data, audit: auditByNode.get(node.id) },
      })),
    [flowNodes, selectedId, auditByNode],
  );

  const decoratedEdges = useMemo(
    () =>
      flowEdges.map((edge) => {
        const flagged = flaggedEdges.has(edgeKey(edge.source, edge.target));
        const base = flagged
          ? {
              ...edge,
              style: { ...edge.style, stroke: SEVERITY_META.error.color, strokeWidth: 2.2 },
              markerEnd: {
                type: MarkerType.ArrowClosed,
                color: SEVERITY_META.error.color,
                width: 18,
                height: 18,
              },
            }
          : edge;

        if (selectedId === null) {
          return base;
        }

        return edgeTouchesNode(base, selectedId)
          ? { ...base, style: { ...base.style, opacity: 1, strokeWidth: flagged ? 2.6 : 2 }, zIndex: 5 }
          : { ...base, style: { ...base.style, opacity: 0.16 } };
      }),
    [flowEdges, selectedId, flaggedEdges],
  );

  return (
    <div className="relative h-full w-full bg-ink-950">
      <ReactFlow
        nodes={decoratedNodes}
        edges={decoratedEdges}
        nodeTypes={nodeTypes}
        onNodeClick={(_event, node) => {
          if (node.type === 'component') {
            onSelect((node.data as ComponentNodeData).component);
          }
        }}
        onNodeDoubleClick={(_event, node) => {
          if (node.type === 'component') {
            onSelect((node.data as ComponentNodeData).component);
            void fitView({ nodes: [{ id: node.id }], padding: 3, duration: 220, maxZoom: 1.1 });
          }
        }}
        onPaneClick={() => onSelect(null)}
        nodesConnectable={false}
        edgesFocusable={false}
        minZoom={0.12}
        maxZoom={1.8}
        fitView
        fitViewOptions={{ padding: 0.18, maxZoom: 1.05, minZoom: 0.45 }}
        className="kodo-flow"
      >
        <Background variant={BackgroundVariant.Dots} gap={26} size={1} color="#1c2637" />
        <Controls showInteractive={false} className="kodo-controls" />
        {nodes.length > 12 && (
          <MiniMap
            pannable
            zoomable
            maskColor="rgba(8,11,17,0.62)"
            className="kodo-minimap"
            style={{ width: 184, height: 112, bottom: 26, right: 12 }}
            nodeBorderRadius={4}
            nodeStrokeWidth={0}
            nodeColor={(node) => {
              if (node.type !== 'component') return 'transparent';
              const component = (node.data as ComponentNodeData).component;
              return LAYER_META[component.layer].color;
            }}
          />
        )}
      </ReactFlow>

      <div className="pointer-events-none absolute left-4 top-3 flex items-center gap-3 rounded-lg border border-ink-700/70 bg-ink-900/80 px-3 py-1.5 backdrop-blur">
        <span className="flex items-center gap-1.5 text-[11px] text-slate-400">
          <GraphIcon className="h-3.5 w-3.5 text-sky-400" />
          <span className="font-semibold text-slate-200">{nodes.length}</span> components
        </span>
        <span className="h-3 w-px bg-ink-600" />
        <span className="text-[11px] text-slate-400">
          <span className="font-semibold text-slate-200">{relations.length}</span> relations
        </span>
        {audit.findings.length > 0 && (
          <>
            <span className="h-3 w-px bg-ink-600" />
            <span className="text-[11px] text-slate-400">
              <span className="font-semibold text-rose-300">{audit.findings.length}</span> audit findings
            </span>
          </>
        )}
      </div>

      <div className="pointer-events-none absolute bottom-3 left-4 flex flex-wrap items-center gap-3 rounded-lg border border-ink-700/70 bg-ink-900/75 px-3 py-1.5 backdrop-blur">
        {(Object.keys(RELATION_META) as Array<keyof typeof RELATION_META>).map((type) => (
          <span key={type} className="flex items-center gap-1.5 text-[10px] text-slate-400">
            <svg width="22" height="6" aria-hidden>
              <line
                x1="0"
                y1="3"
                x2="22"
                y2="3"
                stroke={RELATION_META[type].color}
                strokeWidth="1.6"
                strokeDasharray={RELATION_META[type].dashed ? '4 3' : undefined}
              />
            </svg>
            {RELATION_META[type].label}
          </span>
        ))}
      </div>

      {nodes.length === 0 && (
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
          <div className="rounded-xl border border-ink-700 bg-ink-900/90 px-6 py-5 text-center">
            <p className="text-sm font-medium text-slate-200">No components to draw</p>
            <p className="mt-1 text-xs text-slate-500">
              The scan found source files but no class-like structures. Check the diagnostics above.
            </p>
          </div>
        </div>
      )}
    </div>
  );
}

const nodeTypes = {
  component: ComponentCard,
  layerHeader: LayerHeaderCard,
} satisfies NodeTypes;

function ComponentCard({ data, selected }: NodeProps<Node<ComponentNodeData, 'component'>>) {
  const component = data.component;
  const meta = LAYER_META[component.layer];
  const audit = data.audit;
  const auditMeta = audit ? SEVERITY_META[audit.severity] : null;

  return (
    <div
      className={`group relative w-[248px] rounded-xl border bg-ink-850/95 px-3 py-2.5 text-left shadow-panel transition-colors ${
        selected
          ? 'border-sky-400/90 ring-2 ring-sky-400/25'
          : 'border-ink-600/70 hover:border-ink-600'
      }`}
      style={{
        borderLeft: `3px solid ${meta.color}`,
        outline: auditMeta && !selected ? `1px solid ${auditMeta.color}88` : undefined,
        outlineOffset: -1,
      }}
      title={`${component.id}\n${component.filePath}`}
    >
      <Handle type="target" position={Position.Left} className="kodo-handle !left-[-4px]" />
      <div className="flex items-center justify-between gap-2">
        <span className="truncate text-[13px] font-semibold text-slate-100">{component.name}</span>
        <span className="flex shrink-0 items-center gap-1">
          {audit && <AlertBadge nodeAudit={audit} />}
          <span
            className="shrink-0 rounded border px-1.5 py-0.5 text-[9px] font-medium uppercase tracking-wide"
            style={{ color: meta.color, borderColor: `${meta.color}44`, backgroundColor: `${meta.color}14` }}
          >
            {KIND_LABEL[component.kind] ?? component.kind}
          </span>
        </span>
      </div>

      <div className="mt-1 flex items-center gap-1.5 text-[10px] text-slate-500">
        <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: meta.color }} />
        <span style={{ color: `${meta.color}cc` }}>{meta.label}</span>
        <span className="text-slate-600">·</span>
        <span>{component.fields.length} fields</span>
        <span className="text-slate-600">·</span>
        <span>{component.methods.length} methods</span>
      </div>

      {component.annotations.length > 0 ? (
        <div className="mt-1.5 flex items-center gap-1 overflow-hidden">
          {component.annotations.slice(0, 2).map((annotation) => (
            <span
              key={annotation}
              className="truncate rounded bg-ink-950/80 px-1.5 py-0.5 font-mono text-[9px] text-slate-400"
            >
              {annotation}
            </span>
          ))}
          {component.annotations.length > 2 && (
            <span className="text-[9px] text-slate-600">+{component.annotations.length - 2}</span>
          )}
        </div>
      ) : (
        <div className="mt-1.5 truncate font-mono text-[9px] text-slate-600">{component.filePath}</div>
      )}

      <Handle type="source" position={Position.Right} className="kodo-handle !right-[-4px]" />
    </div>
  );
}

function LayerHeaderCard({ data }: NodeProps<Node<LayerHeaderData, 'layerHeader'>>) {
  return (
    <div className="flex w-[248px] items-center gap-2 border-b pb-1.5" style={{ borderColor: `${data.color}44` }}>
      <span className="h-2 w-2 rounded-sm" style={{ backgroundColor: data.color }} />
      <span className="text-[11px] font-semibold uppercase tracking-[0.12em]" style={{ color: data.color }}>
        {data.label}
      </span>
      <span className="rounded bg-ink-800 px-1.5 text-[10px] text-slate-400">{data.count}</span>
    </div>
  );
}
