import { useEffect, useMemo, useRef, useState } from 'react';
import { LAYER_GROUPS, type GraphFilter, type LayerGroup } from '../lib/graphFilter';
import { LAYER_META, STACK_META } from '../lib/layers';
import type { ComponentNode, Stack } from '../types/core-ir';
import { AlertIcon, CloseIcon, FolderIcon, ScanIcon } from './icons';

interface GraphFilterBarProps {
  filter: GraphFilter;
  active: boolean;
  visibleCount: number;
  totalCount: number;
  findingsCount: number;
  /** A component is selected, so 1-hop focus can be applied. */
  focusEnabled: boolean;
  availableStacks: Stack[];
  searchResults: ComponentNode[];
  onQueryChange: (query: string) => void;
  onToggleLayer: (layer: LayerGroup) => void;
  onToggleStack: (stack: Stack) => void;
  onToggleIssuesOnly: () => void;
  onToggleFocus: () => void;
  onReset: () => void;
  onPickResult: (nodeId: string) => void;
}

export function GraphFilterBar({
  filter,
  active,
  visibleCount,
  totalCount,
  findingsCount,
  focusEnabled,
  availableStacks,
  searchResults,
  onQueryChange,
  onToggleLayer,
  onToggleStack,
  onToggleIssuesOnly,
  onToggleFocus,
  onReset,
  onPickResult,
}: GraphFilterBarProps) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [resultsOpen, setResultsOpen] = useState(false);
  const showResults = resultsOpen && filter.query.trim().length > 0;

  const shortcut = useMemo(() => {
    const platform = typeof navigator === 'undefined' ? '' : navigator.platform;
    return /mac/i.test(platform) ? '⌘K' : 'Ctrl K';
  }, []);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        inputRef.current?.focus();
        inputRef.current?.select();
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, []);

  return (
    <div className="border-b border-ink-700/70 bg-ink-900/70 px-3 py-2">
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-[230px] flex-1">
          <FolderIcon className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-500" />
          <input
            ref={inputRef}
            value={filter.query}
            onChange={(event) => {
              onQueryChange(event.target.value);
              setResultsOpen(true);
            }}
            onFocus={() => setResultsOpen(true)}
            onBlur={() => {
              // Let a click on a result land before the list disappears.
              window.setTimeout(() => setResultsOpen(false), 120);
            }}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && searchResults.length > 0) {
                event.preventDefault();
                setResultsOpen(false);
                onPickResult(searchResults[0].id);
              } else if (event.key === 'Escape') {
                onQueryChange('');
                setResultsOpen(false);
                event.currentTarget.blur();
              }
            }}
            spellCheck={false}
            placeholder="Search components, files, annotations…"
            aria-label="Search the macro graph"
            className="w-full rounded-md border border-ink-600 bg-ink-950/80 py-1.5 pl-8 pr-14 font-mono text-[11px] text-slate-200 outline-none transition placeholder:text-slate-600 focus:border-sky-500/70 focus:ring-2 focus:ring-sky-500/10"
          />
          <kbd className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 rounded border border-ink-600 bg-ink-850 px-1.5 py-0.5 text-[9px] text-slate-500">
            {shortcut}
          </kbd>
          {showResults && (
            <div className="absolute left-0 right-0 top-[calc(100%+4px)] z-30 max-h-[260px] overflow-y-auto rounded-lg border border-ink-600 bg-ink-900/98 py-1 shadow-2xl backdrop-blur">
              {searchResults.length === 0 ? (
                <p className="px-3 py-2 text-[11px] text-slate-500">No component matches.</p>
              ) : (
                searchResults.map((node) => (
                  <button
                    key={node.id}
                    type="button"
                    onClick={() => {
                      setResultsOpen(false);
                      onPickResult(node.id);
                    }}
                    className="flex w-full items-start gap-2 px-2.5 py-1.5 text-left transition hover:bg-ink-800"
                  >
                    <span
                      className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full"
                      style={{ backgroundColor: LAYER_META[node.layer].color }}
                    />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[11.5px] text-slate-200">{node.name}</span>
                      <span className="block truncate font-mono text-[9.5px] text-slate-500">
                        {node.filePath}
                      </span>
                    </span>
                    <span className="shrink-0 text-[9px] uppercase tracking-wide text-slate-500">
                      {LAYER_META[node.layer].label}
                    </span>
                  </button>
                ))
              )}
            </div>
          )}
        </div>

        <span
          className="shrink-0 rounded-full border border-ink-600 bg-ink-850/80 px-2.5 py-1 text-[10.5px] text-slate-400"
          title="Visible components after filters"
        >
          Showing <span className="font-semibold text-slate-100">{visibleCount}</span> / {totalCount}{' '}
          components
        </span>

        <button
          type="button"
          onClick={onToggleIssuesOnly}
          disabled={findingsCount === 0}
          title={
            findingsCount === 0
              ? 'This workspace has no audit findings'
              : 'Show only the components and relations referenced by audit findings'
          }
          className={`inline-flex shrink-0 items-center gap-1.5 rounded-md border px-2.5 py-1 text-[10.5px] transition disabled:cursor-not-allowed disabled:opacity-45 ${
            filter.issuesOnly
              ? 'border-rose-400/60 bg-rose-500/15 text-rose-200'
              : 'border-ink-600 bg-ink-850/80 text-slate-400 hover:border-rose-400/50 hover:text-rose-200'
          }`}
        >
          <AlertIcon className="h-3 w-3" />
          Issues only
          <span className="text-[9.5px] opacity-75">{findingsCount}</span>
        </button>

        <button
          type="button"
          onClick={onToggleFocus}
          disabled={!focusEnabled}
          title={
            focusEnabled
              ? 'Show only the selected component and its direct neighbours (depth 1)'
              : 'Select a component on the graph to focus its 1-hop neighbourhood'
          }
          className={`inline-flex shrink-0 items-center gap-1.5 rounded-md border px-2.5 py-1 text-[10.5px] transition disabled:cursor-not-allowed disabled:opacity-45 ${
            filter.focusOneHop && focusEnabled
              ? 'border-sky-400/60 bg-sky-500/15 text-sky-200'
              : 'border-ink-600 bg-ink-850/80 text-slate-400 hover:border-sky-400/50 hover:text-sky-200'
          }`}
        >
          <ScanIcon className="h-3 w-3" />
          Focus 1-Hop
        </button>

        <button
          type="button"
          onClick={onReset}
          disabled={!active}
          title="Clear the search, layer/stack pills, issues-only and 1-hop focus"
          className="inline-flex shrink-0 items-center gap-1 rounded-md border border-ink-600 bg-ink-850/80 px-2.5 py-1 text-[10.5px] text-slate-400 transition enabled:hover:border-slate-400/60 enabled:hover:text-slate-100 disabled:cursor-not-allowed disabled:opacity-40"
        >
          <CloseIcon className="h-3 w-3" />
          Reset filters
        </button>
      </div>

      <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
        <span className="mr-0.5 text-[9px] uppercase tracking-[0.14em] text-slate-600">Layer</span>
        {LAYER_GROUPS.map((group) => {
          const selected = filter.layers.includes(group.id);
          const color = group.layers.length > 0 ? LAYER_META[group.layers[0]].color : '#94a3b8';
          return (
            <button
              key={group.id}
              type="button"
              onClick={() => onToggleLayer(group.id)}
              title={group.hint}
              className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] transition ${
                selected
                  ? 'border-transparent text-ink-950'
                  : 'border-ink-600 bg-ink-850/60 text-slate-400 hover:border-ink-500 hover:text-slate-200'
              }`}
              style={selected ? { backgroundColor: color } : undefined}
            >
              <span
                className="h-1.5 w-1.5 rounded-full"
                style={{ backgroundColor: selected ? '#0b0f16' : color }}
              />
              {group.label}
            </button>
          );
        })}

        {availableStacks.length > 0 && (
          <>
            <span className="ml-2 mr-0.5 text-[9px] uppercase tracking-[0.14em] text-slate-600">Stack</span>
            {availableStacks.map((stack) => {
              const selected = filter.stacks.includes(stack);
              const meta = STACK_META[stack];
              return (
                <button
                  key={stack}
                  type="button"
                  onClick={() => onToggleStack(stack)}
                  className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] transition ${
                    selected
                      ? 'border-transparent text-ink-950'
                      : 'border-ink-600 bg-ink-850/60 text-slate-400 hover:border-ink-500 hover:text-slate-200'
                  }`}
                  style={selected ? { backgroundColor: meta.color } : undefined}
                >
                  <span
                    className="h-1.5 w-1.5 rounded-full"
                    style={{ backgroundColor: selected ? '#0b0f16' : meta.color }}
                  />
                  {meta.label}
                </button>
              );
            })}
          </>
        )}
      </div>
    </div>
  );
}
