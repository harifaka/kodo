import { useCallback, useEffect, useMemo, useState } from 'react';
import { AiSettingsModal } from './components/AiSettingsModal';
import { BuilderPanel } from './components/BuilderPanel';
import { DecisionsPanel } from './components/DecisionsPanel';
import { CodeInspector } from './components/CodeInspector';
import { DeployStudio } from './components/DeployStudio';
import { DiffPreview } from './components/DiffPreview';
import { EmptyState } from './components/EmptyState';
import { FolderBrowserModal } from './components/FolderBrowserModal';
import { GraphFilterBar } from './components/GraphFilterBar';
import { LoginScreen } from './components/LoginScreen';
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
  DecisionIcon,
  DeployIcon,
  DiffIcon,
  GraphIcon,
  Spinner,
  UmlIcon,
} from './components/icons';
import { useAuditTriage } from './hooks/useAuditTriage';
import { useDraftAudit } from './hooks/useDraftAudit';
import { useAiSettings } from './hooks/useAiSettings';
import { useGraphFilter } from './hooks/useGraphFilter';
import { useHealth } from './hooks/useHealth';
import { useSystemOneSettings } from './hooks/useSystemOneSettings';
import { ApiError, api } from './lib/api';
import { applyGraphFilter, searchComponents } from './lib/graphFilter';
import { isAiConfigured, providerLabel, toLlmOverride } from './lib/aiSettings';
import { systemOneLabel } from './lib/decisionSettings';
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
import type { AuthMeResponse, WorkspaceSummary } from './types/account';
import type { PlanPreview } from './types/ai';
import type {
  AuditFinding,
  ComponentField,
  ComponentNode,
  ComponentRelation,
  RelationType,
  WorkspaceIR,
} from './types/core-ir';

