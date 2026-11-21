import { RELATION_META } from '../lib/layers';
import type { RelationType } from '../types/core-ir';
import type { RelationDraft } from '../lib/draft';

const RELATION_TYPES = Object.keys(RELATION_META) as RelationType[];

interface DraftToolbarProps {
  draft: RelationDraft;
  relationType: RelationType;
  onRelationTypeChange: (type: RelationType) => void;
  onReset: () => void;
  pending: boolean;
  error: string | null;
}

export function DraftToolbar({
  draft,
  relationType,
  onRelationTypeChange,
  onReset,
  pending,
  error,
}: DraftToolbarProps) {
  const dirty = draft.added.length > 0 || draft.removed.length > 0;

  return (
    <div className="absolute right-4 top-3 w-[262px] rounded-lg border border-ink-700/70 bg-ink-900/85 p-2.5 backdrop-blur">
      <div className="flex items-center justify-between">
        <span className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">
          Macro draft
        </span>
        <span className="font-mono text-[9.5px]">
          <span className={draft.added.length > 0 ? 'text-emerald-300' : 'text-slate-600'}>
            +{draft.added.length}
          </span>
          <span className="text-slate-600"> / </span>
          <span className={draft.removed.length > 0 ? 'text-rose-300' : 'text-slate-600'}>
            −{draft.removed.length}
          </span>
        </span>
      </div>

      <p className="mt-1.5 text-[10px] leading-relaxed text-slate-500">
        Drag from a card&apos;s right handle onto another card to connect. Click the × on an edge to
        cut it.
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
