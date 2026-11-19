import { useState } from 'react';
import { AlertIcon, ChevronIcon } from './icons';

export function WarningsBar({ warnings }: { warnings: string[] }) {
  const [open, setOpen] = useState(true);

  if (warnings.length === 0) {
    return null;
  }

  return (
    <div className="border-b border-amber-500/20 bg-amber-500/[0.05]">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-center gap-2 px-4 py-1.5 text-left"
      >
        <AlertIcon className="h-3.5 w-3.5 text-amber-400" />
        <span className="text-[11px] font-medium text-amber-200">
          {warnings.length} diagnostic{warnings.length === 1 ? '' : 's'}
        </span>
        <span className="text-[10px] text-amber-200/45">non-fatal — results may be partial</span>
        <ChevronIcon
          className={`ml-auto h-3.5 w-3.5 text-amber-300/60 transition-transform ${open ? 'rotate-180' : ''}`}
        />
      </button>
      {open && (
        <ul className="max-h-24 space-y-1 overflow-y-auto px-4 pb-2">
          {warnings.map((warning, index) => (
            <li key={`${index}-${warning.slice(0, 24)}`} className="text-[10.5px] leading-relaxed text-amber-100/70">
              • {warning}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
