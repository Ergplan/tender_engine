import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { TENDER } from "../library/fixtures5c";
import { AdminPage } from "./AdminPage";

function respond(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const USER = {
  id: "u1",
  email: "asha@example.org",
  display_name: "Asha Rao",
  role: "reviewer",
  status: "active",
  last_login_at: "2026-10-18T08:00:00+00:00",
  created_at: "2026-10-18T07:00:00+00:00",
};
const KEY = {
  id: "k1",
  name: "Analytics",
  prefix: "tie_live_4k9Q",
  scopes: ["read"],
  rate_limit_per_min: 60,
  daily_cap: 5000,
  created_at: "2026-10-18T08:00:00+00:00",
  created_by: "asha@example.org",
  expires_at: null,
  last_used_at: null,
  revoked_at: null,
};

afterEach(() => vi.unstubAllGlobals());

function serve() {
  return vi.fn((url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    if (url === "/api/v1/admin/users") return Promise.resolve(respond(200, [USER]));
    if (url === "/api/v1/admin/api-keys" && method === "GET") return Promise.resolve(respond(200, [KEY]));
    if (url === "/api/v1/admin/api-keys" && method === "POST") {
      const body = JSON.parse(String(init?.body)) as { name: string; scopes: string[] };
      return Promise.resolve(
        respond(200, { key: { ...KEY, id: "k2", name: body.name, scopes: body.scopes, prefix: "tie_live_m2Xe" }, secret: "tie_live_m2XeSECRET" }),
      );
    }
    if (url === "/api/v1/admin/api-keys/k1" && method === "DELETE") return Promise.resolve(respond(200, {}));
    if (url === "/api/v1/admin/users/u1" && method === "PATCH")
      return Promise.resolve(respond(200, { ...USER, ...(JSON.parse(String(init?.body)) as object) }));
    if (url === "/api/v1/admin/review-tokens" && method === "POST")
      return Promise.resolve(
        respond(200, {
          url: "https://example.org/review/TOKEN",
          token: "TOKEN",
          tender_id: TENDER.id,
          reviewer_name: "Ravi",
          expires_at: "2026-11-17T00:00:00+00:00",
        }),
      );
    if (url === "/api/v1/tenders") return Promise.resolve(respond(200, [TENDER]));
    if (url.startsWith("/api/v1/admin/usage"))
      return Promise.resolve(
        respond(200, { days: 30, calls: 12, by_tool: [{ tool: "get_tender", calls: 12, errors: 0 }], by_key: [] }),
      );
    return Promise.resolve(respond(404, { error_type: "not_found", message: "no" }));
  });
}

describe("AdminPage", () => {
  it("creates an API key and shows it once", async () => {
    const fetchMock = serve();
    vi.stubGlobal("fetch", fetchMock);
    render(<AdminPage />);
    expect(await screen.findByText("Analytics")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Key name"), { target: { value: "Modelling" } });
    fireEvent.click(screen.getByLabelText("model"));
    fireEvent.click(screen.getByRole("button", { name: "Create key" }));
    expect(await screen.findByTestId("raw-key")).toHaveTextContent("tie_live_m2XeSECRET");
    const post = fetchMock.mock.calls.find(([u, i]) => u === "/api/v1/admin/api-keys" && i?.method === "POST");
    expect(JSON.parse(String(post?.[1]?.body))).toEqual({ name: "Modelling", scopes: ["read", "model"] });
    expect(screen.getByText("Modelling")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "I have copied it" }));
    expect(screen.queryByTestId("raw-key")).not.toBeInTheDocument();
  });

  it("changes a role, disables a user, revokes a key and mints a review link", async () => {
    vi.stubGlobal("fetch", serve());
    render(<AdminPage />);
    await screen.findByText("Analytics");
    fireEvent.change(screen.getByLabelText("Role of asha@example.org"), { target: { value: "approver" } });
    await waitFor(() => expect(screen.getByLabelText("Role of asha@example.org")).toHaveValue("approver"));
    fireEvent.click(screen.getByRole("button", { name: "Disable" }));
    expect(await screen.findByRole("button", { name: "Enable" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Revoke" }));
    expect(await screen.findByText("revoked")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Tender"), { target: { value: TENDER.id } });
    fireEvent.change(screen.getByLabelText("Reviewer name"), { target: { value: "Ravi" } });
    fireEvent.click(screen.getByRole("button", { name: "Create link" }));
    expect(await screen.findByRole("status")).toHaveTextContent("https://example.org/review/TOKEN");
    expect(screen.getByText("get_tender")).toBeInTheDocument();
  });

  it("shows a refusal in plain words", async () => {
    // A fresh response per call: the page asks for users, keys and tenders at once.
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(respond(403, { error_type: "forbidden", message: "Admins only." }))),
    );
    render(<AdminPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Admins only.");
  });
});
