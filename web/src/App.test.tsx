import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";

function mockFetch(status: number, body: unknown) {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(JSON.stringify(body), {
        status,
        headers: { "Content-Type": "application/json", "X-Request-Id": "req-1" },
      }),
    ),
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("App", () => {
  it("shows the tenant when the API is healthy", async () => {
    mockFetch(200, { status: "ok", tenant_id: "ergplan", database: "ok" });
    render(<App />);
    expect(await screen.findByText("ergplan")).toBeInTheDocument();
    expect(fetch).toHaveBeenCalledWith("/api/v1/health", expect.anything());
  });

  it("shows the API's own message when it reports an error", async () => {
    mockFetch(503, {
      error_type: "dependency_unavailable",
      message: "A required service is not available. Try again shortly.",
      request_id: "req-1",
    });
    render(<App />);
    expect(await screen.findByRole("alert")).toHaveTextContent("A required service is not available");
  });

  it("shows a plain message when the API cannot be reached", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("network down")));
    render(<App />);
    expect(await screen.findByRole("alert")).toHaveTextContent("The API is not reachable.");
  });
});
