// The workspace's access key, kept in this browser only. Storage can be unavailable (a
// private window, blocked site data), so every access is guarded and the key then lives
// for the page's life alone.
const NAME = "tender-engine.workspace-key";
let memory: string | null = null;

export function loadKey(): string | null {
  try {
    return window.localStorage.getItem(NAME);
  } catch {
    return memory;
  }
}

export function saveKey(key: string): void {
  memory = key;
  try {
    window.localStorage.setItem(NAME, key);
  } catch {
    /* kept in memory for this page */
  }
}

export function forgetKey(): void {
  memory = null;
  try {
    window.localStorage.removeItem(NAME);
  } catch {
    /* nothing stored */
  }
}
