/** Phase 9 sandboxed build verification contracts (client <-> /api/v1/build/*). */

import type { AiPatchResponse, LlmOverride } from './ai';
import type { WorkspaceIR } from './core-ir';

export type BuildStack = 'java' | 'csharp' | 'nodejs' | 'python';
export type BuildStatusKind = 'passed' | 'failed' | 'timeout' | 'unavailable';

/** One in-memory proposal verified inside the sandbox; the workspace itself is never modified. */
export interface BuildPatchInput {
  filePath: string;
  proposedContent: string;
  isNewFile?: boolean;
}

export interface BuildDiagnostic {
  filePath: string;
  line: number;
  column: number;
  severity: 'error' | 'warning';
  /** Compiler code (`CS0103`, `TS2304`) or an empty string for Maven diagnostics. */
  code: string;
  message: string;
}

/** GET /api/v1/build/status */
export interface BuilderStatus {
  enabled: boolean;
  dockerAvailable: boolean;
  daemonRunning: boolean;
  images: Record<BuildStack, boolean>;
  warning: string | null;
}

/** POST /api/v1/build/verify and /verify/stream */
export interface BuildVerifyRequest {
  rootPath: string;
  stack?: BuildStack | null;
  patches?: BuildPatchInput[];
  runTests: boolean;
}

export interface BuildResult {
  buildId: string;
  stack: BuildStack;
  status: BuildStatusKind;
  exitCode: number | null;
  durationMs: number;
  image: string;
  networkMode: string;
  diagnostics: BuildDiagnostic[];
  output: string;
  warnings: string[];
}

/** POST /api/v1/ai/fix-build-errors — a normal dry-run plan plus rationale. */
export interface FixBuildErrorsRequest {
  rootPath: string;
  stack: BuildStack;
  diagnostics: BuildDiagnostic[];
  compilerOutput: string;
  patches?: BuildPatchInput[];
  workspaceIr?: WorkspaceIR;
  llmConfig?: LlmOverride;
}

export type FixBuildErrorsResponse = AiPatchResponse;
