import { useState } from 'react';
import type { ComponentNode } from '../types/core-ir';
import { AlertIcon, SparkIcon, Spinner } from './icons';

interface MethodsSectionProps {
  node: ComponentNode;
  aiConfigured: boolean;
  onConfigureAi: () => void;
  onImplement: (methodName: string, instruction: string) => Promise<void>;
}

/** Methods list with the targeted "AI Implement" inline prompt (Phase 5, workflow 3). */
export function MethodsSection({ node, aiConfigured, onConfigureAi, onImplement }: MethodsSectionProps) {
  const [activeKey, setActiveKey] = useState<string | null>(null);
  const [instruction, setInstruction] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (methodName: string) => {
    const text = instruction.trim();
    if (!text) {
      setError('Describe what the method should do.');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await onImplement(methodName, text);
      setActiveKey(null);
      setInstruction('');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  };

  const toggle = (key: string) => {
    setActiveKey((current) => (current === key ? null : key));
    setInstruction('');
    setError(null);
  };

  return (
    <section className="border-b border-ink-700/40 px-4 py-3 last:border-b-0">
      <h3 className="mb-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">
        Methods · {node.methods.length}
      </h3>

      {node.methods.length === 0 ? (
        <p className="text-[10.5px] text-slate-600">No methods discovered.</p>
      ) : (
        <ul className="space-y-1">
          {node.methods.map((method) => {
            const key = `${method.name}(${method.parameters.join(',')})`;
            const open = activeKey === key;
            return (
              <li key={key} className="rounded-md border border-ink-700/50 bg-ink-950/50 px-2.5 py-1.5">
                <div className="flex items-start gap-2">
                  <div className="min-w-0 flex-1 break-all font-mono text-[10.5px] leading-relaxed">
                    <span className="text-emerald-300">{method.name}</span>
                    <span className="text-slate-500">({method.parameters.join(', ')})</span>
                    {method.returnType && <span className="text-slate-400"> : {method.returnType}</span>}
                  </div>
                  <span
                    title={
                      aiConfigured
                        ? 'Ask the AI Copilot to implement this method — the proposal opens in the diff preview'
                        : 'Configure the AI Copilot (top-right pill) to enable AI implementation'
                    }
                  >
                    <button
                      type="button"
                      disabled={!aiConfigured || busy}
                      onClick={() => toggle(key)}
                      aria-expanded={open}
                      className="flex shrink-0 items-center gap-1 rounded border border-violet-400/30 bg-violet-400/10 px-1.5 py-0.5 text-[9px] text-violet-200 transition enabled:hover:bg-violet-400/20 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      <SparkIcon className="h-2.5 w-2.5" />
                      AI Implement
                    </button>
                  </span>
                </div>

                {open && (
                  <div className="mt-1.5">
                    <textarea
                      value={instruction}
                      onChange={(event) => setInstruction(event.target.value)}
                      rows={3}
                      spellCheck={false}
                      autoFocus
                      placeholder={`What should ${method.name} do? Business rules, edge cases, validation…`}
                      className="w-full resize-y rounded border border-ink-700 bg-ink-950/80 px-2 py-1 text-[10.5px] leading-relaxed text-slate-200 outline-none transition placeholder:text-slate-600 focus:border-violet-400/60"
                    />
                    <div className="mt-1 flex flex-wrap items-center gap-1.5">
                      <button
                        type="button"
                        disabled={busy || !instruction.trim()}
                        onClick={() => void submit(method.name)}
                        className="flex items-center gap-1 rounded border border-violet-400/50 bg-violet-400/10 px-2 py-0.5 text-[9.5px] font-medium text-violet-100 transition enabled:hover:bg-violet-400/20 disabled:opacity-50"
                      >
                        {busy ? <Spinner className="h-2.5 w-2.5" /> : <SparkIcon className="h-2.5 w-2.5" />}
                        {busy ? 'Generating…' : 'Generate patch'}
                      </button>
                      <button
                        type="button"
                        onClick={() => toggle(key)}
                        disabled={busy}
                        className="rounded px-1.5 py-0.5 text-[9.5px] text-slate-400 transition hover:text-slate-200 disabled:opacity-50"
                      >
                        Cancel
                      </button>
                      {!aiConfigured && (
                        <button
                          type="button"
                          onClick={onConfigureAi}
                          className="text-[9.5px] text-violet-200 underline decoration-violet-400/40 underline-offset-2"
                        >
                          Configure AI Copilot
                        </button>
                      )}
                    </div>
                    {error && (
                      <p className="mt-1 flex items-start gap-1.5 text-[9.5px] leading-relaxed text-rose-300">
                        <AlertIcon className="mt-0.5 h-3 w-3 shrink-0" />
                        {error}
                      </p>
                    )}
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
