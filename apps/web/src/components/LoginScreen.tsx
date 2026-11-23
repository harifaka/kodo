import { api } from '../lib/api';
import type { AuthMeResponse } from '../types/account';
import { AlertIcon, LogoMark } from './icons';

interface LoginScreenProps {
  auth: AuthMeResponse;
}

export function LoginScreen({ auth }: LoginScreenProps) {
  const oauthReady = auth.githubOAuthConfigured;

  return (
    <div className="flex min-h-screen items-center justify-center bg-ink-950 px-4 text-slate-200">
      <div className="w-full max-w-md rounded-2xl border border-ink-700/80 bg-ink-900/70 p-8 shadow-2xl backdrop-blur">
        <div className="flex items-center gap-3">
          <LogoMark />
          <div className="leading-tight">
            <div className="text-lg font-semibold tracking-tight text-white">Kodo</div>
            <div className="text-[10px] uppercase tracking-[0.2em] text-slate-500">
              Architecture Control Center
            </div>
          </div>
        </div>

        <p className="mt-6 text-sm leading-relaxed text-slate-300">
          Sign in with GitHub to open your own isolated workspaces. Kodo never stores your GitHub
          token or any LLM API key on the server.
        </p>

        {oauthReady ? (
          <a
            href={api.githubLoginUrl()}
            className="mt-6 flex w-full items-center justify-center gap-2 rounded-lg bg-white px-4 py-2.5 text-[13px] font-semibold text-ink-950 transition hover:bg-slate-200"
          >
            <GitHubMark className="h-4 w-4" />
            Sign in with GitHub
          </a>
        ) : (
          <div className="mt-6 flex items-start gap-2 rounded-lg border border-amber-400/30 bg-amber-400/[0.08] px-3 py-2.5 text-[11px] leading-relaxed text-amber-200">
            <AlertIcon className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            <span>
              GitHub OAuth is not configured on this server. Set{' '}
              <span className="font-mono">KODO_GITHUB_CLIENT_ID</span> and{' '}
              <span className="font-mono">KODO_GITHUB_CLIENT_SECRET</span>, then restart the API.
            </span>
          </div>
        )}

        <p className="mt-6 text-center text-[10px] leading-relaxed text-slate-600">
          SaaS mode · workspaces are sandboxed per user · host Docker control disabled
        </p>
      </div>
    </div>
  );
}

function GitHubMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 16 16" aria-hidden="true" className={className} fill="currentColor">
      <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82a7.4 7.4 0 0 1 2-.27c.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8Z" />
    </svg>
  );
}
