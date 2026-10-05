// A whole review through the browser, on the seeded tender: open the link, decide fields
// by keyboard and mouse, follow evidence into the PDF, complete, read the snapshot.
import { expect, type Page, test } from "@playwright/test";

const TOKEN = "e2e-review-token-0000000000000001";
const REPLACED = "e2e-review-token-0000000000000002";
const DEADLINE = "core.key_dates.bid_submission_deadline";
const PREBID = "core.key_dates.pre_bid_meeting_date";
const EMD = "core.guarantees.emd_per_mw_inr";
const NUMBER = "core.identity.tender_number";

const card = (page: Page, path: string) => page.locator(`[data-field="${path}"]`);
const api = (page: Page, path: string) =>
  page.request.get(`/api/v1${path}`, { headers: { "X-Review-Token": TOKEN } });

test.describe.configure({ mode: "serial" });

test("a link that was replaced, or is not a link, says so in plain words", async ({ page }) => {
  await page.goto(`/review/${REPLACED}`);
  await expect(page.getByRole("alert")).toContainText("replaced by a newer one");
  await page.goto("/review/not-a-real-token-000000000000000");
  await expect(page.getByRole("alert")).toContainText("not valid");
  await page.goto("/");
  await expect(page.getByRole("alert")).toContainText("Open the review link");
  expect((await page.request.get("/api/v1/tenders")).status()).toBe(401);
});

test("the link opens straight into the tender, laid out for a 1366x768 laptop", async ({ page, browser }) => {
  // The first visit after a change makes the dev server compile the screen; a reviewer
  // meets a server that has done so. Timed: a browser with nothing cached, a warm server.
  await page.goto(`/review/${TOKEN}`);
  await expect(page.getByTestId("tender-title")).toContainText("600 MW solar PV projects");
  const context = await browser.newContext({ viewport: { width: 1366, height: 768 } });
  const fresh = await context.newPage();
  const started = Date.now();
  await fresh.goto(`/review/${TOKEN}`);
  await fresh.getByTestId("tender-title").waitFor();
  const painted = Date.now() - started;
  await fresh.waitForFunction(() => {
    const image = document.querySelector<HTMLImageElement>('[data-testid="pdf-page"] img');
    return !!image && image.complete && image.naturalWidth > 0;
  });
  const firstPage = Date.now() - started;
  await context.close();
  // Logged here; the bar (2 s and 3 s) is checked on the deployed app with a real tender
  // by real-load.spec.ts, because this stack has only just been started when the suite runs.
  console.log(`first meaningful paint ${painted} ms, first PDF page ${firstPage} ms`);
  expect(firstPage).toBeLessThan(10_000);

  await expect(page.getByTestId("reviewer-name")).toHaveText("Asha Rao");
  await expect(page.getByTestId("progress")).toContainText("0 of");
  await expect(page.getByTestId("complete-review")).toBeDisabled();
  const sections = await page.getByTestId("section").evaluateAll((all) =>
    all.map((section) => (section as HTMLElement).dataset.section),
  );
  expect(sections.slice(0, 4)).toEqual(["summary", "identity_and_scope", "key_dates", "eligibility"]);
  // Two panes side by side, 44% and 56%, and nothing to scroll sideways.
  const data = await page.getByTestId("data-pane").boundingBox();
  const pdf = await page.getByTestId("pdf-pane").boundingBox();
  expect(Math.round((data!.width / 1366) * 100)).toBe(44);
  expect(pdf!.x).toBeGreaterThan(data!.x + data!.width);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await expect(page.getByText(/approve all/i)).toHaveCount(0);
});

