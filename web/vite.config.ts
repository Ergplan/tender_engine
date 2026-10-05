import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// Served behind Caddy on https://<static-ip>/; the API is the same origin under /api.
export default defineConfig({
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    port: 5173,
    strictPort: true,
    allowedHosts: true,
    hmr: { clientPort: 443, protocol: "wss" },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test-setup.ts"],
    // The browser tests in e2e/ are Playwright's, run by `make test-ui`.
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
