import { useEffect, useState } from "react";

import { api, ApiError, type Health } from "./api/client";

type State =
  | { kind: "loading" }
  | { kind: "ok"; health: Health }
  | { kind: "error"; message: string };

export function App() {
  const [state, setState] = useState<State>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;
    api
      .health()
      .then((health) => !cancelled && setState({ kind: "ok", health }))
      .catch((error: unknown) => {
        const message = error instanceof ApiError ? error.message : "The API is not reachable.";
        if (!cancelled) setState({ kind: "error", message });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <main className="mx-auto max-w-2xl p-8 font-sans text-slate-900">
      <h1 className="text-2xl font-semibold">Tender Intelligence Engine</h1>
      <p className="mt-2 text-sm text-slate-600">
        Stage 0 scaffold. The reviewer screen arrives in Stage 3.
      </p>
      <section className="mt-6 rounded border border-slate-200 p-4" aria-label="System status">
        {state.kind === "loading" && <p>Checking the API…</p>}
        {state.kind === "ok" && (
          <p>
            <span className="mr-2 inline-block h-2 w-2 rounded-full bg-green-600" />
            API and database are up. Tenant: <strong>{state.health.tenant_id}</strong>
          </p>
        )}
        {state.kind === "error" && (
          <p role="alert" className="text-red-700">
            {state.message}
          </p>
        )}
      </section>
    </main>
  );
}
