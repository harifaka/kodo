/** Lightweight line statistics for the dry-run sidebar (Monaco renders the real diff). */

export interface LineChangeStats {
  added: number;
  removed: number;
  changed: number;
}

export function countLineChanges(original: string, proposed: string): LineChangeStats {
  if (original === proposed) {
    return { added: 0, removed: 0, changed: 0 };
  }

  const before = original.split(/\r?\n/);
  const after = proposed.split(/\r?\n/);

  let prefix = 0;
  while (prefix < before.length && prefix < after.length && before[prefix] === after[prefix]) {
    prefix += 1;
  }

  let suffix = 0;
  while (
    suffix < before.length - prefix &&
    suffix < after.length - prefix &&
    before[before.length - 1 - suffix] === after[after.length - 1 - suffix]
  ) {
    suffix += 1;
  }

  const removed = before.length - prefix - suffix;
  const added = after.length - prefix - suffix;

  return { added, removed, changed: added + removed };
}
