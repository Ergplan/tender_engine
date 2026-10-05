import { defineConfig, devices } from "@playwright/test";

// Run by `make test-ui` inside the Playwright container, against the seeded test stack.
export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  outputDir: "../.ci/playwright",
  use: {
    baseURL: process.env.BASE_URL ?? "http://caddy-e2e:8080",
    // The reviewer's laptop.
    viewport: { width: 1366, height: 768 },
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    ignoreHTTPSErrors: true,
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1366, height: 768 } } }],
});
