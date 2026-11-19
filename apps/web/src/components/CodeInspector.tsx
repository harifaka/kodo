import { useEffect, useState } from 'react';
import Editor from '@monaco-editor/react';import { api } from '../lib/api';
import type { ComponentNode, FileContent } from '../types/core-ir';
import { CodeIcon, CopyIcon, ShieldIcon, Spinner } from './icons';

interface CodeInspectorProps {
  rootPath: string;
  node: ComponentNode | null;
}

type LoadState = 'idle' | 'loading' | 'error';

const EDITOR_OPTIONS = {
  readOnly: true,
  domReadOnly: true,
  minimap: { enabled: false },
  fontSize: 12.5,
  fontFamily: '"JetBrains Mono", Consolas, "Cascadia Code", monospace',
  lineHeight: 20,
  scrollBeyondLastLine: false,
  renderLineHighlight: 'line' as const,
  renderValidationDecorations: 'off' as const,
  smoothScrolling: true,
  padding: { top: 14, bottom: 14 },
  lineNumbersMinChars: 4,
  overviewRulerLanes: 0,
  scrollbar: { verticalScrollbarSize: 10, horizontalScrollbarSize: 10 },
};

export function CodeInspector({ rootPath, node }: CodeInspectorProps) {
  const [file, setFile] = useState<FileContent | null>(null);
  const [state, setState] = useState<LoadState>('idle');
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [monacoReady, setMonacoReady] = useState(false);

  useEffect(() => {
    let alive = true;
    // Monaco is heavy: load it (and its workers) only when the inspector is first opened.
    void import('../lib/monaco-setup').then(() => {
      if (alive) {
        setMonacoReady(true);
      }
    });
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    if (!node) {
      setFile(null);
      setState('idle');
      return;
    }

    let cancelled = false;
    setState('loading');
    setError(null);

    api
      .file(rootPath, node.filePath)
      .then((content) => {
        if (!cancelled) {
          setFile(content);
          setState('idle');
        }
      })
      .catch((reason: unknown) => {
        if (!cancelled) {
          setFile(null);
          setError(reason instanceof Error ? reason.message : String(reason));
          setState('error');
        }
      });

    return () => {
      cancelled = true;
    };
  }, [rootPath, node]);

  const copyPath = async () => {
    if (!node) return;
    try {
      await navigator.clipboard.writeText(`${rootPath}\\${node.filePath.replace(/\//g, '\\')}`);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false);
    }
  };

  if (!node) {
    return (
      <div className="flex h-full items-center justify-center bg-ink-950 px-6">
        <div className="max-w-sm text-center">
          <div className="mx-auto mb-3 flex h-11 w-11 items-center justify-center rounded-xl border border-ink-700 bg-ink-900 text-slate-500">
            <CodeIcon className="h-5 w-5" />
          </div>
          <p className="text-sm font-medium text-slate-300">No file selected</p>
          <p className="mt-1 text-xs leading-relaxed text-slate-500">
            Pick a component in the Macro Graph or the UML view, then open it here to inspect its source.
            Everything is read-only.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col bg-ink-950">
      <div className="flex items-center gap-3 border-b border-ink-700/70 bg-ink-900/70 px-3 py-2">
        <span className="flex min-w-0 items-center gap-1.5 truncate font-mono text-[11px] text-slate-400">
          <span className="text-slate-600">{workspaceTail(rootPath)}</span>
          <span className="text-slate-700">/</span>
          <span className="truncate text-slate-200">{node.filePath}</span>
        </span>

        <div className="ml-auto flex shrink-0 items-center gap-2">
          {file && (
            <span className="rounded border border-ink-600 bg-ink-850 px-1.5 py-0.5 text-[10px] text-slate-400">
              {file.language}
            </span>
          )}
          {file && (
            <span className="text-[10px] text-slate-600">{(file.size / 1024).toFixed(1)} KB</span>
          )}
          <span className="inline-flex items-center gap-1 rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2 py-0.5 text-[10px] font-medium text-emerald-300">
            <ShieldIcon className="h-3 w-3" />
            read-only
          </span>
          <button
            type="button"
            onClick={copyPath}
            title="Copy full path"
            className="rounded-md p-1.5 text-slate-500 transition hover:bg-ink-700 hover:text-slate-200"
          >
            <CopyIcon />
          </button>
        </div>
      </div>

      <div className="relative min-h-0 flex-1">
        {state === 'loading' && (
          <div className="absolute inset-0 z-10 flex items-center justify-center bg-ink-950/70">
            <span className="flex items-center gap-2 text-xs text-slate-400">
              <Spinner /> loading source…
            </span>
          </div>
        )}

        {state === 'error' && (
          <div className="absolute inset-0 z-10 flex items-center justify-center px-6">
            <div className="max-w-md rounded-lg border border-rose-500/40 bg-rose-950/30 px-4 py-3 text-center">
              <p className="text-xs font-medium text-rose-200">Could not open this file</p>
              <p className="mt-1 break-words font-mono text-[10.5px] text-rose-300/80">{error}</p>
            </div>
          </div>
        )}

        {file && monacoReady && (
          <Editor
            key={file.relPath}
            height="100%"
            path={file.relPath}
            language={file.language}
            value={file.content}
            theme="kodo-dark"
            options={EDITOR_OPTIONS}
            loading={<span className="text-xs text-slate-500">initializing editor…</span>}
          />
        )}

        {file && !monacoReady && (
          <div className="flex h-full items-center justify-center gap-2 text-xs text-slate-500">
            <Spinner /> initializing editor…
          </div>
        )}

        {copied && (
          <div className="absolute bottom-5 left-1/2 -translate-x-1/2 rounded-md border border-ink-600 bg-ink-850 px-3 py-1.5 text-[11px] text-slate-300 shadow-panel">
            Path copied
          </div>
        )}
      </div>
    </div>
  );
}

function workspaceTail(rootPath: string): string {
  const segments = rootPath.split(/[\\/]/).filter(Boolean);
  return segments.slice(-2).join('/') || rootPath;
}
