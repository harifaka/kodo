/** Phase 8 account contracts (auth, workspaces, saved blueprints, user settings). */

export type KodoMode = 'local' | 'saas';

export interface AuthUser {
  id: string;
  username: string;
  displayName: string | null;
  avatarUrl: string | null;
}

/** GET /api/v1/auth/me */
export interface AuthMeResponse {
  mode: KodoMode | string;
  authenticated: boolean;
  user: AuthUser | null;
  githubOAuthConfigured: boolean;
}

/** GET /api/v1/workspaces */
export interface WorkspaceSummary {
  id: string;
  name: string;
  localPath: string;
  repoUrl: string | null;
  branch: string | null;
  lastHealthScore: number | null;
  lastScannedAt: string | null;
  createdAt: string;
}

export interface WorkspaceListResponse {
  workspaces: WorkspaceSummary[];
}

/** DELETE /api/v1/workspaces/{id} */
export interface DeleteWorkspaceResponse {
  ok: boolean;
  workspaceId: string;
  directoryRemoved: boolean;
}

/** GET/PUT /api/v1/user/settings */
export interface UserSettingsResponse {
  settings: Record<string, unknown>;
  updatedAt: string | null;
}

/** GET /api/v1/blueprints */
export interface BlueprintSummary {
  id: string;
  workspacePath: string;
  name: string;
  stack: string;
  blueprint: Record<string, unknown> | null;
  updatedAt: string;
}

export interface BlueprintListResponse {
  blueprints: BlueprintSummary[];
}
