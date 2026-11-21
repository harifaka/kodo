import { useCallback, useMemo, useState } from 'react';
import { CodeInspector } from './components/CodeInspector';
import { EmptyState } from './components/EmptyState';
import { MacroGraph } from './components/MacroGraph';
import { NodeDetailsPanel } from './components/NodeDetailsPanel';
import { TopBar } from './components/TopBar';
import { UmlDiagram } from './components/UmlDiagram';
import { WarningsBar } from './components/WarningsBar';
import { AlertIcon, CodeIcon, GraphIcon, UmlIcon } from './components/icons';
import { useDraftAudit } from './hooks/useDraftAudit';
import { useHealth } from './hooks/useHealth';
import { api } from './lib/api';
import { applyDraft, connectRelation, disconnectRelation, emptyDraft, isDraftEmpty } from './lib/draft';
import { buildGraph } from './lib/layout';
import type {
  AuditFinding,
  ComponentNode,
  ComponentRelation,
  RelationType,
  WorkspaceIR,
} from './types/core-ir';

type TabId = 'graph' | 'uml' | 'code';

const LAST_PATH_KEY = 'kodo:lastPath';

export default function App() {
  const [path, setPath] = useState(() => window.localStorage.getItem(LAST_PATH_KEY) ?? '');
  const [workspace, setWorkspace] = useState<WorkspaceIR | null>(null);
  const [draft, setDraft] = useState(emptyDraft);
  const [newRelationType, setNewRelationType] = useState<RelationType>('depends_on');
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [tab, setTab] = useState<TabId>('graph');
  const [scanning, setScanning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const health = useHealth();

  const relations = useMemo(
    () => (workspace ? applyDraft(workspace.relations, draft) : []),
    [workspace, draft],
  );
  const draftDirty = !isDraftEmpty(draft);
  const draftAudit = useDraftAudit(workspace, relations, draftDirty);

  const view = useMemo<WorkspaceIR | null>(
    () =>
      workspace
        ? { ...workspace, relations, audit: draftAudit.report ?? workspace.audit }
        : null,
    [workspace, relations, draftAudit.report],
  );

  const selected = useMemo(
    () => view?.nodes.find((node) => node.id === selectedId) ?? null,
    [view, selectedId],
  );

  const graph = useMemo(
    () => (view ? buildGraph(view.nodes, view.relations) : { nodes: [], edges: [] }),
    [view],
  );

  const handleSelect = useCallback((node: ComponentNode | null) => {
    setSelectedId(node?.id ?? null);
  }, []);

  const handleSelectNodeId = useCallback((nodeId: string) => {
    setSelectedId(nodeId);
  }, []);

  const handleConnect = useCallback(
    (sourceId: string, targetId: string, type: RelationType) => {
      const base = workspace?.relations ?? [];
      setDraft((current) => connectRelation(current, base, { sourceId, targetId, type }));
    },
    [workspace],
  );

  const handleDisconnect = useCallback(
    (relation: ComponentRelation) => {
      const base = workspace?.relations ?? [];
      setDraft((current) => disconnectRelation(current, base, relation));
    },
    [workspace],
  );

  const handleResetDraft = useCallback(() => setDraft(emptyDraft()), []);

  const handleOpenFinding = useCallback(
    (finding: AuditFinding) => {
      const nodes = view?.nodes ?? [];
      const target =
        nodes.find((node) => node.filePath === finding.filePath) ??
        nodes.find((node) => node.id === finding.nodeIds[0]);
      if (target) {
        setSelectedId(target.id);
      }
      setTab('code');
    },
    [view],
  );

  const handleScan = useCallback(async () => {
    const target = path.trim();
    if (!target || scanning) {
      return;
    }

    setScanning(true);
    setError(null);
    try {
      const result = await api.scan(target);
      setWorkspace(result);
      setDraft(emptyDraft());
      setSelectedId(null);
      setTab('graph');
      window.localStorage.setItem(LAST_PATH_KEY, target);
      health.refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setScanning(false);
    }
  }, [path, scanning, health.refresh]);

  const openInspector = useCallback(() => setTab('code'), []);

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-ink-950 text-slate-200">
      <TopBar
        path={path}
        onPathChange={setPath}
        onScan={() => void handleScan()}
        scanning={scanning}
        health={health}
        workspace={view}
      />

      {error && (
        <div className="flex items-start gap-2 border-b border-rose-500/25 bg-rose-500/[0.07] px-4 py-2">
          <AlertIcon className="mt-0.5 h-3.5 w-3.5 shrink-0 text-rose-400" />
          <p className="text-[11px] leading-relaxed text-rose-200">{error}</p>
          <button
            type="button"
            onClick={() => setError(null)}
            className="ml-auto shrink-0 rounded px-1.5 text-[10px] text-rose-300/70 transition hover:bg-rose-500/10 hover:text-rose-200"
          >
            dismiss
          </button>
        </div>
      )}

      <div className="flex min-h-0 flex-1">
        <main className="flex min-w-0 flex-1 flex-col">
          {view ? (
            <>
              <TabBar
                tab={tab}
                onChange={setTab}
                workspace={view}
                hasSelection={selected !== null}
                draft={draftDirty ? { added: draft.added.length, removed: draft.removed.length } : null}
              />
              <WarningsBar warnings={view.warnings} />
              <div className="min-h-0 flex-1">
                {tab === 'graph' && (
                  <MacroGraph
                    key={view.rootPath}
                    nodes={view.nodes}
                    relations={view.relations}
                    flowNodes={graph.nodes}
                    flowEdges={graph.edges}
                    audit={view.audit}
                    selectedId={selectedId}
                    onSelect={handleSelect}
                    draft={draft}
                    auditPending={draftAudit.pending}
                    auditError={draftAudit.error}
                    newRelationType={newRelationType}
                    onNewRelationTypeChange={setNewRelationType}
                    onConnect={handleConnect}
                    onDisconnect={handleDisconnect}
                    onResetDraft={handleResetDraft}
                  />
                )}
                {tab === 'uml' && (
                  <UmlDiagram
                    key={`${view.rootPath}-uml`}
                    diagram={view.mermaidClassDiagram}
                    componentCount={view.nodes.length}
                    draftPending={draftDirty}
                  />
                )}
                {tab === 'code' && <CodeInspector rootPath={view.rootPath} node={selected} />}
              </div>
            </>
          ) : (
            <EmptyState healthStatus={health.status} scanning={scanning} />
          )}
        </main>

        {view && (
          <NodeDetailsPanel
            workspace={view}
            selected={selected}
            onSelect={handleSelect}
            onSelectNodeId={handleSelectNodeId}
            onOpenInInspector={openInspector}
            onOpenFinding={handleOpenFinding}
            onDisconnectRelation={handleDisconnect}
          />
        )}
      </div>
    </div>
  );
}

