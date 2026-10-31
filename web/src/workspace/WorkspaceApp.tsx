import { useCallback, useEffect, useMemo, useState } from "react";

import { ApiError, appApi, type TenderSummary, workspaceApi } from "../api/client";
import { DropZone } from "./DropZone";
import { KeyGate, Mark } from "./KeyGate";
import { forgetKey, loadKey, saveKey } from "./keyStore";
import { TenderView } from "./TenderView";

const STATUS_LABEL: Record<string, string> = {
  ingested: "Reading",
  extracted: "Read",
  in_review: "In review",
  reviewed: "Reviewed",
  published: "Reviewed",
  superseded: "Replaced",
};

function go(tenderId: string | null) {
  const path = tenderId ? `/workspace/${tenderId}` : "/workspace";
  if (window.location.pathname !== path) window.history.pushState(null, "", path);
}

/** /workspace: drop a tender in, open any tender read so far, and see its analysis. */
export function WorkspaceApp({ initialTender = null }: { initialTender?: string | null }) {
  const [key, setKey] = useState<string | null>(() => loadKey());
  // Signed in with a username and password (2026-10-31): the session cookie stands in for
  // a key. "checking" while the engine is asked who this browser is.
  const [session, setSession] = useState<"checking" | "signed_in" | "none">(() => (loadKey() ? "none" : "checking"));
  const [refused, setRefused] = useState<string | null>(null);
  const api = useMemo(
    () => (key ? workspaceApi(key) : session === "signed_in" ? workspaceApi("") : null),
    [key, session],
  );

  useEffect(() => {
    if (key || session !== "checking") return;
    let cancelled = false;
    appApi
      .me()
      .then((me) => !cancelled && setSession(me.kind === "user" ? "signed_in" : "none"))
      .catch(() => !cancelled && setSession("none"));
    return () => {
      cancelled = true;
    };
  }, [key, session]);
  const [tenders, setTenders] = useState<TenderSummary[] | null>(null);
  const [selected, setSelected] = useState<string | null>(initialTender);
  const [query, setQuery] = useState("");

  const refresh = useCallback(async () => {
    if (!api) return;
    try {
      const list = await api.tenders();
      setTenders(list.filter((t) => t.status !== "superseded"));
    } catch (caught) {
      if (caught instanceof ApiError && (caught.status === 401 || caught.status === 403)) {
        forgetKey();
        setKey(null);
        setSession("none");
        setRefused(
          key ? "The access key is no longer accepted. Enter a current one." : "Your session has ended. Sign in again.",
        );
      }
    }
  }, [api, key]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    const onPop = () => {
      const match = /^\/workspace\/([0-9a-f]{32})\/?$/.exec(window.location.pathname);
      setSelected(match ? match[1] : null);
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const shown = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return (tenders ?? [])
      .filter((t) => !needle || `${t.title} ${t.issuing_agency} ${t.external_ref ?? ""}`.toLowerCase().includes(needle))
      .sort((a, b) => b.created_at.localeCompare(a.created_at));
  }, [tenders, query]);

  if (!api && session === "checking") return <p className="p-8 font-sans text-sm text-[#5b6b70]">Opening the workspace…</p>;
  if (!api)
    return (
      <KeyGate
        message={refused}
        onKey={(k) => {
          saveKey(k);
          setRefused(null);
          setKey(k);
        }}
      />
    );

  const open = (id: string | null) => {
    setSelected(id);
    go(id);
  };

  return (
    <div className="flex h-full min-h-0 flex-col bg-white font-sans text-[#1b2a2f] lg:flex-row">
      <aside className="flex w-full shrink-0 flex-col border-b border-[#dde4e2] bg-[#f2f5f4] lg:h-full lg:w-[320px] lg:border-b-0 lg:border-r">
        <div className="flex items-center gap-2.5 px-5 pb-3 pt-5">
          <Mark />
          <span className="text-[15px] font-semibold">Tender workspace</span>
          <button
            type="button"
            onClick={() => {
              forgetKey();
              setKey(null);
              if (!key) void appApi.logout().finally(() => window.location.assign("/"));
            }}
            className="ml-auto text-xs text-[#5b6b70] hover:text-[#1b2a2f]"
          >
            Sign out
          </button>
        </div>
        <div className="px-5">
          <button
            type="button"
            onClick={() => open(null)}
            aria-pressed={selected === null}
            className={`min-h-[40px] w-full rounded-md border text-sm font-medium ${
              selected === null ? "border-[#0f5f5c] bg-white text-[#0f5f5c]" : "border-[#c9d3d0] bg-white hover:border-[#0f5f5c]"
            }`}
          >
            Add a tender
          </button>
          <label htmlFor="tender-filter" className="sr-only">
            Find a tender
          </label>
          <input
            id="tender-filter"
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Find a tender"
            className="mt-3 w-full rounded-md border border-[#c9d3d0] bg-white px-3 py-2 text-sm outline-none focus:border-[#0f5f5c]"
          />
        </div>
        <nav aria-label="Tenders" className="mt-3 max-h-[40vh] flex-1 overflow-y-auto px-2 pb-4 lg:max-h-none">
          {tenders === null ? (
            <p className="px-3 text-sm text-[#5b6b70]">Loading…</p>
          ) : shown.length === 0 ? (
            <p className="px-3 text-sm text-[#5b6b70]">{query ? "No tender matches." : "No tender yet. Add the first one."}</p>
          ) : (
            <ul>
              {shown.map((t) => (
                <li key={t.id}>
                  <button
                    type="button"
                    onClick={() => open(t.id)}
                    aria-current={selected === t.id ? "page" : undefined}
                    className={`w-full rounded-md px-3 py-2.5 text-left ${
                      selected === t.id ? "bg-white shadow-sm ring-1 ring-[#dde4e2]" : "hover:bg-white/70"
                    }`}
                  >
                    <span className="line-clamp-2 text-sm font-medium leading-5">{t.title}</span>
                    <span className="mt-0.5 flex items-center gap-2 text-xs text-[#5b6b70]">
                      <span className="truncate">{t.issuing_agency}</span>
                      <span
                        className={`ml-auto shrink-0 rounded-full px-1.5 py-px ${
                          t.status === "ingested" ? "bg-[#fdf1e3] text-[#b45309]" : "bg-[#e6ecea] text-[#45555a]"
                        }`}
                      >
                        {STATUS_LABEL[t.status] ?? t.status}
                      </span>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </nav>
      </aside>
      <main className="min-h-0 flex-1 overflow-y-auto">
        {selected ? (
          <TenderView key={selected} api={api} tenderId={selected} onChanged={() => void refresh()} />
        ) : (
          <div className="mx-auto max-w-[620px] px-6 py-12">
            <h1 className="text-2xl font-semibold">Add a tender</h1>
            <p className="mt-2 text-[15px] leading-7 text-[#45555a]">
              The engine reads every page, pulls out what the tender asks of a bidder, and shows the page each answer
              comes from. Amendments added later show what they change.
            </p>
            <div className="mt-6">
              <DropZone
                onSubmit={async (form, type) => {
                  const made = await api.submit({ ...form, tenderType: type || undefined });
                  await refresh();
                  open(made.tender_id);
                }}
              />
            </div>
            <p className="mt-4 text-xs leading-5 text-[#5b6b70]">
              Reading uses the engine's model and costs about ₹4 a page; a 300-page tender takes 10 to 40 minutes.
              You can leave this page and come back.
            </p>
          </div>
        )}
      </main>
    </div>
  );
}
