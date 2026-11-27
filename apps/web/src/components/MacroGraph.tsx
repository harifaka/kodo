import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
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
  getViewportForBounds,
  useNodesInitialized,
  useReactFlow,
  type Connection,
  type Edge,
  type Node,
  type NodeProps,
  type NodeTypes,
  type XYPosition,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { toPng, toSvg } from 'html-to-image';
import {
  edgeTouchesNode,
  NODE_WIDTH,
  type ComponentNodeData,
  type GraphDirection,
  type LayerBandData,
  type RelationEdgeData,
} from '../lib/layout';
import { KIND_LABEL, LAYER_META, RELATION_META } from '../lib/layers';
import { SEVERITY_META, auditedEdgeKeys, edgeKey, nodeAuditIndex } from '../lib/audit';
import { keyOf, relationKey, type Draft } from '../lib/draft';
import {
  DiagramExportError,
  EXPORT_BACKGROUND,
  dataUrlToBlob,
  downloadBlob,
  slugifyFilename,
  type ExportTheme,
} from '../lib/diagramExport';
import type { AuditReport, ComponentNode, ComponentRelation, RelationType } from '../types/core-ir';
import { AlertIcon, DownloadIcon, FitIcon, GraphIcon } from './icons';
import { AlertBadge } from './AuditPanel';
import { DraftToolbar } from './DraftToolbar';
import { edgeTypes } from './RelationEdge';

const DRAFT_EDGE_COLOR = '#34d399';

interface MacroGraphProps {
  nodes: ComponentNode[];
  relations: ComponentRelation[];
  flowNodes: Node[];
  flowEdges: Edge[];
  audit: AuditReport;
  selectedId: string | null;
  onSelect: (node: ComponentNode | null) => void;
  draft: Draft;
  auditPending: boolean;
  auditError: string | null;
  newRelationType: RelationType;
  onNewRelationTypeChange: (type: RelationType) => void;
  onConnect: (sourceId: string, targetId: string, type: RelationType) => void;
  onDisconnect: (relation: ComponentRelation) => void;
  onResetDraft: () => void;
  onPreviewDiff: () => void;
  previewBusy: boolean;
  /** Smoothly centers/fits the viewport on a node picked from the quick search (Phase 11). */
  centerRequest?: { id: string; token: number } | null;
  /** Swimlane orientation, owned by the app so the layout survives tab switches (Phase 14). */
  direction: GraphDirection;
  onDirectionChange: (direction: GraphDirection) => void;
  workspaceName: string;
  /** e.g. `1hop` / `issues` / `filtered` — appended to exported file names. */
  filterHint?: string | null;
}

