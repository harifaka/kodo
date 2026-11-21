import { useCallback, useMemo, useState } from 'react';
import { BuilderPanel } from './components/BuilderPanel';
import { CodeInspector } from './components/CodeInspector';
import { DiffPreview } from './components/DiffPreview';
import { EmptyState } from './components/EmptyState';
import { MacroGraph } from './components/MacroGraph';
import { NodeDetailsPanel } from './components/NodeDetailsPanel';
import { TopBar } from './components/TopBar';
import { UmlDiagram } from './components/UmlDiagram';
import { WarningsBar } from './components/WarningsBar';
import {
  AlertIcon,
  BuilderIcon,
  CheckIcon,
  CodeIcon,
  DiffIcon,
  GraphIcon,
  Spinner,
  UmlIcon,
} from './components/icons';
import { useDraftAudit } from './hooks/useDraftAudit';
import { useHealth } from './hooks/useHealth';
import { ApiError, api } from './lib/api';
import {
  addField,
  addNodeAnnotation,
  applyDraft,
  connectRelation,
  disconnectRelation,
  draftEditCount,
  emptyDraft,
  isDraftEmpty,
  removeField,
  removeNodeAnnotation,
  updateField,
  type Draft,
} from './lib/draft';
import { buildGraph } from './lib/layout';
import type { ScaffoldPreview } from './types/blueprint';
import type {
  AuditFinding,
  ComponentField,
  ComponentNode,
  ComponentRelation,
  RelationType,
  WorkspaceIR,
} from './types/core-ir';

type TabId = 'graph' | 'uml' | 'code' | 'builder' | 'diff';

const LAST_PATH_KEY = 'kodo:lastPath';
// Stable empty arrays: useDraftAudit keys its effect on these inputs.
const NO_NODES: ComponentNode[] = [];
const NO_RELATIONS: ComponentRelation[] = [];

