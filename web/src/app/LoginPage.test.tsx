import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LoginPage } from "./LoginPage";

function respond(status: number, body: unknown) {
  return new Response(body === null ? null : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => vi.unstubAllGlobals());

describe("LoginPage", () => {
  it("signs in with a username and password and goes on to the workspace", async () => {
    const fetchMock = vi.fn().mockResolvedValue(respond(204, null));
    const assign = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("location", { ...window.location, pathname: "/", search: "", assign });
    render(<LoginPage message={null} />);
    fireEvent.change(screen.getByLabelText("Username"), { target: { value: " admin " } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "a-long-password" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await vi.waitFor(() => expect(assign).toHaveBeenCalledWith("/workspace"));
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/auth/password");
    expect(JSON.parse(init.body)).toEqual({ username: "admin", password: "a-long-password" });
  });

  it("says plainly when the username or password is wrong", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(respond(401, { error_type: "login_failed", message: "Wrong username or password." })),
    );
    render(<LoginPage message={null} />);
    fireEvent.change(screen.getByLabelText("Username"), { target: { value: "admin" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "nope" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Wrong username or password.");
  });
});