type TabId = 'graph' | 'uml' | 'code' | 'builder' | 'deploy' | 'diff' | 'decisions';

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
  const [plan, setPlan] = useState<PlanPreview | null>(null);
  const [workspaceRevision, setWorkspaceRevision] = useState(0);
  const [aiModalOpen, setAiModalOpen] = useState(false);
  const [browseOpen, setBrowseOpen] = useState(false);
  const [centerRequest, setCenterRequest] = useState<{ id: string; token: number } | null>(null);
  const [subsetDiagram, setSubsetDiagram] = useState<string | null>(null);
  const [subsetLoading, setSubsetLoading] = useState(false);
  const [aiServerConfigured, setAiServerConfigured] = useState(false);
  const [aiFixingId, setAiFixingId] = useState<string | null>(null);
  const [auth, setAuth] = useState<AuthMeResponse | null>(null);
  const [workspaces, setWorkspaces] = useState<WorkspaceSummary[]>([]);
  const health = useHealth();
  const aiSettings = useAiSettings();
  const systemOneSettings = useSystemOneSettings();
  const { triage, runTriage, resetTriage } = useAuditTriage(workspace);

  const aiConfigured = isAiConfigured(aiSettings) || aiServerConfigured;
  const systemOneEnabled = systemOneSettings.enabled;
  const systemOneBadge = systemOneLabel(systemOneSettings);
  const aiLabel = isAiConfigured(aiSettings)
    ? providerLabel(aiSettings)
    : aiServerConfigured
      ? 'Server env'
      : 'Not Configured';

  useEffect(() => {
    if (isAiConfigured(aiSettings)) {
      setAiServerConfigured(false);
      return;
    }
    // No browser settings: probe once to discover a server-side KODO_LLM_* configuration.
    const controller = new AbortController();
    api
      .aiTestConnection(undefined, controller.signal)
      .then(() => setAiServerConfigured(true))
      .catch(() => setAiServerConfigured(false));
    return () => controller.abort();
  }, [aiSettings]);

  const refreshAuth = useCallback(async () => {
    try {
      setAuth(await api.fetchAuthMe());
    } catch {
      // Local mode remains usable even if /auth/me is unreachable during startup.
      setAuth({ mode: 'local', authenticated: true, user: null, githubOAuthConfigured: false });
    }
  }, []);

  const refreshWorkspaces = useCallback(async () => {
    try {
      const result = await api.fetchWorkspaces();
      setWorkspaces(result.workspaces);
    } catch {
      setWorkspaces([]);
    }
  }, []);

  useEffect(() => {
    void refreshAuth();
  }, [refreshAuth]);

  useEffect(() => {
    if (!auth?.authenticated) {
      setWorkspaces([]);
      return;
    }
    void refreshWorkspaces();
  }, [auth?.authenticated, auth?.user?.id, refreshWorkspaces, workspaceRevision]);

  useEffect(() => {
    resetTriage();
  }, [workspace?.rootPath, resetTriage]);

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

  const graphFilter = useGraphFilter(view?.rootPath ?? null);

  const filtered = useMemo<ReturnType<typeof applyGraphFilter> | null>(
    () =>
      view
        ? applyGraphFilter(view.nodes, view.relations, view.audit, graphFilter.filter, selectedId)
        : null,
    [view, graphFilter.filter, selectedId],
  );

  const searchResults = useMemo(
    () => searchComponents(view?.nodes ?? NO_NODES, graphFilter.filter.query),
    [view, graphFilter.filter.query],
  );

  const graph = useMemo(
    () =>
      filtered
        ? buildGraph(filtered.nodes, filtered.relations)
        : { nodes: [], edges: [] },
    [filtered],
  );

  // The UML tab re-renders the Mermaid classDiagram server-side for the filtered/1-hop subset, so
  // the diagram always matches what the graph shows.
  useEffect(() => {
    if (!filtered?.active || tab !== 'uml') {
      setSubsetDiagram(null);
      setSubsetLoading(false);
      return;
    }
    const controller = new AbortController();
    setSubsetLoading(true);
    const timer = window.setTimeout(() => {
      api
        .mermaidSubset(filtered.nodes, filtered.relations, controller.signal)
        .then((result) => {
          if (!controller.signal.aborted) {
            setSubsetDiagram(result.diagram);
          }
        })
        .catch(() => {
          if (!controller.signal.aborted) {
            setSubsetDiagram(null);
          }
        })
        .finally(() => {
          if (!controller.signal.aborted) {
            setSubsetLoading(false);
          }
        });
    }, 140);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [filtered, tab]);

  const filterSummary = useMemo(() => {
    const parts: string[] = [];
    if (filtered?.focusActive) {
      parts.push('1-hop focus');
    }
    if (graphFilter.filter.issuesOnly) {
      parts.push('issues only');
    }
    if (graphFilter.filter.layers.length > 0) {
      parts.push(`layers: ${graphFilter.filter.layers.join(', ')}`);
    }
    if (graphFilter.filter.stacks.length > 0) {
      parts.push(`stacks: ${graphFilter.filter.stacks.join(', ')}`);
    }
    const query = graphFilter.filter.query.trim();
    if (query) {
      parts.push(`search: ${query}`);
    }
    return parts.length > 0 ? parts.join(' · ') : null;
  }, [filtered?.focusActive, graphFilter.filter]);

  const handleSelect = useCallback((node: ComponentNode | null) => {
    setSelectedId(node?.id ?? null);
  }, []);

  const handleSelectNodeId = useCallback((nodeId: string) => {
    setSelectedId(nodeId);
  }, []);

  const handlePickSearchResult = useCallback((nodeId: string) => {
    setSelectedId(nodeId);
    setTab('graph');
    setCenterRequest((current) => ({ id: nodeId, token: (current?.token ?? 0) + 1 }));
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
      resetTriage();
      setDraft(emptyDraft());
      setPlan(null);
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
    [health.refresh, resetTriage],
  );

  const runScan = useCallback(
    async (target: string) => {
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
    },
    [lastApply, scanWorkspace],
  );

  const handleScan = useCallback(async () => {
    const target = path.trim();
    if (!target || scanning) {
      return;
    }
    await runScan(target);
  }, [path, scanning, runScan]);

  const handleBrowseSelect = useCallback(
    async (target: string) => {
      setBrowseOpen(false);
      setPath(target);
      setNotice(null);
      await runScan(target);
    },
    [runScan],
  );

  const handleApplied = useCallback(
    async (applyId: string, appliedFiles: string[]) => {
      const target = workspace?.rootPath ?? path.trim();
      const fromPlan = plan !== null;
      setLastApply({ applyId, appliedFiles, rootPath: target });
      setRollbackConflict(null);
      setNotice(null);
      setError(null);
      setPlan(null);
      if (!target) {
        return;
      }
      try {
        await scanWorkspace(target, { resetView: false });
        if (fromPlan) {
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
    [path, plan, scanWorkspace, workspace],
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

  const handleWorkspaceCloned = useCallback(
    async (localPath: string) => {
      setPath(localPath);
      setError(null);
      setLastApply(null);
      setRollbackConflict(null);
      try {
        const result = await scanWorkspace(localPath, { resetView: true });
        setNotice(
          `Cloned repository ready at ${result.rootPath} — ${result.nodes.length} component(s) scanned.`,
        );
      } catch (reason) {
        setError(
          `The repository was cloned to ${localPath}, but scanning it failed: ${
            reason instanceof Error ? reason.message : String(reason)
          }`,
        );
      }
    },
    [scanWorkspace],
  );

  const handleSelectWorkspace = useCallback(
    async (target: WorkspaceSummary) => {
      setPath(target.localPath);
      setError(null);
      setLastApply(null);
      setRollbackConflict(null);
      try {
        const result = await scanWorkspace(target.localPath, { resetView: true });
        setNotice(
          `Switched to ${result.name} — ${result.nodes.length} component(s) scanned.`,
        );
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : String(reason));
      }
    },
    [scanWorkspace],
  );

  const currentRoot = workspace?.rootPath ?? '';

  const handleDeleteWorkspace = useCallback(
    async (target: WorkspaceSummary) => {
      setError(null);
      try {
        await api.deleteWorkspace(target.id);
        await refreshWorkspaces();
        if (path.trim() === target.localPath || currentRoot === target.localPath) {
          setWorkspace(null);
          setPath('');
          setLastApply(null);
          setRollbackConflict(null);
          setNotice(null);
        }
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : String(reason));
      }
    },
    [currentRoot, path, refreshWorkspaces],
  );

  const handleSignOut = useCallback(async () => {
    try {
      await api.logout();
    } catch {
      // Clearing local state is still the right outcome if the call fails.
    }
    setWorkspace(null);
    setPath('');
    setPlan(null);
    setLastApply(null);
    setRollbackConflict(null);
    setNotice(null);
    await refreshAuth();
  }, [refreshAuth]);

  const handleAiAuditFix = useCallback(
    async (finding: AuditFinding) => {
      if (!workspace || aiFixingId) {
        return;
      }
      setAiFixingId(finding.id);
      setError(null);
      try {
        const result = await api.aiAuditFix({
          rootPath: workspace.rootPath,
          finding,
          workspaceIr: workspace,
          llmConfig: toLlmOverride(aiSettings),
        });
        setPlan({
          response: { patches: result.patches, warnings: result.warnings },
          label: finding.title,
          kind: 'ai',
          explanation: result.explanation,
          modelUsed: result.modelUsed,
        });
        setTab('diff');
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : String(reason));
      } finally {
        setAiFixingId(null);
      }
    },
    [aiFixingId, aiSettings, workspace],
  );

  const handleImplementMethod = useCallback(
    async (node: ComponentNode, methodName: string, instruction: string) => {
      if (!workspace) {
        throw new Error('Scan a workspace before using the AI Copilot.');
      }
      const result = await api.aiImplementMethod({
        rootPath: workspace.rootPath,
        filePath: node.filePath,
        nodeId: node.id,
        methodName,
        instruction,
        workspaceIr: workspace,
        llmConfig: toLlmOverride(aiSettings),
      });
      setPlan({
        response: { patches: result.patches, warnings: result.warnings },
        label: `${node.name}.${methodName}`,
        kind: 'ai',
        explanation: result.explanation,
        modelUsed: result.modelUsed,
      });
      setTab('diff');
    },
    [aiSettings, workspace],
  );

  const openInspector = useCallback(() => setTab('code'), []);

  const handleOpenFile = useCallback(
    (filePath: string) => {
      const normalized = filePath.replace(/\\/g, '/');
      const node = view?.nodes.find((item) => item.filePath.replace(/\\/g, '/') === normalized);
      if (node) {
        setSelectedId(node.id);
        setTab('code');
      }
    },
    [view],
  );

  if (auth?.mode === 'saas' && !auth.authenticated) {
    return <LoginScreen auth={auth} />;
  }

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-ink-950 text-slate-200">
      <TopBar
        path={path}
        onPathChange={setPath}
        onScan={() => void handleScan()}
        scanning={scanning}
        onBrowse={() => setBrowseOpen(true)}
        health={health}
        workspace={view}
        aiLabel={aiLabel}
        aiConfigured={aiConfigured}
        systemOneLabel={systemOneBadge}
        systemOneEnabled={systemOneEnabled}
        onOpenAiSettings={() => setAiModalOpen(true)}
        mode={auth?.mode ?? 'local'}
        authenticated={auth?.authenticated ?? true}
        authUser={auth?.user ?? null}
        githubOAuthConfigured={auth?.githubOAuthConfigured ?? false}
        onSignOut={() => void handleSignOut()}
        workspaces={workspaces}
        onSelectWorkspace={handleSelectWorkspace}
        onDeleteWorkspace={(workspace) => void handleDeleteWorkspace(workspace)}
        onWorkspaceCloned={(localPath) => void handleWorkspaceCloned(localPath)}
        onRefreshWorkspaces={() => void refreshWorkspaces()}
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
                planCount={plan ? plan.response.patches.length : null}
              />
              <WarningsBar warnings={view.warnings} />
              <div className="min-h-0 flex-1">
                {tab === 'graph' && (
                  <div className="flex h-full min-h-0 flex-col">
                    <GraphFilterBar
                      filter={graphFilter.filter}
                      active={graphFilter.active}
                      visibleCount={filtered?.nodes.length ?? 0}
                      totalCount={view.nodes.length}
                      findingsCount={view.audit.findings.length}
                      focusEnabled={selectedId !== null}
                      availableStacks={view.detectedStacks}
                      searchResults={searchResults}
                      onQueryChange={graphFilter.setQuery}
                      onToggleLayer={graphFilter.toggleLayer}
                      onToggleStack={graphFilter.toggleStack}
                      onToggleIssuesOnly={graphFilter.toggleIssuesOnly}
                      onToggleFocus={graphFilter.toggleFocusOneHop}
                      onReset={graphFilter.reset}
                      onPickResult={handlePickSearchResult}
                    />
                    <div className="min-h-0 flex-1">
                      <MacroGraph
                        key={view.rootPath}
                        nodes={filtered?.nodes ?? NO_NODES}
                        relations={filtered?.relations ?? NO_RELATIONS}
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
                        centerRequest={centerRequest}
                      />
                    </div>
                  </div>
                )}
                {tab === 'uml' && (
                  <UmlDiagram
                    key={`${view.rootPath}-uml`}
                    diagram={filtered?.active ? (subsetDiagram ?? '') : view.mermaidClassDiagram}
                    componentCount={filtered?.active ? (filtered?.nodes.length ?? 0) : view.nodes.length}
                    totalComponentCount={view.nodes.length}
                    draftPending={draftDirty}
                    filterActive={filtered?.active ?? false}
                    focusActive={filtered?.focusActive ?? false}
                    filterSummary={filterSummary}
                    subsetLoading={subsetLoading}
                    findingsCount={view.audit.findings.length}
                    canFocusSelected={selectedId !== null}
                    onFocusSelected={() => graphFilter.setFocusOneHop(true)}
                    onShowIssuesOnly={() => graphFilter.setIssuesOnly(true)}
                    onResetFilters={graphFilter.reset}
                  />
                )}
                {tab === 'code' && <CodeInspector rootPath={view.rootPath} node={selected} />}
                {tab === 'builder' && (
                  <BuilderPanel
                    key={`${view.rootPath}-builder`}
                    rootPath={view.rootPath}
                    revision={workspaceRevision}
                    aiConfigured={aiConfigured}
                    onOpenAiSettings={() => setAiModalOpen(true)}
                    onPreviewReady={(preview) => {
                      setPlan(preview);
                      setTab('diff');
                    }}
                  />
                )}
                {tab === 'deploy' && (
                  <DeployStudio
                    key={`${view.rootPath}-deploy`}
                    rootPath={view.rootPath}
                    workspaceName={view.name}
                    detectedStacks={view.detectedStacks}
                    mode={auth?.mode ?? 'local'}
                    revision={workspaceRevision}
                    aiConfigured={aiConfigured}
                    llmConfig={toLlmOverride(aiSettings)}
                    onPlanReady={(preview) => {
                      setPlan(preview);
                      setTab('diff');
                    }}
                    onOpenFile={handleOpenFile}
                    onPreviewReady={(preview) => {
                      setPlan(preview);
                      setTab('diff');
                    }}
                    onWorkspaceCloned={(localPath) => void handleWorkspaceCloned(localPath)}
                  />
                )}
                {tab === 'decisions' && (
                  <DecisionsPanel
                    key={`${view.rootPath}-decisions`}
                    rootPath={view.rootPath}
                    workspace={view}
                  />
                )}
                {tab === 'diff' && workspace && (
                  <DiffPreview
                    workspace={workspace}
                    draft={draft}
                    requestId={previewRequest}
                    plan={plan}
                    onPlanDismiss={() => setPlan(null)}
                    onApplied={handleAppliedChange}
                    aiConfigured={aiConfigured}
                    llmConfig={toLlmOverride(aiSettings)}
                    onPlanReady={setPlan}
                    onOpenFile={handleOpenFile}
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
            aiConfigured={aiConfigured}
            aiFixingId={aiFixingId}
            onFixWithAi={(finding) => void handleAiAuditFix(finding)}
            onImplementMethod={handleImplementMethod}
            onOpenAiSettings={() => setAiModalOpen(true)}
            triage={triage}
            onTriage={() => void runTriage()}
          />
        )}
      </div>

      <AiSettingsModal open={aiModalOpen} onClose={() => setAiModalOpen(false)} />
      <FolderBrowserModal
        open={browseOpen}
        onClose={() => setBrowseOpen(false)}
        onSelect={(target) => void handleBrowseSelect(target)}
      />
    </div>
  );
}

function TabBar({
  tab,
  onChange,
  workspace,
  hasSelection,
  draft,
  planCount,
}: {
  tab: TabId;
  onChange: (tab: TabId) => void;
  workspace: WorkspaceIR;
  hasSelection: boolean;
  draft: ReturnType<typeof draftEditCount> | null;
  planCount: number | null;
}) {
  const tabs: Array<{ id: TabId; label: string; icon: typeof GraphIcon; badge?: string }> = [
    { id: 'graph', label: 'Macro Graph', icon: GraphIcon, badge: String(workspace.nodes.length) },
    { id: 'uml', label: 'UML Diagram', icon: UmlIcon },
    { id: 'code', label: 'Code Inspector', icon: CodeIcon, badge: hasSelection ? '●' : undefined },
    {
      id: 'builder',
      label: 'Builder',
      icon: BuilderIcon,
      badge: planCount ? String(planCount) : undefined,
    },
    { id: 'deploy', label: 'Deploy', icon: DeployIcon },
    { id: 'decisions', label: 'Decisions (ADR)', icon: DecisionIcon },
    {
      id: 'diff',
      label: 'Diff Preview',
      icon: DiffIcon,
      badge:
        draft && draft.total > 0
          ? String(draft.total)
          : planCount
            ? String(planCount)
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
