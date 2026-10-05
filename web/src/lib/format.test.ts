import { describe, expect, it } from "vitest";

import {
  confidenceBand,
  paragraphs,
  stripMarkers,
  formatDate,
  formatKey,
  recordFromEdit,
  recordOf,
  recordsOf,
  recordToEdit,
  type KeyDef,
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

describe("long text with evidence markers", () => {
  const text = "What is procured: SECI invites bids for 600 MW. [1] It is solar. [2][3]\n\nLocation: Anywhere in India. [4]\n\nNo heading here.";
  it("is cut into paragraphs with their headings and markers", () => {
    const [first, second, third] = paragraphs(text);
    expect(first.heading).toBe("What is procured");
    expect(first.pieces).toEqual([
      { text: "SECI invites bids for 600 MW. " },
      { marker: 1 },
      { text: " It is solar. " },
      { marker: 2 },
      { marker: 3 },
    ]);
    expect(second).toEqual({ heading: "Location", pieces: [{ text: "Anywhere in India. " }, { marker: 4 }] });
    expect(third).toEqual({ heading: null, pieces: [{ text: "No heading here." }] });
  });
  it("is shown without markers where it is only read", () => {
    expect(stripMarkers("It is solar. [2][3] Next.")).toBe("It is solar. Next.");
    expect(formatValue("Bids are due. [1]", "long_text", null)).toBe("Bids are due.");
    expect(formatValue("Clause [1] of the RfS", "text", null)).toBe("Clause [1] of the RfS");
  });
});

describe("structured values", () => {
  const keys: KeyDef[] = [
    { name: "basis", label: "Stated as", value_type: "enum", enum_values: ["per_mw", "per_component"] },
    { name: "rate_inr_per_mw", label: "Rate per MW", value_type: "money_inr", unit: "INR per MW" },
    { name: "revolving", label: "Revolving", value_type: "bool" },
    {
      name: "components",
      label: "Rates per component",
      value_type: "list",
      keys: [
        { name: "component", label: "Component", value_type: "text" },
        { name: "rate_inr", label: "Rate", value_type: "money_inr" },
      ],
    },
  ];

  it("reads a record from the model's lines and from a stored record", () => {
    const lines = [
      "Basis: per_component",
      "revolving: yes",
      "rate_inr_per_mw: null",
      "components: component=solar; rate_inr=928000",
      "components: component=wind; rate_inr=1264000",
    ];
    const record = recordOf(lines, keys);
    expect(record).toEqual({
      basis: "per_component",
      revolving: "yes",
      components: [
        { component: "solar", rate_inr: "928000" },
        { component: "wind", rate_inr: "1264000" },
      ],
    });
    expect(recordOf({ basis: "per_mw", rate_inr_per_mw: 928000 }, keys)).toEqual({
      basis: "per_mw",
      rate_inr_per_mw: 928000,
    });
    expect(recordOf(null, keys)).toBeNull();
    expect(recordsOf(["name: Line 1 | kv: 400", { name: "Bay", kv: null }])).toEqual([
      { name: "Line 1", kv: "400" },
      { name: "Bay", kv: null },
    ]);
  });

  it("shows a key in its type, and nothing for a key that is not stated", () => {
    expect(formatKey("per_component", keys[0])).toBe("Per component");
    expect(formatKey("928000", keys[1])).toBe(formatRupees(928000));
    expect(formatKey("yes", keys[2])).toBe("Yes");
    expect(formatKey(false, keys[2])).toBe("No");
    expect(formatKey(null, keys[1])).toBeNull();
  });

  it("turns the edit inputs into a record and back", () => {
    const texts = recordToEdit(
      { basis: "per_mw", rate_inr_per_mw: 928000, revolving: true, components: [{ component: "ess", rate_inr: 5 }] },
      keys,
    );
    expect(texts).toEqual({
      basis: "per_mw",
      rate_inr_per_mw: "928000",
      revolving: "yes",
      components: "component=ess; rate_inr=5",
    });
    expect(recordFromEdit({ ...texts, basis: "", components: "component=ess; rate_inr=5\n\n" }, keys)).toEqual({
      rate_inr_per_mw: 928000,
      revolving: true,
      components: [{ component: "ess", rate_inr: "5" }],
    });
    expect(recordFromEdit({ basis: " ", rate_inr_per_mw: "" }, keys)).toBeNull();
  });
});
