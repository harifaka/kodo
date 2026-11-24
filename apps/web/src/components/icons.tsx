type IconProps = { className?: string };

export function LogoMark({ className = 'h-8 w-8' }: IconProps) {
  return (
    <svg viewBox="0 0 40 40" className={className} fill="none" aria-hidden>
      <rect x="1.5" y="1.5" width="37" height="37" rx="10" fill="#0f1621" stroke="#243249" />
      <path d="M13 11v18" stroke="#38bdf8" strokeWidth="2.6" strokeLinecap="round" />
      <path d="M13 20.5 22.5 11" stroke="#38bdf8" strokeWidth="2.6" strokeLinecap="round" />
      <path d="M15.5 18 25 29" stroke="#34d399" strokeWidth="2.6" strokeLinecap="round" />
      <circle cx="27.5" cy="12.5" r="2.2" fill="#a78bfa" />
    </svg>
  );
}

export function FolderIcon({ className = 'h-4 w-4' }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden>
      <path d="M3 7.5A2.5 2.5 0 0 1 5.5 5h3.2c.6 0 1.2.24 1.6.7l.9 1.05c.4.46 1 .75 1.6.75h5.7A2.5 2.5 0 0 1 21 10v6.5A2.5 2.5 0 0 1 18.5 19h-13A2.5 2.5 0 0 1 3 16.5v-9Z" strokeLinejoin="round" />
    </svg>
  );
}

export function ScanIcon({ className = 'h-4 w-4' }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden>
      <path d="M4 8V6a2 2 0 0 1 2-2h2M16 4h2a2 2 0 0 1 2 2v2M20 16v2a2 2 0 0 1-2 2h-2M8 20H6a2 2 0 0 1-2-2v-2" strokeLinecap="round" />
      <path d="M4 12h16" strokeLinecap="round" opacity=".7" />
    </svg>
  );
}

export function GraphIcon({ className = 'h-4 w-4' }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden>
      <rect x="3" y="3" width="7" height="6" rx="1.6" />
      <rect x="14" y="9" width="7" height="6" rx="1.6" />
      <rect x="3" y="15" width="7" height="6" rx="1.6" />
      <path d="M10 6h4M10 18h4M17.5 9V7.5A1.5 1.5 0 0 0 16 6h-2M17.5 15v1.5A1.5 1.5 0 0 1 16 18h-2" strokeLinecap="round" />
    </svg>
  );
}

export function UmlIcon({ className = 'h-4 w-4' }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden>
      <rect x="4" y="3" width="16" height="18" rx="2" />
      <path d="M4 8.5h16M4 14h10" strokeLinecap="round" />
    </svg>
  );
}

export function CodeIcon({ className = 'h-4 w-4' }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden>
      <path d="m9 8-4 4 4 4M15 8l4 4-4 4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function DiffIcon({ className = 'h-4 w-4' }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden>
      <rect x="3" y="4" width="7.5" height="16" rx="1.8" />
      <rect x="13.5" y="4" width="7.5" height="16" rx="1.8" />
      <path d="M5.5 9h2.5M5.5 12h2.5M5.5 15h1.8M16 9h2.5M16 12h2.5M16 15h2.5" strokeLinecap="round" />
    </svg>
  );
}

export function BuilderIcon({ className = 'h-4 w-4' }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden>
      <rect x="3" y="4.5" width="7" height="7" rx="1.5" />
      <rect x="14" y="4.5" width="7" height="7" rx="1.5" />
      <rect x="8.5" y="14.5" width="7" height="5.5" rx="1.5" />
      <path d="M10 8h4M6.5 11.5v2.6a1 1 0 0 0 1 1h1M17.5 11.5v2.6a1 1 0 0 1-1 1h-1" strokeLinecap="round" />
    </svg>
  );
}

export function DeployIcon({ className = 'h-4 w-4' }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden>
      <rect x="4" y="13.5" width="4" height="4" rx="1" />
      <rect x="10" y="13.5" width="4" height="4" rx="1" />
      <rect x="10" y="7.5" width="4" height="4" rx="1" />
      <path d="M6 13.5v-1a1 1 0 0 1 1-1h1M18.5 6.5v11" strokeLinecap="round" />
      <path d="M16 9l2.5-2.5L21 9" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function PlusIcon({ className = 'h-3.5 w-3.5' }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
      <path d="M12 5v14M5 12h14" strokeLinecap="round" />
    </svg>
  );
}

