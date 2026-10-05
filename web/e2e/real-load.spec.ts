// How fast a real tender opens on the deployed app. Reads only; decides nothing.
// Skipped unless REAL_REVIEW_URL names a live review link:
//   docker compose --profile e2e run --rm -T --no-deps -e REAL_REVIEW_URL=<link> \
//     playwright npx playwright test real-load
import { expect, test } from "@playwright/test";

const url = process.env.REAL_REVIEW_URL;

test("a real tender: first paint under 2 s, first PDF page under 3 s", async ({ browser }) => {
  test.skip(!url, "set REAL_REVIEW_URL to a live review link");
  // One visit first, not timed: after a change the dev server compiles the screen on the
  // first request. Then a browser with nothing cached.
  const warm = await browser.newContext({ ignoreHTTPSErrors: true });
  const first = await warm.newPage();
  const cold = Date.now();
  await first.goto(url!);
  await first.getByTestId("tender-title").waitFor();
  console.log(`first visit after the server started: ${Date.now() - cold} ms to first paint`);
  await warm.close();
  const context = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1366, height: 768 } });
  const page = await context.newPage();
  const started = Date.now();
  await page.goto(url!);
  await page.getByTestId("tender-title").waitFor();
  const painted = Date.now() - started;
  await page.waitForFunction(() => {
    const image = document.querySelector<HTMLImageElement>('[data-testid="pdf-page"] img');
    return !!image && image.complete && image.naturalWidth > 0;
  });
  const firstPage = Date.now() - started;
  const pages = await page.getByTestId("pdf-page").count();
  const fields = await page.getByTestId("field-card").count();
  console.log(
    `${await page.getByTestId("tender-title").textContent()}\n` +
      `fields ${fields}, pages of the first document ${pages}\n` +
      `first meaningful paint ${painted} ms, first PDF page ${firstPage} ms`,
  );
  expect(painted).toBeLessThan(2000);
  expect(firstPage).toBeLessThan(3000);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  // The selectable text arrives after the image, from pdf.js reading the PDF in ranges.
  await expect(page.locator('[data-page-no="1"] [data-testid="text-layer"] span').first()).toBeAttached({ timeout: 20_000 });
  console.log(`text layer of page 1 after ${Date.now() - started} ms`);
});
