import type { ReactNode } from 'react';
import { useCallback, useEffect, useRef, useState } from 'react';
import {
  AlertIcon,
  CodeIcon,
  FitIcon,
  ScanIcon,
  ShieldIcon,
  Spinner,
  ZoomInIcon,
  ZoomOutIcon,
} from './icons';

const LARGE_GRAPH_THRESHOLD = 60;

interface UmlDiagramProps {
  diagram: string;
  componentCount: number;
  draftPending?: boolean;
  /** Component count of the full, unfiltered workspace (drives the large-graph guard). */
  totalComponentCount?: number;
  /** A layer/stack/search/issues/1-hop filter produced the diagram above. */
  filterActive?: boolean;
  focusActive?: boolean;
  filterSummary?: string | null;
  subsetLoading?: boolean;
  findingsCount?: number;
  canFocusSelected?: boolean;
  onFocusSelected?: () => void;
  onShowIssuesOnly?: () => void;
  onResetFilters?: () => void;
}

interface ViewTransform {
  scale: number;
  x: number;
  y: number;
}

type MermaidApi = typeof import('mermaid').default;

let mermaidApi: MermaidApi | null = null;
let renderCounter = 0;

async function loadMermaid(): Promise<MermaidApi> {
  if (mermaidApi) {
    return mermaidApi;
  }

  const module = await import('mermaid');
  const instance = module.default;
  instance.initialize({
    startOnLoad: false,
    theme: 'dark',
    securityLevel: 'strict',
    fontFamily: 'Inter, "Segoe UI", system-ui, sans-serif',
    themeVariables: {
      background: '#0b0f16',
      primaryColor: '#131a25',
      primaryTextColor: '#e2e8f0',
      primaryBorderColor: '#334155',
      secondaryColor: '#182130',
      tertiaryColor: '#0f141d',
      lineColor: '#475569',
      textColor: '#cbd5e1',
      classText: '#dbe4f0',
      clusterBkg: '#0f141d',
      clusterBorder: '#243249',
      titleColor: '#e2e8f0',
      edgeLabelBackground: '#0b0f16',
      fontSize: '15px',
    },
  });
  mermaidApi = instance;
  return instance;
}

const MIN_SCALE = 0.15;
const MAX_SCALE = 4;

