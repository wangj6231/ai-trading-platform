import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/e2e-paper",
  outputDir: "./node_modules/.cache/paper-e2e-results",
  reporter: "list", workers: 1, retries: 0, timeout: 240_000,
  use: { baseURL: "http://127.0.0.1:3014", channel: "chrome", headless: true },
  projects: [
    { name: "desktop", use: { viewport: { width: 1440, height: 950 } } },
    { name: "mobile", use: { viewport: { width: 390, height: 844 } } },
  ],
});