export function TrashIcon({ className = 'h-3.5 w-3.5' }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden>
      <path d="M4.5 7h15M9.5 7V4.8h5V7M6.8 7l.8 12.2a1.5 1.5 0 0 0 1.5 1.4h5.8a1.5 1.5 0 0 0 1.5-1.4L17.2 7" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function AlertIcon({ className = 'h-4 w-4' }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden>
      <path d="M12 4.5 21 19.5H3L12 4.5Z" strokeLinejoin="round" />
      <path d="M12 10v4.5M12 17h.01" strokeLinecap="round" />
    </svg>
  );
}

export function ChevronIcon({ className = 'h-3.5 w-3.5' }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
      <path d="m6 9 6 6 6-6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function CopyIcon({ className = 'h-3.5 w-3.5' }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden>
      <rect x="9" y="9" width="11" height="11" rx="2" />
      <path d="M15 5.5A1.5 1.5 0 0 0 13.5 4H5.5A1.5 1.5 0 0 0 4 5.5v8A1.5 1.5 0 0 0 5.5 15" />
    </svg>
  );
}

export function ExternalIcon({ className = 'h-3.5 w-3.5' }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden>
      <path d="M14 4h6v6M20 4l-8.5 8.5" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M18 14v4.5A1.5 1.5 0 0 1 16.5 20h-11A1.5 1.5 0 0 1 4 18.5v-11A1.5 1.5 0 0 1 5.5 6H10" strokeLinecap="round" />
    </svg>
  );
}

export function ZoomInIcon({ className = 'h-4 w-4' }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden>
      <circle cx="11" cy="11" r="6.5" />
      <path d="M11 8.5v5M8.5 11h5M16 16l4 4" strokeLinecap="round" />
    </svg>
  );
}

export function ZoomOutIcon({ className = 'h-4 w-4' }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden>
      <circle cx="11" cy="11" r="6.5" />
      <path d="M8.5 11h5M16 16l4 4" strokeLinecap="round" />
    </svg>
  );
}

export function FitIcon({ className = 'h-4 w-4' }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden>
      <path d="M4 9V5.5A1.5 1.5 0 0 1 5.5 4H9M15 4h3.5A1.5 1.5 0 0 1 20 5.5V9M20 15v3.5a1.5 1.5 0 0 1-1.5 1.5H15M9 20H5.5A1.5 1.5 0 0 1 4 18.5V15" strokeLinecap="round" />
    </svg>
  );
}

export function Spinner({ className = 'h-4 w-4' }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" className={`${className} animate-spin`} fill="none" aria-hidden>
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="2.4" opacity=".22" />
      <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" />
    </svg>
  );
}

export function CheckIcon({ className = 'h-3.5 w-3.5' }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
      <path d="m5 13 4.5 4.5L19 7" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function ShieldIcon({ className = 'h-4 w-4' }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden>
      <path d="M12 3.5 19.5 6v5.5c0 4.4-3.1 7.7-7.5 9-4.4-1.3-7.5-4.6-7.5-9V6L12 3.5Z" strokeLinejoin="round" />
      <path d="m9 12 2.2 2.2L15.5 10" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function SparkIcon({ className = 'h-4 w-4' }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden>
      <path d="m12 3.5 1.8 4.7 4.7 1.8-4.7 1.8L12 16.5l-1.8-4.7L5.5 10l4.7-1.8L12 3.5Z" strokeLinejoin="round" />
      <path d="m18.5 15.5.8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8.8-2.2Z" strokeLinejoin="round" />
    </svg>
  );
}

export function CloseIcon({ className = 'h-4 w-4' }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
      <path d="M6 6l12 12M18 6 6 18" strokeLinecap="round" />
    </svg>
  );
}

/** System 1 (Laya) — a small three-node decision network. */
export function DecisionIcon({ className = 'h-4 w-4' }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden>
      <circle cx="12" cy="4.8" r="2.1" />
      <circle cx="5" cy="18.5" r="2.1" />
      <circle cx="19" cy="18.5" r="2.1" />
      <path d="M10.6 6.6 6.2 16.6M13.4 6.6l4.4 10M7.1 18.5h9.8" strokeLinecap="round" />
    </svg>
  );
}