export function UmlDiagram({
  diagram,
  componentCount,
  draftPending = false,
  totalComponentCount,
  filterActive = false,
  focusActive = false,
  filterSummary = null,
  subsetLoading = false,
  findingsCount = 0,
  canFocusSelected = false,
  onFocusSelected,
  onShowIssuesOnly,
  onResetFilters,
}: UmlDiagramProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const dragRef = useRef<{ x: number; y: number; viewX: number; viewY: number } | null>(null);
  const viewRef = useRef<ViewTransform>({ scale: 1, x: 24, y: 24 });

  const [svg, setSvg] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<ViewTransform>(viewRef.current);
  const [showSource, setShowSource] = useState(false);
  const [forceFullRender, setForceFullRender] = useState(false);

  const total = totalComponentCount ?? componentCount;

  useEffect(() => {
    // A different workspace starts the guard over; an active filter supersedes it.
    setForceFullRender(false);
  }, [total]);

  useEffect(() => {
    if (filterActive) {
      setForceFullRender(false);
    }
  }, [filterActive]);

  const largeGraphGuard = !filterActive && total > LARGE_GRAPH_THRESHOLD && !forceFullRender;

  const updateView = useCallback((next: ViewTransform | ((current: ViewTransform) => ViewTransform)) => {
    setView((current) => {
      const resolved = typeof next === 'function' ? next(current) : next;
      viewRef.current = resolved;
      return resolved;
    });
  }, []);

  const normalizeSvgSize = useCallback((): { width: number; height: number } | null => {
    const svgElement = containerRef.current?.querySelector<SVGSVGElement>('svg');
    if (!svgElement) {
      return null;
    }

    const box = svgElement.viewBox?.baseVal;
    const width = box && box.width > 0 ? box.width : svgElement.clientWidth || 1;
    const height = box && box.height > 0 ? box.height : svgElement.clientHeight || 1;

    // Mermaid emits width="100%": pin the intrinsic size so the wrapper and zoom math are correct.
    svgElement.setAttribute('width', String(width));
    svgElement.setAttribute('height', String(height));
    svgElement.style.width = `${width}px`;
    svgElement.style.height = `${height}px`;
    return { width, height };
  }, []);

  const fitAll = useCallback(() => {
    const container = containerRef.current;
    if (!container) {
      return;
    }

    const size = normalizeSvgSize();
    if (!size) {
      return;
    }

    const padding = 56;
    const scale = Math.min(
      (container.clientWidth - padding) / size.width,
      (container.clientHeight - padding) / size.height,
      1.4,
    );

    updateView({
      scale,
      x: (container.clientWidth - size.width * scale) / 2,
      y: (container.clientHeight - size.height * scale) / 2,
    });
  }, [normalizeSvgSize, updateView]);

  // Readability first: start at full width (the diagram can be panned vertically), "Fit" shows everything.
  const fitWidth = useCallback(() => {
    const container = containerRef.current;
    if (!container) {
      return;
    }

    const size = normalizeSvgSize();
    if (!size) {
      return;
    }

    const padding = 48;
    const scale = Math.min((container.clientWidth - padding) / size.width, 1.2);

    updateView({
      scale,
      x: (container.clientWidth - size.width * scale) / 2,
      y: 24,
    });
  }, [normalizeSvgSize, updateView]);

  useEffect(() => {
    let cancelled = false;

    if (largeGraphGuard || !diagram.trim()) {
      // Guarded: skip the expensive Mermaid render until the user narrows the view or opts in.
      setSvg('');
      setError(null);
      return;
    }

    const render = async () => {
      try {
        const mermaid = await loadMermaid();
        renderCounter += 1;
        const { svg: rendered } = await mermaid.render(`kodo-uml-${renderCounter}`, diagram);
        if (!cancelled) {
          setSvg(rendered);
          setError(null);
        }
      } catch (reason: unknown) {
        if (!cancelled) {
          setSvg('');
          setError(reason instanceof Error ? reason.message : String(reason));
        }
      }
    };

    void render();

    return () => {
      cancelled = true;
    };
  }, [diagram, largeGraphGuard]);

  useEffect(() => {
    if (!svg) {
      return;
    }
    const frame = window.requestAnimationFrame(fitWidth);
    return () => window.cancelAnimationFrame(frame);
  }, [svg, fitWidth]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) {
      return;
    }

    const handleWheel = (event: WheelEvent) => {
      event.preventDefault();
      const bounds = container.getBoundingClientRect();

      if (!event.ctrlKey && !event.metaKey) {
        updateView((current) => ({
          ...current,
          x: current.x - event.deltaX,
          y: current.y - event.deltaY,
        }));
        return;
      }

      const pointerX = event.clientX - bounds.left;
      const pointerY = event.clientY - bounds.top;

      updateView((current) => {
        const factor = Math.exp(-event.deltaY * 0.0015);
        const scale = Math.min(MAX_SCALE, Math.max(MIN_SCALE, current.scale * factor));
        const ratio = scale / current.scale;
        return {
          scale,
          x: pointerX - (pointerX - current.x) * ratio,
          y: pointerY - (pointerY - current.y) * ratio,
        };
      });
    };

    container.addEventListener('wheel', handleWheel, { passive: false });
    return () => container.removeEventListener('wheel', handleWheel);
  }, [updateView]);

  const zoomBy = (factor: number) => {
    const container = containerRef.current;
    if (!container) {
      return;
    }
    const centerX = container.clientWidth / 2;
    const centerY = container.clientHeight / 2;

    updateView((current) => {
      const scale = Math.min(MAX_SCALE, Math.max(MIN_SCALE, current.scale * factor));
      const ratio = scale / current.scale;
      return {
        scale,
        x: centerX - (centerX - current.x) * ratio,
        y: centerY - (centerY - current.y) * ratio,
      };
    });
  };

  return (
    <div className="relative h-full w-full overflow-hidden bg-ink-950">
      <div className="absolute inset-0 opacity-[0.55]" style={gridBackground} aria-hidden />

      <div
        ref={containerRef}
        className={`absolute inset-0 cursor-grab touch-none overflow-hidden active:cursor-grabbing ${
          largeGraphGuard ? 'hidden' : ''
        }`}
        onPointerDown={(event) => {
          if (event.button !== 0) return;
          dragRef.current = {
            x: event.clientX,
            y: event.clientY,
            viewX: viewRef.current.x,
            viewY: viewRef.current.y,
          };
          event.currentTarget.setPointerCapture(event.pointerId);
        }}
        onPointerMove={(event) => {
          const drag = dragRef.current;
          if (!drag) return;
          updateView({
            scale: viewRef.current.scale,
            x: drag.viewX + (event.clientX - drag.x),
            y: drag.viewY + (event.clientY - drag.y),
          });
        }}
        onPointerUp={(event) => {
          dragRef.current = null;
          if (event.currentTarget.hasPointerCapture(event.pointerId)) {
            event.currentTarget.releasePointerCapture(event.pointerId);
          }
        }}
        onPointerCancel={() => {
          dragRef.current = null;
        }}
      >
        <div
          className="kodo-uml absolute left-0 top-0 origin-top-left"
          style={{ transform: `translate(${view.x}px, ${view.y}px) scale(${view.scale})` }}
          dangerouslySetInnerHTML={{ __html: svg }}
        />
      </div>

      <div className="pointer-events-none absolute left-4 top-3 flex items-center gap-3 rounded-lg border border-ink-700/70 bg-ink-900/80 px-3 py-1.5 backdrop-blur">
        <span className="flex items-center gap-1.5 text-[11px] text-slate-400">
          <ShieldIcon className="h-3.5 w-3.5 text-violet-400" />
          Generated UML
        </span>
        <span className="h-3 w-px bg-ink-600" />
        <span className="text-[11px] text-slate-400">
          <span className="font-semibold text-slate-200">{componentCount}</span> classes · read-only
        </span>
        {subsetLoading && (
          <>
            <span className="h-3 w-px bg-ink-600" />
            <Spinner className="h-3 w-3 text-sky-300" />
          </>
        )}
        {filterActive && (
          <>
            <span className="h-3 w-px bg-ink-600" />
            <span
              className="text-[10px] text-amber-300/90"
              title={filterSummary ?? 'Layer / stack / search / issues filter applied'}
            >
              filtered subset · {componentCount} of {total} classes
            </span>
            {onResetFilters && (
              <button
                type="button"
                onClick={onResetFilters}
                className="pointer-events-auto rounded border border-amber-400/40 px-1.5 py-0.5 text-[9.5px] text-amber-200/90 transition hover:bg-amber-400/10"
              >
                Reset filters
              </button>
            )}
          </>
        )}
        {focusActive && (
          <>
            <span className="h-3 w-px bg-ink-600" />
            <span className="text-[10px] text-sky-300/90">1-hop focus</span>
          </>
        )}
        {draftPending && (
          <>
            <span className="h-3 w-px bg-ink-600" />
            <span className="text-[10px] text-amber-300/90">draft edges not applied yet</span>
          </>
        )}
      </div>

      <div className="absolute right-4 top-3 flex items-center gap-2">
        <button
          type="button"
          onClick={() => setShowSource((value) => !value)}
          className={`inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-[11px] transition ${
            showSource
              ? 'border-sky-500/60 bg-sky-500/10 text-sky-300'
              : 'border-ink-600 bg-ink-900/80 text-slate-400 hover:text-slate-200'
          }`}
        >
          <CodeIcon className="h-3.5 w-3.5" />
          Source
        </button>
      </div>

      <div
        className={`pointer-events-none absolute bottom-4 left-4 rounded-md border border-ink-700/60 bg-ink-900/70 px-2.5 py-1 text-[10px] text-slate-500 backdrop-blur ${
          largeGraphGuard ? 'hidden' : ''
        }`}
      >
        drag to pan · ctrl + scroll to zoom
      </div>

      <div
        className={`absolute bottom-4 right-4 flex items-center gap-1 rounded-lg border border-ink-700/80 bg-ink-900/90 p-1 backdrop-blur ${
          largeGraphGuard ? 'hidden' : ''
        }`}
      >
        <span className="w-12 text-center font-mono text-[10px] text-slate-400">
          {Math.round(view.scale * 100)}%
        </span>
        <IconButton label="Zoom out" onClick={() => zoomBy(1 / 1.2)}>
          <ZoomOutIcon />
        </IconButton>
        <IconButton label="Zoom in" onClick={() => zoomBy(1.2)}>
          <ZoomInIcon />
        </IconButton>
        <IconButton label="Fit diagram to view" onClick={fitAll}>
          <FitIcon />
        </IconButton>
      </div>

      {showSource && (
        <div className="absolute bottom-16 right-4 top-16 w-[min(560px,45%)] overflow-auto rounded-lg border border-ink-700 bg-ink-950/95 p-3 shadow-panel">
          <div className="mb-2 flex items-center justify-between">
            <span className="text-[10px] uppercase tracking-[0.16em] text-slate-500">mermaid classDiagram</span>
            <span className="text-[10px] text-slate-600">generated server-side</span>
          </div>
          <pre className="whitespace-pre-wrap break-words font-mono text-[10.5px] leading-relaxed text-slate-400">
            {diagram || '% no diagram'}
          </pre>
        </div>
      )}

      {error && !largeGraphGuard && (
        <div className="absolute inset-x-0 bottom-4 mx-auto w-[min(560px,90%)] rounded-lg border border-rose-500/40 bg-rose-950/40 px-4 py-3">
          <p className="text-xs font-medium text-rose-200">Mermaid could not render this diagram</p>
          <p className="mt-1 font-mono text-[10px] text-rose-300/80">{error}</p>
        </div>
      )}

      {subsetLoading && !largeGraphGuard && (
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
          <p className="flex items-center gap-2 text-xs text-slate-500">
            <Spinner className="h-3.5 w-3.5 text-sky-300" />
            Building the filtered class diagram…
          </p>
        </div>
      )}

      {!svg && !error && !largeGraphGuard && !subsetLoading && (
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
          <p className="text-xs text-slate-500">No diagram generated for this workspace.</p>
        </div>
      )}

      {largeGraphGuard && (
        <div className="absolute inset-0 flex items-center justify-center p-6">
          <div className="w-full max-w-[560px] rounded-xl border border-amber-400/35 bg-ink-900/95 px-5 py-4 shadow-panel">
            <div className="flex items-start gap-2.5">
              <AlertIcon className="mt-0.5 h-4 w-4 shrink-0 text-amber-300" />
              <div>
                <p className="text-[13px] font-semibold text-amber-100">
                  This class diagram would contain {total} classes
                </p>
                <p className="mt-1 text-[11px] leading-relaxed text-slate-400">
                  Huge Mermaid diagrams are slow to render and hard to read. Narrow the view first with a
                  1-hop neighbourhood or the issues-only filter — or render everything anyway.
                </p>
              </div>
            </div>
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <button
                type="button"
                onClick={onFocusSelected}
                disabled={!canFocusSelected}
                title={
                  canFocusSelected
                    ? 'Render only the selected component and its direct neighbours'
                    : 'Select a component in the Macro Graph first'
                }
                className="inline-flex items-center gap-1.5 rounded-md border border-sky-400/50 bg-sky-500/10 px-2.5 py-1 text-[11px] text-sky-200 transition enabled:hover:bg-sky-500/20 disabled:cursor-not-allowed disabled:opacity-45"
              >
                <ScanIcon className="h-3 w-3" />
                Focus Selected Node (1-Hop)
              </button>
              <button
                type="button"
                onClick={onShowIssuesOnly}
                disabled={findingsCount === 0}
                title={
                  findingsCount === 0
                    ? 'This workspace has no audit findings'
                    : 'Render only the components and relations referenced by audit findings'
                }
                className="inline-flex items-center gap-1.5 rounded-md border border-rose-400/50 bg-rose-500/10 px-2.5 py-1 text-[11px] text-rose-200 transition enabled:hover:bg-rose-500/20 disabled:cursor-not-allowed disabled:opacity-45"
              >
                <AlertIcon className="h-3 w-3" />
                Show Issues Only
              </button>
              <button
                type="button"
                onClick={() => setForceFullRender(true)}
                className="inline-flex items-center gap-1.5 rounded-md border border-ink-600 bg-ink-850/80 px-2.5 py-1 text-[11px] text-slate-300 transition hover:border-slate-400/60 hover:text-white"
              >
                Render Full Diagram Anyway
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function IconButton({
  label,
  onClick,
  children,
}: {
  label: string;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      onClick={onClick}
      className="rounded-md p-1.5 text-slate-400 transition hover:bg-ink-700 hover:text-slate-100"
    >
      {children}
    </button>
  );
}

const gridBackground = {
  backgroundImage:
    'radial-gradient(circle at 1px 1px, rgba(148,163,184,0.14) 1px, transparent 0)',
  backgroundSize: '26px 26px',
} as const;
