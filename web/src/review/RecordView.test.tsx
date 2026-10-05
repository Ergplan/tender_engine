import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { ReviewEntry, ReviewField } from "../api/client";
import { EditForm } from "./EditForm";
import { shownValue } from "./FieldCard";
import { RecordView } from "./RecordView";

const keys = [
  { name: "basis", label: "Stated as", value_type: "enum", enum_values: ["per_mw", "per_component"] },
  { name: "rate_inr_per_mw", label: "Rate per MW", value_type: "money_inr", unit: "INR per MW" },
  { name: "cap_inr", label: "Cap", value_type: "money_inr", unit: "INR" },
  {
    name: "components",
    label: "Rates per component",
    value_type: "list",
    keys: [
      { name: "component", label: "Component", value_type: "text" },
      { name: "rate_inr", label: "Rate", value_type: "money_inr", unit: "INR" },
    ],
  },
];
const field = {
  field_path: "core.guarantees.emd_structured",
  label: "EMD, structured",
  value_type: "record",
  unit: null,
  keys,
} as unknown as ReviewField;
const lines = [
  "basis: per_component",
  "components: component=solar; rate_inr=928000",
  "components: component=wind; rate_inr=1264000",
  "cap_inr: 100000000",
];

function row(name: string): HTMLElement {
  const found = screen.getAllByTestId("record-key").find((node) => node.dataset.key === name);
  if (!found) throw new Error(`no row for ${name}`);
  return found;
}

describe("RecordView", () => {
  it("shows every key with its value and unit, and says which are not stated", () => {
    render(<RecordView field={field} value={lines} />);
    expect(row("basis").textContent).toBe("Stated asPer component");
    expect(row("rate_inr_per_mw").textContent).toBe("Rate per MWnot stated");
    expect(row("cap_inr").textContent).toContain("10 crore");
    const items = within(row("components")).getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(items[0].textContent).toContain("component solar");
    expect(items[0].textContent).toContain("9.28 lakh");
  });

  it("shows a list of records item by item with the keys each states", () => {
    const listed = { ...field, value_type: "record_list" } as ReviewField;
    render(<RecordView field={listed} value={["basis: per_mw | rate_inr_per_mw: 5", { basis: "per_component" }]} />);
    expect(within(screen.getByTestId("record-list")).getAllByTestId("record-key")).toHaveLength(3);
  });
});

describe("EditForm for a record", () => {
  it("edits key by key and sends the record", () => {
    const onSave = vi.fn();
    const entry = {
      state: {
        candidate: {
          id: "c1",
          value: lines,
          document_id: "d1",
          evidence: [{ page_no: 3, quote: "q", char_start: 1, char_end: 2 }],
        },
        approval: null,
      },
    } as unknown as ReviewEntry;
    render(<EditForm field={field} entry={entry} documentName="rfs.pdf" onSave={onSave} onCancel={() => {}} />);
    expect((screen.getByTestId("edit-key-cap_inr") as HTMLInputElement).value).toBe("100000000");
    expect((screen.getByTestId("edit-key-components") as HTMLTextAreaElement).value).toBe(
      "component=solar; rate_inr=928000\ncomponent=wind; rate_inr=1264000",
    );
    fireEvent.change(screen.getByTestId("edit-key-cap_inr"), { target: { value: "" } });
    fireEvent.change(screen.getByTestId("edit-key-rate_inr_per_mw"), { target: { value: "5000" } });
    fireEvent.click(screen.getByTestId("edit-save"));
    expect(onSave).toHaveBeenCalledWith({
      value: {
        basis: "per_component",
        rate_inr_per_mw: 5000,
        components: [
          { component: "solar", rate_inr: "928000" },
          { component: "wind", rate_inr: "1264000" },
        ],
      },
      note: null,
      evidence: null,
    });
  });
});

describe("the value a card draws", () => {
  const entryWith = (approval: object | null) =>
    ({ state: { candidate: { value: lines }, approval } }) as unknown as ReviewEntry;
  const edited = { basis: "per_mw", rate_inr_per_mw: 928000, cap_inr: 100000000, components: null };

  it("is the extracted record until a reviewer edits it, then the reviewer's record", () => {
    expect(shownValue(field, entryWith(null))).toBe(lines);
    expect(shownValue(field, entryWith({ decision: "approved", final_value: edited }))).toBe(lines);
    expect(shownValue(field, entryWith({ decision: "flagged", final_value: null }))).toBe(lines);
    expect(shownValue(field, entryWith({ decision: "edited", final_value: edited }))).toBe(edited);
    render(<RecordView field={field} value={shownValue(field, entryWith({ decision: "edited", final_value: edited }))} />);
    expect(row("rate_inr_per_mw").textContent).toContain("9.28 lakh");
    expect(row("cap_inr").textContent).toContain("10 crore");
    expect(row("components").textContent).toContain("not stated");
  });

  it("stays the extracted value for a scalar field, whose edit is told in the decision line", () => {
    const scalar = { ...field, value_type: "money_inr", keys: null } as unknown as ReviewField;
    const entry = { state: { candidate: { value: 5 }, approval: { decision: "edited", final_value: 6 } } };
    expect(shownValue(scalar, entry as unknown as ReviewEntry)).toBe(5);
    expect(shownValue(scalar, null)).toBeNull();
  });
});
