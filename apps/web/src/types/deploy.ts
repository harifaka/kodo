/** Phase 6 Deploy Studio contracts (client <-> /api/v1/deploy, /api/v1/git, /api/v1/audit-log). */

export type DeployStackId = 'spring-boot' | 'nodejs' | 'csharp-dotnet' | 'csharp-wpf';
export type BackingServiceId = 'postgres' | 'redis' | 'rabbitmq';

/** POST /api/v1/deploy/dry-run — returns the standard DryRunResponse. */
export interface DeployDryRunRequest {
  rootPath: string;
  projectName: string;
  /** `auto` resolves to a detected stack server-side. */
  stack: DeployStackId | 'auto';
  appPort?: number | null;
  backingServices: BackingServiceId[];
  overwriteExisting: boolean;
}

export interface ContainerInfo {
  name: string;
  service: string;
  state: string;
  status: string;
  /** `healthy` | `unhealthy` | `starting` | `none` | raw Docker value. */
  health: string;
  ports: string[];
}

/** GET /api/v1/deploy/docker/status */
export interface DockerStatus {
  dockerAvailable: boolean;
  daemonRunning: boolean;
  hasComposeFile: boolean;
  containers: ContainerInfo[];
  warning: string | null;
}

/** POST /api/v1/deploy/docker/up and /down */
export interface ComposeResult {
  success: boolean;
  command: string;
  stdout: string;
  stderr: string;
  status: DockerStatus;
  warning: string | null;
}

/** GET /api/v1/deploy/docker/logs */
export interface ComposeLogs {
  service: string | null;
  tail: number;
  logs: string;
  warning: string | null;
}

/** GET /api/v1/audit-log */
export type AuditAction =
  | 'apply'
  | 'rollback'
  | 'deploy_up'
  | 'deploy_down'
  | 'git_clone'
  | 'git_export';

export interface AuditLogEntry {
  timestamp: string;
  action: AuditAction | string;
  rootPath: string;
  summary: string;
  filesCount: number;
  status: string;
}

export interface AuditLogResponse {
  entries: AuditLogEntry[];
}

/** POST /api/v1/git/clone */
export interface CloneRequest {
  repoUrl: string;
  branch?: string;
  /** Kept in memory only; never persisted by Kodo. */
  token?: string;
}

export interface CloneResponse {
  localPath: string;
  repoUrl: string;
  branch: string | null;
}

/** POST /api/v1/git/export */
export interface ExportRequest {
  rootPath: string;
  branchName: string;
  commitMessage: string;
  createPr: boolean;
  prTitle?: string;
  prBody?: string;
  token?: string;
}

export interface ExportResponse {
  branch: string;
  commitSha: string;
  pushed: boolean;
  prUrl: string | null;
  warnings: string[];
}
