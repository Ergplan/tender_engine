import { createContext, type ReactNode, useContext, useEffect, useState } from "react";

import { ApiError, appApi } from "../api/client";
import type { Me } from "../api/types5c";
import { LoginPage } from "./LoginPage";

type Auth = { kind: "loading" } | { kind: "signed_out"; message: string | null } | { kind: "signed_in"; me: Me };

const MeContext = createContext<Me | null>(null);

/** The signed-in user, for pages under the shell. */
export function useMe(): Me | null {
  return useContext(MeContext);
}

const NAV: { href: string; label: string; match: RegExp; admin?: boolean }[] = [
  { href: "/tenders", label: "Tenders", match: /^\/(tenders(\/.*)?)?$/ },
  { href: "/tenders?filter=review", label: "Reviews", match: /^\/tenders\?filter=review$/ },
  { href: "/admin/reliability", label: "Reliability", match: /^\/admin\/reliability/ },
  { href: "/admin", label: "Admin", match: /^\/admin\/?$/, admin: true },
];

/** The enterprise front end's frame: who is signed in, the navigation, and the page.
 * Signed out, the page is the sign-in page; reviewers with a link never pass here. */
export function Shell({ path, children }: { path: string; children: ReactNode }) {
  const [auth, setAuth] = useState<Auth>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;
    appApi
      .me()
      .then((me) => {
        if (!cancelled) setAuth({ kind: "signed_in", me });
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        const refused = error instanceof ApiError && error.status === 401;
        setAuth({
          kind: "signed_out",
          message: refused ? null : error instanceof ApiError ? error.message : "The API is not reachable.",
        });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (auth.kind === "loading") return <p className="p-8 font-sans text-slate-600">Signing you in…</p>;
  if (auth.kind === "signed_out") return <LoginPage message={auth.message} />;
  const me = auth.me;
  return (
    <MeContext.Provider value={me}>
      <div className="min-h-full bg-[#f6f5f1] font-sans text-slate-900">
        <header className="flex flex-wrap items-center gap-6 border-b border-[#e6e4dd] bg-white px-8 py-3">
          <a href="/tenders" className="flex items-center gap-2 text-base font-semibold no-underline">
            <svg width="24" height="24" viewBox="0 0 26 26" aria-hidden="true">
              <rect x="2" y="2" width="22" height="22" rx="5" fill="#0f5f5c" />
              <path d="M7 13h12M7 9h8M7 17h6" stroke="#fff" strokeWidth="2" strokeLinecap="round" />
            </svg>
            Tender Intelligence Engine
          </a>
          <nav aria-label="Main" className="flex gap-5 text-sm">
            {NAV.filter((item) => !item.admin || me.role === "admin").map((item) => {
              const active = item.match.test(path);
              return (
                <a
                  key={item.href}
                  href={item.href}
                  aria-current={active ? "page" : undefined}
                  className={
                    active
                      ? "border-b-2 border-[#0f5f5c] pb-1 font-semibold text-slate-900 no-underline"
                      : "text-[#0f5f5c] no-underline hover:text-[#0a4341]"
                  }
                >
                  {item.label}
                </a>
              );
            })}
          </nav>
          <div className="ml-auto flex items-center gap-3 text-sm">
            <span className="rounded-full bg-[#eef3f2] px-3 py-1 font-medium text-[#0f5f5c]">tenant: {me.tenant_id}</span>
            <span className="text-slate-600">
              {me.name} · {me.role}
            </span>
            <button
              type="button"
              className="min-h-[44px] rounded-md border border-[#cfccc3] bg-white px-3 text-sm"
              onClick={() => {
                void appApi.logout().finally(() => window.location.assign("/"));
              }}
            >
              Sign out
            </button>
          </div>
        </header>
        {children}
      </div>
    </MeContext.Provider>
  );
}
