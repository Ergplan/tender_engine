// The reviewer's keys. Pure: the screen decides what each action does.

export type KeyAction =
  | "approve"
  | "edit"
  | "not_in_document"
  | "flag"
  | "clear"
  | "next"
  | "previous"
  | "cancel";

const KEYS: Record<string, KeyAction> = {
  Enter: "approve",
  e: "edit",
  n: "not_in_document",
  f: "flag",
  u: "clear",
  j: "next",
  k: "previous",
  Escape: "cancel",
};

/** The action of a key press, or null. Typing in a form field does nothing but Escape. */
export function keyAction(event: {
  key: string;
  ctrlKey: boolean;
  metaKey: boolean;
  altKey: boolean;
  target: EventTarget | null;
}): KeyAction | null {
  if (event.ctrlKey || event.metaKey || event.altKey) return null;
  const action = KEYS[event.key.length === 1 ? event.key.toLowerCase() : event.key] ?? null;
  const element = event.target as HTMLElement | null;
  const typing =
    !!element &&
    typeof element.tagName === "string" &&
    (["INPUT", "TEXTAREA", "SELECT"].includes(element.tagName) || element.isContentEditable);
  if (typing) return action === "cancel" ? action : null;
  // A focused button keeps its own Enter.
  if (action === "approve" && element && element.tagName === "BUTTON") return null;
  return action;
}

/** The next path after `from` in `paths` that satisfies `wanted`, wrapping once; else null. */
export function nextWhere(
  paths: string[],
  from: string | null,
  wanted: (path: string) => boolean,
): string | null {
  const start = from === null ? -1 : paths.indexOf(from);
  for (let step = 1; step <= paths.length; step += 1) {
    const path = paths[(start + step + paths.length) % paths.length];
    if (wanted(path)) return path;
  }
  return null;
}

export function neighbour(paths: string[], from: string | null, step: 1 | -1): string | null {
  if (paths.length === 0) return null;
  const index = from === null ? -1 : paths.indexOf(from);
  if (index === -1) return step === 1 ? paths[0] : paths[paths.length - 1];
  return paths[Math.min(Math.max(index + step, 0), paths.length - 1)];
}
