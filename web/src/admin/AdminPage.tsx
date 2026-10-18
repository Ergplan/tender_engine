import { type FormEvent, useEffect, useState } from "react";

import { ApiError, appApi } from "../api/client";
import type { AdminUser, ApiKeyInfo, TenderListItem, Usage, UserPatch } from "../api/types5c";
import { showDate } from "../library/format";

type UserRole = NonNullable<UserPatch["role"]>;
type Scope = "read" | "model";
const ROLES: UserRole[] = ["reviewer", "approver", "admin"];
const SCOPES: Scope[] = ["read", "model"];

function message(caught: unknown): string {
  return caught instanceof ApiError ? caught.message : "The API is not reachable.";
}

function Users({ users, onChange }: { users: AdminUser[]; onChange: (user: AdminUser) => void }) {
  const [error, setError] = useState<string | null>(null);
  const update = async (user: AdminUser, body: UserPatch) => {
    try {
      onChange(await appApi.updateUser(user.id, body));
    } catch (caught: unknown) {
      setError(message(caught));
    }
  };
  return (
    <section className="overflow-x-auto rounded-lg border border-[#e6e4dd] bg-white">
      <h2 className="border-b border-[#e6e4dd] px-3 py-3 text-sm font-semibold">Users</h2>
      {error && (
        <p role="alert" className="px-3 py-2 text-sm text-[#991b1b]">
          {error}
        </p>
      )}
      <table className="w-full min-w-[640px] border-collapse text-sm">
        <thead>
          <tr className="text-left text-xs uppercase tracking-wide text-slate-600">
            {["User", "Role", "Status", "Last sign-in"].map((h) => (
              <th key={h} className="border-b border-[#e6e4dd] px-3 py-2 font-medium">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {users.map((user) => (
            <tr key={user.id}>
              <td className="border-b border-[#e6e4dd] px-3 py-2">
                <div className="font-medium">{user.display_name}</div>
                <div className="text-xs text-slate-600">{user.email}</div>
              </td>
              <td className="border-b border-[#e6e4dd] px-3 py-2">
                <label className="sr-only" htmlFor={`role-${user.id}`}>
                  Role of {user.email}
                </label>
                <select
                  id={`role-${user.id}`}
                  value={user.role}
                  className="min-h-[44px] rounded-md border border-[#cfccc3] bg-white px-2 text-sm"
                  onChange={(e) => void update(user, { role: e.target.value as UserRole })}
                >
                  {!ROLES.includes(user.role as UserRole) && <option value={user.role}>{user.role}</option>}
                  {ROLES.map((r) => (
                    <option key={r} value={r}>
                      {r}
                    </option>
                  ))}
                </select>
              </td>
              <td className="border-b border-[#e6e4dd] px-3 py-2">
                <button
                  type="button"
                  className="min-h-[44px] rounded-md border border-[#cfccc3] bg-white px-3 text-sm"
                  onClick={() => void update(user, { status: user.status === "active" ? "disabled" : "active" })}
                >
                  {user.status === "active" ? "Disable" : "Enable"}
                </button>{" "}
                <span className="text-xs text-slate-600">{user.status}</span>
              </td>
              <td className="border-b border-[#e6e4dd] px-3 py-2 text-slate-600">{showDate(user.last_login_at)}</td>
            </tr>
          ))}
          {users.length === 0 && (
            <tr>
              <td colSpan={4} className="px-3 py-4 text-slate-600">
                No user has signed in yet.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </section>
  );
}

function ApiKeys({ keys, onChange }: { keys: ApiKeyInfo[]; onChange: (keys: ApiKeyInfo[]) => void }) {
  const [name, setName] = useState("");
  const [scopes, setScopes] = useState<Scope[]>(["read"]);
  const [raw, setRaw] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const create = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    try {
      const made = await appApi.createApiKey({ name: name.trim(), scopes });
      setRaw(made.secret);
      setName("");
      onChange([...keys, made.key]);
    } catch (caught: unknown) {
      setError(message(caught));
    }
  };
  const revoke = async (key: ApiKeyInfo) => {
    try {
      await appApi.revokeApiKey(key.id);
      onChange(keys.map((k) => (k.id === key.id ? { ...k, revoked_at: new Date().toISOString() } : k)));
    } catch (caught: unknown) {
      setError(message(caught));
    }
  };

  return (
    <section className="rounded-lg border border-[#e6e4dd] bg-white">
      <h2 className="border-b border-[#e6e4dd] px-3 py-3 text-sm font-semibold">API keys (intelligence API)</h2>
      {raw && (
        <div role="status" className="m-3 rounded-md border border-[#f1d7b3] bg-[#fdf1e3] p-3 text-sm text-[#6b3a08]">
          <div className="font-semibold">Copy this key now; it is shown once.</div>
          <code data-testid="raw-key" className="mt-1 block select-all break-all rounded bg-white px-2 py-1 font-mono text-xs">
            {raw}
          </code>
          <button
            type="button"
            className="mt-2 min-h-[44px] rounded-md border border-[#cfccc3] bg-white px-3 text-sm"
            onClick={() => setRaw(null)}
          >
            I have copied it
          </button>
        </div>
      )}
      {error && (
        <p role="alert" className="px-3 py-2 text-sm text-[#991b1b]">
          {error}
        </p>
      )}
      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] border-collapse text-sm">
          <thead>
            <tr className="text-left text-xs uppercase tracking-wide text-slate-600">
              {["Key", "Scopes", "Limits", "Created", "Last used", ""].map((h) => (
                <th key={h} className="border-b border-[#e6e4dd] px-3 py-2 font-medium">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {keys.map((key) => (
              <tr key={key.id} className={key.revoked_at ? "text-slate-400" : ""}>
                <td className="border-b border-[#e6e4dd] px-3 py-2">
                  <div className="font-medium">{key.name}</div>
                  <div className="font-mono text-xs">{key.prefix}…</div>
                </td>
                <td className="border-b border-[#e6e4dd] px-3 py-2">{key.scopes.join(", ")}</td>
                <td className="border-b border-[#e6e4dd] px-3 py-2">
                  {key.rate_limit_per_min}/min · {key.daily_cap}/day
                </td>
                <td className="border-b border-[#e6e4dd] px-3 py-2">{showDate(key.created_at)}</td>
                <td className="border-b border-[#e6e4dd] px-3 py-2">{showDate(key.last_used_at)}</td>
                <td className="border-b border-[#e6e4dd] px-3 py-2">
                  {key.revoked_at ? (
                    "revoked"
                  ) : (
                    <button
                      type="button"
                      className="min-h-[44px] rounded-md border border-[#cfccc3] bg-white px-3 text-sm"
                      onClick={() => void revoke(key)}
                    >
                      Revoke
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <form className="flex flex-wrap items-end gap-3 border-t border-[#e6e4dd] p-3" onSubmit={(e) => void create(e)}>
        <label className="flex flex-col gap-1 text-xs text-slate-600">
          Key name
          <input
            required
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="min-h-[44px] rounded-md border border-[#cfccc3] px-3 text-sm"
          />
        </label>
        <fieldset className="flex items-center gap-3 text-sm">
          <legend className="text-xs text-slate-600">Scopes</legend>
          {SCOPES.map((scope) => (
            <label key={scope} className="flex min-h-[44px] items-center gap-1">
              <input
                type="checkbox"
                checked={scopes.includes(scope)}
                onChange={(e) =>
                  setScopes(e.target.checked ? [...scopes, scope] : scopes.filter((s) => s !== scope))
                }
              />
              {scope}
            </label>
          ))}
        </fieldset>
        <button type="submit" className="min-h-[44px] rounded-md bg-[#0f5f5c] px-4 text-sm font-medium text-white">
          Create key
        </button>
      </form>
    </section>
  );
}

function ReviewLinks({ tenders }: { tenders: TenderListItem[] }) {
  const [tenderId, setTenderId] = useState("");
  const [reviewer, setReviewer] = useState("");
  const [url, setUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    try {
      setUrl((await appApi.createReviewToken({ tender: tenderId, reviewer_name: reviewer.trim() })).url);
    } catch (caught: unknown) {
      setError(message(caught));
    }
  };
  return (
    <section className="rounded-lg border border-[#e6e4dd] bg-white">
      <h2 className="border-b border-[#e6e4dd] px-3 py-3 text-sm font-semibold">Review links for external reviewers</h2>
      <form className="flex flex-wrap items-end gap-3 p-3" onSubmit={(e) => void submit(e)}>
        <label className="flex flex-col gap-1 text-xs text-slate-600">
          Tender
          <select
            required
            value={tenderId}
            onChange={(e) => setTenderId(e.target.value)}
            className="min-h-[44px] min-w-[240px] rounded-md border border-[#cfccc3] bg-white px-2 text-sm"
          >
            <option value="">Choose…</option>
            {tenders.map((t) => (
              <option key={t.id} value={t.id}>
                {t.title}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs text-slate-600">
          Reviewer name
          <input
            required
            value={reviewer}
            onChange={(e) => setReviewer(e.target.value)}
            className="min-h-[44px] rounded-md border border-[#cfccc3] px-3 text-sm"
          />
        </label>
        <button type="submit" className="min-h-[44px] rounded-md bg-[#0f5f5c] px-4 text-sm font-medium text-white">
          Create link
        </button>
      </form>
      {url && (
        <p role="status" className="px-3 pb-3 text-sm">
          Send this link once; it replaces any earlier link for the tender:{" "}
          <code className="select-all break-all font-mono text-xs">{url}</code>
        </p>
      )}
      {error && (
        <p role="alert" className="px-3 pb-3 text-sm text-[#991b1b]">
          {error}
        </p>
      )}
    </section>
  );
}

function UsageTable({ usage }: { usage: Usage | null }) {
  return (
    <section className="rounded-lg border border-[#e6e4dd] bg-white">
      <h2 className="border-b border-[#e6e4dd] px-3 py-3 text-sm font-semibold">Usage, last 30 days</h2>
      {!usage ? (
        <p className="p-3 text-sm text-slate-600">Loading…</p>
      ) : (
        <div className="grid gap-3 p-3 text-sm md:grid-cols-2">
          <table className="border-collapse">
            <thead>
              <tr className="text-left text-xs uppercase tracking-wide text-slate-600">
                <th className="border-b border-[#e6e4dd] px-2 py-1 font-medium">Tool</th>
                <th className="border-b border-[#e6e4dd] px-2 py-1 font-medium">Calls</th>
              </tr>
            </thead>
            <tbody>
              {usage.by_tool.map((row) => (
                <tr key={row.tool}>
                  <td className="border-b border-[#e6e4dd] px-2 py-1 font-mono text-xs">{row.tool}</td>
                  <td className="border-b border-[#e6e4dd] px-2 py-1">{row.calls}</td>
                </tr>
              ))}
              {usage.by_tool.length === 0 && (
                <tr>
                  <td colSpan={2} className="px-2 py-2 text-slate-600">
                    No metered call yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
          <table className="border-collapse">
            <thead>
              <tr className="text-left text-xs uppercase tracking-wide text-slate-600">
                <th className="border-b border-[#e6e4dd] px-2 py-1 font-medium">API key</th>
                <th className="border-b border-[#e6e4dd] px-2 py-1 font-medium">Calls</th>
              </tr>
            </thead>
            <tbody>
              {usage.by_key.map((row, i) => (
                <tr key={row.api_key_id ?? `none-${i}`}>
                  <td className="border-b border-[#e6e4dd] px-2 py-1">{row.name ?? "(no key: a signed-in user)"}</td>
                  <td className="border-b border-[#e6e4dd] px-2 py-1">{row.calls}</td>
                </tr>
              ))}
              {usage.by_key.length === 0 && (
                <tr>
                  <td colSpan={2} className="px-2 py-2 text-slate-600">
                    No key has been used.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

/** /admin: users and roles, API keys, review links, usage. Admins only; the server refuses
 * the rest, and the page shows the refusal in plain words. */
export function AdminPage() {
  const [users, setUsers] = useState<AdminUser[] | null>(null);
  const [keys, setKeys] = useState<ApiKeyInfo[] | null>(null);
  const [tenders, setTenders] = useState<TenderListItem[]>([]);
  const [usage, setUsage] = useState<Usage | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const [u, k, t] = await Promise.all([appApi.users(), appApi.apiKeys(), appApi.tenders()]);
      if (cancelled) return;
      setUsers(u);
      setKeys(k);
      setTenders(t);
      const used = await appApi.usage(30).catch(() => null);
      setUsage({ days: 30, calls: used?.calls ?? 0, by_tool: used?.by_tool ?? [], by_key: used?.by_key ?? [] });
    })().catch((caught: unknown) => {
      if (!cancelled) setError(message(caught));
    });
    return () => {
      cancelled = true;
    };
  }, []);

  if (error)
    return (
      <main className="p-8">
        <p role="alert" className="text-sm text-[#991b1b]">
          {error}
        </p>
      </main>
    );
  if (!users || !keys) return <p className="p-8 text-slate-600">Loading the admin page…</p>;
  return (
    <main className="mx-auto flex w-full max-w-[1216px] flex-col gap-5 px-8 py-7">
      <h1 className="text-2xl font-semibold">Admin</h1>
      <Users users={users} onChange={(user) => setUsers(users.map((u) => (u.id === user.id ? user : u)))} />
      <ApiKeys keys={keys} onChange={setKeys} />
      <ReviewLinks tenders={tenders} />
      <UsageTable usage={usage} />
    </main>
  );
}
