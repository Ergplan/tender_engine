import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";

vi.mock("./review/pdfText", () => ({ openPdf: async () => ({}) }));

function respond(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

afterEach(() => vi.unstubAllGlobals());

describe("App", () => {
  it("asks for a sign-in when the address is not a review link and nobody is signed in", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(respond(401, { error_type: "login_required", message: "Sign in." })));
    render(<App path="/" />);
    expect(await screen.findByRole("button", { name: "Sign in with Google" })).toBeInTheDocument();
  });

  it("routes a signed-in user to the library, a tender and the admin page", async () => {
    const me = { kind: "user", name: "Asha", role: "admin", tenant_id: "ergplan" };
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) =>
        Promise.resolve(url === "/api/v1/auth/me" ? respond(200, me) : respond(200, [])),
      ),
    );
    render(<App path="/tenders" />);
    expect(await screen.findByRole("heading", { level: 1, name: "Tenders" })).toBeInTheDocument();
    render(<App path="/admin" />);
    expect(await screen.findByRole("heading", { level: 1, name: "Admin" })).toBeInTheDocument();
  });

  it("sends the token with every call and keeps it for the files the browser fetches", async () => {
    const token = "A".repeat(32);
    const fetchMock = vi.fn().mockResolvedValue(
      respond(410, { error_type: "review_link_expired", message: "This review link has expired. Ask for a new one." }),
    );
    vi.stubGlobal("fetch", fetchMock);
    render(<App path={`/review/${token}`} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("This review link has expired. Ask for a new one.");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/review-session");
    expect(init.headers["X-Review-Token"]).toBe(token);
    expect(document.cookie).toContain(`review_token=${token}`);
  });

  it("shows a plain message when the API cannot be reached", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("network down")));
    render(<App path={`/review/${"B".repeat(32)}`} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Check your connection and reload");
  });
});
