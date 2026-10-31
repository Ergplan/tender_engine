import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// Served behind Caddy on https://<static-ip>/; the API is the same origin under /api. On a
// developer's machine (`make local`) Caddy serves plain HTTP on 8080, and the live-reload
// socket follows it (infra/local/compose.yml sets the two variables).
const hmrPort = Number(process.env.VITE_HMR_CLIENT_PORT ?? 443);
const hmrProtocol = process.env.VITE_HMR_PROTOCOL ?? "wss";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    port: 5173,
    strictPort: true,
    allowedHosts: true,
    hmr: { clientPort: hmrPort, protocol: hmrProtocol },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test-setup.ts"],
    // The browser tests in e2e/ are Playwright's, run by `make test-ui`.
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
