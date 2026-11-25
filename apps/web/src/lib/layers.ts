import type { Layer, RelationType, Stack } from '../types/core-ir';
import type { ProjectStackTag } from '../types/fs';

/** Column order of the Macro Graph, from inbound boundary to internals. */
export const LAYER_ORDER: Layer[] = [
  'controller',
  'service',
  'repository',
  'entity',
  'viewmodel',
  'view',
  'component',
  'other',
];

export interface LayerMeta {
  label: string;
  color: string;
  hint: string;
}

export const LAYER_META: Record<Layer, LayerMeta> = {
  controller: { label: 'Controller', color: '#38bdf8', hint: 'HTTP / request boundary' },
  service: { label: 'Service', color: '#34d399', hint: 'Business logic' },
  repository: { label: 'Repository', color: '#fbbf24', hint: 'Persistence boundary' },
  entity: { label: 'Entity', color: '#f472b6', hint: 'Domain data' },
  viewmodel: { label: 'ViewModel', color: '#a78bfa', hint: 'View state (MVVM)' },
  view: { label: 'View', color: '#22d3ee', hint: 'UI surface' },
  component: { label: 'Component', color: '#818cf8', hint: 'UI component' },
  other: { label: 'Other', color: '#94a3b8', hint: 'Unclassified' },
};

export const STACK_META: Record<Stack, { label: string; color: string }> = {
  'spring-boot': { label: 'Spring Boot', color: '#6ee7b7' },
  'csharp-dotnet': { label: 'C# / .NET', color: '#c084fc' },
  nodejs: { label: 'Node.js', color: '#facc15' },
  python: { label: 'Python', color: '#38bdf8' },
  unknown: { label: 'Unknown', color: '#94a3b8' },
};

export const RELATION_META: Record<RelationType, { label: string; color: string; dashed: boolean }> = {
  depends_on: { label: 'depends on', color: '#38bdf8', dashed: false },
  inherits: { label: 'inherits', color: '#a78bfa', dashed: false },
  implements: { label: 'implements', color: '#c084fc', dashed: true },
  references: { label: 'references', color: '#64748b', dashed: true },
};

export const KIND_LABEL: Record<string, string> = {
  class: 'class',
  interface: 'interface',
  record: 'record',
  enum: 'enum',
  module: 'module',
  router: 'router',
};

/**
 * Folder-browser badges (Phase 11). Python is a first-class stack since Phase 12 (Tree-sitter
 * analyzer, audit rules, patching, generator, deploy template and builder image).
 */
export const PROJECT_STACK_META: Record<
  ProjectStackTag,
  { label: string; short: string; color: string; title: string }
> = {
  java: {
    label: 'Spring Boot / Java',
    short: 'Java',
    color: '#6ee7b7',
    title: 'Detected pom.xml / build.gradle',
  },
  csharp: {
    label: 'C# / .NET',
    short: 'C#/.NET',
    color: '#c084fc',
    title: 'Detected *.csproj / *.sln',
  },
  nodejs: {
    label: 'Node.js',
    short: 'Node.js',
    color: '#facc15',
    title: 'Detected package.json',
  },
  python: {
    label: 'Python',
    short: 'Python',
    color: '#38bdf8',
    title: 'Detected pyproject.toml / requirements.txt / setup.py',
  },
};

export const PROJECT_STACK_ORDER: ProjectStackTag[] = ['java', 'csharp', 'nodejs', 'python'];
