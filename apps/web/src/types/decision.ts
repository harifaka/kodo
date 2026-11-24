/** Phase 10 System 1 (Laya) decision layer contracts (client <-> /api/v1/decision*). */

import type { WorkspaceIR } from './core-ir';

/** Per-request System 1 settings; kept in sessionStorage and never written to the repository. */
export interface SystemOneOverride {
  enabled?: boolean;
  baseUrl?: string;
  model?: string;
  apiKey?: string;
  timeoutSeconds?: number;
  autoThreshold?: number;
}

export interface SystemOneSettings {
  enabled: boolean;
  baseUrl: string;
  model: string;
  apiKey: string;
  autoThreshold: number;
}

export type SystemOneProviderKind = 'ollama' | 'laya-serve';

export interface SystemOnePreset {
  id: SystemOneProviderKind;
  label: string;
  short: string;
  baseUrl: string;
  model: string;
  hint: string;
}

/** POST /api/v1/decision/test-connection */
export interface SystemOneTestResponse {
  reachable: boolean;
  latencyMs: number;
  model: string;
  providerHint: string;
  warning?: string | null;
  errorCode?: string | null;
}

export interface DecisionAnswer {
  answer: string | null;
  probabilities: Record<string, number>;
  confidence: number;
}

export type DecisionAnswers = Record<string, DecisionAnswer>;

export type DecisionType = 'audit_triage' | 'task_route' | 'diff_safety';

export type RiskLevel =
  | 'critical_arch_risk'
  | 'moderate_maintainability'
  | 'low_boilerplate'
  | 'uncertain';

export type SuggestedRoute =
  | 'deterministic_ast'
  | 'template_builder'
  | 'deepseek_refactor'
  | 'human_review'
  | 'ignore_benign'
  | 'uncertain';

export type ExecutionRoute =
  | 'deterministic_ast'
  | 'template_builder'
  | 'deepseek_code'
  | 'deepseek_reasoning'
  | 'human_review'
  | 'uncertain';

export type BlastRadius = 'single_file_local' | 'cross_layer_slice' | 'multi_service_arch' | 'uncertain';
export type DiffStatus = 'pass' | 'caution' | 'high_risk';

/** POST /api/v1/decision/triage-audit */
export interface TriageAuditRequest {
  rootPath: string;
  workspaceIr: WorkspaceIR;
  findingIds?: string[];
  systemOneConfig?: SystemOneOverride;
}

export interface TriageItem {
  adrId: string;
  findingId: string;
  riskLevel: RiskLevel | string;
  recommendedRoute: SuggestedRoute | string;
  confidence: number;
  escalatedToSystem2: boolean;
  priority: number;
  answers: DecisionAnswers;
}

export interface TriageAuditResponse {
  available: boolean;
  model: string;
  latencyMs: number;
  items: TriageItem[];
  warning?: string | null;
}

/** POST /api/v1/decision/route-task */
export interface RouteTaskRequest {
  rootPath: string;
  intent: string;
  workspaceIr: WorkspaceIR;
  targetNodeId?: string;
  systemOneConfig?: SystemOneOverride;
}

export interface RouteTaskResponse {
  available: boolean;
  adrId?: string | null;
  recommendedRoute: ExecutionRoute | string;
  blastRadius: BlastRadius | string;
  confidence: number;
  escalateToSystem2: boolean;
  rationale: string;
  answers: DecisionAnswers;
  warning?: string | null;
}

/** POST /api/v1/decision/screen-diff */
export interface DiffPatchInput {
  filePath: string;
  originalContent: string;
  proposedContent: string;
  isNewFile?: boolean;
}

export interface ScreenDiffRequest {
  rootPath: string;
  patches: DiffPatchInput[];
  workspaceIr?: WorkspaceIR;
  systemOneConfig?: SystemOneOverride;
}

export interface ScreenDiffResponse {
  available: boolean;
  adrId?: string | null;
  status: DiffStatus;
  confidence: number;
  flags: string[];
  answers: DecisionAnswers;
  advisoryNote: string;
  warning?: string | null;
}

export type DecisionFeedbackStatus = 'pending' | 'accepted' | 'overridden';

export interface DecisionRecordSummary {
  id: string;
  workspacePath: string;
  decisionType: DecisionType;
  subject: string;
  model: string;
  recommendedRoute: string;
  confidence: number;
  latencyMs: number;
  feedbackStatus: DecisionFeedbackStatus;
  overrideRoute?: string | null;
  feedbackNote?: string | null;
  createdAt: string;
  feedbackAt?: string | null;
  answers: DecisionAnswers;
}

export interface DecisionListResponse {
  decisions: DecisionRecordSummary[];
}

export interface DecisionFeedbackRequest {
  status: 'accepted' | 'overridden';
  overrideRoute?: string;
  note?: string;
}

/** Shared client-side triage state (App -> NodeDetailsPanel -> AuditPanel). */
export interface TriageState {
  pending: boolean;
  available: boolean | null;
  model?: string;
  latencyMs?: number;
  warning?: string | null;
  error?: string | null;
  items: Record<string, TriageItem>;
}