function TabBar({
  tab,
  onChange,
  workspace,
  hasSelection,
  draft,
}: {
  tab: TabId;
  onChange: (tab: TabId) => void;
  workspace: WorkspaceIR;
  hasSelection: boolean;
  draft: { added: number; removed: number } | null;
}) {
  const tabs: Array<{ id: TabId; label: string; icon: typeof GraphIcon; badge?: string }> = [
    { id: 'graph', label: 'Macro Graph', icon: GraphIcon, badge: String(workspace.nodes.length) },
    { id: 'uml', label: 'UML Diagram', icon: UmlIcon },
    { id: 'code', label: 'Code Inspector', icon: CodeIcon, badge: hasSelection ? '●' : undefined },
  ];

  return (
    <div className="flex items-center gap-1 border-b border-ink-700/70 bg-ink-900/50 px-2">
      <nav className="flex items-center gap-0.5">
        {tabs.map((entry) => {
          const active = tab === entry.id;
          return (
            <button
              key={entry.id}
              type="button"
              onClick={() => onChange(entry.id)}
              className={`relative flex items-center gap-1.5 px-3 py-2.5 text-[11.5px] font-medium transition ${
                active ? 'text-white' : 'text-slate-500 hover:text-slate-300'
              }`}
            >
              <entry.icon className="h-3.5 w-3.5" />
              {entry.label}
              {entry.badge && (
                <span
                  className={`rounded px-1 font-mono text-[9px] ${
                    entry.badge === '●'
                      ? 'text-sky-400'
                      : active
                        ? 'bg-sky-500/20 text-sky-300'
                        : 'bg-ink-700 text-slate-400'
                  }`}
                >
                  {entry.badge}
                </span>
              )}
              {active && <span className="absolute inset-x-2 -bottom-px h-0.5 rounded-full bg-sky-400" />}
            </button>
          );
        })}
      </nav>

      <div className="ml-auto flex min-w-0 items-center gap-2 px-2">
        {draft && (
          <>
            <span
              title="Uncommitted macro edits — kept in the browser only"
              className="shrink-0 rounded border border-emerald-400/30 bg-emerald-400/10 px-1.5 py-0.5 font-mono text-[9.5px] text-emerald-300"
            >
              draft +{draft.added} / −{draft.removed}
            </span>
            <span className="h-3 w-px bg-ink-700" />
          </>
        )}
        <span className="truncate font-mono text-[10px] text-slate-600" title={workspace.rootPath}>
          {workspace.rootPath}
        </span>
      </div>
    </div>
  );
}
