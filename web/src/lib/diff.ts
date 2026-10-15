/** Word-level difference between two texts, for the amendment screen: what a later
 * version removed from and added to a clause as the earlier reading had it. A longest
 * common subsequence over words (whitespace kept with the word before it), so that a
 * sentence rewritten in one place shows that place and not the whole sentence. */

export type DiffPart = { kind: "same" | "removed" | "added"; text: string };

function words(text: string): string[] {
  return text.match(/\S+\s*/g) ?? [];
}

export function wordDiff(before: string, after: string): DiffPart[] {
  const a = words(before);
  const b = words(after);
  // lcs[i][j]: the length of the longest common subsequence of a[i..] and b[j..].
  const lcs: number[][] = Array.from({ length: a.length + 1 }, () => new Array<number>(b.length + 1).fill(0));
  for (let i = a.length - 1; i >= 0; i -= 1) {
    for (let j = b.length - 1; j >= 0; j -= 1) {
      lcs[i][j] = a[i].trim() === b[j].trim() ? lcs[i + 1][j + 1] + 1 : Math.max(lcs[i + 1][j], lcs[i][j + 1]);
    }
  }
  const parts: DiffPart[] = [];
  const push = (kind: DiffPart["kind"], text: string) => {
    const last = parts[parts.length - 1];
    if (last && last.kind === kind) last.text += text;
    else parts.push({ kind, text });
  };
  let i = 0;
  let j = 0;
  while (i < a.length && j < b.length) {
    if (a[i].trim() === b[j].trim()) {
      push("same", b[j]);
      i += 1;
      j += 1;
    } else if (lcs[i + 1][j] >= lcs[i][j + 1]) {
      push("removed", a[i]);
      i += 1;
    } else {
      push("added", b[j]);
      j += 1;
    }
  }
  while (i < a.length) push("removed", a[i++]);
  while (j < b.length) push("added", b[j++]);
  return parts;
}

/** How much of the two texts the difference touches: 0 when identical, 1 when nothing is
 * shared. The screen shows a word diff below this, and the two texts side by side above
 * it, where a diff would be noise. */
export function changedShare(parts: DiffPart[]): number {
  const total = parts.reduce((n, p) => n + words(p.text).length, 0);
  if (total === 0) return 0;
  const changed = parts.filter((p) => p.kind !== "same").reduce((n, p) => n + words(p.text).length, 0);
  return changed / total;
}

/** A numeric change as "12 → 15 (+3)"; null when either side is not a plain number. */
export function numericDelta(before: unknown, after: unknown): string | null {
  const a = typeof before === "number" ? before : Number(before);
  const b = typeof after === "number" ? after : Number(after);
  if (before === null || after === null || before === "" || after === "" || Number.isNaN(a) || Number.isNaN(b)) return null;
  const delta = b - a;
  const sign = delta > 0 ? "+" : "";
  const pct = a !== 0 ? ` (${sign}${Math.round((delta / a) * 1000) / 10}%)` : "";
  return `${sign}${Number.isInteger(delta) ? delta : Math.round(delta * 1000) / 1000}${pct}`;
}
