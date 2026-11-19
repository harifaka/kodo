/**
 * Core IR — canonical contract.
 * Mirrors packages/core-ir/schema.json and the Pydantic/C# implementations. Do not diverge.
 */

export type Stack = 'spring-boot' | 'csharp-dotnet' | 'nodejs' | 'unknown';

export type Layer =
  | 'controller'
  | 'service'
  | 'repository'
  | 'entity'
  | 'viewmodel'
  | 'view'
  | 'component'
  | 'other';

export type NodeKind = 'class' | 'interface' | 'record' | 'enum' | 'module';

export type RelationType = 'depends_on' | 'inherits' | 'implements' | 'references';

export interface ComponentField {
  name: string;
  type: string;
  visibility?: string;
  annotations: string[];
}

export interface ComponentMethod {
  name: string;
  returnType?: string;
  parameters: string[];
}

export interface ComponentNode {
  id: string;
  name: string;
  stack: Stack;
  layer: Layer;
  kind: NodeKind;
  filePath: string;
  annotations: string[];
  fields: ComponentField[];
  methods: ComponentMethod[];
}

export interface ComponentRelation {
  sourceId: string;
  targetId: string;
  type: RelationType;
}

export interface WorkspaceIR {
  name: string;
  rootPath: string;
  detectedStacks: Stack[];
  nodes: ComponentNode[];
  relations: ComponentRelation[];
  mermaidClassDiagram: string;
  warnings: string[];
}

export interface CSharpAnalyzerHealth {
  url: string;
  reachable: boolean;
}

export interface HealthResponse {
  status: string;
  service: string;
  version: string;
  analyzers: Record<string, CSharpAnalyzerHealth>;
  timestamp: string;
}

export interface FileContent {
  relPath: string;
  content: string;
  language: string;
  size: number;
}
