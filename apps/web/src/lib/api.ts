import type {
  AuditReport,
  ComponentNode,
  ComponentRelation,
  FileContent,
  HealthResponse,
  WorkspaceIR,
} from '../types/core-ir';
import type { DryRunResponse, PatchOperation } from '../types/patching';

const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8088').replace(/\/+$/, '');

export class ApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
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
    const detail = await response.json().catch(() => null);
    const message =
      typeof detail?.detail === 'string'
        ? detail.detail
        : `Request failed with status ${response.status}`;
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
};
