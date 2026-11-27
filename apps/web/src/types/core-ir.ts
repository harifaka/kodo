/**
 * Core IR — canonical contract.
 * Mirrors packages/core-ir/schema.json and the Pydantic/C# implementations. Do not diverge.
 */

export type Stack = 'spring-boot' | 'csharp-dotnet' | 'nodejs' | 'python' | 'unknown';

export type Layer =
  | 'controller'
  | 'service'
  | 'repository'
  | 'entity'
  | 'viewmodel'
  | 'view'
  | 'component'
  | 'other';

export type NodeKind = 'class' | 'interface' | 'record' | 'enum' | 'module' | 'router';

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
  audit: AuditReport;
}

export type AuditRuleId =
  | 'LAYER_VIOLATION'
  | 'CIRCULAR_DEPENDENCY'
  | 'GOD_CLASS'
  | 'ORPHAN_COMPONENT'
  | 'ENTITY_EXPOSED_IN_CONTROLLER'
  | 'MISSING_VALIDATION';

export type Severity = 'error' | 'warning' | 'info';

export interface AuditFinding {
  id: string;
  ruleId: AuditRuleId;
  severity: Severity;
  title: string;
  message: string;
  suggestion: string;
  nodeIds: string[];
  /** Affected relations formatted as `${sourceId}->${targetId}`. */
  edgeKeys: string[];
  filePath: string | null;
}

export interface AuditSummary {
  errors: number;
  warnings: number;
  info: number;
}

export interface AuditReport {
  score: number;
  summary: AuditSummary;
  findings: AuditFinding[];
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

/** Response of the stateless `POST /api/v1/mermaid` subset renderer (Phase 11). */
export interface MermaidResponse {
  diagram: string;
  nodeCount: number;
  relationCount: number;
}

/** Layered `classDiagram` layout knobs (Phase 14). Every field is optional on the wire. */
export type DiagramDirection = 'TB' | 'LR';
export type DiagramMemberDetail = 'full' | 'compact' | 'names_only';

export interface MermaidLayoutOptions {
  groupByLayer: boolean;
  direction: DiagramDirection;
  memberDetail: DiagramMemberDetail;
}
