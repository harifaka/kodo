import { useCallback, useEffect, useMemo, useState } from 'react';
import { api, ApiError } from '../lib/api';
import type { McpInfo } from '../types/mcp';
import { CheckIcon, CloseIcon, CopyIcon, DecisionIcon, Spinner } from './icons';

/**
 * Phase 15 MCP setup drawer.
 *
 * Shows the live `/mcp` status and hands out copy-paste config for Cursor, Claude Code and a local
 * stdio process. Everything on this surface is read-only: the modal never sends a mutating request.
 */

interface McpSetupModalProps {
  open: boolean;
  onClose: () => void;
}

type SnippetId = 'cursor' | 'claude' | 'stdio';

const INPUT_CLASS =
  'w-full rounded-lg border border-ink-600 bg-ink-950/80 px-2.5 py-2 font-mono text-[11px] leading-relaxed text-slate-200 outline-none focus:border-sky-500/70';

export function McpSetupModal({ open, onClose }: McpSetupModalProps) {
  const [info, setInfo] = useState<McpInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [activeSnippet, setActiveSnippet] = useState<SnippetId>('cursor');
  const [copied, setCopied] = useState<SnippetId | 'endpoint' | null>(null);

  useEffect(() => {
    if (!open) {
      return;
    }
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    api
      .mcpInfo(controller.signal)
      .then(setInfo)
      .catch((cause: unknown) => {
        if (controller.signal.aborted) {
          return;
        }
        setError(cause instanceof ApiError ? cause.message : 'Could not read the MCP status.');
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setLoading(false);
        }
      });
    return () => controller.abort();
  }, [open]);

  const endpoint = useMemo(() => {
    const origin = api.baseUrl || window.location.origin;
    return `${origin}${info?.endpointPath ?? '/mcp'}`;
  }, [info]);

  const snippets = useMemo(() => {
    const cursor: Record<string, unknown> = { url: endpoint };
    if (info?.saasRequiresAuth) {
      cursor.headers = { Authorization: 'Bearer <YOUR_SESSION_TOKEN>' };
    }
    return {
      cursor: JSON.stringify({ mcpServers: { kodo: cursor } }, null, 2),
      claude: `claude mcp add --transport http kodo ${endpoint}`,
      stdio: JSON.stringify(
        {
          mcpServers: {
            kodo: {
              command: 'python',
              args: ['-m', 'app.mcp.stdio_server'],
              cwd: 'services/api-python',
            },
          },
        },
        null,
        2,
      ),
    } satisfies Record<SnippetId, string>;
  }, [endpoint, info]);

  const copy = useCallback(async (value: string, key: SnippetId | 'endpoint') => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(key);
      window.setTimeout(() => setCopied(null), 1600);
    } catch {
      setCopied(null);
    }
  }, []);

  if (!open) {
    return null;
  }

  const enabled = info?.enabled ?? false;
  const active = snippets[activeSnippet];

  return (
    <div
      role="presentation"
      onClick={onClose}
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink-950/80 p-4 backdrop-blur-sm"
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="mcp-setup-title"
        onClick={(event) => event.stopPropagation()}
        className="max-h-[90vh] w-full max-w-[600px] overflow-y-auto rounded-xl border border-ink-600 bg-ink-900 shadow-2xl"
      >
        <div className="flex items-start gap-3 border-b border-ink-700/70 px-4 py-3">
          <DecisionIcon className="mt-0.5 h-4 w-4 shrink-0 text-sky-300" />
          <div className="min-w-0 flex-1">
            <h2 id="mcp-setup-title" className="text-[13px] font-semibold text-white">
              MCP server · AI coding agents
            </h2>
            <p className="mt-0.5 text-[10.5px] leading-relaxed text-slate-500">
              Connect Cursor, Claude Code or Windsurf to Kodo&apos;s architecture intelligence.
              Every tool is <span className="text-sky-200">strictly read-only</span>: nothing can be
              applied, rolled back or deployed from an agent.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close MCP setup"
            className="rounded p-1 text-slate-500 transition hover:bg-ink-700/60 hover:text-slate-200"
          >
            <CloseIcon className="h-4 w-4" />
          </button>
        </div>

        <div className="space-y-3 px-4 py-3">
          {loading && (
            <div className="flex items-center gap-2 text-[11px] text-slate-400">
              <Spinner className="h-3.5 w-3.5 text-sky-300" />
              Reading /api/v1/mcp/info…
            </div>
          )}

          {error && (
            <p className="rounded-md border border-rose-500/30 bg-rose-500/[0.07] px-2.5 py-2 text-[10.5px] text-rose-200">
              {error}
            </p>
          )}

          {info && (
            <>
              <div className="flex flex-wrap items-center gap-2">
                <span
                  className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[10.5px] font-medium ${
                    enabled
                      ? 'border-emerald-400/30 bg-emerald-400/[0.08] text-emerald-200'
                      : 'border-rose-500/30 bg-rose-500/[0.08] text-rose-200'
                  }`}
                >
                  <span
                    className={`h-1.5 w-1.5 rounded-full ${enabled ? 'bg-emerald-400' : 'bg-rose-500'}`}
                  />
                  {enabled ? 'Enabled' : 'Disabled (KODO_MCP_ENABLED=false)'}
                </span>
                <span className="rounded-full border border-ink-600 bg-ink-850/70 px-2.5 py-1 text-[10.5px] text-slate-300">
                  {info.protocol}
                </span>
                <span className="rounded-full border border-ink-600 bg-ink-850/70 px-2.5 py-1 text-[10.5px] text-slate-300">
                  {info.toolCount} read-only tools
                </span>
                <span className="rounded-full border border-ink-600 bg-ink-850/70 px-2.5 py-1 text-[10.5px] text-slate-300">
                  {info.mode} mode
                </span>
                {info.mode === 'saas' && (
                  <span className="rounded-full border border-ink-600 bg-ink-850/70 px-2.5 py-1 text-[10.5px] text-slate-300">
                    {info.rateLimitPerMinute}/min
                  </span>
                )}
              </div>

              <label className="block">
                <span className="mb-1 flex items-center justify-between text-[9.5px] font-semibold uppercase tracking-[0.14em] text-slate-500">
                  Endpoint
                  <button
                    type="button"
                    onClick={() => void copy(endpoint, 'endpoint')}
                    className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[9.5px] font-medium normal-case tracking-normal text-sky-300 transition hover:bg-sky-500/10"
                  >
                    {copied === 'endpoint' ? <CheckIcon className="h-3 w-3" /> : <CopyIcon className="h-3 w-3" />}
                    {copied === 'endpoint' ? 'Copied' : 'Copy'}
                  </button>
                </span>
                <input readOnly value={endpoint} spellCheck={false} className={INPUT_CLASS} />
              </label>

              <div className="grid grid-cols-3 gap-1.5">
                {(
                  [
                    ['cursor', 'Cursor'],
                    ['claude', 'Claude Code'],
                    ['stdio', 'Local stdio'],
                  ] as const
                ).map(([id, label]) => (
                  <button
                    key={id}
                    type="button"
                    onClick={() => setActiveSnippet(id)}
                    className={`rounded-lg border px-2 py-1.5 text-[10.5px] font-medium transition ${
                      activeSnippet === id
                        ? 'border-sky-400/60 bg-sky-400/10 text-sky-100'
                        : 'border-ink-600 bg-ink-950/50 text-slate-400 hover:border-sky-400/40 hover:text-slate-200'
                    }`}
                  >
                    {label}
                  </button>
                ))}
              </div>

              <div className="rounded-lg border border-ink-700/70 bg-ink-950/60">
                <div className="flex items-center justify-between border-b border-ink-700/60 px-2.5 py-1.5">
                  <span className="font-mono text-[9.5px] text-slate-500">
                    {activeSnippet === 'cursor'
                      ? '.cursor/mcp.json'
                      : activeSnippet === 'claude'
                        ? 'terminal'
                        : 'python -m app.mcp.stdio_server'}
                  </span>
                  <button
                    type="button"
                    onClick={() => void copy(active, activeSnippet)}
                    className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[9.5px] text-sky-300 transition hover:bg-sky-500/10"
                  >
                    {copied === activeSnippet ? <CheckIcon className="h-3 w-3" /> : <CopyIcon className="h-3 w-3" />}
                    {copied === activeSnippet ? 'Copied' : 'Copy'}
                  </button>
                </div>
                <pre className="max-h-56 overflow-auto px-2.5 py-2 font-mono text-[10.5px] leading-relaxed text-slate-300">
                  {active}
                </pre>
              </div>

              {activeSnippet === 'stdio' && (
                <p className="text-[9.5px] leading-relaxed text-slate-500">
                  The stdio bridge runs in local-user context and logs to stderr only, so stdout stays
                  a clean JSON-RPC channel. It shares the exact same read-only tool registry as
                  <span className="font-mono text-slate-400"> /mcp</span>.
                </p>
              )}

              {info.saasRequiresAuth && (
                <p className="rounded-md border border-amber-400/25 bg-amber-400/[0.06] px-2.5 py-2 text-[10px] leading-relaxed text-amber-200/90">
                  SaaS mode: MCP requires a session or Bearer token. Agents are strictly sandboxed to
                  the authenticated user&apos;s own workspaces — any host or foreign path is rejected
                  with <span className="font-mono">SAAS_PATH_FORBIDDEN</span>.
                </p>
              )}

              <div className="rounded-lg border border-ink-700/70 bg-ink-950/40 px-2.5 py-2">
                <p className="text-[9.5px] font-semibold uppercase tracking-[0.14em] text-slate-500">
                  Tools
                </p>
                <ul className="mt-1 space-y-1">
                  {info.tools.map((tool) => (
                    <li key={tool.name} className="flex items-start gap-2 text-[10px] leading-relaxed">
                      <span className="mt-1 h-1 w-1 shrink-0 rounded-full bg-emerald-400" />
                      <span className="min-w-0">
                        <span className="font-mono text-slate-200">{tool.name}</span>
                        <span className="text-slate-500"> — {tool.description.split('. ')[0]}.</span>
                      </span>
                    </li>
                  ))}
                </ul>
              </div>

              <p className="text-[9.5px] leading-relaxed text-slate-600">
                Supported protocol versions: {info.protocolVersions.join(', ')}. Transports:{' '}
                {info.transports.join(', ')}. Zero-write contract:{' '}
                <span className="font-mono text-slate-500">readOnlyHint: true</span>,{' '}
                <span className="font-mono text-slate-500">destructiveHint: false</span>.
              </p>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
