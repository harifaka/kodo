import type {
  AuditReport,
  ComponentNode,
  ComponentRelation,
  FileContent,
  HealthResponse,
  WorkspaceIR,
} from '../types/core-ir';
import type {
  ApplyRequest,
  ApplyResponse,
  DryRunResponse,
  GitStatus,
  PatchOperation,
  RollbackResponse,
} from '../types/patching';
import type { BlueprintResponse, ScaffoldRequest } from '../types/blueprint';
import type {
  AuditLogResponse,
  CloneRequest,
  CloneResponse,
  ComposeLogs,
  ComposeResult,
  DeployDryRunRequest,
  DockerStatus,
  ExportRequest,
  ExportResponse,
} from '../types/deploy';
import type {
  AiPatchResponse,
  AuditFixRequest,
  ImplementMethodRequest,
  LlmOverride,
  SpecToBlueprintRequest,
  SpecToBlueprintResponse,
  TestConnectionResponse,
} from '../types/ai';
import type {
  AuthMeResponse,
  BlueprintListResponse,
  DeleteWorkspaceResponse,
  UserSettingsResponse,
  WorkspaceListResponse,
} from '../types/account';
import type {
  BuildResult,
  BuildVerifyRequest,
  BuilderStatus,
  FixBuildErrorsRequest,
  FixBuildErrorsResponse,
} from '../types/build';
import type {
  DecisionFeedbackRequest,
  DecisionListResponse,
  DecisionRecordSummary,
  RouteTaskRequest,
  RouteTaskResponse,
  ScreenDiffRequest,
  ScreenDiffResponse,
  SystemOneOverride,
  SystemOneTestResponse,
  TriageAuditRequest,
  TriageAuditResponse,
} from '../types/decision';

// Docker/Nginx serves the UI and the API on one origin, so production builds default to relative
// paths (`/api/v1/...`, `/health`) unless VITE_API_BASE_URL is set at build time.
const CONFIGURED_API_BASE = (import.meta.env.VITE_API_BASE_URL ?? '').trim().replace(/\/+$/, '');
const DEFAULT_DEV_API_BASE = 'http://localhost:8088';
const API_BASE = CONFIGURED_API_BASE || (import.meta.env.PROD ? '' : DEFAULT_DEV_API_BASE);
const API_BASE_LABEL = API_BASE || 'same origin';

export class ApiError extends Error {
  readonly status: number;
  /** Structured error code for apply/rollback rejections (e.g. `STALE_FILE`). */
  readonly code?: string;
  /** Raw structured `detail` payload returned by the API, when it is an object. */
  readonly detail?: Record<string, unknown>;

  constructor(
    message: string,
    status: number,
    code?: string,
    detail?: Record<string, unknown>,
  ) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.detail = detail;
  }
}

async function toApiError(response: Response): Promise<ApiError> {
  const body = (await response.json().catch(() => null)) as { detail?: unknown } | null;
  const detail = body?.detail;

  if (detail && typeof detail === 'object') {
    const record = detail as Record<string, unknown>;
    const message =
      typeof record.message === 'string' ? record.message : `Request failed with status ${response.status}`;
    const code = typeof record.code === 'string' ? record.code : undefined;
    return new ApiError(message, response.status, code, record);
  }

  const message = typeof detail === 'string' ? detail : `Request failed with status ${response.status}`;
  return new ApiError(message, response.status);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      // GitHub OAuth session cookies are HttpOnly; every call must carry them.
      credentials: 'include',
      headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
    });
  } catch {
    throw new ApiError(`Kodo API is unreachable at ${API_BASE_LABEL}. Is the FastAPI service running?`, 0);
  }

  if (!response.ok) {
    throw await toApiError(response);
  }

  return (await response.json()) as T;
}

