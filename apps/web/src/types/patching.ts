/** Dry-run AST patching contract (Phase 3b) — computed in memory, never written to disk. */

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
  proposedContent: string;
  summary: string;
  warnings: string[];
}

export interface DryRunResponse {
  patches: PatchResult[];
  warnings: string[];
}
