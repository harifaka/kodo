import { blankField, stackOption } from '../lib/blueprint';
import type { BlueprintField, BlueprintSlice, BlueprintStack } from '../types/blueprint';
import { PlusIcon, TrashIcon } from './icons';

const INPUT_CLASS =
  'min-w-0 rounded-md border border-ink-700 bg-ink-950/70 px-2 py-1 text-[11px] text-slate-200 outline-none transition placeholder:text-slate-600 focus:border-sky-500/60';

interface SliceEditorProps {
  slice: BlueprintSlice;
  slices: BlueprintSlice[];
  index: number;
  stack: BlueprintStack;
  onChange: (index: number, patch: Partial<BlueprintSlice>) => void;
}

export function SliceEditor({ slice, slices, index, stack, onChange }: SliceEditorProps) {
  const option = stackOption(stack);
  const typeListId = `kodo-builder-types-${stack}`;
  const annotationListId = `kodo-builder-annotations-${stack}`;
  const dependencies = slices
    .map((entry, position) => ({ entry, position }))
    .filter(({ position }) => position !== index);

  const updateField = (fieldIndex: number, patch: Partial<BlueprintField>) => {
    onChange(index, {
      fields: slice.fields.map((field, position) =>
        position === fieldIndex ? { ...field, ...patch } : field,
      ),
    });
  };

  const removeField = (fieldIndex: number) => {
    onChange(index, { fields: slice.fields.filter((_, position) => position !== fieldIndex) });
  };

  const toggleDependency = (name: string) => {
    const selected = slice.dependsOnSlices.includes(name);
    onChange(index, {
      dependsOnSlices: selected
        ? slice.dependsOnSlices.filter((entry) => entry !== name)
        : [...slice.dependsOnSlices, name],
    });
  };

  return (
    <div className="min-h-0 flex-1 overflow-y-auto p-4">
      <datalist id={typeListId}>
        {option.fieldTypes.map((type) => (
          <option key={type} value={type} />
        ))}
      </datalist>
      <datalist id={annotationListId}>
        {option.annotationPresets.map((preset) => (
          <option key={preset} value={preset} />
        ))}
      </datalist>

      <div className="grid gap-3 sm:grid-cols-2">
        <label className="flex flex-col gap-1">
          <span className="text-[9.5px] font-semibold uppercase tracking-[0.16em] text-slate-500">
            Slice name (PascalCase)
          </span>
          <input
            value={slice.name}
            onChange={(event) => onChange(index, { name: event.target.value })}
            placeholder="Invoice"
            spellCheck={false}
            className={INPUT_CLASS}
          />
        </label>

        <div className="flex flex-col gap-1">
          <span className="text-[9.5px] font-semibold uppercase tracking-[0.16em] text-slate-500">
            Depends on slices
          </span>
          <div className="flex min-h-[28px] flex-wrap items-center gap-1.5">
            {dependencies.length === 0 ? (
              <span className="text-[10px] text-slate-600">Add another slice to link services.</span>
            ) : (
              dependencies.map(({ entry }) => {
                const active = slice.dependsOnSlices.includes(entry.name);
                return (
                  <button
                    key={entry.name}
                    type="button"
                    onClick={() => toggleDependency(entry.name)}
                    aria-pressed={active}
                    className={`rounded-full border px-2 py-0.5 font-mono text-[9.5px] transition ${
                      active
                        ? 'border-violet-400/50 bg-violet-400/15 text-violet-200'
                        : 'border-ink-600 text-slate-400 hover:border-violet-400/40 hover:text-violet-200'
                    }`}
                  >
                    {entry.name}
                  </button>
                );
              })
            )}
          </div>
        </div>
      </div>

      <label className="mt-3 flex w-fit items-center gap-2 rounded-md border border-ink-700 bg-ink-900/60 px-2 py-1">
        <input
          type="checkbox"
          checked={slice.includeTests}
          onChange={(event) => onChange(index, { includeTests: event.target.checked })}
          className="h-3 w-3 accent-sky-500"
        />
        <span className="text-[10px] text-slate-300">Include unit test skeleton</span>
      </label>

      <div className="mt-4">
        <div className="mb-1.5 flex items-center justify-between">
          <p className="text-[9.5px] font-semibold uppercase tracking-[0.16em] text-slate-500">
            Business fields · {slice.fields.length}
          </p>
          <button
            type="button"
            onClick={() => onChange(index, { fields: [...slice.fields, blankField(stack)] })}
            className="flex items-center gap-1 rounded-md border border-emerald-400/40 px-2 py-0.5 text-[10px] text-emerald-200 transition hover:bg-emerald-400/10"
          >
            <PlusIcon className="h-3 w-3" /> Add field
          </button>
        </div>

        <datalist id={`${typeListId}-row`}>
          {option.fieldTypes.map((type) => (
            <option key={type} value={type} />
          ))}
        </datalist>

        {slice.fields.length === 0 ? (
          <p className="rounded-md border border-dashed border-ink-700 px-3 py-4 text-center text-[10.5px] text-slate-500">
            No fields yet. Add business fields so Kodo generates validation and persistence columns.
          </p>
        ) : (
          <div className="overflow-hidden rounded-lg border border-ink-700">
            <div className="grid grid-cols-[minmax(0,1.1fr)_minmax(0,0.8fr)_auto_minmax(0,1.2fr)_auto] gap-2 border-b border-ink-700 bg-ink-900/70 px-2 py-1.5 text-[9px] font-semibold uppercase tracking-[0.14em] text-slate-500">
              <span>Name</span>
              <span>Type</span>
              <span>Req.</span>
              <span>Annotations</span>
              <span />
            </div>
            {slice.fields.map((field, fieldIndex) => (
              <div
                key={fieldIndex}
                className="grid grid-cols-[minmax(0,1.1fr)_minmax(0,0.8fr)_auto_minmax(0,1.2fr)_auto] items-center gap-2 border-b border-ink-800 px-2 py-1 last:border-b-0"
              >
                <input
                  value={field.name}
                  onChange={(event) => updateField(fieldIndex, { name: event.target.value })}
                  placeholder="number"
                  spellCheck={false}
                  aria-label={`Field ${fieldIndex + 1} name`}
                  className={`${INPUT_CLASS} font-mono`}
                />
                <input
                  value={field.type}
                  onChange={(event) => updateField(fieldIndex, { type: event.target.value })}
                  list={typeListId}
                  spellCheck={false}
                  aria-label={`Field ${fieldIndex + 1} type`}
                  className={`${INPUT_CLASS} font-mono`}
                />
                <input
                  type="checkbox"
                  checked={field.required}
                  onChange={(event) => updateField(fieldIndex, { required: event.target.checked })}
                  aria-label={`Field ${fieldIndex + 1} required`}
                  className="h-3 w-3 accent-sky-500"
                />
                <input
                  value={field.annotations.join(', ')}
                  onChange={(event) =>
                    updateField(fieldIndex, {
                      annotations: event.target.value
                        .split(',')
                        .map((entry) => entry.trim())
                        .filter(Boolean),
                    })
                  }
                  list={annotationListId}
                  placeholder={option.annotationPresets[0] ?? ''}
                  spellCheck={false}
                  aria-label={`Field ${fieldIndex + 1} annotations`}
                  className={`${INPUT_CLASS} font-mono`}
                />
                <button
                  type="button"
                  onClick={() => removeField(fieldIndex)}
                  aria-label={`Remove field ${field.name || fieldIndex + 1}`}
                  className="rounded p-1 text-slate-500 transition hover:bg-rose-500/10 hover:text-rose-300"
                >
                  <TrashIcon className="h-3.5 w-3.5" />
                </button>
              </div>
            ))}
          </div>
        )}
        <p className="mt-1.5 text-[9.5px] leading-relaxed text-slate-600">
          Types are canonical and mapped per stack ({option.fieldTypes.slice(0, 6).join(', ')}, …).
          Unrecognised types are emitted verbatim.
        </p>
      </div>
    </div>
  );
}
