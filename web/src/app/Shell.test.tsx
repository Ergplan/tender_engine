import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Shell } from "./Shell";

function respond(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

afterEach(() => vi.unstubAllGlobals());

describe("Shell", () => {
  it("shows the sign-in page when nobody is signed in", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(respond(401, { error_type: "login_required", message: "Sign in." })));
    render(
      <Shell path="/tenders">
        <p>the page</p>
      </Shell>,
    );
    expect(await screen.findByRole("button", { name: "Sign in with Google" })).toBeInTheDocument();
    expect(screen.queryByText("the page")).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("shows who is signed in, the admin link for admins, and the page", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(respond(200, { kind: "user", name: "Asha Rao", role: "admin", tenant_id: "ergplan" })),
    );
    render(
      <Shell path="/tenders">
        <p>the page</p>
      </Shell>,
    );
    expect(await screen.findByText("the page")).toBeInTheDocument();
    expect(screen.getByText("Asha Rao · admin")).toBeInTheDocument();
    expect(screen.getByText("tenant: ergplan")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Admin" })).toHaveAttribute("href", "/admin");
    expect(screen.getByRole("link", { name: "Tenders" })).toHaveAttribute("aria-current", "page");
  });

  it("hides the admin link from a reviewer", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(respond(200, { kind: "user", name: "Ravi", role: "reviewer", tenant_id: "ergplan" })),
    );
    render(
      <Shell path="/">
        <p>the page</p>
      </Shell>,
    );
    await screen.findByText("the page");
    expect(screen.queryByRole("link", { name: "Admin" })).not.toBeInTheDocument();
  });

  it("says when the API cannot be reached", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("down")));
    render(
      <Shell path="/">
        <p>the page</p>
      </Shell>,
    );
    expect(await screen.findByRole("alert")).toHaveTextContent("The API is not reachable.");
  });
});
