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

const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8088').replace(/\/+$/, '');

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

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
      ...init,
    });
  } catch {
    throw new ApiError(`Kodo API is unreachable at ${API_BASE}. Is the FastAPI service running?`, 0);
  }

  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as { detail?: unknown } | null;
    const detail = body?.detail;

    if (detail && typeof detail === 'object') {
      const record = detail as Record<string, unknown>;
      const message =
        typeof record.message === 'string' ? record.message : `Request failed with status ${response.status}`;
      const code = typeof record.code === 'string' ? record.code : undefined;
      throw new ApiError(message, response.status, code, record);
    }

    const message = typeof detail === 'string' ? detail : `Request failed with status ${response.status}`;
    throw new ApiError(message, response.status);
  }

  return (await response.json()) as T;
}

export const api = {
  baseUrl: API_BASE,

  health(signal?: AbortSignal): Promise<HealthResponse> {
    return request<HealthResponse>('/health', { signal });
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

  rollback(applyId: string, force = false): Promise<RollbackResponse> {
    return request<RollbackResponse>('/api/v1/apply/rollback', {
      method: 'POST',
      body: JSON.stringify({ applyId, force }),
    });
  },
};
