import { defineConfig } from "@playwright/test";

// Actual production Next.js page and actual Lightweight Charts; only HTTP test evidence is isolated.
export default defineConfig({
  testDir: "./tests/product-browser",
  outputDir: "./node_modules/.cache/product-browser-results",
  reporter: "list", workers: 1, retries: 0,
  use: { baseURL: "http://127.0.0.1:3001", channel: process.env.PLAYWRIGHT_CHANNEL ?? "chrome", headless: true },
  webServer: { command: "npm run start -- --hostname 127.0.0.1 --port 3001", url: "http://127.0.0.1:3001", reuseExistingServer: true, timeout: 30_000 },
});
