/** Dry-run AST patching contract (Phase 3b) plus guarded apply/rollback (Phase 3c). */

export type PatchOperationKind =
  | 'add_field'
  | 'update_field'
  | 'remove_field'
  | 'add_annotation'
  | 'remove_annotation'
  | 'add_dependency'
  | 'remove_dependency';

export interface PatchField {
  name: string;
  type: string;
  visibility?: string;
  annotations: string[];
}

export interface PatchOperation {
  op: PatchOperationKind;
  /** Path relative to the workspace root, using forward slashes. */
  filePath: string;
  /** Simple class/interface/record name the operation targets. */
  typeName: string;
  fieldName?: string;
  originalName?: string;
  field?: PatchField;
  annotation?: string;
}

export interface PatchResult {
  filePath: string;
  language: string;
  originalContent: string;
  /** SHA-256 of the original file bytes; echoed back as `expectedSha256` on apply. */
  originalSha256: string;
  proposedContent: string;
  summary: string;
  warnings: string[];
}

export interface DryRunResponse {
  patches: PatchResult[];
  warnings: string[];
}

/** Read-only Git inspection (GET /api/v1/git/status). */
export interface GitStatus {
  isGitRepo: boolean;
  branch: string | null;
  isDirty: boolean;
  dirtyFiles: string[];
  untrackedCount: number;
  gitAvailable: boolean;
  warning: string | null;
}

export interface ApplyPatch {
  filePath: string;
  expectedSha256: string;
  proposedContent: string;
}

export interface ApplyRequest {
  rootPath: string;
  patches: ApplyPatch[];
  allowDirty: boolean;
  allowNonGit: boolean;
}

export interface ApplyResponse {
  applyId: string;
  appliedFiles: string[];
  gitStatus: GitStatus;
  warnings: string[];
}

export interface RollbackResponse {
  restoredFiles: string[];
}

/** Structured 409/404 error codes returned by /api/v1/apply and /api/v1/apply/rollback. */
export type ApplyErrorCode =
  | 'GIT_DIRTY'
  | 'NOT_A_GIT_REPO'
  | 'STALE_FILE'
  | 'UNKNOWN_APPLY'
  | 'PATH_REJECTED'
  | 'DUPLICATE_TARGET'
  | 'FILE_TOO_LARGE'
  | 'NOT_UTF8'
  | 'NOT_READABLE'
  | 'WRITE_FAILED';

export interface ApplyErrorDetail {
  code: ApplyErrorCode | string;
  message: string;
  /** Set by GIT_DIRTY. */
  dirtyFiles?: string[];
  /** Set by STALE_FILE. */
  paths?: string[];
  /** Set by NOT_A_GIT_REPO when Git is missing or the folder is not a repo. */
  warning?: string | null;
}
