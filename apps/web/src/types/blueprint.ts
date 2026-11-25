/** Versioned `kodo.blueprint.json` contract (Phase 4) — mirrors packages/core-ir/blueprint.schema.json. */

import type { DryRunResponse } from './patching';

export type BlueprintStack = 'spring-boot' | 'csharp-wpf' | 'nodejs' | 'python-fastapi';

export interface BlueprintField {
  name: string;
  /** Canonical stack-aware type (string, decimal, date, uuid, …) or a stack-native type. */
  type: string;
  required: boolean;
  annotations: string[];
}

export interface BlueprintSlice {
  name: string;
  fields: BlueprintField[];
  dependsOnSlices: string[];
  includeTests: boolean;
}

export interface Blueprint {
  schemaVersion: '1.0';
  projectName: string;
  stack: BlueprintStack;
  basePackageOrNamespace: string;
  slices: BlueprintSlice[];
}

/** GET /api/v1/blueprint */
export interface BlueprintResponse {
  exists: boolean;
  blueprint: Blueprint | null;
  warnings: string[];
}

/** POST /api/v1/scaffold/dry-run */
export interface ScaffoldRequest {
  rootPath: string;
  blueprint: Blueprint;
  includeProjectSkeleton: boolean;
  saveBlueprint: boolean;
}

/** A generated-file plan handed to the Diff Preview tab for review + guarded apply. */
export interface ScaffoldPreview {
  response: DryRunResponse;
  label: string;
}
