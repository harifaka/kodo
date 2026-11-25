import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  EMPTY_GRAPH_FILTER,
  isFilterActive,
  type GraphFilter,
  type LayerGroup,
} from '../lib/graphFilter';
import type { Stack } from '../types/core-ir';

/** Shared Macro Graph / UML filter state (Phase 11 large-repo ergonomics). */
export function useGraphFilter(rootPath: string | null | undefined) {
  const [filter, setFilter] = useState<GraphFilter>(EMPTY_GRAPH_FILTER);

  useEffect(() => {
    // Filters are per workspace: a rescan or workspace switch starts clean.
    setFilter(EMPTY_GRAPH_FILTER);
  }, [rootPath]);

  const setQuery = useCallback((query: string) => {
    setFilter((current) => ({ ...current, query }));
  }, []);

  const toggleLayer = useCallback((layer: LayerGroup) => {
    setFilter((current) => ({
      ...current,
      layers: current.layers.includes(layer)
        ? current.layers.filter((entry) => entry !== layer)
        : [...current.layers, layer],
    }));
  }, []);

  const toggleStack = useCallback((stack: Stack) => {
    setFilter((current) => ({
      ...current,
      stacks: current.stacks.includes(stack)
        ? current.stacks.filter((entry) => entry !== stack)
        : [...current.stacks, stack],
    }));
  }, []);

  const toggleIssuesOnly = useCallback(() => {
    setFilter((current) => ({ ...current, issuesOnly: !current.issuesOnly }));
  }, []);

  const setIssuesOnly = useCallback((value: boolean) => {
    setFilter((current) => ({ ...current, issuesOnly: value }));
  }, []);

  const setFocusOneHop = useCallback((value: boolean) => {
    setFilter((current) => ({ ...current, focusOneHop: value }));
  }, []);

  const toggleFocusOneHop = useCallback(() => {
    setFilter((current) => ({ ...current, focusOneHop: !current.focusOneHop }));
  }, []);

  const reset = useCallback(() => setFilter(EMPTY_GRAPH_FILTER), []);

  const active = useMemo(() => isFilterActive(filter), [filter]);

  return {
    filter,
    active,
    setQuery,
    toggleLayer,
    toggleStack,
    toggleIssuesOnly,
    setIssuesOnly,
    setFocusOneHop,
    toggleFocusOneHop,
    reset,
  };
}
