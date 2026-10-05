import { describe, expect, it } from "vitest";

import { keyAction, neighbour, nextWhere } from "./keyboard";

function press(key: string, target: Partial<HTMLElement> | null = null, extra = {}) {
  return keyAction({ key, ctrlKey: false, metaKey: false, altKey: false, target: target as EventTarget | null, ...extra });
}

describe("keyAction", () => {
  it("maps the reviewer's keys", () => {
    expect(["Enter", "e", "E", "n", "f", "j", "k", "Escape"].map((key) => press(key))).toEqual([
      "approve", "edit", "edit", "not_in_document", "flag", "next", "previous", "cancel",
    ]);
    expect(press("x")).toBeNull();
  });
  it("does nothing while typing, except Escape", () => {
    const input = { tagName: "INPUT", isContentEditable: false };
    expect(press("e", input)).toBeNull();
    expect(press("Enter", { tagName: "TEXTAREA", isContentEditable: false })).toBeNull();
    expect(press("Escape", input)).toBe("cancel");
  });
  it("leaves Enter to a focused button and ignores key combinations", () => {
    expect(press("Enter", { tagName: "BUTTON", isContentEditable: false })).toBeNull();
    expect(press("j", { tagName: "BUTTON", isContentEditable: false })).toBe("next");
    expect(press("f", null, { ctrlKey: true })).toBeNull();
  });
});

describe("moving between fields", () => {
  const paths = ["a", "b", "c", "d"];
  it("finds the next field that still needs a decision, wrapping once", () => {
    const undecided = new Set(["a", "d"]);
    expect(nextWhere(paths, "a", (path) => undecided.has(path))).toBe("d");
    expect(nextWhere(paths, "d", (path) => undecided.has(path))).toBe("a");
    expect(nextWhere(paths, "b", () => false)).toBeNull();
    expect(nextWhere(paths, null, (path) => undecided.has(path))).toBe("a");
  });
  it("moves one up or down and stops at the ends", () => {
    expect(neighbour(paths, "b", 1)).toBe("c");
    expect(neighbour(paths, "a", -1)).toBe("a");
    expect(neighbour(paths, "d", 1)).toBe("d");
    expect(neighbour(paths, null, 1)).toBe("a");
    expect(neighbour([], null, 1)).toBeNull();
  });
});
