import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/browser",
  testMatch: "**/*.spec.ts",
  outputDir: "./node_modules/.cache/zone-browser-results",
  fullyParallel: true,
  workers: 2,
  retries: 0,
  reporter: [["list"], ["json", { outputFile: "node_modules/.cache/zone-browser-report.json" }]],
  use: {
    browserName: "chromium",
    // Installed Chrome by default; CI may set PLAYWRIGHT_CHANNEL=chromium
    // after running `npx playwright install chromium`.
    channel: process.env.PLAYWRIGHT_CHANNEL ?? "chrome",
    headless: true,
    baseURL: "http://127.0.0.1:4178",
    viewport: { width: 800, height: 600 },
  },
  projects: [
    { name: "chrome-dpr-1", use: { deviceScaleFactor: 1 } },
    { name: "chrome-dpr-2", use: { deviceScaleFactor: 2 } },
  ],
  webServer: {
    command: "npm run test:browser:serve",
    url: "http://127.0.0.1:4178",
    reuseExistingServer: false,
    timeout: 30_000,
  },
});