export default function App() {
  const [path, setPath] = useState(() => window.localStorage.getItem(LAST_PATH_KEY) ?? '');
  const [workspace, setWorkspace] = useState<WorkspaceIR | null>(null);
  const [draft, setDraft] = useState<Draft>(emptyDraft);
  const [newRelationType, setNewRelationType] = useState<RelationType>('depends_on');
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [tab, setTab] = useState<TabId>('graph');
  const [scanning, setScanning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [lastApply, setLastApply] = useState<{
    applyId: string;
    appliedFiles: string[];
    rootPath: string;
  } | null>(null);
  const [rollingBack, setRollingBack] = useState(false);
  const [rollbackConflict, setRollbackConflict] = useState<string[] | null>(null);
  const [previewRequest, setPreviewRequest] = useState(0);
  const [scaffold, setScaffold] = useState<ScaffoldPreview | null>(null);
  const [workspaceRevision, setWorkspaceRevision] = useState(0);
  const health = useHealth();

  const draftView = useMemo(() => (workspace ? applyDraft(workspace, draft) : null), [workspace, draft]);
  const nodes = draftView?.nodes ?? NO_NODES;
  const relations = draftView?.relations ?? NO_RELATIONS;
  const draftDirty = !isDraftEmpty(draft);
  const draftCounts = draftEditCount(draft);
  const draftAudit = useDraftAudit(workspace, nodes, relations, draftDirty);

  const view = useMemo<WorkspaceIR | null>(
    () =>
      workspace && draftView
        ? { ...workspace, nodes: draftView.nodes, relations: draftView.relations, audit: draftAudit.report ?? workspace.audit }
        : null,
    [workspace, draftView, draftAudit.report],
  );

  const selected = useMemo(
    () => view?.nodes.find((node) => node.id === selectedId) ?? null,
    [view, selectedId],
  );
  const baseSelected = useMemo(
    () => workspace?.nodes.find((node) => node.id === selectedId) ?? null,
    [workspace, selectedId],
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

  const handleAddField = useCallback((nodeId: string, field: ComponentField) => {
    setDraft((current) => addField(current, nodeId, field));
  }, []);

  const handleUpdateField = useCallback(
    (nodeId: string, originalName: string, field: ComponentField) => {
      setDraft((current) => updateField(current, nodeId, originalName, field));
    },
    [],
  );

  const handleRemoveField = useCallback((nodeId: string, fieldName: string) => {
    setDraft((current) => removeField(current, nodeId, fieldName));
  }, []);

  const handleAddAnnotation = useCallback((nodeId: string, annotation: string) => {
    setDraft((current) => addNodeAnnotation(current, nodeId, annotation));
  }, []);

  const handleRemoveAnnotation = useCallback((nodeId: string, annotation: string) => {
    setDraft((current) => removeNodeAnnotation(current, nodeId, annotation));
  }, []);

  const handleResetDraft = useCallback(() => setDraft(emptyDraft()), []);

  const handlePreviewDiff = useCallback(() => {
    setPreviewRequest((value) => value + 1);
    setTab('diff');
  }, []);

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

  const scanWorkspace = useCallback(
    async (target: string, options: { resetView: boolean }): Promise<WorkspaceIR> => {
      const result = await api.scan(target);
      setWorkspace(result);
      setDraft(emptyDraft());
      setScaffold(null);
      setWorkspaceRevision((value) => value + 1);
      if (options.resetView) {
        setSelectedId(null);
        setTab('graph');
      } else {
        setSelectedId((current) =>
          current && result.nodes.some((node) => node.id === current) ? current : null,
        );
      }
      window.localStorage.setItem(LAST_PATH_KEY, target);
      health.refresh();
      return result;
    },
    [health.refresh],
  );

  const handleScan = useCallback(async () => {
    const target = path.trim();
    if (!target || scanning) {
      return;
    }

    setScanning(true);
    setError(null);
    try {
      const result = await scanWorkspace(target, { resetView: true });
      // A manual scan of a different folder makes the previous rollback banner meaningless.
      if (lastApply && lastApply.rootPath !== result.rootPath) {
        setLastApply(null);
        setRollbackConflict(null);
        setNotice(null);
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setScanning(false);
    }
  }, [path, scanning, scanWorkspace, lastApply]);

  const handleApplied = useCallback(
    async (applyId: string, appliedFiles: string[]) => {
      const target = workspace?.rootPath ?? path.trim();
      const fromScaffold = scaffold !== null;
      setLastApply({ applyId, appliedFiles, rootPath: target });
      setRollbackConflict(null);
      setNotice(null);
      setError(null);
      setScaffold(null);
      if (!target) {
        return;
      }
      try {
        await scanWorkspace(target, { resetView: false });
        if (fromScaffold) {
          setTab('graph');
        }
      } catch (reason) {
        setError(
          `Applied ${appliedFiles.length} file(s) to disk, but the automatic re-scan failed: ${
            reason instanceof Error ? reason.message : String(reason)
          }`,
        );
      }
    },
    [path, scaffold, scanWorkspace, workspace],
  );

  const handleRollback = useCallback(
    async (force: boolean) => {
      const target = workspace?.rootPath ?? path.trim();
      if (!lastApply || rollingBack) {
        return;
      }

      setRollingBack(true);
      setRollbackConflict(null);
      setError(null);
      try {
        const result = await api.rollback(lastApply.applyId, force);
        setLastApply(null);
        const deleted = result.deletedFiles?.length ?? 0;
        const restored = result.restoredFiles.length;
        setNotice(
          deleted > 0
            ? `Rolled back ${deleted + restored} file(s): ${deleted} generated file(s) deleted, ${restored} restored, and the workspace was re-scanned.`
            : `Rolled back ${restored} file(s); the original bytes are back on disk and the workspace was re-scanned.`,
        );
        if (target) {
          await scanWorkspace(target, { resetView: false });
        }
      } catch (reason) {
        if (reason instanceof ApiError && reason.code === 'STALE_FILE') {
          const paths = Array.isArray(reason.detail?.paths)
            ? (reason.detail?.paths as unknown[]).map(String)
            : [];
          setRollbackConflict(paths.length > 0 ? paths : ['(changed on disk)']);
        } else {
          setError(reason instanceof Error ? reason.message : String(reason));
        }
      } finally {
        setRollingBack(false);
      }
    },
    [lastApply, path, rollingBack, scanWorkspace, workspace],
  );

  const handleAppliedChange = useCallback(
    (applyId: string, appliedFiles: string[]) => {
      void handleApplied(applyId, appliedFiles);
    },
    [handleApplied],
  );

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

      {notice && (
        <div className="flex items-start gap-2 border-b border-emerald-500/25 bg-emerald-500/[0.07] px-4 py-1.5">
          <CheckIcon className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-400" />
          <p className="text-[11px] leading-relaxed text-emerald-200">{notice}</p>
          <button
            type="button"
            onClick={() => setNotice(null)}
            className="ml-auto shrink-0 rounded px-1.5 text-[10px] text-emerald-300/70 transition hover:text-emerald-200"
          >
            dismiss
          </button>
        </div>
      )}

      {lastApply && (
        <div className="flex flex-wrap items-center gap-2 border-b border-emerald-500/25 bg-emerald-500/[0.06] px-4 py-1.5">
          <CheckIcon className="h-3.5 w-3.5 shrink-0 text-emerald-400" />
          <p className="text-[11px] leading-relaxed text-emerald-200">
            Applied {lastApply.appliedFiles.length} file
            {lastApply.appliedFiles.length === 1 ? '' : 's'} to disk · workspace re-scanned
          </p>
          {rollbackConflict && (
            <span className="text-[10px] leading-relaxed text-amber-300">
              Rollback blocked — {rollbackConflict.join(', ')} changed since the apply.
            </span>
          )}
          <div className="ml-auto flex shrink-0 items-center gap-2">
            {rollbackConflict ? (
              <button
                type="button"
                onClick={() => void handleRollback(true)}
                disabled={rollingBack}
                className="flex items-center gap-1 rounded-md border border-amber-400/40 px-2 py-0.5 text-[10px] text-amber-200 transition enabled:hover:bg-amber-400/10 disabled:opacity-50"
              >
                {rollingBack ? <Spinner className="h-3 w-3" /> : null}
                Force rollback
              </button>
            ) : (
              <button
                type="button"
                onClick={() => void handleRollback(false)}
                disabled={rollingBack}
                className="flex items-center gap-1 rounded-md border border-emerald-400/40 px-2 py-0.5 text-[10px] text-emerald-200 transition enabled:hover:bg-emerald-400/10 disabled:opacity-50"
              >
                {rollingBack ? <Spinner className="h-3 w-3" /> : null}
                {rollingBack ? 'Rolling back…' : 'Undo / Rollback Last Apply'}
              </button>
            )}
            <button
              type="button"
              onClick={() => {
                setLastApply(null);
                setRollbackConflict(null);
              }}
              className="rounded px-1.5 text-[10px] text-emerald-300/70 transition hover:text-emerald-200"
            >
              dismiss
            </button>
          </div>
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
                draft={draftDirty ? draftCounts : null}
                scaffoldCount={scaffold ? scaffold.response.patches.length : null}
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
                    onPreviewDiff={handlePreviewDiff}
                    previewBusy={false}
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
                {tab === 'builder' && (
                  <BuilderPanel
                    key={`${view.rootPath}-builder`}
                    rootPath={view.rootPath}
                    revision={workspaceRevision}
                    onPreviewReady={(preview) => {
                      setScaffold(preview);
                      setTab('diff');
                    }}
                  />
                )}
                {tab === 'diff' && workspace && (
                  <DiffPreview
                    workspace={workspace}
                    draft={draft}
                    requestId={previewRequest}
                    scaffold={scaffold}
                    onScaffoldDismiss={() => setScaffold(null)}
                    onApplied={handleAppliedChange}
                  />
                )}
              </div>
            </>
          ) : (
            <EmptyState healthStatus={health.status} scanning={scanning} />
          )}
        </main>

        {view && (
          <NodeDetailsPanel
            workspace={view}
            baseNode={baseSelected}
            selected={selected}
            draft={draft}
            onSelect={handleSelect}
            onSelectNodeId={handleSelectNodeId}
            onOpenInInspector={openInspector}
            onOpenFinding={handleOpenFinding}
            onDisconnectRelation={handleDisconnect}
            onAddField={handleAddField}
            onUpdateField={handleUpdateField}
            onRemoveField={handleRemoveField}
            onAddAnnotation={handleAddAnnotation}
            onRemoveAnnotation={handleRemoveAnnotation}
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
  scaffoldCount,
}: {
  tab: TabId;
  onChange: (tab: TabId) => void;
  workspace: WorkspaceIR;
  hasSelection: boolean;
  draft: ReturnType<typeof draftEditCount> | null;
  scaffoldCount: number | null;
}) {
  const tabs: Array<{ id: TabId; label: string; icon: typeof GraphIcon; badge?: string }> = [
    { id: 'graph', label: 'Macro Graph', icon: GraphIcon, badge: String(workspace.nodes.length) },
    { id: 'uml', label: 'UML Diagram', icon: UmlIcon },
    { id: 'code', label: 'Code Inspector', icon: CodeIcon, badge: hasSelection ? '●' : undefined },
    {
      id: 'builder',
      label: 'Builder',
      icon: BuilderIcon,
      badge: scaffoldCount ? String(scaffoldCount) : undefined,
    },
    {
      id: 'diff',
      label: 'Diff Preview',
      icon: DiffIcon,
      badge:
        draft && draft.total > 0
          ? String(draft.total)
          : scaffoldCount
            ? String(scaffoldCount)
            : undefined,
    },
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
              title="Uncommitted draft edits — kept in the browser only"
              className="shrink-0 rounded border border-emerald-400/30 bg-emerald-400/10 px-1.5 py-0.5 font-mono text-[9.5px] text-emerald-300"
            >
              draft {draft.total} · rel {draft.relations} · fields {draft.fields} · ann {draft.annotations}
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
