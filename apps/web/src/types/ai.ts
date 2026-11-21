/** Phase 5 DeepSeek Architecture Copilot contracts (client <-> /api/v1/ai/*). */

import type { Blueprint, BlueprintStack, ScaffoldPreview } from './blueprint';
import type { AuditFinding, WorkspaceIR } from './core-ir';
import type { DryRunResponse } from './patching';

/** Per-request LLM settings; kept in sessionStorage and never written to the target repository. */
export interface LlmOverride {
  baseUrl?: string;
  apiKey?: string;
  codeModel?: string;
  reasoningModel?: string;
  timeoutSeconds?: number;
}

export interface AiSettings {
  baseUrl: string;
  apiKey: string;
  codeModel: string;
  reasoningModel: string;
}

export type AiProviderKind = 'cloud' | 'local' | 'custom';

/** POST /api/v1/ai/spec-to-blueprint */
export interface SpecToBlueprintRequest {
  spec: string;
  stack: BlueprintStack;
  projectName?: string;
  basePackageOrNamespace?: string;
  llmConfig?: LlmOverride;
}

export interface SpecToBlueprintResponse {
  blueprint: Blueprint;
  rationale: string;
  modelUsed: string;
  warnings: string[];
}

/** POST /api/v1/ai/audit-fix and /api/v1/ai/implement-method — a dry-run plan plus rationale. */
export interface AiPatchResponse extends DryRunResponse {
  explanation: string;
  modelUsed: string;
}

export interface AuditFixRequest {
  rootPath: string;
  finding: AuditFinding;
  workspaceIr: WorkspaceIR;
  llmConfig?: LlmOverride;
}

export interface ImplementMethodRequest {
  rootPath: string;
  filePath: string;
  nodeId: string;
  methodName: string;
  instruction: string;
  workspaceIr: WorkspaceIR;
  llmConfig?: LlmOverride;
}

/** POST /api/v1/ai/test-connection */
export interface TestConnectionResponse {
  ok: boolean;
  provider: 'cloud' | 'local';
  baseUrl: string;
  codeModel: string;
  reasoningModel: string;
  models: string[];
}

/** A reviewed plan handed to the Diff Preview tab (Builder scaffolding or an AI proposal). */
export interface PlanPreview extends ScaffoldPreview {
  kind: 'scaffold' | 'ai';
  /** AI rationale shown above the diff; never used for scaffolding. */
  explanation?: string;
  modelUsed?: string;
}
