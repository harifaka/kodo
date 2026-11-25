/**
 * Phase 11 — local-only, zero-copy folder browser (`GET /api/v1/fs/browse`).
 * The API lists real host/mount folders in place; nothing is uploaded or copied.
 */

export type BrowseRuntime = 'docker' | 'native';

/** Lightweight marker stacks detected from immediate children only (no deep analysis). */
export type ProjectStackTag = 'java' | 'csharp' | 'nodejs' | 'python';

export interface BrowseRoot {
  label: string;
  path: string;
}

export interface BrowseMarkers {
  stacks: ProjectStackTag[];
  isGitRepo: boolean;
}

export interface BrowseEntry {
  name: string;
  path: string;
  stacks: ProjectStackTag[];
  isGitRepo: boolean;
  hasSubdirectories: boolean;
}

export interface BrowseResponse {
  runtime: BrowseRuntime;
  currentPath: string;
  parentPath: string | null;
  roots: BrowseRoot[];
  currentMarkers: BrowseMarkers;
  entries: BrowseEntry[];
  truncated: boolean;
  emptyMountHint: boolean;
  hintMessage: string | null;
}