/** Incremental Server-Sent Events reader for the streaming build route. */
async function readEventStream(
  response: Response,
  handlers: { onLog: (line: string) => void },
): Promise<BuildResult> {
  if (!response.body) {
    throw new ApiError('The build stream is unavailable in this browser.', 0);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let result: BuildResult | null = null;
  let streamError: ApiError | null = null;

  const handleFrame = (frame: string) => {
    let event = 'message';
    const data: string[] = [];
    for (const line of frame.split('\n')) {
      if (line.startsWith('event:')) {
        event = line.slice(6).trim();
      } else if (line.startsWith('data:')) {
        data.push(line.slice(5).trimStart());
      }
    }
    if (data.length === 0) {
      return;
    }

    let payload: Record<string, unknown>;
    try {
      payload = JSON.parse(data.join('\n')) as Record<string, unknown>;
    } catch {
      return;
    }

    if (event === 'log') {
      handlers.onLog(typeof payload.line === 'string' ? payload.line : String(payload.line ?? ''));
    } else if (event === 'result') {
      result = payload as unknown as BuildResult;
    } else if (event === 'error') {
      streamError = new ApiError(
        typeof payload.message === 'string' ? payload.message : 'Build verification failed.',
        0,
        typeof payload.code === 'string' ? payload.code : 'BUILD_FAILED',
        payload,
      );
    }
  };

  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) {
        break;
      }
      buffer += decoder.decode(value, { stream: true });
      buffer = buffer.replace(/\r\n/g, '\n');
      let boundary = buffer.indexOf('\n\n');
      while (boundary !== -1) {
        handleFrame(buffer.slice(0, boundary));
        buffer = buffer.slice(boundary + 2);
        boundary = buffer.indexOf('\n\n');
      }
    }
    if (buffer.trim()) {
      handleFrame(buffer);
    }
  } finally {
    reader.releaseLock();
  }

  if (streamError) {
    throw streamError;
  }
  if (!result) {
    throw new ApiError('The build stream ended before a result arrived.', 0);
  }
  return result;
}