test("an evidence chip scrolls the PDF to its page and highlights the quoted text", async ({ page }) => {
  await page.goto(`/review/${TOKEN}`);
  await expect(page.getByTestId("page-indicator")).toHaveAttribute("data-page", "1");
  await card(page, EMD).getByTestId("evidence-chip").first().click();
  await expect(page.getByTestId("page-indicator")).toHaveAttribute("data-page", "3");
  await expect(page.getByTestId("evidence-pulse")).toBeAttached();
  const box = await page.getByTestId("evidence-pulse").boundingBox();
  const scroller = await page.getByTestId("pdf-scroller").boundingBox();
  expect(box!.y).toBeGreaterThan(scroller!.y);
  expect(box!.y + box!.height).toBeLessThan(scroller!.y + scroller!.height);
  // Focusing the field keeps its evidence marked.
  await card(page, EMD).click();
  await expect(page.getByTestId("evidence-highlight")).toHaveCount(1);
  // The text under the highlight is real, selectable text.
  await expect(page.locator('[data-page-no="3"] [data-testid="text-layer"]')).toContainText("Earnest Money Deposit");

  // The amended deadline shows the amendment, tagged, and its chip opens that document.
  await expect(card(page, DEADLINE).getByTestId("version-tag")).toHaveText("v2 amendment");
  await card(page, DEADLINE).click();
  await expect(page.getByTestId("version-select")).toContainText("amendment-01.pdf");
  await expect(page.getByTestId("page-indicator")).toContainText("Page 1 of 1");

  // Search and contents work on the document shown.
  await page.getByTestId("version-select").selectOption({ label: "v1 · rfs.pdf" });
  await page.getByTestId("pdf-search").fill("performance bank guarantee");
  await page.getByTestId("pdf-search").press("Enter");
  await expect(page.getByTestId("search-count")).toContainText("1/");
  await expect(page.getByTestId("page-indicator")).toHaveAttribute("data-page", "3");
  await expect(page.getByTestId("search-hit").first()).toBeAttached();
});

const SUMMARY = "core.summary.plain_english_summary";

/** WCAG contrast ratio of an element's text against the first opaque background behind it. */
async function contrast(page: Page, selector: string): Promise<number> {
  return page.locator(selector).first().evaluate((element) => {
    const parse = (color: string) => {
      const parts = color.match(/[\d.]+/g)!.map(Number);
      return { rgb: parts.slice(0, 3), alpha: parts.length > 3 ? parts[3] : 1 };
    };
    const luminance = (rgb: number[]) => {
      const [r, g, b] = rgb.map((channel) => {
        const value = channel / 255;
        return value <= 0.03928 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
      });
      return 0.2126 * r + 0.7152 * g + 0.0722 * b;
    };
    const text = parse(getComputedStyle(element).color).rgb;
    let surface = [255, 255, 255];
    for (let node: Element | null = element; node; node = node.parentElement) {
      const background = parse(getComputedStyle(node).backgroundColor);
      if (background.alpha > 0.99) {
        surface = background.rgb;
        break;
      }
    }
    const [light, dark] = [luminance(text), luminance(surface)].sort((a, b) => b - a);
    return (light + 0.05) / (dark + 0.05);
  });
}

for (const scheme of ["light", "dark"] as const) {
  test(`what is typed can be read in a ${scheme} system theme`, async ({ page }) => {
    await page.emulateMedia({ colorScheme: scheme });
    await page.goto(`/review/${TOKEN}`);
    // The edit panel of a long text: a textarea, the evidence boxes and the note.
    await card(page, SUMMARY).getByTestId("edit").click();
    const form = `[data-field="${SUMMARY}"] form`;
    await expect(page.locator(`${form} textarea`)).toBeVisible();
    for (const selector of [`${form} textarea`, `${form} [data-testid="evidence-page"]`, `${form} [data-testid="evidence-quote"]`, `${form} input[aria-label="Note"]`]) {
      expect(await contrast(page, selector), `${selector} in ${scheme}`).toBeGreaterThanOrEqual(7);
    }
    await page.keyboard.press("Escape");
    // A date, a flag note, the document search and the version selector.
    await card(page, DEADLINE).getByTestId("edit").click();
    expect(await contrast(page, `[data-field="${DEADLINE}"] [data-testid="edit-input"]`)).toBeGreaterThanOrEqual(7);
    await page.keyboard.press("Escape");
    await card(page, EMD).getByTestId("flag").click();
    expect(await contrast(page, '[data-testid="flag-note"]')).toBeGreaterThanOrEqual(7);
    await page.keyboard.press("Escape");
    expect(await contrast(page, '[data-testid="pdf-search"]')).toBeGreaterThanOrEqual(7);
    expect(await contrast(page, '[data-testid="version-select"]')).toBeGreaterThanOrEqual(7);
    // The text a reviewer reads, too.
    expect(await contrast(page, `[data-field="${EMD}"] [data-testid="field-value"]`)).toBeGreaterThanOrEqual(7);
  });
}

