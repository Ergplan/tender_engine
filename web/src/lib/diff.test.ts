import { describe, expect, it } from "vitest";

import { changedShare, numericDelta, wordDiff } from "./diff";

describe("wordDiff", () => {
  it("marks the words a later version removed and added, and nothing else", () => {
    const parts = wordDiff(
      "The CfDAs shall be valid for a period of 12 years from the SCD.",
      "The CfDAs shall be valid for a period of 15 years from the SCD.",
    );
    expect(parts.map((p) => [p.kind, p.text.trim()])).toEqual([
      ["same", "The CfDAs shall be valid for a period of"],
      ["removed", "12"],
      ["added", "15"],
      ["same", "years from the SCD."],
    ]);
  });

  it("keeps a rewritten clause readable: the shared tail stays shared", () => {
    const parts = wordDiff("documents 15 days prior to the trial run", "documents 7 working days prior to the trial run");
    expect(parts.filter((p) => p.kind !== "same").map((p) => [p.kind, p.text.trim()])).toEqual([
      ["removed", "15"],
      ["added", "7 working"],
    ]);
  });

  it("handles an empty side", () => {
    expect(wordDiff("", "new text")).toEqual([{ kind: "added", text: "new text" }]);
    expect(wordDiff("old", "")).toEqual([{ kind: "removed", text: "old" }]);
    expect(wordDiff("", "")).toEqual([]);
  });
});

describe("changedShare", () => {
  it("is 0 for identical texts and 1 when nothing is shared", () => {
    expect(changedShare(wordDiff("a b c", "a b c"))).toBe(0);
    expect(changedShare(wordDiff("a b", "c d"))).toBe(1);
    expect(changedShare(wordDiff("a b c d", "a b c e"))).toBeCloseTo(0.4);
  });
});

describe("numericDelta", () => {
  it("gives the change with its share", () => {
    expect(numericDelta(12, 15)).toBe("+3 (+25%)");
    expect(numericDelta("5.8", 5.5)).toBe("-0.3 (-5.2%)");
    expect(numericDelta(0, 4)).toBe("+4");
  });
  it("is null when either side is not a number", () => {
    expect(numericDelta("twelve", 15)).toBeNull();
    expect(numericDelta(null, 15)).toBeNull();
    expect(numericDelta(12, "")).toBeNull();
  });
});
