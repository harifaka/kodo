import { PROJECT_STACK_META, PROJECT_STACK_ORDER } from '../lib/layers';
import type { ProjectStackTag } from '../types/fs';

interface ProjectStackBadgesProps {
  stacks: ProjectStackTag[];
  isGitRepo?: boolean;
  className?: string;
}

/** Folder-browser badges driven by marker-file detection only (no AST analysis). */
export function ProjectStackBadges({ stacks, isGitRepo = false, className = '' }: ProjectStackBadgesProps) {
  const ordered = PROJECT_STACK_ORDER.filter((stack) => stacks.includes(stack));
  if (ordered.length === 0 && !isGitRepo) {
    return null;
  }

  return (
    <span className={`flex flex-wrap items-center gap-1 ${className}`}>
      {ordered.map((stack) => {
        const meta = PROJECT_STACK_META[stack];
        return (
          <span
            key={stack}
            title={meta.title}
            className="inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[9.5px] font-medium"
            style={{ color: meta.color, borderColor: `${meta.color}44`, backgroundColor: `${meta.color}12` }}
          >
            <span className="h-1 w-1 rounded-full" style={{ backgroundColor: meta.color }} />
            {meta.short}
          </span>
        );
      })}
      {isGitRepo && (
        <span
          title="Contains a .git repository"
          className="inline-flex items-center gap-1 rounded border border-slate-500/40 bg-slate-500/10 px-1.5 py-0.5 text-[9.5px] font-medium text-slate-300"
        >
          <span className="h-1 w-1 rounded-full bg-slate-400" />
          Git
        </span>
      )}
    </span>
  );
}
