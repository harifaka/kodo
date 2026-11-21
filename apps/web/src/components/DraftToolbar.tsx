import { RELATION_META } from '../lib/layers';
import type { RelationType } from '../types/core-ir';
import { draftEditCount, type Draft } from '../lib/draft';
import { ShieldIcon } from './icons';

const RELATION_TYPES = Object.keys(RELATION_META) as RelationType[];

interface DraftToolbarProps {
  draft: Draft;
  relationType: RelationType;
  onRelationTypeChange: (type: RelationType) => void;
  onReset: () => void;
  onPreviewDiff: () => void;
  previewBusy: boolean;
  pending: boolean;
  error: string | null;
}

export function DraftToolbar({
  draft,
  relationType,
  onRelationTypeChange,
  onReset,
  onPreviewDiff,
  previewBusy,
  pending,
  error,
}: DraftToolbarProps) {
  const counts = draftEditCount(draft);
  const dirty = counts.total > 0;

  return (
    <div className="absolute right-4 top-3 w-[280px] rounded-lg border border-ink-700/70 bg-ink-900/90 p-2.5 backdrop-blur">
      <div className="flex items-center justify-between">
        <span className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">
          Draft edits
        </span>
        <span className="font-mono text-[9.5px] text-slate-400">
          <span className={dirty ? 'text-amber-300' : 'text-slate-600'}>{counts.total}</span> pending
        </span>
      </div>

      <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 font-mono text-[9px] text-slate-500">
        <span>
          relations{' '}
          <span className={counts.relations > 0 ? 'text-emerald-300' : 'text-slate-600'}>
            {counts.relations}
          </span>
        </span>
        <span>
          fields <span className={counts.fields > 0 ? 'text-amber-300' : 'text-slate-600'}>{counts.fields}</span>
        </span>
        <span>
          annotations{' '}
          <span className={counts.annotations > 0 ? 'text-violet-300' : 'text-slate-600'}>
            {counts.annotations}
          </span>
        </span>
      </div>

      <p className="mt-1.5 text-[10px] leading-relaxed text-slate-500">
        Drag between cards to connect. Edit fields in the component panel. Nothing is written to disk.
      </p>

      <div className="mt-2 flex flex-wrap gap-1">
        {RELATION_TYPES.map((type) => {
          const meta = RELATION_META[type];
          const active = type === relationType;
          return (
            <button
              key={type}
              type="button"
              onClick={() => onRelationTypeChange(type)}
              title={`New connections are drawn as "${meta.label}"`}
              className={`flex items-center gap-1 rounded border px-1.5 py-0.5 text-[9.5px] transition ${
                active
                  ? 'border-slate-400/50 bg-ink-700 text-slate-100'
                  : 'border-ink-700/70 text-slate-500 hover:border-ink-600 hover:text-slate-300'
              }`}
            >
              <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: meta.color }} />
              {meta.label}
            </button>
          );
        })}
      </div>

      <button
        type="button"
        onClick={onPreviewDiff}
        disabled={!dirty || previewBusy}
        className="mt-2 flex w-full items-center justify-center gap-1.5 rounded-md border border-emerald-400/40 bg-emerald-400/10 px-2 py-1.5 text-[10.5px] font-semibold text-emerald-200 transition hover:border-emerald-300/60 hover:bg-emerald-400/15 disabled:cursor-not-allowed disabled:border-ink-700/60 disabled:bg-transparent disabled:text-slate-600"
      >
        <ShieldIcon className="h-3.5 w-3.5" />
        {previewBusy ? 'Computing dry-run…' : 'Preview Diff (Dry-Run)'}
      </button>

      <div className="mt-2 flex items-center gap-2">
        <button
          type="button"
          onClick={onReset}
          disabled={!dirty}
          className="rounded-md border border-ink-600 px-2 py-1 text-[10px] text-slate-300 transition hover:border-rose-500/50 hover:text-rose-200 disabled:cursor-not-allowed disabled:border-ink-700/60 disabled:text-slate-600"
        >
          Reset draft
        </button>
        {pending && <span className="font-mono text-[9.5px] text-amber-300/80">re-auditing…</span>}
        {!pending && dirty && error === null && (
          <span className="font-mono text-[9.5px] text-slate-600">audit preview applied</span>
        )}
      </div>

      {error && (
        <p className="mt-1.5 text-[9.5px] leading-relaxed text-rose-300/80">
          Audit preview unavailable: {error}
        </p>
      )}
    </div>
  );
}