export const api = {
  baseUrl: API_BASE,
  baseUrlLabel: API_BASE_LABEL,

  health(signal?: AbortSignal): Promise<HealthResponse> {
    return request<HealthResponse>('/health', { signal });
  },

  fetchAuthMe(signal?: AbortSignal): Promise<AuthMeResponse> {
    return request<AuthMeResponse>('/api/v1/auth/me', { signal });
  },

  githubLoginUrl(): string {
    return `${API_BASE}/api/v1/auth/github/login`;
  },

  logout(): Promise<{ ok: boolean }> {
    return request<{ ok: boolean }>('/api/v1/auth/logout', { method: 'POST' });
  },

  fetchWorkspaces(signal?: AbortSignal): Promise<WorkspaceListResponse> {
    return request<WorkspaceListResponse>('/api/v1/workspaces', { signal });
  },

  deleteWorkspace(workspaceId: string): Promise<DeleteWorkspaceResponse> {
    return request<DeleteWorkspaceResponse>(
      `/api/v1/workspaces/${encodeURIComponent(workspaceId)}`,
      { method: 'DELETE' },
    );
  },

  blueprints(signal?: AbortSignal): Promise<BlueprintListResponse> {
    return request<BlueprintListResponse>('/api/v1/blueprints', { signal });
  },

  fetchUserSettings(signal?: AbortSignal): Promise<UserSettingsResponse> {
    return request<UserSettingsResponse>('/api/v1/user/settings', { signal });
  },

  saveUserSettings(settings: Record<string, unknown>): Promise<UserSettingsResponse> {
    return request<UserSettingsResponse>('/api/v1/user/settings', {
      method: 'PUT',
      body: JSON.stringify({ settings }),
    });
  },

  scan(path: string): Promise<WorkspaceIR> {
    return request<WorkspaceIR>('/api/v1/scan', {
      method: 'POST',
      body: JSON.stringify({ path }),
    });
  },

  file(root: string, relPath: string): Promise<FileContent> {
    const params = new URLSearchParams({ root, relPath });
    return request<FileContent>(`/api/v1/file?${params.toString()}`);
  },

  previewAudit(
    nodes: ComponentNode[],
    relations: ComponentRelation[],
    signal?: AbortSignal,
  ): Promise<AuditReport> {
    return request<AuditReport>('/api/v1/audit', {
      method: 'POST',
      body: JSON.stringify({ nodes, relations }),
      signal,
    });
  },

  dryRun(rootPath: string, operations: PatchOperation[], signal?: AbortSignal): Promise<DryRunResponse> {
    return request<DryRunResponse>('/api/v1/dry-run', {
      method: 'POST',
      body: JSON.stringify({ rootPath, operations }),
      signal,
    });
  },

  gitStatus(root: string, signal?: AbortSignal): Promise<GitStatus> {
    const params = new URLSearchParams({ root });
    return request<GitStatus>(`/api/v1/git/status?${params.toString()}`, { signal });
  },

  apply(payload: ApplyRequest): Promise<ApplyResponse> {
    return request<ApplyResponse>('/api/v1/apply', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  blueprint(root: string, signal?: AbortSignal): Promise<BlueprintResponse> {
    const params = new URLSearchParams({ root });
    return request<BlueprintResponse>(`/api/v1/blueprint?${params.toString()}`, { signal });
  },

  scaffoldDryRun(payload: ScaffoldRequest, signal?: AbortSignal): Promise<DryRunResponse> {
    return request<DryRunResponse>('/api/v1/scaffold/dry-run', {
      method: 'POST',
      body: JSON.stringify(payload),
      signal,
    });
  },

  rollback(applyId: string, force = false): Promise<RollbackResponse> {
    return request<RollbackResponse>('/api/v1/apply/rollback', {
      method: 'POST',
      body: JSON.stringify({ applyId, force }),
    });
  },

  aiTestConnection(llmConfig?: LlmOverride, signal?: AbortSignal): Promise<TestConnectionResponse> {
    return request<TestConnectionResponse>('/api/v1/ai/test-connection', {
      method: 'POST',
      body: JSON.stringify({ llmConfig }),
      signal,
    });
  },

  aiSpecToBlueprint(payload: SpecToBlueprintRequest, signal?: AbortSignal): Promise<SpecToBlueprintResponse> {
    return request<SpecToBlueprintResponse>('/api/v1/ai/spec-to-blueprint', {
      method: 'POST',
      body: JSON.stringify(payload),
      signal,
    });
  },

  aiAuditFix(payload: AuditFixRequest, signal?: AbortSignal): Promise<AiPatchResponse> {
    return request<AiPatchResponse>('/api/v1/ai/audit-fix', {
      method: 'POST',
      body: JSON.stringify(payload),
      signal,
    });
  },

  aiImplementMethod(payload: ImplementMethodRequest, signal?: AbortSignal): Promise<AiPatchResponse> {
    return request<AiPatchResponse>('/api/v1/ai/implement-method', {
      method: 'POST',
      body: JSON.stringify(payload),
      signal,
    });
  },

  deployDryRun(payload: DeployDryRunRequest, signal?: AbortSignal): Promise<DryRunResponse> {
    return request<DryRunResponse>('/api/v1/deploy/dry-run', {
      method: 'POST',
      body: JSON.stringify(payload),
      signal,
    });
  },

  dockerStatus(root: string, signal?: AbortSignal): Promise<DockerStatus> {
    const params = new URLSearchParams({ root });
    return request<DockerStatus>(`/api/v1/deploy/docker/status?${params.toString()}`, { signal });
  },

  dockerUp(rootPath: string, build: boolean): Promise<ComposeResult> {
    return request<ComposeResult>('/api/v1/deploy/docker/up', {
      method: 'POST',
      body: JSON.stringify({ rootPath, build }),
    });
  },

  dockerDown(rootPath: string, removeVolumes: boolean): Promise<ComposeResult> {
    return request<ComposeResult>('/api/v1/deploy/docker/down', {
      method: 'POST',
      body: JSON.stringify({ rootPath, removeVolumes }),
    });
  },

  dockerLogs(
    root: string,
    service: string | null,
    tail: number,
    signal?: AbortSignal,
  ): Promise<ComposeLogs> {
    const params = new URLSearchParams({ root, tail: String(tail) });
    if (service) {
      params.set('service', service);
    }
    return request<ComposeLogs>(`/api/v1/deploy/docker/logs?${params.toString()}`, { signal });
  },

  auditLog(limit = 100, signal?: AbortSignal): Promise<AuditLogResponse> {
    const params = new URLSearchParams({ limit: String(limit) });
    return request<AuditLogResponse>(`/api/v1/audit-log?${params.toString()}`, { signal });
  },

  gitClone(payload: CloneRequest, signal?: AbortSignal): Promise<CloneResponse> {
    return request<CloneResponse>('/api/v1/git/clone', {
      method: 'POST',
      body: JSON.stringify(payload),
      signal,
    });
  },

  gitExport(payload: ExportRequest, signal?: AbortSignal): Promise<ExportResponse> {
    return request<ExportResponse>('/api/v1/git/export', {
      method: 'POST',
      body: JSON.stringify(payload),
      signal,
    });
  },

  buildStatus(signal?: AbortSignal): Promise<BuilderStatus> {
    return request<BuilderStatus>('/api/v1/build/status', { signal });
  },

  buildVerify(payload: BuildVerifyRequest, signal?: AbortSignal): Promise<BuildResult> {
    return request<BuildResult>('/api/v1/build/verify', {
      method: 'POST',
      body: JSON.stringify(payload),
      signal,
    });
  },

  /** Stream a sandbox build: log lines arrive live, the resolved promise carries the result. */
  async buildVerifyStream(
    payload: BuildVerifyRequest,
    handlers: { onLog: (line: string) => void; signal?: AbortSignal },
  ): Promise<BuildResult> {
    let response: Response;
    try {
      response = await fetch(`${API_BASE}/api/v1/build/verify/stream`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
        body: JSON.stringify(payload),
        signal: handlers.signal,
      });
    } catch (reason) {
      if (reason instanceof DOMException && reason.name === 'AbortError') {
        throw reason;
      }
      throw new ApiError(`Kodo API is unreachable at ${API_BASE_LABEL}. Is the FastAPI service running?`, 0);
    }

    if (!response.ok) {
      throw await toApiError(response);
    }
    return readEventStream(response, handlers);
  },

  aiFixBuildErrors(payload: FixBuildErrorsRequest, signal?: AbortSignal): Promise<FixBuildErrorsResponse> {
    return request<FixBuildErrorsResponse>('/api/v1/ai/fix-build-errors', {
      method: 'POST',
      body: JSON.stringify(payload),
      signal,
    });
  },

  systemOneTestConnection(
    systemOneConfig?: SystemOneOverride,
    signal?: AbortSignal,
  ): Promise<SystemOneTestResponse> {
    return request<SystemOneTestResponse>('/api/v1/decision/test-connection', {
      method: 'POST',
      body: JSON.stringify({ systemOneConfig }),
      signal,
    });
  },

  decisionTriageAudit(
    payload: TriageAuditRequest,
    signal?: AbortSignal,
  ): Promise<TriageAuditResponse> {
    return request<TriageAuditResponse>('/api/v1/decision/triage-audit', {
      method: 'POST',
      body: JSON.stringify(payload),
      signal,
    });
  },

  decisionRouteTask(payload: RouteTaskRequest, signal?: AbortSignal): Promise<RouteTaskResponse> {
    return request<RouteTaskResponse>('/api/v1/decision/route-task', {
      method: 'POST',
      body: JSON.stringify(payload),
      signal,
    });
  },

  decisionScreenDiff(payload: ScreenDiffRequest, signal?: AbortSignal): Promise<ScreenDiffResponse> {
    return request<ScreenDiffResponse>('/api/v1/decision/screen-diff', {
      method: 'POST',
      body: JSON.stringify(payload),
      signal,
    });
  },

  decisions(
    params: { rootPath?: string; decisionType?: string; limit?: number } = {},
    signal?: AbortSignal,
  ): Promise<DecisionListResponse> {
    const query = new URLSearchParams();
    if (params.rootPath) {
      query.set('rootPath', params.rootPath);
    }
    if (params.decisionType) {
      query.set('decisionType', params.decisionType);
    }
    query.set('limit', String(params.limit ?? 50));
    return request<DecisionListResponse>(`/api/v1/decisions?${query.toString()}`, { signal });
  },

  decisionFeedback(
    adrId: string,
    payload: DecisionFeedbackRequest,
  ): Promise<DecisionRecordSummary> {
    return request<DecisionRecordSummary>(
      `/api/v1/decisions/${encodeURIComponent(adrId)}/feedback`,
      { method: 'POST', body: JSON.stringify(payload) },
    );
  },

  /** JSONL download of accepted/overridden ADRs for local Laya calibration. */
  async decisionExportTraining(): Promise<string> {
    let response: Response;
    try {
      response = await fetch(`${API_BASE}/api/v1/decisions/export-training`, {
        credentials: 'include',
      });
    } catch {
      throw new ApiError(`Kodo API is unreachable at ${API_BASE_LABEL}. Is the FastAPI service running?`, 0);
    }
    if (!response.ok) {
      throw await toApiError(response);
    }
    return response.text();
  },
};
