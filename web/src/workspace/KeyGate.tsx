import { useState } from "react";

import { ApiError, workspaceApi } from "../api/client";

/** The door to the workspace: an access key (an API key an administrator minted), checked
 * against the engine before it is kept. */
export function KeyGate({ onKey, message }: { onKey: (key: string) => void; message?: string | null }) {
  const [key, setKey] = useState("");
  const [error, setError] = useState<string | null>(message ?? null);
  const [checking, setChecking] = useState(false);

  async function check(event: React.FormEvent) {
    event.preventDefault();
    const trimmed = key.trim();
    if (!trimmed) return;
    setChecking(true);
    setError(null);
    try {
      await workspaceApi(trimmed).tenders();
      onKey(trimmed);
    } catch (caught) {
      setError(
        caught instanceof ApiError && (caught.status === 401 || caught.status === 403)
          ? "That key was not accepted. Check it was copied whole, or ask for a new one."
          : "The engine could not be reached. Check your connection and try again.",
      );
    } finally {
      setChecking(false);
    }
  }

  return (
    <main className="flex min-h-full items-center justify-center bg-[#f2f5f4] p-6 font-sans text-[#1b2a2f]">
      <form onSubmit={check} className="w-full max-w-md rounded-xl border border-[#dde4e2] bg-white p-8 shadow-sm">
        <div className="flex items-center gap-3">
          <Mark />
          <h1 className="text-xl font-semibold">Tender workspace</h1>
        </div>
        <p className="mt-3 text-sm leading-6 text-[#5b6b70]">
          Drop a tender, see what it asks of a bidder with the page each answer comes from, and follow its
          amendments. Enter the access key your administrator gave you; it stays in this browser.
        </p>
        <label htmlFor="workspace-key" className="mt-6 block text-sm font-medium">
          Access key
        </label>
        <input
          id="workspace-key"
          type="password"
          autoComplete="off"
          spellCheck={false}
          value={key}
          onChange={(e) => setKey(e.target.value)}
          placeholder="tie_live_…"
          className="mt-2 w-full rounded-md border border-[#c9d3d0] px-3 py-2.5 text-sm outline-none focus:border-[#0f5f5c] focus:ring-2 focus:ring-[#0f5f5c]/25"
        />
        {error && (
          <p role="alert" className="mt-3 text-sm text-[#9f1239]">
            {error}
          </p>
        )}
        <button
          type="submit"
          disabled={checking || !key.trim()}
          className="mt-5 min-h-[44px] w-full rounded-md bg-[#0f5f5c] text-sm font-medium text-white hover:bg-[#0a4341] disabled:opacity-50"
        >
          {checking ? "Checking the key…" : "Open the workspace"}
        </button>
        <p className="mt-4 text-center text-sm text-[#5b6b70]">
          Have a username and password?{" "}
          <a href="/" className="text-[#0f5f5c] underline">
            Sign in
          </a>
        </p>
      </form>
    </main>
  );
}

export function Mark() {
  return (
    <svg width="28" height="28" viewBox="0 0 26 26" aria-hidden="true">
      <rect x="2" y="2" width="22" height="22" rx="5" fill="#0f5f5c" />
      <rect x="6" y="11" width="14" height="4" rx="1" fill="#fde68a" />
      <path d="M7 7.5h9M7 19h6" stroke="#fff" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}
