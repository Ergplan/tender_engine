// How long the rest of a review may take, from the reviewer's own pace in this sitting.

export const MIN_DECISIONS = 5;

/** Minutes left for `undecided` fields, or null until there are enough decisions to say.
 * `times` are the moments (ms) of the decisions made in this sitting. The pace is the
 * median gap between them, so one long pause does not stretch the estimate. */
export function minutesLeft(times: number[], undecided: number): number | null {
  if (times.length < MIN_DECISIONS || undecided <= 0) return null;
  const gaps = times
    .slice(1)
    .map((time, index) => time - times[index])
    .sort((a, b) => a - b);
  const middle = Math.floor(gaps.length / 2);
  const median = gaps.length % 2 ? gaps[middle] : (gaps[middle - 1] + gaps[middle]) / 2;
  return Math.max(1, Math.round((median * undecided) / 60000));
}