test("the guide is open on the first visit and stays as the reviewer leaves it", async ({ page }) => {
  await page.goto(`/review/${TOKEN}`);
  const guide = page.getByTestId("guide");
  await expect(guide).toHaveAttribute("data-open", "yes");
  await expect(guide).toContainText("become the canonical record");
  await expect(guide).toContainText("That is a correct answer, not a gap");
  await expect(guide).toContainText("not a measure of whether the value is correct");
  // Open, it still leaves the fields and the document on a 768-pixel-high screen.
  const box = await guide.boundingBox();
  expect(box!.height).toBeLessThan(230);
  await expect(page.getByTestId("field-card").first()).toBeVisible();
  await page.getByTestId("guide-toggle").click();
  await expect(guide).toHaveAttribute("data-open", "no");
  await page.reload();
  await expect(page.getByTestId("guide")).toHaveAttribute("data-open", "no");
});

test("numbered evidence: each sentence of the summary shows its own passage", async ({ page }) => {
  await page.goto(`/review/${TOKEN}`);
  const summary = card(page, SUMMARY);
  await expect(summary.getByTestId("confidence-caption")).toHaveText("model confidence");
  // Written from the record as amended: the deadline's passage is in the amendment (its
  // page 1), the other two in the RfS.
  await expect(summary.getByTestId("evidence-chip")).toHaveText(["1p. 1", "2p. 1", "3p. 3"]);
  await expect(summary.getByTestId("evidence-marker")).toHaveText(["1", "2", "3"]);
  await expect(summary.getByTestId("field-value")).not.toContainText("[1]");
  // The marker after the third sentence shows the third quote, on page 3, and only it.
  await summary.getByTestId("evidence-marker").nth(2).click();
  await expect(page.getByTestId("page-indicator")).toHaveAttribute("data-page", "3");
  await expect(summary.getByTestId("evidence-chip").nth(2)).toHaveAttribute("data-active", "yes");
  await expect(page.getByTestId("evidence-highlight")).toHaveCount(1);
  await expect(page.getByTestId("evidence-highlight-dim")).toHaveCount(1);
  // The sentence on the timeline opens the amendment, where the deadline field's quote is.
  await summary.getByTestId("evidence-marker").nth(1).click();
  await expect(page.getByTestId("page-indicator")).toContainText("Page 1 of 1");
  await expect(summary.getByTestId("evidence-chip").nth(1)).toHaveAttribute("data-active", "yes");
  await expect(page.locator('[data-page-no="1"] [data-testid="text-layer"]')).toContainText("extended to 15.04.2026");
  await summary.getByTestId("evidence-chip").nth(0).click();
  await expect(page.getByTestId("page-indicator")).toHaveAttribute("data-page", "1");
  await expect(summary.getByTestId("evidence-chip").nth(0)).toHaveAttribute("data-active", "yes");
  // The header counts what is left; the section says where to look first.
  await expect(page.getByTestId("remaining")).toContainText("to go");
  // The summary is written from the fields: its third passage is the EMD field's own.
  await expect(summary.getByTestId("rationale")).toContainText("Written from the extracted fields");
  await expect(summary.getByTestId("rationale")).toContainText("[3] EMD per MW");
  await expect(summary.getByTestId("field-value")).toContainText("Eligibility: The record does not state this.");
});

