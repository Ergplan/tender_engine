import { describe, expect, it } from "vitest";

import { minutesLeft } from "./pace";

const at = (...seconds: number[]) => seconds.map((second) => second * 1000);

describe("minutesLeft", () => {
  it("says nothing before five decisions, or when nothing is left", () => {
    expect(minutesLeft(at(0, 20, 40, 60), 50)).toBeNull();
    expect(minutesLeft(at(0, 20, 40, 60, 80), 0)).toBeNull();
  });
  it("multiplies the median gap by the fields left", () => {
    expect(minutesLeft(at(0, 30, 60, 90, 120), 40)).toBe(20);
    expect(minutesLeft(at(0, 10, 20, 30, 40), 3)).toBe(1);
  });
  it("is not stretched by one long pause", () => {
    expect(minutesLeft(at(0, 30, 60, 1260, 1290, 1320), 40)).toBe(20);
  });
});