export function MacroGraph({
  nodes,
  relations,
  flowNodes,
  flowEdges,
  audit,
  selectedId,
  onSelect,
  draft,
  auditPending,
  auditError,
  newRelationType,
  onNewRelationTypeChange,
  onConnect,
  onDisconnect,
  onResetDraft,
  onPreviewDiff,
  previewBusy,
  centerRequest = null,
  direction,
  onDirectionChange,
  workspaceName,
  filterHint = null,
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
        draft={draft}
        auditPending={auditPending}
        auditError={auditError}
        newRelationType={newRelationType}
        onNewRelationTypeChange={onNewRelationTypeChange}
        onConnect={onConnect}
        onDisconnect={onDisconnect}
        onResetDraft={onResetDraft}
        onPreviewDiff={onPreviewDiff}
        previewBusy={previewBusy}
        centerRequest={centerRequest}
        direction={direction}
        onDirectionChange={onDirectionChange}
        workspaceName={workspaceName}
        filterHint={filterHint}
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
  draft,
  auditPending,
  auditError,
  newRelationType,
  onNewRelationTypeChange,
  onConnect,
  onDisconnect,
  onResetDraft,
  onPreviewDiff,
  previewBusy,
  centerRequest = null,
  direction,
  onDirectionChange,
  workspaceName,
  filterHint = null,
}: MacroGraphProps) {
  const { fitView, setCenter, getNodes, getNodesBounds } = useReactFlow();
  const initialized = useNodesInitialized();

  const canvasRef = useRef<HTMLDivElement | null>(null);
  const [positionOverrides, setPositionOverrides] = useState<Record<string, XYPosition>>({});
  const [arrangeToken, setArrangeToken] = useState(0);
  const [exportTheme, setExportTheme] = useState<ExportTheme>('dark');
  const [exporting, setExporting] = useState<'png' | 'svg' | null>(null);
  const [exportMessage, setExportMessage] = useState<{ kind: 'ok' | 'error'; text: string } | null>(null);

  const visibleSignature = useMemo(
    () => `${direction}|${nodes.map((node) => node.id).join('|')}`,
    [nodes, direction],
  );

  // A new layout (filter, direction, workspace) invalidates manual drag positions.
  const layoutSignature = useMemo(
    () => `${direction}|${flowNodes.map((node) => `${node.id}@${node.position.x},${node.position.y}`).join('|')}`,
    [flowNodes, direction],
  );
  useEffect(() => {
    setPositionOverrides({});
  }, [layoutSignature]);

  useEffect(() => {
    if (!initialized) {
      return;
    }
    // Fit only once the custom nodes have measured themselves, otherwise edges/labels are clipped.
    // Also re-fits when a layer/stack/issues/focus filter or the layout direction changes.
    const frame = window.requestAnimationFrame(() => {
      void fitView({ padding: 0.12, maxZoom: 1.05, minZoom: 0.15, duration: 180 });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [initialized, fitView, visibleSignature]);

  useEffect(() => {
    if (arrangeToken === 0) {
      return;
    }
    const frame = window.requestAnimationFrame(() => {
      void fitView({ padding: 0.14, maxZoom: 1.05, minZoom: 0.15, duration: 380 });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [arrangeToken, fitView]);

  useEffect(() => {
    if (!exportMessage) {
      return;
    }
    const timer = window.setTimeout(() => setExportMessage(null), 7_000);
    return () => window.clearTimeout(timer);
  }, [exportMessage]);

  useEffect(() => {
    if (!centerRequest) {
      return;
    }
    const target = flowNodes.find((node) => node.id === centerRequest.id);
    if (!target) {
      return;
    }
    const width = typeof target.width === 'number' ? target.width : NODE_WIDTH;
    const height = typeof target.height === 'number' ? target.height : 96;
    const frame = window.requestAnimationFrame(() => {
      void setCenter(target.position.x + width / 2, target.position.y + height / 2, {
        zoom: 1,
        duration: 420,
      });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [centerRequest, flowNodes, setCenter]);

  const auditByNode = useMemo(() => nodeAuditIndex(audit), [audit]);
  const flaggedEdges = useMemo(() => auditedEdgeKeys(audit), [audit]);
  const draftEdgeKeys = useMemo(() => new Set(draft.relations.added.map(keyOf)), [draft.relations.added]);

  const decoratedNodes = useMemo(
    () =>
      flowNodes.map((node) => ({
        ...node,
        position: positionOverrides[node.id] ?? node.position,
        selected: node.id === selectedId,
        data: node.type === 'component' ? { ...node.data, audit: auditByNode.get(node.id) } : node.data,
      })),
    [flowNodes, selectedId, auditByNode, positionOverrides],
  );

  const decoratedEdges = useMemo(
    () =>
      flowEdges.map((edge) => {
        const relationType = relationTypeOf(edge);
        const isDraft = draftEdgeKeys.has(relationKey(edge.source, edge.target, relationType));
        const flagged = flaggedEdges.has(edgeKey(edge.source, edge.target));

        let base = edge;
        if (isDraft) {
          base = {
            ...edge,
            style: {
              ...edge.style,
              stroke: DRAFT_EDGE_COLOR,
              strokeWidth: 2,
              strokeDasharray: '6 4',
            },
            markerEnd: {
              type: MarkerType.ArrowClosed,
              color: DRAFT_EDGE_COLOR,
              width: 18,
              height: 18,
            },
          };
        } else if (flagged) {
          base = {
            ...edge,
            style: { ...edge.style, stroke: SEVERITY_META.error.color, strokeWidth: 2.2 },
            markerEnd: {
              type: MarkerType.ArrowClosed,
              color: SEVERITY_META.error.color,
              width: 18,
              height: 18,
            },
          };
        }

        if (selectedId === null) {
          return base;
        }

        return edgeTouchesNode(base, selectedId)
          ? {
              ...base,
              style: { ...base.style, opacity: 1, strokeWidth: flagged || isDraft ? 2.6 : 2 },
              zIndex: 5,
            }
          : { ...base, style: { ...base.style, opacity: 0.16 } };
      }),
    [flowEdges, selectedId, flaggedEdges, draftEdgeKeys],
  );

  const interactiveEdges = useMemo(
    () =>
      decoratedEdges.map((edge) => ({
        ...edge,
        data: {
          ...edge.data,
          onCut: () =>
            onDisconnect({
              sourceId: edge.source,
              targetId: edge.target,
              type: relationTypeOf(edge),
            }),
        } as RelationEdgeData,
      })),
    [decoratedEdges, onDisconnect],
  );

  const canConnect = useCallback(
    (connection: Connection | Edge) => {
      if (!connection.source || !connection.target || connection.source === connection.target) {
        return false;
      }
      const candidate = relationKey(connection.source, connection.target, newRelationType);
      return !relations.some((relation) => keyOf(relation) === candidate);
    },
    [relations, newRelationType],
  );

  const handleEdgesDelete = useCallback(
    (removed: Edge[]) => {
      for (const edge of removed) {
        onDisconnect({ sourceId: edge.source, targetId: edge.target, type: relationTypeOf(edge) });
      }
    },
    [onDisconnect],
  );

  const handleAutoArrange = useCallback(() => {
    setPositionOverrides({});
    setArrangeToken((token) => token + 1);
  }, []);

  const handleExport = useCallback(
    async (format: 'png' | 'svg') => {
      if (exporting) {
        return;
      }
      setExporting(format);
      setExportMessage(null);
      try {
        const viewport = canvasRef.current?.querySelector<HTMLElement>('.react-flow__viewport');
        if (!viewport) {
          throw new DiagramExportError('The graph is not ready to export yet.');
        }

        // Capture every visible component (not the current pan/zoom window); swimlane bands are part
        // of the diagram, while minimap/toolbar/controls are overlay UI outside `.react-flow__viewport`.
        const visible = getNodes().filter((node) => node.type === 'component');
        if (visible.length === 0) {
          throw new DiagramExportError('There is nothing to export — no visible components.');
        }
        const framed = getNodes().filter(
          (node) => node.type === 'component' || node.type === 'layerBand',
        );

        const bounds = getNodesBounds(framed);
        const padding = 48;
        const padded = {
          x: bounds.x - padding,
          y: bounds.y - padding,
          width: bounds.width + padding * 2,
          height: bounds.height + padding * 2,
        };
        const imageWidth = Math.max(320, Math.min(4096, Math.ceil(padded.width)));
        const imageHeight = Math.max(240, Math.min(4096, Math.ceil(padded.height)));
        const transform = getViewportForBounds(padded, imageWidth, imageHeight, 0.02, 2, 0);

        const options = {
          backgroundColor: EXPORT_BACKGROUND[exportTheme],
          width: imageWidth,
          height: imageHeight,
          pixelRatio: 2,
          style: {
            width: `${imageWidth}px`,
            height: `${imageHeight}px`,
            transform: `translate(${transform.x}px, ${transform.y}px) scale(${transform.zoom})`,
          },
        };

        const slug = slugifyFilename(workspaceName);
        const hint = filterHint ? `-${slugifyFilename(filterHint, 'filtered')}` : '';

        if (format === 'png') {
          const dataUrl = await toPng(viewport, options);
          downloadBlob(await dataUrlToBlob(dataUrl), `${slug}-graph${hint}.png`);
          setExportMessage({ kind: 'ok', text: 'PNG exported at 2x.' });
        } else {
          const dataUrl = await toSvg(viewport, options);
          downloadBlob(await dataUrlToBlob(dataUrl), `${slug}-graph${hint}.svg`);
          setExportMessage({ kind: 'ok', text: 'SVG exported.' });
        }
      } catch (reason) {
        const text =
          reason instanceof DiagramExportError
            ? reason.message
            : reason instanceof Error
              ? reason.message
              : 'The graph could not be exported.';
        setExportMessage({ kind: 'error', text });
      } finally {
        setExporting(null);
      }
    },
    [exporting, exportTheme, filterHint, getNodes, getNodesBounds, workspaceName],
  );

  return (
    <div ref={canvasRef} className="relative h-full w-full bg-ink-950">
      <ReactFlow
        nodes={decoratedNodes}
        edges={interactiveEdges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
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
        onNodeDragStop={(_event, node) => {
          if (node.type === 'component') {
            setPositionOverrides((current) => ({ ...current, [node.id]: node.position }));
          }
        }}
        onPaneClick={() => onSelect(null)}
        onConnect={(connection) => {
          if (connection.source && connection.target) {
            onConnect(connection.source, connection.target, newRelationType);
          }
        }}
        onEdgesDelete={handleEdgesDelete}
        isValidConnection={canConnect}
        nodesConnectable
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

      <div className="absolute left-4 top-[46px] z-10 flex items-center gap-1 rounded-lg border border-ink-700/80 bg-ink-900/90 p-1 backdrop-blur">
        <button
          type="button"
          onClick={handleAutoArrange}
          title="Re-apply the layered swimlane layout and fit the view"
          className="inline-flex items-center gap-1.5 rounded-md border border-ink-600/80 px-2 py-1 text-[10.5px] text-slate-300 transition hover:border-sky-400/60 hover:text-sky-200"
        >
          <FitIcon className="h-3.5 w-3.5" />
          Auto-Arrange
        </button>
        <span className="mx-0.5 h-4 w-px bg-ink-700" />
        <Segmented
          value={direction}
          options={[
            { id: 'TB', label: 'TB', title: 'Top-to-bottom swimlanes' },
            { id: 'LR', label: 'LR', title: 'Left-to-right columns' },
          ]}
          onChange={(next) => onDirectionChange(next as GraphDirection)}
        />
        <span className="mx-0.5 h-4 w-px bg-ink-700" />
        <ExportMenu
          theme={exportTheme}
          onThemeChange={setExportTheme}
          busy={exporting}
          onExport={(format) => void handleExport(format)}
        />
      </div>

      <DraftToolbar
        draft={draft}
        relationType={newRelationType}
        onRelationTypeChange={onNewRelationTypeChange}
        onReset={onResetDraft}
        onPreviewDiff={onPreviewDiff}
        previewBusy={previewBusy}
        pending={auditPending}
        error={auditError}
      />

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

      {exportMessage && (
        <div
          className={`absolute bottom-16 left-1/2 z-20 -translate-x-1/2 rounded-lg border px-3 py-2 text-[11px] shadow-panel backdrop-blur ${
            exportMessage.kind === 'error'
              ? 'border-rose-500/40 bg-rose-950/80 text-rose-100'
              : 'border-emerald-400/40 bg-emerald-950/80 text-emerald-100'
          }`}
        >
          <span className="flex items-center gap-1.5">
            {exportMessage.kind === 'error' ? (
              <AlertIcon className="h-3.5 w-3.5" />
            ) : (
              <DownloadIcon className="h-3.5 w-3.5" />
            )}
            {exportMessage.text}
          </span>
        </div>
      )}

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

interface SegmentedOption {
  id: string;
  label: string;
  title?: string;
}

function Segmented({
  value,
  options,
  onChange,
}: {
  value: string;
  options: SegmentedOption[];
  onChange: (next: string) => void;
}) {
  return (
    <div className="flex items-center overflow-hidden rounded-md border border-ink-600/80">
      {options.map((option) => (
        <button
          key={option.id}
          type="button"
          title={option.title ?? option.label}
          onClick={() => onChange(option.id)}
          className={`px-2 py-1 text-[10.5px] transition ${
            value === option.id
              ? 'bg-ink-700 text-slate-100'
              : 'text-slate-500 hover:bg-ink-800 hover:text-slate-300'
          }`}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

function ExportMenu({
  theme,
  onThemeChange,
  busy,
  onExport,
}: {
  theme: ExportTheme;
  onThemeChange: (theme: ExportTheme) => void;
  busy: 'png' | 'svg' | null;
  onExport: (format: 'png' | 'svg') => void;
}) {
  const [open, setOpen] = useState(false);

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className={`inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-[10.5px] transition ${
          open
            ? 'border-sky-500/60 bg-sky-500/10 text-sky-200'
            : 'border-ink-600/80 text-slate-300 hover:border-sky-400/60 hover:text-sky-200'
        }`}
      >
        <DownloadIcon className="h-3.5 w-3.5" />
        Export
        {busy && <span className="font-mono text-[9px] text-sky-300/80">{busy}…</span>}
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <div className="absolute left-0 top-full z-20 mt-1.5 w-56 rounded-lg border border-ink-700 bg-ink-900/98 p-2 shadow-panel">
            <p className="mb-1 text-[9px] uppercase tracking-[0.16em] text-slate-500">Background</p>
            <Segmented
              value={theme}
              options={[
                { id: 'dark', label: 'Dark', title: 'Dark background' },
                { id: 'light', label: 'Light', title: 'White background for PRs and wikis' },
              ]}
              onChange={(next) => onThemeChange(next as ExportTheme)}
            />
            <div className="mt-2 flex flex-col gap-1">
              <button
                type="button"
                disabled={busy !== null}
                onClick={() => {
                  setOpen(false);
                  onExport('png');
                }}
                className="rounded-md border border-ink-600 px-2 py-1.5 text-left text-[11px] text-slate-300 transition hover:border-sky-400/60 hover:text-sky-200 disabled:opacity-50"
              >
                Export PNG (2x)
              </button>
              <button
                type="button"
                disabled={busy !== null}
                onClick={() => {
                  setOpen(false);
                  onExport('svg');
                }}
                className="rounded-md border border-ink-600 px-2 py-1.5 text-left text-[11px] text-slate-300 transition hover:border-sky-400/60 hover:text-sky-200 disabled:opacity-50"
              >
                Export SVG
              </button>
            </div>
            <p className="mt-1.5 text-[9px] leading-relaxed text-slate-500">
              Captures every visible component at its full bounding box. Nothing is written to disk.
            </p>
          </div>
        </>
      )}
    </div>
  );
}

function relationTypeOf(edge: Edge): RelationType {
  const value = edge.data?.relation;
  return typeof value === 'string' ? (value as RelationType) : 'depends_on';
}

const nodeTypes = {
  component: ComponentCard,
  layerBand: LayerBandCard,
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

function LayerBandCard({ data }: NodeProps<Node<LayerBandData, 'layerBand'>>) {
  return (
    <div
      className="h-full w-full rounded-2xl border border-dashed"
      style={{ borderColor: `${data.color}33`, backgroundColor: `${data.color}0a` }}
    >
      <div className="flex items-center gap-2 px-3 py-2">
        <span className="h-2 w-2 rounded-sm" style={{ backgroundColor: data.color }} />
        <span className="text-[11px] font-semibold uppercase tracking-[0.12em]" style={{ color: data.color }}>
          {data.label}
        </span>
        <span className="rounded bg-ink-950/60 px-1.5 text-[10px] text-slate-400">{data.count}</span>
      </div>
    </div>
  );
}