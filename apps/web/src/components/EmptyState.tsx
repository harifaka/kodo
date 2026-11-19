import { AlertIcon, GraphIcon, ScanIcon, ShieldIcon, UmlIcon } from './icons';
import type { HealthStatus } from '../hooks/useHealth';

interface EmptyStateProps {
  healthStatus: HealthStatus;
  scanning: boolean;
}

const STEPS = [
  {
    icon: ScanIcon,
    title: 'Start the local stack',
    body: 'FastAPI on :8088 and the Roslyn analyzer on :5050. The desktop shell launches both in production.',
  },
  {
    icon: GraphIcon,
    title: 'Paste a project folder',
    body: 'Any Spring Boot, Node.js / React or .NET folder on this machine. Kodo only reads it.',
  },
  {
    icon: UmlIcon,
    title: 'Scan and explore',
    body: 'Get the layer graph, generated UML, deterministic audit findings and read-only source inspection in one place.',
  },
];

export function EmptyState({ healthStatus, scanning }: EmptyStateProps) {
  const apiOnline = healthStatus === 'online';

  return (
    <div className="relative flex h-full items-center justify-center overflow-y-auto px-6 py-10">
      <div
        className="pointer-events-none absolute inset-0 opacity-40"
        style={{
          backgroundImage:
            'radial-gradient(circle at 1px 1px, rgba(148,163,184,0.12) 1px, transparent 0)',
          backgroundSize: '28px 28px',
        }}
        aria-hidden
      />

      <div className="relative w-full max-w-3xl">
        <div className="flex items-center gap-2">
          <span className="inline-flex items-center gap-1.5 rounded-full border border-sky-500/30 bg-sky-500/10 px-2.5 py-1 text-[10px] font-medium uppercase tracking-[0.14em] text-sky-300">
            <ShieldIcon className="h-3 w-3" />
            Phase 1 · read-only
          </span>
        </div>

        <h1 className="mt-4 text-3xl font-semibold tracking-tight text-white">
          See the architecture your code actually has.
        </h1>
        <p className="mt-2 max-w-2xl text-[13px] leading-relaxed text-slate-400">
          Kodo parses Java, TypeScript, JavaScript and C# into a single Core IR, then renders the dependency
          graph, a Mermaid UML diagram and the original source. Nothing is written to disk.
        </p>

        <div className="mt-7 grid gap-3 sm:grid-cols-3">
          {STEPS.map((step, index) => (
            <div
              key={step.title}
              className="rounded-xl border border-ink-700/70 bg-ink-900/70 p-3.5 shadow-panel"
            >
              <div className="flex items-center gap-2">
                <span className="flex h-6 w-6 items-center justify-center rounded-md border border-ink-600 bg-ink-850 text-sky-400">
                  <step.icon className="h-3.5 w-3.5" />
                </span>
                <span className="font-mono text-[10px] text-slate-600">0{index + 1}</span>
              </div>
              <p className="mt-2 text-[12px] font-medium text-slate-200">{step.title}</p>
              <p className="mt-1 text-[10.5px] leading-relaxed text-slate-500">{step.body}</p>
            </div>
          ))}
        </div>

        <div className="mt-6 flex flex-wrap items-center gap-2 text-[11px] text-slate-500">
          {apiOnline ? (
            <span className="inline-flex items-center gap-1.5 rounded-md border border-emerald-500/25 bg-emerald-500/10 px-2 py-1 text-emerald-300">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
              Orchestrator ready
            </span>
          ) : (
            <span className="inline-flex items-center gap-1.5 rounded-md border border-amber-500/25 bg-amber-500/10 px-2 py-1 text-amber-300">
              <AlertIcon className="h-3 w-3" />
              Start FastAPI: <code className="font-mono">uvicorn app.main:app --port 8088</code>
            </span>
          )}
          <span>Then paste a folder path above and hit “Scan Project”.</span>
        </div>

        {scanning && (
          <p className="mt-4 text-[11px] text-sky-300">Scanning the workspace… large repositories can take a few seconds.</p>
        )}
      </div>
    </div>
  );
}
