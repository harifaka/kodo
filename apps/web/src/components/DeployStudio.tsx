import { useMemo, useState } from 'react';
import { api } from '../lib/api';
import {
  BACKING_SERVICE_OPTIONS,
  DEPLOY_STACK_OPTIONS,
  detectedDeployStack,
  stackOption,
} from '../lib/deploy';
import type { PlanPreview } from '../types/ai';
import type { BackingServiceId, DeployStackId } from '../types/deploy';
import { AuditLogPanel } from './AuditLogPanel';
import { DockerControlPanel } from './DockerControlPanel';
import { GitExportPanel } from './GitExportPanel';
import { AlertIcon, DeployIcon, DiffIcon, Spinner } from './icons';

interface DeployStudioProps {
  rootPath: string;
  /** Workspace name from the Core IR, used as the default project/compose name. */
  workspaceName: string;
  detectedStacks: string[];
  /** `saas` hides host Docker control; generation and Git export stay available. */
  mode?: string;
  /** Bumped after an apply/rollback so the Docker panel re-reads container state. */
  revision?: number;
  onPreviewReady: (preview: PlanPreview) => void;
  /** Receives the local path of a cloned remote repository so the app can scan it. */
  onWorkspaceCloned: (localPath: string) => void;
}

type StackChoice = DeployStackId | 'auto';

