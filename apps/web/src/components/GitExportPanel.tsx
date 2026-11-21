import { useState } from 'react';
import { api } from '../lib/api';
import type { CloneResponse, ExportResponse } from '../types/deploy';
import { AlertIcon, CheckIcon, ExternalIcon, Spinner } from './icons';

interface GitExportPanelProps {
  rootPath: string;
  /** Hands the cloned workspace to the app so it can scan it immediately. */
  onWorkspaceCloned: (localPath: string) => void;
  /** Bumped so the audit table re-reads the JSONL log after a Git action. */
  onChanged: () => void;
}

const DEFAULT_BRANCH = 'kodo/deploy-studio';
const DEFAULT_MESSAGE = 'Add Kodo-generated container artifacts';

export function GitExportPanel({ rootPath, onWorkspaceCloned, onChanged }: GitExportPanelProps) {
  const [repoUrl, setRepoUrl] = useState('');
  const [cloneBranch, setCloneBranch] = useState('');
  const [cloneToken, setCloneToken] = useState('');
  const [cloning, setCloning] = useState(false);
  const [cloneError, setCloneError] = useState<string | null>(null);
  const [cloneResult, setCloneResult] = useState<CloneResponse | null>(null);

  const [branchName, setBranchName] = useState(DEFAULT_BRANCH);
  const [commitMessage, setCommitMessage] = useState(DEFAULT_MESSAGE);
  const [createPr, setCreatePr] = useState(false);
  const [prTitle, setPrTitle] = useState('Deploy Studio: container artifacts');
  const [prBody, setPrBody] = useState('Generated Dockerfile, docker-compose.yml and .env.example via Kodo.');
  const [exportToken, setExportToken] = useState('');
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);
  const [exportResult, setExportResult] = useState<ExportResponse | null>(null);

  const clone = async () => {
    setCloning(true);
    setCloneError(null);
    setCloneResult(null);
    try {
      const result = await api.gitClone({
        repoUrl: repoUrl.trim(),
        branch: cloneBranch.trim() || undefined,
        token: cloneToken.trim() || undefined,
      });
      setCloneResult(result);
      setCloneToken('');
      onChanged();
      onWorkspaceCloned(result.localPath);
    } catch (reason) {
      setCloneError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setCloning(false);
    }
  };

  const exportBranch = async () => {
    setExporting(true);
    setExportError(null);
    setExportResult(null);
    try {
      const result = await api.gitExport({
        rootPath,
        branchName: branchName.trim(),
        commitMessage: commitMessage.trim(),
        createPr,
        prTitle: createPr ? prTitle.trim() || undefined : undefined,
        prBody: createPr ? prBody.trim() || undefined : undefined,
        token: createPr ? exportToken.trim() || undefined : undefined,
      });
      setExportResult(result);
      if (result.pushed) {
        setExportToken('');
      }
      onChanged();
    } catch (reason) {
      setExportError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setExporting(false);
    }
  };

  return (
    <section className="space-y-3 rounded-lg border border-ink-700/70 bg-ink-900/40 px-3 py-2.5">
      <div className="flex items-center gap-2">
        <p className="text-[11.5px] font-semibold text-slate-100">Git Export &amp; Remote</p>
        <span className="rounded border border-ink-600 bg-ink-850 px-1.5 py-0.5 text-[9px] text-slate-400">
          token in memory only
        </span>
      </div>

      <div className="space-y-1.5">
        <p className="text-[9px] font-semibold uppercase tracking-[0.14em] text-slate-500">
          Clone remote repo
        </p>
        <div className="flex flex-wrap items-center gap-1.5">
          <input
            value={repoUrl}
            onChange={(event) => setRepoUrl(event.target.value)}
            placeholder="https://github.com/owner/repo"
            spellCheck={false}
            className={INPUT_CLASS + ' min-w-[220px] flex-1'}
            aria-label="Remote repository URL"
          />
          <input
            value={cloneBranch}
            onChange={(event) => setCloneBranch(event.target.value)}
            placeholder="branch (optional)"
            spellCheck={false}
            className={INPUT_CLASS + ' w-[140px]'}
            aria-label="Clone branch"
          />
          <input
            value={cloneToken}
            onChange={(event) => setCloneToken(event.target.value)}
            type="password"
            autoComplete="off"
            placeholder="token (optional)"
            className={INPUT_CLASS + ' w-[150px]'}
            aria-label="GitHub or GitLab token"
          />
          <button
            type="button"
            onClick={() => void clone()}
            disabled={cloning || repoUrl.trim().length === 0}
            className="flex items-center gap-1 rounded-md border border-sky-400/50 bg-sky-400/10 px-2 py-1 text-[10px] font-medium text-sky-100 transition enabled:hover:bg-sky-400/20 disabled:opacity-40"
          >
            {cloning ? <Spinner className="h-3 w-3" /> : null}
            Clone &amp; Scan
          </button>
        </div>
        <p className="text-[9px] leading-relaxed text-slate-600">
          HTTPS GitHub/GitLab only. Kodo shallow-clones into its own workspaces directory and never
          stores the token in <span className="font-mono">.git/config</span>.
        </p>
        {cloneError && <Feedback tone="error" text={cloneError} />}
        {cloneResult && (
          <Feedback
            tone="ok"
            text={`Cloned ${cloneResult.repoUrl} (${cloneResult.branch ?? 'default branch'}) into your Kodo workspaces folder — scanning it now.`}
          />
        )}
      </div>

      <div className="space-y-1.5 border-t border-ink-700/60 pt-2">
        <p className="text-[9px] font-semibold uppercase tracking-[0.14em] text-slate-500">
          Branch &amp; commit export
        </p>
        <div className="flex flex-wrap items-center gap-1.5">
          <input
            value={branchName}
            onChange={(event) => setBranchName(event.target.value)}
            placeholder="branch name"
            spellCheck={false}
            className={INPUT_CLASS + ' w-[170px] font-mono'}
            aria-label="Export branch name"
          />
          <input
            value={commitMessage}
            onChange={(event) => setCommitMessage(event.target.value)}
            placeholder="commit message"
            className={INPUT_CLASS + ' min-w-[200px] flex-1'}
            aria-label="Commit message"
          />
          <button
            type="button"
            onClick={() => void exportBranch()}
            disabled={exporting || branchName.trim().length === 0 || commitMessage.trim().length === 0}
            className="flex items-center gap-1 rounded-md border border-emerald-400/50 bg-emerald-400/10 px-2 py-1 text-[10px] font-medium text-emerald-100 transition enabled:hover:bg-emerald-400/20 disabled:opacity-40"
          >
            {exporting ? <Spinner className="h-3 w-3" /> : null}
            Export Branch + Commit
          </button>
        </div>

        <label className="flex items-center gap-1.5 text-[10px] text-slate-300">
          <input
            type="checkbox"
            checked={createPr}
            onChange={(event) => setCreatePr(event.target.checked)}
            className="h-3 w-3 rounded border-ink-600 bg-ink-950 accent-emerald-400"
          />
          Push and open a GitHub Pull Request (needs a session-only token)
        </label>

        {createPr && (
          <div className="space-y-1.5">
            <div className="flex flex-wrap items-center gap-1.5">
              <input
                value={prTitle}
                onChange={(event) => setPrTitle(event.target.value)}
                placeholder="pull request title"
                className={INPUT_CLASS + ' min-w-[200px] flex-1'}
                aria-label="Pull request title"
              />
              <input
                value={exportToken}
                onChange={(event) => setExportToken(event.target.value)}
                type="password"
                autoComplete="off"
                placeholder="GitHub token (repo scope)"
                className={INPUT_CLASS + ' w-[190px]'}
                aria-label="GitHub token for the pull request"
              />
            </div>
            <textarea
              value={prBody}
              onChange={(event) => setPrBody(event.target.value)}
              rows={2}
              placeholder="pull request description"
              className={INPUT_CLASS + ' w-full resize-none'}
              aria-label="Pull request description"
            />
          </div>
        )}

        {exportError && <Feedback tone="error" text={exportError} />}
        {exportResult && (
          <div className="rounded-md border border-emerald-400/25 bg-emerald-400/[0.06] px-2 py-1.5">
            <p className="flex flex-wrap items-center gap-1.5 text-[10px] text-emerald-100">
              <CheckIcon className="h-3 w-3" />
              <span className="font-mono">{exportResult.branch}</span>
              <span className="font-mono text-emerald-300/70">{exportResult.commitSha.slice(0, 7)}</span>
              <span>{exportResult.pushed ? '· pushed' : '· local only'}</span>
              {exportResult.prUrl && (
                <a
                  href={exportResult.prUrl}
                  target="_blank"
                  rel="noreferrer noopener"
                  className="inline-flex items-center gap-1 rounded border border-emerald-400/40 px-1.5 py-0.5 text-emerald-200 transition hover:bg-emerald-400/10"
                >
                  Open pull request <ExternalIcon className="h-3 w-3" />
                </a>
              )}
            </p>
            {exportResult.warnings.map((warning) => (
              <p key={warning} className="mt-1 flex items-start gap-1 text-[9.5px] leading-relaxed text-amber-200/90">
                <AlertIcon className="mt-0.5 h-3 w-3 shrink-0" />
                {warning}
              </p>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}

const INPUT_CLASS =
  'rounded-md border border-ink-700 bg-ink-950/80 px-2 py-1 text-[11px] text-slate-200 outline-none transition placeholder:text-slate-600 focus:border-sky-500/60';

function Feedback({ tone, text }: { tone: 'ok' | 'error'; text: string }) {
  return (
    <p
      className={`flex items-start gap-1.5 rounded-md border px-2 py-1 text-[10px] leading-relaxed ${
        tone === 'ok'
          ? 'border-emerald-400/25 bg-emerald-400/[0.06] text-emerald-200'
          : 'border-rose-400/25 bg-rose-400/[0.06] text-rose-200'
      }`}
    >
      {tone === 'ok' ? (
        <CheckIcon className="mt-0.5 h-3 w-3 shrink-0" />
      ) : (
        <AlertIcon className="mt-0.5 h-3 w-3 shrink-0" />
      )}
      {text}
    </p>
  );
}
