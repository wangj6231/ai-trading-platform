import { defineConfig } from "@playwright/test";

// Opt-in diagnostics: requires an already running real backend on port 8000.
// The normal proxy default and its original 10-second deadline are retained.
export default defineConfig({
  testDir: "./tests/live-browser", workers: 1, retries: 0, timeout: 240_000,
  outputDir: "./node_modules/.cache/async-live-results", reporter: "list",
  use: { baseURL: "http://127.0.0.1:3001", channel: "chrome", headless: true },
  webServer: { command: "npm run start -- --hostname 127.0.0.1 --port 3001",
    url: "http://127.0.0.1:3001", reuseExistingServer: false, timeout: 30_000 },
});
