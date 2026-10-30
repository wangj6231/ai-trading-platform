import { defineConfig } from "@playwright/test";
const port = process.env.PAPER_BROWSER_PORT ?? "3002";
export default defineConfig({
  testDir: "./tests/paper-browser", outputDir: "./node_modules/.cache/paper-browser-results", reporter: "list", workers: 1, retries: 0,
  use: { baseURL: `http://127.0.0.1:${port}`, channel: process.env.PLAYWRIGHT_CHANNEL ?? "chrome", headless: true },
  webServer: { command: `npm run start -- --hostname 127.0.0.1 --port ${port}`, url: `http://127.0.0.1:${port}`, reuseExistingServer: !process.env.PAPER_BROWSER_PORT, timeout: 30_000 },
});
