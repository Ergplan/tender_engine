import { describe, expect, it } from "vitest";

import {
  confidenceBand,
  formatDate,
  formatRupees,
  formatValue,
  fromEditText,
  toEditText,
  toIsoDate,
  unitSuffix,
} from "./format";

describe("dates", () => {
  it("reads ISO and day-first dates and shows them as 12 Mar 2026", () => {
    expect(formatDate("2026-03-12")).toBe("12 Mar 2026");
    expect(formatDate("12.03.2026")).toBe("12 Mar 2026");
    expect(formatDate("5/4/2026")).toBe("5 Apr 2026");
    expect(toIsoDate("31.02.2026")).toBeNull();
  });
  it("leaves text that is not a date as it is", () => {
    expect(formatDate("as per NIT")).toBe("as per NIT");
  });
});

describe("money", () => {
  it("writes rupees in lakh and crore", () => {
    expect(formatRupees(2500000)).toBe("₹ 25 lakh");
    expect(formatRupees(928000)).toBe("₹ 9.28 lakh");
    expect(formatRupees(120000000)).toBe("₹ 12 crore");
    expect(formatRupees(59000)).toBe("₹ 59,000");
  });
  it("adds the per-unit of the field", () => {
    expect(formatValue(2500000, "money_inr", "INR per MW")).toBe("₹ 25 lakh/MW");
    expect(formatValue(1000, "money_inr", "INR per MW per day")).toBe("₹ 1,000/MW/day");
    expect(formatValue(3.5, "money_inr", "INR per kWh")).toBe("₹ 3.5/kWh");
    expect(formatValue("928000", "money_inr", "INR")).toBe("₹ 9.28 lakh");
    expect(unitSuffix("money_inr", "INR per MW")).toBe("₹/MW");
  });
});

describe("other value types", () => {
  it("shows percent with one decimal and numbers with their unit", () => {
    expect(formatValue(19, "percent", "percent")).toBe("19.0%");
    expect(formatValue(600, "mw", "MW")).toBe("600 MW");
    expect(formatValue(18, "duration_months", "months")).toBe("18 months");
    expect(formatValue(25, "int", "years")).toBe("25 years");
    expect(formatValue(1200.5, "decimal", null)).toBe("1,200.5");
  });
  it("shows yes/no, choices, lists and records in words", () => {
    expect(formatValue(true, "bool", null)).toBe("Yes");
    expect(formatValue(false, "bool", null)).toBe("No");
    expect(formatValue("ppa_signing", "enum", null)).toBe("Ppa signing");
    expect(formatValue(["a", "b"], "list_text", null)).toBe("a; b");
    expect(formatValue([{ name: "Line 1", kv: "400" }], "record_list", null)).toBe("name: Line 1 | kv: 400");
    expect(formatValue(null, "text", null)).toBe("");
  });
});

describe("confidence", () => {
  it("is green from 0.8, amber from 0.5 and red below", () => {
    expect([0.95, 0.8, 0.79, 0.5, 0.49, 0].map(confidenceBand)).toEqual([
      "high", "high", "medium", "medium", "low", "low",
    ]);
  });
});

describe("editing", () => {
  it("starts from the value in the form its input takes", () => {
    expect(toEditText("12.03.2026", "date")).toBe("2026-03-12");
    expect(toEditText(928000, "money_inr")).toBe("928000");
    expect(toEditText(true, "bool")).toBe("yes");
    expect(toEditText(["a", "b"], "list_text")).toBe("a\nb");
    expect(toEditText(null, "text")).toBe("");
  });
  it("sends the value in the type of the field", () => {
    expect(fromEditText("2026-03-31", "date")).toBe("2026-03-31");
    expect(fromEditText("25,00,000", "money_inr")).toBe(2500000);
    expect(fromEditText("no", "bool")).toBe(false);
    expect(fromEditText(" a \n\n b ", "list_text")).toEqual(["a", "b"]);
    expect(fromEditText("  ", "text")).toBeNull();
  });
});