test("approve with Enter, edit a date, mark not in document, flag", async ({ page }) => {
  await page.goto(`/review/${TOKEN}`);

  // Enter approves the focused field, saves at once and moves to the next undecided one.
  await card(page, NUMBER).click();
  await page.keyboard.press("Enter");
  await expect(card(page, NUMBER)).toHaveAttribute("data-decided", "yes");
  await expect(card(page, NUMBER).getByTestId("decision")).toContainText("Approved · Asha Rao");
  await expect(card(page, NUMBER)).toHaveAttribute("data-focused", "no");
  await expect(page.locator('[data-focused="yes"]')).toHaveCount(1);
  await expect(page.getByTestId("progress")).toContainText("1 of");

  // Edit a date: a date input, typed to the field.
  await card(page, DEADLINE).getByTestId("edit").click();
  const input = card(page, DEADLINE).getByTestId("edit-input");
  await expect(input).toHaveAttribute("type", "date");
  await expect(input).toHaveValue("2026-04-15");
  await input.fill("2026-04-16");
  await card(page, DEADLINE).getByTestId("edit-save").click();
  await expect(card(page, DEADLINE).getByTestId("decision")).toContainText("Edited to 16 Apr 2026");

  // Not in document, by key.
  await card(page, PREBID).click();
  await page.keyboard.press("n");
  await expect(card(page, PREBID).getByTestId("decision")).toContainText("Not in document");

  // Flag with a note: recorded, not counted as decided.
  await card(page, EMD).click();
  await page.keyboard.press("f");
  await card(page, EMD).getByTestId("flag-note").fill("check against the BIS");
  await card(page, EMD).getByTestId("flag-save").click();
  await expect(card(page, EMD).getByTestId("decision")).toContainText("Flagged: check against the BIS");
  await expect(card(page, EMD)).toHaveAttribute("data-decided", "no");

  // Nothing is held in the browser: a reload shows the same decisions.
  await page.reload();
  await expect(card(page, DEADLINE).getByTestId("decision")).toContainText("Edited to 16 Apr 2026");
  await expect(page.getByTestId("progress")).toContainText("3 of");
  const view = await (await api(page, `/tenders/${await tenderId(page)}/view`)).json();
  const deadline = view.fields.find((field: { field_path: string }) => field.field_path === DEADLINE);
  expect(deadline.value).toBe("2026-04-16");
  expect(deadline.version_no).toBe(2);
});

async function tenderId(page: Page): Promise<string> {
  const session = await (await api(page, "/review-session")).json();
  return session.tender_id as string;
}

test("complete the review by keyboard; the snapshot holds the final values", async ({ page }) => {
  // Some eighty decisions one after another: minutes on a busy two-core machine.
  test.setTimeout(300_000);
  await page.goto(`/review/${TOKEN}`);
  const complete = page.getByTestId("complete-review");
  await expect(complete).toBeDisabled();
  await page.keyboard.press("j");
  // Decide every field that is still open: approve what can be approved, otherwise mark
  // it not in document. Enter and N both move on to the next undecided field.
  for (let step = 0; step < 200; step += 1) {
    const focused = page.locator('[data-focused="yes"]');
    if ((await focused.count()) === 0 || (await focused.getAttribute("data-decided")) === "yes") break;
    const path = await focused.getAttribute("data-field");
    const canApprove = await focused.getByTestId("approve").isEnabled();
    await page.keyboard.press(canApprove ? "Enter" : "n");
    await expect(page.locator(`[data-field="${path}"]`)).toHaveAttribute("data-decided", "yes");
  }
  await expect(complete).toBeEnabled();
  await complete.click();
  await expect(page.getByRole("dialog")).toContainText("no longer changed");
  await page.getByTestId("confirm-complete").click();

  await expect(page).toHaveURL(new RegExp(`/review/${TOKEN}/summary$`));
  await expect(page.getByTestId("summary")).toContainText("Review completed");
  await expect(page.locator(`[data-testid="summary-row"][data-field="${DEADLINE}"]`)).toContainText("16 Apr 2026");
  await expect(page.getByTestId("download-json")).toBeEnabled();
  const download = page.waitForEvent("download");
  await page.getByTestId("download-json").click();
  expect((await download).suggestedFilename()).toMatch(/^review-.*\.json$/);

  // The snapshot endpoint returns the final values.
  const id = await tenderId(page);
  const snapshot = await (await api(page, `/tenders/${id}/snapshot`)).json();
  const fields = Object.fromEntries(
    snapshot.snapshot.view.fields.map((field: { field_path: string }) => [field.field_path, field]),
  );
  expect(snapshot.reviewer).toBe("Asha Rao");
  expect(fields[DEADLINE].value).toBe("2026-04-16");
  expect(fields[DEADLINE].version_no).toBe(2);
  expect(fields[NUMBER].value).toBe("ACME/RE/2026/007");
  expect(fields[PREBID].decided).toBe(true);
  expect(fields[PREBID].value).toBeNull();
  expect((await (await api(page, `/tenders/${id}`)).json()).status).toBe("reviewed");

  // Afterwards the link opens the review read-only, and the API refuses a change.
  await page.goto(`/review/${TOKEN}`);
  await expect(page.getByText("Completed · read-only")).toBeVisible();
  await expect(page.getByTestId("approve")).toHaveCount(0);
  const late = await page.request.post("/api/v1/approvals", {
    headers: { "X-Review-Token": TOKEN },
    data: { candidate_id: "0".repeat(32), decision: "approved" },
  });
  expect(late.status()).toBe(409);
});