export function DeployStudio({
  rootPath,
  workspaceName,
  detectedStacks,
  mode = 'local',
  revision = 0,
  onPreviewReady,
  onWorkspaceCloned,
}: DeployStudioProps) {
  const detected = useMemo(() => detectedDeployStack(detectedStacks), [detectedStacks]);
  const [stack, setStack] = useState<StackChoice>(detected);
  const [projectName, setProjectName] = useState(workspaceName);
  const [appPort, setAppPort] = useState(() => String(initialPort(detected)));
  const [backingServices, setBackingServices] = useState<BackingServiceId[]>(['postgres']);
  const [overwriteExisting, setOverwriteExisting] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [auditNonce, setAuditNonce] = useState(0);

  const changeStack = (next: StackChoice) => {
    const previousDefault = initialPort(stack);
    const nextDefault = initialPort(next);
    setStack(next);
    if (appPort.trim() === '' || appPort.trim() === String(previousDefault) || next === 'auto') {
      setAppPort(String(nextDefault));
    }
  };

  const toggleBackingService = (service: BackingServiceId) => {
    setBackingServices((current) =>
      current.includes(service) ? current.filter((entry) => entry !== service) : [...current, service],
    );
  };

  const preview = async () => {
    const name = projectName.trim();
    if (!name) {
      setError('Project name is required (it becomes the compose project and image name).');
      return;
    }
    const port = Number(appPort);
    if (!Number.isInteger(port) || port < 1 || port > 65535) {
      setError('App port must be an integer between 1 and 65535.');
      return;
    }

    setBusy(true);
    setError(null);
    try {
      const response = await api.deployDryRun({
        rootPath,
        projectName: name,
        stack,
        appPort: port,
        backingServices,
        overwriteExisting,
      });
      const label = stack === 'auto' ? `Auto-detected · ${name}` : `${stackOption(stack).label} · ${name}`;
      onPreviewReady({ response, label, kind: 'deploy' });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  };

  const bumpAudit = () => setAuditNonce((value) => value + 1);
  const target = stack === 'auto' ? null : stackOption(stack);

  return (
    <div className="h-full min-h-0 overflow-y-auto bg-ink-950">
      <div className="border-b border-ink-700/70 bg-ink-900/40 px-4 py-2.5">
        <div className="flex flex-wrap items-center gap-2">
          <DeployIcon className="h-4 w-4 text-sky-400" />
          <p className="text-[12px] font-semibold text-slate-100">Deploy Studio</p>
          <span className="rounded border border-ink-600 bg-ink-850 px-1.5 py-0.5 text-[9px] text-slate-400">
            Phase 6 · Docker + Git
          </span>
          {detectedStacks.length > 0 && (
            <span className="rounded border border-sky-400/30 bg-sky-400/[0.07] px-1.5 py-0.5 text-[9px] text-sky-200">
              detected: {detectedStacks.join(', ')}
            </span>
          )}
          <p className="ml-auto text-[9.5px] text-slate-500">
            Everything lands on disk through Dry-Run → Monaco Diff → guarded Apply → Rollback.
          </p>
        </div>
      </div>

      <div className="grid gap-3 p-4 xl:grid-cols-2">
        <div className="space-y-3">
          <section className="rounded-lg border border-ink-700/70 bg-ink-900/40">
            <header className="flex flex-wrap items-center gap-2 border-b border-ink-700/60 px-3 py-2">
              <p className="text-[11.5px] font-semibold text-slate-100">Docker Generator</p>
              <span className="rounded border border-ink-600 bg-ink-850 px-1.5 py-0.5 font-mono text-[9px] text-slate-400">
                {target ? `${target.short} · ${target.healthPath}` : 'auto-detect'}
              </span>
              <button
                type="button"
                onClick={() => void preview()}
                disabled={busy}
                className="ml-auto flex items-center gap-1.5 rounded-md border border-sky-400/50 bg-sky-400/10 px-2.5 py-1 text-[10.5px] font-medium text-sky-100 transition enabled:hover:bg-sky-400/20 disabled:opacity-50"
              >
                {busy ? <Spinner className="h-3 w-3" /> : <DiffIcon className="h-3 w-3" />}
                {busy ? 'Generating…' : 'Preview Docker Files (Dry-Run)'}
              </button>
            </header>

            <div className="space-y-2.5 px-3 py-2.5">
              <div className="flex flex-wrap items-center gap-2">
                <div className="flex items-center gap-0.5 rounded-md border border-ink-700 p-0.5">
                  <StackChip
                    active={stack === 'auto'}
                    label="Auto"
                    onClick={() => changeStack('auto')}
                  />
                  {DEPLOY_STACK_OPTIONS.map((option) => (
                    <StackChip
                      key={option.id}
                      active={stack === option.id}
                      label={option.short}
                      title={option.label}
                      onClick={() => changeStack(option.id)}
                    />
                  ))}
                </div>

                <label className="flex min-w-[170px] flex-1 flex-col gap-0.5">
                  <span className="text-[9px] uppercase tracking-[0.12em] text-slate-500">Project name</span>
                  <input
                    value={projectName}
                    onChange={(event) => setProjectName(event.target.value)}
                    spellCheck={false}
                    className={INPUT_CLASS}
                    aria-label="Project name"
                  />
                </label>

                <label className="flex w-[110px] flex-col gap-0.5">
                  <span className="text-[9px] uppercase tracking-[0.12em] text-slate-500">App port</span>
                  <input
                    value={appPort}
                    onChange={(event) => setAppPort(event.target.value.replace(/[^0-9]/g, ''))}
                    inputMode="numeric"
                    className={INPUT_CLASS + ' font-mono'}
                    aria-label="Application port"
                  />
                </label>
              </div>

              <div className="flex flex-wrap items-center gap-2">
                <span className="text-[9px] uppercase tracking-[0.12em] text-slate-500">Backing services</span>
                {BACKING_SERVICE_OPTIONS.map((option) => {
                  const active = backingServices.includes(option.id);
                  return (
                    <button
                      key={option.id}
                      type="button"
                      onClick={() => toggleBackingService(option.id)}
                      aria-pressed={active}
                      title={option.hint}
                      className={`rounded-md border px-2 py-1 text-[10px] transition ${
                        active
                          ? 'border-emerald-400/50 bg-emerald-400/10 text-emerald-100'
                          : 'border-ink-700 text-slate-400 hover:border-ink-600 hover:text-slate-200'
                      }`}
                    >
                      {option.label}
                    </button>
                  );
                })}
              </div>

              <label className="flex items-start gap-1.5 text-[10px] leading-relaxed text-slate-300">
                <input
                  type="checkbox"
                  checked={overwriteExisting}
                  onChange={(event) => setOverwriteExisting(event.target.checked)}
                  className="mt-0.5 h-3 w-3 rounded border-ink-600 bg-ink-950 accent-amber-400"
                />
                <span>
                  Overwrite existing files
                  <span className="block text-[9px] text-slate-500">
                    Off: create-only patches (existing files cause 409 FILE_EXISTS). On: SHA-256 verified
                    replacement through the same guarded apply.
                  </span>
                </span>
              </label>

              {stack === 'csharp-wpf' && (
                <p className="flex items-start gap-1.5 rounded-md border border-amber-400/25 bg-amber-400/[0.06] px-2 py-1.5 text-[10px] leading-relaxed text-amber-200">
                  <AlertIcon className="mt-0.5 h-3 w-3 shrink-0" />
                  WPF is a Windows-only desktop UI: Kodo generates a sidecar/API compose template plus a
                  clear warning instead of an unusable Linux image.
                </p>
              )}

              {error && (
                <p className="flex items-start gap-1.5 rounded-md border border-rose-400/25 bg-rose-400/[0.06] px-2 py-1.5 text-[10px] leading-relaxed text-rose-200">
                  <AlertIcon className="mt-0.5 h-3 w-3 shrink-0" />
                  {error}
                </p>
              )}

              <p className="text-[9px] leading-relaxed text-slate-600">
                Generates a non-root multi-stage <span className="font-mono">Dockerfile</span>,{' '}
                <span className="font-mono">.dockerignore</span>,{' '}
                <span className="font-mono">docker-compose.yml</span> (healthchecks +{' '}
                <span className="font-mono">kodo-net</span>) and a placeholder-only{' '}
                <span className="font-mono">.env.example</span>.
              </p>
            </div>
          </section>

          {mode === 'saas' ? (
            <section className="rounded-lg border border-sky-400/25 bg-sky-400/[0.05] px-3 py-2.5">
              <p className="flex items-center gap-2 text-[11.5px] font-semibold text-sky-100">
                <DeployIcon className="h-4 w-4 text-sky-300" />
                Container Control
              </p>
              <p className="mt-1.5 text-[10px] leading-relaxed text-slate-300">
                Host Docker control is disabled in SaaS mode, so Kodo never reaches a shared Docker
                daemon. Dockerfile/Compose generation, the Monaco diff review, guarded apply and Git
                PR export remain fully active — deploy the generated artifacts in your own CI/CD.
              </p>
            </section>
          ) : (
            <DockerControlPanel
              rootPath={rootPath}
              revision={revision}
              onChanged={bumpAudit}
            />
          )}
        </div>

        <div className="space-y-3">
          <GitExportPanel rootPath={rootPath} onWorkspaceCloned={onWorkspaceCloned} onChanged={bumpAudit} />
          <AuditLogPanel refreshToken={auditNonce + revision} />
        </div>
      </div>
    </div>
  );
}

function StackChip({
  active,
  label,
  title,
  onClick,
}: {
  active: boolean;
  label: string;
  title?: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title ?? label}
      className={`rounded px-2 py-1 text-[10px] transition ${
        active ? 'bg-sky-500/15 text-sky-200' : 'text-slate-400 hover:text-slate-200'
      }`}
    >
      {label}
    </button>
  );
}

const INPUT_CLASS =
  'min-w-0 rounded-md border border-ink-700 bg-ink-950/80 px-2 py-1 text-[11px] text-slate-200 outline-none transition placeholder:text-slate-600 focus:border-sky-500/60';

function initialPort(stack: StackChoice): number {
  return stack === 'auto' ? 8080 : stackOption(stack).defaultPort;
}
