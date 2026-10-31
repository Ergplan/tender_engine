import { useState } from "react";

import { ApiError, appApi } from "../api/client";
import { Mark } from "../workspace/KeyGate";

/** Where to go after signing in: a path of this origin, else the workspace. */
function nextPath(): string {
  const next = new URLSearchParams(window.location.search).get("next");
  if (next && next.startsWith("/") && !next.startsWith("//")) return next;
  const here = window.location.pathname;
  return here && here !== "/" ? here : "/workspace";
}

/** The sign-in page: a username and password (2026-10-31), or the organisation's Google
 * account where that is configured. Reviewers who were sent a link do not sign in. */
export function LoginPage({ message }: { message: string | null }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function signIn(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await appApi.passwordLogin(username.trim(), password);
      window.location.assign(nextPath());
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "The engine could not be reached. Try again.");
      setBusy(false);
    }
  }

  return (
    <main className="flex min-h-full items-center justify-center bg-[#f2f5f4] p-6 font-sans text-[#1b2a2f]">
      <div className="w-full max-w-sm">
        <div className="flex items-center gap-3">
          <Mark />
          <h1 className="text-xl font-semibold">Tender Intelligence Engine</h1>
        </div>
        {message && (
          <p role="alert" className="mt-4 rounded-md border border-[#f3c4cf] bg-[#fdf2f4] px-3 py-2 text-sm text-[#9f1239]">
            {message}
          </p>
        )}
        <form onSubmit={signIn} className="mt-6 rounded-xl border border-[#dde4e2] bg-white p-6 shadow-sm">
          <label htmlFor="login-username" className="block text-sm font-medium">
            Username
          </label>
          <input
            id="login-username"
            autoComplete="username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            className="mt-1 w-full rounded-md border border-[#c9d3d0] px-3 py-2.5 text-sm outline-none focus:border-[#0f5f5c] focus:ring-2 focus:ring-[#0f5f5c]/25"
          />
          <label htmlFor="login-password" className="mt-4 block text-sm font-medium">
            Password
          </label>
          <input
            id="login-password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="mt-1 w-full rounded-md border border-[#c9d3d0] px-3 py-2.5 text-sm outline-none focus:border-[#0f5f5c] focus:ring-2 focus:ring-[#0f5f5c]/25"
          />
          {error && (
            <p role="alert" className="mt-3 text-sm text-[#9f1239]">
              {error}
            </p>
          )}
          <button
            type="submit"
            disabled={busy || !username.trim() || !password}
            className="mt-5 min-h-[44px] w-full rounded-md bg-[#0f5f5c] text-sm font-medium text-white hover:bg-[#0a4341] disabled:opacity-50"
          >
            {busy ? "Signing in…" : "Sign in"}
          </button>
        </form>
        <div className="mt-5 space-y-2 text-xs text-[#5b6b70]">
          <p>
            Were you sent a review link? Open that link instead; it needs no account.
          </p>
          <p>
            Have an access key instead?{" "}
            <a href="/workspace" className="text-[#0f5f5c] underline">
              Open the tender workspace
            </a>
            . Organisation account?{" "}
            <button
              type="button"
              className="text-[#0f5f5c] underline"
              onClick={() => window.location.assign("/api/v1/auth/login")}
            >
              Sign in with Google
            </button>
          </p>
        </div>
      </div>
    </main>
  );
}
