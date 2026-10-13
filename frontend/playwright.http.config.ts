import { defineConfig } from "@playwright/test";
const port = process.env.HTTP_BROWSER_PORT ?? "3013";
export default defineConfig({
  testDir: "./tests/http-browser", outputDir: "./node_modules/.cache/http-browser-results", reporter: "list", workers: 1, retries: 0, timeout: 60_000,
  use: { baseURL: `http://127.0.0.1:${port}`, channel: "chrome", headless: true },
  webServer: { command: "node tests/http-browser/start-owned-runtime.mjs", url: `http://127.0.0.1:${port}/paper-trading`, reuseExistingServer: false, timeout: 120_000 },
});
